from django.contrib import admin

from .models import CafeWebsite, DemoRequest, Feedback


@admin.register(DemoRequest)
class DemoRequestAdmin(admin.ModelAdmin):
    list_display = ["restaurant_name", "name", "phone", "city", "tables", "is_contacted", "created_at"]
    list_editable = ["is_contacted"]
    list_filter = ["is_contacted", "city"]
    search_fields = ["restaurant_name", "name", "phone", "city"]
    readonly_fields = ["created_at"]


@admin.register(CafeWebsite)
class CafeWebsiteAdmin(admin.ModelAdmin):
    """The cafes' own websites (/cafe/<slug>/), filled in by each cafe: here to help when they ask."""

    list_display = ["restaurant", "is_on", "tagline", "updated_at"]
    list_filter = ["is_on"]
    search_fields = ["restaurant__name", "tagline"]
    list_select_related = ["restaurant"]


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    """Guests' feedback from the cafes' websites (each cafe reads its own in Cafe profile > Feedback)."""

    list_display = ["restaurant", "rating", "name", "phone", "show_on_site", "is_read", "created_at"]
    list_filter = ["restaurant", "rating", "show_on_site"]
    search_fields = ["name", "phone", "message", "restaurant__name"]
    readonly_fields = ["created_at"]
    list_select_related = ["restaurant"]
