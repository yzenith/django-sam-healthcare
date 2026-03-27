import json
import logging

from django.http import JsonResponse
from django.shortcuts import render

from .metrics import build_metrics

logger = logging.getLogger("dqmonitor")


def dashboard(request):
    """
    GET /dq/
    HTML dashboard with summary cards, Chart.js charts, and quality-flag table.
    The template bootstraps Chart.js with the initial server-rendered data, then
    polls /api/dq/metrics/ every 30 s to keep everything live.
    """
    data = build_metrics()
    # Pass JSON-encoded versions for use in the <script> block
    context = {
        **data,
        "status_labels_json":  json.dumps(data["status_labels"]),
        "status_data_json":    json.dumps(data["status_data"]),
        "status_colours_json": json.dumps(data["status_colours"]),
        "error_labels_json":   json.dumps(data["error_labels"]),
        "error_data_json":     json.dumps(data["error_data"]),
        "hourly_labels_json":  json.dumps(data["hourly_labels"]),
        "hourly_total_json":   json.dumps(data["hourly_total"]),
        "hourly_failed_json":  json.dumps(data["hourly_failed"]),
    }
    return render(request, "dqmonitor/dashboard.html", context)


def metrics_api(request):
    """
    GET /api/dq/metrics/
    JSON endpoint consumed by the dashboard auto-refresh JS every 30 s.
    Returns the same payload as the HTML view's context — no auth required
    since the data is aggregate counts, not raw PHI.
    """
    try:
        data = build_metrics()
        return JsonResponse(data)
    except Exception as exc:
        logger.exception("metrics_api failed")
        return JsonResponse({"error": str(exc)}, status=500)
