"""
Home delivery steps, shared by the staff Deliveries screen and the rider's screen.
Each runs inside transaction.atomic() with the order row locked, so two people
pressing at the same moment cannot do a step twice.

    confirm_delivery  a PENDING order (from the public menu) -> OPEN: its KOT goes
                      to the kitchen, the kitchen timer starting now
    assign_rider      choose (or change) the rider
    pick_up           the rider leaves with it. The bill must be made first, so the
                      amount to collect is known, and the kitchen must be done.
    deliver           handed over; the rider records the payment taken for what is
                      still due (any mode, or split in two), which settles the bill

The ride (Order.ride_minutes) is the time from picked up to delivered;
ride_times() sums them up per rider for the screens.
"""

from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone

from billing.models import Bill, Payment
from billing.services import BillingError, add_payments
from core import roles
from core.templatetags.money import inr
from core.models import Staff

from .models import KOT, Order
from .services import DeliveryError

RIDER_PAYMENT_MODES = Payment.Mode.values  # every mode, as on the Bills page


def locked_delivery(order):
    """The delivery order again from the database, locked for this transaction."""
    return Order.objects.select_for_update().get(pk=order.pk, order_type=Order.OrderType.DELIVERY)


def check_running(order):
    if order.status == Order.Status.CANCELLED:
        raise DeliveryError(f"Order #{order.order_no} was cancelled.")
    if order.delivered_at:
        raise DeliveryError(f"Order #{order.order_no} is already delivered.")


def confirm_delivery(order):
    """The customer was called and the order is real: send it to the kitchen."""
    with transaction.atomic():
        order = locked_delivery(order)
        if order.status != Order.Status.PENDING:
            raise DeliveryError(f"Order #{order.order_no} is already {order.get_status_display().lower()}.")
        order.status = Order.Status.OPEN
        order.save(update_fields=["status"])
        order.kots.filter(status=KOT.Status.HELD).update(status=KOT.Status.NEW, created_at=timezone.now())
    return order


def riders_of(location):
    """Who can take deliveries from this location, by name: riders (and all-rounders)
    who can log in and work here."""
    people = Staff.objects.filter(restaurant=location.restaurant, role__in=roles.RIDING, is_active=True,
                                  user__is_active=True)
    return [person for person in people if location in person.allowed_locations()]


def assign_rider(order, rider):
    """Give the delivery to this rider (or to another one, before it leaves)."""
    with transaction.atomic():
        order = locked_delivery(order)
        check_running(order)
        if order.picked_up_at:
            raise DeliveryError(f"Order #{order.order_no} has already left with {order.rider.name}.")
        if rider.restaurant_id != order.restaurant_id or rider.role not in roles.RIDING or not rider.is_active:
            raise DeliveryError("Choose one of your riders.")
        order.rider = rider
        order.save(update_fields=["rider"])
    return order


def pick_up(order, staff):
    """The rider leaves with the parcel. The food handed over counts as served."""
    with transaction.atomic():
        order = locked_delivery(order)
        check_running(order)
        if order.picked_up_at:
            raise DeliveryError(f"Order #{order.order_no} has already left.")
        if order.rider_id is None:
            raise DeliveryError("Choose a rider first.")
        if order.status not in (Order.Status.BILLED, Order.Status.CLOSED):
            raise DeliveryError("Make the bill first, so the rider knows how much to collect.")
        if order.kots.filter(status__in=[KOT.Status.HELD, KOT.Status.NEW, KOT.Status.PREPARING]).exists():
            raise DeliveryError("The kitchen is still preparing this order.")
        now = timezone.now()
        order.picked_up_at = now
        order.save(update_fields=["picked_up_at"])
        order.kots.filter(status=KOT.Status.READY).update(status=KOT.Status.SERVED, served_at=now, served_by=staff)
    return order


def deliver(order, staff, mode=Payment.Mode.CASH, reference="", first_amount=None, second_mode=None):
    """Handed to the customer. What is still due on the bill is recorded as taken
    by the rider, which settles the bill and closes the order.

    Any payment mode, like the Bills page (cash, card, UPI, online), with an
    optional reference (UPI ref, card last 4). Split in two modes: first_amount
    by `mode`, the rest by second_mode (e.g. ₹200 cash, the rest UPI).
    """
    if mode not in RIDER_PAYMENT_MODES or (second_mode and second_mode not in RIDER_PAYMENT_MODES):
        raise DeliveryError("Choose how the customer paid.")
    with transaction.atomic():
        order = locked_delivery(order)
        check_running(order)
        if not order.picked_up_at:
            raise DeliveryError("Mark it picked up first.")
        bill = Bill.objects.filter(order=order).exclude(status=Bill.Status.CANCELLED).first()
        if bill is None:
            raise DeliveryError("This order has no bill.")
        due = bill.balance
        if due > 0:
            note = reference.strip()[:50] or "Collected on delivery"
            if second_mode and first_amount:
                if not 0 < first_amount < due:
                    raise DeliveryError(f"For a split, the first amount must be less than {inr(due)}.")
                if second_mode == mode:
                    raise DeliveryError("A split needs two different modes.")
                rows = [(mode, first_amount, note), (second_mode, due - first_amount, "Collected on delivery")]
            else:
                rows = [(mode, due, note)]
            try:
                add_payments(bill, rows, staff)
            except BillingError as problem:
                raise DeliveryError(str(problem)) from problem
        order.delivered_at = timezone.now()
        order.save(update_fields=["delivered_at"])
    return order


def amount_to_collect(order):
    """What the rider still has to take from the customer (None before the bill is made)."""
    bill = getattr(order, "bill_cached", None) or Bill.objects.filter(order=order).exclude(status=Bill.Status.CANCELLED).first()
    return bill.balance if bill else None


def ride_times(orders):
    """How long the rides took, from delivered orders: the whole list together, and
    each rider's: {"count", "average", "fastest", "slowest"} in minutes (None when none)."""
    def summary(minutes):
        if not minutes:
            return {"count": 0, "average": None, "fastest": None, "slowest": None}
        return {"count": len(minutes), "average": round(sum(minutes) / len(minutes)),
                "fastest": min(minutes), "slowest": max(minutes)}

    rides = [order for order in orders if order.delivered_at and order.picked_up_at]
    by_rider = {}
    for order in rides:
        if order.rider_id:
            by_rider.setdefault(order.rider_id, (order.rider, []))[1].append(order.ride_minutes)
    riders = [{"rider": rider, **summary(minutes)} for rider, minutes in by_rider.values()]
    riders.sort(key=lambda row: row["average"])  # quickest first
    return {"all": summary([order.ride_minutes for order in rides]), "riders": riders}


def rider_cash_today(location):
    """Cash taken at this location's doors by each rider today, to hand over at the
    counter: [{"rider", "amount", "count"}]."""
    rows = (
        Payment.objects.filter(
            location=location, mode=Payment.Mode.CASH, created_at__date=timezone.localdate(),
            received_by__role__in=roles.RIDING,
        )
        .values("received_by").annotate(amount=Sum("amount"), count=Count("pk")).order_by("-amount")
    )
    riders = {rider.pk: rider for rider in Staff.objects.filter(pk__in=[row["received_by"] for row in rows])}
    return [{"rider": riders[row["received_by"]], "amount": row["amount"], "count": row["count"]} for row in rows]
