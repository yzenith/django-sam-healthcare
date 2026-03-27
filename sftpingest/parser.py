"""
sftpingest/parser.py
~~~~~~~~~~~~~~~~~~~~
Flat-file parsing pipeline for simulated SFTP drops.

Responsibilities
----------------
1. Auto-detect delimiter  (CSV comma, pipe |, or tab \t)
2. Auto-detect schema     (PATIENT demographics vs CLINICAL records)
3. Validate every row     — per-field rules, collected without aborting
4. Return a ParseResult   — clean records + structured error log

No Django ORM imports here; the parser is a pure data-transformation
layer that the view calls and then persists however it likes.  This keeps
the logic unit-testable without a database.

Supported schemas
-----------------
PATIENT  – patient demographic flat file (same fields as PatientRecord)
  Required: mrn, last_name, first_name, dob
  Optional: gender, address1, city, state, zip_code, phone

CLINICAL – clinical encounter flat file
  Required: mrn, visit_date
  Optional: visit_type, diagnosis_code, procedure_code,
            provider_id, facility_code, notes
"""

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal

# ── Types ─────────────────────────────────────────────────────────────────────

SchemaType    = Literal["PATIENT", "CLINICAL", "UNKNOWN"]
DelimiterName = Literal["COMMA", "PIPE", "TAB"]

# Sentinel used when a field is absent but not required
_MISSING = object()

# ── Schema definitions ────────────────────────────────────────────────────────

# Canonical headers that identify each schema; any of these in the header
# row triggers that schema.  Checked case-insensitively.
_PATIENT_SIGNALS  = {"mrn", "first_name", "last_name", "dob", "date_of_birth"}
_CLINICAL_SIGNALS = {"visit_date", "diagnosis_code", "procedure_code", "visit_type"}

PATIENT_REQUIRED  = {"mrn", "last_name", "first_name", "dob"}
PATIENT_OPTIONAL  = {"gender", "address1", "city", "state", "zip_code", "phone"}
PATIENT_ALL       = PATIENT_REQUIRED | PATIENT_OPTIONAL

CLINICAL_REQUIRED = {"mrn", "visit_date"}
CLINICAL_OPTIONAL = {"visit_type", "diagnosis_code", "procedure_code",
                     "provider_id", "facility_code", "notes"}
CLINICAL_ALL      = CLINICAL_REQUIRED | CLINICAL_OPTIONAL

# ── Validation helpers ────────────────────────────────────────────────────────

_ICD10_RE   = re.compile(r"^[A-Z][0-9A-Z]{1,6}(\.[0-9A-Z]{1,4})?$", re.IGNORECASE)
_CPT_RE     = re.compile(r"^[0-9]{4,5}[A-Z]?$", re.IGNORECASE)
_HCPCS_RE   = re.compile(r"^[A-Z][0-9]{4}$",   re.IGNORECASE)
_GENDER_MAP = {"m": "M", "f": "F", "male": "M", "female": "F",
               "u": "U", "unknown": "U", "o": "O", "other": "O"}


def _parse_date(raw: str) -> date | None:
    """Accept YYYY-MM-DD or YYYYMMDD; return None on failure."""
    raw = raw.strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%m/%d/%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _norm_str(v: str) -> str:
    return v.strip()


def _norm_state(v: str) -> str:
    return v.strip().upper()[:2]


# ── Delimiter detection ────────────────────────────────────────────────────────

def _detect_delimiter(first_line: str) -> tuple[str, DelimiterName]:
    """Return (delimiter_char, DelimiterName) for the most common delimiter."""
    counts = {
        ",":  first_line.count(","),
        "|":  first_line.count("|"),
        "\t": first_line.count("\t"),
    }
    char = max(counts, key=counts.get)
    # Fall back to comma if all counts are zero (single-column or empty)
    if counts[char] == 0:
        char = ","
    name_map = {",": "COMMA", "|": "PIPE", "\t": "TAB"}
    return char, name_map[char]


# ── Schema detection ──────────────────────────────────────────────────────────

def _detect_schema(headers: list[str]) -> SchemaType:
    """Return 'PATIENT', 'CLINICAL', or 'UNKNOWN' based on header overlap."""
    lower = {h.lower().strip() for h in headers}
    clinical_hits = lower & {s.lower() for s in _CLINICAL_SIGNALS}
    patient_hits  = lower & {s.lower() for s in _PATIENT_SIGNALS}
    if clinical_hits:
        return "CLINICAL"
    if patient_hits:
        return "PATIENT"
    return "UNKNOWN"


# ── Row validation ────────────────────────────────────────────────────────────

def _validate_patient_row(
    rownum: int,
    row: dict[str, str],
) -> tuple[dict, list[dict]]:
    """
    Validate and normalise one patient row.

    Returns (clean_record | None, list_of_errors).
    clean_record is None if the row has any blocking error.
    """
    errors: list[dict] = []

    def err(field: str, msg: str, raw: str = ""):
        errors.append({"rownum": rownum, "field": field, "error": msg, "raw_value": raw})

    mrn = _norm_str(row.get("mrn", ""))
    if not mrn:
        err("mrn", "Missing MRN (required)")

    first_name = _norm_str(row.get("first_name", ""))
    last_name  = _norm_str(row.get("last_name", ""))
    if not last_name:
        err("last_name", "Missing last name (required)")
    if not first_name:
        err("first_name", "Missing first name (required)")

    raw_dob = row.get("dob", "").strip()
    dob = None
    if not raw_dob:
        err("dob", "Missing date of birth (required)")
    else:
        dob = _parse_date(raw_dob)
        if dob is None:
            err("dob", f"Invalid date format — expected YYYYMMDD or YYYY-MM-DD", raw_dob)
        elif dob > date.today():
            err("dob", "Date of birth is in the future", raw_dob)

    raw_gender = row.get("gender", "").strip()
    gender = _GENDER_MAP.get(raw_gender.lower(), "")
    if raw_gender and not gender:
        err("gender", f"Unrecognised gender value (use M/F/U/O)", raw_gender)
    gender = gender or ""

    state = _norm_state(row.get("state", ""))
    if state and len(state) != 2:
        err("state", "State must be a 2-letter US code", state)

    if errors:
        return None, errors

    record = {
        "mrn":        mrn,
        "first_name": first_name,
        "last_name":  last_name,
        "dob":        dob,
        "gender":     gender,
        "address1":   _norm_str(row.get("address1", "")),
        "city":       _norm_str(row.get("city", "")),
        "state":      state,
        "zip_code":   _norm_str(row.get("zip_code", "") or row.get("zip", "")),
    }
    return record, []


def _validate_clinical_row(
    rownum: int,
    row: dict[str, str],
) -> tuple[dict, list[dict]]:
    """Validate and normalise one clinical encounter row."""
    errors: list[dict] = []

    def err(field: str, msg: str, raw: str = ""):
        errors.append({"rownum": rownum, "field": field, "error": msg, "raw_value": raw})

    mrn = _norm_str(row.get("mrn", ""))
    if not mrn:
        err("mrn", "Missing MRN (required)")

    raw_vd = row.get("visit_date", "").strip()
    visit_date = None
    if not raw_vd:
        err("visit_date", "Missing visit date (required)")
    else:
        visit_date = _parse_date(raw_vd)
        if visit_date is None:
            err("visit_date", "Invalid date format — expected YYYY-MM-DD or YYYYMMDD", raw_vd)
        elif visit_date > date.today():
            err("visit_date", "Visit date is in the future", raw_vd)

    dx = _norm_str(row.get("diagnosis_code", "")).upper()
    if dx and not _ICD10_RE.match(dx):
        err("diagnosis_code", f"Does not match ICD-10 format (e.g. Z87.891)", dx)

    cpt = _norm_str(row.get("procedure_code", "")).upper()
    if cpt and not (_CPT_RE.match(cpt) or _HCPCS_RE.match(cpt)):
        err("procedure_code", f"Does not match CPT-4/5 or HCPCS format", cpt)

    if errors:
        return None, errors

    record = {
        "mrn":            mrn,
        "visit_date":     visit_date,
        "visit_type":     _norm_str(row.get("visit_type", "")),
        "diagnosis_code": dx,
        "procedure_code": cpt,
        "provider_id":    _norm_str(row.get("provider_id", "")),
        "facility_code":  _norm_str(row.get("facility_code", "")),
        "notes":          _norm_str(row.get("notes", "")),
    }
    return record, []


# ── ParseResult ───────────────────────────────────────────────────────────────

@dataclass
class ParseResult:
    schema_type:       SchemaType
    delimiter_name:    DelimiterName
    headers:           list[str]
    total_rows:        int          = 0
    valid_records:     list[dict]  = field(default_factory=list)
    validation_errors: list[dict]  = field(default_factory=list)
    duplicate_mrns:    int          = 0
    fatal_error:       str          = ""

    @property
    def valid_rows(self) -> int:
        return len(self.valid_records)

    @property
    def rejected_rows(self) -> int:
        # Each validation error entry is one rejected row (deduped by rownum)
        return len({e["rownum"] for e in self.validation_errors})


# ── Main entry point ──────────────────────────────────────────────────────────

MAX_FILE_BYTES = 20 * 1024 * 1024   # 20 MB hard cap
MAX_ROWS       = 50_000


def parse_flat_file(content: bytes, filename: str) -> ParseResult:
    """
    Parse raw file bytes into a ParseResult.

    Parameters
    ----------
    content : bytes
        Raw file bytes (from Django's InMemoryUploadedFile.read()).
    filename : str
        Original filename — used only for logging context.

    Returns
    -------
    ParseResult
        Contains valid_records, validation_errors, and metadata.
        If a fatal error occurs, ParseResult.fatal_error is set.
    """
    # --- Decode ------------------------------------------------------------------
    text = None
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        return ParseResult(
            schema_type="UNKNOWN", delimiter_name="COMMA", headers=[],
            fatal_error="File encoding not supported (tried UTF-8 and Latin-1).",
        )

    # Normalise line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [l for l in text.split("\n") if l.strip()]

    if not lines:
        return ParseResult(
            schema_type="UNKNOWN", delimiter_name="COMMA", headers=[],
            fatal_error="File is empty.",
        )

    # --- Delimiter & schema detection --------------------------------------------
    delim_char, delim_name = _detect_delimiter(lines[0])
    reader = csv.DictReader(io.StringIO(text), delimiter=delim_char)
    headers = [h.strip().lower() for h in (reader.fieldnames or [])]
    schema  = _detect_schema(headers)

    result = ParseResult(
        schema_type=delim_name,     # overwritten below
        delimiter_name=delim_name,
        headers=headers,
    )
    result.schema_type = schema     # type: ignore[assignment]

    if schema == "UNKNOWN":
        result.fatal_error = (
            f"Cannot determine schema from headers: {headers!r}. "
            "Expected PATIENT headers (mrn, first_name, last_name, dob) "
            "or CLINICAL headers (mrn, visit_date, diagnosis_code)."
        )
        return result

    # --- Row parsing -------------------------------------------------------------
    seen_mrns: set[str] = set()
    rownum = 1  # header is row 0

    for row in reader:
        rownum += 1
        if rownum > MAX_ROWS + 1:
            result.validation_errors.append({
                "rownum": rownum,
                "field":  "__file__",
                "error":  f"File exceeds {MAX_ROWS} row limit — truncated.",
                "raw_value": "",
            })
            break

        # Skip entirely empty rows
        if not any(v.strip() for v in row.values()):
            continue

        result.total_rows += 1

        # Normalise key names (strip whitespace)
        row = {k.strip().lower(): v for k, v in row.items() if k}

        if schema == "PATIENT":
            record, errors = _validate_patient_row(rownum, row)
        else:
            record, errors = _validate_clinical_row(rownum, row)

        if errors:
            result.validation_errors.extend(errors)
            continue

        # Intra-file duplicate MRN detection
        mrn = record["mrn"]
        if mrn in seen_mrns:
            result.duplicate_mrns += 1
            continue
        seen_mrns.add(mrn)

        result.valid_records.append(record)

    return result
