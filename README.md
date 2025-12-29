🏥 End-to-End Healthcare Integration Demo (HL7 v2, FHIR R4, X12 837)

Built by Sam Yan  
Target Role: Integration Analyst / Healthcare Interoperability


🌐 Live Demo: https://django-sam-healthcare.vercel.app/

📡 Mirth Logs: https://django-sam-healthcare.vercel.app/mirth/messages/

🧪 Playground: https://django-sam-healthcare.vercel.app/hl7/playground/

## Overview

This project simulates a real-world healthcare interoperability workflow commonly seen between:

- Hospital / EMR systems
- Integration engines (Mirth Connect)
- Analytics & downstream systems (FHIR APIs, Claims pipelines)

The demo focuses on **how clinical and administrative data flows across systems**, including:
- Message ingestion
- Format transformation
- Validation and traceability
- Error visibility and replay

This mirrors day-to-day responsibilities of an **Integration Analyst** supporting EMR ↔ LIS ↔ Clearinghouse integrations.


🧩 Architecture
GitHub-friendly Mermaid diagram (works on GitHub)
flowchart LR
    EHR["External System<br/>(EHR / PMS / LIS)"] -->|"HL7 v2 ADT over TCP (MLLP)"| Mirth["Mirth Connect<br/>TCP Listener"]

    Mirth -->|"HTTP POST<br/>text/plain HL7"| DjangoAPI["Django Healthcare API<br/>(Vercel Serverless)"]

    DjangoAPI -->|"Parse HL7 v2"| FHIR["FHIR Patient<br/>FHIR Encounter"]

    FHIR -->|"Map fields to claim"| X12["X12 837 Claim<br/>(Professional)"]

    DjangoAPI -->|"Insert log row"| Neon["Neon Postgres<br/>HL7MessageLog table"]

    Neon -->|"SELECT last 50"| Dashboard["Web Dashboard<br/>/mirth/messages/"]

    DjangoAPI -->|"Return JSON (Patient, Encounter, 837)"| Mirth

💎 Features (What this demo proves I can do)
HL7 v2 ADT message ingestion via MLLP (ADT^A01 / A04 / A08)

Use case:
- Simulates patient admission and demographic updates from EMR systems
- Validates segment-level fields (PID, PV1)


✔ FHIR resource generation

Outputs valid FHIR JSON:

FHIR Patient Resource

FHIR Encounter Resource

✔ X12 837 Claim Builder

Creates a simplified 837P claim using fields extracted from ADT/PV1.

✔ Mirth Connect Integration

TCP Listener (HL7 v2.x)

JavaScript/Template routing

HTTP Sender to cloud endpoint

ACK handling

✔ Cloud Deployment

Django API deployed on Vercel Serverless

Neon Postgres for persistent storage

Dynamically switches between SQLite (dev) and Postgres (prod)

✔ Observability & Dashboard

Each message logged into HL7MessageLog

Dashboard showing time, type, patient ID, encounter, 837 length

Detail page with:

Raw HL7

FHIR Patient JSON

FHIR Encounter JSON

Generated X12 837

🛠 Technologies Used
Category	Tools
Interface Engine	Mirth Connect
HL7	HL7 v2 ADT, MLLP, Segment parsing
FHIR	Patient, Encounter structures
EDI	X12 837 Professional
Backend	Django 5, DRF, Python
Deployment	Vercel Serverless
Database	Neon Postgres + SQLite (local)
Frontend	Django Templates, CSS, jQuery
Logging	DB audit table, dashboard
📘 Endpoints
🔹 POST /api/transform/

Browser playground → HL7 input → FHIR + 837 output

🔹 POST /api/mirth/hl7/

Mirth → Django endpoint (raw HL7)

🔹 GET /mirth/messages/

Dashboard of recent HL7 messages

### Message Traceability & Observability

- End-to-end message tracking with unique correlation IDs
- View raw HL7 payloads and parsed fields
- Supports integration troubleshooting and partner issue analysis

This feature reflects real integration support scenarios:
- Identifying dropped messages
- Verifying transformation accuracy
- Supporting vendor or client investigations


Detail viewer

🧪 Try It Yourself
## What This Demo Demonstrates

✔ Understanding of healthcare data standards (HL7 v2, FHIR, X12)  
✔ Ability to trace and troubleshoot data across systems  
✔ Experience supporting integration engines (Mirth Connect)  
✔ API-based integration and validation workflows  
✔ Production-style logging and observability mindset  

This project was intentionally designed to resemble real integration analyst work rather than a theoretical exercise.

No Mirth?

Use the Playground:
https://django-sam-healthcare.vercel.app/hl7/playground/