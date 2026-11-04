"""
What every report is made of.

A report is a plain function of the location and the period:

    def daily_sales(location, start, end):
        return [section(...), ...]

A section is one table: {"title", "columns", "rows", "totals", "links"}.
  columns  [(label, kind)]; kind says how a value is shown and exported:
           text, int, money, percent, date, datetime, minutes
  rows     a list of lists, one value per column
  totals   one value per column ("" where nothing adds up), or None
  links    one per row: where a click on the row goes, like Tally's drill down
           (to_report / to_bills / to_bill), or None

Drill down: a summary row opens the list behind it, the list's row opens the
bill. Order types "Dine in" -> the bill register of dine-in bills -> Bill #212.
A report that is opened narrowed takes the narrowing as keyword arguments
(catalog FILTERS says which), e.g. bill_register(location, start, end, type="DINE_IN").

Only the Django ORM (annotate / aggregate). No raw SQL, no pandas.
"""

import re
from decimal import Decimal

from billing.models import Bill, BillItem, Payment
from core.models import Staff
from menu.models import MenuItem
from orders.models import Order

ZERO = Decimal("0.00")
NUMERIC = ("int", "money", "percent", "minutes")
NONE = "none"  # a filter for "nobody": no waiter (the guests' QR orders), a discount by hand


def section(columns, rows, totals=None, title="", links=None):
    """One table of a report. The totals row is left out when there are no rows."""
    return {"title": title, "columns": columns, "rows": rows, "totals": totals if rows else None,
            "links": links or [None] * len(rows)}


# ================================================================ drill down

def to_report(slug, period=None, **filters):
    """A row's click: another report narrowed to this row (filters), for the same period,
    or for `period` (start, end) when the row is one day or one month."""
    return {"report": slug, "period": period, "filters": {key: str(value) for key, value in filters.items()}}


def to_bills(period=None, **filters):
    """A row's click: its bills in the bill register (only sales bills, as the row counted)."""
    return to_report("bill-register", period, live=1, **filters)


def to_bill(bill_id):
    """A row's click: the bill itself (None when there is no bill yet)."""
    return {"bill": bill_id} if bill_id else None


def bill_id_of(order):
    """The order's bill's id, or None when it has none."""
    bill = getattr(order, "bill", None)
    return bill.pk if bill else None


def whole(value):
    """A filter's number ("12" -> 12); -1 for anything else, which matches nothing."""
    return int(value) if str(value).isdigit() else -1


def hour_label(hour):
    """13 -> "1:00 PM"."""
    return f"{hour % 12 or 12}:00 {'AM' if hour < 12 else 'PM'}"


FILTER_NAMES = {
    "live": "Bills", "type": "Order type", "hour": "Hour", "table": "Table", "waiter": "Waiter", "phone": "Mobile",
    "item": "Item", "dish": "Item", "category": "Category", "gst": "GST", "offer": "Offer", "rider": "Rider",
    "mode": "Mode", "staff": "Received by",
}


def filter_text(location, key, value):
    """How a narrowing reads above the report: ("Order type", "Dine in")."""
    if key == "live":
        shown = "Sales only (cancelled ones left out)"
    elif key == "type":
        shown = dict(Order.OrderType.choices).get(value, value)
    elif key == "mode":
        shown = dict(Payment.Mode.choices).get(value, value)
    elif key == "hour":
        shown = hour_label(whole(value)) if 0 <= whole(value) < 24 else value
    elif key == "gst":
        shown = f"{value}%"
    elif key == "offer" and value == NONE:
        shown = "By hand at the bill"
    elif key in ("waiter", "rider", "staff") and value == NONE:
        shown = "Guests (QR / public menu)" if key == "waiter" else "—"
    elif key in ("waiter", "rider", "staff"):
        shown = Staff.objects.filter(restaurant=location.restaurant, pk=whole(value)).values_list(
            "name", flat=True).first() or value
    elif key == "dish":
        shown = MenuItem.objects.filter(restaurant=location.restaurant, pk=whole(value)).values_list(
            "name", flat=True).first() or value
    else:
        shown = value
    return FILTER_NAMES.get(key, key), shown


def narrow_bills(bills, filters):
    """Only the bills of the row the bill register was opened from (to_bills): its order
    type, hour, table, waiter, mobile, dish or GST rate. Cancelled bills are left out then."""
    if not filters:
        return bills
    bills = bills.exclude(status=Bill.Status.CANCELLED)
    value = filters.get
    if value("type"):
        bills = bills.filter(order__order_type=value("type"))
    if value("hour"):
        bills = bills.filter(created_at__hour=whole(value("hour")))
    if value("table"):
        bills = bills.filter(order__order_type=Order.OrderType.DINE_IN, order__table__name=value("table"))
    if value("waiter"):
        bills = (bills.filter(order__waiter__isnull=True) if value("waiter") == NONE
                 else bills.filter(order__waiter_id=whole(value("waiter"))))
    if value("phone"):
        bills = bills.filter(order__customer_phone=value("phone"))
    if value("item"):
        bills = bills.filter(pk__in=BillItem.objects.filter(item_name=value("item")).values("bill"))
    if value("dish"):
        bills = bills.filter(pk__in=BillItem.objects.filter(menu_item_id=whole(value("dish"))).values("bill"))
    if value("gst"):
        rate = value("gst")
        bills = bills.filter(gst_percent=Decimal(rate)) if re.fullmatch(r"\d{1,3}(\.\d{1,2})?", rate) else bills.none()
    return bills


def money(value):
    return value if value is not None else ZERO


def share(part, whole):
    """part as a percent of whole, 1 decimal (0 when there is no whole)."""
    if not whole:
        return ZERO
    return (Decimal(part) * 100 / Decimal(whole)).quantize(Decimal("0.1"))


def average(total, count):
    return (Decimal(total) / count).quantize(Decimal("0.01")) if count else ZERO


def minutes(later, earlier):
    """Whole minutes between two times, or None when one is missing."""
    if not later or not earlier:
        return None
    return max(0, int((later - earlier).total_seconds() // 60))


def mean(numbers):
    numbers = [number for number in numbers if number is not None]
    return round(sum(numbers) / len(numbers)) if numbers else None


def live_bills(location, start, end):
    """The location's bills of these days that count as sales (cancelled ones left out)."""
    return Bill.objects.filter(location=location, bill_date__range=(start, end)).exclude(status=Bill.Status.CANCELLED)


def bill_items(location, start, end):
    return BillItem.objects.filter(bill__location=location, bill__bill_date__range=(start, end)).exclude(
        bill__status=Bill.Status.CANCELLED)


def place_of(order):
    """Where an order was for: "T4", "Takeaway" or "Delivery"."""
    if order.is_delivery:
        return "Delivery"
    if order.is_takeaway:
        return "Takeaway"
    return order.table.name if order.table_id else "—"
