from django.urls import path
from .views import adt_list_page, dft_list_page

urlpatterns = [
    path("",     adt_list_page, name="adt-list"),
    path("dft/", dft_list_page, name="dft-list"),
]
