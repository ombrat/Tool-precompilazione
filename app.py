import json

import streamlit as st

import core

st.set_page_config(page_title="Precompilazione documenti", layout="wide")


@st.cache_data(show_spinner=False, max_entries=20)
def cached_preview(data, fields_json, values_json):
    return core.preview_pages(data, json.loads(fields_json), json.loads(values_json))


tab_main, tab_db = st.tabs(["Documento", "Database"])

with tab_main:
    up = st.file_uploader("Carica il documento Word (.doc / .docx)", type=["doc", "docx"])
    if up and st.session_state.get("upkey") != (up.name, up.size):
        raw = up.getvalue()
        ext = up.name.rsplit(".", 1)[-1].lower()
        with st.spinner("Lettura del documento..."):
            st.session_state.update(
                doc=core.convert(raw, "doc", "docx") if ext == "doc" else raw,
                fmt=ext, upkey=(up.name, up.size), out=None,
            )

    if up:
        data = st.session_state["doc"]
        fmt = st.session_state["fmt"]
        placeholders = core.find_placeholders(data)
        main_keys, roles = [], {}
        for key in placeholders:
            role = core.split_role(key)[1]
            if role:
                roles.setdefault(role, []).append(key)
            else:
                main_keys.append(key)
        left, right = st.columns([2, 3], gap="large")

        with left:
            st.subheader("Dati")
            ctype = st.radio(
                "Tipo di cliente", list(core.CUSTOMER_TYPES),
                format_func=core.CUSTOMER_TYPES.get, horizontal=True,
            )
            try:
                records = core.db_records(ctype)
                cols = core.db_columns(ctype)
            except Exception as e:
                records, cols = [], []
                st.error(f"Errore database: {e}")
            rec, rid = {}, "none"
            if records:
                idx = st.selectbox(
                    "Anagrafica", range(len(records)),
                    format_func=lambda i: core.record_label(ctype, records[i]),
                )
                rec = records[idx]
                rid = f"{ctype}_{rec.get('id', idx)}"

            mapping = {}
            with st.expander("Collegamento campi / colonne database"):
                for key in main_keys:
                    opts = ["(nessuna)"] + cols
                    g = core.guess_column(key, cols, ctype)
                    sel = st.selectbox(
                        key.replace("_", " "), opts, index=opts.index(g) if g else 0,
                        key=f"map_{ctype}_{key}",
                    )
                    mapping[key] = None if sel == "(nessuna)" else sel

            st.markdown("**Campi del documento**")
            values = {}
            for key in main_keys:
                label = key.replace("_", " ").capitalize()
                col = mapping.get(key)
                init = "" if not col or rec.get(col) is None else str(rec[col])
                k = f"v_{rid}_{key}"
                if key in core.PREDEFINED:
                    values[key] = st.text_input(label, value=init, key=k)
                else:
                    values[key] = st.text_area(label, value=init, height=130, key=k)

            if roles:
                try:
                    people, pcols = core.db_records("fisica"), core.db_columns("fisica")
                except Exception as e:
                    people, pcols = [], []
                    st.error(f"Errore database: {e}")
            for role, keys in roles.items():
                with st.container(border=True):
                    st.markdown(f"**{core.role_label(role)}**")
                    pidx = st.selectbox(
                        "Anagrafica", range(len(people)), index=None, placeholder="Cerca per cognome...",
                        format_func=lambda i: core.record_label("fisica", people[i]), key=f"pers_{role}",
                    )
                    person = people[pidx] if pidx is not None else {}
                    carica = st.selectbox("Carica", core.CARICHE, index=None, placeholder="Seleziona la carica", key=f"car_{role}")
                    if carica == "Altro":
                        carica = st.text_input("Specifica la carica", key=f"caro_{role}")
                    for key in keys:
                        base = core.split_role(key)[0]
                        label = base.replace("_", " ").capitalize()
                        if base == "CARICA":
                            init, k = carica or "", f"v_{key}_{carica}"
                        else:
                            col = core.guess_column(base, pcols, "fisica")
                            init = "" if not col or person.get(col) is None else str(person[col])
                            k = f"v_{key}_{person.get('id', '')}"
                        values[key] = st.text_input(label, value=init, key=k)
            if not placeholders:
                st.warning("Nessun segnaposto trovato (es. [NOME], [COGNOME]).")

            if st.button("Genera documento", type="primary"):
                fields = [{"name": k, "tokens": t} for k, t in placeholders.items()]
                with st.spinner("Generazione..."):
                    out = core.render(data, fields, values)
                    st.session_state["out"] = core.convert(out, "docx", "doc") if fmt == "doc" else out
            if st.session_state.get("out"):
                st.download_button(
                    "Scarica documento compilato", st.session_state["out"],
                    file_name=f"{up.name.rsplit('.', 1)[0]}_compilato.{fmt}",
                    mime="application/msword" if fmt == "doc"
                    else "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )

        with right:
            st.subheader("Anteprima")
            st.caption("Giallo: segnaposto da compilare. Verde: valore inserito.")
            fields = [{"name": k, "tokens": t} for k, t in placeholders.items()]
            with st.container(height=800, border=True):
                with st.spinner("Aggiornamento anteprima..."):
                    for img in cached_preview(data, json.dumps(fields), json.dumps(values)):
                        st.image(img, width="stretch")

with tab_db:
    s = core.load_settings()
    db_up = st.file_uploader("Seleziona il database anagrafiche dal tuo computer (.xls)", type=["xls"])
    if db_up and st.session_state.get("db_upkey") != (db_up.name, db_up.size):
        target = core.BASE / "data" / db_up.name
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(db_up.getvalue())
        s["xls_path"] = str(target)
        core.save_settings(s)
        st.session_state["db_upkey"] = (db_up.name, db_up.size)
        st.rerun()
    st.caption(f"Database in uso: {s['xls_path'] or 'nessun file Excel (database SQL)'}")
    s["xls_path"] = st.text_input("Percorso del file Excel (lascia vuoto per usare il database SQL)", s["xls_path"])
    s["db_url"] = st.text_input("URL database SQL (SQLAlchemy)", s["db_url"])
    for t, tl in core.CUSTOMER_TYPES.items():
        s["tables"][t] = st.text_input(f"Tabella {tl}", s["tables"][t], key=f"tb_{t}")
        s["label_columns"][t] = [
            c.strip() for c in st.text_input(
                f"Colonne etichetta {tl} (separate da virgola)", ", ".join(s["label_columns"][t]), key=f"lc_{t}"
            ).split(",") if c.strip()
        ]
    if st.button("Salva impostazioni"):
        core.save_settings(s)
        st.success("Salvato")
