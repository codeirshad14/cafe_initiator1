from datetime import timedelta

from django.test import Client, TestCase
from django.utils import timezone

from core.testing import HTMX, client_for, make_restaurant, make_staff, make_table
from tables.models import Booking


class PublicBookingTests(TestCase):
    """"Book a table" on the public menu: a request until staff confirm it."""

    def setUp(self):
        self.restaurant = make_restaurant()
        self.url = f"/r/{self.restaurant.slug}/book/"
        self.tomorrow = timezone.localdate() + timedelta(days=1)

    def book(self, **changes):
        data = {"date": self.tomorrow.isoformat(), "time": "20:00", "guests": "4",
                "customer_name": "Meera", "customer_phone": "9876543210", "note": "", **changes}
        return Client().post(self.url, data)

    def test_booking_is_requested_and_the_guest_sees_it(self):
        response = self.book()
        booking = Booking.objects.get()
        self.assertEqual((booking.status, booking.source, booking.booking_no, booking.guests), ("REQUESTED", "PUBLIC", 1, 4))
        self.assertRedirects(response, f"/booking/{booking.public_token}/", fetch_redirect_response=False)
        self.assertContains(Client().get(f"/booking/{booking.public_token}/"), "We will call you to confirm")
        self.assertNotContains(Client().get(f"/r/{self.restaurant.slug}/"), "Book a table")  # no button on the menu

    def test_past_and_far_bookings_are_refused(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        self.assertContains(self.book(date=yesterday.isoformat()), "today or a later day")
        far = timezone.localdate() + timedelta(days=45)
        self.assertContains(self.book(date=far.isoformat()), "up to 30 days ahead")
        self.assertContains(self.book(customer_phone=""), "mobile number")
        self.assertEqual(Booking.objects.count(), 0)

    def test_same_name_and_number_can_book_twice_a_day(self):
        self.book()
        self.book(time="21:00")  # lunch and dinner, same guest
        self.assertEqual(Booking.objects.count(), 2)

    def test_switched_off_bookings(self):
        self.restaurant.booking_enabled = False
        self.restaurant.save()
        self.assertEqual(Client().get(self.url).status_code, 404)
        self.assertNotContains(Client().get(f"/r/{self.restaurant.slug}/"), "Book a table")


class TableLabelTests(TestCase):
    """A table is "Table T1" in sentences, but a name that already says it stays as it is."""

    def test_no_table_table(self):
        restaurant = make_restaurant()
        self.assertEqual(make_table(restaurant, "T1").label, "Table T1")
        named = make_table(restaurant, "Table 1")
        self.assertEqual(named.label, "Table 1")
        page = Client().get(f"/m/{named.qr_token}/")
        self.assertContains(page, "Welcome to Table 1")
        self.assertNotContains(page, "Table Table")


class MenuQrTests(TestCase):
    """Three menus, one look: each table's (order dine in), the order menu (takeaway,
    delivery) and the view-only menu, each with its own QR code."""

    def setUp(self):
        from core.testing import make_menu
        self.restaurant = make_restaurant()
        _, self.paneer, _ = make_menu(self.restaurant)
        self.table = make_table(self.restaurant, "T1")

    def test_view_only_menu_has_no_ordering(self):
        slug = self.restaurant.slug
        page = Client().get(f"/r/{slug}/view/")
        self.assertContains(page, "Our menu")
        self.assertContains(page, "Paneer Tikka")
        self.assertContains(page, f"/r/{slug}/view/dish/{self.paneer.pk}/")
        self.assertNotContains(page, "cart/add")  # no + buttons
        self.assertNotContains(page, "gm-cart")
        dish = Client().get(f"/r/{slug}/view/dish/{self.paneer.pk}/")
        self.assertContains(dish, "Paneer Tikka")
        self.assertNotContains(dish, "cart/put")
        # the order menu and the table menu: the same page, with ordering
        self.assertContains(Client().get(f"/r/{slug}/"), "cart/add")
        table_menu = Client().get(f"/m/{self.table.qr_token}/")
        self.assertContains(table_menu, "cart/add")
        self.assertContains(table_menu, "Table T1")

    def test_tables_page_has_both_menu_qr_codes(self):
        manager = client_for(make_staff(self.restaurant, "MANAGER"))
        page = manager.get("/tables/")
        self.assertContains(page, "Order menu")
        self.assertContains(page, "View-only menu")
        self.assertContains(page, f'data-copy="http://testserver/r/{self.restaurant.slug}/view/"')
        for kind in ("order", "view"):
            png = manager.get(f"/tables/menu-qr/{kind}.png")
            self.assertEqual((png.status_code, png["Content-Type"]), (200, "image/png"))
        self.assertEqual(manager.get("/tables/menu-qr/other.png").status_code, 404)
        sheet = manager.get("/tables/qr-sheet/?menus=1")
        self.assertContains(sheet, "Scan to see our menu")
        self.assertContains(sheet, "Scan to order takeaway or delivery")

    def test_qr_with_label_downloads_a_small_printable_card(self):
        from io import BytesIO
        from PIL import Image
        manager = client_for(make_staff(self.restaurant, "MANAGER"))
        page = manager.get("/tables/")
        self.assertContains(page, "/tables/menu-qr/view.png?download=1&amp;card=1")
        self.assertContains(page, f"/tables/{self.table.pk}/qr.png?download=1&amp;card=1")
        for url, filename in (("/tables/menu-qr/view.png", "qr-view-menu-card.png"),
                              ("/tables/menu-qr/order.png", "qr-order-menu-card.png"),
                              (f"/tables/{self.table.pk}/qr.png", "qr-t1-card.png")):
            with self.subTest(url=url):
                card = manager.get(f"{url}?download=1&card=1")
                self.assertEqual(card["Content-Type"], "image/png")
                self.assertIn(f'filename="{filename}"', card["Content-Disposition"])
                self.assertEqual(Image.open(BytesIO(card.content)).size, (620, 880))  # about A6, not a poster
        plain = Image.open(BytesIO(manager.get("/tables/menu-qr/view.png?download=1").content))
        self.assertLess(plain.size[0], 620)  # "QR" alone is still the bare code

    def test_the_card_foot_is_one_small_row_with_the_website(self):
        from PIL import Image, ImageDraw
        from tables.qr_card import WIDTH, fitting_font, powered_by
        self.assertEqual(powered_by(), "Powered by Mr Cafe (www.cafe.initiatorsolutions.com)")
        draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        self.assertLessEqual(draw.textlength(powered_by(), font=fitting_font(draw, powered_by(), 16, WIDTH - 40)), WIDTH - 40)


class StaffBookingTests(TestCase):
    """Staff: add a phone booking, give a table, confirm, seat; the floor shows it."""

    def setUp(self):
        self.restaurant = make_restaurant()
        self.t1 = make_table(self.restaurant, "T1")
        self.cashier = client_for(make_staff(self.restaurant, "CASHIER"))
        self.today = timezone.localdate()
        # booked for tomorrow, so the tests pass at any hour (late at night "today 11:30 PM" may have passed)
        self.tomorrow = self.today + timedelta(days=1)

    def add(self, **changes):
        data = {"date": self.tomorrow.isoformat(), "time": "23:30", "guests": "2", "customer_name": "Kabir",
                "customer_phone": "9876543211", "note": "", "table": self.t1.pk, "status": "CONFIRMED", **changes}
        return self.cashier.post("/tables/bookings/add/", data, **HTMX)

    def test_phone_booking_shows_on_the_floor(self):
        self.assertEqual(self.add().status_code, 204)
        booking = Booking.objects.get()
        self.assertEqual((booking.status, booking.source, booking.table), ("CONFIRMED", "STAFF", self.t1))
        # the floor shows today's bookings by default: tomorrow's does not make the table red today
        self.assertNotContains(self.cashier.get("/floor/"), "table-tile tile-booked")
        # a range shows only the date-wise summary: the booking with its time, table and an Edit button
        day = self.tomorrow.isoformat()
        summary = self.cashier.get(f"/floor/?when=range&from={day}&to={day}")
        self.assertContains(summary, "summary-day")
        self.assertContains(summary, "11:30 PM")
        self.assertContains(summary, "Table T1")
        self.assertContains(summary, f'hx-get="/tables/bookings/{booking.pk}/edit/"')
        self.assertNotContains(summary, "table-tile")  # no tiles, so no order or bill for a later day
        # that day's tables as small cards: T1 red (booked), T2 green with "book it" for that day
        t2 = make_table(self.restaurant, "T2")
        summary = self.cashier.get(f"/floor/?when=range&from={day}&to={day}")
        self.assertContains(summary, 'class="mini-tile tile-booked"')
        self.assertContains(summary, f'hx-get="/tables/bookings/add/?day={day}&amp;table={t2.pk}"')
        self.assertContains(self.cashier.get(f"/tables/bookings/add/?day={day}&table={t2.pk}", **HTMX),
                            f'<option value="{t2.pk}" selected>')
        Booking.objects.update(date=self.today)  # the day comes: on today's floor (red only near 11:30 PM)
        self.assertContains(self.cashier.get("/floor/"), "11:30 PM")
        self.assertContains(self.cashier.get("/tables/bookings/"), "Kabir")

    def at(self, day, hour, minute=0):
        """A moment on that day (for the floor's "booked now" window)."""
        from datetime import datetime, time
        return timezone.make_aware(datetime.combine(day, time(hour, minute)))

    def test_floor_shows_red_only_near_the_booking_time(self):
        from datetime import time

        from orders.staff_views import floor_tables, mark_bookings
        Booking.objects.create(restaurant=self.restaurant, booking_no=1, customer_name="Kabir",
                               customer_phone="9876543211", guests=2, date=self.tomorrow, time=time(20, 0),
                               table=self.t1, status="CONFIRMED")

        def state_at(hour, minute=0):
            tables = floor_tables(self.restaurant.main_location())
            mark_bookings(tables, self.restaurant.main_location(), self.at(self.tomorrow, hour, minute))
            t1 = next(t for t in tables if t.pk == self.t1.pk)
            return t1.state, t1.booking is not None

        self.assertEqual(state_at(12), ("free", True))  # booked later today: green, with a "Booked 8:00 PM" note
        self.assertEqual(state_at(19, 15), ("booked", True))  # the hour before: red, held for them
        self.assertEqual(state_at(21, 30), ("booked", True))  # still held (two hours after)
        self.assertEqual(state_at(22, 30), ("free", False))  # long past: it no longer holds the table

    def test_staff_change_the_status_even_with_two_bookings_on_one_number(self):
        from datetime import time
        t2 = make_table(self.restaurant, "T2")
        self.add()  # Kabir, tomorrow 11:30 PM on T1
        self.assertEqual(self.add(time="13:00", table=t2.pk).status_code, 204)  # same mobile, same day: fine for staff
        lunch = Booking.objects.get(time=time(13, 0))
        for status in ("SEATED", "NO_SHOW", "CANCELLED", "REQUESTED", "CONFIRMED"):
            data = {"date": lunch.date.isoformat(), "time": "13:00", "guests": "2", "customer_name": "Kabir",
                    "customer_phone": "9876543211", "note": "", "table": t2.pk, "status": status}
            self.assertEqual(self.cashier.post(f"/tables/bookings/{lunch.pk}/edit/", data, **HTMX).status_code, 204, status)
            lunch.refresh_from_db()
            self.assertEqual(lunch.status, status)

    def test_a_table_with_two_bookings_shows_plus_one(self):
        from datetime import time

        from orders.staff_views import floor_tables, mark_bookings
        for no, at in ((1, time(13, 0)), (2, time(20, 0))):
            Booking.objects.create(restaurant=self.restaurant, booking_no=no, customer_name="Guest",
                                   customer_phone=f"98765432{no:02d}", guests=2, date=self.tomorrow, time=at,
                                   table=self.t1, status="CONFIRMED")
        tables = floor_tables(self.restaurant.main_location())
        mark_bookings(tables, self.restaurant.main_location(), self.at(self.tomorrow, 10))
        t1 = next(t for t in tables if t.pk == self.t1.pk)
        self.assertEqual((t1.booking.time, t1.more_bookings), (time(13, 0), 1))  # "Booked 1:00 PM +1"
        day = self.tomorrow.isoformat()
        summary = self.cashier.get(f"/floor/?when=range&from={day}&to={day}")
        self.assertContains(summary, '<span class="mini-tile-more">+1</span>')

    def test_a_booking_has_a_length(self):
        from datetime import date, time
        from tables.models import length_text
        # no "until": the usual two hours; else exactly what was set
        self.add()
        kabir = Booking.objects.get()
        self.assertEqual((kabir.end_date, kabir.end_time, kabir.length_text), (self.tomorrow + timedelta(days=1), time(1, 30), "2 h"))
        t2 = make_table(self.restaurant, "T2")
        self.add(time="19:00", end_date=self.tomorrow.isoformat(), end_time="19:30", table=t2.pk, customer_name="Cake")
        self.assertEqual(Booking.objects.get(customer_name="Cake").length_text, "30 min")
        self.assertEqual([length_text(timedelta(minutes=m)) for m in (90, 2880, 1680)], ["1 h 30 min", "2 days", "1 day 4 h"])
        # an "until" before the start, or longer than a week: refused
        self.assertContains(self.add(time="19:00", end_time="18:00", table=""), "has to end after it starts")
        far = (self.tomorrow + timedelta(days=9)).isoformat()
        self.assertContains(self.add(time="19:00", end_date=far, end_time="19:00", table=""), "can last up to 7 days")

    def test_a_two_day_wedding_holds_the_table_both_days(self):
        from datetime import time

        from orders.staff_views import floor_tables, mark_bookings
        day2 = self.tomorrow + timedelta(days=1)
        wedding = {"time": "18:00", "end_date": day2.isoformat(), "end_time": "23:00", "customer_name": "Wedding"}
        self.assertEqual(self.add(**wedding).status_code, 204)
        # the same table at an overlapping time, on the second day: refused
        clash = self.add(date=day2.isoformat(), time="12:00", customer_name="Lunch", customer_phone="9876543212")
        self.assertContains(clash, "Table T1 is booked")
        # the second day at noon: the table is red (held), with "Since ..."
        tables = floor_tables(self.restaurant.main_location())
        mark_bookings(tables, self.restaurant.main_location(), self.at(day2, 12))
        self.assertEqual(next(t for t in tables if t.pk == self.t1.pk).state, "booked")
        # the date-wise list shows it on both days
        summary = self.cashier.get(f"/floor/?when=range&from={self.tomorrow}&to={day2}")
        self.assertContains(summary, "Wedding <small>", count=2)  # its row on each day
        self.assertContains(summary, "2 days")

    def test_guest_picks_how_long(self):
        from datetime import time
        restaurant = self.restaurant
        restaurant.booking_enabled = True
        restaurant.save()
        Client().post(f"/r/{restaurant.slug}/book/", {
            "date": self.tomorrow.isoformat(), "time": "20:00", "length": "30", "guests": "4",
            "customer_name": "Meera", "customer_phone": "9876543210", "note": ""})
        booking = Booking.objects.get()
        self.assertEqual((booking.end_time, booking.length_text), (time(20, 30), "30 min"))

    def test_guests_arrived_seats_them_and_opens_their_order(self):
        booking = Booking.objects.create(restaurant=self.restaurant, booking_no=1, customer_name="Kabir",
                                         customer_phone="9876543211", guests=2, date=self.today,
                                         time=timezone.localtime().time(), table=self.t1, status="CONFIRMED")
        waiter = client_for(make_staff(self.restaurant, "WAITER"))
        url = f"/tables/bookings/{booking.pk}/arrive/"
        self.assertContains(waiter.get(url, **HTMX), "Guests arrived")
        response = waiter.post(url, **HTMX)
        self.assertEqual(response["HX-Redirect"], f"/waiter/order/{self.t1.pk}/")
        booking.refresh_from_db()
        self.assertEqual(booking.status, "SEATED")

        # a cashier: the same Floor as the waiter, straight on to the table's order screen
        booking.status = "CONFIRMED"
        booking.save()
        response = self.cashier.post(url, **HTMX)
        self.assertEqual(response["HX-Redirect"], f"/waiter/order/{self.t1.pk}/")

    def test_bookings_page_has_the_floors_filter(self):
        self.add()  # tomorrow
        page = self.cashier.get("/tables/bookings/")  # today by default
        self.assertContains(page, 'id="periodFilter"')
        self.assertContains(page, "No bookings in these days")
        week = self.cashier.get(f"/tables/bookings/?when=range&from={self.tomorrow}&to={self.tomorrow}")
        self.assertContains(week, "Kabir")
        self.assertContains(week, 'hx-include="#periodFilter"')  # its buttons keep the days picked
        self.assertNotContains(page, "wait as <strong>Requested</strong>")  # the long line under the title is gone

    def test_one_table_is_not_booked_twice_at_the_same_time(self):
        self.add()
        response = self.add(customer_phone="9876543212", customer_name="Isha", time="23:00")
        self.assertContains(response, "Table T1 is booked")
        self.assertEqual(Booking.objects.count(), 1)

    def test_confirm_seat_and_no_show(self):
        booking = Booking.objects.create(restaurant=self.restaurant, booking_no=1, customer_name="Meera",
                                         customer_phone="9876543210", guests=2, date=self.today,
                                         time=timezone.localtime().time())
        self.cashier.post(f"/tables/bookings/{booking.pk}/confirm/", **HTMX)
        booking.refresh_from_db()
        self.assertEqual(booking.status, "CONFIRMED")
        self.cashier.post(f"/tables/bookings/{booking.pk}/seated/", **HTMX)
        booking.refresh_from_db()
        self.assertEqual(booking.status, "SEATED")
        self.cashier.post(f"/tables/bookings/{booking.pk}/noshow/", **HTMX)  # already seated: no change
        booking.refresh_from_db()
        self.assertEqual(booking.status, "SEATED")

    def test_other_restaurant_cannot_touch_a_booking(self):
        self.add()
        outsider = client_for(make_staff(make_restaurant("Blue Bay"), "CASHIER"))
        booking = Booking.objects.get()
        self.assertEqual(outsider.post(f"/tables/bookings/{booking.pk}/confirm/", **HTMX).status_code, 404)
        self.assertNotContains(outsider.get("/tables/bookings/"), "Kabir")
