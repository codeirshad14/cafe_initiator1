"""Team reports: what each waiter brought in, and the money each person took."""

from collections import defaultdict

from django.db.models import Count, Sum

from billing.models import Payment

from .common import NONE, ZERO, average, live_bills, money, section, to_bills, to_report


def waiter_sales(location, start, end):
    """Each waiter: orders handled, dine-in tables served, net sales and average bill.
    The guests' own QR / public menu orders (no waiter) are one line."""
    bills = live_bills(location, start, end)
    grouped = list(bills.values("order__waiter", "order__waiter__name").annotate(
        orders=Count("order", distinct=True), tables=Count("order__table", distinct=True), net=Sum("grand_total"),
    ).order_by("-net"))
    rows = [[row["order__waiter__name"] or "Guests (QR / public menu)", row["orders"], row["tables"], row["net"],
             average(row["net"], row["orders"])] for row in grouped]
    total = bills.aggregate(orders=Count("order", distinct=True), net=Sum("grand_total"))
    return [section([("Waiter", "text"), ("Orders", "int"), ("Tables", "int"), ("Net sales", "money"),
                     ("Average bill", "money")], rows,
                    ["Total", total["orders"], "", money(total["net"]), average(money(total["net"]), total["orders"])],
                    links=[to_bills(waiter=row["order__waiter"] or NONE) for row in grouped])]


def staff_collections(location, start, end):
    """Money each person took, by mode: what each cashier and rider should hand over."""
    people = defaultdict(lambda: defaultdict(lambda: ZERO))
    counts = defaultdict(int)
    names = {}
    for staff_id, name, mode, amount in (Payment.objects.filter(location=location, created_at__date__range=(start, end))
                                         .values_list("received_by", "received_by__name", "mode", "amount")):
        people[staff_id][mode] += amount
        counts[staff_id] += 1
        names[staff_id] = name or "—"
    modes = Payment.Mode.choices
    order = sorted(people, key=lambda staff_id: names[staff_id])
    rows = [[names[staff_id], counts[staff_id], *(people[staff_id][code] for code, _ in modes),
             sum(people[staff_id].values(), ZERO)] for staff_id in order]
    totals = ["Total", sum(row[1] for row in rows)] + [sum((row[2 + n] for row in rows), ZERO) for n in range(len(modes) + 1)]
    return [section([("Staff", "text"), ("Payments", "int")] + [(label, "money") for _, label in modes] + [("Total", "money")],
                    rows, totals, links=[to_report("payment-register", staff=staff_id or NONE) for staff_id in order])]
