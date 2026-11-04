"""
Cafe profile > Locations (roles.COMPANY): the company's outlets.

  location_list   every location: its tables, staff and today's orders
  location_rows   HTMX: just the list, after a save
  location_add    side panel: a new location (it gets its own Takeaway counter by itself)
  location_edit   side panel: rename it, change its address, close or open it

A location is never deleted (its orders and bills stay in the records); closing
it stops its staff working there and its QR codes taking orders.
"""

from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from . import roles
from .decorators import role_required
from .forms import LocationForm
from .models import Location
from .pagination import paginate
from .utils import get_user_restaurant, htmx_saved, is_htmx


def locations_with_counts(request):
    today = timezone.localdate()
    return (Location.objects.filter(restaurant=get_user_restaurant(request))
            .annotate(table_count=Count("tables", filter=Q(tables__is_takeaway=False), distinct=True),
                      staff_count=Count("staff_members", distinct=True),
                      orders_today=Count("orders", filter=Q(orders__created_at__date=today), distinct=True)))


@role_required(*roles.COMPANY)
def location_list(request):
    locations, pager = paginate(locations_with_counts(request), request.GET)
    return render(request, "core/location_list.html", {"locations": locations, "pager": pager})


@role_required(*roles.COMPANY)
def location_rows(request):
    locations, pager = paginate(locations_with_counts(request), request.GET)
    return render(request, "core/_location_rows.html", {"locations": locations, "pager": pager})


@role_required(*roles.COMPANY)
def location_add(request):
    if not is_htmx(request):
        return redirect("core:location_list")
    restaurant = get_user_restaurant(request)
    restaurant.main_location()  # the first outlet keeps the existing records
    form = LocationForm(request.POST or None, restaurant=restaurant)
    if request.method == "POST" and form.is_valid():
        place = form.save(commit=False)
        place.restaurant = restaurant
        place.save()
        return htmx_saved(f"Location “{place.name}” added. Add its tables in Tables & QR after switching to it.")
    return render(request, "core/_location_form.html", {"form": form, "title": "Add location", "submit_label": "Add location"})


@role_required(*roles.COMPANY)
def location_edit(request, pk):
    if not is_htmx(request):
        return redirect("core:location_list")
    restaurant = get_user_restaurant(request)
    place = get_object_or_404(Location, pk=pk, restaurant=restaurant)
    form = LocationForm(request.POST or None, instance=place, restaurant=restaurant)
    if request.method == "POST" and form.is_valid():
        form.save()
        return htmx_saved(f"Location “{place.name}” saved.")
    return render(request, "core/_location_form.html", {"form": form, "title": f"Edit {place.name}", "submit_label": "Save changes"})
