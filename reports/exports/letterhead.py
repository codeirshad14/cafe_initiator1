"""
The top of every exported report (CSV and PDF) and of the printed page: the
company and cafe details, then which report, which period and which location.
Also how each kind of value is written out (exports have no ₹ sign: "Rs.").
"""

from datetime import date, datetime

from django.utils import timezone

from core.templatetags.money import indian_grouping, inr, percent


def letterhead(location):
    """{"name", "trade_name", "lines"}: the name on the bill, the cafe's own name when it
    differs, and the address, phone, GSTIN and FSSAI lines."""
    restaurant = location.restaurant
    lines = [line.strip() for line in restaurant.address.splitlines() if line.strip()]
    if restaurant.phone:
        lines.append(f"Phone: {restaurant.phone}")
    if restaurant.email:
        lines.append(f"Email: {restaurant.email}")
    tax = [f"GSTIN: {restaurant.gstin}" if restaurant.gstin else "", f"FSSAI: {restaurant.fssai_no}" if restaurant.fssai_no else ""]
    if any(tax):
        lines.append(" · ".join(part for part in tax if part))
    many_places = restaurant.locations.count() > 1
    return {
        "name": restaurant.bill_name,
        "trade_name": restaurant.name if restaurant.bill_name != restaurant.name else "",
        "location": location.name if many_places else "",
        "lines": lines,
    }


def period_text(start, end):
    if start == end:
        return start.strftime("%d %b %Y")
    return f"{start.strftime('%d %b %Y')} to {end.strftime('%d %b %Y')}"


def generated_text():
    return timezone.localtime().strftime("%d %b %Y, %I:%M %p")


def plain(value, kind):
    """A value for the CSV: numbers stay plain numbers (Excel adds them up), dates ISO."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return timezone.localtime(value).strftime("%Y-%m-%d %H:%M") if timezone.is_aware(value) else value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def shown(value, kind):
    """A value as people read it (the PDF): 1,24,536.50 · 12.5% · 24 Oct 2026 · 07:45 PM · 18 min."""
    if value is None:
        return "—"
    if isinstance(value, str):
        return value
    if kind == "money":
        return inr(value).replace("₹", "")
    if kind == "percent":
        return f"{percent(value)}%"
    if kind == "minutes":
        return f"{value} min"
    if kind == "datetime" and isinstance(value, datetime):
        return timezone.localtime(value).strftime("%d %b, %I:%M %p") if timezone.is_aware(value) else value.strftime("%d %b, %I:%M %p")
    if kind == "date" and isinstance(value, date):
        return value.strftime("%d %b %Y")
    if kind == "int":
        return indian_grouping(str(value))
    return str(value)
