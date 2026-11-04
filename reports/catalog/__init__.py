"""
The reports, grouped as the Reports page shows them. Each report is a function
of (location, start, end) returning its sections (catalog/common.py); the
group modules hold them: sales, menu, operations, guests, team, audit.

REPORTS   {slug: {"title", "icon", "group", "about", "function", "filters"}} in page order
GROUPS    [(group title, [slug, ...]), ...]
FILTERS   what a report can be narrowed to when another report's row opens it
          (?type=DINE_IN): passed to its function as keyword arguments
"""

from . import audit, guests, menu, operations, sales, team

_GROUPS = [
    ("Sales", [
        ("daily-sales", "Daily sales summary", "calendar3", sales.daily_sales),
        ("monthly-sales", "Month-wise sales", "calendar-month", sales.monthly_sales),
        ("hourly-sales", "Hour-wise sales", "clock", sales.hourly_sales),
        ("order-types", "Dine in, takeaway & delivery", "bag-check", sales.order_types),
        ("payment-modes", "Payment modes", "wallet2", sales.payment_modes),
        ("gst-summary", "GST summary", "percent", sales.gst_summary),
        ("discounts", "Discount register", "tag", sales.discount_register),
        ("bill-register", "Bill register", "receipt", sales.bill_register),
        ("payment-register", "Payment register", "credit-card", sales.payment_register),
    ]),
    ("Menu", [
        ("item-sales", "Item-wise sales", "journal-text", menu.item_sales),
        ("category-sales", "Category-wise sales", "tags", menu.category_sales),
        ("slow-items", "Slow & not-sold items", "hourglass-bottom", menu.slow_items),
    ]),
    ("Operations", [
        ("kot-register", "KOT register", "fire", operations.kot_register),
        ("kitchen-performance", "Kitchen performance", "speedometer", operations.kitchen_performance),
        ("table-sales", "Table-wise sales", "grid-3x3-gap", operations.table_sales),
        ("delivery-register", "Delivery register", "bicycle", operations.delivery_register),
        ("rider-performance", "Rider performance", "stopwatch", operations.rider_performance),
    ]),
    ("Guests", [
        ("customers", "Customers", "person-lines-fill", guests.customers),
        ("bookings", "Table bookings", "calendar-check", guests.bookings),
    ]),
    ("Team", [
        ("waiter-sales", "Waiter-wise sales", "person-badge", team.waiter_sales),
        ("staff-collections", "Staff collections", "cash-coin", team.staff_collections),
    ]),
    ("Audit", [
        ("cancelled", "Cancelled KOTs, bills & orders", "x-octagon", audit.cancelled),
        ("offers", "Offers & discounts used", "stars", audit.offers_used),
    ]),
]

FILTERS = {
    "bill-register": ("type", "hour", "table", "waiter", "phone", "item", "dish", "gst", "live"),
    "payment-register": ("mode", "staff"),
    "item-sales": ("category",),
    "discounts": ("offer",),
    "delivery-register": ("rider",),
}

REPORTS = {
    slug: {"title": title, "icon": icon, "group": group, "function": function,
           "about": (function.__doc__ or "").strip().split("\n")[0], "filters": FILTERS.get(slug, ())}
    for group, entries in _GROUPS for slug, title, icon, function in entries
}
GROUPS = [(group, [slug for slug, *_ in entries]) for group, entries in _GROUPS]
