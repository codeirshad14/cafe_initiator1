from django.contrib import admin

from .models import Category, MenuItem, MenuItemPortion


class PortionInline(admin.TabularInline):
    model = MenuItemPortion
    extra = 0
    fields = ["name", "price", "sort_order"]


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "restaurant", "sort_order", "is_active"]
    list_filter = ["restaurant", "is_active"]
    search_fields = ["name"]


@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    list_display = ["name", "restaurant", "category", "price", "food_type", "is_available", "is_active"]
    list_filter = ["restaurant", "food_type", "is_available", "is_active"]
    search_fields = ["name"]
    list_select_related = ["restaurant", "category"]
    inlines = [PortionInline]
