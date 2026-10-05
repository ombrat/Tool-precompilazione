import copy
import functools
import hashlib
import html as _html
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path

from docx import Document
from docx.enum.text import WD_COLOR_INDEX
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.run import Run
from sqlalchemy import (
    JSON,
    LargeBinary,
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    func,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.pool import NullPool

BASE = Path(__file__).parent
TEMPLATES_DIR = BASE / "templates"
SETTINGS_FILE = BASE / "settings.json"
PLACEHOLDER_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}|\[([A-ZÀ-Ý][A-ZÀ-Ý0-9 _']*)\]")
CUSTOMER_TYPES = {"fisica": "Persona fisica", "giuridica": "Persona giuridica"}
ARCHIVE_METADATA = MetaData()
ARCHIVE_PROFILES = Table(
    "archive_corporate_profiles",
    ARCHIVE_METADATA,
    Column("id", String(36), primary_key=True),
    Column("name", Text, nullable=False),
    Column("payload", JSON, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
ARCHIVE_DEFAULT_DATABASE = Table(
    "archive_default_database",
    ARCHIVE_METADATA,
    Column("id", String(36), primary_key=True),
    Column("filename", Text, nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("content", LargeBinary, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

DEFAULT_SETTINGS = {
    "xls_path": str(BASE / "Database.XLS"),
    "db_url": f"sqlite:///{BASE / 'anagrafica.db'}",
    "tables": {"fisica": "persone_fisiche", "giuridica": "persone_giuridiche"},
    "label_columns": {"fisica": ["cognome", "nome"], "giuridica": ["cognome"]},
}


# ---------- impostazioni ----------
def load_settings():
    if SETTINGS_FILE.exists():
        return {**DEFAULT_SETTINGS, **json.loads(SETTINGS_FILE.read_text())}
    return DEFAULT_SETTINGS


def save_settings(settings):
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2))


# ---------- database ----------
def _norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"\W+", "_", s.lower()).strip("_")


def _cell(v):
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def _format_residence(rec):
    location = " ".join(
        value for value in (rec.get("Cap", "").strip(), rec.get("Località", "").strip()) if value
    )
    province = rec.get("Prov.", "").strip()
    if province:
        location = f"{location} ({province})" if location else f"({province})"
    return ", ".join(value for value in (location, rec.get("Indirizzo", "").strip()) if value)


def _records_from_xls_sheet(sheet):
    header = [str(h).strip() for h in sheet.row_values(0)]
    rows = {"fisica": [], "giuridica": []}
    for i in range(1, sheet.nrows):
        vals = [_cell(v) for v in sheet.row_values(i)]
        if not any(vals):
            continue
        rec = dict(zip(header, vals))
        place = f"{rec.get('Località', '')} {rec.get('Prov.', '')}".strip()
        rec["Residenza"] = _format_residence(rec)
        rec["Sede legale"] = ", ".join(x for x in (place, rec.get("Indirizzo", "")) if x)
        rec["id"] = rec.get("Codice") or i
        rows["giuridica" if len(rec.get("Codice Fiscale", "")) == 11 else "fisica"].append(rec)
    return header + ["Residenza", "Sede legale"], rows


@functools.lru_cache(maxsize=4)
def _load_xls(path, mtime):
    """Legge il foglio Excel e separa persone fisiche (CF 16 caratteri) e giuridiche (CF 11)."""
    import xlrd

    sheet = xlrd.open_workbook(path, logfile=io.StringIO()).sheet_by_index(0)
    return _records_from_xls_sheet(sheet)


def load_xls_bytes(data):
    """Legge un database Excel caricato in memoria, senza salvarlo sul server."""
    import xlrd

    sheet = xlrd.open_workbook(
        file_contents=data, logfile=io.StringIO()
    ).sheet_by_index(0)
    return _records_from_xls_sheet(sheet)


def _xls():
    path = Path(load_settings().get("xls_path") or "")
    return _load_xls(str(path), path.stat().st_mtime) if path.is_file() else None


def _engine():
    return create_engine(load_settings()["db_url"])


def db_columns(ctype, xls_content=None):
    if xls_content is not None:
        return xls_content[0]
    if x := _xls():
        return x[0]
    table = load_settings()["tables"][ctype]
    with _engine().connect() as c:
        return list(c.execute(text(f'SELECT * FROM "{table}" LIMIT 0')).keys())


def db_records(ctype, xls_content=None):
    if xls_content is not None:
        return xls_content[1][ctype]
    if x := _xls():
        return x[1][ctype]
    table = load_settings()["tables"][ctype]
    with _engine().connect() as c:
        return [dict(r._mapping) for r in c.execute(text(f'SELECT * FROM "{table}"'))]


def record_label(ctype, rec):
    by_norm = {_norm(k): v for k, v in rec.items()}
    cols = load_settings()["label_columns"][ctype]
    return " ".join(str(by_norm.get(_norm(c), "")) for c in cols).strip() or str(rec)


def record_identity(record):
    for key, value in record.items():
        if _norm(key) in {"codice_fiscale", "cf"} and str(value or "").strip():
            return f"cf:{str(value).strip().upper()}"
    if record.get("id") not in (None, ""):
        return f"id:{record['id']}"
    return f"name:{_norm(record_label('fisica', record))}"


def _refresh_record(old, current):
    updated, changes = dict(old), []
    by_norm = {_norm(k): k for k in old}
    for key, value in current.items():
        if key == "id" or value is None or str(value).strip() == "":
            continue
        target = by_norm.get(_norm(key), key)
        previous = old.get(target)
        if str(previous or "").strip() != str(value).strip():
            changes.append((target, previous, value))
            updated[target] = value
    return updated, changes


def refresh_archive_payload(payload, companies, people):
    """Confronta la scheda con i dati correnti del database e li aggiorna."""
    payload = copy.deepcopy(payload)
    changes = []
    company_index = {record_identity(r): r for r in companies}
    people_index = {record_identity(r): r for r in people}

    def refresh(label, record, index):
        current = index.get(record_identity(record))
        if not current:
            return record
        record, diff = _refresh_record(record, current)
        changes.extend((label, *item) for item in diff)
        return record

    payload["company"] = refresh("Società", payload["company"], company_index)
    payload["legal_representative"] = refresh(
        "Legale rappresentante", payload["legal_representative"], people_index
    )
    for number, owner in enumerate(payload.get("owners", []), 1):
        owner["person"] = refresh(f"Titolare effettivo {number}", owner["person"], people_index)
    return payload, changes


@functools.lru_cache(maxsize=2)
def _archive_engine(database_url):
    if database_url.startswith("postgres://"):
        database_url = "postgresql+psycopg://" + database_url[len("postgres://"):]
    elif database_url.startswith("postgresql://"):
        database_url = "postgresql+psycopg://" + database_url[len("postgresql://"):]
    return create_engine(database_url, poolclass=NullPool, pool_pre_ping=True)


def _archive_table(database_url):
    if not database_url:
        raise ValueError("Configura ARCHIVE_DATABASE_URL per usare l'archivio persistente.")
    engine = _archive_engine(database_url)
    ARCHIVE_METADATA.create_all(engine)
    return engine


def get_default_database_info(database_url):
    engine = _archive_table(database_url)
    with engine.connect() as connection:
        row = connection.execute(
            select(
                ARCHIVE_DEFAULT_DATABASE.c.filename,
                ARCHIVE_DEFAULT_DATABASE.c.sha256,
                ARCHIVE_DEFAULT_DATABASE.c.updated_at,
            ).where(ARCHIVE_DEFAULT_DATABASE.c.id == "default")
        ).one_or_none()
    if row is None:
        return None
    return {
        "filename": row.filename,
        "sha256": row.sha256,
        "updated_at": row.updated_at,
    }


def get_default_database_content(database_url):
    engine = _archive_table(database_url)
    with engine.connect() as connection:
        return connection.execute(
            select(ARCHIVE_DEFAULT_DATABASE.c.content).where(
                ARCHIVE_DEFAULT_DATABASE.c.id == "default"
            )
        ).scalar_one_or_none()


def save_default_database(database_url, filename, content):
    filename = str(filename).strip()
    if not filename or not isinstance(content, bytes) or not content:
        raise ValueError("Seleziona un file Excel valido.")
    digest = hashlib.sha256(content).hexdigest()
    engine = _archive_table(database_url)
    with engine.begin() as connection:
        result = connection.execute(
            update(ARCHIVE_DEFAULT_DATABASE)
            .where(ARCHIVE_DEFAULT_DATABASE.c.id == "default")
            .values(
                filename=filename,
                sha256=digest,
                content=content,
                updated_at=func.now(),
            )
        )
        if result.rowcount == 0:
            connection.execute(
                insert(ARCHIVE_DEFAULT_DATABASE).values(
                    id="default",
                    filename=filename,
                    sha256=digest,
                    content=content,
                    updated_at=func.now(),
                )
            )
    return digest


def list_archive_profiles(database_url):
    engine = _archive_table(database_url)
    with engine.connect() as connection:
        rows = connection.execute(
            select(
                ARCHIVE_PROFILES.c.id,
                ARCHIVE_PROFILES.c.name,
                ARCHIVE_PROFILES.c.payload,
                ARCHIVE_PROFILES.c.updated_at,
            ).order_by(ARCHIVE_PROFILES.c.name)
        )
        return [
            {
                "id": row.id,
                "name": row.name,
                "payload": row.payload,
                "updated_at": row.updated_at,
            }
            for row in rows
        ]


def save_archive_profile(database_url, name, payload, profile_id=None):
    name = str(name).strip()
    if not name:
        raise ValueError("Inserisci un nome per la scheda.")
    payload = copy.deepcopy(payload)
    company = payload.get("company")
    representative = payload.get("legal_representative")
    owners = payload.get("owners")
    if not isinstance(company, dict) or not company or not isinstance(representative, dict) or not representative:
        raise ValueError("La scheda deve contenere società e legale rappresentante.")
    if not isinstance(owners, list) or not owners:
        raise ValueError("Aggiungi almeno un titolare effettivo.")
    identities = set()
    for owner in owners:
        if not isinstance(owner, dict):
            raise ValueError("I dati del titolare effettivo non sono validi.")
        person = owner.get("person")
        if not isinstance(person, dict) or not person:
            raise ValueError("Seleziona ogni titolare effettivo.")
        identity = record_identity(person)
        if identity in identities:
            raise ValueError("Lo stesso titolare effettivo è stato selezionato più di una volta.")
        identities.add(identity)
        try:
            percentage = Decimal(str(owner.get("percentage", "")))
        except InvalidOperation as error:
            raise ValueError(
                "Inserisci una percentuale valida per ogni titolare effettivo."
            ) from error
        if not percentage.is_finite() or not Decimal("0") <= percentage <= Decimal("100"):
            raise ValueError("Le percentuali devono essere comprese tra 0 e 100.")
        owner["percentage"] = format(percentage, "f")

    engine = _archive_table(database_url)
    with engine.begin() as connection:
        if profile_id:
            result = connection.execute(
                update(ARCHIVE_PROFILES)
                .where(ARCHIVE_PROFILES.c.id == profile_id)
                .values(name=name, payload=payload, updated_at=func.now())
            )
            if result.rowcount != 1:
                raise KeyError("La scheda da aggiornare non esiste più.")
            return profile_id
        profile_id = str(uuid.uuid4())
        connection.execute(
            insert(ARCHIVE_PROFILES).values(
                id=profile_id, name=name, payload=payload, updated_at=func.now()
            )
        )
    return profile_id


def delete_archive_profile(database_url, profile_id):
    engine = _archive_table(database_url)
    with engine.begin() as connection:
        result = connection.execute(
            ARCHIVE_PROFILES.delete().where(ARCHIVE_PROFILES.c.id == profile_id)
        )
    if result.rowcount != 1:
        raise KeyError("La scheda da eliminare non esiste più.")


# ---------- conversione .doc <-> .docx ----------
def _convert_with_word(data, src, dst):
    try:
        import pythoncom
        from win32com.client import DispatchEx
    except ImportError as exc:
        raise RuntimeError(
            "Per convertire o visualizzare documenti su Windows è necessario Microsoft Word "
            "e il pacchetto pywin32. Riavvia Avvia-Tool-Windows.bat per installarlo."
        ) from exc

    word_formats = {"doc": 0, "docx": 12, "pdf": 17}
    if dst not in word_formats:
        raise ValueError(f"Formato Word non supportato: {dst}")

    pythoncom.CoInitialize()
    word = document = None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            inp = Path(tmp) / f"in.{src}"
            inp.write_bytes(data)
            output = Path(tmp) / f"out.{dst}"
            try:
                try:
                    word = DispatchEx("Word.Application")
                except Exception as exc:
                    raise RuntimeError(
                        "Microsoft Word non è disponibile. Verifica che la versione desktop sia "
                        "installata, attivata e avviabile con questo account Windows."
                    ) from exc
                word.Visible = False
                word.DisplayAlerts = 0
                word.AutomationSecurity = 3
                document = word.Documents.Open(
                    str(inp), ConfirmConversions=False, ReadOnly=True,
                    AddToRecentFiles=False, Visible=False,
                )
                document.SaveAs2(
                    FileName=str(output), FileFormat=word_formats[dst], AddToRecentFiles=False
                )
                return output.read_bytes()
            finally:
                try:
                    if document is not None:
                        document.Close(SaveChanges=0)
                finally:
                    if word is not None:
                        word.Quit()
    finally:
        pythoncom.CoUninitialize()


def convert(data, src, dst):
    """Converte documenti usando Word su Windows e LibreOffice sugli altri sistemi."""
    if sys.platform == "win32":
        return _convert_with_word(data, src, dst)

    profile = BASE / ".lo_profile"
    with tempfile.TemporaryDirectory() as tmp:
        inp = Path(tmp) / f"in.{src}"
        inp.write_bytes(data)
        outdir = Path(tmp) / "out"
        subprocess.run(
            ["soffice", f"-env:UserInstallation={profile.as_uri()}", "--headless",
             "--convert-to", dst, "--outdir", str(outdir), str(inp)],
            check=True, capture_output=True, timeout=180, env={**os.environ, "HOME": tmp},
        )
        return (outdir / f"in.{dst}").read_bytes()


# ---------- documento ----------
def _paragraphs(container):
    for p in container.paragraphs:
        yield p
    for t in getattr(container, "tables", []):
        for row in t.rows:
            for cell in row.cells:
                yield from _paragraphs(cell)


def all_paragraphs(doc):
    yield from _paragraphs(doc)
    for s in doc.sections:
        for part in (s.header, s.footer, s.first_page_header, s.first_page_footer):
            yield from _paragraphs(part)


def _ph_key(m):
    key = re.sub(r"\W+", "_", (m.group(1) or m.group(2)).strip()).strip("_").upper()
    return re.sub(r"_TE_(\d+)$", r"_TE\1", key)  # [COGNOME TE 2] == [COGNOME TE2]


ROLE_RE = re.compile(r"^(.+)_(LR|TE\d*)$")
CARICHE = [
    "Amministratore unico", "Amministratore delegato", "Legale rappresentante",
    "Presidente del consiglio di amministrazione", "Consigliere", "Procuratore", "Socio", "Altro",
]


def split_role(key):
    """'COGNOME_LR' -> ('COGNOME', 'LR'); chiavi senza ruolo -> (key, None)."""
    m = ROLE_RE.match(key)
    return (m.group(1), m.group(2)) if m else (key, None)


def is_anagraphic_field(name):
    normalized = _norm(split_role(name)[0]).upper()
    if any(term in normalized for term in ("PREMESSA", "COMMISSIONE", "PERCENT")):
        return False
    return normalized in PREDEFINED


def legal_form_from_company_name(company_name):
    normalized = _norm(company_name).lower()
    if re.search(r"(?:^|_)(?:kgaa|kg_?a_?a|kommanditgesellschaft_auf_aktien)$", normalized):
        return "SOCIETA' IN ACCOMANDITA PER AZIONI"
    if re.search(r"(?:^|_)(?:gmbh_co_)?kg$", normalized) or re.search(
        r"(?:^|_)kommanditgesellschaft$", normalized
    ):
        return "SOCIETA' IN ACCOMANDITA"
    if re.search(r"(?:^|_)(?:s_n_c|snc|o_h_g|ohg)$", normalized) or re.search(
        r"(?:^|_)(?:societa_in_nome_collettivo|offene_handelsgesellschaft)$", normalized
    ):
        return "SOCIETA' IN NOME COLLETTIVO"
    if re.search(r"(?:^|_)(?:s_p_a|spa|ag|aktiengesellschaft)$", normalized) or re.search(
        r"(?:^|_)societa_per_azioni$", normalized
    ):
        return "SOCIETA' PER AZIONI"
    if re.search(r"(?:^|_)(?:ug(?:_haftungsbeschrankt)?|unternehmergesellschaft)$", normalized):
        return "SOCIETA' IMPRENDITORIALE A RESPONSABILITA' LIMITATA"
    if re.search(r"(?:^|_)(?:gmbh|s_r_l_s?|srls?)$", normalized) or re.search(
        r"(?:^|_)(?:societa_a_responsabilita_limitata|gesellschaft_mit_beschrankter_haftung)$",
        normalized,
    ):
        return "SOCIETA' A RESPONSABILITA' LIMITATA"
    if re.search(r"(?:^|_)(?:g_b_r|gbr|gesellschaft_burgerlichen_rechts)$", normalized):
        return "SOCIETA' DI DIRITTO CIVILE"
    return ""


def role_label(role):
    if role == "LR":
        return "Legale rappresentante"
    return f"Titolare effettivo {role[2:]}".strip()


def roles_for_customer_type(roles, ctype):
    if ctype != "giuridica":
        return roles
    ordered = {"LR": roles.get("LR", []), "TE1": roles.get("TE1", [])}
    ordered.update((role, keys) for role, keys in roles.items() if role not in ordered)
    return ordered


def find_placeholders(docx_bytes):
    """Restituisce {chiave: [token letterali]} per i segnaposto {{NOME}} e [NOME]."""
    doc = Document(io.BytesIO(docx_bytes))
    found = {}
    for p in all_paragraphs(doc):
        for m in PLACEHOLDER_RE.finditer(p.text):
            tokens = found.setdefault(_ph_key(m), [])
            if m.group(0) not in tokens:
                tokens.append(m.group(0))
    return found


def _chunk_html(text, styles, a, b):
    out, i = [], a
    while i < b:
        j = i
        while j < b and styles[j] == styles[i]:
            j += 1
        s = _html.escape(text[i:j]).replace("\n", "<br>").replace("\t", "&emsp;")
        if styles[i][0]:
            s = f"<b>{s}</b>"
        if styles[i][1]:
            s = f"<i>{s}</i>"
        out.append(s)
        i = j
    return "".join(out)


def _paragraph_html(p, values):
    text = p.text
    if not text.strip():
        return '<p style="margin:0;height:0.7em"></p>'
    styles = [(bool(r.bold), bool(r.italic)) for r in p.runs for _ in r.text]
    if len(styles) != len(text):
        styles = [(False, False)] * len(text)
    parts, pos = [], 0
    for m in PLACEHOLDER_RE.finditer(text):
        parts.append(_chunk_html(text, styles, pos, m.start()))
        value = values.get(_ph_key(m))
        if value:
            shown = _html.escape(str(value)).replace("\n", "<br>")
            parts.append(f'<mark style="background:#b7f0c0;padding:0 2px;border-radius:3px">{shown}</mark>')
        else:
            parts.append(
                f'<mark style="background:#ffe066;border:1px solid #d32f2f;padding:0 2px;'
                f'border-radius:3px">{_html.escape(m.group(0))}</mark>'
            )
        pos = m.end()
    parts.append(_chunk_html(text, styles, pos, len(text)))
    jc = p._p.xpath("./w:pPr/w:jc/@w:val")
    align = {"center": "center", "right": "right", "end": "right", "both": "justify"}.get(jc[0] if jc else "", "left")
    return f'<p style="margin:0 0 6px;text-align:{align}">{"".join(parts)}</p>'


def preview_html(docx_bytes, values):
    """HTML del documento: segnaposto vuoti in giallo, valori inseriti in verde."""
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(io.BytesIO(docx_bytes))
    out = []
    for el in doc.element.body.iterchildren():
        if el.tag.endswith("}p"):
            out.append(_paragraph_html(Paragraph(el, doc), values))
        elif el.tag.endswith("}tbl"):
            rows = []
            for row in Table(el, doc).rows:
                cells = "".join(
                    '<td style="border:1px solid #999;padding:4px;vertical-align:top">'
                    + "".join(_paragraph_html(p, values) for p in c.paragraphs) + "</td>"
                    for c in row.cells
                )
                rows.append(f"<tr>{cells}</tr>")
            out.append(
                '<table style="border-collapse:collapse;width:100%;margin-bottom:6px">' + "".join(rows) + "</table>"
            )
    return '<div style="font-family:Georgia,serif;font-size:14px;line-height:1.4;color:#111">' + "".join(out) + "</div>"


def document_text(docx_bytes):
    doc = Document(io.BytesIO(docx_bytes))
    return "\n".join(p.text for p in all_paragraphs(doc))


def _set_run(run, before, value, after, hl=None, border_color=None):
    if hl is None:
        run.text = before
        for i, line in enumerate(str(value).split("\n")):
            if i:
                run.add_break()
            run.add_text(line)
        run.add_text(after)
        return
    # Con evidenziazione il valore diventa un run separato con la stessa formattazione.
    template = copy.deepcopy(run._r)
    run.text = before
    r_val = copy.deepcopy(template)
    run._r.addnext(r_val)
    val_run = Run(r_val, run._parent)
    val_run.text = ""
    for i, line in enumerate(str(value).split("\n")):
        if i:
            val_run.add_break()
        val_run.add_text(line)
    val_run.font.highlight_color = hl
    if border_color:
        border = OxmlElement("w:bdr")
        border.set(qn("w:val"), "single")
        border.set(qn("w:sz"), "8")
        border.set(qn("w:space"), "1")
        border.set(qn("w:color"), border_color)
        val_run._r.get_or_add_rPr().append(border)
    if after:
        r_after = copy.deepcopy(template)
        r_val.addnext(r_after)
        Run(r_after, run._parent).text = after


def _replace_span(p, start, end, value, hl=None, border_color=None):
    """Sostituisce p.text[start:end] con value (start == end inserisce); mantiene la formattazione del primo run coinvolto."""
    if not p.runs:
        p.add_run("")
    pos = 0
    first = True
    runs = p.runs
    for i, run in enumerate(runs):
        r_start, r_end = pos, pos + len(run.text)
        pos = r_end
        if start == end:
            if r_start <= start <= r_end or i == len(runs) - 1:
                k = min(max(start - r_start, 0), len(run.text))
                _set_run(run, run.text[:k], value, run.text[k:], hl, border_color)
                return
            continue
        if r_end <= start or r_start >= end:
            continue
        before = run.text[: max(start - r_start, 0)]
        after = run.text[max(end - r_start, 0):] if r_end > end else ""
        if first:
            _set_run(run, before, value, after, hl, border_color)
            first = False
        else:
            run.text = after


def _replace_in_paragraph(p, token, value, hl=None, border_color=None):
    # Unisce i run per gestire token spezzati.
    pos = 0
    while (start := p.text.find(token, pos)) >= 0:
        _replace_span(p, start, start + len(token), value, hl, border_color)
        pos = start + len(str(value))


def _clear_remaining_placeholders(paragraphs):
    for paragraph in paragraphs:
        tokens = {match.group(0) for match in PLACEHOLDER_RE.finditer(paragraph.text)}
        for token in tokens:
            _replace_in_paragraph(paragraph, token, "")


def doc_paragraphs(docx_bytes):
    """Testi dei paragrafi, nello stesso ordine usato da apply_placeholder."""
    doc = Document(io.BytesIO(docx_bytes))
    return [p.text for p in all_paragraphs(doc)]


def apply_placeholder(docx_bytes, par_index, start, end, name, suffix=""):
    """Sostituisce (o inserisce, se start == end) {{name}} nel paragrafo indicato."""
    doc = Document(io.BytesIO(docx_bytes))
    p = list(all_paragraphs(doc))[par_index]
    _replace_span(p, start, end, "{{%s}}%s" % (name, suffix))
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


# Segnaposto predefiniti: nome -> colonne database possibili
PREDEFINED = {
    "NOME": ["nome"],
    "COGNOME": ["cognome"],
    "DATA_DI_NASCITA": ["data_nascita", "data_di_nascita"],
    "LUOGO_DI_NASCITA": ["localita_nascita", "luogo_nascita", "luogo_di_nascita"],
    "DATA_SCADENZA": ["data_scadenza"],
    "DATA_DI_RILASCIO": ["data_emissione", "data_rilascio"],
    "DATA_EMISSIONE": ["data_di_rilascio", "data_rilascio"],
    "TIPO_DOCUMENTO": ["tipo_documento_di_identita"],
    "TIPO_DOCUMENTO_DI_IDENTITA": ["tipo_documento"],
    "ENTE_EMITTENTE": ["comune_di"],
    "COMUNE_DI": ["ente_emittente"],
    "DOCUMENTO_DI_IDENTITA": ["numero_documento", "documento_di_identita"],
    "NUMERO_DOCUMENTO": ["documento_di_identita"],
    "RESIDENZA": ["residenza", "indirizzo"],
    "COMMISSIONE_ANNUALE": [],
    "COMMISSIONE_APERTURA": [],
    "RAGIONE_SOCIALE": ["cognome", "ragione_sociale", "denominazione", "nome_societa"],
    "NOME_SOCIETA": ["ragione_sociale", "denominazione", "cognome"],
    "NOME_DELLA_SOCIETA": ["ragione_sociale", "denominazione", "cognome"],
    "DENOMINAZIONE": ["ragione_sociale", "nome_societa", "cognome"],
    "FORMA_GIURIDICA": [],
    "SEDE_LEGALE": ["sede_legale"],
    "CODICE_FISCALE": ["codice_fiscale", "cf"],
    "PARTITA_IVA": ["partita_iva", "piva"],
    "RUOLO_SOCIETARIO": ["ruolo_societario", "ruolo"],
}


def format_field_value(name, value):
    if value is None:
        return ""
    value = str(value).strip()
    normalized_name = _norm(name).upper()
    if normalized_name in {"TIPO_DOCUMENTO", "TIPO_DOCUMENTO_DI_IDENTITA"}:
        code = re.sub(r"\.0+$", "", value)
        return {
            "1": "CARTA D'IDENTITA'",
            "01": "CARTA D'IDENTITA'",
            "3": "PASSAPORTO",
            "03": "PASSAPORTO",
        }.get(code, value)
    return value


_COMMISSION_FIELDS = {"COMMISSIONE_ANNUALE", "COMMISSIONE_APERTURA"}
_UNIT_WORDS = (
    "zero", "uno", "due", "tre", "quattro", "cinque", "sei", "sette", "otto", "nove",
    "dieci", "undici", "dodici", "tredici", "quattordici", "quindici", "sedici",
    "diciassette", "diciotto", "diciannove",
)


def _under_hundred(value):
    if value < 20:
        return _UNIT_WORDS[value]
    tens = ("", "", "venti", "trenta", "quaranta", "cinquanta", "sessanta", "settanta", "ottanta", "novanta")
    word = tens[value // 10]
    unit = value % 10
    if unit in {1, 8}:
        word = word[:-1]
    return word + (_UNIT_WORDS[unit] if unit else "")


def _under_thousand(value):
    hundreds, remainder = divmod(value, 100)
    word = ("" if hundreds == 0 else "cento" if hundreds == 1 else _UNIT_WORDS[hundreds] + "cento")
    if remainder:
        rest = _under_hundred(remainder)
        if hundreds and rest.startswith("otto"):
            word = word[:-1]
        word += rest
    return word or "zero"


def _integer_words(value):
    if value < 1000:
        return _under_thousand(value)
    if value < 1_000_000:
        thousands, remainder = divmod(value, 1000)
        thousand_word = _integer_words(thousands)
        if thousands == 1:
            prefix = "mille"
        else:
            if thousand_word.endswith("uno"):
                thousand_word = thousand_word[:-1]
            prefix = thousand_word + "mila"
        return prefix + (_integer_words(remainder) if remainder else "")
    if value < 1_000_000_000:
        millions, remainder = divmod(value, 1_000_000)
        prefix = "un milione" if millions == 1 else f"{_integer_words(millions)} milioni"
        return prefix + (f" {_integer_words(remainder)}" if remainder else "")
    billions, remainder = divmod(value, 1_000_000_000)
    prefix = "un miliardo" if billions == 1 else f"{_integer_words(billions)} miliardi"
    return prefix + (f" {_integer_words(remainder)}" if remainder else "")


def format_commission_value(name, value):
    """Format commission inputs as Italian numeric amounts followed by the amount in words."""
    if _norm(name).upper() not in _COMMISSION_FIELDS:
        return "" if value is None else str(value)
    raw = "" if value is None else str(value).strip()
    if not raw:
        return ""

    normalized = raw.replace(" ", "")
    if "," in normalized and "." in normalized:
        valid = re.fullmatch(r"\d{1,3}(?:\.\d{3})+,\d{1,2}", normalized)
        normalized = normalized.replace(".", "").replace(",", ".") if valid else ""
    elif "," in normalized:
        valid = re.fullmatch(r"\d+,\d{1,2}", normalized)
        normalized = normalized.replace(",", ".") if valid else ""
    elif "." in normalized:
        if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", normalized):
            normalized = normalized.replace(".", "")
        elif not re.fullmatch(r"\d+\.\d{1,2}", normalized):
            normalized = ""
    elif not re.fullmatch(r"\d+", normalized):
        normalized = ""

    try:
        amount = Decimal(normalized)
    except InvalidOperation as exc:
        raise ValueError("inserisci un importo numerico con al massimo due decimali") from exc
    if amount < 0 or amount.as_tuple().exponent < -2:
        raise ValueError("inserisci un importo positivo con al massimo due decimali")
    if amount > Decimal("999999999999.99"):
        raise ValueError("l'importo massimo supportato è 999.999.999.999,99")

    cents_total = int(amount * 100)
    whole, cents = divmod(cents_total, 100)
    formatted = f"{whole:,}".replace(",", ".") + f",{cents:02d}"
    return f"{formatted} ({_integer_words(whole)}/{cents:02d})"


# Campi che non hanno senso per un tipo di cliente
ONLY_FISICA = {"NOME", "COGNOME", "DATA_DI_NASCITA", "LUOGO_DI_NASCITA"}
ONLY_GIURIDICA = {"RAGIONE_SOCIALE", "SEDE_LEGALE"}


def guess_column(name, columns, ctype=None):
    normalized_name = _norm(name).upper()
    if (ctype == "giuridica" and normalized_name in ONLY_FISICA) or (
        ctype == "fisica" and normalized_name in ONLY_GIURIDICA
    ):
        return None
    cands = PREDEFINED.get(normalized_name, []).copy()
    if ctype == "giuridica" and normalized_name == "RESIDENZA":
        cands.insert(0, "sede_legale")
    cands.append(normalized_name.lower())
    if ctype == "giuridica" and normalized_name == "RAGIONE_SOCIALE":
        cands.append("cognome")
    lowered = {_norm(c): c for c in columns}
    for cand in cands:
        if normalized := _norm(cand):
            if normalized in lowered:
                return lowered[normalized]
    return None


def render(docx_bytes, fields, values, preview=False):
    """fields: lista di dict con 'name' e 'tokens'; values: {name: valore}.

    Con preview=True i valori sono evidenziati in verde e i segnaposto vuoti restano visibili in giallo.
    """
    doc = Document(io.BytesIO(docx_bytes))
    paragraphs = list(all_paragraphs(doc))
    for f in fields:
        value = values.get(f["name"], "")
        value = "" if value is None else value
        for p in paragraphs:
            for token in f.get("tokens") or [f["token"]]:
                if not preview:
                    _replace_in_paragraph(p, token, value)
                elif str(value).strip():
                    _replace_in_paragraph(p, token, value, WD_COLOR_INDEX.BRIGHT_GREEN)
                else:
                    _replace_in_paragraph(
                        p, token, token, WD_COLOR_INDEX.YELLOW, border_color="D32F2F"
                    )
    if not preview:
        _clear_remaining_placeholders(paragraphs)
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def preview_pages(docx_bytes, fields, values, dpi=110):
    """Pagine del documento (PNG) con i segnaposto evidenziati, rese da LibreOffice."""
    import pymupdf

    pdf = convert(render(docx_bytes, fields, values, preview=True), "docx", "pdf")
    with pymupdf.open(stream=pdf, filetype="pdf") as d:
        return [page.get_pixmap(dpi=dpi).tobytes("png") for page in d]


# ---------- template ----------
def list_templates():
    TEMPLATES_DIR.mkdir(exist_ok=True)
    return sorted(p.name for p in TEMPLATES_DIR.iterdir() if (p / "config.json").exists())


def save_template(name, docx_bytes, config):
    d = TEMPLATES_DIR / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "template.docx").write_bytes(docx_bytes)
    (d / "config.json").write_text(json.dumps(config, indent=2, ensure_ascii=False))


def load_template(name):
    d = TEMPLATES_DIR / name
    return (d / "template.docx").read_bytes(), json.loads((d / "config.json").read_text())


def load_supabase_document_template(supabase_url, service_role_key, bucket, customer_type):
    """Load a private Word template, preferring DOCX and falling back to DOC."""
    filenames = {
        "fisica": ("persona-fisica.docx", "persona-fisica.doc"),
        "giuridica": ("persona-giuridica.docx", "persona-giuridica.doc"),
    }
    if customer_type not in filenames:
        raise ValueError(f"Tipo cliente non valido: {customer_type}")
    if not supabase_url or not service_role_key:
        raise ValueError("Configura SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY.")
    if not bucket:
        raise ValueError("Configura il nome del bucket Supabase Storage.")

    base_url = supabase_url.rstrip("/")
    headers = {"apikey": service_role_key}
    if not service_role_key.startswith("sb_"):
        headers["Authorization"] = "Bearer " + service_role_key

    for filename in filenames[customer_type]:
        object_path = urllib.parse.quote(f"{bucket}/{filename}", safe="/")
        request = urllib.request.Request(
            f"{base_url}/storage/v1/object/authenticated/{object_path}",
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                content = response.read()
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", "replace")
            # Storage può rispondere 400 con statusCode 404 nel corpo.
            if error.code == 404 or (
                error.code == 400 and re.search(r"not[_ ]found|\"statusCode\"\s*:\s*\"?404", body, re.I)
            ):
                continue
            raise RuntimeError(
                f"Supabase Storage ha restituito HTTP {error.code} per {filename}: {body[:300]}"
            ) from error
        except urllib.error.URLError as error:
            raise RuntimeError(
                f"Connessione a Supabase Storage non riuscita: {error.reason}"
            ) from error

        if not content:
            raise ValueError(f"Il modello {filename} è vuoto.")
        return content, filename

    raise FileNotFoundError(
        f"Non trovo {', '.join(filenames[customer_type])} nel bucket privato "
        f"'{bucket}' di Supabase Storage."
    )
