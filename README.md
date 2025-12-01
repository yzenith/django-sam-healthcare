# HL7 → FHIR → X12 837 Integration Demo

A small end-to-end healthcare integration demo that shows how to:

- Receive **HL7 v2 ADT** messages via **Mirth Connect**
- Forward them to a **Django REST API** deployed on **Vercel**
- Transform HL7 into **FHIR Patient / Encounter**
- Generate a simplified **X12 837** claim
- Store message logs in **Neon Postgres**
- Visualize the pipeline via a **web dashboard**

This project is designed to demonstrate practical skills for healthcare integration / interoperability roles (HL7, FHIR, EDI, Mirth).

---

## Features

- **HL7 v2 ADT → FHIR**  
  Basic parsing of MSH / PID / PV1 segments into FHIR Patient and Encounter resources.

- **HL7 v2 → X12 837**  
  Generates a simplified 837P claim based on the HL7 encounter data.

- **Mirth Connect Integration**  
  - Source: TCP Listener (HL7 v2.x)  
  - Destination: HTTP Sender posting raw HL7 to the Django API

- **Microservice API**  
  - `/api/transform/` – HL7 → FHIR + X12 (HL7 Playground)  
  - `/api/mirth/hl7/` – HL7 endpoint used by Mirth, with logging

- **Message Logging & Dashboard**  
  - Messages persisted into Neon Postgres (`HL7MessageLog`)  
  - `/mirth/messages/` – list of recent messages  
  - `/mirth/messages/<id>/` – detail view (raw HL7, FHIR JSON, 837)

- **HL7 Playground**  
  `/hl7/playground/` – paste an HL7 v2 message in the browser and see the FHIR + 837 output immediately.

---

## Architecture

```mermaid
flowchart LR
    EHR["External System<br/>(EHR / LIS / PMS)"] -->|"HL7 v2 ADT over TCP (MLLP)"| Mirth["Mirth Connect<br/>TCP Listener Channel"]

    Mirth -->|"HTTP POST<br/>text/plain HL7"| DjangoAPI["Django Healthcare API<br/>(Vercel Serverless)"]
    DjangoAPI -->|"Parse HL7 v2"| FHIR["FHIR Patient<br/>FHIR Encounter"]
    FHIR -->|"Map clinical data"| X12["Generate X12 837<br/>Professional Claim"]

    DjangoAPI -->|"Insert log row"| Neon["Neon Postgres<br/>HL7MessageLog"]

    Neon -->|"SELECT last 50"| Dashboard["Web Dashboard<br/>/mirth/messages/"]
    DjangoAPI -->|"JSON (Patient, Encounter, 837)"| Mirth
