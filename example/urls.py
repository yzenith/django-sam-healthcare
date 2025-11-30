# example/urls.py
from django.urls import path
from example.views import index, HL7TransformView, MirthHL7View, mirth_message_detail, mirth_messages


urlpatterns = [
    path("", index, name="index"),        # ← 首页指向 index.html
    path("api/transform/", HL7TransformView.as_view(), name="hl7-transform"),
    path("api/mirth/hl7/", MirthHL7View.as_view(), name="mirth-hl7"),
    path("mirth/messages/", mirth_messages, name="mirth-messages"),
    path("mirth/messages/<int:pk>/", mirth_message_detail, name="mirth-message-detail"),
]
