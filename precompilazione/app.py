import io
import os
from pathlib import Path

from flask import (Flask, abort, flash, redirect, render_template, request,
                   send_file, url_for)

from .docx_engine import fill_document, find_fields
from .store import CLIENT_TYPES, SOURCES, Store


def create_app(data_dir=None):
    app = Flask(__name__)
    app.secret_key = os.environ.get("PRECOMP_SECRET", "precompilazione-dev")
    app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024
    store = Store(data_dir or os.environ.get("PRECOMP_DATA", Path.cwd() / "data"))

    def model_or_404(model_id):
        try:
            return store.config(model_id)
        except KeyError:
            abort(404)

    @app.get("/")
    def index():
        return render_template("index.html", models=store.list())

    @app.post("/upload")
    def upload():
        f = request.files.get("file")
        if not f or not f.filename.lower().endswith(".docx"):
            flash("Carica un file Word (.docx).")
            return redirect(url_for("index"))
        tmp = store.root / "upload.tmp.docx"
        f.save(tmp)
        try:
            fields = find_fields(tmp)
        except Exception:
            tmp.unlink(missing_ok=True)
            flash("File Word non valido.")
            return redirect(url_for("index"))
        tmp.unlink(missing_ok=True)
        f.stream.seek(0)
        name = request.form.get("name") or Path(f.filename).stem
        model_id = store.create(name, f, fields)
        if not fields:
            flash("Nessun campo {{nome_campo}} trovato nel documento.")
        return redirect(url_for("configure", model_id=model_id))

    @app.route("/modello/<model_id>/configura", methods=["GET", "POST"])
    def configure(model_id):
        cfg = model_or_404(model_id)
        if request.method == "POST":
            form = request.form
            cfg["name"] = form.get("name", cfg["name"]) or cfg["name"]
            for key in ("path", "table", "type_column", "label_column"):
                cfg["db"][key] = form.get(f"db_{key}", cfg["db"][key]).strip() or cfg["db"][key]
            for name, fc in cfg["fields"].items():
                source = form.get(f"source_{name}", fc["source"])
                fc["source"] = source if source in SOURCES else "text"
                fc["label"] = form.get(f"label_{name}", fc["label"]) or name
                fc["column"] = form.get(f"column_{name}", "")
                fc["default"] = form.get(f"default_{name}", "")
            store.save_config(model_id, cfg)
            flash("Configurazione salvata.")
            return redirect(url_for("configure", model_id=model_id))
        try:
            columns = store.columns(cfg["db"])
        except Exception as e:
            columns = []
            flash(f"Database non raggiungibile: {e}")
        return render_template("configure.html", model_id=model_id, cfg=cfg, columns=columns)

    @app.post("/modello/<model_id>/elimina")
    def delete(model_id):
        model_or_404(model_id)
        store.delete(model_id)
        return redirect(url_for("index"))

    @app.route("/modello/<model_id>/precompila", methods=["GET", "POST"])
    def fill(model_id):
        cfg = model_or_404(model_id)
        client_type = request.values.get("tipo_cliente", CLIENT_TYPES[0])
        if client_type not in CLIENT_TYPES:
            client_type = CLIENT_TYPES[0]
        try:
            records = store.records(cfg["db"], client_type)
        except Exception as e:
            records = []
            flash(f"Database non raggiungibile: {e}")
        label_col = cfg["db"]["label_column"]
        selected = request.values.get("anagrafica", "")

        if request.method == "POST" and request.form.get("action") == "genera":
            record = {}
            if selected.isdigit():
                record = store.record(cfg["db"], int(selected)) or {}
            values = {}
            for name, fc in cfg["fields"].items():
                if fc["source"] == "db":
                    v = record.get(fc["column"])
                    v = fc["default"] if v in (None, "") else v
                    values[name] = request.form.get(f"v_{name}", v)
                else:
                    values[name] = request.form.get(f"v_{name}", fc["default"])
            buf = io.BytesIO()
            fill_document(store.docx_path(model_id), buf, values)
            buf.seek(0)
            return send_file(buf, as_attachment=True, download_name=f"{cfg['name']}.docx",
                             mimetype="application/vnd.openxmlformats-officedocument."
                                      "wordprocessingml.document")

        record = {}
        if selected.isdigit():
            record = store.record(cfg["db"], int(selected)) or {}
        values = {}
        for name, fc in cfg["fields"].items():
            if fc["source"] == "db" and record:
                v = record.get(fc["column"])
                values[name] = fc["default"] if v in (None, "") else v
            else:
                values[name] = request.form.get(f"v_{name}", fc["default"])
        return render_template("fill.html", model_id=model_id, cfg=cfg, types=CLIENT_TYPES,
                               client_type=client_type, records=records, selected=selected,
                               label_col=label_col, values=values)

    return app
