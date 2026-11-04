from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django import template

register = template.Library()


def indian_grouping(whole):
    """'1234567' -> '12,34,567' (last three digits, then groups of two)."""
    if len(whole) <= 3:
        return whole
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups) + "," + tail


@register.filter
def inr(value):
    """Show an amount in rupees: {{ item.price|inr }} -> ₹1,24,536.50"""
    if value is None or value == "":
        return ""
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return value
    sign = "-" if amount < 0 else ""
    whole, paise = f"{abs(amount):.2f}".split(".")
    return f"{sign}₹{indian_grouping(whole)}.{paise}"


@register.filter
def indian(value):
    """A count with Indian grouping: {{ 5000000|indian }} -> 50,00,000"""
    try:
        return indian_grouping(str(int(value)))
    except (TypeError, ValueError):
        return value


@register.filter
def percent(value):
    """A rate without useless zeros: 5.00 -> 5, 2.50 -> 2.5, 18 -> 18 (add the % sign yourself)."""
    try:
        number = Decimal(str(value)).normalize()
    except InvalidOperation:
        return value
    return f"{number:f}"


@register.filter
def inr_short(value):
    """Like inr, without ".00" for whole rupees (customer menu): ₹249, ₹249.50"""
    text = inr(value)
    return text[:-3] if text.endswith(".00") else text


@register.filter
def duration(minutes):
    """A waiting time that stays short on a tile: 45 -> "45 min", 80 -> "1 h 20 min",
    600 and more -> "10 h" (minutes no longer matter then)."""
    try:
        minutes = max(0, int(minutes or 0))  # nothing yet (e.g. not ready) counts as 0
    except (TypeError, ValueError):
        return minutes
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    if hours >= 10 or rest == 0:
        return f"{hours} h"
    return f"{hours} h {rest} min"
