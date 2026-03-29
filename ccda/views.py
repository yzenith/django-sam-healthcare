import logging

from django.http import HttpResponse
from django.shortcuts import render, get_object_or_404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import generics

from example.models import PatientRecord
from .models import CCDADocument
from .generator import generate_ccda
from .serializers import CCDADocumentSerializer, CCDADocumentListSerializer

logger = logging.getLogger("ccda")


# ── REST ──────────────────────────────────────────────────────────────────────

class CCDAGenerateView(APIView):
    """
    POST /api/ccda/generate/

    Body: { "mrn": "P-00042", "document_type": "CCD" }

    Looks up the PatientRecord and any linked ClinicalRecords, generates a
    C-CDA R2.1 XML document, stores it, and returns the full document.
    """

    def post(self, request):
        mrn = request.data.get("mrn", "").strip()
        doc_type = request.data.get("document_type", "CCD").strip().upper()

        if not mrn:
            return Response({"detail": "mrn is required."}, status=400)

        if doc_type not in CCDADocument.DocumentType.values:
            return Response(
                {"detail": f"document_type must be one of {CCDADocument.DocumentType.values}."},
                status=400,
            )

        patient = PatientRecord.objects.filter(mrn=mrn).first()
        if not patient:
            return Response({"detail": f"No patient found with MRN '{mrn}'."}, status=404)

        # Pull clinical records from sftpingest if available
        clinical_dicts = []
        try:
            from sftpingest.models import ClinicalRecord
            for rec in ClinicalRecord.objects.filter(mrn=mrn).order_by("visit_date")[:50]:
                clinical_dicts.append({
                    "mrn":            rec.mrn,
                    "visit_date":     rec.visit_date,
                    "visit_type":     rec.visit_type,
                    "diagnosis_code": rec.diagnosis_code,
                    "procedure_code": rec.procedure_code,
                    "provider_id":    rec.provider_id,
                    "facility_code":  rec.facility_code,
                    "notes":          rec.notes,
                })
        except Exception:
            pass

        patient_dict = {
            "mrn":        patient.mrn,
            "first_name": patient.first_name,
            "last_name":  patient.last_name,
            "dob":        patient.dob,
            "gender":     patient.gender,
            "address1":   patient.address1,
            "city":       patient.city,
            "state":      patient.state,
            "zip_code":   patient.zip_code,
        }

        xml = generate_ccda(patient_dict, clinical_dicts, doc_type)

        doc = CCDADocument.objects.create(
            patient=patient,
            document_type=doc_type,
            xml_content=xml,
        )

        logger.info("ccda_generated mrn=%s doc_type=%s doc_id=%s", mrn, doc_type, doc.document_id)
        return Response(CCDADocumentSerializer(doc).data, status=201)


class CCDADocumentListAPI(generics.ListAPIView):
    """GET /api/ccda/documents/"""
    queryset         = CCDADocument.objects.select_related("patient").all()
    serializer_class = CCDADocumentListSerializer


class CCDADocumentDetailAPI(generics.RetrieveAPIView):
    """GET /api/ccda/documents/<pk>/"""
    queryset         = CCDADocument.objects.select_related("patient").all()
    serializer_class = CCDADocumentSerializer


# ── HTML ──────────────────────────────────────────────────────────────────────

def ccda_list_page(request):
    """GET /ccda/ — C-CDA generator UI + recent documents."""
    patients  = PatientRecord.objects.all()[:200]
    documents = CCDADocument.objects.select_related("patient").all()[:30]
    return render(request, "ccda/ccda_list.html", {
        "patients":  patients,
        "documents": documents,
    })


def ccda_download(request, pk):
    """GET /ccda/<pk>/download/ — stream the XML as a downloadable file."""
    doc = get_object_or_404(CCDADocument, pk=pk)
    filename = f"CCDA_{doc.patient.mrn}_{doc.document_id}.xml"
    resp = HttpResponse(doc.xml_content, content_type="application/xml")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp
