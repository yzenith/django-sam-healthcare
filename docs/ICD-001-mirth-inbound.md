# ICD-001: Mirth Connect -> Django HL7 Inbound Interface

## Interface Summary

| Field              | Value                                         |
|--------------------|-----------------------------------------------|
| Interface ID       | ICD-001                                       |
| Interface Name     | Mirth Connect Inbound HL7 Receiver            |
| Direction          | Inbound (Mirth Connect -> Django API)         |
| Protocol           | HTTPS / REST (POST)                           |
| Authentication     | Bearer JWT (HS256, exp + iss + sub required)  |
| Supported Versions | HL7 v2.3, v2.5                                |
| API Endpoint       | `POST /api/mirth/hl7/`                        |
| OpenAPI Docs       | `/api/docs/`                                  |
| Status             | Active (Demo)                                 |

---

## Supported Message Types

| Message Type | Event | Description                        | Produces X12? |
|--------------|-------|------------------------------------|---------------|
| ADT          | A01   | Inpatient Admission                | 837 + 835     |
| ADT          | A02   | Transfer                           | No            |
| ADT          | A03   | Discharge                          | 837 + 835     |
| ADT          | A04   | Outpatient/ER Registration         | 837 + 835     |
| ADT          | A08   | Update Patient Information         | No            |
| ORU          | R01   | Lab Result (Observation Report)    | No            |
| ORM          | O01   | New Lab/Radiology Order            | No            |
| MDM          | T02   | Clinical Document Notification     | No            |

---

## Request Specification

### Headers

| Header          | Required | Value                           |
|-----------------|----------|---------------------------------|
| Authorization   | Yes      | `Bearer <JWT>`                  |
| Content-Type    | Yes      | `application/json`              |

### JWT Claims

| Claim | Required | Description                        |
|-------|----------|------------------------------------|
| sub   | Yes      | Channel identifier (e.g. `mirth-channel`) |
| iss   | Yes      | Must be `django-sam-healthcare`    |
| aud   | Yes      | Must be `mirth-connector`          |
| exp   | Yes      | Unix timestamp — token must not be expired |

### Request Body

```json
{
  "hl7_message": "MSH|^~\\&|MIRTH|HOSPITAL|...",
  "source_context": {
    "system_type": "EMR",
    "vendor": "Epic",
    "facility_type": "Acute Care Hospital"
  }
}
```

| Field          | Type   | Required | Description                                     |
|----------------|--------|----------|-------------------------------------------------|
| hl7_message    | string | Yes      | Raw HL7 v2 message text (CR or LF line endings) |
| source_context | object | No       | Metadata about the sending system               |

---

## Response Specification

### 200 OK — Message Accepted

```json
{
  "status": "ok",
  "trace_id": "a1b2c3d4e5f6...",
  "ack": "MSH|^~\\&|DJANGO-SAM|HEALTHCARE|MIRTH|HOSPITAL|20251218120000||ACK|ACK20251218120000|P|2.3\rMSA|AA|MSG001|",
  "summary": {
    "message_type": "ADT^A01",
    "patient_id": "12345^^^MRN",
    "patient_class": "I",
    "encounter_present": true,
    "event_time": "2025-12-18T12:00:00"
  },
  "warnings": []
}
```

### 400 Bad Request — Validation Failure

```json
{
  "status": "failed",
  "trace_id": "a1b2c3d4e5f6...",
  "ack": "MSH|^~\\&|DJANGO-SAM|HEALTHCARE|MIRTH|HOSPITAL|...\rMSA|AE|MSG001|Missing PID-3",
  "error_category": "VALIDATION",
  "errors": ["Missing PID-3 (Patient Identifier)"],
  "warnings": []
}
```

### 403 Forbidden — Auth Failure

```
JWT has expired
```

---

## ACK Codes

| Code | Meaning            | When Used                                      |
|------|--------------------|------------------------------------------------|
| AA   | Application Accept | Message parsed, validated, and transformed     |
| AE   | Application Error  | Validation failed (missing segments/fields)    |
| AR   | Application Reject | Auth failure or unrecognised message type      |

---

## Error Categories

| Category          | Description                                                      |
|-------------------|------------------------------------------------------------------|
| NONE              | No error                                                         |
| VALIDATION        | Required HL7 segments or fields are missing                      |
| MAPPING           | Field could not be mapped to target format                       |
| AUTH              | JWT missing, expired, or invalid issuer                          |
| FACILITY_VARIANCE | MSH-3/4 sending app/facility absent — routing config may differ  |
| SOURCE_SYSTEM     | Upstream system issue (malformed payload)                        |
| DOWNSTREAM        | Failure in downstream system after successful transform          |
| UNKNOWN           | Unexpected error — see trace log for details                     |

---

## Audit & Traceability

Every inbound message — including auth failures — creates an `HL7MessageLog` record with:
- A unique `trace_id` (32-char hex UUID)
- Full `raw_hl7` payload
- Processing steps with status (OK / WARN / ERROR)
- `error_category` and `error_message` for failed records

Browse logs at: `/mirth/messages/`

---

## Facility Variance Handling

If `MSH-3` (Sending Application) or `MSH-4` (Sending Facility) are absent, the message is
**not rejected** but a `FACILITY_VARIANCE` warning is written to the audit log. This is a
common operational condition when integrating across facility types with inconsistent HL7
configuration. Operations staff should review these in the Mirth Live Feed.

---

## Change Log

| Version | Date       | Change                              | Author     |
|---------|------------|-------------------------------------|------------|
| 1.0     | 2025-12-18 | Initial interface specification     | S. Zhang   |
| 1.1     | 2026-03-22 | Added ORM + MDM message types; ACK  | S. Zhang   |
