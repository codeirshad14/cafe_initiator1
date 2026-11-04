"""
The location (outlet) a staff member is working at right now.

Admin and manager may work at every location; others at those they are mapped
to (Staff.locations), or the main one. With more than one, the top bar shows a
switcher; the choice is kept in the session. Every staff screen shows and
makes the orders, KOTs, bills and bookings of this location only.
"""

from django.contrib import messages
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .decorators import role_required

SESSION_KEY = "location_id"


def current_location(request):
    """This request's location (looked up once per request)."""
    if not hasattr(request, "_location"):
        allowed = request.user.staff.allowed_locations()
        wanted = request.session.get(SESSION_KEY)
        request._location = next((place for place in allowed if place.pk == wanted), allowed[0])
    return request._location


def location_from_link(restaurant, request):
    """A public page's location (menu, booking): ?at=<id> when it is one of the
    company's open locations, else the main one."""
    wanted = request.GET.get("at", "")
    if wanted.isdigit():
        place = restaurant.locations.filter(pk=wanted, is_active=True).first()
        if place:
            return place
    return restaurant.main_location()


@require_POST
@role_required()
def switch_location(request):
    """The top bar's switcher: work at another of my locations."""
    wanted = int(request.POST.get("location") or 0)
    place = next((place for place in request.user.staff.allowed_locations() if place.pk == wanted), None)
    if place:
        request.session[SESSION_KEY] = place.pk
        messages.success(request, f"Now working at {place.name}.")
    back = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()}):
        back = "core:home"
    return redirect(back)
