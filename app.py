import hashlib
import hmac
import html
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


def _field_anchor_id(widget_key):
    return f"campo-{core._norm(widget_key)}"


def _field_anchor(widget_key):
    st.markdown(f'<div id="{_field_anchor_id(widget_key)}"></div>', unsafe_allow_html=True)


def _render_field_issues(title, issues, description, *, error=False):
    if not issues:
        return
    message = f"{title} ({len(issues)}). {description}"
    (st.error if error else st.warning)(message)
    with st.expander("Mostra i campi e vai alla correzione", expanded=True):
        for label, widget_key in issues:
            anchor = _field_anchor_id(widget_key)
            st.markdown(
                f'<a href="#{anchor}">{html.escape(label)}</a>',
                unsafe_allow_html=True,
            )


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
    _field_anchor(widget_key)
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


def _apply_archived_premise(select_key, target_key, premises_by_id):
    premise = premises_by_id.get(st.session_state.get(select_key))
    if premise:
        st.session_state[target_key] = premise["content"]


def _render_premise_widget(
    name, label, initial, widget_key, premises_by_id, in_form=False,
    field_initials=None, show_selector=True,
):
    if show_selector:
        select_key = f"{widget_key}_archived_premise"
        archive_ready = bool(archive_database_url and not premises_error)
        if not archive_database_url:
            premise_ids = [None]
            unavailable_label = "Archivio non configurato"
        elif premises_error:
            premise_ids = [None]
            unavailable_label = "Premesse non disponibili"
        else:
            premise_ids = [None] + list(premises_by_id)
            unavailable_label = "Nessuna premessa salvata"
        st.selectbox(
            "Scegli una premessa salvata",
            premise_ids,
            format_func=lambda premise_id: (
                (
                    "Seleziona una premessa"
                    if archive_ready
                    else unavailable_label
                )
                if premise_id is None
                else premises_by_id[premise_id]["name"]
            ),
            key=select_key,
            disabled=not archive_ready,
            on_change=_apply_archived_premise if archive_ready and not in_form else None,
            args=(select_key, widget_key, premises_by_id),
        )
        if in_form:
            st.form_submit_button(
                "Carica premessa selezionata",
                key=f"{widget_key}_apply_archived_premise",
                disabled=not archive_ready or len(premise_ids) < 2,
                on_click=_apply_archived_premise,
                args=(select_key, widget_key, premises_by_id),
            )
        if premises_error:
            st.caption(f"Archivio delle premesse non disponibile: {premises_error}")
        elif not archive_database_url:
            st.caption("Configura ARCHIVE_DATABASE_URL per caricare o salvare premesse.")

    value = _render_field_widget(name, label, initial, widget_key, multiline=True)
    premise_fields = core.find_premise_fields(value)
    field_values = {}
    if premise_fields:
        st.markdown("**Dati della premessa**")
        for field in premise_fields:
            field_key = (
                f"{widget_key}_premise_field_{core._norm(field)}"
            )
            field_values[field] = st.text_input(
                field,
                value=(field_initials or {}).get(
                    field_key, st.session_state.get(field_key, "")
                ),
                key=field_key,
            )
    save_label = "💾 Salva premessa"
    if in_form:
        save_clicked = st.form_submit_button(
            save_label,
            key=f"{widget_key}_save_archived_premise",
            disabled=not archive_database_url,
        )
    else:
        save_clicked = st.button(
            save_label,
            key=f"{widget_key}_save_archived_premise",
            disabled=not archive_database_url,
        )
    invalid_fields = False
    try:
        filled_value = core.fill_premise_fields(value, field_values)
    except ValueError as error:
        st.error(f"Valore numerico non valido nella premessa: {error}")
        filled_value = value
        invalid_fields = True
    return filled_value, save_clicked, value, invalid_fields


@st.dialog("Salva premessa nell'archivio")
def _save_premise_dialog(premise_text):
    st.text_area(
        "Testo della premessa",
        value=premise_text,
        height=180,
        key="premise_dialog_content",
    )
    st.text_input("Titolo", key="premise_dialog_title")
    if st.button("Salva", type="primary", key="premise_dialog_save"):
        try:
            core.save_archive_premise(
                archive_database_url,
                st.session_state.get("premise_dialog_title", ""),
                st.session_state.get("premise_dialog_content", ""),
            )
        except (KeyError, ValueError) as error:
            st.error(str(error))
        except Exception as error:
            st.error(f"Impossibile salvare la premessa: {error}")
        else:
            invalidate_session_premises_cache()
            st.session_state["premise_archive_notice"] = "Premessa salvata nell'archivio."
            st.rerun()


def _open_premise_save_dialog(premise_text):
    st.session_state.pop("premise_dialog_content", None)
    st.session_state.pop("premise_dialog_title", None)
    _save_premise_dialog(premise_text)


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
    invalid_premise = False
    if "PREMESSA" in core._norm(key).upper():
        rendered_value, save_clicked, raw_value, invalid_premise = _render_premise_widget(
            key, label, initial, widget_key, premise_by_id
        )
        if save_clicked:
            _open_premise_save_dialog(raw_value)
    else:
        rendered_value = _render_field_widget(
            key, label, initial, widget_key,
            multiline=core._norm(key).upper() not in core.PREDEFINED,
        )
    try:
        return core.format_field_value(
            key, core.format_commission_value(key, rendered_value)
        ), invalid_premise
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


def session_archive_premises(database_url):
    cached = st.session_state.get("archive_premises_cache")
    if cached is None or cached["database_url"] != database_url:
        cached = {
            "database_url": database_url,
            "premises": core.list_archive_premises(database_url),
        }
        st.session_state["archive_premises_cache"] = cached
    return cached["premises"]


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


def invalidate_session_premises_cache():
    st.session_state.pop("archive_premises_cache", None)


def session_mass_drafts(database_url):
    cached = st.session_state.get("mass_drafts_cache")
    if cached is None or cached["database_url"] != database_url:
        cached = {
            "database_url": database_url,
            "drafts": core.list_mass_drafts(database_url),
        }
        st.session_state["mass_drafts_cache"] = cached
    return cached["drafts"]


def invalidate_session_drafts_cache():
    st.session_state.pop("mass_drafts_cache", None)


_MASS_DRAFT_COUNT_PREFIXES = ("mass_lr_count_", "mass_te_count_")


def _mass_draft_payload():
    state = st.session_state
    return {
        "version": 1,
        "phase": state.get("mass_phase", 1),
        "selected_records": state.get("mass_selected_records", []),
        "pending_records": state.get("mass_pending_records", []),
        "role_data": state.get("mass_role_data", {}),
        "manual_values": state.get("mass_manual_values", {}),
        "mandates": state.get("mass_mandates", []),
        "counts": {
            key: value for key, value in state.items()
            if key.startswith(_MASS_DRAFT_COUNT_PREFIXES)
        },
    }


def _restore_mass_draft(payload, draft):
    state = st.session_state
    for key in [
        key for key in state
        if key.startswith(("mass_value_", "mass_person_", "mass_role_", "mass_percentage_"))
        or key.startswith(_MASS_DRAFT_COUNT_PREFIXES)
    ]:
        del state[key]
    state["mass_phase"] = payload.get("phase", 1)
    state["mass_selected_records"] = payload.get("selected_records", [])
    state["mass_pending_records"] = payload.get(
        "pending_records", payload.get("selected_records", [])
    )
    state["mass_role_data"] = payload.get("role_data", {})
    state["mass_manual_values"] = payload.get("manual_values", {})
    state["mass_mandates"] = payload.get("mandates", [])
    state.update(payload.get("counts", {}))
    state.pop("mass_archive", None)
    state["mass_draft_id"] = draft["id"]
    state["mass_draft_name"] = draft["name"]


def _save_mass_draft(name):
    state = st.session_state
    try:
        draft_id = core.save_mass_draft(
            archive_database_url,
            name,
            _mass_draft_payload(),
            state.get("mass_draft_id"),
        )
    except Exception as error:
        st.error(f"Impossibile salvare la bozza: {error}")
        return
    state["mass_draft_id"] = draft_id
    state["mass_draft_name"] = str(name).strip()
    invalidate_session_drafts_cache()
    st.success(f"Bozza «{str(name).strip()}» salvata.")


def _render_draft_save_controls(key_prefix, on_click=None, args=None):
    """Nome e pulsante di salvataggio bozza da usare dentro un form."""
    if not archive_database_url or archive_error:
        st.caption("Salvataggio bozza non disponibile: archivio non configurato.")
        return False
    st.text_input(
        "Nome della bozza",
        value=st.session_state.get("mass_draft_name", ""),
        key=f"{key_prefix}_draft_name",
    )
    return st.form_submit_button(
        "💾 Salva bozza",
        key=f"{key_prefix}_draft_save",
        on_click=on_click,
        args=args,
    )


@st.dialog("Formato di generazione")
def _format_dialog(confirmed_key):
    choice = st.radio(
        "Cosa vuoi generare?",
        ["Solo PDF", "Documento Word", "Word e PDF"],
        format_func=lambda option: {
            "Solo PDF": "PDF",
            "Documento Word": "Word",
            "Word e PDF": "Entrambi (Word e PDF)",
        }[option],
        key=f"{confirmed_key}_choice",
    )
    if st.button("Genera", type="primary", key=f"{confirmed_key}_confirm"):
        st.session_state[confirmed_key] = choice
        st.rerun()


def _template_manual_keys(placeholders):
    """Segnaposto da compilare a mano (non provenienti dall'anagrafica o dai ruoli)."""
    keys = []
    for key in placeholders:
        base, role = core.split_role(key)
        normalized_base = core._norm(base).upper()
        if role:
            if normalized_base in {"CARICA", "RUOLO", "RUOLO_SOCIETARIO"}:
                continue
            if "PERCENT" in normalized_base or core.is_anagraphic_field(key):
                continue
        elif core.is_anagraphic_field(key):
            continue
        keys.append(key)
    return keys


def _render_checklist_import(bulk_records, mass_templates):
    manual_keys_by_type = {
        customer_type: _template_manual_keys(template["placeholders"])
        for customer_type, template in mass_templates.items()
    }

    def is_premise_key(key):
        return "PREMESSA" in core._norm(key).upper()

    other_keys = list(
        dict.fromkeys(
            key for keys in manual_keys_by_type.values() for key in keys
            if not is_premise_key(key)
        )
    )
    with st.expander("📥 Importa da lista di controllo (Excel)", expanded=False):
        st.caption(
            "Carica la lista interna: il programma cerca ogni nominativo nell'anagrafica "
            "(riconoscendo persona fisica o giuridica), collega le colonne ai campi della "
            "premessa e alle commissioni e precompila i mandati. Le righe TOTALE e le colonne "
            "senza corrispondenza vengono ignorate. Legale rappresentante e titolari effettivi "
            "restano quelli delle schede archiviate."
        )
        uploaded = st.file_uploader(
            "Lista di controllo (.xlsx / .xls)", type=["xlsx", "xls"], key="mass_checklist"
        )
        if not uploaded:
            return
        try:
            checklist = core.read_checklist(uploaded.getvalue(), uploaded.name)
        except Exception as error:
            st.error(f"Impossibile leggere la lista: {error}")
            return
        headers = checklist["headers"]
        name_col = core.find_checklist_column(headers, core.CHECKLIST_NAME_HEADERS)
        cf_col = core.find_checklist_column(headers, core.CHECKLIST_FISCAL_CODE_HEADERS)
        status_col = core.find_checklist_column(headers, core.CHECKLIST_STATUS_HEADERS)
        if name_col is None and cf_col is None:
            st.error(
                "Non trovo la colonna del nominativo: usa un'intestazione come "
                "«Cliente», «Nominativo» o «Ragione sociale» (oppure «Codice fiscale»)."
            )
            return
        file_id = hashlib.sha256(uploaded.getvalue()).hexdigest()[:10]

        premise_ids = [None] + list(premise_by_id)
        premise_id = st.selectbox(
            "Premessa da applicare a tutti i mandati",
            premise_ids,
            format_func=lambda value: (
                "Nessuna (lascia la premessa vuota)" if value is None
                else premise_by_id[value]["name"]
            ),
            key=f"cl_premise_{file_id}",
            disabled=not archive_premises,
        )
        premise_text = premise_by_id[premise_id]["content"] if premise_id else ""
        premise_labels = core.find_premise_fields(premise_text)

        targets = {}
        for label in [*other_keys, *premise_labels]:
            targets.setdefault(core._norm(label).upper(), label)
        auto_mapping = core.auto_map_columns(list(targets.values()), headers)
        column_options = [None] + [
            index for index, header in enumerate(headers) if header
        ]
        mapping = {}
        with st.expander("Corrispondenza colonne ↔ campi", expanded=True):
            if not targets:
                st.caption("I modelli e la premessa scelta non hanno campi da compilare.")
            for norm_name, label in targets.items():
                default = auto_mapping.get(label)
                chosen = st.selectbox(
                    label.replace("_", " ").capitalize(),
                    column_options,
                    index=column_options.index(default),
                    format_func=lambda index: (
                        "— non importare —" if index is None else headers[index]
                    ),
                    key=f"cl_map_{file_id}_{premise_id}_{norm_name}",
                )
                if chosen is not None:
                    mapping[norm_name] = chosen

        status_filter = None
        if status_col is not None:
            statuses = list(dict.fromkeys(
                row["cells"][status_col] for row in checklist["rows"]
                if row["cells"][status_col]
            ))
            if statuses:
                status_filter = set(st.multiselect(
                    f"Importa solo le righe con «{headers[status_col]}»",
                    statuses,
                    default=statuses,
                    key=f"cl_status_{file_id}",
                ))

        candidates = [
            (option, customer_type, record, core.record_label(customer_type, record))
            for option, (customer_type, record) in bulk_records.items()
        ]
        index = core.build_record_index(candidates)
        report, matched = [], {}
        for row in checklist["rows"]:
            cells = row["cells"]
            name = cells[name_col] if name_col is not None else ""
            fiscal_code = cells[cf_col] if cf_col is not None else ""
            if (not name and not fiscal_code) or core.is_checklist_total_row(name):
                continue
            if status_filter is not None and status_col is not None and (
                cells[status_col] not in status_filter
            ):
                continue
            outcome, options = core.match_checklist_row(index, name, fiscal_code)
            found_type, found_label, note = "", "", ""
            if outcome == "ok":
                option = options[0]
                found_type = (
                    "Persona giuridica" if bulk_records[option][0] == "giuridica"
                    else "Persona fisica"
                )
                found_label = index["label"][option]
                if option in matched:
                    note = "Duplicato: riga ignorata"
                else:
                    matched[option] = cells
                    note = "✅ Trovato"
            elif outcome == "ambiguous":
                note = f"⚠️ {len(options)} anagrafiche omonime: selezionala a mano"
            elif outcome == "similar":
                note = "⚠️ Non trovato, simile a: " + ", ".join(
                    index["label"][option] for option in options
                )
            else:
                note = "❌ Non presente nell'anagrafica (o manca il modello del tipo)"
            report.append(
                {
                    "Riga": row["row"],
                    "Nominativo in lista": name or fiscal_code,
                    "Tipo": found_type,
                    "Anagrafica trovata": found_label,
                    "Esito": note,
                }
            )
        if report:
            st.dataframe(report, hide_index=True, width="stretch")
        unused = [
            header for column, header in enumerate(headers)
            if header and column not in mapping.values()
            and column not in (name_col, cf_col, status_col)
        ]
        if unused:
            st.caption("Colonne non utilizzate: " + ", ".join(unused))
        nominal_column = core.nominal_capital_column(headers)
        missing_targets = [
            label for norm_name, label in targets.items()
            if norm_name not in mapping
            and not (nominal_column is not None and core.is_share_cost_field(label))
        ]
        if nominal_column is not None and any(
            core.is_share_cost_field(label) and norm_name not in mapping
            for norm_name, label in targets.items()
        ):
            st.caption(
                "Costo del capitale sociale senza colonna: verrà usato il valore "
                f"nominale («{headers[nominal_column]}»)."
            )
        if missing_targets:
            st.caption(
                "Campi senza colonna (da compilare a mano): "
                + ", ".join(label.replace("_", " ").lower() for label in missing_targets)
            )
        if not matched:
            st.warning("Nessuna riga corrisponde alle anagrafiche disponibili.")
            return
        if st.button(f"Importa {len(matched)} mandati", type="primary", key=f"cl_apply_{file_id}"):
            saved_values = st.session_state.setdefault("mass_manual_values", {})
            for option, cells in matched.items():
                customer_type, record = bulk_records[option]
                record_key = core._norm(core.record_identity(record))
                prefix = f"mass_value_{record_key}_"
                for state_key in [k for k in st.session_state if k.startswith(prefix)]:
                    del st.session_state[state_key]
                for state_key in [k for k in saved_values if k.startswith(prefix)]:
                    del saved_values[state_key]
                manual_keys = manual_keys_by_type[customer_type]
                for key in manual_keys:
                    widget_key = f"{prefix}{core._norm(key)}"
                    if is_premise_key(key):
                        if premise_text:
                            saved_values[widget_key] = premise_text
                        for label in premise_labels:
                            column = mapping.get(core._norm(label).upper())
                            cell = core.checklist_cell_value(label, cells, column, headers)
                            if cell:
                                saved_values[
                                    f"{widget_key}_premise_field_{core._norm(label)}"
                                ] = core.checklist_value(label, cell)
                    else:
                        column = mapping.get(core._norm(key).upper())
                        cell = core.checklist_cell_value(key, cells, column, headers)
                        if cell:
                            saved_values[widget_key] = core.checklist_value(key, cell)
            st.session_state["mass_pending_records"] = list(matched)
            st.success(
                f"{len(matched)} anagrafiche selezionate e precompilate: controlla "
                "l'elenco qui sotto e conferma la selezione."
            )


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
        field_prefix = f"{widget_key}_premise_field_"
        for state_key in st.session_state:
            if state_key.startswith(field_prefix):
                saved_values[state_key] = st.session_state[state_key]


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


def _document_archive_roles(role_data, values):
    archive_roles = {}
    for role, info in role_data.items():
        percentage_key = next(
            (
                key for key in info["keys"]
                if "PERCENT" in core._norm(core.split_role(key)[0]).upper()
            ),
            None,
        )
        archive_roles[role] = {
            "person": info["person"],
            "role": info["carica"] or "",
            "percentage": values.get(percentage_key, "") if percentage_key else "",
        }
    return archive_roles


archive_profiles, archive_error = [], None
if archive_database_url:
    try:
        archive_profiles = session_archive_profiles(archive_database_url)
    except Exception as error:
        archive_error = str(error)

archive_premises, premises_error = [], None
if archive_database_url:
    try:
        archive_premises = session_archive_premises(archive_database_url)
    except Exception as error:
        premises_error = str(error)
premise_by_id = {premise["id"]: premise for premise in archive_premises}

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

st.title("Precompilazione documenti")

profile_by_id = {profile["id"]: profile for profile in archive_profiles}
PAGES = {
    "single": ("✍️", "Singolo documento", "Un solo mandato, compilato a mano."),
    "excel": ("📊", "Massiva con Excel", "Più mandati da una lista di controllo."),
    "manual": ("📚", "Massiva manuale", "Più mandati scegliendo le anagrafiche."),
    "db": ("⚙️", "Database", "Anagrafica e modelli."),
    "archive": ("🗂️", "Archivio", "Persone giuridiche archiviate."),
    "premises": ("📝", "Premesse", "Premesse archiviate."),
}
MAIN_PAGES = ("single", "excel", "manual")
page = st.session_state.get("gen_mode")
if page not in PAGES:
    page = None
tab_gen = st.container()

if notice := st.session_state.pop("premise_archive_notice", None):
    st.success(notice)

if page is None:
    st.markdown(
        """
<style>
[class*="st-key-gen_mode_"] button {
    min-height: 11rem; font-size: 1.4rem; white-space: pre-wrap;
}
[class*="st-key-gen_mode_"] button p { font-size: 1.4rem; }
[class*="st-key-gen_aux_"] button { min-height: 3rem; }
</style>
""",
        unsafe_allow_html=True,
    )
    st.subheader("Che cosa vuoi fare?")
    for page_key, page_col in zip(MAIN_PAGES, st.columns(len(MAIN_PAGES))):
        icon, title, help_text = PAGES[page_key]
        if page_col.button(
            f"{icon}\n\n**{title}**\n\n{help_text}",
            key=f"gen_mode_{page_key}",
            use_container_width=True,
        ):
            st.session_state["gen_mode"] = page_key
            st.rerun()
    st.divider()
    aux_keys = [key for key in PAGES if key not in MAIN_PAGES]
    for page_key, page_col in zip(aux_keys, st.columns(len(aux_keys))):
        icon, title, _ = PAGES[page_key]
        if page_col.button(
            f"{icon} {title}", key=f"gen_aux_{page_key}", use_container_width=True
        ):
            st.session_state["gen_mode"] = page_key
            st.rerun()
else:
    back_col, label_col = st.columns([1, 4], vertical_alignment="center")
    if back_col.button("← Menu iniziale", key="gen_back"):
        st.session_state.pop("gen_mode")
        st.rerun()
    icon, title, _ = PAGES[page]
    label_col.markdown(f"### {icon} {title}")

if page == "single":
    with tab_gen:
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
                title_col, generate_col = st.columns([3, 1])
                title_col.subheader("Dati")
                generate_slot = generate_col.container()
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
                te_roles = sorted(
                    (r for r in roles if r.startswith("TE")),
                    key=lambda r: int(r[2:]) if r[2:].isdigit() else 0,
                )
                hidden_te_keys = []
                if te_roles:
                    te_scope = (
                        selected_archive["id"] if selected_archive else "manual",
                        ctype,
                    )
                    if st.session_state.get("doc_te_scope") != te_scope:
                        st.session_state["doc_te_scope"] = te_scope
                        st.session_state["doc_te_count"] = max(
                            1,
                            len(selected_archive["payload"].get("owners", []))
                            if selected_archive else 1,
                        )
                    doc_te_count = min(st.session_state["doc_te_count"], len(te_roles))
                    st.session_state["doc_te_count"] = doc_te_count
                    for hidden_role in te_roles[doc_te_count:]:
                        hidden_te_keys.extend(roles.pop(hidden_role))
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
                value_widget_keys = {}
                invalid_field_issues = []
                role_data = {}
                premise_errors = {"invalid": False}
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
                            elif role.startswith("LR") and role[2:].isdigit():
                                representatives = payload.get(
                                    "additional_legal_representatives", []
                                )
                                representative_index = int(role[2:]) - 2
                                representative = (
                                    representatives[representative_index]
                                    if representative_index < len(representatives)
                                    else None
                                )
                                person = representative.get("person", {}) if representative else {}
                                carica = representative.get("role", "") if representative else ""
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
                            value_widget_keys[key] = k
                            if "PREMESSA" in core._norm(base).upper():
                                (
                                    rendered_value,
                                    save_clicked,
                                    premise_text,
                                    invalid_premise,
                                ) = _render_premise_widget(
                                    base, label, init, k, premise_by_id
                                )
                                premise_errors["invalid"] |= invalid_premise
                                if invalid_premise:
                                    invalid_field_issues.append((label, k))
                                if save_clicked:
                                    _open_premise_save_dialog(premise_text)
                            else:
                                rendered_value = _render_field_widget(base, label, init, k)
                            values[key] = core.format_field_value(
                                base, rendered_value
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

                for hidden_key in hidden_te_keys:
                    values[hidden_key] = ""
                if te_roles:
                    te_add_col, te_remove_col = st.columns(2)
                    if doc_te_count < len(te_roles) and te_add_col.button(
                        "Aggiungi titolare effettivo", key="doc_add_te"
                    ):
                        st.session_state["doc_te_count"] = doc_te_count + 1
                        st.rerun()
                    if doc_te_count > 1 and te_remove_col.button(
                        "Rimuovi ultimo titolare effettivo", key="doc_remove_te"
                    ):
                        st.session_state["doc_te_count"] = doc_te_count - 1
                        st.rerun()

                st.markdown("**Campi del documento**")
                invalid_commission = premise_errors["invalid"]
                visible_main_keys = [key for key in main_keys if not core.is_anagraphic_field(key)]
                anagraphic_main_keys = [key for key in main_keys if core.is_anagraphic_field(key)]
                for key in visible_main_keys:
                    value_widget_keys[key] = f"v_{rid}_{key}{_field_widget_revision(key)}"
                    values[key], invalid = _render_document_field(key, rec, mapping, rid)
                    invalid_commission |= invalid
                    if invalid:
                        invalid_field_issues.append(
                            (key.replace("_", " ").capitalize(), value_widget_keys[key])
                        )
                if anagraphic_main_keys:
                    with st.expander("Dati anagrafici", expanded=False):
                        for key in anagraphic_main_keys:
                            value_widget_keys[key] = f"v_{rid}_{key}{_field_widget_revision(key)}"
                            values[key], invalid = _render_document_field(key, rec, mapping, rid)
                            invalid_commission |= invalid
                            if invalid:
                                invalid_field_issues.append(
                                    (key.replace("_", " ").capitalize(), value_widget_keys[key])
                                )

                _render_field_issues(
                    "Valori non validi da correggere",
                    invalid_field_issues,
                    "Usa i collegamenti per raggiungere direttamente i campi.",
                    error=True,
                )
                missing_value_issues = [
                    (
                        key.replace("_", " ").capitalize(),
                        value_widget_keys[key],
                    )
                    for key in placeholders
                    if not str(values.get(key, "") or "").strip()
                    and key in value_widget_keys
                ]
                _render_field_issues(
                    "Segnaposto vuoti",
                    missing_value_issues,
                    "Un campo vuoto non è necessariamente obbligatorio; il documento "
                    "può comunque essere generato.",
                )

                if not placeholders:
                    st.warning("Nessun segnaposto trovato (es. [NOME], [COGNOME]).")

                matching_archive_profile = (
                    next(
                        (
                            profile for profile in archive_profiles
                            if core.record_identity(profile["payload"]["company"])
                            == core.record_identity(rec)
                        ),
                        None,
                    )
                    if ctype == "giuridica" and rec else None
                )
                if (
                    archive_database_url
                    and not archive_error
                    and not selected_archive
                    and not matching_archive_profile
                    and ctype == "giuridica"
                    and rec
                    and "LR" in role_data
                ):
                    with st.expander("Salva questa anagrafica nell'archivio"):
                        default_name = core.record_label(ctype, rec)
                        save_name = st.text_input("Nome della scheda", value=default_name, key=f"doc_save_name_{rid}")
                        if st.button("Salva anagrafica", key="doc_save_profile"):
                            try:
                                payload = core.archive_payload_from_mass_roles(
                                    rec, _document_archive_roles(role_data, values)
                                )
                                core.save_archive_profile(
                                    archive_database_url,
                                    save_name,
                                    payload,
                                )
                            except (KeyError, ValueError) as error:
                                st.error(str(error))
                            except Exception as error:
                                st.error(f"Impossibile salvare la scheda: {error}")
                            else:
                                invalidate_session_profiles_cache()
                                st.success("Anagrafica salvata nell'archivio.")

                output_format = st.session_state.pop("single_format_confirmed", None)
                if generate_slot.button(
                    "Genera documento", type="primary", disabled=invalid_commission,
                    use_container_width=True,
                ):
                    _format_dialog("single_format_confirmed")
                if output_format:
                    fields = [{"name": k, "tokens": t} for k, t in placeholders.items()]
                    with st.spinner("Generazione..."):
                        out = core.render(data, fields, values)
                        st.session_state["out"] = (
                            None if output_format == "Solo PDF"
                            else core.convert(out, "docx", "doc") if fmt == "doc" else out
                        )
                        st.session_state["out_pdf"] = (
                            core.convert(out, "docx", "pdf")
                            if output_format != "Documento Word" else None
                        )
                    if (
                        ctype == "giuridica"
                        and rec
                        and not selected_archive
                        and not matching_archive_profile
                    ):
                        if not archive_database_url:
                            st.warning(
                                "Documento generato, ma la scheda non è stata salvata: "
                                "l'archivio non è configurato."
                            )
                        elif archive_error:
                            st.warning(
                                "Documento generato, ma non è stato possibile verificare "
                                f"l'archivio: {archive_error}"
                            )
                        else:
                            try:
                                payload = core.archive_payload_from_mass_roles(
                                    rec, _document_archive_roles(role_data, values)
                                )
                                core.save_archive_profile(
                                    archive_database_url,
                                    core.record_label(ctype, rec),
                                    payload,
                                )
                            except Exception as error:
                                st.error(
                                    "Documento generato, ma impossibile salvare "
                                    f"automaticamente la scheda: {error}"
                                )
                            else:
                                invalidate_session_profiles_cache()
                                st.success(
                                    "Scheda della persona giuridica salvata "
                                    "automaticamente nell'archivio."
                                )
                if st.session_state.get("out"):
                    st.download_button(
                        "Scarica documento compilato", st.session_state["out"],
                        file_name=f"{source_name.rsplit('.', 1)[0]}_compilato.{fmt}",
                        mime="application/msword" if fmt == "doc"
                        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                if st.session_state.get("out_pdf"):
                    st.download_button(
                        "Scarica PDF", st.session_state["out_pdf"],
                        file_name=f"{source_name.rsplit('.', 1)[0]}_compilato.pdf",
                        mime="application/pdf",
                    )

            with right:
                st.subheader("Anteprima")
                st.caption("Bordo rosso: campo non compilato. Verde: valore inserito.")
                fields = [{"name": k, "tokens": t} for k, t in placeholders.items()]
                with st.container(height=800, border=True):
                    with st.spinner("Aggiornamento anteprima..."):
                        for img in cached_preview(data, json.dumps(fields), json.dumps(values)):
                            st.image(img, width="stretch")

if page in ("excel", "manual"):
    with tab_gen:
        mass_templates = {}
        with st.popover("Carica modello"):
            for customer_type, label in core.CUSTOMER_TYPES.items():
                st.file_uploader(
                    f"Modello {label.lower()} (.doc / .docx)",
                    type=["doc", "docx"],
                    key=f"mass_template_{customer_type}",
                )
        for customer_type, label in core.CUSTOMER_TYPES.items():
            uploaded_template = st.session_state.get(f"mass_template_{customer_type}")
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
            st.warning("Carica o configura prima un'anagrafica nella sezione Database.")
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
                with st.expander(
                    "📂 Bozze salvate"
                    + (
                        f" — in uso: {st.session_state['mass_draft_name']}"
                        if st.session_state.get("mass_draft_name") else ""
                    ),
                    expanded=False,
                ):
                    if not archive_database_url:
                        st.caption("Configura ARCHIVE_DATABASE_URL per salvare e riprendere le bozze.")
                    elif archive_error:
                        st.caption(f"Archivio non disponibile: {archive_error}")
                    else:
                        try:
                            mass_drafts = session_mass_drafts(archive_database_url)
                        except Exception as error:
                            mass_drafts = []
                            st.error(f"Impossibile caricare le bozze: {error}")
                        if not mass_drafts:
                            st.caption(
                                "Nessuna bozza salvata. Usa «Salva bozza» in una qualsiasi fase."
                            )
                        else:
                            draft_by_id = {draft["id"]: draft for draft in mass_drafts}
                            chosen_draft_id = st.selectbox(
                                "Bozza",
                                list(draft_by_id),
                                format_func=lambda draft_id: (
                                    f"{draft_by_id[draft_id]['name']} — "
                                    f"{draft_by_id[draft_id]['updated_at']:%d/%m/%Y %H:%M}"
                                ),
                                key="mass_draft_choice",
                            )
                            resume_col, delete_col = st.columns(2)
                            if resume_col.button("Riprendi bozza", type="primary", key="mass_draft_resume"):
                                _restore_mass_draft(
                                    draft_by_id[chosen_draft_id]["payload"],
                                    draft_by_id[chosen_draft_id],
                                )
                                st.rerun()
                            if delete_col.button("Elimina bozza", key="mass_draft_delete"):
                                try:
                                    core.delete_mass_draft(archive_database_url, chosen_draft_id)
                                except Exception as error:
                                    st.error(f"Impossibile eliminare la bozza: {error}")
                                else:
                                    if st.session_state.get("mass_draft_id") == chosen_draft_id:
                                        st.session_state.pop("mass_draft_id", None)
                                        st.session_state.pop("mass_draft_name", None)
                                    invalidate_session_drafts_cache()
                                    st.rerun()
                st.session_state.setdefault("mass_phase", 1)
                if st.session_state["mass_phase"] == 1:
                    st.progress(1 / 3, text="Fase 1 di 3 — Seleziona le anagrafiche")
                    st.caption("Scegli le persone e le società per cui creare i mandati.")
                    if page == "excel":
                        _render_checklist_import(bulk_records, mass_templates)
                    st.session_state["mass_pending_records"] = [
                        option
                        for option in st.session_state.get(
                            "mass_pending_records",
                            st.session_state.get("mass_selected_records", []),
                        )
                        if option in bulk_records
                    ]
                    with st.form("mass_record_selection"):
                        _field_anchor("mass_pending_records")
                        st.multiselect(
                            "Anagrafiche da includere",
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
                        draft_save_clicked = _render_draft_save_controls("mass_p1")
                    if draft_save_clicked:
                        _save_mass_draft(st.session_state["mass_p1_draft_name"])
                    if selection_submitted:
                        selected_keys = st.session_state["mass_pending_records"]
                        if not selected_keys:
                            st.error("Seleziona almeno un'anagrafica.")
                            _render_field_issues(
                                "Seleziona almeno un'anagrafica",
                                [("Anagrafiche da includere", "mass_pending_records")],
                                "Apri il selettore e scegli una o più persone.",
                                error=True,
                            )
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
                                saved_representatives = []
                                representative = payload.get("legal_representative")
                                if representative:
                                    saved_representatives.append(
                                        {
                                            "person": representative,
                                            "role": payload.get("representative_role", ""),
                                        }
                                    )
                                saved_representatives.extend(
                                    payload.get("additional_legal_representatives", [])
                                )
                                st.session_state.setdefault(
                                    f"mass_lr_count_{company_key}",
                                    max(1, len(saved_representatives)),
                                )
                                st.session_state.setdefault(
                                    f"mass_te_count_{company_key}",
                                    max(1, len(saved_owners)),
                                )
                                if option in st.session_state["mass_role_data"]:
                                    continue
                                role_data = {}
                                for number, saved_representative in enumerate(
                                    saved_representatives, 1
                                ):
                                    role = "LR" if number == 1 else f"LR{number}"
                                    role_data[role] = {
                                        "person": saved_representative.get("person", {}),
                                        "role": saved_representative.get("role", ""),
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
                    st.progress(2 / 3, text="Fase 2 di 3 — Completa ruoli e incarichi")
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
                        back_to_selection = st.form_submit_button(
                            "← Torna alla selezione delle anagrafiche",
                            on_click=_normalize_percentage_widgets,
                            args=(percentage_keys, percentage_error_key),
                        )
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
                                    _field_anchor(person_key)
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
                                    _field_anchor(role_key)
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
                                        _field_anchor(
                                            f"mass_role_other_{company_key}_{role}"
                                        )
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
                                    _field_anchor(person_key)
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
                                    _field_anchor(percentage_key)
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

                        next_to_manual = st.form_submit_button(
                            "Conferma i ruoli e passa alla fase 3",
                            type="primary",
                            disabled=not selected_keys,
                            on_click=_normalize_percentage_widgets,
                            args=(percentage_keys, percentage_error_key),
                        )
                        draft_save_clicked = _render_draft_save_controls(
                            "mass_p2",
                            on_click=_normalize_percentage_widgets,
                            args=(percentage_keys, percentage_error_key),
                        )

                    if back_to_selection or next_to_manual or add_or_remove or draft_save_clicked:
                        _save_mass_role_widgets(selected_corporates, people)
                    if draft_save_clicked:
                        _save_mass_draft(st.session_state["mass_p2_draft_name"])
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
                        validation_issues = []
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
                                        validation_issues.append(
                                            (
                                                f"{core.record_label(customer_type, record)} — "
                                                f"{core.role_label(role)}",
                                                f"mass_person_{company_key}_{role}",
                                            )
                                        )
                                        errors.append(
                                            f"{core.record_label(customer_type, record)}: "
                                            f"salva {core.role_label(role).lower()}."
                                        )
                                    elif role.startswith("LR") and not role_data.get("role"):
                                        role_widget_key = f"mass_role_{company_key}_{role}"
                                        if st.session_state.get(role_widget_key) == "Altro":
                                            role_widget_key = (
                                                f"mass_role_other_{company_key}_{role}"
                                            )
                                        validation_issues.append(
                                            (
                                                f"{core.record_label(customer_type, record)} — "
                                                f"carica di {core.role_label(role)}",
                                                role_widget_key,
                                            )
                                        )
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
                                            validation_issues.append(
                                                (
                                                    f"{core.record_label(customer_type, record)} — "
                                                    f"percentuale di {core.role_label(role)}",
                                                    f"mass_percentage_{company_key}_{role}",
                                                )
                                            )
                                            errors.append(
                                                f"{core.record_label(customer_type, record)}: "
                                                f"completa la percentuale di "
                                                f"{core.role_label(role).lower()}."
                                            )
                            mandates.append(mandate)
                        if errors:
                            st.error(" ".join(errors))
                            _render_field_issues(
                                "Dati obbligatori da completare",
                                validation_issues,
                                "Usa i collegamenti per raggiungere direttamente i campi.",
                                error=True,
                            )
                        else:
                            saved_profiles = []
                            archive_save_errors = []
                            if archive_database_url and not archive_error:
                                profile_by_identity = {
                                    core.record_identity(profile["payload"]["company"]): profile
                                    for profile in archive_profiles
                                }
                                auto_saved_profiles = st.session_state.setdefault(
                                    "mass_auto_saved_profile_ids", {}
                                )
                                for mandate in mandates:
                                    if mandate["customer_type"] != "giuridica":
                                        continue
                                    record = mandate["record"]
                                    company_identity = core.record_identity(record)
                                    profile_id = auto_saved_profiles.get(company_identity)
                                    if (
                                        company_identity in profile_by_identity
                                        and not profile_id
                                    ):
                                        continue
                                    company_name = core.record_label("giuridica", record)
                                    try:
                                        payload = core.archive_payload_from_mass_roles(
                                            record, mandate["roles"]
                                        )
                                        profile_id = core.save_archive_profile(
                                            archive_database_url,
                                            company_name,
                                            payload,
                                            profile_id=profile_id,
                                        )
                                    except Exception as error:
                                        archive_save_errors.append(
                                            f"{company_name}: {error}"
                                        )
                                    else:
                                        auto_saved_profiles[company_identity] = profile_id
                                        saved_profiles.append(company_name)
                                        profile_by_identity[company_identity] = {
                                            "id": profile_id,
                                            "payload": payload,
                                        }
                            elif archive_database_url and archive_error:
                                archive_save_errors.append(
                                    "Impossibile verificare le schede già presenti: "
                                    f"{archive_error}"
                                )
                            elif any(
                                mandate["customer_type"] == "giuridica"
                                for mandate in mandates
                            ):
                                archive_save_errors.append(
                                    "Archivio non configurato: le schede delle persone "
                                    "giuridiche non possono essere salvate."
                                )
                            if saved_profiles:
                                invalidate_session_profiles_cache()
                            st.session_state["mass_archive_save_notice"] = (
                                "Schede salvate automaticamente nell'archivio: "
                                + ", ".join(saved_profiles)
                                if saved_profiles else ""
                            )
                            st.session_state["mass_archive_save_errors"] = (
                                archive_save_errors
                            )
                            st.session_state["mass_mandates"] = mandates
                            st.session_state["mass_phase"] = 3
                            st.session_state.pop("mass_archive", None)
                            st.rerun()
                else:
                    st.progress(1.0, text="Fase 3 di 3 — Completa i dati e genera i mandati")
                    mandates = st.session_state.get("mass_mandates", [])
                    if not mandates:
                        st.session_state["mass_phase"] = 1
                        st.rerun()
                    st.info(
                        "Inserisci le variabili specifiche per ciascun mandato. "
                        "I dati anagrafici e gli incarichi arrivano dalla fase 2."
                    )
                    if notice := st.session_state.pop("mass_archive_save_notice", ""):
                        st.success(notice)
                    for error in st.session_state.pop("mass_archive_save_errors", []):
                        st.error(f"Salvataggio automatico nell'archivio non riuscito: {error}")
                    mass_values_by_mandate = []
                    invalid_bulk_fields = False
                    invalid_bulk_issues = []
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
                    premise_save_request = None
                    mass_output_format = st.session_state.pop("mass_format_confirmed", None)
                    mass_left, mass_right = st.columns([2, 3], gap="large")
                    with mass_left:
                        with st.form("mass_values_form"):
                            top_left, top_right = st.columns([3, 1])
                            back_to_roles = top_left.form_submit_button(
                                "← Torna alla fase 2 — LR e TE",
                                on_click=_save_mass_manual_values,
                                args=(manual_widget_keys,),
                            )
                            generate_clicked = top_right.form_submit_button(
                                "Genera i mandati",
                                type="primary",
                                use_container_width=True,
                                disabled=invalid_bulk_fields or not mass_values_by_mandate,
                            )
                            for (
                                mandate, template, placeholders, values, label, manual_keys
                            ) in mass_values_by_mandate:
                                record_key = core._norm(
                                    core.record_identity(mandate["record"])
                                )
                                with st.expander(
                                    f"Mandato — {label}",
                                    expanded=True,
                                ):
                                    if manual_keys:
                                        st.markdown("**Premessa, commissioni e altre variabili**")
                                        for key in manual_keys:
                                            field_label = key.replace("_", " ").capitalize()
                                            widget_key = (
                                                f"mass_value_{record_key}_{core._norm(key)}"
                                            )
                                            if "PREMESSA" in core._norm(key).upper():
                                                (
                                                    rendered_value,
                                                    save_clicked,
                                                    premise_text,
                                                    invalid_premise,
                                                ) = _render_premise_widget(
                                                    key,
                                                    field_label,
                                                    saved_manual_values.get(widget_key, ""),
                                                    widget_key,
                                                    premise_by_id,
                                                    in_form=True,
                                                    field_initials=saved_manual_values,
                                                    show_selector=page != "excel",
                                                )
                                                invalid_bulk_fields |= invalid_premise
                                                if invalid_premise:
                                                    invalid_bulk_issues.append(
                                                        (field_label, widget_key)
                                                    )
                                                if save_clicked:
                                                    premise_save_request = premise_text
                                            else:
                                                rendered_value = _render_field_widget(
                                                    key,
                                                    field_label,
                                                    saved_manual_values.get(widget_key, ""),
                                                    widget_key,
                                                    multiline=key not in core.PREDEFINED,
                                                )
                                            try:
                                                values[key] = core.format_field_value(
                                                    key,
                                                    core.format_commission_value(
                                                        key, rendered_value
                                                    ),
                                                )
                                            except ValueError as error:
                                                invalid_bulk_fields = True
                                                invalid_bulk_issues.append(
                                                    (field_label, widget_key)
                                                )
                                                st.error(f"{field_label}: {error}")
                                    else:
                                        st.caption("Il modello non contiene variabili manuali.")
                            st.form_submit_button("Aggiorna anteprima")
                            draft_save_clicked = _render_draft_save_controls(
                                "mass_p3",
                                on_click=_save_mass_manual_values,
                                args=(manual_widget_keys,),
                            )

                    _render_field_issues(
                        "Valori non validi da correggere",
                        invalid_bulk_issues,
                        "Usa i collegamenti per raggiungere direttamente i campi.",
                        error=True,
                    )
                    if invalid_bulk_fields and not invalid_bulk_issues:
                        st.error(
                            "Non è possibile generare i documenti: controlla gli errori "
                            "mostrati nei campi o verifica che tutti i modelli siano validi."
                        )

                    if premise_save_request is not None:
                        _open_premise_save_dialog(premise_save_request)

                    if draft_save_clicked:
                        _save_mass_draft(st.session_state["mass_p3_draft_name"])

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
                    with mass_right:
                        st.subheader("Anteprima")
                        st.caption("Bordo rosso: campo non compilato. Verde: valore inserito. Premi «Aggiorna anteprima» dopo le modifiche.")
                        if mass_values_by_mandate:
                            preview_index = st.selectbox(
                                "Mandato da visualizzare",
                                range(len(mass_values_by_mandate)),
                                format_func=lambda number: mass_values_by_mandate[number][4],
                                key="mass_preview_index",
                            )
                            _, preview_template, preview_placeholders, preview_values, _, _ = (
                                mass_values_by_mandate[preview_index]
                            )
                            preview_fields = [
                                {"name": key, "tokens": tokens}
                                for key, tokens in preview_placeholders.items()
                            ]
                            with st.container(height=800, border=True):
                                with st.spinner("Aggiornamento anteprima..."):
                                    for image in cached_preview(
                                        preview_template["docx"],
                                        json.dumps(preview_fields),
                                        json.dumps(preview_values),
                                    ):
                                        st.image(image, width="stretch")
                    with mass_left:
                        missing_required = []
                        required_field_issues = []
                        for mandate, _, _, values, label, manual_keys in mass_values_by_mandate:
                            premessa_keys = [
                                key for key in manual_keys
                                if "PREMESSA" in core._norm(key).upper()
                            ]
                            commission_keys = [
                                key for key in manual_keys
                                if core._norm(key).upper() in core._COMMISSION_FIELDS
                            ]
                            missing = []
                            if premessa_keys and not any(
                                str(values.get(key, "")).strip() for key in premessa_keys
                            ):
                                missing.append("premessa")
                                required_field_issues.extend(
                                    (
                                        f"{label} — {key.replace('_', ' ').capitalize()}",
                                        (
                                            f"mass_value_"
                                            f"{core._norm(core.record_identity(mandate['record']))}_"
                                            f"{core._norm(key)}"
                                        ),
                                    )
                                    for key in premessa_keys
                                )
                            if commission_keys and not any(
                                str(values.get(key, "")).strip() for key in commission_keys
                            ):
                                missing.append("almeno una commissione")
                                required_field_issues.extend(
                                    (
                                        f"{label} — {key.replace('_', ' ').capitalize()}",
                                        (
                                            f"mass_value_"
                                            f"{core._norm(core.record_identity(mandate['record']))}_"
                                            f"{core._norm(key)}"
                                        ),
                                    )
                                    for key in commission_keys
                                )
                            if missing:
                                missing_required.append(f"{label}: {' e '.join(missing)}")
                        _render_field_issues(
                            "Campi obbligatori da completare",
                            required_field_issues,
                            "Compila almeno una premessa e/o una commissione dove richiesto.",
                        )
                        if generate_clicked and missing_required:
                            st.error(
                                "Generazione bloccata. Compila i campi obbligatori:\n\n"
                                + "\n".join(f"- {item}" for item in missing_required)
                            )
                        if (
                            generate_clicked
                            and not invalid_bulk_fields
                            and not missing_required
                        ):
                            _format_dialog("mass_format_confirmed")
                        if (
                            mass_output_format
                            and not invalid_bulk_fields
                            and not missing_required
                        ):
                            documents = []
                            used_names = set()
                            progress = st.progress(0.0, text="Generazione dei documenti...")
                            with st.spinner("Generazione dei documenti..."):
                                for position, (
                                    mandate, template, placeholders, values, label, _
                                ) in enumerate(mass_values_by_mandate, 1):
                                    fields = [
                                        {"name": key, "tokens": tokens}
                                        for key, tokens in placeholders.items()
                                    ]
                                    docx_output = core.render(template["docx"], fields, values)
                                    filename_base = core._norm(label).replace("_", " ") or "anagrafica"
                                    stem = f"Mandato {filename_base}"
                                    duplicate = 2
                                    while f"{stem}.pdf".casefold() in used_names:
                                        stem = f"Mandato {filename_base} ({duplicate})"
                                        duplicate += 1
                                    used_names.add(f"{stem}.pdf".casefold())
                                    if mass_output_format != "Solo PDF":
                                        extension = template["format"]
                                        output = (
                                            core.convert(docx_output, "docx", "doc")
                                            if extension == "doc" else docx_output
                                        )
                                        documents.append((f"{stem}.{extension}", output))
                                    if mass_output_format != "Documento Word":
                                        documents.append(
                                            (f"{stem}.pdf", core.convert(docx_output, "docx", "pdf"))
                                        )
                                    progress.progress(
                                        position / len(mass_values_by_mandate),
                                        text=f"Generati {position} di {len(mass_values_by_mandate)} mandati",
                                    )
                            progress.empty()
                            st.session_state["mass_archive"] = core.create_document_archive(
                                documents
                            )
                            st.session_state["mass_archive_signature"] = (
                                mass_signature + mass_output_format
                            )

                        if (
                            st.session_state.get("mass_archive")
                            and str(st.session_state.get("mass_archive_signature", "")).startswith(
                                mass_signature
                            )
                        ):
                            st.download_button(
                                "Scarica i mandati separati (ZIP)",
                                st.session_state["mass_archive"],
                                file_name="Mandati_massivi.zip",
                                mime="application/zip",
                                key="mass_download",
                            )

if page == "archive":
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
                "nella sezione Database. Le schede già salvate restano disponibili."
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
                        "additional_legal_representatives": (
                            saved_profile["payload"].get(
                                "additional_legal_representatives", []
                            )
                            if saved_profile else []
                        ),
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

if page == "premises":
    st.subheader("Archivio condiviso delle premesse")
    st.caption(
        "Le premesse salvate qui sono disponibili nei campi omonimi del documento "
        "singolo e della generazione massiva."
    )
    if not archive_database_url:
        st.error(
            "Archivio non configurato. Aggiungi ARCHIVE_DATABASE_URL ai Secrets "
            "dell'app Streamlit."
        )
    elif premises_error:
        st.error(f"Impossibile caricare l'archivio delle premesse: {premises_error}")
    elif not archive_premises:
        st.info(
            "Non ci sono ancora premesse archiviate. Puoi salvarne una direttamente "
            "dal campo Premessa durante la compilazione."
        )
    else:
        for premise in archive_premises:
            with st.expander(premise["name"]):
                st.text_area(
                    "Testo della premessa",
                    value=premise["content"],
                    height=160,
                    disabled=True,
                    key=f"archived_premise_content_{premise['id']}",
                )
                if st.button(
                    "Elimina premessa",
                    key=f"delete_archived_premise_{premise['id']}",
                ):
                    try:
                        core.delete_archive_premise(
                            archive_database_url, premise["id"]
                        )
                    except (KeyError, ValueError) as error:
                        st.error(str(error))
                    except Exception as error:
                        st.error(f"Impossibile eliminare la premessa: {error}")
                    else:
                        invalidate_session_premises_cache()
                        st.rerun()

if page == "db":
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
