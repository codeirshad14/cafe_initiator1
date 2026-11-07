"""
Billing steps. Each runs inside transaction.atomic() and locks the rows it
changes, so two cashiers pressing at the same moment cannot double-bill or
double-pay.

    make_bill      OPEN order  -> bill made, order BILLED (table shows "bill printed").
                   "Bill together": other open dine-in orders of the location (the same
                   people's second order at the table, a big family's other table) go on
                   the same bill; each keeps its table and KOTs, all are BILLED
    add_payment    one payment row; when the payments cover the total: bill PAID,
                   its orders CLOSED, their tables free
    add_payments   two (or more) rows at once: a split payment, e.g. cash + UPI
    remove_payment undo a payment typed by mistake (bill not fully paid yet)
    reopen_order   unpaid bill, guests want more: order back to OPEN (orders billed with
                   it too, each on its own again); the next "Generate bill" redoes this
                   same bill (same number)
    cancel_bill    void an unpaid bill and its order (orders billed with it go back to
                   open, to be billed again)
"""

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from core.models import Restaurant
from core.templatetags.money import inr
from core.utils import next_number
from orders.models import KOT, KOTItem, Order
from orders.services import cancel_order

from .calc import ZERO, bill_totals, discount_amount_for
from .models import Bill, BillItem, Offer, Payment


class BillingError(Exception):
    """A billing step that is not allowed right now; the message says why, for the screen."""


def billable_lines(order, joined=()):
    """The order's dishes (and those of the orders billed together with it) as bill lines:
    the same dish (and portion) at the same rate across rounds is one line.

    Cancelled dishes and cancelled KOTs are left out. A dish whose price changed
    between rounds stays on two lines, each with its own rate; so do its
    portions ("Butter Chicken (Half)" and "(Full)").
    """
    kot_items = (
        KOTItem.objects.filter(kot__order__in=[order.pk, *[other.pk for other in joined]], is_cancelled=False)
        .exclude(kot__status=KOT.Status.CANCELLED)
        .select_related("menu_item__category")
        .order_by("kot__created_at", "pk")
    )
    lines = {}
    for kot_item in kot_items:
        key = (kot_item.menu_item_id, kot_item.item_name, kot_item.rate)
        if key not in lines:
            lines[key] = {
                "menu_item": kot_item.menu_item,
                "item_name": kot_item.item_name,
                "category_name": kot_item.menu_item.category.name,
                "rate": kot_item.rate,
                "qty": 0,
                "amount": ZERO,
            }
        lines[key]["qty"] += kot_item.qty
        lines[key]["amount"] += kot_item.amount
    return list(lines.values())


def offer_for(restaurant, day, subtotal):
    """The festival offer for a bill of `subtotal` made on `day`: of the switched-on
    offers running that day whose minimum the bill reaches, the one giving the
    most off. None when there is none."""
    offers = Offer.objects.filter(restaurant=restaurant, is_active=True, start_date__lte=day, end_date__gte=day,
                                  min_bill__lte=subtotal)
    return max(offers, key=lambda offer: discount_amount_for(subtotal, offer.kind, offer.value), default=None)


def joinable_orders(order):
    """The open orders that may go on this order's bill ("Bill together"): dine-in orders of
    the same location without a bill of their own, this table's first, then by table.
    A parcel (take away, delivery) is billed on its own."""
    if order.order_type != Order.OrderType.DINE_IN:
        return Order.objects.none()
    return (Order.objects.filter(location=order.location, status=Order.Status.OPEN,
                                 order_type=Order.OrderType.DINE_IN, bill__isnull=True, joined_bill__isnull=True)
            .exclude(pk=order.pk).select_related("table")
            .order_by("table__name", "created_at"))


def preview_totals(order, discount_type, discount_value, joined=()):
    """Lines and totals as they would be billed, without saving anything (for the preview).
    joined: the orders billed together with this one."""
    lines = billable_lines(order, joined)
    subtotal = sum((line["amount"] for line in lines), ZERO)
    discount = discount_amount_for(subtotal, discount_type, discount_value)
    # delivery: the restaurant's charge, free from its free-delivery amount (after discount)
    delivery = order.restaurant.delivery_charge_for(subtotal - discount) if order.is_delivery and lines else ZERO
    return lines, bill_totals(subtotal, discount, order.restaurant.gst_percent, delivery)


def make_bill(order, staff, discount_type="AMOUNT", discount_value=0, offer_name="", join=()):
    """Bill an OPEN order. Returns the bill. A reopened order gets its own unpaid bill redone.
    offer_name: the festival offer the discount comes from (printed next to it).
    join: other open orders to bill together on this one bill (see joinable_orders)."""
    with transaction.atomic():
        restaurant = Restaurant.objects.select_for_update().get(pk=order.restaurant_id)
        order = Order.objects.select_for_update().get(pk=order.pk)
        if order.status != Order.Status.OPEN:
            raise BillingError(f"Order #{order.order_no} is {order.get_status_display().lower()}, so it cannot be billed.")

        wanted = {other.pk for other in join}
        joined = list(joinable_orders(order).select_for_update(of=("self",)).filter(pk__in=wanted))
        if len(joined) != len(wanted):
            raise BillingError("One of the orders to bill together was billed or changed a moment ago. Please pick again.")

        lines, totals = preview_totals(order, discount_type, discount_value, joined)
        if not lines:
            raise BillingError("This order has nothing to bill. Cancel the order instead.")

        bill = Bill.objects.filter(order=order).first()
        if bill is None:
            # the plan's bills for this membership year (core/plans.py); redoing a bill is not a new one
            if not restaurant.can_make_bill():
                raise BillingError(restaurant.bill_limit_message())
            bill = Bill(restaurant=restaurant, location=order.location, order=order,
                        bill_no=next_number(Bill, order.location, "bill_no"))
        elif bill.status != Bill.Status.UNPAID or bill.payments.exists():
            raise BillingError(f"Bill #{bill.bill_no} already has payments, so it cannot be redone.")

        for field, value in totals.items():
            if field != "half_percent":
                setattr(bill, field, value)
        bill.offer_name = offer_name if totals["discount_amount"] else ""
        bill.paid_amount = ZERO
        bill.status = Bill.Status.UNPAID
        bill.created_by = staff
        bill.save()

        bill.items.all().delete()  # a redo replaces the old lines
        BillItem.objects.bulk_create([
            BillItem(
                bill=bill, menu_item=line["menu_item"], item_name=line["item_name"],
                category_name=line["category_name"], rate=line["rate"], qty=line["qty"], amount=line["amount"],
            )
            for line in lines
        ])

        order.status = Order.Status.BILLED
        order.save(update_fields=["status"])
        for other in joined:  # billed together: each keeps its table, all wait for this bill
            other.status, other.joined_bill = Order.Status.BILLED, bill
            other.save(update_fields=["status", "joined_bill"])

        if bill.grand_total == ZERO:  # a 100% discount: nothing to collect
            settle(bill)
    return bill


def release_joined(bill):
    """The orders billed together on this bill go back to open, each on its own again."""
    for other in bill.joined_orders.all():
        other.status, other.joined_bill = Order.Status.OPEN, None
        other.save(update_fields=["status", "joined_bill"])


def settle(bill):
    """Recount what is paid from the payment rows and set the status.

    Fully paid: bill PAID, its order (and the orders billed together on it) CLOSED,
    their tables free. Call inside transaction.atomic() with the bill row locked.
    """
    bill.paid_amount = bill.payments.aggregate(total=Sum("amount"))["total"] or ZERO
    if bill.paid_amount >= bill.grand_total:
        bill.status = Bill.Status.PAID
        now = timezone.now()
        for order in [bill.order, *bill.joined_orders.all()]:
            order.status = Order.Status.CLOSED
            order.closed_at = now
            order.save(update_fields=["status", "closed_at"])
    elif bill.paid_amount > ZERO:
        bill.status = Bill.Status.PARTIAL
    else:
        bill.status = Bill.Status.UNPAID
    bill.save(update_fields=["paid_amount", "status"])


def locked_bill(bill):
    """The bill again from the database, locked for this transaction."""
    return Bill.objects.select_for_update().select_related("order").get(pk=bill.pk)


def add_payment(bill, mode, amount, reference_no, staff):
    """Record one payment (cash, card, UPI ...). Returns the updated bill."""
    return add_payments(bill, [(mode, amount, reference_no)], staff)


def add_payments(bill, rows, staff):
    """Record one or more payments together, e.g. a split bill paid part cash, part UPI.

    rows: [(mode, amount, reference_no), ...]. All are saved, or none (when
    together they are more than the balance). Returns the updated bill.
    """
    with transaction.atomic():
        bill = locked_bill(bill)
        if not bill.is_open_for_payment:
            raise BillingError(f"Bill #{bill.bill_no} is {bill.get_status_display().lower()}.")
        if bill.order.status != Order.Status.BILLED:
            raise BillingError("The order was reopened. Generate the bill again before taking payment.")
        if any(amount <= ZERO for _, amount, _ in rows):
            raise BillingError("Enter an amount above zero.")
        if sum(amount for _, amount, _ in rows) > bill.balance:
            raise BillingError(f"That is more than the balance of {inr(bill.balance)}.")

        for mode, amount, reference_no in rows:
            Payment.objects.create(
                restaurant=bill.restaurant, bill=bill, mode=mode, amount=amount,
                reference_no=reference_no, received_by=staff,
            )
        settle(bill)
    return bill


def remove_payment(payment):
    """Take back a payment typed by mistake. Not once the bill is fully paid."""
    with transaction.atomic():
        bill = locked_bill(payment.bill)
        if not bill.is_open_for_payment:
            raise BillingError(f"Bill #{bill.bill_no} is {bill.get_status_display().lower()}; its payments are final.")
        payment.delete()
        settle(bill)
    return bill


def reopen_order(bill):
    """Guests want more after the bill was made: the order takes new rounds again."""
    with transaction.atomic():
        bill = locked_bill(bill)
        if bill.status != Bill.Status.UNPAID or bill.payments.exists():
            raise BillingError("Only an unpaid bill with no payments can be reopened.")
        if bill.order.status != Order.Status.BILLED:
            raise BillingError("The order is already open.")
        bill.order.status = Order.Status.OPEN
        bill.order.save(update_fields=["status"])
        release_joined(bill)  # ticked again when the bill is generated again
    return bill


def cancel_bill(bill, reason):
    """Void an unpaid bill: the bill and its order are cancelled, and the table is free."""
    with transaction.atomic():
        bill = locked_bill(bill)
        if bill.status == Bill.Status.CANCELLED:
            raise BillingError("This bill is already cancelled.")
        if bill.payments.exists():
            raise BillingError("This bill has payments. Remove them first, then cancel.")
        bill.status = Bill.Status.CANCELLED
        bill.cancel_reason = reason
        bill.save(update_fields=["status", "cancel_reason"])
        cancel_order(bill.order, reason)
        release_joined(bill)  # their food is still to be paid: back to open, billed again
    return bill
