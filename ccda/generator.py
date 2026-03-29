"""
ccda/generator.py
~~~~~~~~~~~~~~~~~
Generates a valid C-CDA R2.1 Continuity of Care Document (CCD) for a given
PatientRecord, optionally enriched with ClinicalRecord encounter data.

Output is well-formed XML conforming to:
  - CDA R2 (HL7 templateId 2.16.840.1.113883.10.20.22.1.1)
  - C-CDA R2.1 CCD (HL7 templateId 2.16.840.1.113883.10.20.22.1.2.1)

Pure Python — no Django ORM imports.  The view passes plain dicts so this
module remains independently unit-testable.
"""

import uuid
import html
from datetime import datetime, date


# ── OIDs ──────────────────────────────────────────────────────────────────────
OID_HL7_V3    = "2.16.840.1.113883.1.3"
OID_LOINC     = "2.16.840.1.113883.6.1"
OID_SNOMED    = "2.16.840.1.113883.6.96"
OID_NULLFLAVOR = "2.16.840.1.113883.5.1008"
OID_CDA_R2    = "2.16.840.1.113883.10.20.22.1.1"
OID_CCD_R21   = "2.16.840.1.113883.10.20.22.1.2.1"
OID_ENCOUNTER_SECTION = "2.16.840.1.113883.10.20.22.2.22.1"
OID_PROBLEM_SECTION   = "2.16.840.1.113883.10.20.22.2.5.1"
OID_ALLERGY_SECTION   = "2.16.840.1.113883.10.20.22.2.6.1"
OID_DEMO_ROOT = "2.16.840.1.113883.19.5"

GENDER_CODES = {"M": "M", "F": "F", "U": "UN", "O": "OTH", "": "UNK"}


def _e(text: str) -> str:
    """XML-escape a string value."""
    return html.escape(str(text or ""), quote=True)


def _ts(dt) -> str:
    """Format a date or datetime to HL7 timestamp (YYYYMMDDHHMMSS or YYYYMMDD)."""
    if dt is None:
        return datetime.utcnow().strftime("%Y%m%d%H%M%S")
    if isinstance(dt, datetime):
        return dt.strftime("%Y%m%d%H%M%S")
    if isinstance(dt, date):
        return dt.strftime("%Y%m%d")
    return str(dt)


def generate_ccda(
    patient: dict,
    clinical_records: list[dict] | None = None,
    document_type: str = "CCD",
) -> str:
    """
    Generate a C-CDA R2.1 document.

    Parameters
    ----------
    patient : dict
        Keys: mrn, first_name, last_name, dob (date), gender, address1,
              city, state, zip_code.
    clinical_records : list[dict] | None
        Each dict: mrn, visit_date, visit_type, diagnosis_code,
                   procedure_code, provider_id, facility_code, notes.
    document_type : str
        One of CCD, DISCHARGE_SUMMARY, PROGRESS_NOTE.

    Returns
    -------
    str
        Indented XML string.
    """
    clinical_records = clinical_records or []
    doc_id   = str(uuid.uuid4())
    now_ts   = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    mrn      = _e(patient.get("mrn", "UNKNOWN"))
    fname    = _e(patient.get("first_name", ""))
    lname    = _e(patient.get("last_name", ""))
    dob_ts   = _ts(patient.get("dob"))
    gender   = GENDER_CODES.get(patient.get("gender", ""), "UNK")
    addr1    = _e(patient.get("address1", ""))
    city     = _e(patient.get("city", ""))
    state    = _e(patient.get("state", ""))
    zip_code = _e(patient.get("zip_code", ""))

    doc_code, doc_title = {
        "CCD":              ("34133-9", "Continuity of Care Document"),
        "DISCHARGE_SUMMARY":("18842-5", "Discharge Summary"),
        "PROGRESS_NOTE":    ("11506-3", "Progress Note"),
    }.get(document_type, ("34133-9", "Continuity of Care Document"))

    # ── Build encounter rows for the Encounters section ───────────────────────
    encounter_entries = ""
    for i, rec in enumerate(clinical_records, start=1):
        enc_id   = _e(rec.get("mrn", mrn) + f"-ENC-{i:03d}")
        vd       = _ts(rec.get("visit_date"))
        vtype    = _e(rec.get("visit_type") or "UNKNOWN")
        dx       = _e(rec.get("diagnosis_code", ""))
        proc     = _e(rec.get("procedure_code", ""))
        prov     = _e(rec.get("provider_id", ""))
        fac      = _e(rec.get("facility_code", ""))
        notes    = _e(rec.get("notes", ""))
        dx_text  = f"Diagnosis: {dx}" if dx else ""
        proc_text = f"Procedure: {proc}" if proc else ""
        encounter_entries += f"""
          <entry typeCode="DRIV">
            <encounter classCode="ENC" moodCode="EVN">
              <templateId root="2.16.840.1.113883.10.20.22.4.49"/>
              <id root="{OID_DEMO_ROOT}" extension="{enc_id}"/>
              <code code="{_e(vtype)}" codeSystem="{OID_SNOMED}" displayName="{_e(vtype)}"/>
              <effectiveTime value="{vd}"/>
              <performer>
                <assignedEntity>
                  <id root="{OID_DEMO_ROOT}" extension="{prov or 'UNKNOWN'}"/>
                  <representedOrganization>
                    <name>{fac or "Demo Facility"}</name>
                  </representedOrganization>
                </assignedEntity>
              </performer>
              {"<entryRelationship typeCode='RSON'><act classCode='ACT' moodCode='EVN'><code code='DX' displayName='" + dx_text + "'/></act></entryRelationship>" if dx else ""}
              {"<entryRelationship typeCode='COMP'><act classCode='ACT' moodCode='EVN'><code code='PROC' displayName='" + proc_text + "'/></act></entryRelationship>" if proc else ""}
              {"<text>" + notes + "</text>" if notes else ""}
            </encounter>
          </entry>"""

    # ── Build problem entries ─────────────────────────────────────────────────
    seen_dx = {}
    for rec in clinical_records:
        dx = rec.get("diagnosis_code", "").strip().upper()
        if dx and dx not in seen_dx:
            seen_dx[dx] = rec.get("visit_date")

    problem_entries = ""
    for dx, vdate in seen_dx.items():
        problem_entries += f"""
          <entry typeCode="DRIV">
            <act classCode="ACT" moodCode="EVN">
              <templateId root="2.16.840.1.113883.10.20.22.4.3"/>
              <id root="{OID_DEMO_ROOT}" extension="{_e(mrn)}-{_e(dx)}"/>
              <code code="CONC" codeSystem="2.16.840.1.113883.5.6"/>
              <statusCode code="active"/>
              <effectiveTime><low value="{_ts(vdate)}"/></effectiveTime>
              <entryRelationship typeCode="SUBJ">
                <observation classCode="OBS" moodCode="EVN">
                  <templateId root="2.16.840.1.113883.10.20.22.4.4"/>
                  <id root="{OID_DEMO_ROOT}" extension="{_e(mrn)}-obs-{_e(dx)}"/>
                  <code code="55607006" codeSystem="{OID_SNOMED}" displayName="Problem"/>
                  <statusCode code="completed"/>
                  <effectiveTime><low value="{_ts(vdate)}"/></effectiveTime>
                  <value xsi:type="CD" code="{_e(dx)}"
                         codeSystem="2.16.840.1.113883.6.90"
                         displayName="{_e(dx)}"
                         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"/>
                </observation>
              </entryRelationship>
            </act>
          </entry>"""

    enc_section_narrative = "\n".join(
        f"<tr><td>{_e(r.get('visit_date',''))}</td>"
        f"<td>{_e(r.get('visit_type',''))}</td>"
        f"<td>{_e(r.get('diagnosis_code',''))}</td>"
        f"<td>{_e(r.get('procedure_code',''))}</td>"
        f"<td>{_e(r.get('provider_id',''))}</td></tr>"
        for r in clinical_records
    ) if clinical_records else "<tr><td colspan='5'>No encounters on record</td></tr>"

    problem_narrative = "\n".join(
        f"<tr><td>{_e(dx)}</td><td>Active</td><td>{_ts(vd)[:8]}</td></tr>"
        for dx, vd in seen_dx.items()
    ) if seen_dx else "<tr><td colspan='3'>No known problems on record</td></tr>"

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<ClinicalDocument xmlns="urn:hl7-org:v3"
                  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                  xmlns:voc="urn:hl7-org:v3/voc"
                  xsi:schemaLocation="urn:hl7-org:v3 CDA.xsd">

  <!-- ═══ Document Header ═══════════════════════════════════════════════════ -->
  <realmCode code="US"/>
  <typeId root="{OID_HL7_V3}" extension="POCD_HD000040"/>
  <templateId root="{OID_CDA_R2}"/>
  <templateId root="{OID_CCD_R21}"/>
  <id root="{doc_id}"/>
  <code code="{doc_code}"
        codeSystem="{OID_LOINC}"
        codeSystemName="LOINC"
        displayName="{doc_title}"/>
  <title>{doc_title}</title>
  <effectiveTime value="{now_ts}"/>
  <confidentialityCode code="N" codeSystem="2.16.840.1.113883.5.25"/>
  <languageCode code="en-US"/>

  <!-- ═══ Record Target (Patient) ══════════════════════════════════════════ -->
  <recordTarget>
    <patientRole>
      <id extension="{mrn}" root="{OID_DEMO_ROOT}"/>
      <addr use="HP">
        <streetAddressLine>{addr1}</streetAddressLine>
        <city>{city}</city>
        <state>{state}</state>
        <postalCode>{zip_code}</postalCode>
        <country>US</country>
      </addr>
      <patient>
        <name use="L">
          <given>{fname}</given>
          <family>{lname}</family>
        </name>
        <administrativeGenderCode code="{gender}"
                                   codeSystem="2.16.840.1.113883.5.1"/>
        <birthTime value="{dob_ts}"/>
      </patient>
    </patientRole>
  </recordTarget>

  <!-- ═══ Author ═══════════════════════════════════════════════════════════ -->
  <author>
    <time value="{now_ts}"/>
    <assignedAuthor>
      <id root="{OID_DEMO_ROOT}" extension="DEMO-SYSTEM"/>
      <assignedAuthoringDevice>
        <manufacturerModelName>Django Healthcare Integration Demo</manufacturerModelName>
        <softwareName>sam-healthcare v1.0</softwareName>
      </assignedAuthoringDevice>
      <representedOrganization>
        <id root="{OID_DEMO_ROOT}"/>
        <name>Demo Health System</name>
        <telecom value="tel:+1-555-000-0000" use="WP"/>
      </representedOrganization>
    </assignedAuthor>
  </author>

  <!-- ═══ Custodian ════════════════════════════════════════════════════════ -->
  <custodian>
    <assignedCustodian>
      <representedCustodianOrganization>
        <id root="{OID_DEMO_ROOT}"/>
        <name>Demo Health System</name>
      </representedCustodianOrganization>
    </assignedCustodian>
  </custodian>

  <!-- ═══ Structured Body ══════════════════════════════════════════════════ -->
  <component>
    <structuredBody>

      <!-- ── Allergies (required section, no known allergies) ──────────── -->
      <component>
        <section>
          <templateId root="{OID_ALLERGY_SECTION}"/>
          <code code="48765-2" codeSystem="{OID_LOINC}"
                displayName="Allergies and adverse reactions"/>
          <title>Allergies</title>
          <text>No known allergies.</text>
          <entry typeCode="DRIV">
            <act classCode="ACT" moodCode="EVN">
              <templateId root="2.16.840.1.113883.10.20.22.4.30"/>
              <id root="{OID_DEMO_ROOT}" extension="{mrn}-allergy-nka"/>
              <code code="CONC" codeSystem="2.16.840.1.113883.5.6"/>
              <statusCode code="active"/>
              <entryRelationship typeCode="SUBJ">
                <observation classCode="OBS" moodCode="EVN" negationInd="true">
                  <templateId root="2.16.840.1.113883.10.20.22.4.7"/>
                  <id root="{OID_DEMO_ROOT}" extension="{mrn}-allergy-obs-nka"/>
                  <code code="ASSERTION" codeSystem="2.16.840.1.113883.5.4"/>
                  <statusCode code="completed"/>
                  <value xsi:type="CD" code="419199007"
                         codeSystem="{OID_SNOMED}"
                         displayName="Allergy to substance"
                         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"/>
                </observation>
              </entryRelationship>
            </act>
          </entry>
        </section>
      </component>

      <!-- ── Problem List ───────────────────────────────────────────────── -->
      <component>
        <section>
          <templateId root="{OID_PROBLEM_SECTION}"/>
          <code code="11450-4" codeSystem="{OID_LOINC}" displayName="Problem list"/>
          <title>Problem List</title>
          <text>
            <table border="1" width="100%">
              <thead><tr>
                <th>ICD-10 Code</th><th>Status</th><th>Onset</th>
              </tr></thead>
              <tbody>{problem_narrative}</tbody>
            </table>
          </text>
          {problem_entries if problem_entries else ""}
        </section>
      </component>

      <!-- ── Encounters ─────────────────────────────────────────────────── -->
      <component>
        <section>
          <templateId root="{OID_ENCOUNTER_SECTION}"/>
          <code code="46240-8" codeSystem="{OID_LOINC}"
                displayName="History of encounters"/>
          <title>Encounters</title>
          <text>
            <table border="1" width="100%">
              <thead><tr>
                <th>Date</th><th>Type</th><th>Diagnosis</th>
                <th>Procedure</th><th>Provider</th>
              </tr></thead>
              <tbody>{enc_section_narrative}</tbody>
            </table>
          </text>
          {encounter_entries if encounter_entries else ""}
        </section>
      </component>

    </structuredBody>
  </component>

</ClinicalDocument>"""

    return xml
