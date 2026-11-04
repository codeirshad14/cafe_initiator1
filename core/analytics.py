"""
The dashboard's figures for a period (core.views.dashboard): a CEO's view of every
module. Sales, menu, kitchen, tables, deliveries, guests and bookings, the team,
and what leaks away (cancellations, discounts).

    Today        today so far
    This week    Monday to today
    This month   the 1st to today
    Range        any two past days (at most a year)

Every headline figure comes with the same-length period just before it, so the
dashboard can say "+12% on the previous week". Cancelled bills never count as
sales; they are shown on their own.
"""

import math
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlencode

from django.db.models import Count, Sum
from django.db.models.functions import ExtractHour, ExtractIsoWeekDay

from billing.models import Bill, BillItem, Payment
from menu.models import MenuItem
from orders.delivery import ride_times
from orders.models import KOT, Order
from tables.models import Booking, DiningTable
from tables.periods import read_date

ZERO = Decimal("0.00")
LATE_KOT_MINUTES = 15       # a KOT not ready within this is late (as on the kitchen board)
ON_TIME_DELIVERY_MINUTES = 45  # ordered to the door within this counts as on time
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
PERIODS = [("today", "Today"), ("week", "This week"), ("month", "This month"), ("range", "Range")]
MAX_RANGE_DAYS = 366


def analytics_period(params, today):
    """(when, first day, last day) from ?when= (&from= &to=), never after today; Today by default."""
    when = params.get("when", "today")
    if when == "week":
        return when, today - timedelta(days=today.weekday()), today
    if when == "month":
        return when, today.replace(day=1), today
    if when == "range":
        end = min(read_date(params.get("to")) or today, today)
        start = min(read_date(params.get("from")) or end, end)
        return when, max(start, end - timedelta(days=MAX_RANGE_DAYS - 1)), end
    return "today", today, today


def period_filter_context(params, today):
    """The filter row (partials/_period_filter.html, looking back) and the query to ask again with."""
    when, start, end = analytics_period(params, today)
    filters = {"when": when}
    if when == "range":
        filters.update({"from": start.isoformat(), "to": end.isoformat()})
    return {"periods": PERIODS, "when": when, "start": start, "end": end, "today": today,
            "filter_query": urlencode(filters), "looks_back": True}


def change(now, before):
    """Percent change from `before` to `now`, rounded; None when there is nothing to compare with."""
    if not before:
        return None
    return round((Decimal(now) - Decimal(before)) * 100 / Decimal(before))


def share_rows(rows):
    """[{"label", "total", ...}] -> the same, each with "share": its percent of the biggest row (bar width)."""
    biggest = max((row["total"] for row in rows), default=ZERO)
    for row in rows:
        row["share"] = int(row["total"] * 100 / biggest) if biggest else 0
    return rows


def headline(bills, payments):
    sums = bills.aggregate(count=Count("id"), sales=Sum("grand_total"), discount=Sum("discount_amount"),
                           gst=Sum("cgst_amount") + Sum("sgst_amount"))
    sales = sums["sales"] or ZERO
    count = sums["count"]
    return {
        "sales": sales,
        "bills": count,
        "average": (sales / count).quantize(Decimal("0.01")) if count else ZERO,
        "discount": sums["discount"] or ZERO,
        "gst": sums["gst"] or ZERO,
        "collected": payments.aggregate(total=Sum("amount"))["total"] or ZERO,
    }


def trend(bills, start, end):
    """Sales over the period: by hour for one day, else by day. Bar heights against the best bar."""
    if start == end:
        totals = dict(bills.annotate(hour=ExtractHour("created_at")).values_list("hour")
                      .annotate(total=Sum("grand_total")))
        hours = sorted(totals) or [12]
        points = [{"label": f"{hour % 12 or 12}{'a' if hour < 12 else 'p'}", "title": f"{hour:02d}:00",
                   "total": totals.get(hour, ZERO)} for hour in range(min(hours), max(hours) + 1)]
    else:
        totals = dict(bills.values_list("bill_date").annotate(total=Sum("grand_total")))
        days = (end - start).days + 1
        points = []
        for n in range(days):
            day = start + timedelta(days=n)
            label = day.strftime("%a") if days <= 7 else str(day.day)
            points.append({"label": label, "title": day.strftime("%a %d %b"), "total": totals.get(day, ZERO)})
    best = max((point["total"] for point in points), default=ZERO)
    for point in points:
        point["height"] = int(point["total"] * 100 / best) if best else 0
        if point["total"] and point["height"] < 3:
            point["height"] = 3  # a day with sales never looks empty
    return points


def busy_hours(bills):
    """Bills by hour of the day, the whole period together: when the cafe is busiest."""
    rows = [{"label": f"{hour % 12 or 12} {'AM' if hour < 12 else 'PM'}", "total": total, "count": count}
            for hour, total, count in bills.annotate(hour=ExtractHour("created_at")).values_list("hour")
            .annotate(total=Sum("grand_total"), count=Count("id")).order_by("hour")]
    return share_rows(rows)


def by_order_type(bills):
    totals = {kind: (total, count) for kind, total, count in bills.values_list("order__order_type")
              .annotate(total=Sum("grand_total"), count=Count("id"))}
    labels = {Order.OrderType.DINE_IN: "Dine in", Order.OrderType.TAKEAWAY: "Takeaway", Order.OrderType.DELIVERY: "Delivery"}
    return share_rows([{"label": label, "total": totals.get(kind, (ZERO, 0))[0], "count": totals.get(kind, (ZERO, 0))[1]}
                       for kind, label in labels.items()])


def by_payment_mode(payments):
    totals = dict(payments.values_list("mode").annotate(total=Sum("amount")))
    return share_rows([{"label": label, "total": totals.get(code, ZERO)} for code, label in Payment.Mode.choices])


def by_category(bills):
    rows = [{"label": name, "total": total, "count": qty} for name, total, qty in
            BillItem.objects.filter(bill__in=bills).values_list("category_name")
            .annotate(total=Sum("amount"), qty=Sum("qty")).order_by("-total")]
    return share_rows(rows)


def top_dishes(bills, limit=10):
    return list(BillItem.objects.filter(bill__in=bills).values("item_name", "category_name")
                .annotate(qty=Sum("qty"), amount=Sum("amount")).order_by("-amount", "-qty")[:limit])


def by_staff(bills):
    """Sales by who took the order: each waiter, and the guests' own QR / public menu orders."""
    rows = [{"label": name or "Guests (QR / public menu)", "total": total, "count": count}
            for name, total, count in bills.values_list("order__waiter__name")
            .annotate(total=Sum("grand_total"), count=Count("id")).order_by("-total")]
    return share_rows(rows)


def minutes(later, earlier):
    return max(0, int((later - earlier).total_seconds() // 60))


def average(numbers):
    return round(sum(numbers) / len(numbers)) if numbers else None


def percent(part, whole):
    return round(part * 100 / whole) if whole else None


def sparkline(points, width=100, height=28):
    """The trend as SVG polyline points ("x,y x,y ...") in a width x height box, for the hero tile."""
    values = [float(point["total"]) for point in points]
    if len(values) < 2:
        return ""
    top = max(values) or 1
    step = width / (len(values) - 1)
    return " ".join(f"{index * step:.1f},{height - 2 - value / top * (height - 4):.1f}" for index, value in enumerate(values))


def order_type_split(rows):
    """The three order types as one stacked bar: each row gets "width", its percent of all sales."""
    whole = sum((row["total"] for row in rows), ZERO)
    for row in rows:
        row["width"] = round(row["total"] * 100 / whole, 1) if whole else 0
    return rows


def heatmap(bills):
    """Pivot: weekday x hour of net sales, the period together. Each cell has a level 0-5
    (0 = nothing; 1-5 = steps of the sequential ramp, against the busiest cell)."""
    cells = {(day, hour): total for day, hour, total in
             bills.annotate(day=ExtractIsoWeekDay("created_at"), hour=ExtractHour("created_at"))
             .values_list("day", "hour").annotate(total=Sum("grand_total"))}
    if not cells:
        return None
    hours = range(min(hour for _, hour in cells), max(hour for _, hour in cells) + 1)
    busiest = max(cells.values())
    rows = []
    for day in range(1, 8):
        row = []
        for hour in hours:
            total = cells.get((day, hour), ZERO)
            row.append({"total": total, "level": math.ceil(total * 5 / busiest) if total else 0,
                        "title": f"{WEEKDAYS[day - 1]} {hour % 12 or 12} {'AM' if hour < 12 else 'PM'}"})
        rows.append({"day": WEEKDAYS[day - 1], "cells": row})
    labels = [f"{hour % 12 or 12}{'a' if hour < 12 else 'p'}" for hour in hours]
    return {"hours": labels, "rows": rows}


def slow_dishes(restaurant, bills, limit=6):
    """The dishes on the menu that sold least (0 when not at all): what to fix or drop."""
    sold = dict(BillItem.objects.filter(bill__in=bills).values_list("menu_item").annotate(qty=Sum("qty")))
    dishes = MenuItem.objects.filter(restaurant=restaurant, is_active=True).select_related("category")
    rows = sorted(({"name": dish.name, "category": dish.category.name, "qty": sold.get(dish.pk, 0)} for dish in dishes),
                  key=lambda row: (row["qty"], row["name"]))
    return rows[:limit]


def offers_used(bills):
    """Discounts given, by festival offer, and by hand (the cashier's own)."""
    rows = [{"label": name, "total": total, "count": count} for name, total, count in
            bills.exclude(offer_name="").values_list("offer_name")
            .annotate(total=Sum("discount_amount"), count=Count("id")).order_by("-total")]
    by_hand = bills.filter(offer_name="", discount_amount__gt=0).aggregate(total=Sum("discount_amount"), count=Count("id"))
    if by_hand["count"]:
        rows.append({"label": "By hand at the bill", "total": by_hand["total"], "count": by_hand["count"]})
    return share_rows(rows)


def kitchen_figures(location, start, end):
    """KOTs sent, how fast they were ready, how many late, how many cancelled."""
    kots = KOT.objects.filter(location=location, created_at__date__range=(start, end)).exclude(status=KOT.Status.HELD)
    prep = [minutes(ready, sent) for sent, ready in kots.filter(ready_at__isnull=False).values_list("created_at", "ready_at")]
    late = sum(1 for taken in prep if taken > LATE_KOT_MINUTES)
    return {
        "kots": kots.count(),
        "cancelled": kots.filter(status=KOT.Status.CANCELLED).count(),
        "avg_prep": average(prep),
        "slowest": max(prep, default=None),
        "on_time": percent(len(prep) - late, len(prep)),
        "late": late,
    }


def table_figures(location, start, end, days):
    """Dine-in tables: how long guests stay, how often a table turns, the busiest tables."""
    closed = Order.objects.filter(location=location, order_type=Order.OrderType.DINE_IN, status=Order.Status.CLOSED,
                                  closed_at__date__range=(start, end))
    stays = [minutes(left, came) for came, left in closed.values_list("created_at", "closed_at")]
    tables = DiningTable.objects.filter(location=location, is_active=True, is_takeaway=False).count()
    busiest = [{"label": name, "total": total or ZERO, "count": count} for name, total, count in
               closed.values_list("table__name").annotate(total=Sum("bill__grand_total"), count=Count("id"))
               .order_by("-total")[:6]]
    return {
        "orders": len(stays),
        "avg_stay": average(stays),
        "turns": round(len(stays) / tables / days, 1) if tables else None,  # orders per table per day
        "busiest": share_rows(busiest),
    }


def delivery_figures(location, start, end):
    """Deliveries done: door-to-door time, the rides, on time, and the ones rejected or cancelled."""
    done =list(Order.objects.filter(location=location, order_type=Order.OrderType.DELIVERY,
                                     delivered_at__date__range=(start, end)).select_related("rider"))
    door = [minutes(order.delivered_at, order.created_at) for order in done]
    on_time = sum(1 for taken in door if taken <= ON_TIME_DELIVERY_MINUTES)
    return {
        "count": len(done),
        "door_avg": average(door),
        "on_time": percent(on_time, len(door)),
        "rides": ride_times(done),
        "cancelled": Order.objects.filter(location=location, order_type=Order.OrderType.DELIVERY,
                                          status=Order.Status.CANCELLED, closed_at__date__range=(start, end)).count(),
    }


def booking_figures(location, start, end):
    """Bookings for the period's days: how many, the guests, how they ended."""
    bookings = Booking.objects.filter(location=location, date__range=(start, end))
    counts = dict(bookings.values_list("status").annotate(count=Count("id")))
    seated, no_show = counts.get(Booking.Status.SEATED, 0), counts.get(Booking.Status.NO_SHOW, 0)
    rows = [{"label": label, "total": counts.get(code, 0)} for code, label in Booking.Status.choices]
    return {
        "count": sum(counts.values()),
        "guests": bookings.exclude(status=Booking.Status.CANCELLED).aggregate(total=Sum("guests"))["total"] or 0,
        "show_rate": percent(seated, seated + no_show),
        "statuses": share_rows(rows),
    }


def guest_figures(location, start, bills):
    """Guests known by their mobile number: how many, and how many came back (ordered here before)."""
    phones = set(bills.exclude(order__customer_phone="").values_list("order__customer_phone", flat=True))
    returning = set(Order.objects.filter(location=location, customer_phone__in=phones, created_at__date__lt=start)
                    .values_list("customer_phone", flat=True).distinct())
    return {"known": len(phones), "returning": len(returning), "new": len(phones) - len(returning),
            "returning_share": percent(len(returning), len(phones))}


def by_collector(payments):
    """Money taken by each staff member (cashiers at the counter, riders at the door)."""
    rows = [{"label": name or "—", "total": total, "count": count} for name, total, count in
            payments.values_list("received_by__name").annotate(total=Sum("amount"), count=Count("id")).order_by("-total")]
    return share_rows(rows)


def by_location(restaurant, start, end):
    """Net sales of every location of the company in the period, for the admin and
    manager when there is more than one ([] otherwise)."""
    places = list(restaurant.locations.all())
    if len(places) < 2:
        return []
    totals = {place_id: (total, count) for place_id, total, count in
              Bill.objects.filter(restaurant=restaurant, bill_date__range=(start, end))
              .exclude(status=Bill.Status.CANCELLED).values_list("location")
              .annotate(total=Sum("grand_total"), count=Count("id"))}
    return share_rows([{"label": place.name, "total": totals.get(place.pk, (ZERO, 0))[0],
                        "count": totals.get(place.pk, (ZERO, 0))[1]} for place in places])


def dashboard_figures(location, start, end):
    """Everything the dashboard shows for the location's start..end (days included),
    with the period before to compare."""
    def bills_between(first, last):
        return Bill.objects.filter(location=location, bill_date__range=(first, last)).exclude(status=Bill.Status.CANCELLED)

    def payments_between(first, last):
        return Payment.objects.filter(location=location, created_at__date__range=(first, last))

    length = (end - start).days + 1
    before_end = start - timedelta(days=1)
    before_start = before_end - timedelta(days=length - 1)

    bills = bills_between(start, end)
    payments = payments_between(start, end)
    now = headline(bills, payments)
    before_bills = bills_between(before_start, before_end)
    before = headline(before_bills, payments_between(before_start, before_end))
    now["items"] = BillItem.objects.filter(bill__in=bills).aggregate(qty=Sum("qty"))["qty"] or 0
    now["items_per_bill"] = round(now["items"] / now["bills"], 1) if now["bills"] else 0
    guests = guest_figures(location, start, bills)
    sales_trend = trend(bills, start, end)

    return {
        "figures": now,
        "changes": {key: change(now[key], before[key]) for key in ("sales", "bills", "average", "collected", "discount")},
        "before_start": before_start, "before_end": before_end,
        "trend": sales_trend,
        "spark": sparkline(sales_trend),
        # sales
        "order_types": order_type_split(by_order_type(bills)),
        "modes": by_payment_mode(payments),
        "heat": heatmap(bills),
        "hours": busy_hours(bills),
        # menu
        "categories": by_category(bills),
        "dishes": top_dishes(bills),
        "slow": slow_dishes(location.restaurant, bills),
        "offers": offers_used(bills),
        # operations
        "kitchen": kitchen_figures(location, start, end),
        "tables": table_figures(location, start, end, length),
        "delivery": delivery_figures(location, start, end),
        # guests and team
        "guests": guests,
        "bookings": booking_figures(location, start, end),
        "staff_sales": by_staff(bills),
        "collectors": by_collector(payments),
        # what leaks away
        "losses": {
            "bills": Bill.objects.filter(location=location, bill_date__range=(start, end), status=Bill.Status.CANCELLED)
                     .aggregate(count=Count("id"), total=Sum("grand_total")),
            "orders": Order.objects.filter(location=location, status=Order.Status.CANCELLED,
                                           closed_at__date__range=(start, end)).count(),
            "kots": KOT.objects.filter(location=location, status=KOT.Status.CANCELLED,
                                       created_at__date__range=(start, end)).count(),
        },
        "recent_bills": bills.select_related("order__table").order_by("-created_at")[:10],
        "days": length,
    }
