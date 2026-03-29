from django.http import JsonResponse
from django.shortcuts import render
from .codes import LOINC_CODES, CATEGORIES


def loinc_search_api(request):
    """
    GET /api/loinc/search/?q=<term>&category=<cat>

    Returns JSON list of matching LOINC codes.
    Searches code, name, long_name (case-insensitive).
    """
    q        = request.GET.get("q", "").strip().lower()
    category = request.GET.get("category", "").strip()

    results = []
    for code, info in LOINC_CODES.items():
        if category and info["category"] != category:
            continue
        if q:
            haystack = f"{code} {info['name']} {info['long_name']}".lower()
            if q not in haystack:
                continue
        results.append({"code": code, **info})

    results.sort(key=lambda r: r["category"] + r["name"])
    return JsonResponse({"count": len(results), "results": results[:100]})


def loinc_lookup_page(request):
    """GET /loinc/ — searchable LOINC reference table."""
    return render(request, "loinc/lookup.html", {"categories": CATEGORIES})
