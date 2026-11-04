"""
Home delivery screens (staff login). The steps themselves are in delivery.py.

  deliveries        the Deliveries board: To confirm, In the kitchen, Ready for a
                    rider, Out for delivery, Delivered today; cash with riders   DELIVERY_ROLES
  delivery_new      "New delivery" for a call or a walk-in: the order-taking
                    screen on the counter table, set to Delivery              ORDER_TAKER_ROLES
  delivery_step     HTMX: confirm, rider, pickup, deliver (then redraws the screen)
  delivery_reject   side panel: reject a to-confirm order, with a reason       DELIVERY_ROLES
  rider_home        the rider's own deliveries: call, map, picked up, collect  RIDER
"""

import json
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db.models import Q, Sum
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from billing.models import Bill, Payment
from core import roles
from core.analytics import period_filter_context
from core.decorators import role_required
from core.models import Staff
from core.utils import get_user_location, get_user_restaurant, is_htmx
from tables.models import takeaway_table

from .delivery import (
    RIDER_PAYMENT_MODES, assign_rider, confirm_delivery, deliver, pick_up, ride_times, rider_cash_today, riders_of,
)
from .forms import OrderCancelForm
from .models import KOT, Order
from .services import DeliveryError, cancel_order, order_total

DELIVERY_ROLES = roles.DELIVERIES
ORDER_TAKER_ROLES = roles.COUNTER_ORDERS  # a delivery is a counter order
BILLING_ROLES = roles.BILLING


def toast(response, text, level="success"):
    response["HX-Trigger"] = json.dumps({"showMessage": {"text": text, "level": level}})
    return response


def delivery_orders(location, rider=None):
    """The location's deliveries still going on, plus those delivered today, each
    with what the cards need: amount, kitchen state, bill, amount to collect, minutes."""
    today = timezone.localdate()
    orders = (
        Order.objects.filter(location=location, order_type=Order.OrderType.DELIVERY)
        .exclude(status=Order.Status.CANCELLED)
        .filter(Q(delivered_at__isnull=True) | Q(delivered_at__date=today))
        .select_related("rider").prefetch_related("kots__items").order_by("created_at")
    )
    if rider is not None:
        orders = orders.filter(rider=rider)
    bills = {bill.order_id: bill for bill in Bill.objects.filter(
        order__in=orders).exclude(status=Bill.Status.CANCELLED)}
    now = timezone.now()
    result = []
    for order in orders:
        kots = [kot for kot in order.kots.all() if kot.status != KOT.Status.CANCELLED]
        order.amount = order_total(kots)
        order.cooking = any(kot.status in (KOT.Status.NEW, KOT.Status.PREPARING) for kot in kots)
        order.bill_row = bills.get(order.pk)
        order.to_collect = order.bill_row.balance if order.bill_row else None
        order.minutes = int((now - order.created_at).total_seconds() // 60)
        order.items_text = ", ".join(f"{line.qty} × {line.item_name}" for kot in kots for line in kot.items.all()
                                     if not line.is_cancelled)
        result.append(order)
    return result


def board_context(request):
    """The Deliveries board: four working columns, then today's delivered list and
    the cash each rider holds."""
    staff = request.user.staff
    restaurant, place = staff.restaurant, get_user_location(request)
    orders = delivery_orders(place)
    columns = [
        {"key": "confirm", "title": "To confirm", "icon": "telephone", "orders": [o for o in orders if o.is_pending]},
        {"key": "kitchen", "title": "In the kitchen", "icon": "fire",
         "orders": [o for o in orders if not o.is_pending and not o.picked_up_at and o.cooking]},
        {"key": "ready", "title": "Ready for a rider", "icon": "bag-check",
         "orders": [o for o in orders if not o.is_pending and not o.picked_up_at and not o.cooking]},
        {"key": "out", "title": "Out for delivery", "icon": "bicycle",
         "orders": [o for o in orders if o.picked_up_at and not o.delivered_at]},
    ]
    delivered = [o for o in orders if o.delivered_at]
    return {
        "columns": columns,
        "delivered": delivered,
        "rides": ride_times(delivered),  # pickup -> door, today: overall and each rider's
        "riders": riders_of(place),
        "rider_cash": rider_cash_today(place),
        "can_bill": staff.role in BILLING_ROLES,
        "can_take_order": staff.role in ORDER_TAKER_ROLES,
        "delivery_enabled": restaurant.delivery_enabled,
        "payment_modes": [(mode, Payment.Mode(mode).label) for mode in RIDER_PAYMENT_MODES],
    }


@role_required(*DELIVERY_ROLES)
def deliveries(request):
    """Deliveries board. Refreshes every 15 seconds (not while a rider list is open)."""
    template = "orders/_delivery_board.html" if is_htmx(request) else "orders/deliveries.html"
    return render(request, template, board_context(request))


@role_required(*ORDER_TAKER_ROLES)
def delivery_new(request):
    """"New delivery" (a customer calls or walks in): the order screen on the counter table, set to Delivery."""
    restaurant = get_user_restaurant(request)
    counter = takeaway_table(restaurant, get_user_location(request))
    if not restaurant.delivery_enabled or not counter.is_active:
        messages.warning(request, "Deliveries are switched off. Switch them on in Restaurant settings "
                                  "(and keep the Takeaway table on in Tables & QR).")
        return redirect("orders:deliveries")
    return redirect(reverse("orders:waiter_order", args=[counter.pk]) + "?type=DELIVERY")


def period_words(period):
    """The period in a heading: "today", "this week", "this month", "21 Oct" or "1 Oct – 24 Oct"."""
    words = {"today": "today", "week": "this week", "month": "this month"}
    if period["when"] in words:
        return words[period["when"]]
    if period["start"] == period["end"]:
        return f"{period['start']:%d %b}"
    return f"{period['start']:%d %b} – {period['end']:%d %b}"


def rider_context(request):
    """The rider's own deliveries: on the way first, then ready to take (always);
    below, those delivered in the period picked in the filter row (Today by
    default, This week, This month, Range: core/analytics.py), with what was
    collected. A button's POST brings the period along (hx-include of the filter row)."""
    staff, place = request.user.staff, get_user_location(request)
    params = request.GET if "when" in request.GET else request.POST
    period = period_filter_context(params, timezone.localdate())
    mine = [o for o in delivery_orders(place, rider=staff) if o.delivered_at is None]
    mine.sort(key=lambda o: (o.picked_up_at is None, o.created_at))
    done = list(
        Order.objects.filter(location=place, order_type=Order.OrderType.DELIVERY, rider=staff,
                             delivered_at__date__range=(period["start"], period["end"]))
        .select_related("bill", "rider").order_by("-delivered_at")
    )
    taken = Payment.objects.filter(location=place, received_by=staff,
                                   created_at__date__range=(period["start"], period["end"]))
    cash = next((row for row in rider_cash_today(place) if row["rider"].pk == staff.pk), None)
    return {
        **period,
        "period_text": period_words(period),
        "active": mine,
        "done": done,
        "rides": ride_times(done)["all"],  # my average, fastest and slowest ride in the period
        "collected": taken.aggregate(total=Sum("amount"))["total"] or Decimal("0.00"),
        "cash_today": cash["amount"] if cash else Decimal("0.00"),
        "payment_modes": [(mode, Payment.Mode(mode).label) for mode in RIDER_PAYMENT_MODES],
    }


@role_required(*roles.RIDING)
def rider_home(request):
    """Rider: my deliveries, with tap-to-call, the map, Picked up and Delivered; those
    delivered in the period picked (?when=today|week|month|range). Refreshes every 15s."""
    template = "orders/_rider_board.html" if is_htmx(request) else "orders/rider_home.html"
    return render(request, template, rider_context(request))


STEP_DONE = {
    "confirm": "Order #{no} confirmed and sent to the kitchen.",
    "rider": "Order #{no} given to {rider}.",
    "pickup": "Order #{no} is out for delivery.",
    "deliver": "Order #{no} delivered and paid.",
}


def read_amount(text):
    """"200" or "199.50" -> Decimal; empty or not a number -> None (no split)."""
    try:
        return Decimal(str(text).strip()).quantize(Decimal("0.01")) if text and str(text).strip() else None
    except InvalidOperation:
        return None


@require_POST
@role_required(*DELIVERY_ROLES, *roles.RIDING)
def delivery_step(request, order_id, step):
    """HTMX: one delivery step, then the screen it came from again (screen=board | rider).

    A rider may only move their own deliveries (picked up, delivered).
    """
    if step not in STEP_DONE:
        return HttpResponseBadRequest("Unknown step.")
    staff = request.user.staff
    order = get_object_or_404(Order, pk=order_id, location=get_user_location(request),
                              order_type=Order.OrderType.DELIVERY)
    is_rider = staff.role == Staff.Role.RIDER
    if is_rider and (step in ("confirm", "rider") or order.rider_id != staff.pk):
        return HttpResponseBadRequest("Not your delivery.")

    try:
        if step == "confirm":
            confirm_delivery(order)
        elif step == "rider":
            rider = get_object_or_404(Staff, pk=request.POST.get("rider") or 0, restaurant=staff.restaurant)
            order = assign_rider(order, rider)
        elif step == "pickup":
            pick_up(order, staff)
        elif step == "deliver":
            deliver(order, staff, request.POST.get("mode", Payment.Mode.CASH), request.POST.get("reference", ""),
                    first_amount=read_amount(request.POST.get("first_amount")),
                    second_mode=request.POST.get("second_mode") or None)
        order.refresh_from_db()
        text = STEP_DONE[step].format(no=order.order_no, rider=order.rider.name if order.rider else "")
        level = "success"
    except DeliveryError as problem:
        text, level = str(problem), "warning"

    if request.POST.get("screen") == "rider":
        response = render(request, "orders/_rider_board.html", rider_context(request))
    else:
        response = render(request, "orders/_delivery_board.html", board_context(request))
    return toast(response, text, level)


@role_required(*DELIVERY_ROLES)
def delivery_reject(request, order_id):
    """Side panel: reject a delivery that is still to be confirmed (a wrong or fake order)."""
    order = get_object_or_404(Order, pk=order_id, location=get_user_location(request),
                              order_type=Order.OrderType.DELIVERY)
    if not is_htmx(request):
        return redirect("orders:deliveries")
    blocked = "" if order.is_pending else f"Order #{order.order_no} is already confirmed. Cancel it from its order page."
    form = OrderCancelForm(request.POST or None)
    form.fields["reason"].widget.attrs["placeholder"] = "e.g. no answer on the phone, outside our delivery area"
    if request.method == "POST" and not blocked and form.is_valid():
        cancel_order(order, form.cleaned_data["reason"])
        response = HttpResponse(status=204)
        response["HX-Trigger"] = json.dumps({
            "closePanel": True, "rowsChanged": True,
            "showMessage": {"text": f"Order #{order.order_no} rejected.", "level": "success"},
        })
        return response
    return render(request, "orders/_order_cancel_form.html", {
        "form": form, "order": order, "blocked": blocked,
        "title": f"Reject delivery #{order.order_no}", "submit_label": "Reject order",
    })
