from django.urls import path
from .views import (
    ADTTriggerView,
    ADTMessageListAPI,
    ADTMessageDetailAPI,
    DFTMessageListAPI,
    DFTMessageDetailAPI,
)

urlpatterns = [
    # ADT
    path("trigger/",              ADTTriggerView.as_view(),        name="adt-trigger"),
    path("messages/",             ADTMessageListAPI.as_view(),     name="adt-message-list"),
    path("messages/<int:pk>/",    ADTMessageDetailAPI.as_view(),   name="adt-message-detail"),
    # DFT
    path("dft/",                  DFTMessageListAPI.as_view(),     name="dft-message-list"),
    path("dft/<int:pk>/",         DFTMessageDetailAPI.as_view(),   name="dft-message-detail"),
]
