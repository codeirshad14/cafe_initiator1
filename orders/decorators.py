from functools import wraps

from django.shortcuts import redirect, render

from tables.models import DiningTable


def with_customer_table(view_func):
    """For the customer (QR) pages: turn the qr_token in the URL into the table.

    The view then receives `table` instead of `qr_token`:

        @with_customer_table
        def customer_menu(request, table): ...

    An unknown token, a switched-off table, a closed location or a restaurant
    whose plan is off shows the "not taking orders" page instead. An Only Menu
    cafe's table QR opens its view-only menu (core/plans.py). Checked on every request.
    """

    @wraps(view_func)
    def wrapper(request, qr_token, *args, **kwargs):
        table = DiningTable.objects.select_related("restaurant", "location").filter(qr_token=qr_token).first()
        if table is None or not table.is_active or not table.location.is_active or not table.restaurant.is_usable():
            return render(request, "orders/customer_closed.html", status=404)
        if table.restaurant.menu_only:
            return redirect("orders:menu_view", slug=table.restaurant.slug)
        return view_func(request, table, *args, **kwargs)

    return wrapper
