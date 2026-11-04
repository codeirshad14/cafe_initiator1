from django.contrib import admin

from .models import Bill, BillItem, Offer, Payment


class BillItemInline(admin.TabularInline):
    model = BillItem
    extra = 0
    fields = ["item_name", "category_name", "rate", "qty", "amount"]
    readonly_fields = fields
    can_delete = False


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    fields = ["mode", "amount", "reference_no", "received_by", "created_at"]
    readonly_fields = ["created_at"]


@admin.register(Bill)
class BillAdmin(admin.ModelAdmin):
    list_display = ["bill_no", "restaurant", "location", "bill_date", "grand_total", "paid_amount", "status"]
    list_filter = ["restaurant", "location", "status", "bill_date"]
    search_fields = ["bill_no", "order__customer_name"]
    list_select_related = ["restaurant", "location"]
    date_hierarchy = "bill_date"
    inlines = [BillItemInline, PaymentInline]


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ["bill", "restaurant", "location", "mode", "amount", "reference_no", "created_at"]
    list_filter = ["restaurant", "location", "mode"]
    list_select_related = ["bill", "restaurant", "location"]


@admin.register(Offer)
class OfferAdmin(admin.ModelAdmin):
    list_display = ["name", "restaurant", "start_date", "end_date", "kind", "value", "min_bill", "is_active"]
    list_filter = ["restaurant", "kind", "is_active"]
    search_fields = ["name", "restaurant__name"]
    list_select_related = ["restaurant"]
    date_hierarchy = "start_date"
