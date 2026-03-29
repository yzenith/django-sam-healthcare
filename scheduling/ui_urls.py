from django.urls import path
from .views import siu_list_page

urlpatterns = [
    path("", siu_list_page, name="siu-list"),
]
