from django.urls import path
from .views import SIUTriggerView, SIUMessageListAPI, SIUMessageDetailAPI

urlpatterns = [
    path("trigger/",            SIUTriggerView.as_view(),       name="siu-trigger"),
    path("messages/",           SIUMessageListAPI.as_view(),    name="siu-message-list"),
    path("messages/<int:pk>/",  SIUMessageDetailAPI.as_view(),  name="siu-message-detail"),
]
