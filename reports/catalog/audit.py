"""Audit reports: what was cancelled (and why), and the festival offers given."""

from django.db.models import Count, Q, Sum

from billing.models import Bill
from orders.models import KOT, Order

from .common import NONE, ZERO, bill_id_of, live_bills, money, place_of, section, to_bill, to_report


def cancelled(location, start, end):
    """Cancelled KOTs, cancelled bills and orders cancelled before their bill, with the reasons."""
    kots = (KOT.objects.filter(location=location, status=KOT.Status.CANCELLED, created_at__date__range=(start, end))
            .select_related("order__table", "order__bill").order_by("created_at")
            .annotate(dishes=Count("items", filter=Q(items__is_cancelled=False)),
                      value=Sum("items__amount", filter=Q(items__is_cancelled=False))))
    kot_rows = [[kot.kot_no, kot.created_at.date(), place_of(kot.order), kot.order.order_no, kot.dishes,
                 money(kot.value), kot.order.cancel_reason or "—"] for kot in kots]

    bills = (Bill.objects.filter(location=location, status=Bill.Status.CANCELLED, bill_date__range=(start, end))
             .select_related("order__table").order_by("bill_no"))
    bill_rows = [[bill.bill_no, bill.bill_date, place_of(bill.order), bill.grand_total, bill.cancel_reason or "—"]
                 for bill in bills]

    orders = (Order.objects.filter(location=location, status=Order.Status.CANCELLED, closed_at__date__range=(start, end))
              .exclude(bill__isnull=False).select_related("table").order_by("closed_at"))
    order_rows = [[order.order_no, order.closed_at.date(), place_of(order), order.customer_name,
                   order.cancel_reason or "—"] for order in orders]

    return [
        section([("KOT no.", "int"), ("Date", "date"), ("For", "text"), ("Order no.", "int"), ("Dishes", "int"),
                 ("Value", "money"), ("Order cancel reason", "text")], kot_rows,
                ["Total", "", "", "", sum(row[4] for row in kot_rows), sum((row[5] for row in kot_rows), ZERO), ""],
                title="Cancelled KOTs", links=[to_bill(bill_id_of(kot.order)) for kot in kots]),
        section([("Bill no.", "int"), ("Date", "date"), ("For", "text"), ("Amount", "money"), ("Reason", "text")],
                bill_rows, ["Total", "", "", sum((row[3] for row in bill_rows), ZERO), ""], title="Cancelled bills",
                links=[to_bill(bill.pk) for bill in bills]),
        section([("Order no.", "int"), ("Date", "date"), ("For", "text"), ("Guest", "text"), ("Reason", "text")],
                order_rows, [f"{len(order_rows)} orders", "", "", "", ""], title="Orders cancelled before their bill"),
    ]


def offers_used(location, start, end):
    """Each festival offer (and discounts by hand): bills it went on, discount given, and the sales it came with."""
    bills = live_bills(location, start, end).filter(discount_amount__gt=0)
    grouped = list(bills.values("offer_name").annotate(bills=Count("id"), discount=Sum("discount_amount"),
                                                       gross=Sum("subtotal"), net=Sum("grand_total")).order_by("-discount"))
    rows = [[row["offer_name"] or "By hand at the bill", row["bills"], row["gross"], row["discount"], row["net"]]
            for row in grouped]
    totals = ["Total", sum(row[1] for row in rows), sum((row[2] for row in rows), ZERO),
              sum((row[3] for row in rows), ZERO), sum((row[4] for row in rows), ZERO)]
    return [section([("Offer", "text"), ("Bills", "int"), ("Gross", "money"), ("Discount", "money"),
                     ("Bill total", "money")], rows, totals,
                    links=[to_report("discounts", offer=row["offer_name"] or NONE) for row in grouped])]
