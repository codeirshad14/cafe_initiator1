from datetime import timedelta
from decimal import Decimal as D

from django.test import Client, TestCase
from django.utils import timezone

from billing.models import Bill
from core.testing import HTMX, client_for, guest_orders, make_menu, make_restaurant, make_staff, make_table
from orders.models import Order
from reports.catalog import GROUPS, REPORTS


class ReportTests(TestCase):
    """The reports (reports/catalog/): every one opens for every period, searches, and exports
    to CSV and PDF with the company's letterhead on top."""

    def setUp(self):
        self.restaurant = make_restaurant(address="12 MG Road, Pune", phone="020 1234 5678", gstin="27ABCDE1234F1Z5")
        _, paneer, naan = make_menu(self.restaurant)
        guest_orders(Client(), make_table(self.restaurant), [paneer, paneer, naan])  # 558 -> bill 586
        cashier = client_for(make_staff(self.restaurant, "CASHIER"))
        order = Order.objects.get()
        cashier.post(f"/billing/create/{order.pk}/", {"discount_type": "AMOUNT"})
        bill = Bill.objects.get()
        cashier.post(f"/billing/{bill.pk}/pay/", {"mode": "CASH", "amount": "86"}, **HTMX)
        cashier.post(f"/billing/{bill.pk}/pay/", {"mode": "UPI", "amount": "500"}, **HTMX)
        self.place = self.restaurant.main_location()
        self.manager = client_for(make_staff(self.restaurant, "MANAGER"))
        self.today = timezone.localdate()

    def run_report(self, slug):
        return REPORTS[slug]["function"](self.place, self.today, self.today)

    def test_every_report_opens_for_every_period(self):
        self.assertEqual(sum(len(slugs) for _, slugs in GROUPS), len(REPORTS))
        for slug in REPORTS:
            for when in ("today", "week", "month"):
                with self.subTest(slug=slug, when=when):
                    self.assertEqual(self.manager.get(f"/reports/{slug}/?when={when}").status_code, 200)
            self.assertEqual(self.manager.get(f"/reports/{slug}/?when=week", **HTMX).status_code, 200)

    def test_index_is_grouped_without_hints(self):
        page = self.manager.get("/reports/")
        for group, _ in GROUPS:
            self.assertContains(page, f">{group}</h2>")
        self.assertNotContains(page, "Bills, gross, discount, tax and net for each day.")

    def test_report_page_has_the_bookings_filter_and_stripes(self):
        page = self.manager.get("/reports/item-sales/")
        self.assertContains(page, 'id="periodFilter"')
        self.assertContains(page, 'data-search-in="#reportBody"')
        self.assertContains(page, 'class="data-table table-stack report-table"')
        self.assertContains(page, 'data-search="paneer tikka starters')
        self.assertContains(page, "export=csv")
        self.assertContains(page, "export=pdf")

    def test_daily_sales_numbers(self):
        totals = self.run_report("daily-sales")[0]["totals"]
        # bills, gross, discount, delivery, tax, round off, net, average bill
        self.assertEqual(totals[1:], [1, D("558"), D("0"), D("0"), D("27.90"), D("0.10"), D("586"), D("586.00")])

    def test_payment_modes(self):
        collected = {row[0]: row[2] for row in self.run_report("payment-modes")[0]["rows"]}
        self.assertEqual((collected["Cash"], collected["UPI"], collected["Debit card"]), (D("86"), D("500"), 0))

    def test_gst_and_staff_collections(self):
        gst = self.run_report("gst-summary")[0]["totals"]
        self.assertEqual((gst[3], gst[4], gst[5], gst[6]), (D("558"), D("13.95"), D("13.95"), D("27.90")))
        staff = self.run_report("staff-collections")[0]["rows"][0]
        self.assertEqual((staff[1], staff[-1]), (2, D("586")))

    def test_csv_export_has_the_letterhead(self):
        response = self.manager.get("/reports/item-sales/?export=csv")
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        text = response.content.decode("utf-8-sig")
        lines = text.splitlines()
        self.assertEqual(lines[0], "Spice Garden")
        self.assertIn("GSTIN: 27ABCDE1234F1Z5", text)
        self.assertIn("Item-wise sales", text)
        self.assertIn("Paneer Tikka,Starters,1,2,498", text)

    def test_pdf_export(self):
        response = self.manager.get("/reports/bill-register/?when=month&export=pdf")
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertIn('filename="bill-register_', response["Content-Disposition"])

    def test_search_narrows_the_export(self):
        everything = self.manager.get("/reports/item-sales/?export=csv").content.decode("utf-8-sig")
        searched = self.manager.get("/reports/item-sales/?export=csv&q=naan").content.decode("utf-8-sig")
        self.assertIn("Paneer Tikka", everything)
        self.assertIn("Butter Naan", searched)
        self.assertNotIn("Paneer Tikka", searched)
        self.assertIn("Search,naan", searched)

    def test_search_on_screen_runs_over_every_row(self):
        page = self.manager.get("/reports/item-sales/?q=naan", **HTMX)
        self.assertContains(page, "Butter Naan")
        self.assertNotContains(page, "Paneer Tikka")
        self.assertNotContains(page, "<tfoot>")  # the totals are of every row: not with a search
        nothing = self.manager.get("/reports/item-sales/?q=pizza", **HTMX)
        self.assertContains(nothing, "Nothing matches “pizza”")

    def test_report_tables_scroll_page_and_show_loading_dots(self):
        page = self.manager.get("/reports/item-sales/?when=month")
        self.assertContains(page, 'class="table-wrap table-scroll"')
        self.assertContains(page, "<strong>2</strong>", html=False)  # 2 rows: one page, no page buttons
        self.assertNotContains(page, "pager-pages")
        self.assertContains(page, 'class="report-loading"')
        self.assertEqual(self.manager.get("/reports/bill-register/?page=all", **HTMX).status_code, 200)

    def test_operations_and_guest_reports_have_rows(self):
        order = Order.objects.get()
        kot = order.kots.get()
        type(kot).objects.filter(pk=kot.pk).update(status="READY", ready_at=kot.created_at + timedelta(minutes=9))
        self.assertEqual(self.run_report("kot-register")[0]["rows"][0][7], 9)  # minutes to ready
        self.assertEqual(self.run_report("kitchen-performance")[0]["totals"][2], 9)
        self.assertEqual(self.run_report("table-sales")[0]["rows"][0][0], "T1")
        self.assertEqual(self.run_report("waiter-sales")[0]["rows"][0][0], "Guests (QR / public menu)")
        slow = self.run_report("slow-items")[0]
        self.assertEqual([(row[0], row[4]) for row in slow["rows"]], [("Butter Naan", 1), ("Paneer Tikka", 2)])  # least first
        self.assertEqual(slow["totals"][0], "0 not sold")  # the menu has two dishes: both sold

    def test_other_restaurant_sees_none_of_it(self):
        other = make_restaurant("Blue Bay")
        sections = REPORTS["bill-register"]["function"](other.main_location(), self.today, self.today)
        self.assertEqual(sections[0]["rows"], [])

    def test_drill_down_from_a_summary_to_its_bills_to_the_bill(self):
        """Like Tally: Dine in -> the dine-in bills -> the bill, each with the way back."""
        bill = Bill.objects.get()
        page = self.manager.get("/reports/order-types/?when=month")
        self.assertContains(page, "Click a row to see its details")
        dine_in = REPORTS["order-types"]["function"](self.place, self.today, self.today)[0]["links"][0]
        self.assertEqual(dine_in["filters"], {"live": "1", "type": "DINE_IN"})
        self.assertContains(page, 'data-drill="/reports/bill-register/?when=month&amp;live=1&amp;type=DINE_IN&amp;back=')
        self.assertIsNone(REPORTS["order-types"]["function"](self.place, self.today, self.today)[0]["links"][1])  # no takeaway

        bills = self.manager.get("/reports/bill-register/?when=month&type=DINE_IN&live=1&back=/reports/order-types/?when=month")
        self.assertContains(bills, "Back to Dine in, takeaway &amp; delivery")
        self.assertContains(bills, '<span class="report-drill-chip"><span>Order type</span> Dine in</span>', html=True)
        self.assertContains(bills, f'href="/billing/{bill.pk}/?back=')
        self.assertContains(bills, 'name="type" value="DINE_IN"')  # a new period keeps the narrowing
        self.assertEqual(len(self.manager.get("/reports/bill-register/?type=TAKEAWAY&live=1", **HTMX).context["sections"][0]["rows"]), 0)

        detail = self.manager.get(f"/billing/{bill.pk}/?back=/reports/bill-register/?type=DINE_IN")
        self.assertContains(detail, 'href="/reports/bill-register/?type=DINE_IN"')
        self.assertContains(detail, "Back to report")
        self.assertNotContains(self.manager.get(f"/billing/{bill.pk}/?back=https://evil.test/"), "evil.test")

    def test_every_summary_drills_into_rows_that_add_up(self):
        bill = Bill.objects.get()
        run = REPORTS["bill-register"]["function"]
        for filters in ({"live": "1", "hour": str(timezone.localtime(bill.created_at).hour)}, {"live": "1", "table": "T1"},
                        {"live": "1", "waiter": "none"}, {"live": "1", "item": "Paneer Tikka"},
                        {"live": "1", "gst": "5.00"}, {"live": "1", "dish": str(bill.items.first().menu_item_id)}):
            with self.subTest(filters=filters):
                self.assertEqual([row[0] for row in run(self.place, self.today, self.today, **filters)[0]["rows"]],
                                 [bill.bill_no])
        self.assertEqual(run(self.place, self.today, self.today, live="1", hour="abc")[0]["rows"], [])
        self.assertEqual(run(self.place, self.today, self.today, live="1", gst="x")[0]["rows"], [])
        upi = REPORTS["payment-register"]["function"](self.place, self.today, self.today, mode="UPI")[0]
        self.assertEqual(upi["totals"][6], D("500"))  # = Payment modes' UPI
        self.assertEqual(REPORTS["item-sales"]["function"](self.place, self.today, self.today, category="Starters")[0]["rows"][0][0],
                         "Paneer Tikka")
        # every report's links open (summary -> list -> bill)
        for slug in REPORTS:
            page = self.manager.get(f"/reports/{slug}/?when=month", **HTMX)
            for section in page.context["sections"]:
                for href in filter(None, section["hrefs"]):
                    with self.subTest(slug=slug, href=href):
                        self.assertEqual(self.manager.get(href).status_code, 200)

    def test_reports_are_for_the_outlet_heads(self):
        cashier = client_for(make_staff(self.restaurant, "CASHIER", email="c2@x.test"))
        self.assertEqual(cashier.get("/reports/").status_code, 403)
        self.assertEqual(cashier.get("/reports/daily-sales/?export=pdf").status_code, 403)
