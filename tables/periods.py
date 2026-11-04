"""
Which days' bookings a screen shows: the filter row on the Floor and on the
Bookings page (partials/_period_filter.html), and the date-wise cards under it.

    Today        today only (the default)
    This week    today to Sunday
    This month   today to the month's last day
    Range        two dates picked (never before today, at most 92 days)
"""

import calendar
from datetime import time, timedelta
from urllib.parse import urlencode

from django.utils.dateparse import parse_date

from .models import Booking

PERIODS = [("today", "Today"), ("week", "This week"), ("month", "This month"), ("range", "Range")]
MAX_RANGE_DAYS = 92


def read_date(text):
    """"2026-10-24" -> date, anything else -> None."""
    try:
        return parse_date(text or "")
    except ValueError:  # well formed but not a real day, e.g. 2026-02-30
        return None


def booking_period(params, today):
    """(when, first day, last day) from ?when= (&from= &to=); Today by default."""
    when = params.get("when", "today")
    if when == "week":
        return when, today, today + timedelta(days=6 - today.weekday())
    if when == "month":
        return when, today, today.replace(day=calendar.monthrange(today.year, today.month)[1])
    if when == "range":
        start = max(read_date(params.get("from")) or today, today)
        end = max(read_date(params.get("to")) or start, start)
        return when, start, min(end, start + timedelta(days=MAX_RANGE_DAYS))
    return "today", today, today


def period_context(params, today):
    """What the filter row and the live block need: the period, its days and the query to ask again with."""
    when, start, end = booking_period(params, today)
    filters = {"when": when}
    if when == "range":
        filters.update({"from": start.isoformat(), "to": end.isoformat()})
    return {
        "periods": PERIODS, "when": when, "start": start, "end": end,
        "today": today, "tomorrow": today + timedelta(days=1), "filter_query": urlencode(filters),
    }


def booking_days(location, start, end, tables, today, statuses=None):
    """The location's bookings from start to end, date by date: [{"date", "bookings", "guests", "tables"}].

    A booking is listed on every day it covers (a two-day wedding: both days).
    statuses: which bookings to list (default: still to come, and seated).
    tables: every dining table, with its live state for today (orders.staff_views.floor_tables);
    each day lists them like the floor's tiles: booked that day (red) or free (green),
    and today also occupied / bill printed.
    """
    statuses = statuses or Booking.UPCOMING + [Booking.Status.SEATED]
    bookings = Booking.objects.filter(
        location=location, date__lte=end, end_date__gte=start, status__in=statuses,
    ).select_related("table").order_by("date", "time")
    by_day = {}
    for booking in bookings:
        last = booking.end_date
        if booking.is_multi_day and booking.end_time == time(0, 0):
            last -= timedelta(days=1)  # ends at midnight: the next day is not part of it
        day = max(booking.date, start)
        while day <= min(last, end):
            by_day.setdefault(day, []).append(booking)
            day += timedelta(days=1)
    days = []
    for day in sorted(by_day):
        items = by_day[day]
        days.append({"date": day, "bookings": items,
                     "guests": sum(b.guests for b in items if b.status != Booking.Status.CANCELLED)})

    for day in days:
        booked = {}  # table -> its bookings still to come that day, earliest first
        for booking in day["bookings"]:
            if booking.table_id and booking.is_upcoming:
                booked.setdefault(booking.table_id, []).append(booking)
        day["tables"] = []
        for table in tables:
            bookings = booked.get(table.pk, [])
            if day["date"] == today and table.running:
                state = table.state  # guests are eating: occupied or bill printed
            else:
                state = "booked" if bookings else "free"
            day["tables"].append({
                "table": table, "state": state,
                "booking": bookings[0] if bookings else None,
                "more": len(bookings) - 1 if bookings else 0,  # "+1": more bookings that day
            })
    return days
