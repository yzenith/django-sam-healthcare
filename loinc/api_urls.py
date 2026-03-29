from django.urls import path
from .views import loinc_search_api

urlpatterns = [
    path("search/", loinc_search_api, name="loinc-search"),
]
