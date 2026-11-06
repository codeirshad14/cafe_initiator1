"""
Order logic shared by the guest (QR) screens, the staff screens and the kitchen.

The life of an order, in short:

    place_kot()       a round of dishes -> a KOT for the kitchen, on a new or a running order
    move_kot()        the kitchen: New -> Preparing -> Ready; the waiter: Ready -> Served
    (billing app)     make_bill() -> BILLED, add_payment() -> CLOSED
    cancel_order()    cancelled with a reason

Which order a dine-in round goes on is decided by order_to_join(): people
at one table share one order (one bill), unless someone picks "My own bill".
"""

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from core import roles
from core.models import Restaurant
from core.utils import next_number
from tables.models import takeaway_table

from .models import KOT, KOTItem, Notification, Order

PARCEL_TYPES = (Order.OrderType.TAKEAWAY, Order.OrderType.DELIVERY)


class OrderNotAllowed(Exception):
    """The order cannot take a new round right now (its bill was made a moment ago)."""


class DeliveryError(Exception):
    """A delivery step that is not allowed right now; the message says why, for the screen."""


# ---------------------------------------------------------------- which order

def running_orders(table):
    """The dining table's dine-in orders still going on (OPEN or BILLED), oldest first.

    Usually none (free) or one. More than one when people at the table pay
    separately. The counter (Takeaway) table has none: its parcels are listed apart.
    """
    if table.is_takeaway:
        return Order.objects.none()
    return Order.objects.filter(
        table=table, status__in=Order.RUNNING, order_type=Order.OrderType.DINE_IN,
    ).order_by("created_at")


def joinable_orders(table, my_order=None, guest=False):
    """The open orders a round at this table may go on. The Common table seats strangers:
    a guest sees (and adds to) only their own order there; staff see them all."""
    open_orders = running_orders(table).filter(status=Order.Status.OPEN)
    if table.is_common and guest:
        return open_orders.filter(pk=my_order.pk) if my_order else open_orders.none()
    return open_orders


def order_to_join(table, choice="", my_order=None, guest=False):
    """The OPEN order a new dine-in round is added to, or None to start a new order (its own bill).

    choice  "new"      -> None: a new order, a separate bill
            "12"       -> the open order with id 12 on this table (None if it was billed meanwhile)
            ""         -> this phone's own order if it is still open, else the table's oldest
                          open order (friends at one table share a bill), else None.
                          At the Common table never someone else's: a new order then.
    guest   True for the guest's own screens (the Common table: only their own order)
    """
    if table.is_takeaway or choice == "new":
        return None
    open_orders = joinable_orders(table, my_order, guest)
    if choice:
        return open_orders.filter(pk=choice).first() if str(choice).isdigit() else None
    if my_order is not None and open_orders.filter(pk=my_order.pk).exists():
        return my_order
    return None if table.is_common else open_orders.first()


def bill_choice(table, my_order=None, guest=False):
    """What the "Which bill?" choice needs (orders/_bill_choice.html, cart and waiter
    screens): the table's open orders and the one picked when nobody chooses."""
    return {
        "open_orders": list(joinable_orders(table, my_order, guest)),
        "default_order": order_to_join(table, "", my_order, guest),
        "my_order": my_order,
    }


def running_takeaway_orders(location):
    """The location's take-away orders still waiting to be paid or picked up, oldest first."""
    return Order.objects.filter(
        location=location, order_type=Order.OrderType.TAKEAWAY, status__in=Order.RUNNING,
    ).order_by("created_at")


def place_kot(table, lines, customer_name, customer_phone="", note="", source=Order.Source.QR, waiter=None,
              order_type=Order.OrderType.DINE_IN, customer_address="", to_confirm=False, add_to=None):
    """Send one round of dishes to the kitchen. Returns the new KOT.

    lines   [{"item": MenuItem, "qty": 2}, ...]; a portion line also brings "name" and "rate"
    add_to  dine in: the running order this round joins (see order_to_join), or None for a
            new order. Take away / delivery are a new order of their own, on the
            location's counter (Takeaway) table, whichever table they were ordered from;
            except a delivery that grows on the phone ("Add items" while it is to
            confirm or cooking): add_to is that delivery, and a round still to
            confirm stays HELD with it.
    to_confirm  a delivery from the public menu: the order is PENDING and its KOT HELD,
            out of the kitchen, until staff confirm it (delivery.confirm_delivery).

    The order and its KOT belong to the table's location and take that location's
    next numbers. The dish name and price are copied onto the KOT, so later menu
    changes do not alter it. A new order also rings the bell in the top bar (Notification).
    """
    restaurant, location = table.restaurant, table.location
    if table.is_takeaway and order_type not in PARCEL_TYPES:
        order_type = Order.OrderType.TAKEAWAY  # the counter table only takes parcels
    if order_type in PARCEL_TYPES:
        table = takeaway_table(restaurant, location)
        if add_to is not None and not (order_type == Order.OrderType.DELIVERY and add_to.is_delivery):
            add_to = None  # a parcel is its own order; only a delivery grows on the phone
    to_confirm = to_confirm and order_type == Order.OrderType.DELIVERY

    with transaction.atomic():
        # Lock the restaurant row so two guests ordering at the same moment are
        # handled one after the other (no duplicate numbers).
        Restaurant.objects.select_for_update().get(pk=restaurant.pk)

        order, new_order = None, False
        if add_to is not None:
            order = Order.objects.select_for_update().get(pk=add_to.pk)
            growing = [Order.Status.OPEN, Order.Status.PENDING] if order.is_delivery else [Order.Status.OPEN]
            if order.table_id != table.pk or order.status not in growing:
                raise OrderNotAllowed(f"Order #{order.order_no} is {order.get_status_display().lower()}, "
                                      f"so it cannot take new rounds.")
            if waiter is not None and order.waiter_id is None:
                # a QR order a waiter now adds to: the table is theirs (waiter-wise report)
                order.waiter = waiter
                order.save(update_fields=["waiter"])

        if order is None:
            order = Order.objects.create(
                restaurant=restaurant,
                location=location,
                table=table,
                order_no=next_number(Order, location, "order_no"),
                customer_name=customer_name,
                customer_phone=customer_phone,
                customer_address=customer_address,
                source=source,
                waiter=waiter,
                order_type=order_type,
                status=Order.Status.PENDING if to_confirm else Order.Status.OPEN,
            )
            new_order = True

        kot = KOT.objects.create(
            restaurant=restaurant,
            location=location,
            order=order,
            kot_no=next_number(KOT, location, "kot_no"),
            note=note,
            # a delivery still to confirm keeps its new round out of the kitchen too
            status=KOT.Status.HELD if to_confirm or order.status == Order.Status.PENDING else KOT.Status.NEW,
        )
        # a portion line brings its own name ("Butter Chicken (Half)") and price
        KOTItem.objects.bulk_create([
            KOTItem(
                kot=kot,
                menu_item=line["item"],
                item_name=line.get("name") or line["item"].name,
                rate=line.get("rate", line["item"].price),
                qty=line["qty"],
                amount=line.get("rate", line["item"].price) * line["qty"],
            )
            for line in lines
        ])
        if new_order:  # "New order" in everyone's bell at this location (top bar)
            Notification.objects.create(restaurant=restaurant, location=location, order=order)
    return kot


# ---------------------------------------------------------------- KOT status

# Which role may move a KOT from one status to the next.
# (from, to): (button label, roles)
KOT_MOVES = {
    (KOT.Status.NEW, KOT.Status.PREPARING): ("Start cooking", roles.COOK),
    (KOT.Status.PREPARING, KOT.Status.READY): ("Mark ready", roles.COOK),
    (KOT.Status.READY, KOT.Status.SERVED): ("Mark served", roles.SERVE),
    (KOT.Status.NEW, KOT.Status.CANCELLED): ("Cancel KOT", roles.CANCEL),
    (KOT.Status.PREPARING, KOT.Status.CANCELLED): ("Cancel KOT", roles.CANCEL),
}

LATE_MINUTES = 15  # a KOT still not ready after this long shows in red


def kot_actions(kot, role):
    """The status buttons this role gets for this KOT: [{"status", "label"}]."""
    return [
        {"status": to_status, "label": label}
        for (from_status, to_status), (label, roles) in KOT_MOVES.items()
        if from_status == kot.status and role in roles
    ]


def can_move_kot(kot, new_status, role):
    """True when this role may move the KOT to new_status from where it is now."""
    move = KOT_MOVES.get((kot.status, new_status))
    return move is not None and role in move[1]


def move_kot(kot, new_status, staff):
    """Save the KOT's new status and the time it happened (ready_at, served_at)."""
    kot.status = new_status
    fields = ["status"]
    if new_status == KOT.Status.READY:
        kot.ready_at = timezone.now()
        fields.append("ready_at")
    elif new_status == KOT.Status.SERVED:
        kot.served_at = timezone.now()
        kot.served_by = staff
        fields += ["served_at", "served_by"]
    kot.save(update_fields=fields)


def add_timing(kot, now=None):
    """Put kot.age_min (minutes since it was placed) and kot.is_late on the KOT, for the screens."""
    now = now or timezone.now()
    kot.age_min = int((now - kot.created_at).total_seconds() // 60)
    kot.is_late = kot.status in (KOT.Status.NEW, KOT.Status.PREPARING) and kot.age_min >= LATE_MINUTES
    kot.ready_min = int((now - kot.ready_at).total_seconds() // 60) if kot.ready_at else None
    return kot


def cancel_order(order, reason):
    """Cancel a running (or still-to-confirm) order: the table is free again, and
    its unfinished KOTs leave the kitchen."""
    with transaction.atomic():
        order.status = Order.Status.CANCELLED
        order.cancel_reason = reason
        order.closed_at = timezone.now()
        order.save(update_fields=["status", "cancel_reason", "closed_at"])
        order.kots.filter(
            status__in=[KOT.Status.HELD, KOT.Status.NEW, KOT.Status.PREPARING, KOT.Status.READY]
        ).update(status=KOT.Status.CANCELLED)


# ---------------------------------------------------------------- tracking

KOT_STEPS = [
    (KOT.Status.NEW, "Placed"),
    (KOT.Status.PREPARING, "Preparing"),
    (KOT.Status.READY, "Ready"),
    (KOT.Status.SERVED, "Served"),
]


def kot_steps(kot):
    """The progress line for one KOT: [{"label", "done", "current"}, ...]."""
    codes = [code for code, label in KOT_STEPS]
    reached = codes.index(kot.status) if kot.status in codes else -1
    return [
        {"label": label, "done": index <= reached, "current": index == reached}
        for index, (code, label) in enumerate(KOT_STEPS)
    ]


def order_headline(order, kots):
    """One friendly sentence about where the order stands, plus an icon name."""
    if order.status == Order.Status.CANCELLED:
        return "This order was cancelled.", "x-circle"
    if order.is_delivery:
        return delivery_headline(order, kots)
    if order.status == Order.Status.CLOSED:
        return "Paid. Thank you for dining with us!", "heart"
    if order.status == Order.Status.BILLED:
        return "Your bill is ready. Please pay at the counter or ask your waiter.", "receipt"

    live = [kot for kot in kots if kot.status != KOT.Status.CANCELLED]
    if any(kot.status in (KOT.Status.NEW, KOT.Status.PREPARING) for kot in live):
        return "The kitchen is preparing your food.", "fire"
    if order.is_takeaway:
        if any(kot.status == KOT.Status.READY for kot in live):
            return "Your parcel is ready. Please collect it at the counter.", "bag-check"
        return "Your parcel has been handed over. Enjoy your meal!", "emoji-smile"
    if any(kot.status == KOT.Status.READY for kot in live):
        return "Your food is ready and on its way to your table.", "bell"
    return "Everything is served. Enjoy your meal!", "emoji-smile"


def delivery_steps(order, kots):
    """The delivery's progress line for the customer: Placed, Confirmed, Cooking, On the way, Delivered."""
    live = [kot for kot in kots if kot.status != KOT.Status.CANCELLED]
    cooked = bool(live) and all(kot.status in (KOT.Status.READY, KOT.Status.SERVED) for kot in live)
    reached = [True, not order.is_pending, cooked, bool(order.picked_up_at), bool(order.delivered_at)]
    labels = ["Placed", "Confirmed", "Cooking", "On the way", "Delivered"]
    last = max(index for index, done in enumerate(reached) if done)
    return [{"label": label, "done": index <= last, "current": index == last} for index, label in enumerate(labels)]


def delivery_headline(order, kots):
    """Where a delivery order stands, for the customer's status page."""
    if order.is_pending:
        return "We have your delivery order. The restaurant will call you shortly to confirm it.", "telephone"
    if order.delivered_at:
        return "Delivered. Enjoy your meal!", "emoji-smile"
    if order.picked_up_at:
        return "Your order is on the way.", "bicycle"
    live = [kot for kot in kots if kot.status != KOT.Status.CANCELLED]
    if any(kot.status in (KOT.Status.NEW, KOT.Status.PREPARING) for kot in live):
        return "Confirmed. The kitchen is preparing your food.", "fire"
    return "Your food is packed and waiting for the rider.", "bag-check"


def order_total(kots):
    """Value of everything ordered so far (cancelled items and KOTs left out), before GST."""
    total = Decimal("0.00")
    for kot in kots:
        if kot.status == KOT.Status.CANCELLED:
            continue
        for item in kot.items.all():
            if not item.is_cancelled:
                total += item.amount
    return total
