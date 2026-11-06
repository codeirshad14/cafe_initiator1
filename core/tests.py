from datetime import date, timedelta

from django.test import Client, TestCase
from django.utils import timezone

from core.models import Restaurant, add_months, membership_end_for
from core.testing import HTMX, PASSWORD, client_for, make_restaurant, make_staff


class DurationFilterTests(TestCase):
    """Waiting times stay short on tiles and KOT cards."""

    def test_duration(self):
        from core.templatetags.money import duration
        self.assertEqual([duration(m) for m in (0, 45, 60, 80, 600, 1568, None)],
                         ["0 min", "45 min", "1 h", "1 h 20 min", "10 h", "26 h", "0 min"])


class PaginationTests(TestCase):
    """Long lists: 100 rows a page (?page=2) or all of them (?page=all), in a box that scrolls."""

    def test_pages(self):
        from core.pagination import paginate
        rows = list(range(250))
        shown, pager = paginate(rows, {})
        self.assertEqual((shown[0], len(shown), pager["start"], pager["end"], pager["count"]), (0, 100, 1, 100, 250))
        shown, pager = paginate(rows, {"page": "3"})
        self.assertEqual((len(shown), pager["start"], pager["end"]), (50, 201, 250))
        self.assertEqual([link["label"] for link in pager["links"]], ["‹", "1", "2", "3", "›"])
        shown, pager = paginate(rows, {"page": "all"})
        self.assertEqual((len(shown), pager["value"], pager["links"]), (250, "all", []))
        self.assertEqual(paginate(rows, {"page": "x"})[1]["start"], 1)  # a wrong page: the first
        self.assertEqual(paginate(rows, {"page": "99"})[1]["start"], 201)  # past the end: the last
        self.assertFalse(paginate(rows[:40], {})[1]["many"])  # one page: no page buttons

    def test_long_gaps(self):
        from core.pagination import page_links
        self.assertEqual([link["label"] for link in page_links(10, 20)],
                         ["‹", "1", "…", "8", "9", "10", "11", "12", "…", "20", "›"])

    def test_menu_items_in_pages(self):
        from decimal import Decimal
        from menu.models import Category, MenuItem
        restaurant = make_restaurant()
        category = Category.objects.create(restaurant=restaurant, name="Mains")
        MenuItem.objects.bulk_create([MenuItem(restaurant=restaurant, category=category, name=f"Dish {n:03}",
                                               price=Decimal("10"), sort_order=n) for n in range(105)])
        manager = client_for(make_staff(restaurant, "MANAGER"))
        page = manager.get("/menu/items/")
        self.assertContains(page, "<strong>1–100</strong> of <strong>105</strong>", html=False)
        self.assertContains(page, 'class="table-wrap table-scroll"')
        self.assertContains(page, "Dish 099")
        self.assertNotContains(page, "Dish 100")
        second = manager.get("/menu/items/rows/?page=2", **HTMX)
        self.assertContains(second, "<strong>101–105</strong>", html=False)
        self.assertContains(second, "Dish 104")
        self.assertNotContains(second, "Dish 000")
        everything = manager.get("/menu/items/rows/?page=all", **HTMX)
        self.assertContains(everything, "Dish 000")
        self.assertContains(everything, "Dish 104")
        self.assertContains(everything, "100 per page")


class OneThemeTests(TestCase):
    """One fixed colour theme: no light / dark switch anywhere."""

    def test_no_theme_switch(self):
        restaurant = make_restaurant()
        page = client_for(make_staff(restaurant, "ADMIN")).get("/floor/")
        self.assertNotContains(page, "themeToggle")
        self.assertContains(page, 'name="color-scheme" content="light"')
        self.assertNotContains(Client().get("/"), "themeToggle")


class BottomNavTests(TestCase):
    """Phones and tablets: each role's bottom bar holds its main pages, then More."""

    def bottom_labels(self, role):
        import re
        restaurant = make_restaurant(f"Cafe {role}")
        page = client_for(make_staff(restaurant, role)).get("/floor/" if role != "KITCHEN" else "/kitchen/")
        nav = page.content.decode().split('class="bottom-nav"')[1].split("</nav>")[0]
        return re.findall(r"<span>([^<]+)</span>", nav)

    def test_each_role_gets_its_main_pages(self):
        self.assertEqual(self.bottom_labels("ADMIN"), ["Dashboard", "Floor", "Kitchen", "Bills", "More"])
        self.assertEqual(self.bottom_labels("CASHIER"), ["Floor", "Kitchen", "Bills", "Deliveries", "More"])
        self.assertEqual(self.bottom_labels("WAITER"), ["Floor", "Ready", "Kitchen", "Bills", "More"])  # bills: view only
        self.assertEqual(self.bottom_labels("KITCHEN"), ["Kitchen", "More"])
        self.assertEqual(self.bottom_labels("RM"), ["Dashboard", "Floor", "Kitchen", "Bills", "More"])
        # the all-rounder: the waiter's, the kitchen's and the rider's screens ("My deliveries")
        self.assertEqual(self.bottom_labels("ALL"), ["Floor", "Ready", "Kitchen", "Deliveries", "More"])

    def test_cashier_menu_has_service_billing_and_setup(self):
        """The Bills role (cashier): Floor, Kitchen, Deliveries, Bookings, Bills, Menu items, Categories, Tables & QR."""
        import re
        page = client_for(make_staff(make_restaurant(), "CASHIER")).get("/floor/")
        menu = page.content.decode().split('class="sidebar-nav"')[1].split("</nav>")[0]
        self.assertEqual(re.findall(r'<span class="nav-label">([^<]+)</span>', menu),
                         ["Floor", "Kitchen", "Deliveries", "Bookings", "Bills", "Menu items", "Categories", "Tables &amp; QR"])

    def test_the_page_open_is_lit(self):
        page = client_for(make_staff(make_restaurant(), "WAITER")).get("/floor/")
        self.assertContains(page, 'class="bottom-nav-item active" aria-current="page"')


class LoginTests(TestCase):
    """Email login, the "Sign in as restaurant admin" tick box, and refused logins."""

    def setUp(self):
        self.restaurant = make_restaurant()
        self.admin = make_staff(self.restaurant, "ADMIN")
        self.waiter = make_staff(self.restaurant, "WAITER")

    def login(self, email, as_admin=False):
        data = {"username": email, "password": PASSWORD}
        if as_admin:
            data["as_admin"] = "on"
        return Client().post("/login/", data)

    def test_admin_logs_in_with_email_and_tick(self):
        response = self.login(self.admin.user.email.upper(), as_admin=True)
        self.assertRedirects(response, "/home/", fetch_redirect_response=False)

    def test_tick_box_must_match_the_role(self):
        self.assertContains(self.login(self.admin.user.email), "Tick")
        self.assertContains(self.login(self.waiter.user.email, as_admin=True), "Untick")
        self.assertEqual(self.login(self.waiter.user.email).status_code, 302)

    def test_switched_off_staff_cannot_log_in(self):
        self.waiter.is_active = False
        self.waiter.save()
        self.assertContains(self.login(self.waiter.user.email), "switched off")

    def test_ended_membership_stops_login(self):
        self.restaurant.membership_start = date(2020, 1, 1)
        self.restaurant.membership_end = date(2020, 1, 31)
        self.restaurant.save()
        self.assertContains(self.login(self.waiter.user.email), "membership ended on 31 Jan 2020")

    def test_password_guessing_waits_after_five_tries(self):
        from django.core.cache import cache
        cache.clear()
        email = self.waiter.user.email
        for n in range(5):
            self.assertContains(Client().post("/login/", {"username": email, "password": f"guess{n}"}), "did not match")
        self.assertContains(self.login(email.upper()), "Too many wrong passwords")  # even the right one
        self.assertEqual(self.login(self.admin.user.email, as_admin=True).status_code, 302)  # others go on
        cache.clear()  # the 15 minutes are over
        self.assertEqual(self.login(email).status_code, 302)

    def test_the_login_page_asks_for_https_when_the_cookie_needs_it(self):
        from django.test import override_settings
        self.assertNotContains(Client().get("/login/"), "Open this page with https://")  # this PC
        with override_settings(SESSION_COOKIE_SECURE=True):
            self.assertContains(Client().get("/login/"), "Open this page with https://")
            self.assertNotContains(Client().get("/login/", secure=True), "Open this page with https://")

    def test_a_good_login_clears_the_count(self):
        from django.core.cache import cache
        cache.clear()
        email = self.waiter.user.email
        for n in range(4):
            Client().post("/login/", {"username": email, "password": f"guess{n}"})
        self.assertEqual(self.login(email).status_code, 302)
        for n in range(4):
            Client().post("/login/", {"username": email, "password": f"guess{n}"})
        self.assertEqual(self.login(email).status_code, 302)


class ErrorPageTests(TestCase):
    """The error pages of the server (tests run with DEBUG=False)."""

    def test_404_is_our_page(self):
        response = Client().get("/no-such-page/")
        self.assertContains(response, "This page is not here", status_code=404)
        self.assertContains(response, 'href="/"', status_code=404)  # a guest goes to the website

    def test_500_renders_with_no_context(self):
        from django.template.loader import render_to_string
        self.assertIn("Something went wrong", render_to_string("500.html"))

    def test_a_wrong_host_is_a_clean_400(self):
        with self.settings(ALLOWED_HOSTS=["testserver"]):
            response = Client(raise_request_exception=False).get("/", HTTP_HOST="evil.example")
        self.assertContains(response, "That did not work", status_code=400)

    def test_csrf_failure_is_our_page(self):
        response = Client(enforce_csrf_checks=True).post("/login/", {"username": "a@b.c", "password": "x"})
        self.assertContains(response, "open too long", status_code=403)


class MembershipTests(TestCase):
    def test_month_end_is_kept_inside_the_month(self):
        self.assertEqual(add_months(date(2028, 1, 31), 1), date(2028, 2, 29))

    def test_periods(self):
        self.assertEqual(membership_end_for(date(2026, 10, 7), "MONTHLY"), date(2026, 11, 6))
        self.assertEqual(membership_end_for(date(2026, 10, 7), "YEARLY"), date(2027, 10, 6))

    def test_renew_while_running_adds_after_the_end(self):
        today = timezone.localdate()
        restaurant = Restaurant(plan="MONTHLY", membership_start=today, membership_end=today + timedelta(days=3))
        restaurant.renew_membership()
        self.assertEqual(restaurant.membership_end, membership_end_for(today + timedelta(days=4), "MONTHLY"))

    def test_logged_in_staff_see_membership_ended_page(self):
        restaurant = make_restaurant()
        client = client_for(make_staff(restaurant, "ADMIN"))
        restaurant.membership_start = date(2020, 1, 1)
        restaurant.membership_end = date(2020, 1, 31)
        restaurant.save()
        self.assertContains(client.get("/dashboard/"), "membership ended", status_code=403)


class MembershipTypeTests(TestCase):
    """Only Menu, Basic, Standard, Enterprise, Ultimate (core/plans.py): what each may use."""

    def setUp(self):
        from core.testing import guest_orders, make_menu, make_table
        self.guest_orders, self.make_table = guest_orders, make_table
        self.restaurant = make_restaurant(tier="BASIC")
        _, self.paneer, self.naan = make_menu(self.restaurant)
        self.manager = client_for(make_staff(self.restaurant, "MANAGER"))
        self.cashier = client_for(make_staff(self.restaurant, "CASHIER"))

    def set_tier(self, tier):
        Restaurant.objects.filter(pk=self.restaurant.pk).update(tier=tier)
        self.restaurant.refresh_from_db()

    def order_and_bill(self, table_name):
        from orders.models import Order
        table = self.make_table(self.restaurant, table_name)
        self.guest_orders(Client(), table, [self.paneer])
        order = Order.objects.get(table=table)
        return order, self.cashier.post(f"/billing/create/{order.pk}/", {"discount_type": "AMOUNT"}, follow=True)

    def test_membership_year_runs_from_each_anniversary(self):
        restaurant = Restaurant(membership_start=date(2025, 11, 5))
        self.assertEqual(restaurant.plan_year(date(2026, 10, 31)), (date(2025, 11, 5), date(2026, 11, 4)))
        self.assertEqual(restaurant.plan_year(date(2026, 11, 5)), (date(2026, 11, 5), date(2027, 11, 4)))

    def test_new_cafes_start_on_basic_and_limits_follow_the_type(self):
        self.assertEqual(Restaurant.objects.create(name="New", slug="new").tier, "BASIC")
        for tier, bills, places in (("MENU", 0, 1), ("BASIC", 10_000, 1), ("STANDARD", 50_000, 1),
                                    ("ENTERPRISE", 5_000_000, 20), ("ULTIMATE", None, None)):
            self.set_tier(tier)
            self.assertEqual((self.restaurant.bill_limit, self.restaurant.location_limit), (bills, places))

    def test_make_bill_stops_once_the_years_bills_are_used(self):
        from unittest import mock
        from billing.models import Bill
        from core.plans import LIMITS
        with mock.patch.dict(LIMITS["BASIC"], {"bills": 1}):
            _, first = self.order_and_bill("T1")
            self.assertEqual(Bill.objects.count(), 1)
            order, second = self.order_and_bill("T2")
            self.assertContains(second, "Upgrade your plan to make more bills")
            self.assertEqual(Bill.objects.count(), 1)  # no second bill
            self.assertEqual(order.status, "OPEN")
            page = self.cashier.get("/billing/")
            self.assertContains(page, "This year's bills are used up")
            Bill.objects.update(status="CANCELLED")  # a cancelled bill does not count
            self.assertTrue(Restaurant.objects.get(pk=self.restaurant.pk).can_make_bill())

    def test_bills_page_warns_near_the_limit(self):
        from unittest import mock
        from core.plans import LIMITS
        self.order_and_bill("T1")
        with mock.patch.dict(LIMITS["BASIC"], {"bills": 10}):
            self.assertNotContains(self.cashier.get("/billing/"), "plan-alert")
        with mock.patch.dict(LIMITS["BASIC"], {"bills": 1}):
            self.assertContains(self.cashier.get("/billing/"), "plan-alert")
        self.assertContains(self.manager.get("/home/", follow=True), "Bills this year: 1 of 10,000")

    def test_locations_within_the_plan(self):
        from core.testing import HTMX
        add = {"name": "MG Road", "address": "", "phone": "", "is_active": "on"}
        self.restaurant.main_location()
        refused = self.manager.post("/locations/add/", add, **HTMX)
        self.assertContains(refused, "plan includes 1 open location")
        self.assertEqual(self.restaurant.locations.count(), 1)
        self.set_tier("ENTERPRISE")
        self.assertEqual(self.manager.post("/locations/add/", add, **HTMX).status_code, 204)
        # a closed location opened again counts too
        self.set_tier("BASIC")
        place = self.restaurant.locations.get(name="MG Road")
        place.is_active = False
        place.save()
        reopen = self.manager.post(f"/locations/{place.pk}/edit/", add, **HTMX)
        self.assertContains(reopen, "Upgrade to Enterprise")

    def test_only_menu_has_the_menu_screens(self):
        self.set_tier("MENU")
        home = self.manager.get("/home/")
        self.assertRedirects(home, "/menu/items/")
        page = self.manager.get("/menu/items/")
        self.assertContains(page, "Only Menu plan")
        self.assertContains(page, 'href="/menu/categories/"')
        self.assertNotContains(page, 'href="/floor/"')
        self.assertNotContains(page, 'id="notifyBell"')
        for url in ("/floor/", "/kitchen/", "/billing/", "/reports/", "/dashboard/", "/deliveries/", "/tables/bookings/"):
            with self.subTest(url=url):
                self.assertContains(self.manager.get(url), "Upgrade your plan", status_code=403)
        for url in ("/menu/categories/", "/restaurant/", "/staff/", "/tables/"):
            with self.subTest(url=url):
                self.assertEqual(self.manager.get(url).status_code, 200)
        qr_page = self.manager.get("/tables/")
        self.assertContains(qr_page, "View-only menu")
        self.assertNotContains(qr_page, "Order menu")
        self.assertNotContains(qr_page, "Add table")
        self.assertEqual(self.manager.get("/tables/menu-qr/order.png").status_code, 404)
        self.assertEqual(self.manager.get("/tables/menu-qr/view.png").status_code, 200)

    def test_only_menu_guests_look_but_do_not_order(self):
        table = self.make_table(self.restaurant, "T1")
        self.set_tier("MENU")
        slug = self.restaurant.slug
        self.assertRedirects(Client().get(f"/m/{table.qr_token}/"), f"/r/{slug}/view/")
        self.assertRedirects(Client().post(f"/m/{table.qr_token}/place/", {"customer_name": "X"}), f"/r/{slug}/view/")
        menu = Client().get(f"/r/{slug}/")
        self.assertContains(menu, "Paneer Tikka")
        self.assertNotContains(menu, "/cart/")
        self.assertEqual(Client().get(f"/r/{slug}/book/").status_code, 404)
        from orders.models import Order
        self.assertFalse(Order.objects.exists())

    def test_django_admin_shows_the_type_and_use(self):
        from django.contrib.auth.models import User
        developer = Client()
        developer.force_login(User.objects.create_superuser("dev", email="dev@x.test", password="Dev@12345"))
        page = developer.get("/admin/core/restaurant/")
        self.assertContains(page, "Membership type")
        self.assertContains(page, "Bills this year")
        self.assertContains(page, "0 / 10,000")


class AdminRestaurantFormTests(TestCase):
    """Django admin (developer only): a new restaurant with its admin login and membership.
    The cafe's admin fills in the profile and adds the staff logins in the app."""

    def setUp(self):
        from django.contrib.auth.models import User
        self.User = User
        self.client = Client()
        self.client.force_login(User.objects.create_superuser("dev", email="dev@x.test", password="Dev@12345"))
        self.free = User.objects.create_user("free@x.test", email="free@x.test", password=PASSWORD)
        self.taken = make_staff(make_restaurant("Blue Bay"), "ADMIN").user  # already staff elsewhere

    def form_data(self, restaurant=None):
        today = timezone.localdate().isoformat()
        return {
            "name": "Spice Garden", "slug": "spice-garden", "gst_percent": "5", "tier": "BASIC", "plan": "MONTHLY",
            "membership_start": today, "membership_end": today, "max_users": "5", "is_active": "on",
            # the restaurant admin's login, on the first tab
            "email": "Admin@Spice.in", "admin_password": "Spice@2026",
            # the Locations rows on Change (none added here)
            "locations-TOTAL_FORMS": "0", "locations-INITIAL_FORMS": "0",
            "locations-MIN_NUM_FORMS": "0", "locations-MAX_NUM_FORMS": "1000",
            **(restaurant or {}),
        }

    def staff_of(self, role):
        return Restaurant.objects.get(slug="spice-garden").staff_members.get(role=role)

    def test_new_restaurant_gets_its_admin_login_from_its_email(self):
        response = self.client.post("/admin/core/restaurant/add/", self.form_data())
        self.assertEqual(response.status_code, 302, response.content[:2000])
        admin = self.staff_of("ADMIN")
        self.assertEqual((admin.user.username, admin.user.email, admin.name), ("admin@spice.in", "admin@spice.in", "Spice Garden"))
        self.assertTrue(admin.user.check_password("Spice@2026"))
        login = Client().post("/login/", {"username": "admin@spice.in", "password": "Spice@2026", "as_admin": "on"})
        self.assertRedirects(login, "/home/", fetch_redirect_response=False)

    def test_new_restaurant_needs_the_email_and_a_good_password(self):
        for changes, error in (({"email": ""}, "This field is required"), ({"admin_password": ""}, "This field is required"),
                               ({"admin_password": "12345"}, "too short"), ({"email": "free@x.test"}, "Another login already has")):
            with self.subTest(changes=changes):
                self.assertContains(self.client.post("/admin/core/restaurant/add/", self.form_data(restaurant=changes)), error)
        self.assertFalse(Restaurant.objects.filter(slug="spice-garden").exists())

    def test_add_asks_only_what_we_set(self):
        """Add: the restaurant, its admin login and the membership; the cafe fills in the rest itself."""
        page = self.client.get("/admin/core/restaurant/add/").content.decode()
        for ours in ('name="name"', 'name="slug"', 'name="email"', 'name="admin_password"', 'name="tier"', 'name="membership_end"'):
            self.assertIn(ours, page)
        for theirs in ('name="address"', 'name="gstin"', 'name="logo"', "staff_members-TOTAL_FORMS", "locations-TOTAL_FORMS"):
            self.assertNotIn(theirs, page)
        self.client.post("/admin/core/restaurant/add/", self.form_data())
        change = self.client.get(f"/admin/core/restaurant/{Restaurant.objects.get(slug='spice-garden').pk}/change/")
        self.assertContains(change, 'name="gstin"')  # shown later, to help the cafe when it asks
        self.assertNotContains(change, "staff_members-TOTAL_FORMS")  # the cafe adds its own staff

    def staff_page(self, **row):
        """The Django admin's own Staff page (support only): one staff login for Blue Bay."""
        data = {"restaurant": self.taken.staff.restaurant.pk, "name": "Anil", "role": "MANAGER", "is_active": "on", **row}
        return self.client.post("/admin/core/staff/add/", data)

    def test_staff_page_lists_free_logins_only(self):
        response = self.client.get("/admin/core/staff/add/")
        self.assertContains(response, "free@x.test")
        self.assertNotContains(response, f'value="{self.taken.pk}"')

    def test_staff_page_picks_an_existing_login(self):
        self.assertEqual(self.staff_page(login=self.free.pk).status_code, 302)
        self.assertEqual(self.free.staff.role, "MANAGER")

    def test_staff_page_makes_a_new_login(self):
        self.assertEqual(self.staff_page(new_email="Owner@Spice.in", new_password="Owner@2026").status_code, 302)
        user = self.User.objects.get(email="owner@spice.in")
        self.assertEqual(user.username, "owner@spice.in")
        self.assertTrue(user.check_password("Owner@2026"))

    def test_staff_page_refuses_a_taken_email_and_needs_a_login(self):
        self.assertContains(self.staff_page(new_email=self.taken.email, new_password="Owner@2026"), "already exists")
        self.assertContains(self.staff_page(), "Pick a login from the list")

    def edit(self, restaurant, **changes):
        """Save the restaurant's form again in the admin, as it is plus `changes`."""
        data = self.form_data(restaurant={"slug": restaurant.slug, "name": restaurant.name,
                                          "email": restaurant.email, "admin_password": "", **changes})
        return self.client.post(f"/admin/core/restaurant/{restaurant.pk}/change/", data)

    def test_the_password_box_resets_the_admin_password(self):
        self.client.post("/admin/core/restaurant/add/", self.form_data())
        restaurant = Restaurant.objects.get(slug="spice-garden")
        self.assertEqual(self.edit(restaurant).status_code, 302)  # empty: kept
        self.assertTrue(self.staff_of("ADMIN").user.check_password("Spice@2026"))
        self.assertEqual(self.edit(restaurant, admin_password="Fresh@2027").status_code, 302)
        self.assertTrue(self.staff_of("ADMIN").user.check_password("Fresh@2027"))

    def test_a_new_email_moves_the_login_only_when_changed_here(self):
        self.client.post("/admin/core/restaurant/add/", self.form_data())
        restaurant = Restaurant.objects.get(slug="spice-garden")
        self.assertEqual(self.edit(restaurant, email="boss@spice.in").status_code, 302)
        self.assertEqual(self.staff_of("ADMIN").user.username, "boss@spice.in")
        # the cafe put another contact email in Cafe profile: saving the admin form keeps the login
        Restaurant.objects.filter(pk=restaurant.pk).update(email="hello@spice.in")
        restaurant.refresh_from_db()
        self.assertEqual(self.edit(restaurant).status_code, 302)
        self.assertEqual(self.staff_of("ADMIN").user.username, "boss@spice.in")
        self.assertContains(self.edit(restaurant, email="free@x.test"), "Another login already has")

    def test_an_older_restaurant_without_admin_gets_one(self):
        old = make_restaurant("Old Cafe", email="old@cafe.in")
        self.assertEqual(self.edit(old).status_code, 302)  # no password: nothing made
        self.assertIsNone(old.admin_login())
        self.assertEqual(self.edit(old, admin_password="Old@20260").status_code, 302)
        self.assertEqual(old.admin_login().user.email, "old@cafe.in")


class ProfileFirstTests(TestCase):
    """A new cafe's admin: the cafe profile first (address, phone), then the staff logins."""

    def setUp(self):
        self.restaurant = make_restaurant("Green Leaf", address="", phone="")
        self.admin = make_staff(self.restaurant, "ADMIN")
        self.client = client_for(self.admin)

    def profile(self, **changes):
        return {"name": "Green Leaf", "address": "4 MG Road, Pune", "phone": "9876543210", "email": "",
                "gstin": "", "gst_percent": "5", "fssai_no": "", **changes}

    def test_first_login_opens_the_profile_with_the_steps(self):
        self.assertRedirects(self.client.get("/home/"), "/restaurant/", fetch_redirect_response=False)
        page = self.client.get("/restaurant/")
        self.assertContains(page, "Step 1 of 2: your cafe profile")
        self.assertContains(page, "address and phone number")

    def test_staff_waits_for_the_profile(self):
        self.assertContains(self.client.get("/staff/"), "First your cafe profile, then your staff")
        self.assertNotContains(self.client.get("/staff/"), 'hx-get="/staff/add/"')
        new = {"name": "Kavya", "email": "kavya@x.test", "role": "WAITER", "password": "Waiter@2026", "is_active": "on"}
        self.assertContains(self.client.post("/staff/add/", new, **HTMX), "Step 1 of 2")
        self.assertFalse(self.restaurant.staff_members.filter(name="Kavya").exists())

    def test_the_profile_needs_address_and_phone(self):
        self.assertContains(self.client.post("/restaurant/", self.profile(address="")), "This field is required")

    def test_saving_the_profile_goes_on_to_staff_then_staff_can_be_added(self):
        self.assertRedirects(self.client.post("/restaurant/", self.profile()), "/staff/", fetch_redirect_response=False)
        self.assertRedirects(self.client.get("/home/"), "/dashboard/", fetch_redirect_response=False)
        self.assertContains(self.client.get("/staff/"), 'hx-get="/staff/add/"')
        new = {"name": "Kavya", "email": "kavya@x.test", "role": "WAITER", "password": "Waiter@2026", "is_active": "on"}
        self.assertEqual(self.client.post("/staff/add/", new, **HTMX).status_code, 204)
        login = Client().post("/login/", {"username": "kavya@x.test", "password": "Waiter@2026"})
        self.assertEqual(login.status_code, 302)  # the waiter signs in (no tick)
        # later saves stay on the profile
        self.assertRedirects(self.client.post("/restaurant/", self.profile()), "/restaurant/", fetch_redirect_response=False)

    def test_other_roles_go_to_their_own_screen(self):
        waiter = client_for(make_staff(self.restaurant, "WAITER"))
        self.assertNotEqual(waiter.get("/home/")["Location"], "/restaurant/")


class RoleAndLimitTests(TestCase):
    def setUp(self):
        self.restaurant = make_restaurant(max_users=2)
        self.admin = make_staff(self.restaurant, "ADMIN")
        self.client = client_for(self.admin)

    def test_waiter_cannot_open_dashboard_or_staff(self):
        waiter = client_for(make_staff(self.restaurant, "WAITER"))
        self.assertEqual(waiter.get("/dashboard/").status_code, 403)
        self.assertEqual(waiter.get("/staff/").status_code, 403)

    def test_login_limit_counts_the_admin(self):
        new = {"name": "Kavya", "email": "kavya@x.test", "role": "KITCHEN", "password": "Kitchen@2026", "is_active": "on"}
        self.assertEqual(self.client.post("/staff/add/", new, **HTMX).status_code, 204)  # 2 of 2
        new.update(email="ravi@x.test")
        self.assertContains(self.client.post("/staff/add/", new, **HTMX), "allows 2 active logins")

    def test_staff_of_another_restaurant_is_not_found(self):
        other = make_staff(make_restaurant("Blue Bay"), "WAITER")
        self.assertEqual(self.client.get(f"/staff/{other.pk}/edit/", **HTMX).status_code, 404)


class SliderTests(TestCase):
    """Restaurant settings: up to three photos for the public menu's slider (slide 1 is the restaurant)."""

    def setUp(self):
        import tempfile
        from django.test import override_settings
        media = override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="resto-test-media-"))
        media.enable()
        self.addCleanup(media.disable)
        self.restaurant = make_restaurant()
        self.client = client_for(make_staff(self.restaurant, "ADMIN"))

    def details(self, **extra):
        r = self.restaurant
        return {"name": r.name, "address": r.address, "phone": r.phone, "email": r.email,
                "gstin": "", "gst_percent": "5", "fssai_no": "", **extra}

    def photo(self, name="offer.png", size=(40, 20)):
        from io import BytesIO
        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image
        out = BytesIO()
        Image.new("RGB", size, (200, 80, 20)).save(out, "PNG")
        return SimpleUploadedFile(name, out.getvalue(), content_type="image/png")

    def test_add_a_slide_and_it_shows_on_the_public_menu(self):
        self.client.post("/restaurant/", self.details(slide_2=self.photo(), slide_2_text="20% off on weekdays"))
        self.restaurant.refresh_from_db()
        self.assertEqual([s["text"] for s in self.restaurant.slides()], ["20% off on weekdays"])

        menu = Client().get(f"/r/{self.restaurant.slug}/")
        self.assertContains(menu, "gm-slide--photo")
        self.assertContains(menu, "20% off on weekdays")
        self.assertContains(menu, 'data-slide-to="1"')  # a dot for slide 2

    def test_remove_a_slide(self):
        self.client.post("/restaurant/", self.details(slide_1=self.photo(), slide_1_text="Rooftop"))
        self.client.post("/restaurant/", self.details(remove_slide_1="on"))
        self.restaurant.refresh_from_db()
        self.assertEqual(self.restaurant.slides(), [])
        self.assertNotContains(Client().get(f"/r/{self.restaurant.slug}/"), "data-slide-to")  # no dots for one slide

    def test_django_admin_has_the_slider_uploads(self):
        from django.contrib.auth.models import User
        developer = Client()
        developer.force_login(User.objects.create_superuser("dev", email="dev@x.test", password="Dev@12345"))
        page = developer.get(f"/admin/core/restaurant/{self.restaurant.pk}/change/")
        self.assertContains(page, "Public menu slider")
        self.assertContains(page, 'name="slide_1"')
        self.assertContains(page, 'name="slide_3_text"')

    def test_photo_over_2_mb_is_refused(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        big = SimpleUploadedFile("big.png", self.photo().read() + b"0" * (2 * 1024 * 1024), content_type="image/png")
        response = self.client.post("/restaurant/", self.details(slide_1=big))
        self.assertContains(response, "under 2 MB")
        self.restaurant.refresh_from_db()
        self.assertFalse(self.restaurant.slide_1)

    def test_profile_saves_when_a_saved_photo_file_is_missing(self):
        """A photo whose file has gone (site moved, backup restored) does not block saving."""
        type(self.restaurant).objects.filter(pk=self.restaurant.pk).update(slide_1="slides/gone.jpg")
        response = self.client.post("/restaurant/", self.details(phone="020 9999 0000"))
        self.assertRedirects(response, "/restaurant/")
        self.restaurant.refresh_from_db()
        self.assertEqual(self.restaurant.phone, "020 9999 0000")


class DashboardTests(TestCase):
    """The analyst dashboard: Today / This week / This month / Range, compared with the period before."""

    def setUp(self):
        from core.testing import guest_orders, make_menu, make_table
        from orders.models import Order
        self.restaurant = make_restaurant()
        _, paneer, naan = make_menu(self.restaurant)
        guest_orders(Client(), make_table(self.restaurant), [paneer, paneer, naan])  # 558 + GST = 586
        self.admin = client_for(make_staff(self.restaurant, "ADMIN"))
        self.admin.post(f"/billing/create/{Order.objects.get().pk}/", {"discount_type": "AMOUNT"})

    def test_today_by_default_with_every_panel(self):
        page = self.admin.get("/dashboard/")
        for text in ("Right now", "Net sales", "₹586", "Sales by hour", "Dine in, takeaway, delivery", "Payment modes",
                     "Busiest hours", "Categories", "Top dishes", "Who took the orders", "Latest bills",
                     'id="periodFilter"', "Period", "no earlier figures",
                     # the CEO sections: every module
                     "When sales come in", 'class="heat"', "Slow movers", "Discounts and offers", "Operations",
                     "Kitchen", "Ready within 15 min", "Tables", "Deliveries", "At the door within 45 min",
                     "Guests and team", "Bookings", "Who took the money", "What leaks away", "Items per bill",
                     'class="stack-bar"'):  # (one hour of sales: no sparkline to draw yet)
            self.assertContains(page, text)
        self.assertContains(page, 'data-search="paneer tikka starters"')
        self.assertContains(page, 'hx-trigger="liveChanged from:body, every 60s"')

    def test_week_month_and_range_compare_with_the_period_before(self):
        from datetime import timedelta
        from billing.models import Bill
        from django.utils import timezone
        today = timezone.localdate()
        Bill.objects.update(bill_date=today - timedelta(days=40))  # last month's bill only
        month = self.admin.get("/dashboard/?when=month", HTTP_HX_REQUEST="true")
        self.assertContains(month, "Sales by day")
        self.assertContains(month, "No bills in this period yet.")
        old = (today - timedelta(days=40)).isoformat()
        ranged = self.admin.get(f"/dashboard/?when=range&from={old}&to={old}", HTTP_HX_REQUEST="true")
        self.assertContains(ranged, "₹586")
        future = (today + timedelta(days=5)).isoformat()
        self.assertContains(self.admin.get(f"/dashboard/?when=range&from={future}&to={future}"), today.strftime("%d %b %Y"))

    def test_operations_figures(self):
        """Kitchen prep time, table stay and the heat map come from the real orders."""
        from datetime import timedelta
        from django.utils import timezone
        from core.analytics import heatmap, kitchen_figures, table_figures
        from billing.models import Bill
        from orders.models import KOT, Order
        place = self.restaurant.main_location()
        today = timezone.localdate()
        kot = KOT.objects.get()
        KOT.objects.filter(pk=kot.pk).update(status="READY", ready_at=kot.created_at + timedelta(minutes=12))
        kitchen = kitchen_figures(place, today, today)
        self.assertEqual((kitchen["kots"], kitchen["avg_prep"], kitchen["on_time"]), (1, 12, 100))
        # at noon, so the 50 minutes stay inside today whatever the clock says when the test runs
        noon = timezone.make_aware(timezone.datetime.combine(today, timezone.datetime.min.time().replace(hour=12)))
        Order.objects.filter(pk=Order.objects.get().pk).update(status="CLOSED", created_at=noon,
                                                               closed_at=noon + timedelta(minutes=50))
        tables = table_figures(place, today, today, 1)
        self.assertEqual((tables["orders"], tables["avg_stay"], tables["turns"]), (1, 50, 1.0))
        heat = heatmap(Bill.objects.all())
        self.assertEqual(sum(cell["level"] == 5 for row in heat["rows"] for cell in row["cells"]), 1)  # the busiest cell

    def test_change_against_the_day_before(self):
        from datetime import timedelta
        from billing.models import Bill
        from django.utils import timezone
        bill = Bill.objects.get()
        Bill.objects.create(restaurant=self.restaurant, order=bill.order.__class__.objects.create(
            restaurant=self.restaurant, order_no=99, customer_name="Old", table=bill.order.table, status="CLOSED"),
            bill_no=99, bill_date=timezone.localdate() - timedelta(days=1), grand_total=293, status="PAID")
        self.assertContains(self.admin.get("/dashboard/"), "up 100%")  # 586 today, 293 yesterday


class LocationTests(TestCase):
    """One company, two outlets: own tables, own numbers, staff mapped to locations."""

    def setUp(self):
        from core.models import Location
        from core.testing import make_menu, make_table
        self.restaurant = make_restaurant()
        self.main = self.restaurant.main_location()
        self.mg_road = Location.objects.create(restaurant=self.restaurant, name="MG Road")
        _, self.paneer, _ = make_menu(self.restaurant)
        self.t1_main = make_table(self.restaurant, "T1")  # the main location's
        from tables.models import DiningTable
        self.t1_mg = DiningTable.objects.create(restaurant=self.restaurant, location=self.mg_road, name="T1")

    def test_every_location_counts_its_own_numbers(self):
        from core.testing import guest_orders
        from orders.models import KOT, Order
        guest_orders(Client(), self.t1_main, [self.paneer])
        guest_orders(Client(), self.t1_mg, [self.paneer])
        orders = {o.location.name: (o.order_no, o.kots.get().kot_no) for o in Order.objects.select_related("location")}
        self.assertEqual(orders, {"Main": (1, 1), "MG Road": (1, 1)})  # both start at 1
        self.assertEqual(KOT.objects.get(location=self.mg_road).order.table, self.t1_mg)

    def test_rm_works_only_at_their_location(self):
        rm = make_staff(self.restaurant, "RM")
        rm.locations.set([self.mg_road])
        client = client_for(rm)
        floor = client.get("/floor/")
        self.assertNotContains(floor, "location-chip")  # one location: no switcher
        self.assertContains(floor, f'href="/waiter/order/{self.t1_mg.pk}/"')
        self.assertNotContains(floor, f'href="/waiter/order/{self.t1_main.pk}/"')
        self.assertEqual(client.get(f"/floor/table/{self.t1_main.pk}/").status_code, 404)
        client.post("/location/", {"location": self.main.pk, "next": "/floor/"})  # not theirs: nothing changes
        self.assertContains(client.get("/floor/"), f'href="/waiter/order/{self.t1_mg.pk}/"')

    def test_manager_switches_between_every_location(self):
        manager = client_for(make_staff(self.restaurant, "MANAGER"))
        page = manager.get("/floor/")
        self.assertContains(page, "location-chip")
        self.assertContains(page, f'href="/waiter/order/{self.t1_main.pk}/"')
        response = manager.post("/location/", {"location": self.mg_road.pk, "next": "/floor/"})
        self.assertRedirects(response, "/floor/", fetch_redirect_response=False)
        self.assertContains(manager.get("/floor/"), f'href="/waiter/order/{self.t1_mg.pk}/"')

    def test_public_menu_of_another_location(self):
        from tables.models import takeaway_table
        page = Client().get(f"/r/{self.restaurant.slug}/?at={self.mg_road.pk}")
        counter = takeaway_table(self.restaurant, self.mg_road)
        self.assertContains(page, f"/m/{counter.qr_token}/cart/add/")
        self.assertEqual(counter.menu_path, f"/r/{self.restaurant.slug}/?at={self.mg_road.pk}")
        self.assertEqual(takeaway_table(self.restaurant).menu_path, f"/r/{self.restaurant.slug}/")

    def test_staff_mapped_in_the_form_and_locations_tab(self):
        admin = client_for(make_staff(self.restaurant, "ADMIN"))
        self.assertContains(admin.get("/locations/"), "MG Road")
        form = admin.get("/staff/add/", HTTP_HX_REQUEST="true")
        self.assertContains(form, "Works at")
        data = {"name": "Ravi", "phone": "", "role": "RM", "email": "ravi@x.test", "password": "Strong@pass9",
                "is_active": "on"}
        self.assertContains(admin.post("/staff/add/", data, HTTP_HX_REQUEST="true"), "the one location")
        response = admin.post("/staff/add/", {**data, "locations": [self.mg_road.pk]}, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 204)
        from core.models import Staff
        self.assertEqual(Staff.objects.get(name="Ravi").allowed_locations(), [self.mg_road])

    def test_manager_cannot_touch_the_admin_login(self):
        admin = make_staff(self.restaurant, "ADMIN")
        manager = client_for(make_staff(self.restaurant, "MANAGER"))
        self.assertEqual(manager.get(f"/staff/{admin.pk}/edit/", HTTP_HX_REQUEST="true").status_code, 404)
        self.assertNotContains(manager.get("/staff/add/", HTTP_HX_REQUEST="true"), 'value="ADMIN"')
        self.assertContains(manager.get("/staff/"), "Who can do what")


class RoleAuditTests(TestCase):
    """Every role, on the demo restaurant with live orders: every page it reaches opens,
    and no page shows it a link or button that would refuse it (core/roles.py)."""

    @classmethod
    def setUpTestData(cls):
        from io import StringIO
        from django.core.management import call_command
        call_command("seed_demo", "--with-orders", stdout=StringIO())

    def crawl(self, staff):
        import re
        from collections import deque
        from urllib.parse import urljoin, urlparse
        from django.urls import Resolver404, resolve

        def allowed(view):
            while view is not None and not hasattr(view, "allowed_roles"):
                view = getattr(view, "__wrapped__", None)
            return getattr(view, "allowed_roles", None)

        client = Client()
        client.force_login(staff.user)
        problems, seen, per_view = [], set(), {}
        queue = deque([("/home/", False, "start")])
        while queue:
            url, htmx, came_from = queue.popleft()
            path = urlparse(url).path
            if url in seen or path.startswith(("/static/", "/media/", "/admin/", "/logout/", "/r/", "/m/", "/track/", "/booking/")):
                continue
            seen.add(url)
            try:
                name = resolve(path).view_name
            except Resolver404:
                problems.append(f"no such page {url} (on {came_from})")
                continue
            per_view[name] = per_view.get(name, 0) + 1
            if per_view[name] > 2:
                continue
            response = client.get(url, **({"HTTP_HX_REQUEST": "true"} if htmx else {}))
            if response.status_code in (301, 302):
                queue.append((response["Location"], False, url))
                continue
            if response.status_code >= 400:
                problems.append(f"{response.status_code} {url} (on {came_from})")
                continue
            if "html" not in response.get("Content-Type", ""):
                continue
            html = response.content.decode()
            for attr, link in re.findall(r'\b(href|hx-get|hx-post)="(/[^"]*)"', html):
                link = urljoin(url, link.replace("&amp;", "&"))
                if attr == "hx-post":
                    try:
                        roles_allowed = allowed(resolve(urlparse(link).path).func)
                    except Resolver404:
                        problems.append(f"button to no page {link} (on {url})")
                        continue
                    if roles_allowed and staff.role not in roles_allowed:
                        problems.append(f"button refuses {staff.role}: {link} (on {url})")
                else:
                    queue.append((link, attr == "hx-get", url))
        return problems

    def test_every_role_sees_only_what_it_may_use(self):
        restaurant = Restaurant.objects.get(slug="demo-spice-garden")
        for staff in restaurant.staff_members.all():
            with self.subTest(role=staff.role):
                self.assertEqual(self.crawl(staff), [])


class SlipTests(TestCase):
    """core/escpos.py: lines for 3-inch (80 mm) POS paper, 48 characters wide."""

    def lines(self, slip):
        import re
        text = re.sub(rb"\x1b[aE!d].|\x1d[!V].|\x1b@", b"", slip.to_bytes())  # drop the printer commands
        return text.decode("cp437").splitlines()

    def test_row_puts_the_amount_at_the_right_edge(self):
        from core.escpos import Slip
        slip = Slip()
        slip.row("Subtotal", "558.00")
        self.assertEqual(self.lines(slip), ["Subtotal" + " " * 34 + "558.00"])

    def test_a_long_dish_name_wraps_and_nothing_is_wider_than_the_paper(self):
        from core.escpos import Slip
        slip = Slip()
        slip.columns(["Paneer Butter Masala with Extra Cheese", 2, "249.00", "498.00"], (24, 5, 9, 10))
        first, second = self.lines(slip)
        self.assertTrue(first.startswith("Paneer Butter Masala") and first.endswith("498.00"))
        self.assertEqual(second.strip(), "with Extra Cheese")
        self.assertTrue(all(len(line) <= 48 for line in self.lines(slip)))

    def test_the_rupee_sign_prints_as_rs(self):
        from core.escpos import Slip
        slip = Slip()
        slip.row("TOTAL", "₹586.00", big=True)
        self.assertEqual(self.lines(slip), ["TOTAL" + " " * 10 + "Rs.586.00"])  # big letters: 24 a line


class DirectPrintTests(TestCase):
    """Setup > Printers, and the slips the print helper sends to the POS printer."""

    def setUp(self):
        from core.testing import guest_orders, make_menu, make_table
        self.restaurant = make_restaurant(address="MG Road, Pune", gstin="27ABCDE1234F1Z5")
        _, paneer, naan = make_menu(self.restaurant)
        guest_orders(Client(), make_table(self.restaurant), [paneer, paneer, naan])
        self.cashier = client_for(make_staff(self.restaurant, "CASHIER"))

    def test_printers_is_a_cafe_profile_tab_for_the_admin(self):
        admin = client_for(make_staff(self.restaurant, "ADMIN"))
        page = admin.get("/printers/")
        self.assertContains(page, 'id="printerSettings"')
        self.assertContains(page, "Download print helper")
        self.assertContains(page, 'class="profile-tab is-active"')
        self.assertNotContains(page, 'data-nav-tip="Printers"')  # not in the left menu
        self.assertNotContains(page, 'data-nav-tip="Cafe profile"')  # the account menu, top right, has it
        self.assertContains(page, '<i class="bi bi-shop" aria-hidden="true"></i> Create Update Profile</a>', html=False)
        self.assertContains(page, '<i class="bi bi-people" aria-hidden="true"></i> Staff</a>', html=False)
        self.assertNotContains(self.cashier.get("/floor/"), "Create Update Profile</a>")  # not the cashier's
        self.assertEqual(self.cashier.get("/printers/").status_code, 403)
        for role in ("KITCHEN", "WAITER"):
            self.assertEqual(client_for(make_staff(self.restaurant, role)).get("/printers/").status_code, 403)

    def test_bill_slip(self):
        from billing.models import Bill
        from orders.models import Order
        self.cashier.post(f"/billing/create/{Order.objects.get().pk}/", {"discount_type": "AMOUNT"})
        bill = Bill.objects.get()
        page = self.cashier.get(f"/billing/{bill.pk}/")
        self.assertContains(page, f'data-print-slip="/billing/{bill.pk}/print/slip/"')

        slip = self.cashier.get(f"/billing/{bill.pk}/print/slip/")
        self.assertEqual(slip["Content-Type"], "application/octet-stream")
        data = slip.content
        for text in (b"Spice Garden", b"TAX INVOICE", b"GSTIN: 27ABCDE1234F1Z5", b"Paneer Tikka", b"Rs.586.00"):
            self.assertIn(text, data)
        self.assertTrue(data.endswith(b"\x1dV\x01"))  # the paper is cut

    def test_kot_slip_has_no_prices(self):
        from orders.models import KOT
        kot = KOT.objects.get()
        kitchen = client_for(make_staff(self.restaurant, "KITCHEN"))
        data = kitchen.get(f"/kot/{kot.pk}/print/slip/").content
        self.assertIn(b"KITCHEN ORDER TICKET", data)
        self.assertIn(b"  2  Paneer Tikka", data)
        self.assertNotIn(b"249", data)
        self.assertEqual(client_for(make_staff(self.restaurant, "RIDER")).get(f"/kot/{kot.pk}/print/slip/").status_code, 403)

    def test_test_slip_and_helper_download(self):
        import io
        import zipfile
        admin = client_for(make_staff(self.restaurant, "ADMIN"))
        data = admin.get("/printers/test/?for=kot&printer=TVS RP3160").content
        self.assertIn(b"PRINTER TEST", data)
        self.assertIn(b"prints the KOTs", data)

        download = admin.get("/printers/helper.zip")
        files = zipfile.ZipFile(io.BytesIO(download.content))
        self.assertEqual(sorted(files.namelist()), ["README.txt", "Start Mr Cafe print.bat", "mrcafe_print.py"])
        self.assertIn(b"--site http://testserver", files.read("Start Mr Cafe print.bat"))


class BillSettingsTests(TestCase):
    """Cafe profile > Bill & print: one setting for every bill, on paper and on screen."""

    def setUp(self):
        import tempfile
        from django.test import override_settings
        from core.testing import guest_orders, make_menu, make_table
        from orders.models import Order
        media = override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="resto-test-media-"))
        media.enable()
        self.addCleanup(media.disable)
        self.restaurant = make_restaurant(gstin="27ABCDE1234F1Z5")
        _, paneer, _ = make_menu(self.restaurant)
        guest_orders(Client(), make_table(self.restaurant), [paneer, paneer])
        self.admin = client_for(make_staff(self.restaurant, "ADMIN"))
        self.admin.post(f"/billing/create/{Order.objects.get().pk}/", {"discount_type": "AMOUNT"})
        from billing.models import Bill
        self.bill = Bill.objects.get()

    def picture(self, name, size=(60, 60)):
        from io import BytesIO
        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image
        out = BytesIO()
        Image.new("RGB", size, (10, 10, 10)).save(out, "PNG")
        return SimpleUploadedFile(name, out.getvalue(), content_type="image/png")

    def save(self, **settings):
        data = {"print_name": "", "invoice_title": "TAX INVOICE", "print_logo": "on", "print_tax_details": "on",
                "upi_id": "", "print_upi": "on", **settings}
        return self.admin.post("/restaurant/bill/", data)

    def test_admin_and_manager_set_it_and_it_is_a_profile_tab(self):
        page = self.admin.get("/restaurant/bill/")
        self.assertContains(page, "Bill &amp; print")
        self.assertContains(page, 'href="/printers/"')
        self.assertEqual(client_for(make_staff(self.restaurant, "MANAGER")).get("/restaurant/bill/").status_code, 200)
        for role in ("RM", "CASHIER"):
            self.assertEqual(client_for(make_staff(self.restaurant, role)).get("/restaurant/bill/").status_code, 403)

    def test_company_name_title_and_order_type_on_the_bill(self):
        self.assertEqual(self.save(print_name="Spice Garden Foods Pvt Ltd", invoice_title="bill").status_code, 302)
        page = self.admin.get(f"/billing/{self.bill.pk}/print/")
        self.assertContains(page, "Spice Garden Foods Pvt Ltd")
        self.assertContains(page, ">BILL<")
        self.assertContains(page, "Dine in · Table T1")
        slip = self.admin.get(f"/billing/{self.bill.pk}/print/slip/").content
        self.assertIn(b"Spice Garden Foods Pvt\n", slip)  # big letters: 24 a line, so it wraps
        self.assertIn(b"BILL\n", slip)
        self.assertIn(b"Dine in", slip)

    def test_tax_details_can_be_left_off(self):
        self.save(print_tax_details="")
        page = self.admin.get(f"/billing/{self.bill.pk}/print/")
        self.assertNotContains(page, "CGST")
        self.assertNotContains(page, "GSTIN")
        self.assertContains(page, "Taxes")  # one line, so the bill still adds up
        slip = self.admin.get(f"/billing/{self.bill.pk}/print/slip/").content
        self.assertNotIn(b"CGST", slip)
        self.assertIn(b"Taxes", slip)

    def test_logo_and_upi_print_while_the_bill_is_unpaid(self):
        self.admin.post("/restaurant/", {"name": "Spice Garden", "address": "12 Test Road", "phone": "9876500000", "email": "",
                                         "gstin": "", "gst_percent": "5", "fssai_no": "", "logo": self.picture("logo.png")})
        self.assertContains(self.save(upi_id="bad id"), "name@bank")
        self.save(upi_id="SpiceGarden@okicici", upi_qr=self.picture("upi.png"))
        self.restaurant.refresh_from_db()
        self.assertEqual(self.restaurant.upi_id, "spicegarden@okicici")

        from core.templatetags.money import inr
        amount = inr(self.bill.balance)
        page = self.admin.get(f"/billing/{self.bill.pk}/print/")
        self.assertContains(page, 'class="slip-logo"')
        # with a UPI ID the QR code is made for this bill, with the amount in it (not the uploaded picture)
        self.assertContains(page, 'class="slip-upi-qr" src="data:image/png;base64,')
        self.assertContains(page, f"Amount: {amount}")
        self.assertNotContains(page, "/upi/upi")
        self.assertContains(page, "UPI ID: spicegarden@okicici")
        slip = self.admin.get(f"/billing/{self.bill.pk}/print/slip/").content
        self.assertGreater(slip.count(b"\x1dv0\x00"), 1)  # the logo (one band), then the QR code
        self.assertIn(f"Amount: {amount}".replace("₹", "Rs.").encode(), slip)
        self.assertIn(b"UPI ID: spicegarden@okicici", slip)
        settings_page = self.admin.get("/restaurant/bill/")
        self.assertContains(settings_page, 'class="bill-preview-qr" src="data:image/png;base64,')

        from billing.models import Payment
        from billing.services import add_payments
        add_payments(self.bill, [(Payment.Mode.CASH, self.bill.balance, "")], None)
        page = self.admin.get(f"/billing/{self.bill.pk}/print/")
        self.assertNotContains(page, "Scan &amp; pay by UPI")  # paid: nothing to scan
        self.assertNotIn(b"Scan & pay", self.admin.get(f"/billing/{self.bill.pk}/print/slip/").content)

        self.save(upi_id="spicegarden@okicici", print_logo="", print_upi="")
        slip = self.admin.get(f"/billing/{self.bill.pk}/print/slip/").content
        self.assertNotIn(b"\x1dv0\x00", slip)
        self.assertNotIn(b"UPI", slip)
