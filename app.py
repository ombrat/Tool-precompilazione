import hashlib
import hmac
import json
import os

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

import core

st.set_page_config(page_title="Precompilazione documenti", layout="wide")

def _setting(name):
    try:
        secret = st.secrets.get(name, "")
    except StreamlitSecretNotFoundError:
        secret = ""
    return os.environ.get(name) or secret


app_password = _setting("APP_PASSWORD")
auth_supabase_url = _setting("SUPABASE_URL")
auth_publishable_key = _setting("SUPABASE_PUBLISHABLE_KEY")
use_supabase_auth = bool(auth_supabase_url and auth_publishable_key)

if not use_supabase_auth and (not isinstance(app_password, str) or not app_password):
    st.error(
        "Accesso non configurato. Imposta SUPABASE_URL e SUPABASE_PUBLISHABLE_KEY "
        "(autenticazione a due fattori) oppure APP_PASSWORD."
    )
    st.stop()

if not st.session_state.get("authenticated"):
    st.title("Accesso")
    if not use_supabase_auth:
        with st.form("login"):
            entered_password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Accedi")
        if submitted:
            if hmac.compare_digest(entered_password, app_password):
                st.session_state["authenticated"] = True
                st.rerun()
            st.error("Password non valida.")
        st.stop()

    pending = st.session_state.get("auth_pending")
    if not pending:
        with st.form("login"):
            email = st.text_input("Email")
            entered_password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Accedi")
        if submitted:
            try:
                session = core.auth_sign_in(
                    auth_supabase_url, auth_publishable_key, email, entered_password
                )
                token = session["access_token"]
                factors = core.auth_totp_factors(
                    auth_supabase_url, auth_publishable_key, token
                )
                verified = next((f for f in factors if f.get("status") == "verified"), None)
                st.session_state["auth_pending"] = {
                    "token": token,
                    "email": session.get("user", {}).get("email", email),
                    "factor_id": verified["id"] if verified else None,
                }
                st.session_state.pop("auth_enroll", None)
                st.rerun()
            except (ValueError, RuntimeError) as error:
                st.error(str(error))
        st.stop()

    st.caption(f"Account: {pending['email']}")
    if pending["factor_id"] is None:
        st.info(
            "Primo accesso: scansiona il codice QR con un'app di autenticazione "
            "(Google Authenticator, Microsoft Authenticator, Authy...) e inserisci il codice generato."
        )
        if "auth_enroll" not in st.session_state:
            try:
                st.session_state["auth_enroll"] = core.auth_enroll_totp(
                    auth_supabase_url, auth_publishable_key, pending["token"]
                )
            except (ValueError, RuntimeError) as error:
                st.error(str(error))
                st.stop()
        enroll = st.session_state["auth_enroll"]
        st.markdown(
            f'<img src="{core.totp_qr_data_uri(enroll["totp"])}" width="220" alt="Codice QR">',
            unsafe_allow_html=True,
        )
        st.caption("Se non riesci a scansionare il QR, inserisci manualmente questa chiave:")
        st.code(enroll["totp"]["secret"], language=None)
        factor_id = enroll["id"]
    else:
        factor_id = pending["factor_id"]
    with st.form("totp"):
        code = st.text_input("Codice a 6 cifre", max_chars=6)
        confirmed = st.form_submit_button("Conferma")
    if confirmed:
        try:
            core.auth_verify_totp(
                auth_supabase_url, auth_publishable_key, pending["token"], factor_id, code
            )
        except (ValueError, RuntimeError) as error:
            st.error(str(error))
        else:
            st.session_state.pop("auth_pending", None)
            st.session_state.pop("auth_enroll", None)
            st.session_state["authenticated"] = True
            st.rerun()
    if st.button("Annulla"):
        st.session_state.pop("auth_pending", None)
        st.session_state.pop("auth_enroll", None)
        st.rerun()
    st.stop()

if st.sidebar.button("Esci"):
    st.session_state.clear()
    st.rerun()

try:
    secrets_archive_url = st.secrets.get("ARCHIVE_DATABASE_URL", "")
except StreamlitSecretNotFoundError:
    secrets_archive_url = ""
archive_database_url = os.environ.get("ARCHIVE_DATABASE_URL") or secrets_archive_url

try:
    secrets_supabase_url = st.secrets.get("SUPABASE_URL", "")
    secrets_supabase_key = st.secrets.get("SUPABASE_SERVICE_ROLE_KEY", "")
    secrets_templates_bucket = st.secrets.get("SUPABASE_TEMPLATES_BUCKET", "")
except StreamlitSecretNotFoundError:
    secrets_supabase_url = secrets_supabase_key = secrets_templates_bucket = ""
supabase_url = os.environ.get("SUPABASE_URL") or secrets_supabase_url
supabase_service_role_key = (
    os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or secrets_supabase_key
)
templates_bucket = (
    os.environ.get("SUPABASE_TEMPLATES_BUCKET")
    or secrets_templates_bucket
    or "document-templates"
)

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


@st.cache_data(show_spinner=False, max_entries=4, ttl=60)
def cached_supabase_template(url, service_role_key, bucket, customer_type):
    return core.load_supabase_document_template(
        url, service_role_key, bucket, customer_type
    )


@st.cache_data(show_spinner=False, max_entries=4)
def cached_mass_template(template_bytes, template_format):
    docx_template = (
        core.convert(template_bytes, "doc", "docx")
        if template_format == "doc"
        else template_bytes
    )
    return docx_template, core.find_placeholders(docx_template)


def session_archive_profiles(database_url):
    cached = st.session_state.get("archive_profiles_cache")
    if cached is None or cached["database_url"] != database_url:
        cached = {
            "database_url": database_url,
            "profiles": core.list_archive_profiles(database_url),
        }
        st.session_state["archive_profiles_cache"] = cached
    return cached["profiles"]


def session_default_database_info(database_url):
    cached = st.session_state.get("default_database_info_cache")
    if cached is None or cached["database_url"] != database_url:
        cached = {
            "database_url": database_url,
            "info": core.get_default_database_info(database_url),
        }
        st.session_state["default_database_info_cache"] = cached
    return cached["info"]


def invalidate_session_default_database_cache():
    st.session_state.pop("default_database_info_cache", None)


def invalidate_session_profiles_cache():
    st.session_state.pop("archive_profiles_cache", None)


def _normalize_percentage_widgets(widget_keys, error_key):
    errors = []
    for widget_key in widget_keys:
        try:
            st.session_state[widget_key] = core.format_percentage_value(
                st.session_state.get(widget_key, "")
            )
        except ValueError as error:
            errors.append(str(error))
    st.session_state[error_key] = errors


def _save_mass_manual_values(widget_keys):
    saved_values = st.session_state.setdefault("mass_manual_values", {})
    for widget_key in widget_keys:
        saved_values[widget_key] = st.session_state.get(widget_key, "")


def _save_mass_role_widgets(selected_corporates, people):
    for option, _ in selected_corporates:
        company_key = core._norm(option)
        role_data = st.session_state["mass_role_data"].setdefault(option, {})
        lr_count = st.session_state[f"mass_lr_count_{company_key}"]
        te_count = st.session_state[f"mass_te_count_{company_key}"]

        for number in range(lr_count):
            role = "LR" if number == 0 else f"LR{number + 1}"
            person_index = st.session_state.get(
                f"mass_person_{company_key}_{role}"
            )
            role_value = st.session_state.get(
                f"mass_role_{company_key}_{role}", ""
            )
            if role_value == "Altro":
                role_value = st.session_state.get(
                    f"mass_role_other_{company_key}_{role}", ""
                )
            role_data[role] = {
                "person": people[person_index] if person_index is not None else {},
                "role": role_value.strip(),
                "percentage": "",
            }

        for number in range(te_count):
            role = f"TE{number + 1}"
            person_index = st.session_state.get(
                f"mass_person_{company_key}_{role}"
            )
            percentage = st.session_state.get(
                f"mass_percentage_{company_key}_{role}", ""
            )
            try:
                percentage = core.format_percentage_value(percentage)
            except ValueError:
                pass
            role_data[role] = {
                "person": people[person_index] if person_index is not None else {},
                "role": "Socio",
                "percentage": percentage,
            }


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
        archive_profiles = session_archive_profiles(archive_database_url)
    except Exception as error:
        archive_error = str(error)

default_database_info, default_database_error = None, None
if archive_database_url and not archive_error:
    try:
        default_database_info = session_default_database_info(archive_database_url)
    except Exception as error:
        default_database_error = str(error)

if default_database_info:
    if st.session_state.get("default_db_sha256") != default_database_info["sha256"]:
        try:
            default_database_bytes = core.get_default_database_content(archive_database_url)
            if default_database_bytes is None:
                raise ValueError("Il file dell'anagrafica condivisa non è disponibile.")
            default_database_xls = core.load_xls_bytes(default_database_bytes)
        except Exception as error:
            default_database_error = str(error)
            st.session_state.pop("default_db_xls", None)
            st.session_state.pop("default_db_sha256", None)
        else:
            st.session_state["default_db_xls"] = default_database_xls
            st.session_state["default_db_sha256"] = default_database_info["sha256"]
elif not default_database_error:
    st.session_state.pop("default_db_xls", None)
    st.session_state.pop("default_db_sha256", None)

active_xls_content = st.session_state.get("uploaded_xls") or st.session_state.get(
    "default_db_xls"
)

profile_by_id = {profile["id"]: profile for profile in archive_profiles}
tab_main, tab_bulk, tab_archive, tab_db = st.tabs(
    ["Documento singolo", "Generazione massiva", "Archivio", "Database"]
)

with tab_main:
    selected_archive_for_type = profile_by_id.get(
        st.session_state.get("doc_archive_id")
    )
    if selected_archive_for_type:
        ctype = "giuridica"
        st.caption("Tipo cliente: Persona giuridica (impostato dalla scheda archiviata)")
    else:
        ctype = st.radio(
            "Tipo di cliente", list(core.CUSTOMER_TYPES),
            format_func=core.CUSTOMER_TYPES.get, horizontal=True, key="customer_type",
        )

    with st.expander("Usa un documento locale al posto del modello Supabase"):
        up = st.file_uploader(
            "Carica il documento Word (.doc / .docx)", type=["doc", "docx"]
        )

    template_error = None
    remote_template = None
    if not up and supabase_url and supabase_service_role_key:
        try:
            remote_template = cached_supabase_template(
                supabase_url, supabase_service_role_key, templates_bucket, ctype
            )
        except Exception as error:
            template_error = str(error)
    elif not up:
        st.info(
            "Configura SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY per caricare "
            "automaticamente il modello da Supabase Storage."
        )

    if up:
        source_name = up.name
        raw = up.getvalue()
        ext = up.name.rsplit(".", 1)[-1].lower()
        source_key = ("upload", up.name, up.size, hashlib.sha256(raw).hexdigest())
    elif remote_template:
        raw, source_name = remote_template
        ext = source_name.rsplit(".", 1)[-1].lower()
        source_key = (
            "supabase", ctype, source_name, hashlib.sha256(raw).hexdigest()
        )
        st.caption(f"Modello caricato da Supabase Storage: {source_name}")
    else:
        source_name = raw = ext = source_key = None
        if template_error:
            st.error(f"Impossibile caricare il modello da Supabase Storage: {template_error}")

    if source_key:
        if st.session_state.get("document_source_key") != source_key:
            with st.spinner("Lettura del documento..."):
                doc = core.convert(raw, "doc", "docx") if ext == "doc" else raw
                st.session_state.update(
                    doc=doc, fmt=ext, document_source_key=source_key, out=None,
                )

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
            selected_archive_id = st.session_state.get("doc_archive_id")
            selected_archive = profile_by_id.get(selected_archive_id)
            if selected_archive:
                st.info(f"Scheda archiviata caricata: {selected_archive['name']}")
                try:
                    fresh_payload, archive_changes = core.refresh_archive_payload(
                        selected_archive["payload"],
                        core.db_records("giuridica", active_xls_content),
                        core.db_records("fisica", active_xls_content),
                    )
                except Exception:
                    fresh_payload, archive_changes = None, []
                if archive_changes:
                    st.warning(
                        f"Il database contiene {len(archive_changes)} dati diversi o nuovi rispetto alla scheda."
                    )
                    with st.expander("Vedi differenze"):
                        for label, field, old_value, new_value in archive_changes:
                            st.write(f"**{label}** - {field}: `{old_value or '(vuoto)'}` → `{new_value}`")
                    if st.button("Aggiorna scheda con i dati del database", key="doc_refresh_profile"):
                        try:
                            core.save_archive_profile(
                                archive_database_url, selected_archive["name"],
                                fresh_payload, profile_id=selected_archive["id"],
                            )
                        except Exception as error:
                            st.error(f"Impossibile aggiornare la scheda: {error}")
                        else:
                            invalidate_session_profiles_cache()
                            st.rerun()
                ctype = "giuridica"
            roles = core.roles_for_customer_type(roles, ctype)
            if selected_archive:
                rec = selected_archive["payload"]["company"]
                cols = list(rec)
                rid = f"archive_{selected_archive['id']}"
            else:
                try:
                    records = core.db_records(ctype, active_xls_content)
                    cols = core.db_columns(ctype, active_xls_content)
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
                    if ctype == "giuridica" and archive_database_url and not archive_error:
                        match = next(
                            (p for p in archive_profiles
                             if core.record_identity(p["payload"]["company"]) == core.record_identity(rec)),
                            None,
                        )
                        if match:
                            st.info(f"Esiste una scheda salvata per questa società: {match['name']}")
                            st.button(
                                "Usa scheda salvata", key="doc_use_saved",
                                on_click=lambda pid=match["id"]: st.session_state.update(doc_archive_id=pid),
                            )

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
                    people = core.db_records("fisica", active_xls_content)
                    pcols = core.db_columns("fisica", active_xls_content)
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
                            invalidate_session_profiles_cache()
                            st.success("Anagrafica salvata nell'archivio.")

            if st.button("Genera documento", type="primary", disabled=invalid_commission):
                fields = [{"name": k, "tokens": t} for k, t in placeholders.items()]
                with st.spinner("Generazione..."):
                    out = core.render(data, fields, values)
                    st.session_state["out"] = core.convert(out, "docx", "doc") if fmt == "doc" else out
            if st.session_state.get("out"):
                st.download_button(
                    "Scarica documento compilato", st.session_state["out"],
                    file_name=f"{source_name.rsplit('.', 1)[0]}_compilato.{fmt}",
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

with tab_bulk:
    st.subheader("Generazione massiva")
    st.caption(
        "Seleziona più anagrafiche: per ciascuna verrà creato un mandato separato. "
        "I codici fiscali che iniziano con una lettera sono persone fisiche; "
        "quelli che iniziano con un numero sono persone giuridiche."
    )

    mass_templates = {}
    for customer_type, label in core.CUSTOMER_TYPES.items():
        with st.expander(f"Modello {label.lower()}", expanded=False):
            uploaded_template = st.file_uploader(
                f"Modello locale {label.lower()} (.doc / .docx)",
                type=["doc", "docx"],
                key=f"mass_template_{customer_type}",
            )
        try:
            if uploaded_template:
                template_name = uploaded_template.name
                template_bytes = uploaded_template.getvalue()
                template_format = template_name.rsplit(".", 1)[-1].lower()
            elif supabase_url and supabase_service_role_key:
                template_bytes, template_name = cached_supabase_template(
                    supabase_url, supabase_service_role_key, templates_bucket, customer_type
                )
                template_format = template_name.rsplit(".", 1)[-1].lower()
                st.caption(f"Modello {label.lower()} caricato da Supabase: {template_name}")
            else:
                continue
            docx_template, template_placeholders = cached_mass_template(
                template_bytes, template_format
            )
            mass_templates[customer_type] = {
                "name": template_name,
                "format": template_format,
                "docx": docx_template,
                "placeholders": template_placeholders,
            }
        except Exception as error:
            st.error(f"Impossibile caricare il modello {label.lower()}: {error}")

    if not supabase_url or not supabase_service_role_key:
        st.info(
            "Carica un modello locale per ogni tipo di persona da includere, "
            "oppure configura Supabase Storage."
        )

    if active_xls_content is None:
        st.warning("Carica o configura prima un'anagrafica nella scheda Database.")
    elif not mass_templates:
        st.warning("Per iniziare, rendi disponibile almeno un modello valido.")
    else:
        try:
            bulk_records = {}
            for customer_type in core.CUSTOMER_TYPES:
                if customer_type not in mass_templates:
                    continue
                for index, record in enumerate(
                    core.db_records(customer_type, active_xls_content)
                ):
                    fiscal_code_column = core.guess_column(
                        "CODICE_FISCALE", record.keys(), customer_type
                    )
                    actual_type = core.classify_customer_type(
                        record.get(fiscal_code_column) if fiscal_code_column else None
                    )
                    if actual_type != customer_type:
                        continue
                    option_key = f"{customer_type}:{core.record_identity(record)}"
                    if option_key in bulk_records:
                        option_key = f"{option_key}:{index}"
                    bulk_records[option_key] = (customer_type, record)
        except Exception as error:
            bulk_records = {}
            st.error(f"Impossibile leggere le anagrafiche: {error}")

        if bulk_records:
            people = [
                person
                for person in core.db_records("fisica", active_xls_content)
                if core.classify_customer_type(
                    (
                        person.get(column)
                        if (column := core.guess_column(
                            "CODICE_FISCALE", person.keys(), "fisica"
                        ))
                        else None
                    )
                ) == "fisica"
            ]
            st.session_state.setdefault("mass_phase", 1)
            if st.session_state["mass_phase"] == 1:
                st.session_state["mass_pending_records"] = [
                    option
                    for option in st.session_state.get(
                        "mass_pending_records",
                        st.session_state.get("mass_selected_records", []),
                    )
                    if option in bulk_records
                ]
                with st.form("mass_record_selection"):
                    st.multiselect(
                        "Fase 1 — Seleziona le anagrafiche",
                        list(bulk_records),
                        format_func=lambda option: (
                            f"{core.CUSTOMER_TYPES[bulk_records[option][0]]} — "
                            f"{core.record_label(bulk_records[option][0], bulk_records[option][1])}"
                        ),
                        key="mass_pending_records",
                    )
                    selection_submitted = st.form_submit_button(
                        "Conferma anagrafiche selezionate",
                        type="primary",
                    )
                if selection_submitted:
                    selected_keys = st.session_state["mass_pending_records"]
                    if not selected_keys:
                        st.error("Seleziona almeno un'anagrafica.")
                    else:
                        st.session_state["mass_selected_records"] = selected_keys
                        st.session_state.setdefault("mass_role_data", {})
                        profile_by_identity = {
                            core.record_identity(profile["payload"]["company"]): profile
                            for profile in archive_profiles
                        }
                        for option in selected_keys:
                            customer_type, record = bulk_records[option]
                            if customer_type != "giuridica":
                                continue
                            company_key = core._norm(option)
                            profile = profile_by_identity.get(
                                core.record_identity(record)
                            )
                            payload = profile["payload"] if profile else {}
                            saved_owners = payload.get("owners", [])
                            st.session_state.setdefault(
                                f"mass_lr_count_{company_key}", 1
                            )
                            st.session_state.setdefault(
                                f"mass_te_count_{company_key}",
                                max(1, len(saved_owners)),
                            )
                            if option in st.session_state["mass_role_data"]:
                                continue
                            role_data = {}
                            representative = payload.get("legal_representative")
                            if representative:
                                role_data["LR"] = {
                                    "person": representative,
                                    "role": payload.get("representative_role", ""),
                                    "percentage": "",
                                }
                            for number, owner in enumerate(saved_owners, 1):
                                role_data[f"TE{number}"] = {
                                    "person": owner.get("person", {}),
                                    "role": "Socio",
                                    "percentage": core.format_percentage_value(
                                        owner.get("percentage", "")
                                    ),
                                }
                            st.session_state["mass_role_data"][option] = role_data
                        st.session_state["mass_phase"] = 2
                        st.rerun()

            elif st.session_state["mass_phase"] == 2:
                selected_keys = [
                    option for option in st.session_state.get("mass_selected_records", [])
                    if option in bulk_records
                ]
                selected_corporates = [
                    (option, bulk_records[option][1])
                    for option in selected_keys
                    if bulk_records[option][0] == "giuridica"
                ]
                percentage_keys = [
                    f"mass_percentage_{core._norm(option)}_TE{number + 1}"
                    for option, _ in selected_corporates
                    for number in range(
                        st.session_state[f"mass_te_count_{core._norm(option)}"]
                    )
                ]
                percentage_error_key = "mass_percentage_errors"
                phase_action = None
                add_or_remove = None
                with st.form("mass_corporate_roles_form"):
                    for option, company in selected_corporates:
                        company_name = core.record_label("giuridica", company)
                        with st.expander(
                            f"Legale rappresentante e titolari effettivi — {company_name}",
                            expanded=True,
                        ):
                            company_key = core._norm(option)
                            role_data = st.session_state["mass_role_data"].setdefault(
                                option, {}
                            )
                            lr_count_key = f"mass_lr_count_{company_key}"
                            te_count_key = f"mass_te_count_{company_key}"
                            lr_slots = [
                                "LR" if number == 0 else f"LR{number + 1}"
                                for number in range(st.session_state[lr_count_key])
                            ]
                            for role in lr_slots:
                                saved = role_data.get(role, {})
                                st.markdown(f"**{core.role_label(role)}**")
                                person_key = f"mass_person_{company_key}_{role}"
                                st.selectbox(
                                    "Persona",
                                    list(range(len(people))),
                                    index=st.session_state.get(
                                        person_key,
                                        _find_record_index(saved.get("person", {}), people),
                                    ),
                                    placeholder="Seleziona una persona...",
                                    format_func=lambda index: core.record_label(
                                        "fisica", people[index]
                                    ),
                                    key=person_key,
                                )
                                role_key = f"mass_role_{company_key}_{role}"
                                saved_role = saved.get("role", "")
                                role_options = [""] + core.CARICHE + ["Altro"]
                                default_role = (
                                    saved_role
                                    if saved_role in core.CARICHE
                                    else "Altro" if saved_role else ""
                                )
                                role_value = st.session_state.get(
                                    role_key, default_role
                                )
                                st.selectbox(
                                    "Carica / ruolo",
                                    role_options,
                                    index=role_options.index(
                                        role_value if role_value in role_options else default_role
                                    ),
                                    key=role_key,
                                )
                                if role_value == "Altro":
                                    st.text_input(
                                        "Specifica la carica",
                                        value=saved_role,
                                        key=f"mass_role_other_{company_key}_{role}",
                                    )
                            lr_add, lr_remove = st.columns(2)
                            if lr_add.form_submit_button(
                                "Aggiungi legale rappresentante",
                                on_click=_normalize_percentage_widgets,
                                args=(percentage_keys, percentage_error_key),
                                key=f"mass_add_lr_{company_key}",
                            ):
                                add_or_remove = ("add_lr", option, None)
                            if len(lr_slots) > 1 and lr_remove.form_submit_button(
                                "Rimuovi ultimo legale rappresentante",
                                on_click=_normalize_percentage_widgets,
                                args=(percentage_keys, percentage_error_key),
                                key=f"mass_remove_lr_{company_key}",
                            ):
                                add_or_remove = ("remove_lr", option, lr_slots[-1])

                            te_slots = [
                                f"TE{number + 1}"
                                for number in range(st.session_state[te_count_key])
                            ]
                            for role in te_slots:
                                saved = role_data.get(role, {})
                                st.markdown(f"**{core.role_label(role)} (socio)**")
                                person_key = f"mass_person_{company_key}_{role}"
                                st.selectbox(
                                    "Persona",
                                    list(range(len(people))),
                                    index=st.session_state.get(
                                        person_key,
                                        _find_record_index(saved.get("person", {}), people),
                                    ),
                                    placeholder="Seleziona una persona...",
                                    format_func=lambda index: core.record_label(
                                        "fisica", people[index]
                                    ),
                                    key=person_key,
                                )
                                percentage_key = f"mass_percentage_{company_key}_{role}"
                                if percentage_key not in st.session_state:
                                    st.session_state[percentage_key] = saved.get(
                                        "percentage", "0,00%"
                                    )
                                st.text_input(
                                    "Percentuale di titolarità",
                                    key=percentage_key,
                                )
                            te_add, te_remove = st.columns(2)
                            if te_add.form_submit_button(
                                "Aggiungi titolare effettivo",
                                on_click=_normalize_percentage_widgets,
                                args=(percentage_keys, percentage_error_key),
                                key=f"mass_add_te_{company_key}",
                            ):
                                add_or_remove = ("add_te", option, None)
                            if len(te_slots) > 1 and te_remove.form_submit_button(
                                "Rimuovi ultimo titolare effettivo",
                                on_click=_normalize_percentage_widgets,
                                args=(percentage_keys, percentage_error_key),
                                key=f"mass_remove_te_{company_key}",
                            ):
                                add_or_remove = ("remove_te", option, te_slots[-1])

                    back_to_selection = st.form_submit_button(
                        "Torna alla selezione delle anagrafiche",
                        on_click=_normalize_percentage_widgets,
                        args=(percentage_keys, percentage_error_key),
                    )
                    next_to_manual = st.form_submit_button(
                        "Conferma anagrafiche e passa alla fase 2",
                        type="primary",
                        disabled=not selected_keys,
                        on_click=_normalize_percentage_widgets,
                        args=(percentage_keys, percentage_error_key),
                    )

                if back_to_selection or next_to_manual or add_or_remove:
                    _save_mass_role_widgets(selected_corporates, people)
                if add_or_remove:
                    action, option, removed_role = add_or_remove
                    company_key = core._norm(option)
                    if action == "add_lr":
                        st.session_state[f"mass_lr_count_{company_key}"] += 1
                    elif action == "remove_lr":
                        st.session_state[f"mass_lr_count_{company_key}"] -= 1
                        st.session_state["mass_role_data"][option].pop(
                            removed_role, None
                        )
                        for key in (
                            f"mass_person_{company_key}_{removed_role}",
                            f"mass_role_{company_key}_{removed_role}",
                            f"mass_role_other_{company_key}_{removed_role}",
                        ):
                            st.session_state.pop(key, None)
                    elif action == "add_te":
                        st.session_state[f"mass_te_count_{company_key}"] += 1
                    elif action == "remove_te":
                        st.session_state[f"mass_te_count_{company_key}"] -= 1
                        st.session_state["mass_role_data"][option].pop(
                            removed_role, None
                        )
                        for key in (
                            f"mass_person_{company_key}_{removed_role}",
                            f"mass_percentage_{company_key}_{removed_role}",
                        ):
                            st.session_state.pop(key, None)
                    st.rerun()
                if back_to_selection:
                    st.session_state["mass_pending_records"] = selected_keys
                    st.session_state["mass_phase"] = 1
                    st.rerun()
                if next_to_manual:
                    errors = []
                    mandates = []
                    for option in selected_keys:
                        customer_type, record = bulk_records[option]
                        roles = st.session_state["mass_role_data"].get(option, {})
                        mandate = {
                            "customer_type": customer_type,
                            "record": record,
                            "roles": roles,
                        }
                        if customer_type == "giuridica":
                            company_key = core._norm(option)
                            expected_roles = [
                                *(
                                    "LR" if number == 0 else f"LR{number + 1}"
                                    for number in range(
                                        st.session_state[ f"mass_lr_count_{company_key}"]
                                    )
                                ),
                                *(
                                    f"TE{number + 1}"
                                    for number in range(
                                        st.session_state[ f"mass_te_count_{company_key}"]
                                    )
                                ),
                            ]
                            for role in expected_roles:
                                role_data = roles.get(role)
                                if not role_data or not role_data.get("person"):
                                    errors.append(
                                        f"{core.record_label(customer_type, record)}: "
                                        f"salva {core.role_label(role).lower()}."
                                    )
                                elif role.startswith("LR") and not role_data.get("role"):
                                    errors.append(
                                        f"{core.record_label(customer_type, record)}: "
                                        f"inserisci la carica per "
                                        f"{core.role_label(role).lower()}."
                                    )
                                elif role.startswith("TE"):
                                    try:
                                        role_data["percentage"] = (
                                            core.format_percentage_value(
                                                role_data.get("percentage", "")
                                            )
                                        )
                                    except ValueError:
                                        errors.append(
                                            f"{core.record_label(customer_type, record)}: "
                                            f"completa la percentuale di "
                                            f"{core.role_label(role).lower()}."
                                        )
                        mandates.append(mandate)
                    if errors:
                        st.error(" ".join(errors))
                    else:
                        st.session_state["mass_mandates"] = mandates
                        st.session_state["mass_phase"] = 3
                        st.session_state.pop("mass_archive", None)
                        st.rerun()
            else:
                mandates = st.session_state.get("mass_mandates", [])
                if not mandates:
                    st.session_state["mass_phase"] = 1
                    st.rerun()
                st.info(
                    "Fase 2 — Inserisci le variabili specifiche per ciascun mandato. "
                    "I dati anagrafici e gli incarichi vengono precompilati dalla fase 1."
                )
                mass_values_by_mandate = []
                invalid_bulk_fields = False
                for number, mandate in enumerate(mandates, 1):
                    customer_type = mandate["customer_type"]
                    record = mandate["record"]
                    template = mass_templates.get(customer_type)
                    if not template:
                        st.error(
                            f"Manca il modello {core.CUSTOMER_TYPES[customer_type].lower()} "
                            "per una delle anagrafiche selezionate."
                        )
                        invalid_bulk_fields = True
                        continue
                    placeholders = template["placeholders"]
                    label = core.record_label(customer_type, record)
                    values = {}
                    manual_keys = []
                    for key in placeholders:
                        base, role = core.split_role(key)
                        normalized_base = core._norm(base).upper()
                        if role:
                            role_data = mandate["roles"].get(role, {})
                            if normalized_base in {"CARICA", "RUOLO", "RUOLO_SOCIETARIO"}:
                                values[key] = role_data.get("role", "")
                            elif "PERCENT" in normalized_base:
                                values[key] = role_data.get("percentage", "")
                            elif core.is_anagraphic_field(key):
                                person = role_data.get("person", {})
                                column = core.guess_column(base, person.keys(), "fisica")
                                values[key] = core.format_field_value(
                                    base, person.get(column) if column else None
                                )
                            else:
                                manual_keys.append(key)
                        elif core.is_anagraphic_field(key):
                            if normalized_base == "FORMA_GIURIDICA":
                                company_name_column = core.guess_column(
                                    "RAGIONE_SOCIALE", record.keys(), "giuridica"
                                )
                                value = core.legal_form_from_company_name(
                                    record.get(company_name_column)
                                    if company_name_column else None
                                )
                            else:
                                column = core.guess_column(
                                    base, record.keys(), customer_type
                                )
                                value = core.format_field_value(
                                    base, record.get(column) if column else None
                                )
                            values[key] = value
                        else:
                            manual_keys.append(key)

                    mass_values_by_mandate.append(
                        (mandate, template, placeholders, values, label, manual_keys)
                    )

                manual_widget_keys = [
                    (
                        f"mass_value_{core._norm(core.record_identity(mandate['record']))}_"
                        f"{core._norm(key)}"
                    )
                    for mandate, _, _, _, _, manual_keys in mass_values_by_mandate
                    for key in manual_keys
                ]
                saved_manual_values = st.session_state.setdefault(
                    "mass_manual_values", {}
                )
                generate_clicked = False
                back_to_roles = False
                with st.form("mass_values_form"):
                    for (
                        mandate, template, placeholders, values, label, manual_keys
                    ) in mass_values_by_mandate:
                        record_key = core._norm(
                            core.record_identity(mandate["record"])
                        )
                        with st.expander(
                            f"Mandato — {label}",
                            expanded=len(mandates) == 1,
                        ):
                            if manual_keys:
                                st.markdown("**Premessa, commissioni e altre variabili**")
                                for key in manual_keys:
                                    field_label = key.replace("_", " ").capitalize()
                                    widget_key = (
                                        f"mass_value_{record_key}_{core._norm(key)}"
                                    )
                                    raw_value = _render_field_widget(
                                        key,
                                        field_label,
                                        saved_manual_values.get(widget_key, ""),
                                        widget_key,
                                        multiline="PREMESSA" in core._norm(key).upper()
                                        or key not in core.PREDEFINED,
                                    )
                                    try:
                                        values[key] = core.format_field_value(
                                            key,
                                            core.format_commission_value(key, raw_value),
                                        )
                                    except ValueError as error:
                                        invalid_bulk_fields = True
                                        st.error(f"{field_label}: {error}")
                            else:
                                st.caption("Il modello non contiene variabili manuali.")
                    back_to_roles = st.form_submit_button(
                        "Torna alla fase 1 — LR e TE",
                        on_click=_save_mass_manual_values,
                        args=(manual_widget_keys,),
                    )
                    generate_clicked = st.form_submit_button(
                        "Genera i mandati",
                        type="primary",
                        disabled=invalid_bulk_fields or not mass_values_by_mandate,
                    )

                if back_to_roles:
                    st.session_state["mass_phase"] = 2
                    st.rerun()

                mass_signature = json.dumps(
                    [
                        (
                            mandate["customer_type"],
                            core.record_identity(mandate["record"]),
                            mandate["record"],
                            mandate["roles"],
                            hashlib.sha256(template["docx"]).hexdigest(),
                            template["format"],
                            values,
                        )
                        for mandate, template, _, values, _, _ in mass_values_by_mandate
                    ],
                    sort_keys=True,
                    ensure_ascii=False,
                )
                if generate_clicked and not invalid_bulk_fields:
                    documents = []
                    used_names = set()
                    with st.spinner("Generazione dei documenti..."):
                        for (
                            mandate, template, placeholders, values, label, _
                        ) in mass_values_by_mandate:
                            fields = [
                                {"name": key, "tokens": tokens}
                                for key, tokens in placeholders.items()
                            ]
                            output = core.render(template["docx"], fields, values)
                            extension = template["format"]
                            if extension == "doc":
                                output = core.convert(output, "docx", "doc")
                            filename_base = core._norm(label).replace("_", " ") or "anagrafica"
                            filename = f"Mandato {filename_base}.{extension}"
                            duplicate = 2
                            while filename.casefold() in used_names:
                                filename = (
                                    f"Mandato {filename_base} ({duplicate}).{extension}"
                                )
                                duplicate += 1
                            used_names.add(filename.casefold())
                            documents.append((filename, output))
                    st.session_state["mass_archive"] = core.create_document_archive(
                        documents
                    )
                    st.session_state["mass_archive_signature"] = mass_signature

                if (
                    st.session_state.get("mass_archive")
                    and st.session_state.get("mass_archive_signature") == mass_signature
                ):
                    st.download_button(
                        "Scarica i mandati separati (ZIP)",
                        st.session_state["mass_archive"],
                        file_name="Mandati_massivi.zip",
                        mime="application/zip",
                        key="mass_download",
                    )

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

        xls_content = active_xls_content
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
                        invalidate_session_profiles_cache()
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
                        invalidate_session_profiles_cache()
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
                        invalidate_session_profiles_cache()
                        st.session_state["archive_notice"] = "Scheda eliminata."
                        st.rerun()

with tab_db:
    s = core.load_settings()
    if notice := st.session_state.pop("default_db_notice", None):
        st.success(notice)
    if default_database_error:
        st.error(f"Impossibile caricare l'anagrafica condivisa: {default_database_error}")
    elif default_database_info:
        st.info(
            f"Anagrafica condivisa: {default_database_info['filename']} "
            f"(aggiornata il {default_database_info['updated_at']:%d/%m/%Y %H:%M})"
        )
    elif archive_database_url and not archive_error:
        st.warning("Non è ancora stata salvata un'anagrafica condivisa.")
    if archive_database_url and not archive_error:
        st.caption(
            "Chiunque abbia accesso all'app può sostituire l'anagrafica condivisa."
        )
    db_up = st.file_uploader(
        "Carica un database anagrafiche (.xls)",
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
        f"{default_database_info['filename']} (condiviso)"
        if default_database_info and active_xls_content
        else s["xls_path"] or "nessun file Excel (database SQL)"
    )
    st.caption(f"Database in uso: {active_db}")
    if db_up and st.session_state.get("uploaded_xls") and archive_database_url:
        st.caption(
            "Il file caricato è temporaneo finché non lo salvi come anagrafica condivisa."
        )
        if st.button("Salva o aggiorna l'anagrafica condivisa", type="primary"):
            try:
                digest = core.save_default_database(
                    archive_database_url, db_up.name, db_bytes
                )
            except Exception as error:
                st.error(f"Impossibile salvare l'anagrafica condivisa: {error}")
            else:
                invalidate_session_default_database_cache()
                st.session_state["default_db_xls"] = st.session_state["uploaded_xls"]
                st.session_state["default_db_sha256"] = digest
                st.session_state["default_db_notice"] = (
                    "Anagrafica condivisa salvata e disponibile a tutti gli utenti."
                )
                st.rerun()
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
