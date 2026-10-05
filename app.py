import hashlib
import hmac
import json
import os

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

import core

st.set_page_config(page_title="Precompilazione documenti", layout="wide")

try:
    secrets_password = st.secrets.get("APP_PASSWORD", "")
except StreamlitSecretNotFoundError:
    secrets_password = ""
app_password = os.environ.get("APP_PASSWORD") or secrets_password
if not isinstance(app_password, str) or not app_password:
    st.error(
        "Accesso non configurato. Imposta il segreto APP_PASSWORD prima di avviare l'app."
    )
    st.stop()

if not st.session_state.get("authenticated"):
    st.title("Accesso")
    with st.form("login"):
        entered_password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Accedi")
    if submitted:
        if hmac.compare_digest(entered_password, app_password):
            st.session_state["authenticated"] = True
            st.rerun()
        st.error("Password non valida.")
    st.stop()

if st.sidebar.button("Esci"):
    st.session_state.clear()
    st.rerun()

try:
    secrets_archive_url = st.secrets.get("ARCHIVE_DATABASE_URL", "")
except StreamlitSecretNotFoundError:
    secrets_archive_url = ""
archive_database_url = os.environ.get("ARCHIVE_DATABASE_URL") or secrets_archive_url

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
    if core._norm(key).upper() == "FORMA_GIURIDICA":
        company_name_column = core.guess_column(
            "RAGIONE_SOCIALE", record.keys(), "giuridica"
        )
        company_name = record.get(company_name_column) if company_name_column else None
        initial = core.legal_form_from_company_name(company_name)
    else:
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


def _find_record_index(snapshot, records):
    identity = core.record_identity(snapshot)
    return next(
        (index for index, record in enumerate(records)
         if core.record_identity(record) == identity),
        None,
    )


archive_profiles, archive_error = [], None
if archive_database_url:
    try:
        archive_profiles = core.list_archive_profiles(archive_database_url)
    except Exception as error:
        archive_error = str(error)

profile_by_id = {profile["id"]: profile for profile in archive_profiles}
tab_main, tab_archive, tab_db = st.tabs(["Documento", "Archivio", "Database"])

with tab_main:
    up = st.file_uploader("Carica il documento Word (.doc / .docx)", type=["doc", "docx"])
    if up and st.session_state.get("upkey") != (up.name, up.size):
        raw = up.getvalue()
        ext = up.name.rsplit(".", 1)[-1].lower()
        with st.spinner("Lettura del documento..."):
            doc = core.convert(raw, "doc", "docx") if ext == "doc" else raw
            has_role_placeholders = any(
                core.split_role(key)[1] for key in core.find_placeholders(doc)
            )
            st.session_state.update(
                doc=doc, fmt=ext, upkey=(up.name, up.size), out=None,
                customer_type="giuridica" if has_role_placeholders else "fisica",
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
            if st.session_state.get("doc_archive_id") not in (
                [None] + list(profile_by_id)
            ):
                st.session_state["doc_archive_id"] = None
            if archive_database_url and not archive_error:
                selected_archive_id = st.selectbox(
                    "Scheda archiviata (opzionale)",
                    [None] + list(profile_by_id),
                    format_func=lambda value: (
                        "Seleziona una scheda" if value is None
                        else profile_by_id[value]["name"]
                    ),
                    key="doc_archive_id",
                )
            else:
                selected_archive_id = None
            selected_archive = profile_by_id.get(selected_archive_id)
            if selected_archive:
                st.info(f"Scheda archiviata caricata: {selected_archive['name']}")
                ctype = "giuridica"
            else:
                ctype = st.radio(
                    "Tipo di cliente", list(core.CUSTOMER_TYPES),
                    format_func=core.CUSTOMER_TYPES.get, horizontal=True, key="customer_type",
                )
            roles = core.roles_for_customer_type(roles, ctype)
            if selected_archive:
                rec = selected_archive["payload"]["company"]
                cols = list(rec)
                rid = f"archive_{selected_archive['id']}"
            else:
                try:
                    xls_content = st.session_state.get("uploaded_xls")
                    records = core.db_records(ctype, xls_content)
                    cols = core.db_columns(ctype, xls_content)
                except Exception as e:
                    records, cols = [], []
                    st.error(f"Errore database: {e}")
                rec, rid = {}, "none"
                if records:
                    idx = st.selectbox(
                        "Anagrafica", range(len(records)),
                        format_func=lambda i: core.record_label(ctype, records[i]),
                        key="company_record",
                    )
                    rec = records[idx]
                    rid = f"{ctype}_{rec.get('id', idx)}"

            mapping = {}
            with st.expander("Collegamento campi / colonne database"):
                for key in main_keys:
                    if core._norm(key).upper() == "FORMA_GIURIDICA":
                        mapping[key] = None
                        continue
                    opts = ["(nessuna)"] + cols
                    g = core.guess_column(key, cols, ctype)
                    key_revision = _field_widget_revision(key)
                    sel = st.selectbox(
                        key.replace("_", " "), opts, index=opts.index(g) if g else 0,
                        key=f"map_{ctype}_{key}{key_revision}",
                    )
                    mapping[key] = None if sel == "(nessuna)" else sel

            values = {}
            role_data = {}
            if roles and not selected_archive:
                try:
                    xls_content = st.session_state.get("uploaded_xls")
                    people = core.db_records("fisica", xls_content)
                    pcols = core.db_columns("fisica", xls_content)
                except Exception as e:
                    people, pcols = [], []
                    st.error(f"Errore database: {e}")
            for role, keys in roles.items():
                with st.container(border=True):
                    st.markdown(f"**{core.role_label(role)}**")
                    archived_owner = None
                    if selected_archive:
                        payload = selected_archive["payload"]
                        if role == "LR":
                            person = payload["legal_representative"]
                            carica = payload.get("representative_role", "")
                        elif role.startswith("TE"):
                            owner_index = int(role[2:]) - 1 if role[2:].isdigit() else 0
                            owners = payload.get("owners", [])
                            archived_owner = owners[owner_index] if owner_index < len(owners) else None
                            person = archived_owner["person"] if archived_owner else {}
                            carica = ""
                        else:
                            person, carica = {}, ""
                        st.caption(core.record_label("fisica", person) if person else "Nominativo non presente nella scheda.")
                    else:
                        pidx = st.selectbox(
                            "Anagrafica", range(len(people)), index=None, placeholder="Cerca per cognome...",
                            format_func=lambda i: core.record_label("fisica", people[i]), key=f"pers_{role}",
                        )
                        person = people[pidx] if pidx is not None else {}
                        carica = st.selectbox(
                            "Carica", core.CARICHE, index=None, placeholder="Seleziona la carica",
                            key=f"car_{role}",
                        )
                        if carica == "Altro":
                            carica = st.text_input("Specifica la carica", key=f"caro_{role}")

                    def render_role_field(key):
                        base = core.split_role(key)[0]
                        label = base.replace("_", " ").capitalize()
                        key_revision = _field_widget_revision(base)
                        if base in {"CARICA", "RUOLO"}:
                            init, k = carica or "", f"v_{key}_{carica}{key_revision}"
                        elif archived_owner and "PERCENT" in core._norm(base).upper():
                            init = archived_owner["percentage"]
                            k = f"v_{rid}_{key}_{role}{key_revision}"
                        else:
                            person_columns = person.keys() if selected_archive else pcols
                            col = core.guess_column(base, person_columns, "fisica")
                            init = core.format_field_value(base, person.get(col) if col else None)
                            k = f"v_{rid}_{key}_{person.get('id', '')}{key_revision}"
                        values[key] = core.format_field_value(
                            base, _render_field_widget(base, label, init, k)
                        )
                    role_data[role] = {"person": person, "carica": carica, "keys": keys}
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

            if archive_database_url and not archive_error and not selected_archive and rec and "LR" in role_data:
                with st.expander("Salva questa anagrafica nell'archivio"):
                    owners_to_save = []
                    for role, info in role_data.items():
                        if not role.startswith("TE") or not info["person"]:
                            continue
                        pct_key = next(
                            (k for k in info["keys"] if "PERCENT" in core._norm(core.split_role(k)[0]).upper()),
                            None,
                        )
                        owners_to_save.append({
                            "person": info["person"],
                            "percentage": str(values.get(pct_key, "")).replace("%", "").replace(",", ".").strip() if pct_key else "",
                        })
                    default_name = core.record_label(ctype, rec)
                    save_name = st.text_input("Nome della scheda", value=default_name, key=f"doc_save_name_{rid}")
                    if st.button("Salva anagrafica", key="doc_save_profile"):
                        try:
                            core.save_archive_profile(
                                archive_database_url,
                                save_name,
                                {
                                    "company": rec,
                                    "legal_representative": role_data["LR"]["person"],
                                    "representative_role": role_data["LR"]["carica"] or "",
                                    "owners": owners_to_save,
                                },
                            )
                        except (KeyError, ValueError) as error:
                            st.error(str(error))
                        except Exception as error:
                            st.error(f"Impossibile salvare la scheda: {error}")
                        else:
                            st.success("Anagrafica salvata nell'archivio.")

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

with tab_archive:
    st.subheader("Archivio condiviso delle persone giuridiche")
    if not archive_database_url:
        st.error(
            "Archivio non configurato. Aggiungi ARCHIVE_DATABASE_URL ai Secrets "
            "dell'app Streamlit."
        )
    elif archive_error:
        st.error(f"Impossibile collegarsi al database dell'archivio: {archive_error}")
    else:
        if notice := st.session_state.pop("archive_notice", None):
            st.success(notice)

        saved_profile_ids = [profile["id"] for profile in archive_profiles]
        if st.session_state.get("archive_edit_id") not in [None] + saved_profile_ids:
            st.session_state["archive_edit_id"] = None
        selected_id = st.selectbox(
            "Scheda da modificare o consultare",
            [None] + saved_profile_ids,
            format_func=lambda value: (
                "Nuova scheda" if value is None else profile_by_id[value]["name"]
            ),
            key="archive_edit_id",
        )
        saved_profile = profile_by_id.get(selected_id)
        editor_key = selected_id or "new"

        if (
            "archive_owner_count" not in st.session_state
            or st.session_state.get("archive_editor_loaded") != selected_id
        ):
            st.session_state["archive_owner_count"] = max(
                1, len(saved_profile["payload"].get("owners", [])) if saved_profile else 1
            )
            st.session_state["archive_editor_loaded"] = selected_id
            st.rerun()

        xls_content = st.session_state.get("uploaded_xls")
        if xls_content is None:
            st.warning(
                "Per creare o modificare una scheda, carica prima il file Excel "
                "nella scheda Database. Le schede già salvate restano disponibili."
            )
            if saved_profile:
                payload = saved_profile["payload"]
                st.write(f"**Società:** {core.record_label('giuridica', payload['company'])}")
                st.write(
                    "**Legale rappresentante:** "
                    f"{core.record_label('fisica', payload['legal_representative'])}"
                )
                for index, owner in enumerate(payload["owners"], start=1):
                    st.write(
                        f"**Titolare effettivo {index}:** "
                        f"{core.record_label('fisica', owner['person'])} — "
                        f"{owner['percentage']}%"
                    )
                if st.button("Elimina scheda", type="secondary"):
                    try:
                        core.delete_archive_profile(archive_database_url, selected_id)
                    except Exception as error:
                        st.error(f"Impossibile eliminare la scheda: {error}")
                    else:
                        st.session_state["archive_notice"] = "Scheda eliminata."
                        st.rerun()
        else:
            companies = xls_content[1]["giuridica"]
            people = xls_content[1]["fisica"]
            if not companies:
                st.warning("Il file Excel caricato non contiene persone giuridiche.")
            elif not people:
                st.warning("Il file Excel caricato non contiene persone fisiche.")
            else:
                saved_payload = saved_profile["payload"] if saved_profile else {}
                saved_company = saved_payload.get("company", {})
                company_index = _find_record_index(saved_company, companies)
                company_idx = st.selectbox(
                    "Persona giuridica",
                    range(len(companies)),
                    index=company_index,
                    format_func=lambda index: core.record_label("giuridica", companies[index]),
                    key=f"archive_company_{editor_key}",
                )
                company = companies[company_idx] if company_idx is not None else {}

                saved_representative = saved_payload.get("legal_representative", {})
                representative_index = _find_record_index(saved_representative, people)
                representative_idx = st.selectbox(
                    "Legale rappresentante",
                    range(len(people)),
                    index=representative_index,
                    format_func=lambda index: core.record_label("fisica", people[index]),
                    key=f"archive_representative_{editor_key}",
                )
                representative = (
                    people[representative_idx] if representative_idx is not None else {}
                )
                representative_role = st.text_input(
                    "Carica del legale rappresentante",
                    value=saved_payload.get("representative_role", ""),
                    key=f"archive_role_{editor_key}",
                )

                owner_count_key = "archive_owner_count"
                owner_count = st.session_state[owner_count_key]
                add_col, remove_col = st.columns(2)
                if add_col.button("Aggiungi titolare effettivo", key=f"add_owner_{editor_key}"):
                    st.session_state[owner_count_key] = owner_count + 1
                    st.rerun()
                if owner_count > 1 and remove_col.button(
                    "Rimuovi ultimo titolare", key=f"remove_owner_{editor_key}"
                ):
                    st.session_state[owner_count_key] = owner_count - 1
                    st.rerun()

                saved_owners = saved_payload.get("owners", [])
                owners = []
                for index in range(owner_count):
                    existing_owner = saved_owners[index] if index < len(saved_owners) else {}
                    owner_cols = st.columns([3, 1])
                    person_index = _find_record_index(existing_owner.get("person", {}), people)
                    person_index = st.selectbox(
                        f"Titolare effettivo {index + 1}",
                        range(len(people)),
                        index=person_index,
                        format_func=lambda person_idx: core.record_label(
                            "fisica", people[person_idx]
                        ),
                        key=f"archive_owner_{editor_key}_{index}",
                    )
                    percentage = owner_cols[1].number_input(
                        "Quota %",
                        min_value=0.0,
                        max_value=100.0,
                        step=0.01,
                        format="%.2f",
                        value=float(existing_owner.get("percentage", 0) or 0),
                        key=f"archive_percentage_{editor_key}_{index}",
                    )
                    owners.append(
                        {
                            "person": people[person_index] if person_index is not None else {},
                            "percentage": str(percentage),
                        }
                    )

                profile_name = st.text_input(
                    "Nome della scheda",
                    value=saved_profile["name"] if saved_profile else "",
                    key=f"archive_name_{editor_key}",
                    placeholder=(
                        core.record_label("giuridica", company) if company else ""
                    ),
                )
                save_col, delete_col = st.columns(2)
                can_save = bool(company and representative) and all(
                    owner["person"] for owner in owners
                )
                if save_col.button("Salva scheda", type="primary", disabled=not can_save):
                    payload = {
                        "company": company,
                        "legal_representative": representative,
                        "representative_role": representative_role.strip(),
                        "owners": owners,
                    }
                    try:
                        core.save_archive_profile(
                            archive_database_url,
                            profile_name or core.record_label("giuridica", company),
                            payload,
                            profile_id=selected_id,
                        )
                    except (KeyError, ValueError) as error:
                        st.error(str(error))
                    except Exception as error:
                        st.error(f"Impossibile salvare la scheda: {error}")
                    else:
                        st.session_state["archive_notice"] = "Scheda salvata nell'archivio."
                        st.rerun()

                if saved_profile and delete_col.button(
                    "Elimina scheda", type="secondary"
                ):
                    try:
                        core.delete_archive_profile(archive_database_url, selected_id)
                    except Exception as error:
                        st.error(f"Impossibile eliminare la scheda: {error}")
                    else:
                        st.session_state["archive_notice"] = "Scheda eliminata."
                        st.rerun()

with tab_db:
    s = core.load_settings()
    db_up = st.file_uploader(
        "Seleziona il database anagrafiche dal tuo computer (.xls)",
        type=["xls"],
        key="db_upload",
    )
    if not db_up:
        if st.session_state.pop("uploaded_xls", None) is not None:
            st.session_state.pop("db_upkey", None)
            st.rerun()
    if db_up:
        db_bytes = db_up.getvalue()
        db_key = (db_up.name, len(db_bytes), hashlib.sha256(db_bytes).digest())
    else:
        db_key = None
    if db_up and st.session_state.get("db_upkey") != db_key:
        try:
            st.session_state["uploaded_xls"] = core.load_xls_bytes(db_bytes)
        except Exception as error:
            st.session_state.pop("uploaded_xls", None)
            st.error(f"Impossibile leggere il database Excel: {error}")
        else:
            st.session_state["db_upkey"] = db_key
            st.rerun()
    active_db = db_up.name if db_up and st.session_state.get("uploaded_xls") else (
        s["xls_path"] or "nessun file Excel (database SQL)"
    )
    st.caption(f"Database in uso: {active_db}")
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
