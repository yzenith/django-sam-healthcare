from django.urls import path
from .views import sftp_upload_page, sftp_run_detail_page

urlpatterns = [
    path("",        sftp_upload_page,    name="sftp-ingest"),
    path("<int:pk>/", sftp_run_detail_page, name="sftp-run-detail-page"),
]
