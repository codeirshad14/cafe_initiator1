"""
The bell in the top bar (every staff page) for this location:
"New order" (made with each new order: orders.services.place_kot) and, for the Floor
roles, a guest's call from their table's bell (orders.services.call_waiter): "Table T4:
Water please", with a soft sound once (static/js/app.js part 11).

  notification_bell      the bell, its count of unread and the list (HTMX; it redraws
                         itself when anything changes: core/live.py)
  notification_open      open one: marked read for everyone, then its order's page
                         (a call: its table on the Floor)
  notification_read_all  Mark all as read (for everyone)
"""

from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core import roles
from core.decorators import role_required
from core.live import bump
from core.navigation import first_page_for
from core.utils import get_user_location

from .models import Notification

SHOWN = 20  # the newest unread ones in the list; the count says how many in all


def hears_calls(staff):
    """Guests' calls go to whoever serves the tables (the Floor roles), not the kitchen or riders."""
    return staff.role in roles.FLOOR


def unread(request):
    waiting = Notification.objects.filter(location=get_user_location(request), read_at__isnull=True)
    if not hears_calls(request.user.staff):
        waiting = waiting.exclude(kind=Notification.Kind.CALL)
    return waiting


def bell(request):
    waiting = unread(request)
    notes = list(waiting.select_related("order__table", "order__waiter", "table")[:SHOWN])
    now = timezone.now()
    for note in notes:  # "Just now", "5 min ago", "1 h 20 min ago"
        note.minutes = int((now - note.created_at).total_seconds() // 60)
    count = waiting.count()
    # the newest call: static/js/app.js rings once when its number is new on this device
    latest_call = next((note for note in notes if note.is_call), None)
    return render(request, "orders/_notification_bell.html", {
        "notifications": notes, "unread_count": count, "more": count - len(notes), "latest_call": latest_call,
    })


def order_page(order, staff):
    """Where opening a notification goes, for this person's role."""
    if order.is_pending and staff.role in roles.DELIVERIES:
        return reverse("orders:deliveries")  # to confirm on the phone first
    if staff.role in roles.FLOOR:
        return reverse("orders:floor_order", args=[order.pk])
    if staff.role in roles.KITCHEN_BOARD:
        return reverse("orders:kitchen")
    if staff.role in roles.RIDING:
        return reverse("orders:rider_home")
    return first_page_for(staff.role, staff.restaurant.menu_only) or reverse("core:home")


@role_required()
def notification_bell(request):
    return bell(request)


@require_POST
@role_required()
def notification_open(request, pk):
    note = get_object_or_404(unread_or_read(request).select_related("order", "table"), pk=pk)
    if note.read_at is None:
        note.read_at, note.read_by = timezone.now(), request.user.staff
        note.save(update_fields=["read_at", "read_by"])
        bump(note.restaurant_id)  # the other bells drop it at once
    if note.is_call:  # going to the table that called
        return redirect("orders:floor_table", table_id=note.table_id)
    return redirect(order_page(note.order, request.user.staff))


def unread_or_read(request):
    """This location's notes this person may open (a call: only the Floor roles)."""
    notes = Notification.objects.filter(location=get_user_location(request))
    if not hears_calls(request.user.staff):
        notes = notes.exclude(kind=Notification.Kind.CALL)
    return notes


@require_POST
@role_required()
def notification_read_all(request):
    if unread(request).update(read_at=timezone.now(), read_by=request.user.staff):
        bump(request.user.staff.restaurant_id)
    return bell(request)
