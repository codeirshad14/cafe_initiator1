"""Sales reports: by day, month and hour; order types; payment modes; GST; discounts; the bill and payment registers."""

from datetime import timedelta

from django.db.models import Count, F, Sum
from django.db.models.functions import ExtractHour, TruncMonth
from django.utils import timezone

from billing.models import Bill, Payment
from orders.models import Order

from .common import (
    NONE, ZERO, average, hour_label, live_bills, money, narrow_bills, place_of, section, share, to_bill, to_bills,
    to_report, whole,
)

SALE_SUMS = dict(
    bills=Count("id"), gross=Sum("subtotal"), discount=Sum("discount_amount"), delivery=Sum("delivery_charge"),
    tax=Sum(F("cgst_amount") + F("sgst_amount")), round_off=Sum("round_off"), net=Sum("grand_total"),
)
SALE_COLUMNS = [("Bills", "int"), ("Gross", "money"), ("Discount", "money"), ("Delivery", "money"),
                ("Tax (CGST + SGST)", "money"), ("Round off", "money"), ("Net", "money"), ("Average bill", "money")]


def sale_row(label, sums):
    return [label, sums["bills"], money(sums["gross"]), money(sums["discount"]), money(sums["delivery"]),
            money(sums["tax"]), money(sums["round_off"]), money(sums["net"]), average(money(sums["net"]), sums["bills"])]


def daily_sales(location, start, end):
    """Each day: bills, gross (before discount), discount, delivery, tax, round off, net, average bill."""
    bills = live_bills(location, start, end)
    days = list(bills.values("bill_date").annotate(**SALE_SUMS).order_by("bill_date"))
    rows = [sale_row(day["bill_date"], day) for day in days]
    links = [to_bills(period=(day["bill_date"], day["bill_date"])) for day in days]  # the day's bills
    return [section([("Date", "date")] + SALE_COLUMNS, rows, sale_row("Total", bills.aggregate(**SALE_SUMS)), links=links)]


def month_days(month, start, end):
    """The days of `month` inside the period: (first, last)."""
    last = (month.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return max(month, start), min(last, end)


def monthly_sales(location, start, end):
    """Each month of the period: the same figures, a month a line (pick Range for a year)."""
    bills = live_bills(location, start, end)
    months = list(bills.annotate(month=TruncMonth("bill_date")).values("month").annotate(**SALE_SUMS).order_by("month"))
    rows = [sale_row(row["month"].strftime("%B %Y"), row) for row in months]
    links = [to_report("daily-sales", period=month_days(row["month"], start, end)) for row in months]  # its days
    return [section([("Month", "text")] + SALE_COLUMNS, rows, sale_row("Total", bills.aggregate(**SALE_SUMS)), links=links)]


def hourly_sales(location, start, end):
    """Each hour of the day, the period together: when the cafe sells."""
    bills = live_bills(location, start, end)
    grand = money(bills.aggregate(total=Sum("grand_total"))["total"])
    hours = list(bills.annotate(hour=ExtractHour("created_at")).values("hour").annotate(
        bills=Count("id"), net=Sum("grand_total")).order_by("hour"))
    rows = [[hour_label(row["hour"]), row["bills"], row["net"], average(row["net"], row["bills"]), share(row["net"], grand)]
            for row in hours]
    totals = ["Total", sum(row[1] for row in rows), grand, average(grand, sum(row[1] for row in rows)), ""]
    return [section([("Hour", "text"), ("Bills", "int"), ("Net", "money"), ("Average bill", "money"),
                     ("Share", "percent")], rows, totals, links=[to_bills(hour=row["hour"]) for row in hours])]


def order_types(location, start, end):
    """Dine in, takeaway and delivery: bills, net sales, average bill and share."""
    bills = live_bills(location, start, end)
    grand = money(bills.aggregate(total=Sum("grand_total"))["total"])
    sums = {row["order__order_type"]: row for row in
            bills.values("order__order_type").annotate(bills=Count("id"), net=Sum("grand_total"))}
    rows, links = [], []
    for code, label in Order.OrderType.choices:
        row = sums.get(code, {"bills": 0, "net": ZERO})
        rows.append([label, row["bills"], row["net"], average(row["net"], row["bills"]), share(row["net"], grand)])
        links.append(to_bills(type=code) if row["bills"] else None)
    return [section([("Order type", "text"), ("Bills", "int"), ("Net", "money"), ("Average bill", "money"),
                     ("Share", "percent")], rows, ["Total", sum(row[1] for row in rows), grand, "", ""], links=links)]


def payment_modes(location, start, end):
    """Money collected per mode on these days (the day the payment was taken)."""
    payments = Payment.objects.filter(location=location, created_at__date__range=(start, end))
    by_mode = {row["mode"]: row for row in payments.values("mode").annotate(count=Count("id"), amount=Sum("amount"))}
    grand = money(payments.aggregate(total=Sum("amount"))["total"])
    rows, links = [], []
    for code, label in Payment.Mode.choices:
        row = by_mode.get(code, {"count": 0, "amount": ZERO})
        rows.append([label, row["count"], row["amount"], share(row["amount"], grand)])
        links.append(to_report("payment-register", mode=code) if row["count"] else None)
    return [section([("Mode", "text"), ("Payments", "int"), ("Collected", "money"), ("Share", "percent")],
                    rows, ["Total", sum(row[1] for row in rows), grand, ""], links=links)]


def gst_summary(location, start, end):
    """For the GST return: each day's taxable amount, CGST, SGST and total tax, at each rate."""
    bills = live_bills(location, start, end)
    sums = dict(bills=Count("id"), taxable=Sum("taxable_amount"), cgst=Sum("cgst_amount"), sgst=Sum("sgst_amount"),
                net=Sum("grand_total"))
    days = list(bills.values("bill_date", "gst_percent").annotate(**sums).order_by("bill_date", "gst_percent"))
    rows = [[row["bill_date"], row["gst_percent"], row["bills"], row["taxable"], row["cgst"], row["sgst"],
             row["cgst"] + row["sgst"], row["net"]] for row in days]
    links = [to_bills(period=(row["bill_date"], row["bill_date"]), gst=row["gst_percent"]) for row in days]
    total = bills.aggregate(**sums)
    totals = ["Total", "", total["bills"], money(total["taxable"]), money(total["cgst"]), money(total["sgst"]),
              money(total["cgst"]) + money(total["sgst"]), money(total["net"])]
    return [section([("Date", "date"), ("GST %", "percent"), ("Bills", "int"), ("Taxable", "money"),
                     ("CGST", "money"), ("SGST", "money"), ("Total tax", "money"), ("Bill total", "money")],
                    rows, totals, links=links)]


def discount_register(location, start, end, offer=""):
    """Every bill with a discount: the offer (or by hand), gross, discount and its percent."""
    bills = live_bills(location, start, end).filter(discount_amount__gt=0).select_related("order__table").order_by("bill_no")
    if offer:  # opened from Offers & discounts used
        bills = bills.filter(offer_name="" if offer == NONE else offer)
    rows = [[bill.bill_no, bill.bill_date, place_of(bill.order), bill.offer_name or "By hand", bill.subtotal,
             bill.discount_amount, share(bill.discount_amount, bill.subtotal), bill.grand_total] for bill in bills]
    totals = ["Total", "", "", "", sum((row[4] for row in rows), ZERO), sum((row[5] for row in rows), ZERO),
              share(sum((row[5] for row in rows), ZERO), sum((row[4] for row in rows), ZERO)),
              sum((row[7] for row in rows), ZERO)]
    return [section([("Bill no.", "int"), ("Date", "date"), ("For", "text"), ("Offer", "text"), ("Gross", "money"),
                     ("Discount", "money"), ("Discount %", "percent"), ("Bill total", "money")], rows, totals,
                    links=[to_bill(bill.pk) for bill in bills])]


def bill_register(location, start, end, **filters):
    """Every bill, like a day book. Cancelled bills are listed but not added up."""
    every = Bill.objects.filter(location=location, bill_date__range=(start, end))
    bills = narrow_bills(every, filters).select_related("order__table", "created_by").order_by("bill_no")
    rows = [[bill.bill_no, bill.bill_date, timezone.localtime(bill.created_at), place_of(bill.order),
             bill.order.customer_name, bill.grand_total, bill.paid_amount, bill.balance, bill.get_status_display(),
             bill.created_by.name if bill.created_by else "—"] for bill in bills]
    total = narrow_bills(live_bills(location, start, end), filters).aggregate(
        amount=Sum("grand_total"), paid=Sum("paid_amount"))
    totals = ["Total", "", "", "", "", money(total["amount"]), money(total["paid"]),
              money(total["amount"]) - money(total["paid"]), "", ""]
    return [section([("Bill no.", "int"), ("Date", "date"), ("Time", "datetime"), ("For", "text"), ("Guest", "text"),
                     ("Amount", "money"), ("Paid", "money"), ("Balance", "money"), ("Status", "text"),
                     ("Made by", "text")], rows, totals, links=[to_bill(bill.pk) for bill in bills])]


def payment_register(location, start, end, mode="", staff=""):
    """Every payment taken on these days: when, the bill, the mode and reference, the amount, who took it."""
    payments = (Payment.objects.filter(location=location, created_at__date__range=(start, end))
                .select_related("bill__order__table", "received_by").order_by("created_at"))
    if mode:  # opened from Payment modes
        payments = payments.filter(mode=mode)
    if staff:  # opened from Staff collections
        payments = (payments.filter(received_by__isnull=True) if staff == NONE
                    else payments.filter(received_by_id=whole(staff)))
    rows = [[timezone.localtime(payment.created_at), payment.bill.bill_no, place_of(payment.bill.order),
             payment.bill.order.customer_name, payment.get_mode_display(), payment.reference_no or "—", payment.amount,
             payment.received_by.name if payment.received_by else "—"] for payment in payments]
    totals = ["Total", "", "", "", "", "", sum((row[6] for row in rows), ZERO), ""]
    return [section([("Time", "datetime"), ("Bill no.", "int"), ("For", "text"), ("Guest", "text"), ("Mode", "text"),
                     ("Reference", "text"), ("Amount", "money"), ("Received by", "text")], rows, totals,
                    links=[to_bill(payment.bill_id) for payment in payments])]
