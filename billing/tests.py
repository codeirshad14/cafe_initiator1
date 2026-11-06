from decimal import Decimal as D

from django.test import Client, TestCase

from billing.calc import bill_totals, discount_amount_for
from billing.models import Bill
from core.testing import HTMX, client_for, guest_orders, make_menu, make_restaurant, make_staff, make_table
from orders.models import Order


class BillTotalsTests(TestCase):
    """Discount, CGST / SGST and round off (billing/calc.py)."""

    def test_gst_is_split_half_and_half(self):
        totals = bill_totals(D("1000"), D("0"), D("5"))
        self.assertEqual((totals["cgst_amount"], totals["sgst_amount"], totals["grand_total"]), (D("25.00"), D("25.00"), D("1050.00")))
        self.assertEqual(totals["round_off"], D("0.00"))

    def test_percent_discount_and_rounding_down(self):
        discount = discount_amount_for(D("1179"), "PERCENT", 10)
        totals = bill_totals(D("1179"), discount, D("5"))
        # 1179 - 117.90 = 1061.10; 2.5% = 26.5275 -> 26.53 each; 1114.16 -> 1114
        self.assertEqual(discount, D("117.90"))
        self.assertEqual(totals["taxable_amount"], D("1061.10"))
        self.assertEqual(totals["cgst_amount"], D("26.53"))
        self.assertEqual(totals["grand_total"], D("1114.00"))
        self.assertEqual(totals["round_off"], D("-0.16"))

    def test_half_rupee_rounds_up(self):
        totals = bill_totals(D("230"), D("0"), D("5"))  # 230 + 11.50 = 241.50
        self.assertEqual((totals["grand_total"], totals["round_off"]), (D("242.00"), D("0.50")))

    def test_discount_is_never_more_than_the_subtotal(self):
        self.assertEqual(discount_amount_for(D("100"), "AMOUNT", 500), D("100.00"))
        self.assertEqual(discount_amount_for(D("100"), "PERCENT", 150), D("100.00"))


class NewBillTests(TestCase):
    """"New bill" on the Bills page: a counter sale, picked on the POS screen and billed straight away."""

    def setUp(self):
        from tables.models import takeaway_table
        self.restaurant = make_restaurant()
        _, self.paneer, _ = make_menu(self.restaurant)
        self.counter = takeaway_table(self.restaurant)
        self.cashier = client_for(make_staff(self.restaurant, "CASHIER"))

    def test_new_bill_goes_from_dishes_to_the_bill(self):
        self.assertContains(self.cashier.get("/billing/"), 'href="/billing/new/"')
        page = self.cashier.get("/billing/new/")  # the POS screen on the counter, in "bill" mode
        self.assertContains(page, "Make bill")
        self.assertContains(page, 'name="then" value="bill"')
        self.assertContains(page, f'action="/waiter/order/{self.counter.pk}/place/"')

        self.cashier.post(f"/waiter/order/{self.counter.pk}/add/{self.paneer.pk}/", **HTMX)
        response = self.cashier.post(f"/waiter/order/{self.counter.pk}/place/", {"order_type": "TAKEAWAY", "then": "bill"})
        order = Order.objects.get()
        self.assertEqual((order.order_type, order.kots.count()), ("TAKEAWAY", 1))  # the kitchen still gets the KOT
        self.assertRedirects(response, f"/billing/create/{order.pk}/", fetch_redirect_response=False)
        self.cashier.post(f"/billing/create/{order.pk}/", {"discount_type": "AMOUNT"})
        self.assertEqual(Bill.objects.get(order=order).subtotal, D("249"))

    def test_waiters_do_not_make_bills(self):
        waiter = client_for(make_staff(self.restaurant, "WAITER"))
        self.assertEqual(waiter.get("/billing/new/").status_code, 403)
        self.assertNotContains(waiter.get(f"/waiter/order/{self.counter.pk}/?then=bill"), "Make bill")

    def test_bills_page_lists_orders_still_to_bill(self):
        table = make_table(self.restaurant)
        guest_orders(Client(), table, [self.paneer])
        order = Order.objects.get()
        page = self.cashier.get("/billing/")
        self.assertContains(page, "To bill")
        self.assertContains(page, f'href="/billing/create/{order.pk}/"')  # Make bill
        self.assertContains(page, "₹249")
        self.cashier.post(f"/billing/create/{order.pk}/", {"discount_type": "AMOUNT"})  # billed: off the list
        self.assertNotContains(self.cashier.get("/billing/to-make/", **HTMX), f'href="/billing/create/{order.pk}/"')

    def test_bill_register_stops_at_today(self):
        from datetime import timedelta

        from django.utils import timezone
        today = timezone.localdate()
        later = (today + timedelta(days=5)).isoformat()
        page = self.cashier.get(f"/billing/?date_from={later}&date_to={later}")
        self.assertContains(page, f'max="{today.isoformat()}"')
        self.assertEqual(page.context["date_to"], today)


class FestivalOfferTests(TestCase):
    """Cafe profile > Offers: ₹ or % off every bill, on chosen days only."""

    def setUp(self):
        from datetime import timedelta
        from django.utils import timezone
        self.today = timezone.localdate()
        self.yesterday = self.today - timedelta(days=1)
        self.restaurant = make_restaurant()
        _, self.paneer, self.naan = make_menu(self.restaurant)
        self.table = make_table(self.restaurant)
        guest_orders(Client(), self.table, [self.paneer, self.paneer, self.naan])  # 558
        self.order = Order.objects.get()
        self.admin = client_for(make_staff(self.restaurant, "ADMIN"))
        self.cashier = client_for(make_staff(self.restaurant, "CASHIER"))

    def add_offer(self, **data):
        fields = {"name": "Valentine's Day", "start_date": self.today.isoformat(), "end_date": self.today.isoformat(),
                  "kind": "PERCENT", "value": "5", "min_bill": "0", "is_active": "on", **data}
        return self.admin.post("/billing/offers/add/", fields, **HTMX)

    def test_admin_adds_an_offer_in_the_cafe_profile(self):
        self.assertEqual(self.add_offer().status_code, 204)
        page = self.admin.get("/billing/offers/")
        self.assertContains(page, "Valentine&#x27;s Day")
        self.assertContains(page, "Running today")
        self.assertContains(page, 'class="profile-tab is-active"')
        self.assertContains(self.add_offer(end_date=self.yesterday.isoformat()), "on or after the day it starts")
        self.assertContains(self.add_offer(value="150"), "more than 100%")
        self.assertEqual(self.cashier.get("/billing/offers/").status_code, 403)

    def test_running_offer_is_applied_and_printed(self):
        self.add_offer()
        page = self.cashier.get(f"/billing/create/{self.order.pk}/")
        self.assertContains(page, "applied today")
        self.assertContains(page, '<input type="radio" name="discount_type" value="PERCENT"', count=1)
        self.cashier.post(f"/billing/create/{self.order.pk}/", {"discount_type": "PERCENT", "discount_value": "5.00"})
        bill = Bill.objects.get()
        self.assertEqual((bill.discount_amount, bill.offer_name), (D("27.90"), "Valentine's Day"))  # 5% of 558
        self.assertContains(self.cashier.get(f"/billing/{bill.pk}/print/"), "Discount (Valentine&#x27;s Day)")

    def test_cashier_changed_discount_is_not_the_offer(self):
        self.add_offer()
        self.cashier.post(f"/billing/create/{self.order.pk}/", {"discount_type": "AMOUNT", "discount_value": "10"})
        bill = Bill.objects.get()
        self.assertEqual((bill.discount_amount, bill.offer_name), (D("10.00"), ""))

    def test_offer_only_on_its_days_and_from_its_minimum(self):
        from billing.services import offer_for
        self.add_offer(name="Yesterday", start_date=self.yesterday.isoformat(), end_date=self.yesterday.isoformat())
        self.add_offer(name="Big bills", kind="AMOUNT", value="100", min_bill="1000")
        self.assertIsNone(offer_for(self.restaurant, self.today, D("558")))
        self.assertEqual(offer_for(self.restaurant, self.today, D("1200")).name, "Big bills")
        self.add_offer(name="Switched off", is_active="")
        self.assertNotContains(self.cashier.get(f"/billing/create/{self.order.pk}/"), "applied today")


class UpiQrTests(TestCase):
    """Take payment > Show UPI QR: a QR code with the balance in it (upi://pay), a customer
    screen for a second monitor, and one tap to record the UPI payment."""

    def setUp(self):
        self.restaurant = make_restaurant(upi_id="spicegarden@okicici")
        _, paneer, naan = make_menu(self.restaurant)
        guest_orders(Client(), make_table(self.restaurant), [paneer, paneer, naan])  # 558 -> bill 586
        self.cashier = client_for(make_staff(self.restaurant, "CASHIER"))
        self.cashier.post(f"/billing/create/{Order.objects.get().pk}/", {"discount_type": "AMOUNT"})
        self.bill = Bill.objects.get()

    def test_the_link_carries_the_upi_id_name_and_amount(self):
        from billing.upi import upi_link
        link = upi_link(self.restaurant, D("586"), "Bill 1 Spice Garden")
        self.assertEqual(link, "upi://pay?pa=spicegarden@okicici&pn=Spice%20Garden&am=586.00&cu=INR&tn=Bill%201%20Spice%20Garden")

    def test_show_the_qr_with_the_balance_then_record_it(self):
        self.cashier.post(f"/billing/{self.bill.pk}/pay/", {"mode": "CASH", "amount": "86"}, **HTMX)
        self.assertContains(self.cashier.get(f"/billing/{self.bill.pk}/"), "Show UPI QR for ₹500.00")
        panel = self.cashier.get(f"/billing/{self.bill.pk}/upi/", **HTMX)
        self.assertContains(panel, f"/billing/{self.bill.pk}/upi.png?v=500.00")
        self.assertContains(panel, "spicegarden@okicici")
        picture = self.cashier.get(f"/billing/{self.bill.pk}/upi.png")
        self.assertEqual((picture["Content-Type"], picture.content[:4]), ("image/png", b"\x89PNG"))
        screen = self.cashier.get(f"/billing/{self.bill.pk}/upi/screen/")
        self.assertContains(screen, 'hx-trigger="every 3s"')  # asks again until paid
        self.assertContains(screen, "₹500.00")

        paid = self.cashier.post(f"/billing/{self.bill.pk}/upi/paid/", {"reference_no": "UTR4417"}, **HTMX)
        self.assertIn("closePanel", paid["HX-Trigger"])
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.status, "PAID")
        upi = self.bill.payments.get(mode="UPI")
        self.assertEqual((upi.amount, upi.reference_no), (D("500"), "UTR4417"))
        done = self.cashier.get(f"/billing/{self.bill.pk}/upi/screen/", **HTMX)
        self.assertContains(done, "Payment received")
        self.assertNotContains(done, "every 3s")  # stops asking
        self.assertEqual(self.cashier.get(f"/billing/{self.bill.pk}/upi.png").status_code, 404)  # nothing to pay

    def test_without_a_upi_id(self):
        self.restaurant.upi_id = ""
        self.restaurant.save()
        panel = self.cashier.get(f"/billing/{self.bill.pk}/upi/", **HTMX)
        self.assertContains(panel, "No UPI ID yet")
        self.assertNotContains(panel, "Paid by UPI")
        self.assertEqual(self.cashier.get(f"/billing/{self.bill.pk}/upi.png").status_code, 404)

    def test_only_billing_staff(self):
        waiter = client_for(make_staff(self.restaurant, "WAITER"))
        self.assertEqual(waiter.get(f"/billing/{self.bill.pk}/upi/screen/").status_code, 403)
        self.assertEqual(waiter.post(f"/billing/{self.bill.pk}/upi/paid/", **HTMX).status_code, 403)
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.paid_amount, D("0"))


class BillingFlowTests(TestCase):
    def setUp(self):
        self.restaurant = make_restaurant()
        _, self.paneer, self.naan = make_menu(self.restaurant)
        self.table = make_table(self.restaurant)
        guest_orders(Client(), self.table, [self.paneer, self.paneer, self.naan])  # 558
        self.order = Order.objects.get()
        self.cashier = client_for(make_staff(self.restaurant, "CASHIER"))

    def make_bill(self, **discount):
        self.cashier.post(f"/billing/create/{self.order.pk}/", {"discount_type": "AMOUNT", **discount})
        return Bill.objects.get(order=self.order)

    def pay(self, bill, mode, amount):
        self.cashier.post(f"/billing/{bill.pk}/pay/", {"mode": mode, "amount": amount}, **HTMX)
        bill.refresh_from_db()
        self.order.refresh_from_db()

    def test_bill_is_made_from_all_rounds_with_gst(self):
        guest_orders(Client(), self.table, [self.naan])  # a 2nd round: naan merges into one line
        bill = self.make_bill(discount_value="18")
        self.assertEqual(bill.subtotal, D("618"))
        self.assertEqual(bill.items.get(item_name="Butter Naan").qty, 2)
        self.assertEqual(bill.discount_amount, D("18"))
        self.assertEqual(bill.cgst_amount, D("15.00"))  # 600 x 2.5%
        self.assertEqual(bill.grand_total, D("630"))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "BILLED")

    def test_multi_mode_payment_closes_the_order_only_when_covered(self):
        bill = self.make_bill()  # 558 + 27.90 = 585.90 -> 586
        self.assertEqual(bill.grand_total, D("586"))

        self.pay(bill, "CASH", "300")
        self.assertEqual((bill.status, self.order.status), ("PARTIAL", "BILLED"))

        self.pay(bill, "UPI", "1000")  # more than the balance: refused
        self.assertEqual(bill.paid_amount, D("300"))

        self.pay(bill, "UPI", "286")
        self.assertEqual((bill.status, bill.paid_amount, self.order.status), ("PAID", D("586"), "CLOSED"))
        self.assertIsNotNone(self.order.closed_at)

    def test_split_payment_two_modes_at_once(self):
        bill = self.make_bill()  # 586
        page = self.cashier.get(f"/billing/{bill.pk}/")
        self.assertContains(page, "Split: 2 modes")
        pay = f"/billing/{bill.pk}/pay/"

        # same mode twice, or no second amount: refused, nothing saved
        self.cashier.post(pay, {"mode": "CASH", "amount": "300", "split": "on", "mode2": "CASH", "amount2": "286"}, **HTMX)
        self.cashier.post(pay, {"mode": "CASH", "amount": "300", "split": "on", "mode2": "UPI"}, **HTMX)
        # together more than the balance: refused, nothing saved
        self.cashier.post(pay, {"mode": "CASH", "amount": "300", "split": "on", "mode2": "UPI", "amount2": "500"}, **HTMX)
        self.assertFalse(bill.payments.exists())

        # cash 300 (guest gives 500) + UPI 286: both saved, bill paid, change for the cash part
        response = self.cashier.post(pay, {"mode": "CASH", "amount": "300", "tendered": "500", "split": "on",
                                           "mode2": "UPI", "amount2": "286", "reference_no2": "UPI123"}, **HTMX)
        bill.refresh_from_db()
        self.assertEqual(sorted(bill.payments.values_list("mode", "amount")), [("CASH", D("300")), ("UPI", D("286"))])
        self.assertEqual(bill.status, "PAID")
        self.assertEqual(bill.payments.get(mode="UPI").reference_no, "UPI123")
        self.assertIn("200.00 change", response["HX-Trigger"])  # 500 given - 300 cash

    def test_reopened_order_keeps_its_bill_number(self):
        bill = self.make_bill()
        self.cashier.post(f"/billing/{bill.pk}/reopen/")
        guest_orders(Client(), self.table, [self.naan])
        redone = self.make_bill()
        self.assertEqual((redone.pk, redone.bill_no, redone.subtotal), (bill.pk, 1, D("618")))

    def test_bills_of_another_restaurant_are_not_found(self):
        bill = self.make_bill()
        outsider = client_for(make_staff(make_restaurant("Blue Bay"), "CASHIER"))
        self.assertEqual(outsider.get(f"/billing/{bill.pk}/").status_code, 404)
        self.assertEqual(outsider.get(f"/billing/{bill.pk}/print/").status_code, 404)
        self.assertEqual(outsider.post(f"/billing/{bill.pk}/pay/", {"mode": "CASH", "amount": "1"}, **HTMX).status_code, 404)

    def test_waiter_cannot_bill(self):
        waiter = client_for(make_staff(self.restaurant, "WAITER"))
        self.assertEqual(waiter.get(f"/billing/create/{self.order.pk}/").status_code, 403)
