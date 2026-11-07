"""
Staff screens of the orders app (login needed). Guest pages are in guest_views.py,
deliveries and the rider's screen in delivery_views.py.

  floor               every table: free / occupied / bill printed      roles.FLOOR
  floor_table         one table: its orders (one tab per bill), KOTs   same
  floor_order         one take-away / delivery order                   same
  waiter_order        take an order on the staff phone                 roles.TABLE_ORDERS (tables)
                                                                       roles.COUNTER_ORDERS (take away, delivery)
  kitchen             KOT board: New / Preparing / Ready               roles.KITCHEN_BOARD
  kot_status          move a KOT to its next status (HTMX)             by role: services.KOT_MOVES
  waiter_ready        READY KOTs waiting to be served                  roles.READY_LIST
  kot_print           80 mm KOT slip                                   roles.PRINT_KOT
  kot_print_slip      the same slip as printer bytes (direct print)    same
  order_cancel        cancel a running order, with a reason            roles.CANCEL

Every screen shows the staff member's current location only (core/locations.py).
"""

import json
from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Prefetch
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from billing.models import Bill
from billing.services import cancel_bill
from core import roles
from core.decorators import role_required
from core.utils import get_user_location, get_user_restaurant, is_htmx
from menu.models import Category, MenuItem
from tables.models import Booking, DiningTable, takeaway_table
from tables.periods import booking_days, period_context

from .cart import (
    cart_details, change_qty, clear_cart, dish_and_portion, item_cart_total, keep_orderable_only, menu_with_cart,
    read_cart,
)
from .forms import OrderCancelForm, WaiterOrderForm
from .models import KOT, Order
from .printing import kot_slip
from .services import (
    OrderNotAllowed, add_timing, bill_choice, can_move_kot, cancel_order, kot_actions, move_kot, order_to_join,
    order_total, place_kot, running_orders, running_takeaway_orders,
)

FLOOR_ROLES = roles.FLOOR
ORDER_TAKER_ROLES = roles.TABLE_ORDERS
# the cashier answers the phone at the counter: take-away and delivery orders, not tables
COUNTER_ROLES = roles.COUNTER_ORDERS
KITCHEN_ROLES = roles.KITCHEN_BOARD
BILLING_ROLES = roles.BILLING

# what the message says after a KOT moves
MOVED_TEXT = {
    KOT.Status.PREPARING: "is being prepared",
    KOT.Status.READY: "is ready to serve",
    KOT.Status.SERVED: "is served",
    KOT.Status.CANCELLED: "is cancelled",
}


def show_message(response, text, level="success"):
    """Add a toast to an HTMX response (static/js/app.js shows it)."""
    response["HX-Trigger"] = json.dumps({"showMessage": {"text": text, "level": level}})
    return response


# ================================================================ floor

def floor_tables(location):
    """Every active dining table of the location, with what its floor tile needs.

    A table can hold more than one order (people paying separately); the tile
    adds them up: state, number of orders, amount, minutes since the first,
    rounds sent, cooking and ready.
    """
    running = Order.objects.filter(
        location=location, status__in=Order.RUNNING, order_type=Order.OrderType.DINE_IN,
    ).order_by("created_at").prefetch_related("kots__items")
    orders_by_table = {}
    for order in running:
        orders_by_table.setdefault(order.table_id, []).append(order)
    now = timezone.now()

    tables = list(DiningTable.objects.filter(location=location, is_active=True, is_takeaway=False))
    for table in tables:
        table.running = orders_by_table.get(table.pk, [])
        if not table.running:
            table.state = "free"
            continue
        all_billed = all(order.status == Order.Status.BILLED for order in table.running)
        table.state = "billed" if all_billed else "occupied"
        kots = [kot for order in table.running for kot in order.kots.all()]
        table.amount = order_total(kots)
        table.minutes = int((now - table.running[0].created_at).total_seconds() // 60)
        # the kitchen's progress: sent (not started yet), cooking, ready to serve
        table.new_count = sum(1 for kot in kots if kot.status == KOT.Status.NEW)
        table.cooking_count = sum(1 for kot in kots if kot.status == KOT.Status.PREPARING)
        table.ready_count = sum(1 for kot in kots if kot.status == KOT.Status.READY)
    return tables


def takeaway_orders(location):
    """The location's open take-away orders with what the takeaway list needs: amount, minutes, ready or cooking."""
    now = timezone.now()
    orders = list(running_takeaway_orders(location).prefetch_related("kots__items"))
    for order in orders:
        kots = list(order.kots.all())
        order.amount = order_total(kots)
        order.minutes = int((now - order.created_at).total_seconds() // 60)
        order.ready = any(kot.status == KOT.Status.READY for kot in kots)
        order.cooking = any(kot.status in (KOT.Status.NEW, KOT.Status.PREPARING) for kot in kots)
        order.bill = Bill.objects.filter(order=order).first()
    return orders


# a free table turns red ("Booked") only around its booking: from an hour
# before it starts until it ends (30 minutes, two hours, two days ...).
# Earlier in the day it stays green, with a small "Booked 9:30 PM" note.
BOOKED_FROM_BEFORE = timedelta(hours=1)


def mark_bookings(tables, location, now):
    """Give each table today's next booking (one not over yet, also one that
    started on an earlier day and runs on) and, while it is near (see above)
    and the table has no order, the "booked" (red) state."""
    today = now.date()
    booked = {}
    for booking in Booking.objects.filter(location=location, date__lte=today, end_date__gte=today,
                                          status__in=Booking.UPCOMING, table__isnull=False).order_by("date", "time"):
        starts, ends = timezone.make_aware(booking.starts_at), timezone.make_aware(booking.ends_at)
        if now >= ends:
            continue  # over (a no-show not marked yet): it no longer holds the table
        booking.is_near = now >= starts - BOOKED_FROM_BEFORE
        booked.setdefault(booking.table_id, []).append(booking)
    for table in tables:
        bookings = booked.get(table.pk, [])
        table.booking = bookings[0] if bookings else None
        table.more_bookings = len(bookings) - 1  # "+1 more" later today
        if table.state == "free" and table.booking and table.booking.is_near:
            table.state = "booked"


@role_required(*FLOOR_ROLES)
def floor(request):
    """Floor: a tile per table, free (green) / booked now (red) / occupied (orange) /
    bill printed (blue), plus the Takeaway and Deliveries chips. Refreshes every 10s.

    ?when=week|month|range (&from=&to=) shows a date-wise summary of those days'
    bookings instead of the tiles. Today (the tiles) by default.
    """
    restaurant, place = get_user_restaurant(request), get_user_location(request)
    tables = floor_tables(place)
    counter = takeaway_table(restaurant, place)
    parcels = takeaway_orders(place)

    today = timezone.localdate()
    mark_bookings(tables, place, timezone.localtime())
    period = period_context(request.GET, today)
    # This week / This month / Range: the summary, date by date
    summary_days = (booking_days(place, period["start"], period["end"], tables, today)
                    if period["when"] != "today" else [])

    deliveries = Order.objects.filter(location=place, order_type=Order.OrderType.DELIVERY,
                                      delivered_at__isnull=True).exclude(status=Order.Status.CANCELLED)
    context = {
        "delivery_enabled": restaurant.delivery_enabled,
        "delivery_to_confirm": deliveries.filter(status=Order.Status.PENDING).count(),
        "delivery_count": deliveries.count(),
        "bookings_today": Booking.objects.filter(location=place, date__lte=today, end_date__gte=today,
                                                 status__in=Booking.UPCOMING).count(),
        **period,  # the filter row; filter_query: the live grid asks again with the same filter
        "summary_days": summary_days,
        "summary_count": sum(len(day["bookings"]) for day in summary_days),
        "summary_guests": sum(day["guests"] for day in summary_days),
        "tables": tables,
        "free_count": sum(1 for t in tables if t.state == "free"),
        "booked_count": sum(1 for t in tables if t.state == "booked"),
        "occupied_count": sum(1 for t in tables if t.state == "occupied"),
        "billed_count": sum(1 for t in tables if t.state == "billed"),
        "counter": counter,
        "takeaway_count": len(parcels),
        "takeaway_ready": sum(1 for order in parcels if order.ready),
        "takeaway_amount": sum((order.amount for order in parcels), Decimal("0.00")),
        "can_take_order": request.user.staff.role in ORDER_TAKER_ROLES,
        "can_take_counter": request.user.staff.role in COUNTER_ROLES,  # New takeaway / New delivery
    }
    template = "orders/_floor_grid.html" if is_htmx(request) else "orders/floor.html"
    return render(request, template, context)


def table_order_context(request, table, order=None):
    """One order with its KOTs, timings and the buttons this role gets.

    For a dining table: the order picked with ?order=<id>, else its first running
    order; table_orders lists them all (a table can have separate bills).
    """
    role = request.user.staff.role
    table_orders = list(running_orders(table))
    if order is None:
        wanted = request.GET.get("order", "")
        order = next((o for o in table_orders if str(o.pk) == wanted), table_orders[0] if table_orders else None)
    kots = []
    if order:
        now = timezone.now()
        kots = list(order.kots.prefetch_related("items"))
        for kot in kots:
            add_timing(kot, now)
            kot.actions = kot_actions(kot, role)
    if order and order.is_parcel:
        poll_url = reverse("orders:floor_order", args=[order.pk])
    else:
        poll_url = reverse("orders:floor_table", args=[table.pk]) + (f"?order={order.pk}" if order else "")
    # two or more open orders here (the same people ordered twice): "Bill all together"
    open_here = [o for o in table_orders if o.status == Order.Status.OPEN]
    bill_together_url = ""
    if role in BILLING_ROLES and len(open_here) > 1 and not table.is_takeaway:
        first, *others = open_here
        bill_together_url = reverse("billing:bill_create", args=[first.pk]) + "?" + "&".join(
            f"join={other.pk}" for other in others)
    return {
        "table": table,
        "order": order,
        "table_orders": table_orders,
        "kots": kots,
        "total": order_total(kots),
        # its own bill, or the one it is billed together on (another order's, maybe another table's)
        "bill": (Bill.objects.filter(order=order).first() or order.joined_bill) if order else None,
        "can_bill": role in BILLING_ROLES,
        "can_view_bill": role in roles.BILL_VIEW,  # the waiter: sees the bill's amount
        # a parcel is one order: new rounds only for dine-in tables
        "can_take_order": role in ORDER_TAKER_ROLES and not table.is_takeaway,
        "can_cancel": role in roles.CANCEL and order is not None and order.status in Order.CANCELLABLE,
        "can_print": role in roles.PRINT_KOT,
        "poll_url": poll_url,  # the live block asks this address again every 10 seconds
        "bill_together_url": bill_together_url,
        "open_here": len(open_here),
    }


@role_required(*FLOOR_ROLES)
def floor_table(request, table_id):
    """One table: its running order, each KOT with status buttons, and what to do next.
    The Takeaway table shows its list of open take-away orders instead."""
    table = get_object_or_404(DiningTable, pk=table_id, location=get_user_location(request))
    if table.is_takeaway:
        template = "orders/_takeaway_list.html" if is_htmx(request) else "orders/takeaway_list.html"
        return render(request, template, {
            "table": table,
            "orders": takeaway_orders(table.location),
            "can_take_order": request.user.staff.role in COUNTER_ROLES,
            "can_bill": request.user.staff.role in BILLING_ROLES,
        })

    context = table_order_context(request, table)
    template = "orders/_table_order.html" if is_htmx(request) else "orders/floor_table.html"
    return render(request, template, context)


@role_required(*FLOOR_ROLES)
def floor_order(request, order_id):
    """One order on its own page (used for take-away parcels): its KOTs and what to do next."""
    order = get_object_or_404(Order.objects.select_related("table"), pk=order_id, location=get_user_location(request))
    context = table_order_context(request, order.table, order=order)
    template = "orders/_table_order.html" if is_htmx(request) else "orders/floor_table.html"
    return render(request, template, context)


@role_required(*roles.CANCEL)
def order_cancel(request, order_id):
    """Side panel: cancel a running order with a reason. The table becomes free.
    Its bill too, if one was printed and nothing is paid on it yet."""
    order = get_object_or_404(Order.objects.select_related("table"), pk=order_id, location=get_user_location(request))
    if not is_htmx(request):
        return redirect("orders:floor")

    bill = Bill.objects.filter(order=order).exclude(status=Bill.Status.CANCELLED).first()
    blocked = ""
    if order.status not in Order.CANCELLABLE:
        blocked = f"Order #{order.order_no} is {order.get_status_display().lower()}, so it cannot be cancelled here."
    elif order.joined_bill_id:  # its dishes are on another order's bill
        blocked = (f"Order #{order.order_no} is billed together on Bill #{order.joined_bill.bill_no}. "
                   f"Reopen or cancel that bill first.")
    elif bill and bill.payments.exists():
        blocked = f"Bill #{bill.bill_no} already has payments. Remove them on the bill first, then cancel."

    form = OrderCancelForm(request.POST or None)
    if request.method == "POST" and not blocked and form.is_valid():
        if bill:
            cancel_bill(bill, form.cleaned_data["reason"])  # cancels the order with it
        else:
            cancel_order(order, form.cleaned_data["reason"])
        response = HttpResponse(status=204)
        if order.is_delivery:
            messages.success(request, f"Delivery order #{order.order_no} cancelled.")
            response["HX-Redirect"] = reverse("orders:deliveries")
        elif order.is_takeaway:
            messages.success(request, f"Take-away order #{order.order_no} cancelled.")
            response["HX-Redirect"] = reverse("orders:floor_table", args=[order.table_id])
        else:
            messages.success(request, f"Order #{order.order_no} cancelled. {order.table.label} is free again.")
            response["HX-Redirect"] = reverse("orders:floor_table", args=[order.table_id])
        return response

    return render(request, "orders/_order_cancel_form.html", {
        "form": form, "order": order, "bill": bill, "blocked": blocked,
        "title": f"Cancel order #{order.order_no}", "submit_label": "Cancel order",
    })


# ================================================================ waiter: take an order

def waiter_table(request, table_id):
    """The table staff are ordering for: at their location, and switched on.
    A cashier may order only at the counter (take-away, delivery)."""
    table = get_object_or_404(DiningTable, pk=table_id, location=get_user_location(request), is_active=True)
    if request.user.staff.role not in ORDER_TAKER_ROLES and not table.is_takeaway:
        raise PermissionDenied("Table orders are taken by waiters.")
    return table


@role_required(*COUNTER_ROLES)
def waiter_takeaway(request):
    """"New takeaway" on the floor: the waiter screen for the location's Takeaway table."""
    counter = takeaway_table(get_user_restaurant(request), get_user_location(request))
    if not counter.is_active:
        messages.warning(request, "Take-away is switched off. Switch the Takeaway table on in Tables & QR.")
        return redirect("orders:floor")
    return redirect("orders:waiter_order", table_id=counter.pk)


@role_required(*COUNTER_ROLES)
def waiter_order(request, table_id):
    """Staff take an order: the menu with + / − and the round so far.

    At a table: Dine in (on the table's order, or a separate bill) or Take away.
    At the counter: Take away or Delivery.
    ?type=DELIVERY ("New delivery") and ?bill=<order id> or ?bill=new (from the
    table page) pick those choices in advance. ?add=<order id> ("Add items" on
    the Deliveries board): the dishes join that delivery, still to confirm or cooking.
    """
    table = waiter_table(request, table_id)
    return render_pos(request, table, bill_now=wants_bill_now(request, table, request.GET))


def growing_delivery(table, order_id):
    """The delivery "Add items" adds to: on this counter, still to confirm or not billed yet; else None."""
    if not table.is_takeaway or not str(order_id or "").isdigit():
        return None
    return Order.objects.filter(pk=order_id, table=table, order_type=Order.OrderType.DELIVERY,
                                status__in=[Order.Status.PENDING, Order.Status.OPEN]).first()


def render_pos(request, table, bill_now=False):
    """The POS screen for this table. bill_now: "New bill" on the Bills page
    (billing.views.bill_new), a counter sale whose Make bill button goes on to its bill."""
    form = waiter_form(table, initial={"bill": request.GET.get("bill", "")})
    add_order = growing_delivery(table, request.GET.get("add"))
    wanted = Order.OrderType.DELIVERY if add_order else request.GET.get("type")
    if wanted in dict(form.fields["order_type"].choices):
        form.initial["order_type"] = wanted
    categories = menu_with_cart(table.restaurant, read_cart(request, table))
    return render(request, "orders/waiter_order.html", {
        "table": table,
        "categories": categories,
        "dish_count": sum(len(category.menu_items) for category in categories),  # "All items 24"
        "cart": cart_details(request, table),
        "form": form,
        "order_type": form.initial.get("order_type") or form.default_type,  # one type per screen
        "is_delivery": form.initial.get("order_type") == Order.OrderType.DELIVERY,
        "bill_now": bill_now,
        "add_order": add_order,  # "Add items" to this delivery: no guest details to type
        **bill_choice(table),
    })


def wants_bill_now(request, table, data):
    """"New bill" mode: a counter sale billed straight after it is sent (cashier, admin, manager)."""
    return data.get("then") == "bill" and table.is_takeaway and request.user.staff.role in BILLING_ROLES


def waiter_form(table, *args, **kwargs):
    """The waiter's order form: Dine in / Take away at a table; Take away / Delivery at the counter."""
    counter = table.is_takeaway
    return WaiterOrderForm(*args, counter=counter, delivery=counter and table.restaurant.delivery_enabled, **kwargs)


def waiter_change_cart(request, table_id, item_id, step):
    """Add / remove one of a dish (or a portion of it) on the POS screen;
    send back the bill lines, the tile's − qty + (and count), and the total."""
    table = waiter_table(request, table_id)
    item, portion, warning = dish_and_portion(request, table.restaurant, item_id)
    if not warning:
        warning = change_qty(request, table, item, step, portion)
    else:
        item.cart_qty = 0
    sizes = list(item.portions.all())
    item.cart_total = item_cart_total(read_cart(request, table), item, sizes)
    response = render(request, "orders/_waiter_item_update.html", {
        "table": table, "item": item, "portion": portion, "qty": (portion or item).cart_qty,
        "has_sizes": bool(sizes), "cart": cart_details(request, table),
    })
    if warning:
        show_message(response, warning, "warning")
    return response


@require_POST
@role_required(*COUNTER_ROLES)
def waiter_cart_add(request, table_id, item_id):
    """HTMX: one more of this dish in the waiter's round."""
    return waiter_change_cart(request, table_id, item_id, step=1)


@require_POST
@role_required(*COUNTER_ROLES)
def waiter_cart_remove(request, table_id, item_id):
    """HTMX: one less of this dish in the waiter's round."""
    return waiter_change_cart(request, table_id, item_id, step=-1)


@require_POST
@role_required(*COUNTER_ROLES)
def waiter_order_place(request, table_id):
    """Send the waiter's round to the kitchen as a KOT, then open the table's (or parcel's) page.
    In "New bill" mode (then=bill) a take-away goes straight on to its bill instead."""
    table = waiter_table(request, table_id)
    cart = cart_details(request, table)
    form = waiter_form(table, request.POST)
    bill_now = wants_bill_now(request, table, request.POST)
    again = reverse("billing:bill_new") if bill_now else reverse("orders:waiter_order", args=[table.pk])
    if request.POST.get("order_type") == Order.OrderType.DELIVERY:
        again += "?type=DELIVERY"
    if request.POST.get("add_to"):
        again += f"&add={request.POST['add_to']}"

    if not cart["lines"]:
        messages.warning(request, "Add at least one dish first.")
        return redirect(again)
    if cart["dropped"]:
        keep_orderable_only(request, table, cart)
        messages.warning(request, "These just ran out and were taken off: " + ", ".join(cart["dropped"]) + ". Please check and send again.")
        return redirect(again)
    if request.POST.get("add_to"):
        return add_to_delivery(request, table, cart)
    if not form.is_valid():
        problems = [error for errors in form.errors.values() for error in errors]
        messages.error(request, " ".join(problems) or "Please check the guest's details.")
        return redirect(again)

    order_type = form.cleaned_data["order_type"]
    dine_in = order_type == Order.OrderType.DINE_IN
    join = order_to_join(table, form.cleaned_data["bill"]) if dine_in else None  # None: a new order / bill
    default_name = join.customer_name if join else (f"Guest at {table.name}" if dine_in else "Takeaway guest")
    try:
        # a delivery taken by staff (a call or a walk-in) goes straight to the kitchen
        kot = place_kot(
            table, cart["lines"], customer_name=form.cleaned_data["customer_name"] or default_name,
            customer_phone=form.cleaned_data["customer_phone"], customer_address=form.cleaned_data["customer_address"],
            note=form.cleaned_data["note"], source=Order.Source.WAITER, waiter=request.user.staff,
            order_type=order_type, add_to=join,
        )
    except OrderNotAllowed as problem:
        messages.error(request, f"{problem} Choose another bill, or a new one.")
        return redirect(again)

    clear_cart(request, table)
    if kot.order.is_delivery:
        messages.success(request, f"Delivery order #{kot.order.order_no} (KOT #{kot.kot_no}) sent to the kitchen.")
        return redirect("orders:deliveries")
    if kot.order.is_takeaway and bill_now:
        messages.success(request, f"Order #{kot.order.order_no} (KOT #{kot.kot_no}) sent to the kitchen. "
                                  "Check the bill, add a discount if any, and make it.")
        return redirect("billing:bill_create", order_id=kot.order.pk)
    if kot.order.is_takeaway:
        messages.success(request, f"Take-away order #{kot.order.order_no} (KOT #{kot.kot_no}) sent to the kitchen.")
        return redirect("orders:floor_order", order_id=kot.order.pk)
    messages.success(request, f"KOT #{kot.kot_no} sent to the kitchen for {table.label} "
                              f"(order #{kot.order.order_no}).")
    return redirect(reverse("orders:floor_table", args=[table.pk]) + f"?order={kot.order.pk}")


def add_to_delivery(request, table, cart):
    """"Add items" (the customer asks for more on the phone): the cart joins that delivery
    as one more round. Still to confirm: it waits with the rest; confirmed: to the kitchen."""
    order = growing_delivery(table, request.POST.get("add_to"))
    if order is None:
        messages.error(request, "That delivery was billed, delivered or cancelled meanwhile. Nothing was added.")
        return redirect("orders:deliveries")
    try:
        kot = place_kot(table, cart["lines"], customer_name=order.customer_name, note=request.POST.get("note", "").strip()[:200],
                        source=Order.Source.WAITER, waiter=request.user.staff,
                        order_type=Order.OrderType.DELIVERY, add_to=order)
    except OrderNotAllowed:
        messages.error(request, f"Delivery #{order.order_no} cannot take more dishes now. Nothing was added.")
        return redirect("orders:deliveries")
    clear_cart(request, table)
    if kot.order.is_pending:
        messages.success(request, f"Added to delivery #{order.order_no}. Confirm it when the customer agrees.")
    else:
        messages.success(request, f"Added to delivery #{order.order_no}: KOT #{kot.kot_no} sent to the kitchen.")
    return redirect("orders:deliveries")


# ================================================================ kitchen

KITCHEN_COLUMNS = [
    (KOT.Status.NEW, "New", "inbox"),
    (KOT.Status.PREPARING, "Preparing", "fire"),
    (KOT.Status.READY, "Ready", "bell"),
]


# the kitchen board's order: newest KOT on top (default) or oldest on top
KITCHEN_SORTS = {"new": ("-created_at", "-pk"), "old": ("created_at", "pk")}


def kitchen_sort(request):
    """"new" or "old": picked on the kitchen page (?sort=), then kept in the session,
    so the 5-second refresh and the status buttons keep it."""
    wanted = request.GET.get("sort")
    if wanted in KITCHEN_SORTS:
        request.session["kitchen_sort"] = wanted
    return request.session.get("kitchen_sort", "new")


def kitchen_context(request):
    """The three columns of the kitchen board, the latest KOT on top in each by
    default, or the oldest (tables, take-away parcels and deliveries alike)."""
    role = request.user.staff.role
    sort = kitchen_sort(request)
    kots = (
        KOT.objects.filter(location=get_user_location(request), status__in=[code for code, _, _ in KITCHEN_COLUMNS])
        .select_related("order__table").prefetch_related("items").order_by(*KITCHEN_SORTS[sort])
    )
    now = timezone.now()
    by_status = {code: [] for code, _, _ in KITCHEN_COLUMNS}
    for kot in kots:
        add_timing(kot, now)
        kot.actions = kot_actions(kot, role)
        by_status[kot.status].append(kot)

    columns = [
        {"status": code, "title": title, "icon": icon, "kots": by_status[code]}
        for code, title, icon in KITCHEN_COLUMNS
    ]
    return {
        "columns": columns,
        "sort": sort,
        "new_count": len(by_status[KOT.Status.NEW]),
        "late_count": sum(1 for kot in kots if getattr(kot, "is_late", False)),
        "can_print": role in roles.PRINT_KOT,
        "can_stock": role in roles.STOCK,  # the Stock button (a waiter sees the board, not the stock)
    }


@role_required(*KITCHEN_ROLES)
def kitchen(request):
    """Kitchen board: KOTs in New / Preparing / Ready. Refreshes every 5s; late KOTs show in red."""
    template = "orders/_kitchen_board.html" if is_htmx(request) else "orders/kitchen.html"
    return render(request, template, kitchen_context(request))


@role_required(*roles.STOCK)
def kitchen_stock(request):
    """Side panel on the kitchen board: switch dishes in or out of stock."""
    items = MenuItem.objects.filter(is_active=True).order_by("sort_order", "name")
    categories = Category.objects.filter(restaurant=get_user_restaurant(request), is_active=True).prefetch_related(
        Prefetch("items", queryset=items, to_attr="menu_items")
    )
    return render(request, "orders/_kitchen_stock.html", {
        "categories": [category for category in categories if category.menu_items],
    })


# ================================================================ KOT status + waiter ready list

def ready_context(request):
    """READY KOTs of this location, the longest-waiting first. Deliveries are left
    out: the rider collects them (Deliveries board)."""
    kots = list(
        KOT.objects.filter(location=get_user_location(request), status=KOT.Status.READY)
        .exclude(order__order_type=Order.OrderType.DELIVERY)
        .select_related("order__table").prefetch_related("items").order_by("ready_at", "created_at")
    )
    now = timezone.now()
    for kot in kots:
        add_timing(kot, now)
    return {"kots": kots}


@role_required(*roles.READY_LIST)
def waiter_ready(request):
    """Waiter: food that is ready to take to the tables, with Mark served. Refreshes every 10s."""
    template = "orders/_ready_list.html" if is_htmx(request) else "orders/waiter_ready.html"
    return render(request, template, ready_context(request))


@require_POST
@role_required(*set(roles.COOK + roles.SERVE + roles.CANCEL))
def kot_status(request, kot_id, status):
    """HTMX: move a KOT to its next status, then redraw the screen the button was on.

    The form sends screen=kitchen | ready | table. When someone else has already
    moved the KOT, nothing changes and the fresh screen says so.
    """
    if status not in KOT.Status.values:
        return HttpResponseBadRequest("Unknown status.")
    staff = request.user.staff
    kot = get_object_or_404(KOT.objects.select_related("order__table"), pk=kot_id, location=get_user_location(request))

    if can_move_kot(kot, status, staff.role):
        move_kot(kot, status, staff)
        text, level = f"KOT #{kot.kot_no} {MOVED_TEXT[status]}.", "success"
    else:
        text, level = f"KOT #{kot.kot_no} is already {kot.get_status_display().lower()}. The screen is up to date now.", "warning"

    screen = request.POST.get("screen")
    if screen == "kitchen":
        response = render(request, "orders/_kitchen_board.html", kitchen_context(request))
    elif screen == "ready":
        response = render(request, "orders/_ready_list.html", ready_context(request))
    else:
        response = render(request, "orders/_table_order.html", table_order_context(request, kot.order.table, order=kot.order))
    return show_message(response, text, level)


def get_kot_to_print(request, kot_id):
    """This location's KOT, and which round of its order it is (1, 2, ...)."""
    kot = get_object_or_404(
        KOT.objects.select_related("order__table", "order__waiter", "restaurant"),
        pk=kot_id, location=get_user_location(request),
    )
    round_no = kot.order.kots.filter(created_at__lte=kot.created_at).count()
    return kot, round_no


@role_required(*roles.PRINT_KOT)
def kot_print(request, kot_id):
    """The 80 mm KOT slip: table, time, dishes and quantities, the note. No prices. Prints on open."""
    kot, round_no = get_kot_to_print(request, kot_id)
    return render(request, "print/kot.html", {
        "kot": kot,
        "restaurant": kot.restaurant,
        "items": kot.items.filter(is_cancelled=False),
        "round_no": round_no,
    })


@role_required(*roles.PRINT_KOT)
def kot_print_slip(request, kot_id):
    """The same KOT as printer bytes (ESC/POS), for the print helper's direct print (static/js/printing.js)."""
    kot, round_no = get_kot_to_print(request, kot_id)
    return HttpResponse(kot_slip(kot, round_no), content_type="application/octet-stream")
