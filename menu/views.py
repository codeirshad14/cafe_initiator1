import json

from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core import roles
from core.decorators import role_required
from core.pagination import paginate
from core.utils import delete_with_confirm, get_user_restaurant, htmx_saved, is_htmx

from .forms import CategoryForm, MenuItemForm, kept_portions, portion_formset
from .models import Category, MenuItem


# ================================================================ categories

def category_queryset(request):
    """This restaurant's categories, with how many items each one holds."""
    return Category.objects.filter(restaurant=get_user_restaurant(request)).annotate(item_count=Count("items"))


@role_required(*roles.MENU_SETUP)
def category_list(request):
    """Categories page: the list of menu sections."""
    categories, pager = paginate(category_queryset(request), request.GET)
    return render(request, "menu/category_list.html", {"categories": categories, "pager": pager})


@role_required(*roles.MENU_SETUP)
def category_rows(request):
    """HTMX: just the categories table, after a save, a delete or another page."""
    categories, pager = paginate(category_queryset(request), request.GET)
    return render(request, "menu/_category_rows.html", {"categories": categories, "pager": pager})


@role_required(*roles.MENU_SETUP)
def category_add(request):
    """Side panel: add a category."""
    if not is_htmx(request):
        return redirect("menu:category_list")
    restaurant = get_user_restaurant(request)

    if request.method == "POST":
        form = CategoryForm(request.POST, restaurant=restaurant)
        if form.is_valid():
            category = form.save(commit=False)
            category.restaurant = restaurant
            category.save()
            return htmx_saved(f"Category “{category.name}” added.")
    else:
        form = CategoryForm(restaurant=restaurant)

    return render(request, "menu/_category_form.html", {
        "form": form, "title": "Add category", "submit_label": "Add category",
    })


@role_required(*roles.MENU_SETUP)
def category_edit(request, pk):
    """Side panel: rename a category, change its order or hide it."""
    if not is_htmx(request):
        return redirect("menu:category_list")
    restaurant = get_user_restaurant(request)
    category = get_object_or_404(Category, pk=pk, restaurant=restaurant)

    if request.method == "POST":
        form = CategoryForm(request.POST, instance=category, restaurant=restaurant)
        if form.is_valid():
            form.save()
            return htmx_saved(f"Category “{category.name}” updated.")
    else:
        form = CategoryForm(instance=category, restaurant=restaurant)

    return render(request, "menu/_category_form.html", {
        "form": form, "title": f"Edit {category.name}", "submit_label": "Save changes",
    })


@role_required(*roles.MENU_SETUP)
def category_delete(request, pk):
    """Side panel: delete a category. Blocked while it still has items."""
    if not is_htmx(request):
        return redirect("menu:category_list")
    category = get_object_or_404(Category, pk=pk, restaurant=get_user_restaurant(request))
    return delete_with_confirm(
        request, category, "Category",
        "It still has menu items. Move or delete those items first, or just switch "
        "off “Show on the menu” to hide the whole category.",
    )


# ================================================================ menu items

def filtered_items(request):
    """This restaurant's items, narrowed by search, category and the "show" filter."""
    items = MenuItem.objects.filter(restaurant=get_user_restaurant(request)).select_related("category")

    q = request.GET.get("q", "").strip()
    if q:
        items = items.filter(Q(name__icontains=q) | Q(description__icontains=q))

    category = request.GET.get("category", "")
    if category.isdigit():
        items = items.filter(category_id=category)

    show = request.GET.get("show", "")
    if show == "in_stock":
        items = items.filter(is_available=True, is_active=True)
    elif show == "out_of_stock":
        items = items.filter(is_available=False)
    elif show == "hidden":
        items = items.filter(Q(is_active=False) | Q(category__is_active=False))
    return items.prefetch_related("portions")


@role_required(*roles.MENU_SETUP)
def menu_item_list(request):
    """Menu items page: search, filters and the item table."""
    restaurant = get_user_restaurant(request)
    items, pager = paginate(filtered_items(request), request.GET)
    return render(request, "menu/menu_item_list.html", {
        "items": items,
        "pager": pager,
        "categories": Category.objects.filter(restaurant=restaurant),
        "selected_category": request.GET.get("category", ""),
    })


@role_required(*roles.MENU_SETUP)
def menu_item_rows(request):
    """HTMX: just the item table, after a filter change, save, delete or another page."""
    items, pager = paginate(filtered_items(request), request.GET)
    return render(request, "menu/_menu_item_rows.html", {"items": items, "pager": pager})


def save_menu_item(form, portions, restaurant):
    """Check the dish form and its portion rows together; save both, or return None.

    A dish needs a price, or at least one portion. With portions, the dish's
    own price becomes its smallest portion's price ("from ₹99").
    """
    form_ok = form.is_valid()
    portions_ok = portions.is_valid()
    if not (form_ok and portions_ok):
        return None

    sizes = kept_portions(portions)
    if not sizes and not form.price_given:
        form.add_error("price", "Give a price, or add portions (Qtr / Half / Full) below.")
        return None

    price = min(size["price"] for size in sizes) if sizes else form.cleaned_data["price"]
    with transaction.atomic():
        item = form.save_for(restaurant, price)

        # 1. new and changed portion rows
        portions.instance = item
        for portion in portions.save(commit=False):
            portion.item = item
            portion.save()
        # 2. rows ticked "remove"
        for portion in portions.deleted_objects:
            portion.delete()
        # 3. keep the portions in the order they were typed (Qtr, Half, Full)
        kept_rows = [row for row in portions.forms if row.instance.pk and not row.cleaned_data.get("DELETE")]
        for position, row in enumerate(kept_rows):
            if row.instance.sort_order != position:
                row.instance.sort_order = position
                row.instance.save(update_fields=["sort_order"])
    return item


@role_required(*roles.MENU_SETUP)
def menu_item_add(request):
    """Side panel: add a dish, with an optional photo and optional portions (Qtr / Half / Full)."""
    if not is_htmx(request):
        return redirect("menu:menu_item_list")
    restaurant = get_user_restaurant(request)

    if request.method == "POST":
        form = MenuItemForm(request.POST, request.FILES, restaurant=restaurant)
        portions = portion_formset(request.POST, instance=MenuItem(restaurant=restaurant), extra=3)
        item = save_menu_item(form, portions, restaurant)
        if item:
            return htmx_saved(f"“{item.name}” added to {item.category}.")
    else:
        # opened from a filtered list: start with that category picked
        form = MenuItemForm(restaurant=restaurant, initial={"category": request.GET.get("category")})
        portions = portion_formset(instance=MenuItem(restaurant=restaurant), extra=3)

    return render(request, "menu/_menu_item_form.html", {
        "form": form, "portions": portions, "title": "Add menu item", "submit_label": "Add item",
    })


@role_required(*roles.MENU_SETUP)
def menu_item_edit(request, pk):
    """Side panel: change a dish's details, price, portions or photo."""
    if not is_htmx(request):
        return redirect("menu:menu_item_list")
    restaurant = get_user_restaurant(request)
    item = get_object_or_404(MenuItem, pk=pk, restaurant=restaurant)
    extra = 1 if item.portions.exists() else 3

    if request.method == "POST":
        form = MenuItemForm(request.POST, request.FILES, instance=item, restaurant=restaurant)
        portions = portion_formset(request.POST, instance=item, extra=extra)
        saved = save_menu_item(form, portions, restaurant)
        if saved:
            return htmx_saved(f"“{saved.name}” updated.")
    else:
        form = MenuItemForm(instance=item, restaurant=restaurant)
        portions = portion_formset(instance=item, extra=extra)

    return render(request, "menu/_menu_item_form.html", {
        "form": form, "portions": portions, "item": item,
        "title": f"Edit {item.name}", "submit_label": "Save changes",
    })


@role_required(*roles.MENU_SETUP)
def menu_item_delete(request, pk):
    """Side panel: delete a dish. Blocked once it has been ordered."""
    if not is_htmx(request):
        return redirect("menu:menu_item_list")
    item = get_object_or_404(MenuItem, pk=pk, restaurant=get_user_restaurant(request))
    return delete_with_confirm(
        request, item, "Menu item",
        "It is on old orders or bills, so it must stay for the records. "
        "Switch off “Show on the menu” instead to hide it from customers.",
    )


@require_POST
@role_required(*roles.STOCK)
def menu_item_toggle(request, pk):
    """HTMX: mark an item in stock / out of stock, then redraw its switch."""
    item = get_object_or_404(MenuItem, pk=pk, restaurant=get_user_restaurant(request))
    # the switch sends available=1 when it is on, nothing when it is off
    item.is_available = request.POST.get("available") == "1"
    item.save(update_fields=["is_available"])

    response = render(request, "menu/_availability_toggle.html", {"item": item})
    state = "back in stock" if item.is_available else "marked out of stock"
    response["HX-Trigger"] = json.dumps({
        "showMessage": {"text": f"“{item.name}” {state}.", "level": "success"},
    })
    return response
