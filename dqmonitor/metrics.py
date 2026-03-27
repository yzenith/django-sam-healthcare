"""
dqmonitor/metrics.py
~~~~~~~~~~~~~~~~~~~~
All data-quality metric computations live here, pulling from the existing
HL7MessageLog, TraceLog, ADTMessage, and DFTMessage tables without adding
any new models.

Design principles:
  - Every public function returns plain dicts/lists — no ORM objects cross
    the boundary so the JSON serializer never hits lazy-load surprises.
  - Each function performs the minimum number of DB queries (aggregates only).
  - Delay threshold and lookback window are module-level constants so they
    can be adjusted without touching view logic.
"""

from datetime import timedelta

from django.db.models import Avg, Count, Q
from django.db.models.functions import TruncHour
from django.utils import timezone

from example.models import HL7MessageLog
from logtrace.models import TraceLog
from adt.models import ADTMessage, DFTMessage

# ── Tunable constants ─────────────────────────────────────────────────────────

DELAY_THRESHOLD_SECONDS = 300   # message stuck in RECEIVED/VALIDATED > 5 min
HOURLY_LOOKBACK_HOURS   = 24    # window for the hourly-volume chart
RECENT_ROWS             = 20    # rows shown in the "recent messages" table
FLAG_LIMIT              = 50    # max flagged messages returned

# ── Colour palette (shared between server-side context and JSON API) ──────────

STATUS_COLOURS = {
    "TRANSFORMED": "#198754",   # green
    "VALIDATED":   "#0dcaf0",   # cyan
    "RECEIVED":    "#6c757d",   # grey
    "FAILED":      "#dc3545",   # red
}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _pct(numerator: int, denominator: int) -> float:
    return round(numerator / denominator * 100, 1) if denominator else 0.0


def _ms_label(ms: float | None) -> str:
    if ms is None:
        return "—"
    return f"{round(ms)} ms" if ms < 1000 else f"{ms / 1000:.2f} s"


# ── HL7 message metrics ────────────────────────────────────────────────────────

def hl7_summary() -> dict:
    """Aggregate counts, success rate, and quality-flag counts from HL7MessageLog."""
    qs   = HL7MessageLog.objects.all()
    total = qs.count()

    # Status distribution in one query
    rows = (
        qs.values("processing_status")
          .annotate(n=Count("id"))
    )
    dist = {r["processing_status"]: r["n"] for r in rows}

    transformed = dist.get("TRANSFORMED", 0)
    failed      = dist.get("FAILED",      0)
    validated   = dist.get("VALIDATED",   0)
    received    = dist.get("RECEIVED",    0)

    # Incomplete: missing patient_id OR validation error category
    incomplete_count = qs.filter(
        Q(patient_id="") | Q(error_category=HL7MessageLog.ErrorCategory.VALIDATION)
    ).count()

    # Delayed: still in early-stage status past the threshold
    cutoff = timezone.now() - timedelta(seconds=DELAY_THRESHOLD_SECONDS)
    delayed_count = qs.filter(
        processing_status__in=[
            HL7MessageLog.ProcessingStatus.RECEIVED,
            HL7MessageLog.ProcessingStatus.VALIDATED,
        ],
        created_at__lt=cutoff,
    ).count()

    return {
        "total":            total,
        "transformed":      transformed,
        "failed":           failed,
        "validated":        validated,
        "received":         received,
        "success_rate":     _pct(transformed, total),
        "error_rate":       _pct(failed, total),
        "incomplete_count": incomplete_count,
        "delayed_count":    delayed_count,
        "flagged_count":    incomplete_count + delayed_count,
        "dist":             dist,
    }


def hl7_errors_by_type() -> list[dict]:
    """Error count grouped by message type, descending."""
    return list(
        HL7MessageLog.objects
        .filter(processing_status=HL7MessageLog.ProcessingStatus.FAILED)
        .values("message_type")
        .annotate(count=Count("id"))
        .order_by("-count")[:10]
    )


def hl7_hourly_volume() -> list[dict]:
    """Hourly total + failed message counts for the last HOURLY_LOOKBACK_HOURS."""
    since = timezone.now() - timedelta(hours=HOURLY_LOOKBACK_HOURS)
    rows = (
        HL7MessageLog.objects
        .filter(created_at__gte=since)
        .annotate(hour=TruncHour("created_at"))
        .values("hour")
        .annotate(
            total=Count("id"),
            failed=Count("id", filter=Q(processing_status="FAILED")),
        )
        .order_by("hour")
    )
    return [
        {
            "hour":   r["hour"].strftime("%H:%M") if r["hour"] else "?",
            "hour_iso": r["hour"].isoformat() if r["hour"] else "",
            "total":  r["total"],
            "failed": r["failed"],
        }
        for r in rows
    ]


def hl7_flagged_messages() -> list[dict]:
    """
    Returns messages flagged for data-quality issues.

    Flag types:
      INCOMPLETE – patient_id is blank (PID-3 missing) or VALIDATION error
      DELAYED    – stuck in RECEIVED/VALIDATED beyond the delay threshold
    """
    flags: list[dict] = []

    # --- INCOMPLETE ---
    incomplete_qs = (
        HL7MessageLog.objects
        .filter(Q(patient_id="") | Q(error_category=HL7MessageLog.ErrorCategory.VALIDATION))
        .order_by("-created_at")[:FLAG_LIMIT]
        .values("id", "created_at", "message_type", "processing_status",
                "patient_id", "error_category", "error_message", "trace_id")
    )
    for row in incomplete_qs:
        reason = (
            "Missing patient ID (PID-3)"
            if not row["patient_id"]
            else f"Validation error: {row['error_category']}"
        )
        flags.append({
            "flag_type":         "INCOMPLETE",
            "source":            "HL7MessageLog",
            "id":                row["id"],
            "trace_id":          row["trace_id"] or "",
            "message_type":      row["message_type"] or "—",
            "patient_id":        row["patient_id"] or "—",
            "processing_status": row["processing_status"],
            "reason":            reason,
            "created_at":        row["created_at"].isoformat(),
        })

    # --- DELAYED ---
    cutoff = timezone.now() - timedelta(seconds=DELAY_THRESHOLD_SECONDS)
    delayed_qs = (
        HL7MessageLog.objects
        .filter(
            processing_status__in=[
                HL7MessageLog.ProcessingStatus.RECEIVED,
                HL7MessageLog.ProcessingStatus.VALIDATED,
            ],
            created_at__lt=cutoff,
        )
        .order_by("created_at")[:FLAG_LIMIT]
        .values("id", "created_at", "message_type", "processing_status",
                "patient_id", "trace_id")
    )
    for row in delayed_qs:
        age_s = int((timezone.now() - row["created_at"]).total_seconds())
        flags.append({
            "flag_type":         "DELAYED",
            "source":            "HL7MessageLog",
            "id":                row["id"],
            "trace_id":          row["trace_id"] or "",
            "message_type":      row["message_type"] or "—",
            "patient_id":        row["patient_id"] or "—",
            "processing_status": row["processing_status"],
            "reason":            f"Stuck in {row['processing_status']} for {age_s}s (threshold {DELAY_THRESHOLD_SECONDS}s)",
            "created_at":        row["created_at"].isoformat(),
        })

    # Deduplicate by id (a message could be both incomplete AND delayed)
    seen, deduped = set(), []
    for f in flags:
        key = (f["source"], f["id"], f["flag_type"])
        if key not in seen:
            seen.add(key)
            deduped.append(f)

    return deduped[:FLAG_LIMIT]


def hl7_recent(n: int = RECENT_ROWS) -> list[dict]:
    """Last N HL7 messages for the summary table."""
    return list(
        HL7MessageLog.objects
        .order_by("-created_at")[:n]
        .values("id", "created_at", "message_type", "processing_status",
                "patient_id", "error_category", "has_x12", "trace_id")
    )


# ── Latency metrics (from TraceLog.duration_ms) ───────────────────────────────

def latency_metrics() -> dict:
    """Average processing latency from TraceLog, overall and per input_type."""
    qs = TraceLog.objects.filter(duration_ms__isnull=False)

    overall = qs.aggregate(avg=Avg("duration_ms"))["avg"]

    by_type = list(
        qs.values("input_type")
          .annotate(avg_ms=Avg("duration_ms"), count=Count("id"))
          .order_by("input_type")
    )

    return {
        "avg_ms":       round(overall, 1) if overall is not None else None,
        "avg_ms_label": _ms_label(overall),
        "by_type":      [
            {
                "input_type": r["input_type"],
                "avg_ms":     round(r["avg_ms"], 1),
                "count":      r["count"],
            }
            for r in by_type
        ],
    }


# ── Cross-source summary counts ───────────────────────────────────────────────

def source_counts() -> dict:
    """Quick counts from every message source for the summary bar."""
    trace_total   = TraceLog.objects.count()
    trace_failed  = TraceLog.objects.filter(status=TraceLog.Status.FAILED).count()
    adt_total     = ADTMessage.objects.count()
    dft_total     = DFTMessage.objects.count()

    return {
        "trace_total":  trace_total,
        "trace_failed": trace_failed,
        "adt_total":    adt_total,
        "dft_total":    dft_total,
    }


# ── Master payload (single function for both view + JSON API) ─────────────────

def build_metrics() -> dict:
    """
    Assemble all metrics into a single dict.  Called by both the HTML view
    (for template context) and the JSON endpoint (for auto-refresh).
    """
    summary  = hl7_summary()
    latency  = latency_metrics()
    sources  = source_counts()
    errors   = hl7_errors_by_type()
    hourly   = hl7_hourly_volume()
    flags    = hl7_flagged_messages()
    recent   = hl7_recent()

    # Prepare Chart.js-ready arrays from status distribution
    status_order   = ["TRANSFORMED", "VALIDATED", "RECEIVED", "FAILED"]
    status_labels  = ["Transformed", "Validated", "Received", "Failed"]
    status_data    = [summary["dist"].get(s, 0) for s in status_order]
    status_colours = [STATUS_COLOURS[s] for s in status_order]

    # Error-by-type chart arrays
    error_labels = [e["message_type"] or "(unknown)" for e in errors]
    error_data   = [e["count"] for e in errors]

    # Hourly chart arrays
    hourly_labels = [h["hour"] for h in hourly]
    hourly_total  = [h["total"] for h in hourly]
    hourly_failed = [h["failed"] for h in hourly]

    return {
        # ── Summary cards ──────────────────────────────────────────────────
        "total_hl7":       summary["total"],
        "success_rate":    summary["success_rate"],
        "error_rate":      summary["error_rate"],
        "avg_latency_ms":  latency["avg_ms"],
        "avg_latency_label": latency["avg_ms_label"],
        "flagged_count":   summary["flagged_count"],
        "incomplete_count": summary["incomplete_count"],
        "delayed_count":   summary["delayed_count"],

        # ── Cross-source counts ────────────────────────────────────────────
        "trace_total":     sources["trace_total"],
        "trace_failed":    sources["trace_failed"],
        "adt_total":       sources["adt_total"],
        "dft_total":       sources["dft_total"],

        # ── Chart.js payloads ──────────────────────────────────────────────
        "status_labels":   status_labels,
        "status_data":     status_data,
        "status_colours":  status_colours,

        "error_labels":    error_labels,
        "error_data":      error_data,

        "hourly_labels":   hourly_labels,
        "hourly_total":    hourly_total,
        "hourly_failed":   hourly_failed,

        # ── Tables ─────────────────────────────────────────────────────────
        "flags":           flags,
        "recent":          [
            {**r, "created_at": r["created_at"].isoformat()}
            for r in recent
        ],

        # ── Latency breakdown (for tooltip / table) ────────────────────────
        "latency_by_type": latency["by_type"],

        # ── Refresh metadata ───────────────────────────────────────────────
        "refreshed_at":    timezone.now().isoformat(),
        "delay_threshold_s": DELAY_THRESHOLD_SECONDS,
    }
