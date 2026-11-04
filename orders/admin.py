from django.contrib import admin

from .models import KOT, KOTItem, Notification, Order


class KOTInline(admin.TabularInline):
    model = KOT
    extra = 0
    fields = ["kot_no", "status", "note", "created_at"]
    readonly_fields = ["created_at"]
    show_change_link = True


class KOTItemInline(admin.TabularInline):
    model = KOTItem
    extra = 0
    fields = ["menu_item", "item_name", "rate", "qty", "amount", "is_cancelled"]
    raw_id_fields = ["menu_item"]


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ["order_no", "restaurant", "location", "table", "order_type", "customer_name", "source", "status",
                    "created_at"]
    list_filter = ["restaurant", "location", "order_type", "status", "source"]
    search_fields = ["order_no", "customer_name", "customer_phone"]
    list_select_related = ["restaurant", "location", "table"]
    readonly_fields = ["public_token", "created_at"]
    date_hierarchy = "created_at"
    inlines = [KOTInline]


@admin.register(KOT)
class KOTAdmin(admin.ModelAdmin):
    list_display = ["kot_no", "restaurant", "location", "order", "status", "created_at"]
    list_filter = ["restaurant", "location", "status"]
    list_select_related = ["restaurant", "location", "order"]
    inlines = [KOTItemInline]


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    """The bell's "New order" notes (orders/notification_views.py): made by the app, read by its staff."""

    list_display = ["order", "restaurant", "location", "created_at", "read_at", "read_by"]
    list_filter = ["restaurant", "location", ("read_at", admin.EmptyFieldListFilter)]
    list_select_related = ["order", "restaurant", "location", "read_by"]
    readonly_fields = ["restaurant", "location", "order", "created_at"]
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False  # made with each new order
