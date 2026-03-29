from django.contrib import admin
from .models import CCDADocument


@admin.register(CCDADocument)
class CCDADocumentAdmin(admin.ModelAdmin):
    list_display  = ["id", "patient", "document_type", "document_id", "created_at"]
    list_filter   = ["document_type"]
    search_fields = ["patient__mrn", "document_id"]
    readonly_fields = ["document_id", "created_at", "xml_content"]
