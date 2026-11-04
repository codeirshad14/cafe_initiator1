import json
import re

from django.core.exceptions import ValidationError
from django.db.models import Max, ProtectedError
from django.http import HttpResponse
from django.shortcuts import render

from .models import Location


def get_user_restaurant(request):
    """Return the restaurant (company) of the logged-in staff user: its menu, settings, staff."""
    return request.user.staff.restaurant


def get_user_location(request):
    """The location the logged-in staff user works at now: its tables, orders, KOTs, bills
    and bookings (core/locations.py)."""
    from .locations import current_location
    return current_location(request)


def next_number(model, location, field):
    """Next running number at this location (orders, KOTs, bills and bookings
    count per outlet). Call inside transaction.atomic()."""
    Location.objects.select_for_update().get(pk=location.pk)  # lock
    last = model.objects.filter(location=location).aggregate(m=Max(field))["m"]
    return (last or 0) + 1


def htmx_saved(message):
    """Answer a successful HTMX form save.

    No page content (204). The HX-Trigger header tells the page to close the
    side panel, reload the list rows and show a green message (static/js/app.js).
    """
    response = HttpResponse(status=204)
    response["HX-Trigger"] = json.dumps({
        "closePanel": True,
        "rowsChanged": True,
        "showMessage": {"text": message, "level": "success"},
    })
    return response


def clean_indian_mobile(value):
    """Accept 98765 43210, +91 9876543210, 09876543210 ... and return the 10 digits.

    Empty stays empty. Anything else raises ValidationError (for form clean_ methods).
    """
    phone = re.sub(r"[\s\-]", "", value or "")
    if not phone:
        return ""
    phone = re.sub(r"^(\+91|91|0)(?=\d{10}$)", "", phone)
    if not re.fullmatch(r"[6-9]\d{9}", phone):
        raise ValidationError("Please enter a valid 10-digit mobile number.")
    return phone


def report_back(value):
    """?back=: the report a drilled-down page (another report, a bill) was opened from.
    Only a report's own address is taken, never a link to anywhere else."""
    value = value or ""
    return value if value.startswith("/reports/") and "//" not in value and "\\" not in value else ""


def is_htmx(request):
    """True when the request was sent by HTMX (not a normal page load)."""
    return request.headers.get("HX-Request") == "true"


def delete_with_confirm(request, obj, what, blocked_hint):
    """The shared delete flow inside the side panel.

    GET  -> "Delete this?" with a Delete button.
    POST -> delete it, or, when other rows still use it (on_delete=PROTECT),
            explain why it cannot go, using blocked_hint.
    `what` names the kind of thing, e.g. "Category".
    """
    context = {"obj": obj, "what": what, "blocked": None}
    if request.method == "POST":
        name = str(obj)
        try:
            obj.delete()
        except ProtectedError:
            context["blocked"] = blocked_hint
        else:
            return htmx_saved(f"{what} “{name}” deleted.")
    return render(request, "partials/_confirm_delete.html", context)
