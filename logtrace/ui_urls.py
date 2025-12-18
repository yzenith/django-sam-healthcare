from django.urls import path
from .views import TraceLogListPage, TraceLogDetailPage, TraceIngestPage

urlpatterns = [
    path("logs/", TraceLogListPage.as_view(), name="trace-logs-page"),
    path("logs/<str:trace_id>/", TraceLogDetailPage.as_view(), name="trace-detail-page"),
    path("trace/ingest/", TraceIngestPage.as_view(), name="trace-ingest-page"),
]
