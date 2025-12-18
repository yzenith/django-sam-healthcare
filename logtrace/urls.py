from django.urls import path, include

urlpatterns = [
    path("api/trace/", include("logtrace.api_urls")),  # JSON only
    path("trace/", include("logtrace.ui_urls")),       # HTML only
]


