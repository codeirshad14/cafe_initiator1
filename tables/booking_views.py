"""
Table bookings.

Guest (no login), from the public menu:
  public_booking   /r/<slug>/book/         the booking form; it starts as Requested
  booking_status   /booking/<token>/       the guest's own page: Requested / Confirmed / ...

Staff (BOOKING_ROLES), /tables/bookings/:
  booking_list     the days picked (Today, This week, ...) date by date, and every request still to confirm
  booking_arrive   side panel from the Floor's red table: "Guests arrived" seats them, then their order
  booking_add      side panel: a booking taken on the phone (Confirmed)
  booking_edit     side panel: change the time, guests or table
  booking_step     HTMX: confirm, seated, no-show
  booking_cancel   side panel: cancel with a reason
"""

import json

from django.contrib import messages
from django.db import transaction
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from core import roles
from core.decorators import role_required
from core.locations import location_from_link
from core.models import Restaurant
from core.utils import get_user_location, get_user_restaurant, htmx_saved, is_htmx, next_number

from .forms import BookingForm, StaffBookingForm
from .models import Booking
from .periods import booking_days, period_context

BOOKING_ROLES = roles.BOOKINGS
TABLE_ORDER_ROLES = roles.TABLE_ORDERS  # who takes table orders (orders.staff_views)


def save_booking(form, restaurant, location, source):
    """Save a new booking with the location's next booking number."""
    with transaction.atomic():
        booking = form.save(commit=False)
        booking.restaurant = restaurant
        booking.location = location
        booking.source = source
        booking.booking_no = next_number(Booking, location, "booking_no")
        booking.save()
    return booking


# ================================================================ guest

def public_booking(request, slug):
    """"Book a table" on the public menu (?at=<location> for a location other than
    the main one). Staff call to confirm, so the booking starts as Requested."""
    restaurant = Restaurant.objects.filter(slug=slug).first()
    if restaurant is None or not restaurant.takes_orders or not restaurant.booking_enabled:
        return render(request, "orders/customer_closed.html", {"public": True}, status=404)

    form = BookingForm(request.POST or None, restaurant=restaurant,
                       initial={"date": timezone.localdate(), "guests": 2,
                                "customer_name": request.session.get("customer_name", ""),
                                "customer_phone": request.session.get("customer_phone", "")})
    if request.method == "POST" and form.is_valid():
        booking = save_booking(form, restaurant, location_from_link(restaurant, request), Booking.Source.PUBLIC)
        request.session["customer_name"] = booking.customer_name
        request.session["customer_phone"] = booking.customer_phone
        return redirect("orders:booking_status", public_token=booking.public_token)
    return render(request, "tables/public_booking.html", {"restaurant": restaurant, "form": form})


def booking_status(request, public_token):
    """The guest's booking: what they asked for and where it stands. Refreshes while Requested."""
    booking = get_object_or_404(Booking.objects.select_related("restaurant", "table"), public_token=public_token)
    template = "tables/_booking_status.html" if is_htmx(request) else "tables/booking_status.html"
    return render(request, template, {"booking": booking, "restaurant": booking.restaurant})


# ================================================================ staff

def bookings_context(request):
    """The requests still to confirm (any day), and the bookings of the days picked
    in the filter row (?when=today|week|month|range, the same as the Floor's;
    Today by default), date by date with every status. A button's POST brings
    the period along (hx-include of the filter row)."""
    from orders.staff_views import floor_tables  # the tables' live state, for today's cards

    place = get_user_location(request)
    today = timezone.localdate()
    params = request.GET if "when" in request.GET else request.POST
    period = period_context(params, today)
    days = booking_days(place, period["start"], period["end"], floor_tables(place), today,
                        statuses=Booking.Status.values)
    return {
        **period,
        "summary_days": days,
        "summary_count": sum(len(day["bookings"]) for day in days),
        "summary_guests": sum(day["guests"] for day in days),
        "requests": list(Booking.objects.filter(location=place, status=Booking.Status.REQUESTED,
                                                date__gte=today).select_related("table").order_by("date", "time")),
    }


@role_required(*BOOKING_ROLES)
def booking_list(request):
    """Bookings: the days picked (Today by default) with Confirm / Seated / No-show / Cancel,
    and the requests to confirm."""
    template = "tables/_booking_rows.html" if is_htmx(request) else "tables/booking_list.html"
    return render(request, template, bookings_context(request))


@role_required(*BOOKING_ROLES)
def booking_arrive(request, pk):
    """Side panel, from the Floor's red (booked now) table: the booking, with "Guests arrived".

    POST: the booking is Seated. Staff who take table orders go straight on to
    the table's order screen; a cashier (counter orders only) sees the floor again.
    """
    if not is_htmx(request):
        return redirect("tables:booking_list")
    booking = get_object_or_404(Booking.objects.select_related("table"), pk=pk, location=get_user_location(request))
    can_take_order = request.user.staff.role in TABLE_ORDER_ROLES
    if request.method == "POST":
        if booking.is_upcoming:
            booking.status = Booking.Status.SEATED
            booking.save(update_fields=["status"])
        if can_take_order and booking.table_id:
            messages.success(request, f"{booking.customer_name} seated at {booking.table.label}. Take their order.")
            response = HttpResponse(status=204)
            response["HX-Redirect"] = reverse("orders:waiter_order", args=[booking.table_id])
            return response
        return htmx_saved(f"{booking.customer_name} seated{f' at {booking.table.label}' if booking.table_id else ''}.")
    return render(request, "tables/_booking_arrive.html", {"booking": booking, "can_take_order": can_take_order})


@role_required(*BOOKING_ROLES)
def booking_add(request):
    """Side panel: a booking taken on the phone. Confirmed straight away."""
    if not is_htmx(request):
        return redirect("tables:booking_list")
    restaurant, place = get_user_restaurant(request), get_user_location(request)
    # ?day= and ?table= fill those in (a free table's card in the floor's booking summary)
    form = StaffBookingForm(request.POST or None, restaurant=restaurant, location=place, initial={
        "date": request.GET.get("day") or timezone.localdate(), "guests": 2, "table": request.GET.get("table"),
    })
    if request.method == "POST" and form.is_valid():
        booking = save_booking(form, restaurant, place, Booking.Source.STAFF)
        return htmx_saved(f"Booking #{booking.booking_no} for {booking.customer_name} saved.")
    return render(request, "tables/_booking_form.html", {"form": form, "title": "New booking", "submit_label": "Save booking"})


@role_required(*BOOKING_ROLES)
def booking_edit(request, pk):
    """Side panel: change a booking's day, time, guests, table or status."""
    if not is_htmx(request):
        return redirect("tables:booking_list")
    place = get_user_location(request)
    booking = get_object_or_404(Booking, pk=pk, location=place)
    form = StaffBookingForm(request.POST or None, instance=booking, restaurant=place.restaurant, location=place)
    if request.method == "POST" and form.is_valid():
        form.save()
        return htmx_saved(f"Booking #{booking.booking_no} updated.")
    return render(request, "tables/_booking_form.html", {
        "form": form, "booking": booking, "title": f"Booking #{booking.booking_no}", "submit_label": "Save changes",
    })


# which status a button moves the booking to, from which statuses
BOOKING_STEPS = {
    "confirm": (Booking.Status.CONFIRMED, [Booking.Status.REQUESTED], "confirmed"),
    "seated": (Booking.Status.SEATED, [Booking.Status.REQUESTED, Booking.Status.CONFIRMED], "seated"),
    "noshow": (Booking.Status.NO_SHOW, [Booking.Status.REQUESTED, Booking.Status.CONFIRMED], "marked no-show"),
}


@role_required(*BOOKING_ROLES)
def booking_step(request, pk, step):
    """HTMX POST: Confirm, Seated or No-show, then the list again."""
    if request.method != "POST" or step not in BOOKING_STEPS:
        return HttpResponseBadRequest("Unknown step.")
    booking = get_object_or_404(Booking, pk=pk, location=get_user_location(request))
    new_status, allowed_from, done = BOOKING_STEPS[step]
    if booking.status in allowed_from:
        booking.status = new_status
        booking.save(update_fields=["status"])
        text, level = f"Booking #{booking.booking_no} ({booking.customer_name}) {done}.", "success"
    else:
        text, level = f"Booking #{booking.booking_no} is already {booking.get_status_display().lower()}.", "warning"
    response = render(request, "tables/_booking_rows.html", bookings_context(request))
    response["HX-Trigger"] = json.dumps({"showMessage": {"text": text, "level": level}})
    return response


@role_required(*BOOKING_ROLES)
def booking_cancel(request, pk):
    """Side panel: cancel a booking (the guest called, or a fake request), with a reason."""
    from orders.forms import OrderCancelForm

    if not is_htmx(request):
        return redirect("tables:booking_list")
    booking = get_object_or_404(Booking, pk=pk, location=get_user_location(request))
    blocked ="" if booking.is_upcoming else f"Booking #{booking.booking_no} is already {booking.get_status_display().lower()}."
    form = OrderCancelForm(request.POST or None)
    form.fields["reason"].widget.attrs["placeholder"] = "e.g. the guest called to cancel, no answer on the phone"
    if request.method == "POST" and not blocked and form.is_valid():
        booking.status = Booking.Status.CANCELLED
        booking.cancel_reason = form.cleaned_data["reason"]
        booking.save(update_fields=["status", "cancel_reason"])
        return htmx_saved(f"Booking #{booking.booking_no} cancelled.")
    return render(request, "tables/_booking_cancel.html", {
        "form": form, "booking": booking, "blocked": blocked,
        "title": f"Cancel booking #{booking.booking_no}", "submit_label": "Cancel booking",
    })
