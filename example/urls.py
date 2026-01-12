# example/urls.py
from django import views
from django.views.generic import TemplateView

from django.urls import path
from example.views import hl7_playground, HL7TransformView, MirthHL7View, mirth_message_detail, mirth_messages, home, patient_import_detail, patient_import_page, patient_import_rejects_csv


urlpatterns = [
    # path("", index, name="index"),        # ← 首页指向 index.html
    path("", home, name="home"),
    path("api/transform/", HL7TransformView.as_view(), name="hl7-transform"),
    path("hl7/playground/", hl7_playground, name="hl7-playground"),
    path("api/mirth/hl7/", MirthHL7View.as_view(), name="mirth-hl7"),
    path("mirth/messages/", mirth_messages, name="mirth-messages"),
    path("mirth/messages/<int:pk>/", mirth_message_detail, name="mirth-message-detail"),
    path("import/patients/", patient_import_page, name="patient-import"),
    path("import/patients/<int:pk>/", patient_import_detail, name="patient-import-detail"),
    path("import/patients/<int:pk>/rejects.csv", patient_import_rejects_csv, name="patient-import-rejects-csv"),
    path("overview/", TemplateView.as_view(template_name="overview.html"), name="overview"),



]
