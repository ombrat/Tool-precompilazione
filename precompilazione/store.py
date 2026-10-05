"""Archivio dei modelli (docx + configurazione) e accesso al database anagrafiche."""
import json
import re
import shutil
import sqlite3
import uuid
from pathlib import Path

DEFAULT_DB = {"path": "anagrafiche.db", "table": "anagrafiche",
              "type_column": "tipo_cliente", "label_column": "denominazione"}
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
CLIENT_TYPES = ["Persona fisica", "Persona giuridica"]
SOURCES = ["db", "text", "longtext"]


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.models = self.root / "modelli"
        self.models.mkdir(parents=True, exist_ok=True)
        self.default_db = self.root / DEFAULT_DB["path"]
        if not self.default_db.exists():
            seed_demo_db(self.default_db)

    # --- modelli ---
    def _dir(self, model_id):
        if not re.fullmatch(r"[0-9a-f]{32}", model_id):
            raise KeyError(model_id)
        d = self.models / model_id
        if not d.is_dir():
            raise KeyError(model_id)
        return d

    def docx_path(self, model_id):
        return self._dir(model_id) / "modello.docx"

    def create(self, name, file_storage, fields):
        model_id = uuid.uuid4().hex
        d = self.models / model_id
        d.mkdir()
        file_storage.save(d / "modello.docx")
        cfg = {"name": name, "db": dict(DEFAULT_DB),
               "fields": {f: {"label": f.replace("_", " ").capitalize(),
                              "source": "text", "column": "", "default": ""}
                          for f in fields}}
        self.save_config(model_id, cfg)
        return model_id

    def list(self):
        out = []
        for d in sorted(self.models.iterdir()):
            if (d / "config.json").exists():
                out.append({"id": d.name, "name": self.config(d.name)["name"]})
        return out

    def config(self, model_id):
        return json.loads((self._dir(model_id) / "config.json").read_text("utf-8"))

    def save_config(self, model_id, cfg):
        (self.models / model_id / "config.json").write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2), "utf-8")

    def delete(self, model_id):
        shutil.rmtree(self._dir(model_id))

    # --- database ---
    def connect(self, db_cfg):
        path = Path(db_cfg["path"])
        if not path.is_absolute():
            path = self.root / path
        con = sqlite3.connect(path)
        con.row_factory = sqlite3.Row
        return con

    def columns(self, db_cfg):
        table = _ident(db_cfg["table"])
        with self.connect(db_cfg) as con:
            return [r["name"] for r in con.execute(f'PRAGMA table_info("{table}")')]

    def records(self, db_cfg, client_type):
        table, tcol = _ident(db_cfg["table"]), _ident(db_cfg["type_column"])
        with self.connect(db_cfg) as con:
            rows = con.execute(f'SELECT rowid AS _rid, * FROM "{table}" WHERE "{tcol}" = ? '
                               "ORDER BY 2", (client_type,)).fetchall()
        return [dict(r) for r in rows]

    def record(self, db_cfg, rid):
        table = _ident(db_cfg["table"])
        with self.connect(db_cfg) as con:
            row = con.execute(f'SELECT * FROM "{table}" WHERE rowid = ?', (rid,)).fetchone()
        return dict(row) if row else None


def _ident(name):
    if not IDENT.match(name or ""):
        raise ValueError(f"Nome non valido: {name!r}")
    return name


def seed_demo_db(path):
    con = sqlite3.connect(path)
    con.execute("""CREATE TABLE anagrafiche (
        id INTEGER PRIMARY KEY, tipo_cliente TEXT, denominazione TEXT,
        nome TEXT, cognome TEXT, codice_fiscale TEXT, partita_iva TEXT,
        indirizzo TEXT, citta TEXT, email TEXT, pec TEXT, legale_rappresentante TEXT)""")
    con.executemany(
        "INSERT INTO anagrafiche (tipo_cliente, denominazione, nome, cognome, codice_fiscale,"
        " partita_iva, indirizzo, citta, email, pec, legale_rappresentante)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
            ("Persona fisica", "Mario Rossi", "Mario", "Rossi", "RSSMRA80A01H501U", "",
             "Via Roma 1", "Roma", "mario.rossi@example.com", "", ""),
            ("Persona fisica", "Laura Bianchi", "Laura", "Bianchi", "BNCLRA85M41F205Z", "",
             "Via Dante 5", "Milano", "laura.bianchi@example.com", "", ""),
            ("Persona giuridica", "Acme S.r.l.", "", "", "01234567890", "01234567890",
             "Corso Italia 10", "Torino", "info@acme.example", "acme@pec.example",
             "Giulia Verdi"),
        ])
    con.commit()
    con.close()
