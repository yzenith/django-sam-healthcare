from django.urls import path
from .views import loinc_lookup_page

urlpatterns = [
    path("", loinc_lookup_page, name="loinc-lookup"),
]
