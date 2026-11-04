from functools import wraps

from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render

from .plans import menu_only_allows


def role_required(*roles):
    """Let only active staff whose role is in `roles` open the view.

        @role_required("ADMIN", "CASHIER")
        def bill_list(request): ...

    With no roles, any active staff member may open it: @role_required()
    """

    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapper(request, *args, **kwargs):
            staff = getattr(request.user, "staff", None)

            # the developer's superuser, not staff of any restaurant: the app never
            # sends them into the Django admin, it explains instead
            if staff is None:
                if request.user.is_superuser:
                    return render(request, "core/developer_login.html", status=403)
                logout(request)
                messages.error(request, "This login is not linked to any restaurant.")
                return redirect("login")

            if not staff.is_active or not staff.restaurant.is_active:
                logout(request)
                messages.error(request, "Your login has been switched off.")
                return redirect("login")

            # still logged in from before the membership ended: their data
            # stays, renewing opens it again
            if not staff.restaurant.membership_active:
                if request.headers.get("HX-Request") == "true":
                    response = HttpResponse(status=204)
                    response["HX-Refresh"] = "true"  # reload, so the page below shows
                    return response
                return render(request, "core/membership_ended.html",
                              {"restaurant": staff.restaurant}, status=403)

            # Only Menu: the cafe profile and the menu; every other screen says "Upgrade" (core/plans.py)
            view_name = request.resolver_match.view_name if request.resolver_match else ""
            if staff.restaurant.menu_only and not menu_only_allows(view_name):
                return render(request, "core/upgrade.html", {"restaurant": staff.restaurant}, status=403)

            if roles and staff.role not in roles:
                return render(request, "core/no_access.html", status=403)

            return view_func(request, *args, **kwargs)

        wrapper.allowed_roles = roles  # who may open it (empty: any staff), for checks and tests
        return wrapper

    return decorator
