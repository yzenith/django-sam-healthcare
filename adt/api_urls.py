from django.urls import path
from .views import ADTTriggerView, ADTMessageListAPI, ADTMessageDetailAPI

urlpatterns = [
    path("trigger/",         ADTTriggerView.as_view(),     name="adt-trigger"),
    path("messages/",        ADTMessageListAPI.as_view(),  name="adt-message-list"),
    path("messages/<int:pk>/", ADTMessageDetailAPI.as_view(), name="adt-message-detail"),
]
