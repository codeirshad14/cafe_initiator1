"""Small helpers for the tests (used by every app's tests.py). Not used by the app itself."""

from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client

from core.models import Restaurant, Staff
from menu.models import Category, MenuItem
from tables.models import DiningTable

PASSWORD = "Test@12345"
HTMX = {"HTTP_HX_REQUEST": "true"}  # pass as **HTMX to make a request look like it came from HTMX


def make_restaurant(name="Spice Garden", **extra):
    """A restaurant for a test: on the Ultimate plan (no limits) unless the test gives tier=,
    with its profile filled in (address, phone) unless the test gives them empty."""
    slug = name.lower().replace(" ", "-")
    extra.setdefault("tier", "ULTIMATE")
    extra.setdefault("address", "12 Test Road")
    extra.setdefault("phone", "9876500000")
    return Restaurant.objects.create(name=name, slug=slug, **extra)


def make_staff(restaurant, role, email=None):
    email = email or f"{role.lower()}@{restaurant.slug}.test"
    user = User.objects.create_user(email, email=email, password=PASSWORD)
    return Staff.objects.create(user=user, restaurant=restaurant, name=f"{role.title()} {restaurant.name}", role=role)


def client_for(staff):
    """A test browser already logged in as this staff member."""
    client = Client()
    client.force_login(staff.user)
    return client


def developer_client(user=None):
    """A test browser signed in to the Django admin as the developer's superuser.
    /admin/ keeps a login of its own (core/middleware.py), so it gets the admin's cookie."""
    from django.conf import settings

    from core.middleware import ADMIN_SESSION
    if user is None:
        user = User.objects.create_superuser("dev", email="dev@x.test", password="Dev@12345")
    client = Client()
    client.force_login(user)
    client.cookies[ADMIN_SESSION] = client.cookies[settings.SESSION_COOKIE_NAME].value
    return client


def make_menu(restaurant):
    """One category with two dishes: (category, paneer at 249, naan at 60)."""
    category = Category.objects.create(restaurant=restaurant, name="Starters")
    paneer = MenuItem.objects.create(restaurant=restaurant, category=category, name="Paneer Tikka", price=Decimal("249"))
    naan = MenuItem.objects.create(restaurant=restaurant, category=category, name="Butter Naan", price=Decimal("60"))
    return category, paneer, naan


def make_table(restaurant, name="T1"):
    return DiningTable.objects.create(restaurant=restaurant, name=name)


def guest_orders(client, table, dishes, name="Meera"):
    """A guest adds these dishes (a list, repeat a dish for 2) and places the order from the QR menu."""
    menu = f"/m/{table.qr_token}/"
    for dish in dishes:
        client.post(f"{menu}cart/add/{dish.pk}/", **HTMX)
    return client.post(f"{menu}place/", {"customer_name": name})
