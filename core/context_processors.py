from django.conf import settings

from .locations import current_location
from .navigation import build_bottom_nav, build_nav


def brand(request):
    """The product's name ("Mr Cafe") for every template: {{ brand_name }}. Set in settings.BRAND_NAME."""
    return {"brand_name": settings.BRAND_NAME}


def staff_context(request):
    """Give every template the logged-in staff, their restaurant, the location they
    work at now (and their other locations, for the top bar's switcher), their
    sidebar and (phones, tablets) their bottom bar.
    Nothing for a request stopped before the login is known (a wrong host name:
    the 400 page is drawn before the middleware sets request.user)."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    staff = getattr(user, "staff", None)
    if staff is None:
        return {}

    current_view = request.resolver_match.view_name if request.resolver_match else ""
    sections = build_nav(staff.role, current_view, staff.restaurant.menu_only)
    my_locations = staff.allowed_locations()
    return {
        "current_staff": staff,
        "current_restaurant": staff.restaurant,
        "current_location": current_location(request),
        "my_locations": my_locations if len(my_locations) > 1 else [],
        "nav_sections": sections,
        "bottom_nav": build_bottom_nav(sections),
    }
