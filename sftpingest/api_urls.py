from django.urls import path
from .views import SFTPUploadView, SFTPRunListAPI, SFTPRunDetailAPI

urlpatterns = [
    path("upload/",       SFTPUploadView.as_view(),  name="sftp-upload"),
    path("runs/",         SFTPRunListAPI.as_view(),   name="sftp-run-list"),
    path("runs/<int:pk>/", SFTPRunDetailAPI.as_view(), name="sftp-run-detail"),
]
