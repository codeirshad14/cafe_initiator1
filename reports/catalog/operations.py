"""Operations reports: the kitchen (KOTs and their timings), tables, deliveries and riders."""

from collections import defaultdict

from django.db.models import Count, Q, Sum
from django.utils import timezone

from billing.models import Payment
from orders.models import KOT, Order

from .common import (
    ZERO, average, bill_id_of, live_bills, mean, minutes, money, place_of, section, to_bill, to_bills, to_report, whole,
)

LATE_KOT_MINUTES = 15          # as on the kitchen board
ON_TIME_DELIVERY_MINUTES = 45  # ordered to the door


def kot_register(location, start, end):
    """Every KOT: when, for whom, dishes, value, status, minutes to ready, who served it."""
    kots = (KOT.objects.filter(location=location, created_at__date__range=(start, end)).exclude(status=KOT.Status.HELD)
            .select_related("order__table", "order__bill", "served_by").order_by("created_at")
            .annotate(dishes=Sum("items__qty", filter=Q(items__is_cancelled=False)),
                      value=Sum("items__amount", filter=Q(items__is_cancelled=False))))
    rows = [[kot.kot_no, timezone.localtime(kot.created_at), place_of(kot.order), kot.order.order_no, kot.dishes or 0,
             money(kot.value), kot.get_status_display(), minutes(kot.ready_at, kot.created_at),
             kot.served_by.name if kot.served_by else "—"] for kot in kots]
    totals = ["Total", "", "", "", sum(row[4] for row in rows), sum((row[5] for row in rows), ZERO), "",
              mean(row[7] for row in rows), ""]
    return [section([("KOT no.", "int"), ("Sent", "datetime"), ("For", "text"), ("Order no.", "int"), ("Dishes", "int"),
                     ("Value", "money"), ("Status", "text"), ("Minutes to ready", "minutes"), ("Served by", "text")],
                    rows, totals, links=[to_bill(bill_id_of(kot.order)) for kot in kots])]


def kitchen_performance(location, start, end):
    """Each day: KOTs, average and slowest minutes to ready, KOTs late (over 15 min), cancelled."""
    days = defaultdict(lambda: {"kots": 0, "prep": [], "cancelled": 0})
    for sent, ready, status in (KOT.objects.filter(location=location, created_at__date__range=(start, end))
                                .exclude(status=KOT.Status.HELD).values_list("created_at", "ready_at", "status")):
        day = days[timezone.localtime(sent).date()]
        day["kots"] += 1
        day["cancelled"] += status == KOT.Status.CANCELLED
        if ready:
            day["prep"].append(minutes(ready, sent))
    rows = [[date, day["kots"], mean(day["prep"]), max(day["prep"], default=None),
             sum(1 for taken in day["prep"] if taken > LATE_KOT_MINUTES), day["cancelled"]]
            for date, day in sorted(days.items())]
    every = [taken for day in days.values() for taken in day["prep"]]
    totals = ["Total", sum(row[1] for row in rows), mean(every), max(every, default=None),
              sum(row[4] for row in rows), sum(row[5] for row in rows)]
    return [section([("Date", "date"), ("KOTs", "int"), ("Average minutes", "minutes"), ("Slowest", "minutes"),
                     ("Late (over 15 min)", "int"), ("Cancelled", "int")], rows, totals,
                    links=[to_report("kot-register", period=(row[0], row[0])) for row in rows])]  # the day's KOTs


def table_sales(location, start, end):
    """Each dining table: bills, net sales, average bill, and how long guests stayed."""
    bills = live_bills(location, start, end).filter(order__order_type=Order.OrderType.DINE_IN)
    grouped = list(bills.values("order__table__name").annotate(bills=Count("id"), net=Sum("grand_total")).order_by("-net"))
    stays = defaultdict(list)
    for name, came, left in (Order.objects.filter(location=location, order_type=Order.OrderType.DINE_IN,
                                                  closed_at__date__range=(start, end), status=Order.Status.CLOSED)
                             .values_list("table__name", "created_at", "closed_at")):
        stays[name].append(minutes(left, came))
    rows = [[row["order__table__name"] or "—", row["bills"], row["net"], average(row["net"], row["bills"]),
             mean(stays.get(row["order__table__name"], []))] for row in grouped]
    total = bills.aggregate(bills=Count("id"), net=Sum("grand_total"))
    totals = ["Total", total["bills"], money(total["net"]), average(money(total["net"]), total["bills"]),
              mean(taken for table in stays.values() for taken in table)]
    return [section([("Table", "text"), ("Bills", "int"), ("Net sales", "money"), ("Average bill", "money"),
                     ("Average stay (min)", "minutes")], rows, totals,
                    links=[to_bills(table=row["order__table__name"]) if row["order__table__name"] else None
                           for row in grouped])]


def delivery_register(location, start, end, rider=""):
    """Every delivery order: customer, address, rider, minutes on the ride and to the door, amount, state."""
    orders = (Order.objects.filter(location=location, order_type=Order.OrderType.DELIVERY,
                                   created_at__date__range=(start, end))
              .select_related("rider", "bill").order_by("created_at"))
    if rider:  # opened from Rider performance: the rider's deliveries
        orders = orders.filter(rider_id=whole(rider), delivered_at__isnull=False)
    rows = []
    for order in orders:
        bill = order.bill if hasattr(order, "bill") else None  # (no bill made yet: no row to follow)
        state = ("Delivered" if order.delivered_at else "Cancelled" if order.status == Order.Status.CANCELLED
                 else "On the way" if order.picked_up_at else order.get_status_display())
        rows.append([order.order_no, timezone.localtime(order.created_at), order.customer_name, order.customer_phone,
                     order.customer_address, order.rider.name if order.rider else "—",
                     minutes(order.delivered_at, order.picked_up_at), minutes(order.delivered_at, order.created_at),
                     bill.grand_total if bill else ZERO, state])
    totals = ["Total", "", "", "", "", "", mean(row[6] for row in rows), mean(row[7] for row in rows),
              sum((row[8] for row in rows), ZERO), ""]
    return [section([("Order no.", "int"), ("Ordered", "datetime"), ("Customer", "text"), ("Mobile", "text"),
                     ("Address", "text"), ("Rider", "text"), ("Ride (min)", "minutes"), ("Door to door (min)", "minutes"),
                     ("Amount", "money"), ("State", "text")], rows, totals,
                    links=[to_bill(bill_id_of(order)) for order in orders])]


def rider_performance(location, start, end):
    """Each rider: deliveries, average / fastest / slowest ride, on time, cash and other money taken at the door."""
    riders = defaultdict(lambda: {"name": "", "rides": [], "door": []})
    for rider_id, name, ordered, picked, delivered in (Order.objects.filter(
            location=location, order_type=Order.OrderType.DELIVERY, delivered_at__date__range=(start, end),
            rider__isnull=False).values_list("rider", "rider__name", "created_at", "picked_up_at", "delivered_at")):
        riders[rider_id]["name"] = name
        riders[rider_id]["rides"].append(minutes(delivered, picked))
        riders[rider_id]["door"].append(minutes(delivered, ordered))
    taken = defaultdict(lambda: {"cash": ZERO, "other": ZERO})
    for rider_id, mode, amount in (Payment.objects.filter(location=location, created_at__date__range=(start, end),
                                                          bill__order__order_type=Order.OrderType.DELIVERY,
                                                          received_by__in=list(riders))
                                   .values_list("received_by", "mode", "amount")):
        taken[rider_id]["cash" if mode == Payment.Mode.CASH else "other"] += amount
    rows, links = [], []
    for rider_id, rider in sorted(riders.items(), key=lambda item: mean(item[1]["rides"]) or 0):
        rides = [ride for ride in rider["rides"] if ride is not None]
        on_time = sum(1 for door in rider["door"] if door is not None and door <= ON_TIME_DELIVERY_MINUTES)
        rows.append([rider["name"], len(rider["rides"]), mean(rides), min(rides, default=None), max(rides, default=None),
                     average(on_time * 100, len(rider["door"])), taken[rider_id]["cash"], taken[rider_id]["other"]])
        links.append(to_report("delivery-register", rider=rider_id))  # the rider's deliveries
    totals = ["Total", sum(row[1] for row in rows), "", "", "", "", sum((row[6] for row in rows), ZERO),
              sum((row[7] for row in rows), ZERO)]
    return [section([("Rider", "text"), ("Deliveries", "int"), ("Average ride", "minutes"), ("Fastest", "minutes"),
                     ("Slowest", "minutes"), ("On time %", "percent"), ("Cash taken", "money"),
                     ("UPI / card taken", "money")], rows, totals, links=links)]
