import json

import streamlit as st

import core

st.set_page_config(page_title="Precompilazione documenti", layout="wide")
st.markdown(
    """
    <style>
    div[class*="st-key-missing-field-"] {
        border: 2px solid #d32f2f !important;
        border-radius: 0.5rem;
        padding: 0.4rem 0.65rem;
        margin-bottom: 0.5rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

_REFRESH_FIELD_WIDGETS = {
    "DATA_EMISSIONE", "DATA_DI_RILASCIO", "DOCUMENTO_DI_IDENTITA", "NUMERO_DOCUMENTO",
    "RAGIONE_SOCIALE", "NOME_SOCIETA", "NOME_DELLA_SOCIETA", "DENOMINAZIONE", "RUOLO",
}


def _field_widget_revision(name):
    return "_v2" if core._norm(name).upper() in _REFRESH_FIELD_WIDGETS else ""


def _render_field_widget(name, label, initial, widget_key, multiline=False):
    current = st.session_state.get(widget_key, initial)
    missing = not str(current or "").strip()
    if not missing and core._norm(name).upper() in {"COMMISSIONE_ANNUALE", "COMMISSIONE_APERTURA"}:
        try:
            core.format_commission_value(name, current)
        except ValueError:
            missing = True
    state_key = "missing-field-" if missing else "filled-field-"
    container_key = state_key + core._norm(widget_key)
    with st.container(key=container_key, border=missing):
        if multiline:
            return st.text_area(label, value=initial, height=130, key=widget_key)
        return st.text_input(label, value=initial, key=widget_key)


def _render_document_field(key, record, mapping, record_id):
    label = key.replace("_", " ").capitalize()
    col = mapping.get(key)
    initial = core.format_field_value(key, record.get(col) if col else None)
    widget_key = f"v_{record_id}_{key}{_field_widget_revision(key)}"
    raw_value = _render_field_widget(
        key, label, initial, widget_key, multiline=core._norm(key).upper() not in core.PREDEFINED
    )
    try:
        return core.format_field_value(key, core.format_commission_value(key, raw_value)), False
    except ValueError as error:
        st.error(f"{label}: {error}")
        return "", True


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
            roles = core.roles_for_customer_type(roles, ctype)
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
                    key_revision = _field_widget_revision(key)
                    sel = st.selectbox(
                        key.replace("_", " "), opts, index=opts.index(g) if g else 0,
                        key=f"map_{ctype}_{key}{key_revision}",
                    )
                    mapping[key] = None if sel == "(nessuna)" else sel

            values = {}
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

                    def render_role_field(key):
                        base = core.split_role(key)[0]
                        label = base.replace("_", " ").capitalize()
                        key_revision = _field_widget_revision(base)
                        if base in {"CARICA", "RUOLO"}:
                            init, k = carica or "", f"v_{key}_{carica}{key_revision}"
                        else:
                            col = core.guess_column(base, pcols, "fisica")
                            init = core.format_field_value(base, person.get(col) if col else None)
                            k = f"v_{key}_{person.get('id', '')}{key_revision}"
                        values[key] = core.format_field_value(
                            base, _render_field_widget(base, label, init, k)
                        )
                    visible_role_keys = [
                        key for key in keys if not core.is_anagraphic_field(key)
                    ]
                    anagraphic_role_keys = [
                        key for key in keys if core.is_anagraphic_field(key)
                    ]
                    for key in visible_role_keys:
                        render_role_field(key)
                    if anagraphic_role_keys:
                        with st.expander(
                            f"Dati anagrafici - {core.role_label(role)}", expanded=False
                        ):
                            for key in anagraphic_role_keys:
                                render_role_field(key)

            st.markdown("**Campi del documento**")
            invalid_commission = False
            visible_main_keys = [key for key in main_keys if not core.is_anagraphic_field(key)]
            anagraphic_main_keys = [key for key in main_keys if core.is_anagraphic_field(key)]
            for key in visible_main_keys:
                values[key], invalid = _render_document_field(key, rec, mapping, rid)
                invalid_commission |= invalid
            if anagraphic_main_keys:
                with st.expander("Dati anagrafici", expanded=False):
                    for key in anagraphic_main_keys:
                        values[key], invalid = _render_document_field(key, rec, mapping, rid)
                        invalid_commission |= invalid

            if not placeholders:
                st.warning("Nessun segnaposto trovato (es. [NOME], [COGNOME]).")

            if st.button("Genera documento", type="primary", disabled=invalid_commission):
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
            st.caption("Bordo rosso: campo non compilato. Verde: valore inserito.")
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
