"""
Guest pages (no login). Staff screens are in staff_views.py and delivery_views.py.

  public_menu        /r/<slug>/                the restaurant's menu for anyone: take away, delivery
  public_dish        /r/<slug>/dish/<id>/      one dish's details from the public menu
  menu_view          /r/<slug>/view/           the same menu to look at only (no ordering), its own QR
  view_dish          /r/<slug>/view/dish/<id>/ one dish's details from it
  customer_menu      /m/<qr_token>/            the table's QR menu: the table is known from the QR
  dish_detail        /m/<qr_token>/dish/<id>/  one dish's details, sizes and quantity
  cart_put / cart_add / cart_remove            HTMX: change the cart (kept in the session)
  cart_view          /m/<qr_token>/cart/       the cart, the order type, which bill, the details
  order_place        POST                      the cart becomes a KOT (services.place_kot)
  call_waiter        POST /m/<qr_token>/call/  "Call waiter" from a table's menu: to that table
  call_about_order   POST /track/<token>/call/ "Call waiter" / "Need help?" about an order (any type)
  order_track        /track/<token>/           the order's live status (and, once billed,
                                               "Rate your visit": web.views.order_feedback)
  order_track_lookup /m/<qr_token>/track/      find a recent order by its number
"""

import json
from datetime import timedelta

from django.contrib import messages
from django.db.models import Prefetch
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.locations import location_from_link
from core.models import Restaurant
from core.utils import is_htmx
from menu.models import MenuItem, MenuItemPortion
from tables.models import common_table, tables_to_pick, takeaway_table
from web.models import Feedback

from .cart import (
    MAX_QTY, add_qty, cart_details, change_qty, clear_cart, dish_and_portion, item_cart_total, keep_orderable_only,
    menu_facts, menu_with_cart, read_cart, remove_line, with_counts,
)
from .decorators import with_customer_table
from . import services
from .forms import CustomerOrderForm, TrackLookupForm
from .models import Notification, Order
from .services import (
    OrderNotAllowed, bill_choice, delivery_steps, kot_steps, order_headline, order_to_join, order_total, place_kot,
)


# ================================================================ helpers

def last_order_key(table):
    return f"last_order_{table.qr_token}"


def my_running_order(request, table):
    """The order this phone placed from this table's QR, while it is still going on.

    It can be a take-away order even when placed from a dining table, or a
    delivery still waiting to be confirmed or on its way.
    """
    token = request.session.get(last_order_key(table))
    if not token:
        return None
    order = Order.objects.filter(public_token=token, restaurant=table.restaurant).first()
    return order if order and order.is_live else None


def render_cart_page(request, table, form, cart, error=""):
    """The cart page, used both to show it and to show it again with problems."""
    return render(request, "orders/cart.html", {
        "table": table,
        "restaurant": table.restaurant,
        "menu_url": table.menu_path,  # take away / delivery: back to the one public menu
        "cart": cart,
        "form": form,
        "error": error,
        "max_qty": MAX_QTY,
        **bill_choice(table, my_running_order(request, table), guest=True),
    })


# ================================================================ public menu (view only)

def public_menu(request, slug):
    """The restaurant's menu for anyone: /r/<slug>/, for sharing on WhatsApp,
    Instagram or Google Maps.

    Orders from here are take-away, on the location's Takeaway table (name and
    mobile optional); ?at=<location> picks a location other than the main one.
    Dine-in stays on each table's own QR link, so nobody can order for a table
    they are not sitting at. With the Takeaway table switched off, the menu is
    view only.
    """
    restaurant = Restaurant.objects.filter(slug=slug).first()
    if restaurant is None or not restaurant.is_usable():
        return render(request, "orders/customer_closed.html", {"public": True}, status=404)

    counter = takeaway_table(restaurant, location_from_link(restaurant, request))
    if not counter.is_active or not restaurant.takes_orders:  # take away off, or Only Menu: view only
        return render_view_only_menu(request, restaurant)
    return render_menu(request, counter)


def menu_view(request, slug):
    """/r/<slug>/view/: the menu to look at only (its own QR, e.g. on the wall or the
    door): the same page as every menu, without + buttons, cart or ordering."""
    restaurant = Restaurant.objects.filter(slug=slug).first()
    if restaurant is None or not restaurant.is_usable():
        return render(request, "orders/customer_closed.html", {"public": True}, status=404)
    return render_view_only_menu(request, restaurant)


def render_view_only_menu(request, restaurant):
    categories = menu_with_cart(restaurant)
    return render(request, "orders/menu.html", {
        "restaurant": restaurant, "categories": categories, "ordering": False,
        "featured": featured_dish(categories), **menu_facts(categories),
        "call": phone_call_sheet(),  # just looking: "Need help?" calls the cafe
    })


def view_dish(request, slug, item_id):
    """One dish's details from the view-only menu: everything but "Add"."""
    restaurant = Restaurant.objects.filter(slug=slug).first()
    if restaurant is None or not restaurant.is_usable():
        return render(request, "orders/customer_closed.html", {"public": True}, status=404)
    return render_dish(request, {
        "restaurant": restaurant, "item": shown_dish(restaurant, item_id), "ordering": False,
        "back_url": reverse("orders:menu_view", args=[restaurant.slug]),
    })


def public_dish(request, slug, item_id):
    """One dish's details on the public menu: photo, tags, description, ingredients
    and sizes, with "Add" for a take-away order (view only when the Takeaway
    table is off). A sheet over the menu (HTMX), or a page of its own."""
    restaurant = Restaurant.objects.filter(slug=slug).first()
    if restaurant is None or not restaurant.is_usable():
        return render(request, "orders/customer_closed.html", {"public": True}, status=404)
    item = shown_dish(restaurant, item_id)
    counter = takeaway_table(restaurant, location_from_link(restaurant, request))
    ordering = counter.is_active and restaurant.takes_orders
    context = {
        "restaurant": restaurant, "item": item, "ordering": ordering,
        "back_url": counter.menu_path,
    }
    if ordering:
        item.cart_total = item_cart_total(read_cart(request, counter), item, item.sizes)
        context.update({"table": counter, "cart": cart_details(request, counter)})
    return render_dish(request, context)


def shown_dish(restaurant, item_id):
    """A dish guests can see (shown, in a shown category), with its sizes; 404 otherwise."""
    portions = MenuItemPortion.objects.order_by("sort_order", "price")
    dishes = MenuItem.objects.select_related("category").prefetch_related(
        Prefetch("portions", queryset=portions, to_attr="sizes")
    )
    return get_object_or_404(dishes, pk=item_id, restaurant=restaurant, is_active=True, category__is_active=True)


def render_dish(request, context):
    """The dish details: a sheet over the menu for HTMX, or a page of its own (opened as a link)."""
    if is_htmx(request):
        return render(request, "orders/_dish_sheet.html", context)
    return render(request, "orders/dish_page.html", context)


def featured_dish(categories):
    """The first dish with a photo, for the welcome banner (None when no dish has one)."""
    for category in categories:
        for item in category.menu_items:
            if item.image:
                return item
    return None


# ================================================================ menu + cart

@with_customer_table
def customer_menu(request, table):
    """A dining table's QR menu: category tabs, dish cards with + (or − 1 +), a tap
    opens the dish's details; the cart bar at the bottom.

    The counter (take away / delivery) has no menu of its own: its address (an
    old printed counter QR, a link) opens the one public menu instead.
    """
    if table.is_takeaway:
        return redirect(table.menu_path)
    return render_menu(request, table)


def order_type_key(table):
    return f"order_type_{table.qr_token}"


def public_order_types(table):
    """The public menu's three ways: [(code, label, icon)]; Delivery only when the restaurant delivers."""
    types = [(Order.OrderType.DINE_IN, "Dine in", "cup-hot"), (Order.OrderType.TAKEAWAY, "Take away", "bag")]
    if table.restaurant.delivery_enabled:
        types.append((Order.OrderType.DELIVERY, "Delivery", "bicycle"))
    return types


def render_menu(request, table):
    """The one guest menu page (orders/menu.html) for a table, or for the counter
    (the public menu: dine in / take away / delivery). Same look everywhere; only the
    words for "where you are" change (at_table). On the public menu the guest
    picks how they want it (?type=); the cart starts with that choice."""
    categories = menu_with_cart(table.restaurant, read_cart(request, table))
    context = {
        "table": table,
        "at_table": not table.is_takeaway,
        "restaurant": table.restaurant,
        "ordering": True,
        "categories": categories,
        "featured": featured_dish(categories),
        **menu_facts(categories),
        "cart": cart_details(request, table),
        "my_order": my_running_order(request, table),
    }
    # "Call waiter" / "Need help?" (always there): the table; else this phone's order; else the phone
    if can_call_waiter(table):
        context["call"] = table_call_sheet(table)
    elif context["my_order"] is not None:
        context["call"] = order_call_sheet(context["my_order"])
    else:
        context["call"] = phone_call_sheet()
    if table.is_takeaway:
        types = public_order_types(table)
        wanted = request.GET.get("type", "")
        if wanted in [code for code, _, _ in types]:
            request.session[order_type_key(table)] = wanted
        at = request.GET.get("at", "")
        context.update({
            "order_types": types,
            "order_type": request.session.get(order_type_key(table), types[0][0]),
            "location_query": f"at={at}" if at.isdigit() else "",
        })
    return render(request, "orders/menu.html", context)


@with_customer_table
def dish_detail(request, table, item_id):
    """One dish's details for the guest: photo, tags, description, ingredients,
    sizes (Qtr / Half / Full) and quantity, with "Add to order"."""
    item = shown_dish(table.restaurant, item_id)
    cart = read_cart(request, table)
    item.cart_total = item_cart_total(cart, item, item.sizes)
    return render_dish(request, {
        "restaurant": table.restaurant, "table": table, "item": item, "ordering": True,
        "back_url": table.menu_path,
        "cart": cart_details(request, table),  # the cart bar on the page of its own
    })


@require_POST
@with_customer_table
def cart_put(request, table, item_id):
    """HTMX, from the dish details sheet: add `qty` of the dish (in the chosen size).

    Sends back the dish card's control and the cart bar (both "out of band"),
    and tells the page to close the sheet.
    """
    item, portion, warning = dish_and_portion(request, table.restaurant, item_id)
    qty = request.POST.get("qty", "1")
    qty = int(qty) if qty.isdigit() else 1
    added = 0
    if not warning:
        added, warning = add_qty(request, table, item, max(1, min(qty, MAX_QTY)), portion)

    with_counts(item, read_cart(request, table))
    response = render(request, "orders/_dish_added.html", {
        "table": table, "item": item, "cart": cart_details(request, table),
    })
    events = {}
    if added:
        name = f"{item.name} ({portion.name})" if portion else item.name
        events["closeSheet"] = True
        events["showMessage"] = {"text": f"Added {added} × {name}.", "level": "success"}
    if warning:
        events["showMessage"] = {"text": warning, "level": "warning"}
    response["HX-Trigger"] = json.dumps(events)
    return response


def change_cart(request, table, item_id, step):
    """Add (step=1) or remove (step=-1) one of a dish (or one portion of it), then send back what changed.

    POST "all=1" takes the whole line out (the cart's delete button).
    From the menu: that dish card's control, plus the cart bar (hx-swap-oob).
    From the cart page (view=cart): the cart lines; an emptied cart goes back to the menu.
    """
    item, portion, warning = dish_and_portion(request, table.restaurant, item_id)
    if not warning and request.POST.get("all") == "1":
        remove_line(request, table, item, portion)
    elif not warning:
        warning = change_qty(request, table, item, step, portion)
    details = cart_details(request, table)

    if request.POST.get("view") == "cart":
        if not details["lines"]:
            response = HttpResponse(status=204)
            response["HX-Redirect"] = table.menu_path
            return response
        response = render(request, "orders/_cart_lines.html", {
            "table": table, "cart": details, "max_qty": MAX_QTY, "refresh_total": True,
        })
    else:
        with_counts(item, read_cart(request, table))
        response = render(request, "orders/_item_update.html", {"table": table, "item": item, "cart": details})

    if warning:
        response["HX-Trigger"] = json.dumps({"showMessage": {"text": warning, "level": "warning"}})
    return response


@require_POST
@with_customer_table
def cart_add(request, table, item_id):
    """HTMX: one more of this dish in the cart."""
    return change_cart(request, table, item_id, step=1)


@require_POST
@with_customer_table
def cart_remove(request, table, item_id):
    """HTMX: one less of this dish in the cart."""
    return change_cart(request, table, item_id, step=-1)


@with_customer_table
def cart_view(request, table):
    """Cart page: the dishes picked, the guest's name and note, and Place order."""
    cart = cart_details(request, table)
    error = ""
    if cart["dropped"]:
        # take out what ran out since it was added, and say so
        keep_orderable_only(request, table, cart)
        error = "Sorry, these just ran out and were taken out of your cart: " + ", ".join(cart["dropped"]) + "."
    if not cart["lines"] and not error:
        return redirect(table.menu_path)

    initial = {
        "customer_name": request.session.get("customer_name", ""),
        "customer_phone": request.session.get("customer_phone", ""),
        "customer_address": request.session.get("customer_address", ""),
    }
    if request.session.get(order_type_key(table)):  # picked on the public menu
        initial["order_type"] = request.session[order_type_key(table)]
    form = customer_form(table, initial=initial)
    return render_cart_page(request, table, form, cart, error)


def customer_form(table, *args, **kwargs):
    """The cart's details form. At a dining table: Dine in / Take away. At the
    counter (the public menu, the Takeaway QR): Dine in (a table of this location,
    or none: the Common table), Take away, or Delivery when the restaurant takes deliveries."""
    counter = table.is_takeaway
    return CustomerOrderForm(*args, counter=counter, delivery=counter and table.restaurant.delivery_enabled,
                             tables=tables_to_pick(table.location) if counter else None, **kwargs)


@require_POST
@with_customer_table
def order_place(request, table):
    """Send the cart to the kitchen as a new KOT, then open the order's live status page.

    Dine in: a round on the chosen bill: the table's order (shared), or the
    guest's own order ("My own bill"). Take away: a separate order on the
    restaurant's counter (Takeaway) table. Delivery (public menu): a separate
    order that waits for the restaurant to call and confirm it.
    Dine in from the public menu: an order of its own on the table the guest
    picked, or on the location's Common table when they picked none.
    """
    cart = cart_details(request, table)
    form = customer_form(table, request.POST)

    if not cart["lines"]:
        messages.info(request, "Your cart is empty. Add a dish first.")
        return redirect(table.menu_path)

    if cart["dropped"]:
        # something ran out while the guest was on the cart page: let them look again
        keep_orderable_only(request, table, cart)
        error = ("Sorry, these just ran out and were taken out of your cart: "
                 + ", ".join(cart["dropped"]) + ". Please check your order and place it again.")
        return render_cart_page(request, table, form, cart_details(request, table), error)

    if not form.is_valid():
        return render_cart_page(request, table, form, cart)

    order_type = form.cleaned_data["order_type"]
    dine_in = order_type == Order.OrderType.DINE_IN
    seat = table  # where the order goes
    if dine_in and table.is_takeaway:  # the public menu: the table picked, else the Common table
        seat = form.cleaned_data.get("table") or common_table(table.restaurant, table.location)
        join = None  # an order of its own: never someone else's bill from a public link
    elif dine_in:
        join = order_to_join(table, form.cleaned_data["bill"], my_running_order(request, table), guest=True)
    else:
        join = None
    # the name is optional (not for delivery): keep the order's name, else "Guest at T5" / "Takeaway guest"
    default_name = join.customer_name if join else (f"Guest at {seat.name}" if dine_in else "Takeaway guest")
    try:
        kot = place_kot(
            seat, cart["lines"],
            customer_name=form.cleaned_data["customer_name"] or default_name,
            customer_phone=form.cleaned_data["customer_phone"],
            customer_address=form.cleaned_data["customer_address"],
            note=form.cleaned_data["note"],
            order_type=order_type,
            add_to=join,
            to_confirm=order_type == Order.OrderType.DELIVERY,  # anyone can open the menu: staff call first
        )
    except OrderNotAllowed as problem:
        # the bill of the chosen order was made a moment ago: choose again
        return render_cart_page(request, table, form, cart, f"{problem} Please choose your own bill.")

    clear_cart(request, table)
    request.session["customer_name"] = form.cleaned_data["customer_name"]
    request.session["customer_phone"] = form.cleaned_data["customer_phone"]
    request.session["customer_address"] = form.cleaned_data["customer_address"]
    request.session[last_order_key(table)] = str(kot.order.public_token)
    if seat != table:  # "order more" opens that table's menu: there this order is this phone's own
        request.session[last_order_key(seat)] = str(kot.order.public_token)
    return redirect(reverse("orders:order_track", args=[kot.order.public_token]) + "?placed=1")


# ================================================================ the guest's bell
# "Call waiter" / "Need help?" is on every guest menu (a floating button) and order page,
# opening orders/_call_waiter.html. Where it goes depends on where the guest is:
#   a table's QR menu        -> that table               (call_waiter)
#   an order (status page, or the public menu once ordered) -> about that order
#                               (call_about_order): its table, else "Take away #216"
#   no order yet on the public menu -> the cafe's phone number (nothing to point staff to)

Reason = Notification.Reason
TABLE_CALLS = [Reason.CALL, Reason.WATER, Reason.BILL]
ORDER_CALLS = [Reason.HELP, Reason.STATUS, Reason.CALLBACK]
CALL_ICONS = {Reason.CALL: "person-raised-hand", Reason.WATER: "cup-straw", Reason.BILL: "receipt",
              Reason.HELP: "question-circle", Reason.STATUS: "clock-history", Reason.CALLBACK: "telephone-inbound"}


def can_call_waiter(table):
    """The bell is for a real dining table: staff know where to go. Not the counter
    (parcels) nor the Common table (no place to walk to)."""
    return not table.is_takeaway and not table.is_common


def order_call_reasons(order):
    """At a table (or the Common table): waiter, water, bill. A take-away or delivery: help,
    how long, call me (only with a mobile to call)."""
    if not order.is_parcel:
        return TABLE_CALLS
    return [reason for reason in ORDER_CALLS if reason != Reason.CALLBACK or order.customer_phone]


def call_sheet(url=None, reasons=(), title="Need help?", subtitle="", button="Need help?"):
    """What orders/_call_waiter.html and the floating button need. No url: the phone only."""
    return {"url": url, "title": title, "subtitle": subtitle, "button": button,
            "options": [(reason.value, reason.label, CALL_ICONS[reason]) for reason in reasons]}


def table_call_sheet(table):
    return call_sheet(reverse("orders:call_waiter", args=[table.qr_token]), TABLE_CALLS, "Call the waiter",
                      f"To {table.label}. What do you need?", "Call waiter")


def order_call_sheet(order):
    """About this order: to its table (dine in), or the order itself (a parcel, the Common table)."""
    table = services.table_to_walk_to(order)
    reasons = order_call_reasons(order)
    url = reverse("orders:call_about_order", args=[order.public_token])
    if table is not None:
        return call_sheet(url, reasons, "Call the waiter", f"To {table.label}. What do you need?", "Call waiter")
    if not order.is_parcel:  # the Common table: staff find them by the order
        return call_sheet(url, reasons, "Call the waiter", f"For your order #{order.order_no}. What do you need?",
                          "Call waiter")
    return call_sheet(url, reasons, "Need help?", f"About your order #{order.order_no}. What do you need?")


def phone_call_sheet():
    """No order yet (just looking at the menu): call the cafe."""
    return call_sheet(subtitle="Call us, or ask at the counter. Once you order, you can call us from here too.")


def call_done(request, called, reason, where):
    return render(request, "orders/_call_waiter_done.html", {
        "called": called, "reason": Reason(reason).label, "where": where,
    })


@require_POST
@with_customer_table
def call_waiter(request, table):
    """HTMX, from a table's QR menu: "Call waiter", "Water please" or "Bring the bill".
    The Floor staff's bells ring once with the table's name."""
    if not can_call_waiter(table):
        return HttpResponse(status=404)
    reason = request.POST.get("reason", "")
    if reason not in TABLE_CALLS:
        reason = Reason.CALL
    call = services.call_waiter(table, reason, my_running_order(request, table))
    return call_done(request, call is not None, reason, f"Someone is coming to {table.label}.")


@require_POST
def call_about_order(request, public_token):
    """HTMX, from the order's status page or the public menu: a call about this order. At a
    table it goes to the table; a take-away, a delivery or the Common table: to the order
    ("Take away #216: How long for my order?")."""
    order = get_object_or_404(Order.objects.select_related("restaurant", "table", "location"), public_token=public_token)
    if not order.is_live or not order.restaurant.is_usable():
        return HttpResponse(status=404)
    reasons = order_call_reasons(order)
    reason = request.POST.get("reason", "")
    if reason not in reasons:
        reason = reasons[0]
    table = services.table_to_walk_to(order)
    call = services.call_waiter(table, reason, order)
    if table is not None:
        where = f"Someone is coming to {table.label}."
    elif reason == Reason.CALLBACK:
        where = f"We will call {order.customer_phone} shortly."
    else:
        where = f"We have your message about order #{order.order_no}."
    return call_done(request, call is not None, reason, where)


# ================================================================ tracking

def order_track(request, public_token):
    """Live status of one order: every round (KOT) and its progress.

    The status block asks again every 10 seconds (HTMX) while the order is
    running; this same view then sends back just that block.
    """
    order = get_object_or_404(Order.objects.select_related("restaurant", "table"), public_token=public_token)
    kots = list(order.kots.prefetch_related("items"))
    for kot in kots:
        kot.steps = kot_steps(kot)
    headline, headline_icon = order_headline(order, kots)
    bill = order.current_bill()  # its own, or the one it was billed together on
    bill = bill if bill and bill.status != "CANCELLED" else None

    context = {
        "order": order,
        "restaurant": order.restaurant,
        "kots": kots,
        "headline": headline,
        "headline_icon": headline_icon,
        "total": order_total(kots),
        "delivery_steps": delivery_steps(order, kots) if order.is_delivery else None,
        "bill": bill,
        # another round for the same table (a take-away parcel is one order, so not there)
        "can_order_more": (
            order.status == Order.Status.OPEN and not order.is_parcel and order.table is not None
            and order.table.is_active and order.restaurant.is_usable()
        ),
        # "Call waiter" / "Need help?" while the order is going on (every order type)
        "call": order_call_sheet(order) if order.is_live and order.restaurant.is_usable() else None,
        # once the bill is made: "Rate your visit" (web.views.order_feedback), or their stars
        "feedback": Feedback.objects.filter(order=order).first() if bill else None,
    }
    if is_htmx(request):
        return render(request, "orders/_track_status.html", context)

    context["just_placed"] = request.GET.get("placed") == "1"
    context["header_title"] = f"Order #{order.order_no}"
    context["header_subtitle"] = order.restaurant.name
    if order.is_delivery:
        context["header_subtitle"] += " · Delivery"
    elif order.is_takeaway:
        context["header_subtitle"] += " · Take away"
    elif order.table:
        context["header_subtitle"] += f" · {order.table.label}"
        if context["can_order_more"]:
            context["menu_url"] = order.table.menu_path
    return render(request, "orders/order_track.html", context)


@with_customer_table
def order_track_lookup(request, table):
    """Find a recent order of this location by its number (numbers count per location), then open its status page."""
    form = TrackLookupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        since = timezone.now() - timedelta(hours=24)
        order = Order.objects.filter(
            location=table.location, order_no=form.cleaned_data["order_no"], created_at__gte=since,
        ).first()
        if order:
            return redirect("orders:order_track", public_token=order.public_token)
        form.add_error("order_no", "No order with this number today. Please check the number on your order screen.")

    return render(request, "orders/track_lookup.html", {
        "table": table, "restaurant": table.restaurant, "form": form,
    })
