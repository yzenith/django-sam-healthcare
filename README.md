# Healthcare Integration Engineer Demo

## Recruiter / Hiring Manager Quick Review (2–3 minutes)

### What this is
A portfolio demo that mirrors real healthcare integration engineering work:
- **HL7 v2 ingestion** → validation → **ACK/NAK** → mapping into **FHIR R4 resources**
- **X12 claim lifecycle**: generates a simplified **837** and simulates an **835** response + reconciliation
- **Data migration utility**: **Patients CSV import** with validation, dedupe, upsert, and reconciliation + rejects download
- **OpenAPI specification** at `/api/docs/` — live, interactive, typed

This is intentionally **not a full spec implementation**. It's a workflow-focused demo showing how I design, validate, and operate healthcare data pipelines — with the traceability and auditability that production systems require.

---

### The fastest way to evaluate it (click path)

1) **HL7 Playground**
- Paste an ADT / ORU / ORM / MDM message
- Click **Transform HL7**
- Review: parsed fields, FHIR resources, X12 output, and ACK response
Path: `/hl7/playground/`

2) **Trace Logs**
- Open a trace record
- See: step-by-step processing timeline, validations, decisions, and errors
Path: `/trace/logs/`

3) **API Docs**
- Browse the full typed interface specification with live examples
Path: `/api/docs/`

4) **CSV Import (Patients)**
- Upload a sample CSV
- See: dedupe, rejects, inserts vs updates, reconciliation summary
- Download rejects CSV for operational follow-up
Path: `/import/patients/`

---

### What to look for (signal of real-world readiness)
- **ACK/NAK protocol**: every Mirth inbound message returns a proper HL7 ACK (AA/AE/AR)
- **Validation & error taxonomy**: missing fields, invalid DOB, duplicates, warning vs reject behavior
- **Reconciliation**: source rows → deduped → inserted/updated → rejected + sample rejects
- **Auditability**: Trace IDs and step-by-step outcomes that support post-incident investigation
- **Interface Control Document**: `docs/ICD-001-mirth-inbound.md` — real engineering deliverable

---

### Notes on scope
- Uses synthetic data only (no PHI).
- Simplifies certain standards detail (by design) to keep focus on **pipeline design, integrity checks, and operational troubleshooting**.


## Purpose of This Demo

This project demonstrates **how a Healthcare Integration Engineer designs, builds, and operates healthcare data exchange pipelines** — including the validation logic, protocol handling, error taxonomy, and audit trails that production integrations require.

Healthcare integrations are rarely clean or predictable. Messages arrive incomplete, malformed, duplicated, or semantically ambiguous. The engineer's role is to **make integration behavior explicit, traceable, auditable, and operationally manageable** — and to own the full pipeline from inbound ACK to downstream reconciliation.

This demo reflects those engineering responsibilities.

---

## Problem Statement

Healthcare systems exchange data across:

* EMRs
* Practice management systems
* Clearinghouses
* Downstream analytics and billing platforms

These systems often:

* Use inconsistent HL7 v2 implementations
* Omit required fields
* Send invalid or conflicting values
* Require downstream normalization into modern data models

Without proper validation, traceability, and review workflows, these integrations fail silently or create operational risk.

---

## Integration Engineer Responsibilities Demonstrated

This demo is designed around **integration engineering responsibilities**, including:

### 1. Interface Design & Protocol Handling

* JWT-authenticated Mirth Connect inbound endpoint
* HL7 v2 ACK/NAK generation (AA = Accept, AE = Error, AR = Reject)
* Interface Control Document (ICD) specifying message types, auth, and error categories
* OpenAPI schema with typed request/response for every API endpoint

### 2. Message Intake & Classification

* Accepts inbound HL7 v2 messages via Mirth Connect channel simulation
* Routes ADT, ORU, ORM, and MDM message types automatically
* Classifies messages before transformation

### 3. Validation & Assumption Handling

* Detects missing or malformed fields (PID-3, PV1, DOB format)
* Applies controlled assumptions when possible
* Flags messages requiring review without blocking the pipeline

### 4. Normalization & Mapping

* Transforms HL7 v2 into FHIR R4 resources (Patient, Encounter, ServiceRequest, DocumentReference)
* Generates X12 837 claims and simulates 835 ERA responses
* Reconciles claim vs. payer response with balance-due calculation
* Separates mapping logic from transport logic

### 5. Traceability & Audit Logging

* Every inbound payload — including auth failures — produces a Trace ID
* Processing steps, validation outcomes, and transformation decisions recorded in sequence
* Enables post-incident investigation and review
* Error categories: VALIDATION, MAPPING, AUTH, FACILITY_VARIANCE, DOWNSTREAM

### 6. Operational Visibility

* UI to inspect message history, filter by status/type/errors
* Exceptions dashboard for messages requiring review
* Health check endpoint for uptime monitoring (`/health/`)

### 7. Data Migration (CSV Import + Reconciliation)

* Imports Patients CSV with schema validation and normalization
* Dedupes within-file, upserts into database
* Produces reconciliation report and downloadable rejects CSV


---

## What This Demo Proves

This project demonstrates the ability to:

* Design and implement healthcare data exchange pipelines end-to-end
* Handle real-world HL7 v2 complexity: multiple message types, ACK protocol, facility variance
* Build systems that support investigation, accountability, and post-incident review
* Think in terms of operational risk, not just code execution
* Produce engineering artifacts (ICD, OpenAPI spec) that interface teams use in production

In short, it shows **how an integration engineer reduces ambiguity, enforces protocol contracts, and makes failure recoverable**.

---

## Example Integration Scenario

**Scenario:**
An inbound ADT message arrives with a missing patient identifier.

**System Behavior:**

* Message is accepted but classified as `ACCEPTED_WITH_WARNING`
* Missing field is recorded in the trace
* An `AE` ACK is returned to the Mirth channel
* Message is flagged for manual review in the exceptions dashboard

**Engineer Response:**

* Reviews the trace log and ACK response
* Determines whether the fallback logic is acceptable for this facility
* Updates the channel configuration or field mapping rule
* Documents the decision in the ICD change log

This reflects how real healthcare integration incidents are handled.

---

## Technology Overview

* **Backend:** Django 5, Django REST Framework
* **Standards:** HL7 v2.3/2.5, FHIR R4, X12 5010 (837/835)
* **Integration Engine:** Mirth Connect (simulated inbound channel with JWT auth + ACK)
* **API Docs:** OpenAPI 3.0 via drf-spectacular (`/api/docs/`)
* **Persistence:** PostgreSQL (Neon) on Vercel / SQLite locally
* **Auth:** JWT (HS256) for Mirth connector endpoint
* **Monitoring:** `/health/` endpoint, structured JSON logging

Technology choices are intentionally focused to keep the emphasis on **pipeline design, protocol handling, and operational correctness** — not infrastructure complexity.

---

## What This Demo Is Not

This project is **not** intended to be:

* A full Mirth Connect replacement
* A production-ready EMR or interface engine
* A FHIR server with full specification coverage
* A microservices or streaming platform

Real production systems add: terminology services, PHI encryption layers, Kafka/queue-based routing, and full IHE profile compliance. These extend naturally from the pipeline design shown here.

---

## Intended Audience

This demo is built for:

* Healthcare Integration Engineer roles
* Interface Engineer / HL7 Engineer roles
* Implementation Engineer roles
* Integration Operations teams

It is designed to support conversations with:

* Hiring managers
* Technical leads
* Interface teams
* Implementation and onboarding stakeholders

---

## How to Review This Project

When reviewing this repository, focus on:

* How messages are classified, validated, and acknowledged (ACK/NAK)
* How assumptions and failures are recorded and categorized
* How traceability supports post-incident investigation
* How the interface is specified (ICD, OpenAPI docs)
* How the UI enables operational understanding

These are the daily concerns of a Healthcare Integration Engineer.

---

## Summary

This demo demonstrates **integration engineering thinking applied to healthcare data exchange**:

* Protocol contracts are explicit — every message gets an ACK
* Data ambiguity is expected and handled, not avoided
* Decisions are traceable and reviewable
* Failures are categorized, auditable, and explainable
* Systems are designed to support operations, not just pipelines

That is the core value of a Healthcare Integration Engineer.
