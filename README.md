🏥 HL7 → FHIR → X12 837 Healthcare Integration Demo
Built by Sam Yan · Healthcare Interoperability Engineer

🌐 Live Demo: https://django-sam-healthcare.vercel.app/

📡 Mirth Logs: https://django-sam-healthcare.vercel.app/mirth/messages/

🧪 Playground: https://django-sam-healthcare.vercel.app/hl7/playground/

🚀 Overview

This project demonstrates a complete healthcare integration pipeline, built end-to-end with real interoperability standards:

HL7 v2 ADT ingestion (MLLP/TCP)

Mirth Connect TCP Listener + HTTP Sender

Django REST API (Serverless Vercel)

FHIR resource generation (Patient + Encounter)

X12 837 claim generation

Cloud database logging (Neon Postgres)

Web dashboard + message detail viewer

Interactive HL7 Playground (client-side tester)

This is a practical demo showing the same skills used in healthcare integration roles (Interface Engineer, Interoperability Engineer, API Integration Developer, etc.)

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
✔ HL7 v2 ADT Parsing

Extracts PID, PV1, demographics, encounter info, provider, etc.

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

🔹 GET /mirth/messages/<id>/

Detail viewer

🧪 Try It Yourself
Using Mirth?

Send an ADT^A01 message to your TCP Listener → It will appear on the dashboard.

No Mirth?

Use the Playground:
https://django-sam-healthcare.vercel.app/hl7/playground/