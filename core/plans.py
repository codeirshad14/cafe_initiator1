"""
Membership types (Restaurant.tier): what a cafe may use. We set it in the Django admin,
next to the billing period (monthly / yearly), the membership dates and the logins allowed.

  Only Menu    the cafe profile and the menu: categories, dishes and the view-only menu QR.
               Guests can look at the menu, not order or book. Every other screen: "Upgrade".
  Basic        every app; 10,000 bills a membership year; 1 location
  Standard     every app; 50,000 bills a membership year; 1 location
  Enterprise   every app; 50,00,000 bills a membership year; up to 20 locations
  Ultimate     every app, no limits

A membership year is 12 months from the day the membership started, then again from
each anniversary (Restaurant.plan_year). Cancelled bills do not count. Once a year's
bills are used, "Make bill" says to upgrade (billing.services.make_bill); adding or
reopening a location past the plan's number does too (core.forms.LocationForm).
"""

MENU, BASIC, STANDARD, ENTERPRISE, ULTIMATE = "MENU", "BASIC", "STANDARD", "ENTERPRISE", "ULTIMATE"

TIER_CHOICES = [
    (MENU, "Only Menu"),
    (BASIC, "Basic"),
    (STANDARD, "Standard"),
    (ENTERPRISE, "Enterprise"),
    (ULTIMATE, "Ultimate"),
]

# bills a membership year, open locations; None = no limit
LIMITS = {
    MENU: {"bills": 0, "locations": 1},
    BASIC: {"bills": 10_000, "locations": 1},
    STANDARD: {"bills": 50_000, "locations": 1},
    ENTERPRISE: {"bills": 5_000_000, "locations": 20},
    ULTIMATE: {"bills": None, "locations": None},
}

# The screens of an Only Menu cafe (view names; each covers the names that start with it):
# the start page, the cafe profile and staff logins, the menu, the menu's QR code, and the
# cafe's own website with its feedback.
MENU_ONLY_VIEWS = (
    "core:home", "core:live", "core:switch_location", "core:restaurant_settings", "core:staff",
    "menu:", "tables:table_list", "tables:menu_qr", "tables:qr_sheet", "orders:notification",
    "web:website_settings", "web:feedback",
)

NEAR_LIMIT = 0.9  # from 90% of the year's bills used, the Bills page warns


def menu_only_allows(view_name):
    """True when an Only Menu cafe has this screen."""
    return view_name.startswith(MENU_ONLY_VIEWS)
