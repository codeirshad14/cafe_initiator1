"""
The customer's cart, kept in the Django session (no login, no cart table).

One cart per table: session key "cart_<qr_token>" holds {line key: qty}.
A line key is the dish id ("12"), or dish and portion for a sized dish
("12-5" = dish 12, portion 5, e.g. Butter Chicken Half).
"""

from decimal import Decimal

from django.db.models import Prefetch
from django.shortcuts import get_object_or_404

from menu.models import Category, MenuItem, MenuItemPortion

MAX_QTY = 20  # per dish (or portion), per round


def cart_key(table):
    return f"cart_{table.qr_token}"


def line_key(item, portion=None):
    """"12" for a dish, "12-5" for portion 5 of dish 12."""
    return f"{item.pk}-{portion.pk}" if portion else str(item.pk)


def read_cart(request, table):
    """{"12": 2, "15-3": 1}: line key to quantity."""
    return dict(request.session.get(cart_key(table), {}))


def write_cart(request, table, cart):
    """Save the cart back into the session (empty lines removed)."""
    request.session[cart_key(table)] = {key: qty for key, qty in cart.items() if qty > 0}


def clear_cart(request, table):
    request.session.pop(cart_key(table), None)


def can_be_ordered(item):
    """A dish guests may add right now."""
    return item.is_active and item.is_available and item.category.is_active


def change_qty(request, table, item, step, portion=None):
    """Add (step=1) or remove (step=-1) one of a dish (or one of its portions) in the table's cart.

    Sets cart_qty on the portion (or the dish) to the new quantity, for redrawing
    its control. Returns a short warning to show, or "" when all went fine.
    """
    cart = read_cart(request, table)
    key = line_key(item, portion)
    warning = ""

    if step > 0 and not can_be_ordered(item):
        cart.pop(key, None)
        warning = f"Sorry, {item.name} has just run out."
    else:
        cart[key] = max(0, min(cart.get(key, 0) + step, MAX_QTY))
        if step > 0 and cart[key] == MAX_QTY:
            warning = f"{MAX_QTY} is the most for one dish in one order."

    write_cart(request, table, cart)
    (portion or item).cart_qty = cart.get(key, 0)
    return warning


def add_qty(request, table, item, qty, portion=None):
    """Add `qty` of a dish (or one of its portions) at once, from the dish details sheet.

    Returns (added, warning): how many were really added (the line stops at
    MAX_QTY) and a short warning, or "".
    """
    if not can_be_ordered(item):
        return 0, f"Sorry, {item.name} has just run out."
    cart = read_cart(request, table)
    key = line_key(item, portion)
    before = cart.get(key, 0)
    cart[key] = min(before + max(qty, 0), MAX_QTY)
    write_cart(request, table, cart)
    added = cart[key] - before
    warning = f"{MAX_QTY} is the most for one dish in one order." if added < qty else ""
    return added, warning


def remove_line(request, table, item, portion=None):
    """Take a dish (or one portion of it) out of the cart completely: the cart's delete button."""
    cart = read_cart(request, table)
    cart.pop(line_key(item, portion), None)
    write_cart(request, table, cart)


def item_cart_total(cart, item, sizes):
    """How many of this dish are in the cart, all its sizes together (for the menu card badge)."""
    if sizes:
        return sum(cart.get(line_key(item, portion), 0) for portion in sizes)
    return cart.get(line_key(item), 0)


def with_counts(item, cart):
    """Ready one dish's buttons after a tap, as menu_with_cart does for the whole menu:
    its sizes (in menu order) and how many of the dish, and of each size, are in the cart."""
    item.sizes = list(item.portions.all())
    item.cart_qty = cart.get(line_key(item), 0)
    for portion in item.sizes:
        portion.cart_qty = cart.get(line_key(item, portion), 0)
    item.cart_total = item_cart_total(cart, item, item.sizes)
    return item


def keep_orderable_only(request, table, details):
    """Write back only the lines that can still be ordered (after cart_details found dropped ones)."""
    write_cart(request, table, {line["key"]: line["qty"] for line in details["lines"]})


def dish_and_portion(request, restaurant, item_id):
    """The dish of this restaurant tapped on, and the portion sent with the tap
    (POST "portion"), if any. 404 for another restaurant's dish or portion.

    A dish with portions must be ordered by portion: (item, None, warning) then.
    """
    item = get_object_or_404(MenuItem.objects.select_related("category"), pk=item_id, restaurant=restaurant)
    portion_id = request.POST.get("portion", "")
    if portion_id:
        return item, get_object_or_404(MenuItemPortion, pk=portion_id, item=item), ""
    if item.portions.exists():
        return item, None, f"Please pick a size of {item.name}."
    return item, None, ""


def menu_with_cart(restaurant, cart=None):
    """The menu as guests see it: shown categories that have shown dishes, in order.

    Each dish gets .sizes (its portions, maybe empty) and, when a cart is
    given, .cart_qty on the dish and on each portion.
    """
    cart = cart or {}
    portions = MenuItemPortion.objects.order_by("sort_order", "price")
    dishes = (
        MenuItem.objects.filter(is_active=True).order_by("sort_order", "name")
        .prefetch_related(Prefetch("portions", queryset=portions, to_attr="sizes"))
    )
    categories = Category.objects.filter(restaurant=restaurant, is_active=True).prefetch_related(
        Prefetch("items", queryset=dishes, to_attr="menu_items")
    )
    categories = [category for category in categories if category.menu_items]
    for category in categories:
        for item in category.menu_items:
            item.cart_qty = cart.get(line_key(item), 0)
            item.cart_total = item_cart_total(cart, item, item.sizes)
            for portion in item.sizes:
                portion.cart_qty = cart.get(line_key(item, portion), 0)
    return categories


def menu_facts(categories):
    """Counts for the menu's header and filters: dishes, veg dishes, and which food types exist."""
    dishes = [item for category in categories for item in category.menu_items]
    return {
        "dish_count": len(dishes),
        "veg_count": sum(1 for item in dishes if item.food_type == MenuItem.FoodType.VEG),
        "has_non_veg": any(item.food_type == MenuItem.FoodType.NON_VEG for item in dishes),
    }


def split_key(key):
    """"12-5" -> (12, 5); "12" -> (12, None). Anything else -> (None, None)."""
    dish, _, portion = key.partition("-")
    if not dish.isdigit() or (portion and not portion.isdigit()):
        return None, None
    return int(dish), int(portion) if portion else None


def cart_details(request, table):
    """Everything the cart screens need.

    Returns {"lines": [...], "count", "total", "dropped"}. Each line is
    {"key", "item", "portion", "name", "rate", "qty", "amount"}, where name is
    "Butter Chicken (Half)" for a portion. Dishes that were hidden or ran out
    since they were added are left out of lines and named in "dropped".
    """
    cart = read_cart(request, table)
    wanted = {key: split_key(key) for key in cart}
    item_ids = {dish for dish, _ in wanted.values() if dish}
    items = {
        item.pk: item
        for item in MenuItem.objects.filter(restaurant=table.restaurant, pk__in=item_ids)
        .select_related("category").prefetch_related("portions")
    }

    lines = []
    dropped = []
    for key, (dish_id, portion_id) in wanted.items():
        item = items.get(dish_id)
        if item is None:
            continue  # the dish was deleted
        sizes = {portion.pk: portion for portion in item.portions.all()}
        portion = sizes.get(portion_id) if portion_id else None
        if (portion_id and portion is None) or (sizes and portion is None):
            dropped.append(item.name)  # its sizes changed since it was added
            continue
        if not can_be_ordered(item):
            dropped.append(item.name)
            continue
        rate = portion.price if portion else item.price
        lines.append({
            "key": key,
            "item": item,
            "portion": portion,
            "name": f"{item.name} ({portion.name})" if portion else item.name,
            "rate": rate,
            "qty": cart[key],
            "amount": rate * cart[key],
        })

    # menu order: category, dish, then portion
    lines.sort(key=lambda line: (
        line["item"].category.sort_order, line["item"].sort_order, line["item"].name,
        line["portion"].sort_order if line["portion"] else 0,
    ))
    return {
        "lines": lines,
        "count": sum(line["qty"] for line in lines),
        "total": sum((line["amount"] for line in lines), Decimal("0.00")),
        "dropped": dropped,
    }
