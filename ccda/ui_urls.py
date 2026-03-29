from django.urls import path
from .views import ccda_list_page, ccda_download

urlpatterns = [
    path("",           ccda_list_page, name="ccda-list"),
    path("<int:pk>/download/", ccda_download, name="ccda-download"),
]
