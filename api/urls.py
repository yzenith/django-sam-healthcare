"""api URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView

handler404 = "example.views.custom_404"

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('django.contrib.auth.urls')),  # login, logout, password_change, etc.
    path('', include('example.urls')),
    path("api/trace/", include("logtrace.api_urls")),   # JSON only
    path("trace/", include("logtrace.ui_urls")),        # HTML only
    path("api/adt/",  include("adt.api_urls")),         # ADT REST API
    path("adt/",      include("adt.ui_urls")),          # ADT HTML UI
    path("dq/",       include("dqmonitor.urls")),       # DQ dashboard (HTML) + metrics API
    path("api/sftp/",        include("sftpingest.api_urls")),  # SFTP ingest REST API
    path("sftp/",            include("sftpingest.ui_urls")),   # SFTP ingest HTML UI
    path("api/ccda/",        include("ccda.api_urls")),        # C-CDA REST API
    path("ccda/",            include("ccda.ui_urls")),         # C-CDA HTML UI
    path("api/scheduling/",  include("scheduling.api_urls")),  # SIU scheduling REST API
    path("scheduling/",      include("scheduling.ui_urls")),   # SIU scheduling HTML UI
    path("api/loinc/",       include("loinc.api_urls")),       # LOINC search API
    path("loinc/",           include("loinc.ui_urls")),        # LOINC reference page

    # OpenAPI schema + docs
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/",   SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/",  SpectacularRedocView.as_view(url_name="schema"),   name="redoc"),
]

