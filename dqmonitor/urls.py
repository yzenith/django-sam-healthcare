from django.urls import path
from .views import dashboard, metrics_api

urlpatterns = [
    path("",        dashboard,   name="dq-dashboard"),
    path("metrics/", metrics_api, name="dq-metrics-api"),
]
