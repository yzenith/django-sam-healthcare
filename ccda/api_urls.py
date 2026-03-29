from django.urls import path
from .views import CCDAGenerateView, CCDADocumentListAPI, CCDADocumentDetailAPI

urlpatterns = [
    path("generate/",          CCDAGenerateView.as_view(),     name="ccda-generate"),
    path("documents/",         CCDADocumentListAPI.as_view(),  name="ccda-document-list"),
    path("documents/<int:pk>/", CCDADocumentDetailAPI.as_view(), name="ccda-document-detail"),
]
