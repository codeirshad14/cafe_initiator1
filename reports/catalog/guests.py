"""Guest reports: customers known by their mobile number, and table bookings."""

from collections import defaultdict

from django.db.models import Count, Max, Min, Sum

from billing.models import Bill
from tables.models import Booking

from .common import ZERO, average, live_bills, section, to_bills


def customers(location, start, end):
    """Each customer (by mobile number) who ordered in the period: visits, spent, average, first and last visit,
    and whether they had ordered here before."""
    bills = live_bills(location, start, end).exclude(order__customer_phone="")
    grouped = list(bills.values("order__customer_phone").annotate(
        visits=Count("id"), spent=Sum("grand_total"), first=Min("bill_date"), last=Max("bill_date")).order_by("-spent"))
    names = dict(bills.order_by("created_at").values_list("order__customer_phone", "order__customer_name"))
    before = set(Bill.objects.filter(location=location, bill_date__lt=start, order__customer_phone__in=names)
                 .values_list("order__customer_phone", flat=True))
    rows = [[names.get(row["order__customer_phone"], ""), row["order__customer_phone"], row["visits"], row["spent"],
             average(row["spent"], row["visits"]), row["first"], row["last"],
             "Returning" if row["order__customer_phone"] in before else "New"] for row in grouped]
    totals = [f"{len(rows)} customers", "", sum(row[2] for row in rows), sum((row[3] for row in rows), ZERO),
              "", "", "", f"{sum(1 for row in rows if row[7] == 'Returning')} returning"]
    return [section([("Customer", "text"), ("Mobile", "text"), ("Visits", "int"), ("Spent", "money"),
                     ("Average bill", "money"), ("First visit", "date"), ("Last visit", "date"), ("Guest", "text")],
                    rows, totals, links=[to_bills(phone=row["order__customer_phone"]) for row in grouped])]


def bookings(location, start, end):
    """Every table booking for the period's days: when, how long, who, how many, which table, how it ended;
    then the count of each ending."""
    rows_qs = Booking.objects.filter(location=location, date__range=(start, end)).select_related("table").order_by(
        "date", "time")
    rows = [[booking.booking_no, booking.date, booking.time.strftime("%I:%M %p"), booking.length_text,
             booking.customer_name, booking.customer_phone, booking.guests, booking.table.name if booking.table else "—",
             booking.get_source_display(), booking.get_status_display()] for booking in rows_qs]
    endings = defaultdict(int)
    for row in rows:
        endings[row[9]] += 1
    summary = [[label, endings.get(label, 0)] for _, label in Booking.Status.choices]
    result = [section([("No.", "int"), ("Date", "date"), ("Time", "text"), ("Length", "text"), ("Guest", "text"),
                       ("Mobile", "text"), ("Guests", "int"), ("Table", "text"), ("Asked on", "text"),
                       ("Status", "text")],
                      rows, ["Total", "", "", "", "", "", sum(row[6] for row in rows), "", "", f"{len(rows)} bookings"])]
    if rows:
        result.append(section([("Status", "text"), ("Bookings", "int")], summary, ["Total", len(rows)],
                              title="How the bookings ended"))
    return result
