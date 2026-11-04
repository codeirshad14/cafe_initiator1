"""
The staff sidebar: every link, its icon and the roles that may see it.

A link whose page does not exist yet (its URL name cannot be found) shows
as "Soon" and lights up by itself once the phase that builds it lands.
Icons are Bootstrap Icons names: https://icons.getbootstrap.com
"""

from django.urls import NoReverseMatch, reverse

from . import roles
from .plans import menu_only_allows

# "match" marks the link active for every page whose view name starts with
# it, e.g. "core:staff" covers the staff list and its add / edit forms.
# A tuple of several beginnings works too. Who sees a link: core/roles.py.
NAV_SECTIONS = [
    {
        "title": "Overview",
        "links": [
            {"label": "Dashboard", "icon": "speedometer2", "url_name": "core:dashboard",
             "match": "core:dashboard", "roles": roles.DASHBOARD},
        ],
    },
    {
        "title": "Service",
        "links": [
            {"label": "Floor", "icon": "grid-3x3-gap", "url_name": "orders:floor",
             "match": ("orders:floor", "orders:waiter_order", "orders:waiter_takeaway", "orders:order_cancel"),
             "roles": roles.FLOOR},
            {"label": "Kitchen", "icon": "fire", "url_name": "orders:kitchen",
             "match": "orders:kitchen", "roles": roles.KITCHEN_BOARD},
            {"label": "Ready to serve", "icon": "bell", "url_name": "orders:waiter_ready",
             "match": "orders:waiter_ready", "roles": roles.READY_LIST},
            {"label": "Deliveries", "icon": "bicycle", "url_name": "orders:deliveries",
             "match": ("orders:deliveries", "orders:delivery"), "roles": roles.DELIVERIES},
            {"label": "Bookings", "icon": "calendar-check", "url_name": "tables:booking_list",
             "match": "tables:booking", "roles": roles.BOOKINGS},
            {"label": "My deliveries", "icon": "bicycle", "url_name": "orders:rider_home",
             "match": "orders:rider", "roles": roles.RIDING},
        ],
    },
    {
        "title": "Billing",
        "links": [
            {"label": "Bills", "icon": "receipt", "url_name": "billing:bill_list",
             "match": ("billing:bill", "billing:payment"), "roles": roles.BILL_VIEW},
        ],
    },
    {
        "title": "Setup",
        "links": [
            {"label": "Menu items", "icon": "journal-text", "url_name": "menu:menu_item_list",
             "match": "menu:menu_item", "roles": roles.MENU_SETUP},
            {"label": "Categories", "icon": "tags", "url_name": "menu:category_list",
             "match": "menu:category", "roles": roles.MENU_SETUP},
            {"label": "Tables & QR", "icon": "qr-code", "url_name": "tables:table_list",
             "match": ("tables:table", "tables:qr", "tables:menu_qr"), "roles": roles.MENU_SETUP},
            # Cafe profile and Staff are in the account menu, top right (partials/_topbar.html)
        ],
    },
    {
        "title": "Insights",
        "links": [
            {"label": "Reports", "icon": "bar-chart-line", "url_name": "reports:index",
             "match": "reports:", "roles": roles.REPORTS},
        ],
    },
]


# Phones and tablets: the bottom bar, like an app. Each role gets the first
# four of these it may see (in this order), then "More" for the whole menu.
BOTTOM_NAV_ORDER = [
    "core:dashboard", "orders:floor", "orders:waiter_ready", "orders:kitchen", "orders:rider_home",
    "billing:bill_list", "orders:deliveries", "tables:booking_list",
]
BOTTOM_NAV_SIZE = 4
# the bottom bar has little room: shorter names there
SHORT_LABELS = {"Ready to serve": "Ready", "My deliveries": "Deliveries"}


def link_url(url_name):
    """The link's address, or None while its page is not built yet."""
    try:
        return reverse(url_name)
    except NoReverseMatch:
        return None


def build_nav(role, current_view, menu_only=False):
    """The sidebar sections this role may see, each link with url and active flag.
    menu_only: an Only Menu cafe sees its menu screens only (core/plans.py)."""
    sections = []
    for section in NAV_SECTIONS:
        links = []
        for link in section["links"]:
            if role not in link["roles"] or (menu_only and not menu_only_allows(link["url_name"])):
                continue
            links.append({
                "label": link["label"],
                "short": SHORT_LABELS.get(link["label"], link["label"]),
                "icon": link["icon"],
                "url_name": link["url_name"],
                "url": link_url(link["url_name"]),
                "is_active": current_view.startswith(link["match"]),
            })
        if links:
            sections.append({"title": section["title"], "links": links})
    return sections


def build_bottom_nav(sections):
    """The bottom bar (phones, tablets): up to four of the role's main pages, from its sidebar."""
    links = {link["url_name"]: link for section in sections for link in section["links"] if link["url"]}
    return [links[name] for name in BOTTOM_NAV_ORDER if name in links][:BOTTOM_NAV_SIZE]


def first_page_for(role, menu_only=False):
    """URL of the first built page in this role's sidebar, or None."""
    for section in build_nav(role, "", menu_only):
        for link in section["links"]:
            if link["url"]:
                return link["url"]
    return None
