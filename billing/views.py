import json
from decimal import Decimal

from django.contrib import messages
from django.db.models import Count, Q, Sum
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core import roles
from core.decorators import role_required
from core.pagination import paginate
from core.templatetags.money import inr
from core.utils import get_user_location, get_user_restaurant, is_htmx, report_back
from orders.models import KOT, Order
from orders.services import order_total
from orders.staff_views import render_pos
from tables.models import takeaway_table

from .forms import BillCancelForm, BillFilterForm, DiscountForm, PaymentForm
from .models import Bill, Payment
from .printing import bill_slip
from .upi import bill_upi_png
from .services import (
    BillingError, add_payments, cancel_bill, make_bill, offer_for, preview_totals, remove_payment, reopen_order,
)

BILLING_ROLES = roles.BILLING


def toast(response, text, level="success"):
    """Add a message to an HTMX response (static/js/app.js shows it)."""
    response["HX-Trigger"] = json.dumps({"showMessage": {"text": text, "level": level}})
    return response


# ================================================================ generate the bill

@role_required(*BILLING_ROLES)
def bill_new(request):
    """"New bill" on the Bills page: a counter sale billed straight away.

    The POS screen on the counter (Takeaway) table in "bill" mode: its Make
    bill button sends the KOT and goes on to this order's bill
    (orders.staff_views.waiter_order_place).
    """
    counter = takeaway_table(get_user_restaurant(request), get_user_location(request))
    if not counter.is_active:
        messages.warning(request, "Counter bills need the Takeaway table. Switch it on in Tables & QR.")
        return redirect("billing:bill_list")
    return render_pos(request, counter, bill_now=True)


@role_required(*BILLING_ROLES)
def bill_create(request, order_id):
    """Preview the bill of an open order, type a discount, then confirm to make the bill.

    A festival offer running today (Cafe profile > Offers) is filled in as the
    discount; the cashier may change it. While the discount is typed, HTMX asks
    this same view (GET) for the totals only.
    """
    restaurant = get_user_restaurant(request)
    order = get_object_or_404(Order.objects.select_related("table", "restaurant"), pk=order_id,
                              location=get_user_location(request))

    if order.status == Order.Status.BILLED and hasattr(order, "bill"):
        return redirect("billing:bill_detail", pk=order.bill.pk)
    if order.status != Order.Status.OPEN:
        messages.warning(request, f"Order #{order.order_no} is {order.get_status_display().lower()}.")
        return redirect("orders:floor")

    food_total = preview_totals(order, "AMOUNT", 0)[1]["subtotal"]
    offer = offer_for(restaurant, timezone.localdate(), food_total)
    form = DiscountForm(request.POST or request.GET or None,
                        initial={"discount_type": offer.kind, "discount_value": offer.value} if offer else None)
    if form.is_bound:
        discount_type, discount_value = form.discount()
    elif offer:
        discount_type, discount_value = offer.kind, offer.value
    else:
        discount_type, discount_value = "AMOUNT", 0
    # the offer's name goes on the bill only while its discount is kept as it is
    offer_kept = offer is not None and (discount_type, Decimal(discount_value or 0)) == (offer.kind, offer.value)

    if request.method == "POST" and form.is_valid():
        try:
            bill = make_bill(order, request.user.staff, discount_type, discount_value,
                             offer_name=offer.name if offer_kept else "")
        except BillingError as error:
            messages.error(request, str(error))
            return redirect("orders:floor_table", table_id=order.table_id)
        messages.success(request, f"Bill #{bill.bill_no} made for {inr(bill.grand_total)}.")
        return redirect("billing:bill_detail", pk=bill.pk)

    lines, totals = preview_totals(order, discount_type, discount_value)
    context = {"order": order, "lines": lines, "totals": totals, "form": form, "restaurant": restaurant,
               "offer": offer, "offer_kept": offer_kept}
    if is_htmx(request) and request.method == "GET":
        return render(request, "billing/_bill_totals.html", context)

    context["unserved"] = order.kots.filter(status__in=[KOT.Status.NEW, KOT.Status.PREPARING, KOT.Status.READY]).count()
    context["redo"] = hasattr(order, "bill")
    return render(request, "billing/bill_create.html", context)


# ================================================================ one bill + payments

def payment_context(bill, form=None, change=None, can_bill=True):
    """What the payment box needs. can_bill False (a waiter, view only): no payment form."""
    if form is None:
        form = PaymentForm(initial={"amount": bill.balance, "mode": Payment.Mode.CASH})
    return {
        "bill": bill,
        "payments": bill.payments.select_related("received_by"),
        "form": form,
        "change": change,
        "can_pay": can_bill and bill.is_open_for_payment and bill.order.status == Order.Status.BILLED,
    }


def get_bill(request, pk):
    """A bill of this location only."""
    return get_object_or_404(
        Bill.objects.select_related("order__table", "order__waiter", "restaurant", "created_by"),
        pk=pk, location=get_user_location(request),
    )


@role_required(*roles.BILL_VIEW)
def bill_detail(request, pk):
    """The bill with its payments, and the form to take payment in one or more modes.
    A waiter sees the bill and its amounts only (no payment, reopen or cancel).
    Opened from a report's row (?back=, reports drill down): a Back button to that report."""
    bill = get_bill(request, pk)
    role = request.user.staff.role
    can_bill = role in BILLING_ROLES
    context = payment_context(bill, can_bill=can_bill)
    context.update({
        "back": report_back(request.GET.get("back")),
        "items": bill.items.all(),
        "can_bill": can_bill,
        "can_reopen": can_bill and bill.status == Bill.Status.UNPAID and bill.order.status == Order.Status.BILLED
                      and not bill.payments.exists(),
        "can_cancel": role in roles.CANCEL and bill.status in (Bill.Status.UNPAID, Bill.Status.PARTIAL),
        "reopened": bill.status == Bill.Status.UNPAID and bill.order.status == Order.Status.OPEN,
    })
    return render(request, "billing/bill_detail.html", context)


@require_POST
@role_required(*BILLING_ROLES)
def payment_add(request, pk):
    """HTMX: record one payment row (or two for "Split: 2 modes"), then redraw
    the payment box (balance, rows, form)."""
    bill = get_bill(request, pk)
    form = PaymentForm(request.POST)
    if not form.is_valid():
        return render(request, "billing/_payment_box.html", payment_context(bill, form))

    rows = form.payments()
    try:
        bill = add_payments(bill, rows, request.user.staff)
    except BillingError as error:
        response = render(request, "billing/_payment_box.html", payment_context(bill, form))
        return toast(response, str(error), "error")

    change = form.change_to_return()
    response = render(request, "billing/_payment_box.html", payment_context(bill, change=change))
    received = " + ".join(f"{inr(amount)} {dict(Payment.Mode.choices)[mode]}" for mode, amount, _ in rows)
    if bill.status == Bill.Status.PAID:
        text = f"{received} received. Bill #{bill.bill_no} fully paid, order #{bill.order.order_no} is closed."
    else:
        text = f"{received} received. Balance {inr(bill.balance)}."
    if change:
        text += f" Return {inr(change)} change."
    return toast(response, text)


# ================================================================ UPI QR with the amount

def upi_context(bill):
    """What the UPI QR screens need: the amount, and whether a QR with it can be made."""
    restaurant = bill.restaurant
    paid = bill.balance <= 0 or bill.status == Bill.Status.PAID
    own_qr = restaurant.upi_qr if not restaurant.upi_id else None  # only the cafe's picture: no amount in it
    return {
        "bill": bill,
        "restaurant": restaurant,
        "amount": bill.balance,
        "can_make_qr": bool(restaurant.upi_id),  # a UPI ID: a QR with the amount in it
        "own_qr": own_qr,
        "paid": paid,
        "can_record": not paid and bool(restaurant.upi_id or own_qr),  # "Paid by UPI"
    }


@role_required(*BILLING_ROLES)
def bill_upi(request, pk):
    """Side panel (Take payment > Show UPI QR): a QR code with the balance in it, for the guest
    to scan; "Customer screen" opens it big in a window for a second screen; then
    "Paid by UPI" records the payment."""
    bill = get_bill(request, pk)
    if not is_htmx(request):
        return redirect("billing:bill_detail", pk=bill.pk)
    return render(request, "billing/_upi_panel.html", upi_context(bill))


@role_required(*BILLING_ROLES)
def bill_upi_qr(request, pk):
    """The QR code picture of the bill's balance (PNG). Made fresh every time: never cached."""
    bill = get_bill(request, pk)
    if not bill.restaurant.upi_id or bill.balance <= 0:
        raise Http404("No UPI ID, or nothing left to pay.")
    response = HttpResponse(bill_upi_png(bill), content_type="image/png")
    response["Cache-Control"] = "no-store"
    return response


@role_required(*BILLING_ROLES)
def bill_upi_screen(request, pk):
    """The customer screen: the QR code and the amount, big, for a second screen facing
    the guest. It asks again every 3 seconds (HTMX); once the payment is recorded it
    says "Payment received. Thank you!"."""
    bill = get_bill(request, pk)
    template = "billing/_upi_screen_body.html" if is_htmx(request) else "billing/upi_screen.html"
    return render(request, template, upi_context(bill))


@require_POST
@role_required(*BILLING_ROLES)
def bill_upi_paid(request, pk):
    """HTMX, from the UPI panel: the guest has paid by UPI. Records the balance as one UPI
    payment (with the UTR / reference if typed), closes the panel, redraws the payment box."""
    bill = get_bill(request, pk)
    reference = request.POST.get("reference_no", "").strip()[:50]
    amount = bill.balance
    try:
        bill = add_payments(bill, [(Payment.Mode.UPI, amount, reference)], request.user.staff)
    except BillingError as error:
        return toast(render(request, "billing/_payment_box.html", payment_context(bill)), str(error), "error")
    response = render(request, "billing/_payment_box.html", payment_context(bill))
    text = f"{inr(amount)} UPI received."
    if bill.status == Bill.Status.PAID:
        text += f" Bill #{bill.bill_no} fully paid."
    response["HX-Trigger"] = json.dumps({"closePanel": True, "showMessage": {"text": text, "level": "success"}})
    return response


@require_POST
@role_required(*BILLING_ROLES)
def payment_remove(request, pk, payment_id):
    """HTMX: take back a payment typed by mistake (only while the bill is not fully paid)."""
    bill = get_bill(request, pk)
    payment = get_object_or_404(Payment, pk=payment_id, bill=bill)
    try:
        bill = remove_payment(payment)
    except BillingError as error:
        return toast(render(request, "billing/_payment_box.html", payment_context(bill)), str(error), "error")
    return toast(render(request, "billing/_payment_box.html", payment_context(bill)), "Payment removed.")


@require_POST
@role_required(*BILLING_ROLES)
def bill_reopen(request, pk):
    """Guests want more after the bill: the order takes new rounds; generate the bill again later."""
    bill = get_bill(request, pk)
    try:
        reopen_order(bill)
    except BillingError as error:
        messages.error(request, str(error))
        return redirect("billing:bill_detail", pk=bill.pk)
    messages.success(request, f"Order #{bill.order.order_no} is open again. Generate the bill again when they are done.")
    return redirect("orders:floor_table", table_id=bill.order.table_id)


@role_required(*roles.CANCEL)
def bill_cancel(request, pk):
    """Side panel: cancel an unpaid bill with a reason. Its order is cancelled and the table freed."""
    bill = get_bill(request, pk)
    if not is_htmx(request):
        return redirect("billing:bill_detail", pk=bill.pk)

    form = BillCancelForm(request.POST or None)
    blocked = ""
    if bill.payments.exists():
        blocked = "This bill has payments. Remove them first, then cancel the bill."
    elif bill.status == Bill.Status.CANCELLED:
        blocked = "This bill is already cancelled."

    if request.method == "POST" and not blocked and form.is_valid():
        try:
            cancel_bill(bill, form.cleaned_data["reason"])
        except BillingError as error:
            blocked = str(error)
        else:
            messages.success(request, f"Bill #{bill.bill_no} cancelled.")
            response = HttpResponse(status=204)
            response["HX-Redirect"] = reverse("billing:bill_detail", args=[bill.pk])
            return response

    return render(request, "billing/_bill_cancel_form.html", {
        "form": form, "bill": bill, "blocked": blocked,
        "title": f"Cancel bill #{bill.bill_no}", "submit_label": "Cancel bill",
    })


@role_required(*roles.BILL_VIEW)
def bill_print(request, pk):
    """80 mm bill for the thermal printer. Prints on open."""
    bill = get_bill(request, pk)
    return render(request, "print/bill.html", {
        "bill": bill,
        "restaurant": bill.restaurant,
        "items": bill.items.all(),
        "payments": bill.payments.all(),
    })


@role_required(*roles.BILL_VIEW)
def bill_print_slip(request, pk):
    """The same bill as printer bytes (ESC/POS), for the print helper's direct print (static/js/printing.js)."""
    bill = get_bill(request, pk)
    return HttpResponse(bill_slip(bill), content_type="application/octet-stream")


# ================================================================ bill register

def orders_to_bill(location):
    """The location's open orders still waiting for their bill, oldest first (tables, parcels,
    deliveries), each with its amount, minutes and what the kitchen is still doing.
    An order with nothing left to bill (every round cancelled) is left out."""
    now = timezone.now()
    orders = []
    running = (Order.objects.filter(location=location, status=Order.Status.OPEN)
               .select_related("table").prefetch_related("kots__items").order_by("created_at"))
    for order in running:
        kots = [kot for kot in order.kots.all() if kot.status != KOT.Status.CANCELLED]
        order.amount = order_total(kots)
        if not order.amount:
            continue
        order.minutes = int((now - order.created_at).total_seconds() // 60)
        order.rounds = len(kots)
        order.cooking = sum(1 for kot in kots if kot.status in (KOT.Status.NEW, KOT.Status.PREPARING))
        order.ready = sum(1 for kot in kots if kot.status == KOT.Status.READY)
        orders.append(order)
    return orders


def to_bill_context(request):
    """What the "To bill" block on the Bills page needs."""
    orders = orders_to_bill(get_user_location(request))
    return {"to_bill": orders, "to_bill_amount": sum((order.amount for order in orders), Decimal("0.00")),
            "can_bill": request.user.staff.role in BILLING_ROLES}  # a waiter sees the amounts, no Make bill


@role_required(*roles.BILL_VIEW)
def bills_to_make(request):
    """HTMX: the "To bill" block again (it asks every 15 seconds)."""
    return render(request, "billing/_to_bill.html", to_bill_context(request))


def filtered_bills(request):
    """This location's bills in the chosen dates, status and search."""
    form = BillFilterForm(request.GET or None)
    date_from, date_to = form.dates()
    bills = Bill.objects.filter(
        location=get_user_location(request), bill_date__range=(date_from, date_to),
    ).select_related("order__table")

    if form.is_valid():
        if form.cleaned_data["status"]:
            bills = bills.filter(status=form.cleaned_data["status"])
        q = form.cleaned_data["q"].strip()
        if q:
            match = Q(order__customer_name__icontains=q) | Q(order__table__name__iexact=q)
            if q.lstrip("#").isdigit():
                match |= Q(bill_no=int(q.lstrip("#")))
            bills = bills.filter(match)

    totals = bills.exclude(status=Bill.Status.CANCELLED).aggregate(
        count=Count("id"), total=Sum("grand_total"), paid=Sum("paid_amount"),
    )
    return form, bills, totals, date_from, date_to


@role_required(*roles.BILL_VIEW)
def bill_list(request):
    """Bill register: every bill in the dates, like a day book. Today by default.
    Above it, the orders still waiting for their bill, each with Make bill
    (a waiter sees the same lists and amounts, without Make bill or New bill)."""
    form, bills, totals, date_from, date_to = filtered_bills(request)
    if not form.is_bound:
        form = BillFilterForm(initial={"date_from": date_from, "date_to": date_to})
    bills, pager = paginate(bills, request.GET)
    return render(request, "billing/bill_list.html", {
        "form": form, "bills": bills, "pager": pager, "totals": totals, "date_from": date_from, "date_to": date_to,
        **to_bill_context(request),
    })


@role_required(*roles.BILL_VIEW)
def bill_rows(request):
    """HTMX: just the bill register table, after a filter change or another page."""
    form, bills, totals, date_from, date_to = filtered_bills(request)
    bills, pager = paginate(bills, request.GET)
    return render(request, "billing/_bill_rows.html", {
        "bills": bills, "pager": pager, "totals": totals, "date_from": date_from, "date_to": date_to,
    })
