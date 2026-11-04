from django.contrib import admin

from .models import Booking, DiningTable


@admin.register(DiningTable)
class DiningTableAdmin(admin.ModelAdmin):
    list_display = ["name", "restaurant", "location", "section", "capacity", "is_takeaway", "is_active", "qr_token"]
    list_filter = ["restaurant", "location", "is_active", "is_takeaway"]
    search_fields = ["name", "section"]
    list_select_related = ["restaurant", "location"]
    readonly_fields = ["qr_token"]


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ["booking_no", "customer_name", "customer_phone", "restaurant", "location", "date", "time",
                    "guests", "table", "status", "source"]
    list_filter = ["restaurant", "location", "status", "source"]
    search_fields = ["booking_no", "customer_name", "customer_phone"]
    list_select_related = ["restaurant", "location", "table"]
    date_hierarchy = "date"
    readonly_fields = ["public_token", "created_at"]
