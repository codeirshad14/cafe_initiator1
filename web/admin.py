from django.contrib import admin

from .models import DemoRequest


@admin.register(DemoRequest)
class DemoRequestAdmin(admin.ModelAdmin):
    list_display = ["restaurant_name", "name", "phone", "city", "tables", "is_contacted", "created_at"]
    list_editable = ["is_contacted"]
    list_filter = ["is_contacted", "city"]
    search_fields = ["restaurant_name", "name", "phone", "city"]
    readonly_fields = ["created_at"]
