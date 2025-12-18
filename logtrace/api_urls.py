from django.urls import path
from .views import IngestAPIView, TraceLogListAPI, TraceLogDetailAPI

urlpatterns = [
    path("ingest/", IngestAPIView.as_view(), name="trace-ingest"),
    path("logs/", TraceLogListAPI.as_view(), name="trace-logs"),
    path("logs/<str:trace_id>/", TraceLogDetailAPI.as_view(), name="trace-log-detail"),
]
