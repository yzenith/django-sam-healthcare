# example/urls.py
from django.urls import path
from example.views import index, HL7TransformView


urlpatterns = [
    path("", index, name="index"),        # ← 首页指向 index.html
    path("api/transform/", HL7TransformView.as_view(), name="hl7-transform"),
]
