from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.views import LoginView
from django.urls import reverse
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from billing.models import Bill
from billing.upi import upi_link
from orders.models import KOT, Order
from tables.models import DiningTable
from tables.qr import qr_data_uri

from . import roles
from .analytics import by_location, dashboard_figures, period_filter_context
from .decorators import role_required
from .forms import BillSettingsForm, RestaurantForm, StaffForm, StaffLoginForm
from .models import Staff
from .navigation import first_page_for
from .pagination import paginate
from .utils import get_user_location, get_user_restaurant, htmx_saved, is_htmx


# ---------------------------------------------------------------- login

class StaffLoginView(LoginView):
    """/login/: Django's login with our form (email, "Sign in as restaurant admin").
    On the server the login cookie only travels over https:// (SECURE_COOKIES), so the
    page says so when it is opened over http://, instead of failing without a word."""

    authentication_form = StaffLoginForm
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["cookies_need_https"] = settings.SESSION_COOKIE_SECURE
        return context


# ---------------------------------------------------------------- live screens

@role_required()
def live(request):
    """The restaurant's change number, asked every 3 seconds by every staff page (core/live.py)."""
    return JsonResponse({"v": get_user_restaurant(request).live_version})


# ---------------------------------------------------------------- start page

@role_required()
def home(request):
    """After login: send each staff member to the first screen of their role.
    A new cafe's admin (or manager) first fills in the cafe profile, then adds the staff."""
    staff = request.user.staff
    if staff.role in roles.COMPANY and not staff.restaurant.profile_done:
        return redirect("core:restaurant_settings")  # it says "Step 1 of 2" there
    url = first_page_for(staff.role, staff.restaurant.menu_only)
    if url:
        return redirect(url)
    # this role's screens are built in a later phase
    return render(request, "core/home.html")


def greeting_for_now():
    """'Good morning' / 'Good afternoon' / 'Good evening' by local time."""
    hour = timezone.localtime().hour
    if hour < 12:
        return "Good morning"
    if hour < 17:
        return "Good afternoon"
    return "Good evening"


def right_now(location):
    """The live strip: what is going on at this location at this moment, whatever period is picked."""
    return {
        # tables in use (a table with separate bills still counts once)
        "open_tables": Order.objects.filter(
            location=location, status__in=Order.RUNNING, order_type=Order.OrderType.DINE_IN,
        ).values("table").distinct().count(),
        "table_count": DiningTable.objects.filter(location=location, is_active=True, is_takeaway=False).count(),
        "open_parcels": Order.objects.filter(
            location=location, status__in=Order.RUNNING + [Order.Status.PENDING],
            order_type__in=[Order.OrderType.TAKEAWAY, Order.OrderType.DELIVERY], delivered_at__isnull=True,
        ).count(),
        "pending_kots": KOT.objects.filter(location=location, status__in=[KOT.Status.NEW, KOT.Status.PREPARING]).count(),
        "ready_kots": KOT.objects.filter(location=location, status=KOT.Status.READY).count(),
        "unpaid_bills": Bill.objects.filter(location=location, status__in=[Bill.Status.UNPAID, Bill.Status.PARTIAL]).count(),
    }


@role_required(*roles.DASHBOARD)
def dashboard(request):
    """The owner's analysis of the current location: sales and how they compare with
    the period before, the trend, busy hours, dine in / takeaway / delivery, payment
    modes, categories, top dishes, staff; plus what is going on right now. Today /
    This week / This month / Range (core/analytics.py). Admin and manager also see
    every location side by side. The body reloads by itself when anything changes."""
    restaurant, place = get_user_restaurant(request), get_user_location(request)
    period = period_filter_context(request.GET, timezone.localdate())
    active_staff = Staff.objects.filter(restaurant=restaurant, is_active=True, user__is_active=True).count()
    company_wide = request.user.staff.role in roles.COMPANY
    context = {
        "restaurant": restaurant,
        "greeting": greeting_for_now(),
        **period,
        **dashboard_figures(place, period["start"], period["end"]),
        "location_sales": by_location(restaurant, period["start"], period["end"]) if company_wide else [],
        "now": right_now(place),
        "active_staff": active_staff,
    }
    template = "core/_dashboard_body.html" if is_htmx(request) else "core/dashboard.html"
    return render(request, template, context)


# ---------------------------------------------------------------- restaurant settings

@role_required(*roles.COMPANY)
def restaurant_settings(request):
    """The restaurant admin edits their own restaurant: name, address, GST, logo.

    Membership is shown, not edited: the platform owner sets it in the Django admin.
    A new cafe fills this in first; the first complete save goes on to Staff.
    """
    restaurant = get_user_restaurant(request)
    first_time = not restaurant.profile_done
    if request.method == "POST":
        form = RestaurantForm(request.POST, request.FILES, instance=restaurant)
        if form.is_valid():
            form.save()
            if first_time:
                messages.success(request, "Your cafe profile is ready. Next: add your staff logins "
                                          "(cashier, waiter, kitchen, rider…) with Add staff.")
                return redirect("core:staff_list")
            messages.success(request, "Restaurant details saved.")
            return redirect("core:restaurant_settings")
    else:
        form = RestaurantForm(instance=restaurant)

    return render(request, "core/restaurant_settings.html", {
        "form": form,
        "restaurant": restaurant,
        "first_time": first_time,
        "public_menu_url": request.build_absolute_uri(reverse("orders:public_menu", args=[restaurant.slug])),
    })


@role_required(*roles.COMPANY)
def bill_settings(request):
    """Cafe profile > Bill & print: name and title on the bill, logo, tax lines, UPI. For every bill."""
    restaurant = get_user_restaurant(request)
    if request.method == "POST":
        form = BillSettingsForm(request.POST, request.FILES, instance=restaurant)
        if form.is_valid():
            form.save()
            messages.success(request, "Bill settings saved. Every bill prints this way from now on.")
            return redirect("core:bill_settings")
    else:
        form = BillSettingsForm(instance=restaurant)
    sample_qr = ""  # the preview's QR code, as a bill of 525.00 prints it
    if restaurant.shows_upi_on_bill and restaurant.upi_id:
        sample_qr = qr_data_uri(upi_link(restaurant, Decimal("525.00"), f"Bill 1 {restaurant.name}"))
    return render(request, "core/bill_settings.html", {"form": form, "restaurant": restaurant, "sample_qr": sample_qr})


# ---------------------------------------------------------------- staff

def filtered_staff(request):
    """Staff of this restaurant, narrowed by the search box and role filter."""
    staff_members = Staff.objects.filter(restaurant=get_user_restaurant(request)).select_related("user")

    q = request.GET.get("q", "").strip()
    if q:
        staff_members = staff_members.filter(
            Q(name__icontains=q) | Q(user__email__icontains=q) | Q(phone__icontains=q)
        )

    role = request.GET.get("role", "")
    if role:
        staff_members = staff_members.filter(role=role)
    return staff_members


@role_required(*roles.COMPANY)
def staff_list(request):
    """Staff page: search, role filter, logins used of the plan, the staff table
    (role and locations), and the "who can do what" table of the roles."""
    staff_members, pager = paginate(filtered_staff(request), request.GET)
    return render(request, "core/staff_list.html", {
        "staff_members": staff_members,
        "pager": pager,
        "roles": Staff.Role.choices,
        "restaurant": get_user_restaurant(request),
        "matrix": role_matrix(),
    })


def role_matrix():
    """The roles table: [{"what", "cells": [True/False per role]}] and the role names as header."""
    names = dict(Staff.Role.choices)
    return {
        "roles": [names[role] for role in roles.ROLE_ORDER],
        "rows": [{"what": what, "cells": [role in allowed for role in roles.ROLE_ORDER]} for what, allowed in roles.MATRIX],
    }


@role_required(*roles.COMPANY)
def staff_rows(request):
    """HTMX: just the staff table, after a search, a save or another page."""
    staff_members, pager = paginate(filtered_staff(request), request.GET)
    return render(request, "core/_staff_rows.html", {"staff_members": staff_members, "pager": pager})


@role_required(*roles.COMPANY)
def staff_usage(request):
    """HTMX: the "3 / 5 logins" pill, after a save."""
    return render(request, "core/_login_usage.html", {"restaurant": get_user_restaurant(request)})


@role_required(*roles.COMPANY)
def staff_add(request):
    """Side panel: create a login user and its Staff row in one form.
    A new cafe fills in its profile first (Staff says so, and so does this panel)."""
    if not is_htmx(request):
        return redirect("core:staff_list")

    restaurant = get_user_restaurant(request)
    if not restaurant.profile_done:
        return render(request, "core/_profile_first.html", {"restaurant": restaurant})

    editor_role = request.user.staff.role
    if request.method == "POST":
        form = StaffForm(request.POST, restaurant=restaurant, editor_role=editor_role)
        if form.is_valid():
            with transaction.atomic():
                staff = form.save_with_user()
            return htmx_saved(f"{staff.name} added as {staff.get_role_display()}.")
    else:
        form = StaffForm(restaurant=restaurant, editor_role=editor_role, initial={"is_active": True})

    return render(request, "core/_staff_form.html", {
        "form": form,
        "title": "Add staff member",
        "submit_label": "Create login",
    })


@role_required(*roles.COMPANY)
def staff_edit(request, pk):
    """Side panel: change a staff member's details, role or password."""
    if not is_htmx(request):
        return redirect("core:staff_list")

    restaurant = get_user_restaurant(request)
    editor_role = request.user.staff.role
    staff_members = Staff.objects.filter(restaurant=restaurant)
    if editor_role != roles.ADMIN:
        staff_members = staff_members.exclude(role=roles.ADMIN)  # only the admin changes the admin login
    staff = get_object_or_404(staff_members, pk=pk)
    editing_self = staff.pk == request.user.staff.pk

    if request.method == "POST":
        form = StaffForm(request.POST, instance=staff, restaurant=restaurant, editing_self=editing_self,
                         editor_role=editor_role)
        if form.is_valid():
            with transaction.atomic():
                staff = form.save_with_user()
            if editing_self and form.cleaned_data["password"]:
                # a new password would otherwise log the admin out
                update_session_auth_hash(request, staff.user)
            return htmx_saved(f"{staff.name} updated.")
    else:
        form = StaffForm(instance=staff, restaurant=restaurant, editing_self=editing_self, editor_role=editor_role)

    return render(request, "core/_staff_form.html", {
        "form": form,
        "title": f"Edit {staff.name}",
        "submit_label": "Save changes",
    })
