from decimal import Decimal

from django.test import Client, TestCase

from core.testing import HTMX, client_for, guest_orders, make_menu, make_restaurant, make_staff, make_table
from orders.models import KOT, Order


class PlaceOrderTests(TestCase):
    def setUp(self):
        self.restaurant = make_restaurant()
        _, self.paneer, self.naan = make_menu(self.restaurant)
        self.table = make_table(self.restaurant)
        self.guest = Client()

    def test_two_orders_on_one_table_make_one_order_with_two_kots(self):
        guest_orders(self.guest, self.table, [self.paneer, self.paneer])
        guest_orders(Client(), self.table, [self.naan], name="Friend")  # another phone, same table

        self.assertEqual(Order.objects.filter(table=self.table).count(), 1)
        order = Order.objects.get(table=self.table)
        self.assertEqual(order.kots.count(), 2)
        self.assertEqual(list(order.kots.values_list("kot_no", flat=True)), [1, 2])

    def test_name_and_price_are_copied_onto_the_kot(self):
        guest_orders(self.guest, self.table, [self.paneer, self.paneer])
        self.paneer.name, self.paneer.price = "Paneer Tikka Special", Decimal("399")
        self.paneer.save()

        line = KOT.objects.get().items.get()
        self.assertEqual((line.item_name, line.rate, line.qty, line.amount), ("Paneer Tikka", Decimal("249"), 2, Decimal("498")))

    def test_numbers_start_at_one_in_each_restaurant(self):
        guest_orders(self.guest, self.table, [self.paneer])
        other = make_restaurant("Blue Bay")
        _, dish, _ = make_menu(other)
        guest_orders(Client(), make_table(other, "B1"), [dish])
        self.assertEqual(Order.objects.get(restaurant=other).order_no, 1)

    def test_switched_off_table_does_not_take_orders(self):
        self.table.is_active = False
        self.table.save()
        self.assertEqual(Client().get(f"/m/{self.table.qr_token}/").status_code, 404)

    def test_out_of_stock_dish_is_not_added(self):
        self.naan.is_available = False
        self.naan.save()
        self.guest.post(f"/m/{self.table.qr_token}/cart/add/{self.naan.pk}/", **HTMX)
        guest_orders(self.guest, self.table, [])
        self.assertFalse(Order.objects.exists())


class SeparateBillTests(TestCase):
    """Two people at one table can pay separately: each gets an order (and bill) of their own."""

    def setUp(self):
        self.restaurant = make_restaurant()
        _, self.paneer, self.naan = make_menu(self.restaurant)
        self.table = make_table(self.restaurant, "T4")
        self.menu = f"/m/{self.table.qr_token}/"

    def order(self, guest, dish, name, **extra):
        guest.post(f"{self.menu}cart/add/{dish.pk}/", **HTMX)
        return guest.post(f"{self.menu}place/", {"customer_name": name, **extra})

    def test_own_bill_makes_a_second_order_and_a_phone_keeps_its_own(self):
        meera, ravi = Client(), Client()
        self.order(meera, self.paneer, "Meera")

        ravi.post(f"{self.menu}cart/add/{self.naan.pk}/", **HTMX)
        self.assertContains(ravi.get(f"{self.menu}cart/"), "My own order")  # the choice shows
        ravi.post(f"{self.menu}place/", {"customer_name": "Ravi", "bill": "new"})
        self.assertEqual(Order.objects.filter(table=self.table).count(), 2)

        self.order(ravi, self.naan, "Ravi")  # no choice: Ravi's phone adds to Ravi's own order
        self.assertEqual(Order.objects.get(customer_name="Ravi").kots.count(), 2)
        self.assertEqual(Order.objects.get(customer_name="Meera").kots.count(), 1)

    def test_each_bill_is_paid_on_its_own(self):
        from billing.services import add_payment, make_bill
        self.order(Client(), self.paneer, "Meera")
        self.order(Client(), self.naan, "Ravi", bill="new")
        meera, ravi = Order.objects.get(customer_name="Meera"), Order.objects.get(customer_name="Ravi")
        cashier_staff = make_staff(self.restaurant, "CASHIER")
        bill = make_bill(meera, cashier_staff)
        add_payment(bill, "CASH", bill.grand_total, "", cashier_staff)
        meera.refresh_from_db()
        ravi.refresh_from_db()
        self.assertEqual((meera.status, ravi.status), ("CLOSED", "OPEN"))

        floor = client_for(cashier_staff).get("/floor/")
        self.assertContains(floor, "Order #2")  # Ravi's order still running on T4

    def test_waiter_starts_a_separate_bill_and_sees_both(self):
        self.order(Client(), self.paneer, "Meera")
        waiter = client_for(make_staff(self.restaurant, "WAITER"))
        self.assertContains(waiter.get(f"/waiter/order/{self.table.pk}/?bill=new"), 'value="new" checked')
        waiter.post(f"/waiter/order/{self.table.pk}/add/{self.naan.pk}/", **HTMX)
        waiter.post(f"/waiter/order/{self.table.pk}/place/", {"customer_name": "Ravi", "bill": "new"})
        self.assertEqual(Order.objects.filter(table=self.table, status="OPEN").count(), 2)

        self.assertContains(waiter.get("/floor/"), "2 bills")
        page = waiter.get(f"/floor/table/{self.table.pk}/")
        self.assertContains(page, "Meera")
        self.assertContains(page, "Ravi")
        self.assertContains(page, "Separate bill")


class PortionOrderTests(TestCase):
    """Guests order a dish by its size; KOT and bill show "Dish (Half)" at the Half price."""

    def setUp(self):
        from menu.models import MenuItemPortion
        self.restaurant = make_restaurant()
        _, self.dish, self.naan = make_menu(self.restaurant)
        self.half = MenuItemPortion.objects.create(item=self.dish, name="Half", price=Decimal("179"), sort_order=1)
        self.full = MenuItemPortion.objects.create(item=self.dish, name="Full", price=Decimal("329"), sort_order=2)
        self.table = make_table(self.restaurant)
        self.menu = f"/m/{self.table.qr_token}/"
        self.guest = Client()

    def add(self, item, portion=None):
        data = {"portion": portion.pk} if portion else {}
        return self.guest.post(f"{self.menu}cart/add/{item.pk}/", data, **HTMX)

    def test_each_size_is_its_own_line_on_kot_and_bill(self):
        self.add(self.dish, self.half)
        self.add(self.dish, self.half)
        self.add(self.dish, self.full)
        self.guest.post(f"{self.menu}place/", {"customer_name": "Meera"})

        lines = {line.item_name: (line.rate, line.qty) for line in KOT.objects.get().items.all()}
        self.assertEqual(lines, {"Paneer Tikka (Half)": (Decimal("179"), 2), "Paneer Tikka (Full)": (Decimal("329"), 1)})

        cashier = client_for(make_staff(self.restaurant, "CASHIER"))
        cashier.post(f"/billing/create/{Order.objects.get().pk}/", {"discount_type": "AMOUNT"})
        from billing.models import Bill
        bill = Bill.objects.get()
        self.assertEqual(bill.subtotal, Decimal("687"))
        self.assertEqual(bill.items.count(), 2)

    def test_a_sized_dish_needs_a_size(self):
        response = self.add(self.dish)
        self.assertIn("pick a size", response["HX-Trigger"])
        self.guest.post(f"{self.menu}place/", {"customer_name": "Meera"})
        self.assertFalse(Order.objects.exists())

    def test_another_dishes_portion_is_not_found(self):
        self.assertEqual(self.add(self.naan, self.half).status_code, 404)

    def test_menu_card_opens_details_with_the_sizes(self):
        menu = self.guest.get(self.menu)
        self.assertContains(menu, "2 sizes")
        self.assertContains(menu, f'id="ctl-{self.dish.pk}"')
        sheet = self.guest.get(f"{self.menu}dish/{self.dish.pk}/", **HTMX)
        self.assertContains(sheet, 'class="gm-sheet"')
        self.assertContains(sheet, f'value="{self.half.pk}"')
        self.assertContains(sheet, "₹329")
        page = self.guest.get(f"{self.menu}dish/{self.dish.pk}/")  # opened as a link: a page of its own
        self.assertContains(page, "Dish details")
        self.assertContains(Client().get(f"/r/{self.restaurant.slug}/dish/{self.dish.pk}/"), "Full")

    def test_add_from_the_details_sheet(self):
        response = self.guest.post(f"{self.menu}cart/put/{self.dish.pk}/", {"portion": self.full.pk, "qty": "3"}, **HTMX)
        self.assertIn("closeSheet", response["HX-Trigger"])
        self.assertContains(response, 'hx-swap-oob="true"')
        self.assertContains(self.guest.get(f"{self.menu}cart/"), "Paneer Tikka (Full)")
        self.assertContains(self.guest.get(f"{self.menu}cart/"), "₹987")  # 3 x 329

    def test_cart_delete_takes_the_whole_line_out(self):
        self.add(self.naan)
        self.add(self.naan)
        self.add(self.dish, self.half)
        response = self.guest.post(f"{self.menu}cart/remove/{self.naan.pk}/", {"view": "cart", "all": "1"}, **HTMX)
        self.assertNotContains(response, "Butter Naan")
        self.assertContains(response, "Paneer Tikka (Half)")
        self.assertContains(response, 'id="placeTotal" hx-swap-oob="true"')

    def test_hidden_dish_details_are_not_found(self):
        self.naan.is_active = False
        self.naan.save()
        self.assertEqual(self.guest.get(f"{self.menu}dish/{self.naan.pk}/", **HTMX).status_code, 404)


class PosScreenTests(TestCase):
    """The staff order screen works like a POS: tap a tile to add; − qty + on the tile,
    on each size and on the bill lines."""

    def setUp(self):
        from menu.models import MenuItemPortion
        self.restaurant = make_restaurant()
        _, self.paneer, self.naan = make_menu(self.restaurant)
        self.half = MenuItemPortion.objects.create(item=self.paneer, name="Half", price=Decimal("179"))
        self.table = make_table(self.restaurant)
        self.waiter = client_for(make_staff(self.restaurant, "WAITER"))
        self.screen = f"/waiter/order/{self.table.pk}/"

    def test_tiles_and_the_size_menu(self):
        page = self.waiter.get(self.screen)
        self.assertContains(page, 'class="pos-tile food-veg"', count=2)  # Paneer (opens its sizes) and Naan
        self.assertContains(page, "1 size · from")
        self.assertContains(page, f'id="step-{self.naan.pk}" hidden')  # no − qty + until it is in the round
        self.assertContains(page, f'id="step-{self.paneer.pk}-{self.half.pk}"')  # each size: Add, then − qty +
        self.assertContains(page, "All items <small>2</small>")

    def test_a_tap_sends_back_the_lines_the_tile_stepper_and_the_total(self):
        self.waiter.post(f"{self.screen}add/{self.naan.pk}/", **HTMX)
        response = self.waiter.post(f"{self.screen}add/{self.naan.pk}/", **HTMX)
        body = response.content.decode()
        self.assertIn(f'id="step-{self.naan.pk}" hx-swap-oob="true"', body)  # the tile's − 2 +
        self.assertIn('<span class="pos-step-count" aria-live="polite">2</span>', body.split('id="waiterSummary"')[0])
        self.assertContains(response, 'id="waiterSummary"')
        self.assertContains(response, "₹120.00")  # the total, 2 x 60
        # a size: its own − qty +, and the dish tile's count
        response = self.waiter.post(f"{self.screen}add/{self.paneer.pk}/", {"portion": self.half.pk}, **HTMX)
        self.assertContains(response, f'id="step-{self.paneer.pk}-{self.half.pk}" hx-swap-oob="true"')
        self.assertContains(response, f'id="tileqty-{self.paneer.pk}" hx-swap-oob="true">1<')
        # − on the tile, down to none: the stepper hides, the line leaves the bill
        self.waiter.post(f"{self.screen}remove/{self.naan.pk}/", **HTMX)
        response = self.waiter.post(f"{self.screen}remove/{self.naan.pk}/", **HTMX)
        self.assertContains(response, "Paneer Tikka (Half)")
        self.assertNotContains(response, "Butter Naan")
        self.assertContains(response, f'id="step-{self.naan.pk}" hidden hx-swap-oob="true"')

    def test_floor_counter_chips_and_free_table_opens_the_order_screen(self):
        floor = self.waiter.get("/floor/")
        self.assertContains(floor, "legend-chip legend-counter")  # Takeaway, next to Free / Occupied
        self.assertContains(floor, "New takeaway")
        self.assertContains(floor, 'hx-get="/tables/bookings/add/"')  # Book table: opens the booking form
        self.assertContains(floor, "rowsChanged from:body")  # a saved booking redraws the tables at once
        self.assertContains(floor, f'href="{self.screen}"')  # free table: straight to the POS screen
        cashier = client_for(make_staff(self.restaurant, "CASHIER"))
        self.assertContains(cashier.get("/floor/"), f'href="{self.screen}"')  # every Floor role: the same Floor
        kitchen = client_for(make_staff(self.restaurant, "KITCHEN"))
        self.assertEqual(kitchen.get("/floor/").status_code, 403)  # not a Floor role


class FloorPeriodTests(TestCase):
    """The floor's booking filter: Today (default), This week, This month, a Range."""

    def test_periods(self):
        from datetime import date

        from tables.periods import booking_period
        thursday = date(2026, 10, 22)
        self.assertEqual(booking_period({}, thursday), ("today", thursday, thursday))
        self.assertEqual(booking_period({"when": "week"}, thursday), ("week", thursday, date(2026, 10, 25)))  # to Sunday
        self.assertEqual(booking_period({"when": "month"}, thursday), ("month", thursday, date(2026, 10, 31)))
        picked = {"when": "range", "from": "2026-10-24", "to": "2026-10-28"}
        self.assertEqual(booking_period(picked, thursday), ("range", date(2026, 10, 24), date(2026, 10, 28)))
        # never before today, "to" never before "from", nonsense dates fall back
        past = {"when": "range", "from": "2026-10-01", "to": "2026-10-02"}
        self.assertEqual(booking_period(past, thursday), ("range", thursday, thursday))
        self.assertEqual(booking_period({"when": "range", "from": "2026-02-30"}, thursday), ("range", thursday, thursday))
        self.assertEqual(booking_period({"when": "anything"}, thursday), ("today", thursday, thursday))

    def test_floor_keeps_the_filter_when_it_refreshes(self):
        restaurant = make_restaurant()
        make_table(restaurant)
        page = client_for(make_staff(restaurant, "WAITER")).get("/floor/?when=week")
        self.assertContains(page, 'hx-get="/floor/?when=week"')
        self.assertContains(page, 'value="week" checked')
        self.assertContains(page, "No bookings in these days")  # the summary, not the tiles
        self.assertNotContains(page, "table-tile")


class TakeawayTests(TestCase):
    """Dine in or Take away. Take-away orders go on the default Takeaway table, many at once."""

    def setUp(self):
        self.restaurant = make_restaurant()
        _, self.paneer, self.naan = make_menu(self.restaurant)
        self.t1 = make_table(self.restaurant, "T1")

    def place(self, client, table, dishes, **details):
        menu = f"/m/{table.qr_token}/"
        for dish in dishes:
            client.post(f"{menu}cart/add/{dish.pk}/", **HTMX)
        return client.post(f"{menu}place/", {"customer_name": "Meera", **details})

    def test_take_away_from_a_table_is_its_own_order_on_the_takeaway_table(self):
        guest_orders(Client(), self.t1, [self.paneer])  # dine-in order on T1
        response = self.place(Client(), self.t1, [self.naan], order_type="TAKEAWAY", customer_phone="9876543210")
        self.assertEqual(response.status_code, 302)

        dine_in = Order.objects.get(order_type="DINE_IN")
        parcel = Order.objects.get(order_type="TAKEAWAY")
        self.assertEqual(dine_in.table, self.t1)
        self.assertTrue(parcel.table.is_takeaway)
        self.assertEqual((dine_in.kots.count(), parcel.kots.count()), (1, 1))

    def test_name_and_mobile_are_optional(self):
        menu = f"/m/{self.t1.qr_token}/"
        guest = Client()
        guest.post(f"{menu}cart/add/{self.naan.pk}/", **HTMX)
        response = guest.post(f"{menu}place/", {"order_type": "TAKEAWAY"})  # no name, no mobile
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Order.objects.get().customer_name, "Takeaway guest")

        guest.post(f"{menu}cart/add/{self.naan.pk}/", **HTMX)
        guest.post(f"{menu}place/", {})  # dine in, nothing filled in
        self.assertEqual(Order.objects.get(order_type="DINE_IN").customer_name, "Guest at T1")

    def test_public_menu_orders_take_away(self):
        from tables.models import takeaway_table
        counter = takeaway_table(self.restaurant)
        public = f"/r/{self.restaurant.slug}/"
        guest = Client()
        self.assertContains(guest.get(public), f'id="ctl-{self.naan.pk}"')  # + on every dish
        guest.post(f"/m/{counter.qr_token}/cart/add/{self.naan.pk}/", **HTMX)
        self.assertContains(guest.get(public), "View cart")
        self.assertContains(guest.get(f"/m/{counter.qr_token}/cart/"), f'href="{public}"')  # back to the public menu
        guest.post(f"/m/{counter.qr_token}/place/", {})
        order = Order.objects.get()
        self.assertEqual((order.order_type, order.table, order.customer_name), ("TAKEAWAY", counter, "Takeaway guest"))

        counter.is_active = False  # Takeaway switched off: the menu is view only
        counter.save()
        self.assertNotContains(Client().get(public), 'id="ctl-')

    def test_counter_qr_opens_the_one_public_menu(self):
        from tables.models import takeaway_table
        counter = takeaway_table(self.restaurant)
        public = f"/r/{self.restaurant.slug}/"
        self.assertRedirects(Client().get(f"/m/{counter.qr_token}/"), public, fetch_redirect_response=False)
        self.assertEqual(counter.menu_path, public)
        self.assertEqual(self.t1.menu_path, f"/m/{self.t1.qr_token}/")  # a dining table keeps its own QR menu
        admin = client_for(make_staff(self.restaurant, "ADMIN"))
        self.assertContains(admin.get("/tables/qr-sheet/"), "Scan to order take away or delivery")

    def test_many_parcels_can_be_open_at_once(self):
        from tables.models import takeaway_table
        counter = takeaway_table(self.restaurant)
        self.place(Client(), counter, [self.paneer], customer_phone="9876543210")
        self.place(Client(), counter, [self.naan], customer_phone="9876543211")
        self.assertEqual(Order.objects.filter(table=counter, status="OPEN", order_type="TAKEAWAY").count(), 2)

    def test_billed_table_starts_a_new_bill_or_takes_a_parcel(self):
        guest_orders(Client(), self.t1, [self.paneer])
        Order.objects.update(status="BILLED")
        self.place(Client(), self.t1, [self.naan])  # the billed order cannot grow: a new order, its own bill
        self.assertEqual(Order.objects.filter(table=self.t1, order_type="DINE_IN").count(), 2)
        self.place(Client(), self.t1, [self.naan], order_type="TAKEAWAY", customer_phone="9876543210")
        self.assertTrue(Order.objects.filter(order_type="TAKEAWAY").exists())

    def test_waiter_new_takeaway_and_kitchen_sees_a_parcel(self):
        waiter = client_for(make_staff(self.restaurant, "WAITER"))
        response = waiter.get("/waiter/takeaway/")
        counter_id = int(response.url.rstrip("/").split("/")[-1])
        waiter.post(f"/waiter/order/{counter_id}/add/{self.paneer.pk}/", **HTMX)
        response = waiter.post(f"/waiter/order/{counter_id}/place/", {"customer_name": "Ravi"})
        parcel = Order.objects.get()
        self.assertEqual((parcel.order_type, parcel.source, parcel.customer_name), ("TAKEAWAY", "WAITER", "Ravi"))
        self.assertRedirects(response, f"/floor/order/{parcel.pk}/", fetch_redirect_response=False)

        self.assertContains(waiter.get("/floor/"), "1 open take-away order")  # on the Takeaway chip
        self.assertContains(waiter.get(f"/floor/table/{counter_id}/"), f"#{parcel.order_no}")
        self.assertContains(waiter.get(f"/floor/order/{parcel.pk}/"), "Take-away order")
        kitchen = client_for(make_staff(self.restaurant, "KITCHEN"))
        self.assertContains(kitchen.get("/kitchen/"), f"Parcel #{parcel.order_no}")
        self.assertContains(kitchen.get(f"/kot/{parcel.kots.get().pk}/print/"), "TAKEAWAY - PACK IT")

    def test_one_order_type_per_staff_screen(self):
        """A table is Dine in only; the counter is New takeaway or New delivery, each its own screen."""
        waiter = client_for(make_staff(self.restaurant, "WAITER"))
        table_screen = waiter.get(f"/waiter/order/{self.t1.pk}/")
        self.assertContains(table_screen, '<input type="hidden" name="order_type" value="DINE_IN">', html=True)
        self.assertNotContains(table_screen, 'value="TAKEAWAY"')
        waiter.post(f"/waiter/order/{self.t1.pk}/add/{self.paneer.pk}/", **HTMX)
        waiter.post(f"/waiter/order/{self.t1.pk}/place/", {"order_type": "TAKEAWAY"})  # an old page: refused
        self.assertFalse(Order.objects.exists())

        counter = waiter.get("/waiter/takeaway/").url
        takeaway = waiter.get(counter)
        self.assertContains(takeaway, "New takeaway order")
        self.assertContains(takeaway, '<input type="hidden" name="order_type" value="TAKEAWAY">', html=True)
        delivery = waiter.get(counter + "?type=DELIVERY")
        self.assertContains(delivery, "New delivery order")
        self.assertContains(delivery, '<input type="hidden" name="order_type" value="DELIVERY">', html=True)
        self.assertNotContains(delivery, 'value="TAKEAWAY"')

    def test_cancel_a_billed_table_order_cancels_its_bill(self):
        from billing.models import Bill
        guest_orders(Client(), self.t1, [self.paneer])
        order = Order.objects.get()
        client_for(make_staff(self.restaurant, "CASHIER")).post(f"/billing/create/{order.pk}/", {"discount_type": "AMOUNT"})
        manager = client_for(make_staff(self.restaurant, "MANAGER"))
        page = manager.get(f"/floor/table/{self.t1.pk}/")
        self.assertContains(page, 'hx-target="#panel" hx-swap="innerHTML"')  # the panel opens, the live block stays
        self.assertContains(manager.get(f"/orders/{order.pk}/cancel/", **HTMX), "is cancelled with it")
        response = manager.post(f"/orders/{order.pk}/cancel/", {"reason": "Wrong table"}, **HTMX)
        self.assertEqual(response.status_code, 204)
        order.refresh_from_db()
        self.assertEqual((order.status, Bill.objects.get().status), ("CANCELLED", "CANCELLED"))


class DeliveryTests(TestCase):
    """Home delivery: public orders wait for a call, a rider takes them and collects the payment."""

    def setUp(self):
        from tables.models import takeaway_table
        self.restaurant = make_restaurant(delivery_charge=Decimal("30"), free_delivery_above=Decimal("500"))
        _, self.paneer, self.naan = make_menu(self.restaurant)
        self.counter = takeaway_table(self.restaurant)
        self.menu = f"/m/{self.counter.qr_token}/"
        self.cashier = client_for(make_staff(self.restaurant, "CASHIER"))
        self.kitchen = client_for(make_staff(self.restaurant, "KITCHEN"))
        self.rider_staff = make_staff(self.restaurant, "RIDER")
        self.rider = client_for(self.rider_staff)

    def order_delivery(self, dishes, **details):
        guest = Client()
        for dish in dishes:
            guest.post(f"{self.menu}cart/add/{dish.pk}/", **HTMX)
        data = {"order_type": "DELIVERY", "customer_name": "Meera", "customer_phone": "9876543210",
                "customer_address": "Flat 4, Lake Road, Camp", **details}
        return guest.post(f"{self.menu}place/", data)

    def step(self, client, order, step, **data):
        return client.post(f"/deliveries/{order.pk}/{step}/", data, **HTMX)

    def cook(self, order):
        for kot in order.kots.all():
            for status in ("PREPARING", "READY"):
                self.kitchen.post(f"/kot/{kot.pk}/status/{status}/", {"screen": "kitchen"}, **HTMX)

    def test_delivery_needs_name_mobile_and_address(self):
        response = self.order_delivery([self.paneer], customer_address="")
        self.assertContains(response, "address to deliver to")
        self.assertFalse(Order.objects.exists())

    def test_public_delivery_waits_for_a_call_before_the_kitchen(self):
        self.order_delivery([self.paneer])
        order = Order.objects.get()
        self.assertEqual((order.order_type, order.status, order.kots.get().status), ("DELIVERY", "PENDING", "HELD"))
        self.assertNotContains(self.kitchen.get("/kitchen/"), f"Delivery #{order.order_no}")
        self.assertContains(Client().get(f"/track/{order.public_token}/"), "will call you shortly")

        self.step(self.cashier, order, "confirm")
        order.refresh_from_db()
        self.assertEqual((order.status, order.kots.get().status), ("OPEN", "NEW"))
        self.assertContains(self.kitchen.get("/kitchen/"), f"Delivery #{order.order_no}")

    def test_whole_delivery_from_the_public_menu_to_the_door(self):
        """Point by point, as the screens do it: call to confirm, kitchen, bill, rider, paid at the door.
        Every step moves the live number, so the other screens redraw at once."""
        from billing.models import Bill
        live = lambda: self.cashier.get("/live/").json()["v"]
        start = live()
        self.order_delivery([self.paneer, self.naan])
        order = Order.objects.get()
        self.assertGreater(live(), start)
        board = self.cashier.get("/deliveries/")
        self.assertContains(board, "To confirm")
        self.assertContains(board, f'href="tel:{order.customer_phone}"')  # the Call button

        before = live()
        self.assertEqual(self.step(self.cashier, order, "confirm").status_code, 200)
        self.assertGreater(live(), before)
        self.cook(order)
        self.assertContains(self.cashier.get("/deliveries/"), "Ready for a rider")

        self.assertIn("Choose a rider first", self.step(self.cashier, order, "pickup")["HX-Trigger"])  # the toast
        self.step(self.cashier, order, "rider", rider=self.rider_staff.pk)
        self.assertIn("Make the bill first", self.step(self.rider, order, "pickup", screen="rider")["HX-Trigger"])
        self.cashier.post(f"/billing/create/{order.pk}/", {"discount_type": "AMOUNT"})
        bill = Bill.objects.get(order=order)
        self.assertEqual(bill.delivery_charge, Decimal("30"))  # 309 food, under the 500 free-delivery amount
        self.assertContains(self.rider.get("/rider/"), f"#{order.order_no}")

        self.step(self.rider, order, "pickup", screen="rider")
        self.step(self.rider, order, "deliver", screen="rider", mode="UPI")
        order.refresh_from_db()
        bill.refresh_from_db()
        self.assertIsNotNone(order.delivered_at)
        self.assertEqual((bill.status, order.status, bill.payments.get().mode), ("PAID", "CLOSED", "UPI"))
        self.assertContains(self.cashier.get("/deliveries/"), "Delivered today")

    def test_rider_filters_delivered_by_period_and_searches(self):
        from datetime import timedelta
        from django.utils import timezone
        self.order_delivery([self.paneer])
        order = Order.objects.get()
        self.step(self.cashier, order, "confirm")
        self.cook(order)
        self.step(self.cashier, order, "rider", rider=self.rider_staff.pk)
        self.cashier.post(f"/billing/create/{order.pk}/", {"discount_type": "AMOUNT"})
        self.step(self.rider, order, "pickup", screen="rider")
        self.step(self.rider, order, "deliver", screen="rider", mode="CASH", when="week")

        page = self.rider.get("/rider/")
        self.assertContains(page, 'id="periodFilter"')
        self.assertContains(page, "Delivered today")
        self.assertContains(page, f'data-search="#{order.order_no} meera 9876543210')
        Order.objects.filter(pk=order.pk).update(delivered_at=timezone.now() - timedelta(days=40))
        self.assertContains(self.rider.get("/rider/"), "Nothing delivered today.")
        old = (timezone.localdate() - timedelta(days=40)).isoformat()
        ranged = self.rider.get(f"/rider/?when=range&from={old}&to={old}", HTTP_HX_REQUEST="true")
        self.assertContains(ranged, f"#{order.order_no} · Meera")
        self.assertContains(ranged, 'hx-get="/rider/?when=range')

    def test_ride_time_from_pickup_to_door(self):
        from datetime import timedelta
        from django.utils import timezone
        self.order_delivery([self.paneer])
        order = Order.objects.get()
        self.step(self.cashier, order, "confirm")
        self.cook(order)
        self.step(self.cashier, order, "rider", rider=self.rider_staff.pk)
        self.cashier.post(f"/billing/create/{order.pk}/", {"discount_type": "AMOUNT"})
        self.step(self.rider, order, "pickup", screen="rider")
        Order.objects.filter(pk=order.pk).update(picked_up_at=timezone.now() - timedelta(minutes=12))
        self.assertContains(self.cashier.get("/deliveries/"), "On the way 12 min")
        self.assertContains(self.rider.get("/rider/"), "12 min")

        self.step(self.rider, order, "deliver", screen="rider", mode="UPI")
        now = timezone.now()
        Order.objects.filter(pk=order.pk).update(picked_up_at=now - timedelta(minutes=34), delivered_at=now)
        board = self.cashier.get("/deliveries/")
        self.assertContains(board, "Rider times today")
        self.assertContains(board, "Average ride 34 min")
        self.assertContains(board, '<span class="ride-time is-slow">', html=False)  # 30 min or more
        self.assertContains(self.rider.get("/rider/"), "took 34 min")

    def test_add_items_on_the_call_before_confirming(self):
        """The customer asks for more on the phone: the dishes join the same order, held till Confirm."""
        self.order_delivery([self.paneer])
        order = Order.objects.get()
        board = self.cashier.get("/deliveries/")
        add_url = f"/waiter/order/{order.table_id}/?type=DELIVERY&amp;add={order.pk}"
        self.assertContains(board, add_url)

        screen = self.cashier.get(f"/waiter/order/{order.table_id}/?type=DELIVERY&add={order.pk}")
        self.assertContains(screen, f"Add items · delivery #{order.order_no}")
        self.assertContains(screen, f'name="add_to" value="{order.pk}"')
        self.assertContains(screen, "Still to confirm")
        self.cashier.post(f"/waiter/order/{order.table_id}/add/{self.naan.pk}/", **HTMX)
        self.cashier.post(f"/waiter/order/{order.table_id}/add/{self.naan.pk}/", **HTMX)
        response = self.cashier.post(f"/waiter/order/{order.table_id}/place/",
                                     {"order_type": "DELIVERY", "add_to": order.pk, "note": "extra spicy"})
        self.assertRedirects(response, "/deliveries/", fetch_redirect_response=False)
        self.assertEqual(Order.objects.count(), 1)  # the same order, one more round
        self.assertEqual(sorted(order.kots.values_list("status", flat=True)), ["HELD", "HELD"])
        self.assertNotContains(self.kitchen.get("/kitchen/"), f"Delivery #{order.order_no}")

        self.step(self.cashier, order, "confirm")  # both rounds go to the kitchen together
        self.assertEqual(sorted(order.kots.values_list("status", flat=True)), ["NEW", "NEW"])

        # confirmed (cooking): one more call, the new round goes straight to the kitchen
        self.cashier.post(f"/waiter/order/{order.table_id}/add/{self.paneer.pk}/", **HTMX)
        self.cashier.post(f"/waiter/order/{order.table_id}/place/", {"order_type": "DELIVERY", "add_to": order.pk})
        self.assertEqual(order.kots.filter(status="NEW").count(), 3)

    def out_for_delivery(self):
        """A billed delivery the rider has picked up (paneer 249 + GST + delivery 30 = 291)."""
        self.order_delivery([self.paneer])
        order = Order.objects.get()
        self.step(self.cashier, order, "confirm")
        self.cook(order)
        self.step(self.cashier, order, "rider", rider=self.rider_staff.pk)
        self.cashier.post(f"/billing/create/{order.pk}/", {"discount_type": "AMOUNT"})
        self.step(self.rider, order, "pickup", screen="rider")
        return order

    def test_rider_takes_any_mode_with_a_reference(self):
        order = self.out_for_delivery()
        page = self.rider.get("/rider/")
        for mode in ("CASH", "CREDIT_CARD", "DEBIT_CARD", "UPI", "ONLINE"):
            self.assertContains(page, f'<option value="{mode}">', count=2)  # the mode and the split's second mode
        self.step(self.rider, order, "deliver", screen="rider", mode="DEBIT_CARD", reference="4421")
        payment = order.bill.payments.get()
        self.assertEqual((payment.mode, payment.reference_no), ("DEBIT_CARD", "4421"))

    def test_rider_splits_in_two_modes(self):
        from billing.models import Bill
        order = self.out_for_delivery()
        bill = Bill.objects.get(order=order)
        due = bill.balance
        too_much = self.step(self.rider, order, "deliver", screen="rider", mode="CASH", first_amount=str(due),
                             second_mode="UPI")
        self.assertIn("must be less than", too_much["HX-Trigger"])
        self.step(self.rider, order, "deliver", screen="rider", mode="CASH", first_amount="200", second_mode="UPI")
        bill.refresh_from_db()
        self.assertEqual(sorted((p.mode, p.amount) for p in bill.payments.all()),
                         [("CASH", Decimal("200.00")), ("UPI", due - Decimal("200.00"))])
        self.assertEqual(bill.status, "PAID")
        self.assertContains(self.cashier.get("/deliveries/"), "Cash with riders today")

    def test_reject_a_fake_order(self):
        self.order_delivery([self.paneer])
        order = Order.objects.get()
        self.cashier.post(f"/deliveries/{order.pk}/reject/", {"reason": "No answer"}, **HTMX)
        order.refresh_from_db()
        self.assertEqual((order.status, order.kots.get().status), ("CANCELLED", "CANCELLED"))

    def test_delivery_charge_and_free_delivery(self):
        from billing.services import make_bill
        from orders.services import place_kot
        cashier = self.restaurant.staff_members.get(role="CASHIER")
        small = place_kot(self.counter, [{"item": self.paneer, "qty": 1}], "Ravi", "9876543210",
                          customer_address="Camp", order_type="DELIVERY").order
        bill = make_bill(small, cashier)
        self.assertEqual((bill.delivery_charge, bill.taxable_amount), (Decimal("30.00"), Decimal("279.00")))
        big = place_kot(self.counter, [{"item": self.paneer, "qty": 3}], "Ravi", "9876543210",
                        customer_address="Camp", order_type="DELIVERY").order
        self.assertEqual(make_bill(big, cashier).delivery_charge, Decimal("0.00"))  # 747 >= 500: free

    def test_staff_delivery_rider_picks_up_and_collects(self):
        waiter = client_for(make_staff(self.restaurant, "WAITER"))
        waiter.post(f"/waiter/order/{self.counter.pk}/add/{self.paneer.pk}/", **HTMX)
        response = waiter.post(f"/waiter/order/{self.counter.pk}/place/", {
            "order_type": "DELIVERY", "customer_name": "Kabir", "customer_phone": "9876543211",
            "customer_address": "12 MG Road"})
        self.assertRedirects(response, "/deliveries/", fetch_redirect_response=False)
        order = Order.objects.get()
        self.assertEqual(order.status, "OPEN")  # taken by staff: straight to the kitchen

        self.step(self.cashier, order, "rider", rider=self.rider_staff.pk)
        self.cook(order)
        self.step(self.rider, order, "pickup")
        order.refresh_from_db()
        self.assertIsNone(order.picked_up_at)  # no bill yet: the rider would not know what to collect

        self.cashier.post(f"/billing/create/{order.pk}/", {"discount_type": "AMOUNT"})
        self.assertContains(self.rider.get("/rider/"), "Collect")
        self.step(self.rider, order, "pickup", screen="rider")
        self.step(self.rider, order, "deliver", mode="CASH", screen="rider")
        order.refresh_from_db()
        self.assertIsNotNone(order.delivered_at)
        self.assertEqual((order.status, order.bill.status), ("CLOSED", "PAID"))
        self.assertEqual(order.bill.payments.get().received_by, self.rider_staff)
        self.assertContains(self.cashier.get("/deliveries/"), "Cash with riders today")
        self.assertContains(Client().get(f"/track/{order.public_token}/"), "Delivered")

    def test_a_rider_only_moves_their_own_deliveries(self):
        from orders.services import place_kot
        order = place_kot(self.counter, [{"item": self.naan, "qty": 1}], "Ravi", "9876543210",
                          customer_address="Camp", order_type="DELIVERY").order
        other = client_for(make_staff(self.restaurant, "RIDER", email="rider2@x.test"))
        self.step(self.cashier, order, "rider", rider=self.rider_staff.pk)
        self.assertEqual(self.step(other, order, "pickup").status_code, 400)
        self.assertEqual(self.step(self.rider, order, "confirm").status_code, 400)
        self.assertEqual(self.rider.get("/floor/").status_code, 403)

    def test_cashier_takes_phone_and_table_orders(self):
        self.assertRedirects(self.cashier.get("/deliveries/new/"), f"/waiter/order/{self.counter.pk}/?type=DELIVERY",
                             fetch_redirect_response=False)
        self.assertContains(self.cashier.get(f"/waiter/order/{self.counter.pk}/?type=DELIVERY"), "New delivery order")
        table = make_table(self.restaurant, "T9")
        self.assertContains(self.cashier.get(f"/waiter/order/{table.pk}/"), "New KOT · Table T9")  # like every Floor role
        self.assertEqual(self.rider.get(f"/waiter/order/{table.pk}/").status_code, 403)

    def test_switched_off_delivery_is_not_offered(self):
        self.restaurant.delivery_enabled = False
        self.restaurant.save()
        guest = Client()
        guest.post(f"{self.menu}cart/add/{self.paneer.pk}/", **HTMX)
        self.assertNotContains(guest.get(f"{self.menu}cart/"), 'value="DELIVERY"')
        self.order_delivery([self.paneer])
        self.assertFalse(Order.objects.filter(order_type="DELIVERY").exists())


class KotStatusTests(TestCase):
    """Who may move a KOT where (orders/services.py, KOT_MOVES)."""

    def setUp(self):
        self.restaurant = make_restaurant()
        _, paneer, _ = make_menu(self.restaurant)
        guest_orders(Client(), make_table(self.restaurant), [paneer])
        self.kot = KOT.objects.get()
        self.kitchen = client_for(make_staff(self.restaurant, "KITCHEN"))
        self.waiter = client_for(make_staff(self.restaurant, "WAITER"))

    def move(self, client, status):
        client.post(f"/kot/{self.kot.pk}/status/{status}/", {"screen": "kitchen"}, **HTMX)
        self.kot.refresh_from_db()
        return self.kot.status

    def test_kitchen_cooks_waiter_serves(self):
        self.assertEqual(self.move(self.kitchen, "PREPARING"), "PREPARING")
        self.assertEqual(self.move(self.kitchen, "READY"), "READY")
        self.assertEqual(self.move(self.kitchen, "SERVED"), "READY")  # not the kitchen's job
        self.assertEqual(self.move(self.waiter, "SERVED"), "SERVED")
        self.assertIsNotNone(self.kot.ready_at)
        self.assertIsNotNone(self.kot.served_at)

    def test_waiter_checks_and_moves_kots_but_cannot_cancel_or_bill(self):
        """roles.py: the waiter sees the kitchen board and moves KOTs on; cancelling and billing are not theirs."""
        self.assertEqual(self.waiter.get("/kitchen/").status_code, 200)
        self.assertEqual(self.move(self.waiter, "CANCELLED"), "NEW")
        self.assertEqual(self.move(self.waiter, "PREPARING"), "PREPARING")
        self.assertEqual(self.waiter.get(f"/billing/create/{self.kot.order_id}/").status_code, 403)
        self.assertEqual(self.waiter.get("/billing/new/").status_code, 403)

    def test_waiter_sees_bills_and_amounts_only(self):
        from billing.models import Bill
        cashier = client_for(make_staff(self.restaurant, "CASHIER"))
        cashier.post(f"/billing/create/{self.kot.order_id}/", {"discount_type": "AMOUNT"})
        bill = Bill.objects.get()
        bills = self.waiter.get("/billing/")
        self.assertContains(bills, f"#{bill.bill_no}")
        self.assertNotContains(bills, "New bill</a>")
        page = self.waiter.get(f"/billing/{bill.pk}/")
        self.assertContains(page, "Balance")
        self.assertNotContains(page, 'id="payForm"')  # no payment
        self.assertNotContains(page, "Reopen for more orders")
        self.assertNotContains(page, "Cancel bill")
        self.assertEqual(self.waiter.get(f"/billing/{bill.pk}/print/").status_code, 200)
        self.assertEqual(self.waiter.post(f"/billing/{bill.pk}/pay/", {"mode": "CASH", "amount": "10"}, **HTMX).status_code, 403)
        table_page = self.waiter.get(f"/floor/table/{self.kot.order.table_id}/")
        self.assertContains(table_page, f"View bill #{bill.bill_no}")

    def test_rider_takes_no_orders_and_makes_no_kots(self):
        rider = client_for(make_staff(self.restaurant, "RIDER"))
        table = self.kot.order.table
        self.assertEqual(rider.get(f"/waiter/order/{table.pk}/").status_code, 403)
        self.assertEqual(rider.get("/waiter/takeaway/").status_code, 403)
        self.assertEqual(rider.get("/kitchen/").status_code, 403)
        self.assertEqual(self.move(rider, "PREPARING"), "NEW")
        self.assertEqual(rider.get("/rider/").status_code, 200)  # their own deliveries and their status

    def test_other_restaurant_cannot_touch_the_kot(self):
        outsider = client_for(make_staff(make_restaurant("Blue Bay"), "KITCHEN"))
        response = outsider.post(f"/kot/{self.kot.pk}/status/PREPARING/", {"screen": "kitchen"}, **HTMX)
        self.assertEqual(response.status_code, 404)

    def test_latest_kot_on_top_table_or_parcel(self):
        from tables.models import takeaway_table
        counter = takeaway_table(self.restaurant)
        paneer = self.kot.items.get().menu_item
        self.waiter.post(f"/waiter/order/{counter.pk}/add/{paneer.pk}/", **HTMX)
        self.waiter.post(f"/waiter/order/{counter.pk}/place/", {"order_type": "TAKEAWAY"})  # the newer KOT: a parcel
        board = self.kitchen.get("/kitchen/").content.decode()
        parcel = KOT.objects.exclude(pk=self.kot.pk).get()
        self.assertLess(board.index(f"KOT #{parcel.kot_no}<"), board.index(f"KOT #{self.kot.kot_no}<"))

        # Oldest first: picked once, then kept for the refreshes
        self.kitchen.get("/kitchen/?sort=old", **HTMX)
        board = self.kitchen.get("/kitchen/").content.decode()
        self.assertLess(board.index(f"KOT #{self.kot.kot_no}<"), board.index(f"KOT #{parcel.kot_no}<"))
        self.assertIn('value="old" checked', board)


class NotificationTests(TestCase):
    """The bell in the top bar: every new order rings it for everyone at the location;
    opening it (or Mark all as read) clears it for everyone."""

    def setUp(self):
        self.restaurant = make_restaurant()
        _, self.paneer, self.naan = make_menu(self.restaurant)
        self.table = make_table(self.restaurant)
        self.waiter = client_for(make_staff(self.restaurant, "WAITER"))
        self.cashier = client_for(make_staff(self.restaurant, "CASHIER"))

    def bell(self, client):
        return client.get("/notifications/", **HTMX)

    def test_a_new_order_rings_every_bell_once(self):
        guest_orders(Client(), self.table, [self.paneer])
        guest_orders(Client(), self.table, [self.naan], name="Friend")  # a second round: the same order
        for client in (self.waiter, self.cashier):
            page = self.bell(client)
            self.assertContains(page, 'class="notify-count" aria-hidden="true">1<')
            self.assertContains(page, "New dine in order #1")
            self.assertContains(page, "QR / online")
        self.assertContains(self.waiter.get("/floor/"), 'id="notifyBell"')

    def test_opening_it_shows_the_order_and_clears_it_for_everyone(self):
        from core.models import Restaurant
        from orders.models import Notification
        guest_orders(Client(), self.table, [self.paneer])
        note, order = Notification.objects.get(), Order.objects.get()
        before = Restaurant.objects.get(pk=self.restaurant.pk).live_version
        response = self.waiter.post(f"/notifications/{note.pk}/open/")
        self.assertRedirects(response, f"/floor/order/{order.pk}/")
        note.refresh_from_db()
        self.assertIsNotNone(note.read_at)
        self.assertEqual(note.read_by.role, "WAITER")
        self.assertGreater(Restaurant.objects.get(pk=self.restaurant.pk).live_version, before)  # other bells redraw
        page = self.bell(self.cashier)
        self.assertNotContains(page, "notify-count")
        self.assertContains(page, "You are all caught up.")

    def test_mark_all_as_read(self):
        guest_orders(Client(), self.table, [self.paneer])
        guest_orders(Client(), make_table(self.restaurant, "T2"), [self.naan])
        self.assertContains(self.bell(self.cashier), 'class="notify-count" aria-hidden="true">2<')
        page = self.cashier.post("/notifications/read-all/", **HTMX)
        self.assertContains(page, "You are all caught up.")
        self.assertNotContains(self.bell(self.waiter), "notify-count")

    def test_each_role_lands_on_its_own_screen(self):
        from orders.models import Notification
        guest_orders(Client(), self.table, [self.paneer])
        note = Notification.objects.get()
        kitchen = client_for(make_staff(self.restaurant, "KITCHEN"))
        self.assertRedirects(kitchen.post(f"/notifications/{note.pk}/open/"), "/kitchen/")
        rider = client_for(make_staff(self.restaurant, "RIDER"))
        self.assertRedirects(rider.post(f"/notifications/{note.pk}/open/"), "/rider/")

    def test_a_delivery_to_confirm_opens_the_deliveries_board(self):
        from orders.models import Notification
        from orders.services import place_kot
        place_kot(self.table, [{"item": self.paneer, "qty": 1}], "Asha", "9876500011",
                  customer_address="1 Road", order_type="DELIVERY", to_confirm=True)
        self.assertContains(self.bell(self.cashier), "To confirm")
        note = Notification.objects.get()
        self.assertRedirects(self.cashier.post(f"/notifications/{note.pk}/open/"), "/deliveries/",
                             fetch_redirect_response=False)

    def test_other_restaurants_and_locations_do_not_see_it(self):
        guest_orders(Client(), self.table, [self.paneer])
        other = make_restaurant("Blue Bay")
        self.assertNotContains(self.bell(client_for(make_staff(other, "WAITER"))), "notify-count")
        from orders.models import Notification
        note = Notification.objects.get()
        self.assertEqual(client_for(make_staff(other, "MANAGER")).post(f"/notifications/{note.pk}/open/").status_code, 404)
        self.assertEqual(Client().get("/notifications/").status_code, 302)  # not logged in: the login page
