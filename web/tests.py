from datetime import date

from django.contrib.auth.models import User
from django.test import Client, TestCase

from core.testing import client_for, make_menu, make_restaurant, make_staff, make_table


class LandingPageTests(TestCase):
    """/ is always the website; nothing in the app sends anyone to /admin/."""

    def test_visitors_see_the_website(self):
        self.assertContains(Client().get("/"), "Book a free demo")

    def test_logged_in_staff_still_see_the_website(self):
        restaurant = make_restaurant()
        response = client_for(make_staff(restaurant, "ADMIN")).get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Open Spice Garden")

    def test_developer_superuser_is_not_sent_to_django_admin(self):
        client = Client()
        client.force_login(User.objects.create_superuser("dev", email="dev@x.test", password="Dev@12345"))
        self.assertEqual(client.get("/").status_code, 200)
        response = client.get("/home/")
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "developer login", status_code=403)


class PublicMenuTests(TestCase):
    """/r/<slug>/: the restaurant's menu for anyone; orders from it are take-away only."""

    def setUp(self):
        self.restaurant = make_restaurant()
        _, self.paneer, self.naan = make_menu(self.restaurant)
        other = make_restaurant("Blue Bay")
        category, dish, _ = make_menu(other)
        dish.name = "Blue Bay Soup"
        dish.save()

    def test_shows_this_restaurants_dishes_only(self):
        response = Client().get("/r/spice-garden/")
        self.assertContains(response, "Paneer Tikka")
        self.assertNotContains(response, "Blue Bay Soup")

    def test_hidden_dishes_are_left_out_and_orders_go_to_the_takeaway_table_only(self):
        from tables.models import takeaway_table
        table = make_table(self.restaurant)
        self.naan.is_active = False
        self.naan.save()
        response = Client().get("/r/spice-garden/")
        self.assertNotContains(response, "Butter Naan")
        self.assertContains(response, f"/m/{takeaway_table(self.restaurant).qr_token}/cart/add/")
        self.assertNotContains(response, str(table.qr_token))  # never a dining table

    def test_unknown_or_ended_restaurant_is_not_found(self):
        self.assertEqual(Client().get("/r/no-such-place/").status_code, 404)
        self.restaurant.membership_start, self.restaurant.membership_end = date(2020, 1, 1), date(2020, 1, 31)
        self.restaurant.save()
        self.assertEqual(Client().get("/r/spice-garden/").status_code, 404)

    def test_ordering_still_needs_the_table_qr(self):
        table = make_table(self.restaurant)
        self.assertEqual(Client().get(f"/m/{table.qr_token}/").status_code, 200)
        self.assertEqual(Client().get(f"/m/spice-garden/{table.pk}/").status_code, 404)


class CafeWebsiteTests(TestCase):
    """/cafe/<slug>/: a cafe's own one-page website, the same look as ours, with its own
    name, story, menu (with sizes), locations, contacts and a feedback form."""

    def setUp(self):
        from decimal import Decimal
        from menu.models import MenuItemPortion
        self.restaurant = make_restaurant(phone="98765 43210", email="hello@sg.in")
        _, self.paneer, self.naan = make_menu(self.restaurant)
        MenuItemPortion.objects.create(item=self.paneer, name="Half", price=Decimal("179"), sort_order=1)
        MenuItemPortion.objects.create(item=self.paneer, name="Full", price=Decimal("329"), sort_order=2)
        other = make_restaurant("Blue Bay")
        _, soup, _ = make_menu(other)
        soup.name = "Blue Bay Soup"
        soup.save()
        self.admin = client_for(make_staff(self.restaurant, "ADMIN"))

    def test_every_cafe_has_its_own_page_with_its_own_things(self):
        page = Client().get("/cafe/spice-garden/")
        self.assertContains(page, "<title>Spice Garden</title>", html=True)
        self.assertContains(page, "Butter Naan")
        self.assertContains(page, "Half <b>₹179</b>", html=True)  # the sizes with their prices
        self.assertNotContains(page, "Blue Bay Soup")
        self.assertContains(page, "12 Test Road")  # where to find us, with directions
        self.assertContains(page, "google.com/maps/search")
        self.assertContains(page, 'href="/r/spice-garden/"')  # Order online: the public menu
        self.assertContains(page, 'href="tel:9876543210"')
        self.assertContains(page, 'hx-post="/cafe/spice-garden/feedback/"')
        self.assertContains(page, "Website by")
        self.assertContains(Client().get("/"), "Book a free demo")  # our own website stays as it is

    def test_the_cafe_writes_what_it_says(self):
        response = self.admin.post("/restaurant/website/", {
            "is_on": "on", "tagline": "Wood-fired pizzas since 2015", "about": "Run by two brothers.",
            "opening_hours": "Mon – Fri: 11 am – 11 pm\nSat – Sun: 9 am – midnight",
            "highlight_choices": ["wifi", "parking"], "whatsapp": "+91 98765 43210",
            "instagram": "https://instagram.com/spicegarden", "facebook": ""})
        self.assertRedirects(response, "/restaurant/website/", fetch_redirect_response=False)
        page = Client().get("/cafe/spice-garden/")
        for text in ("Wood-fired pizzas since 2015", "Run by two brothers.", "Sat – Sun: 9 am – midnight",
                     "Free Wi-Fi", "Parking", "https://wa.me/919876543210", "https://instagram.com/spicegarden"):
            self.assertContains(page, text)
        self.assertNotContains(page, "Live music")  # not ticked

    def test_switched_off_unknown_or_ended_is_not_found(self):
        self.admin.post("/restaurant/website/", {"tagline": "x"})  # "Show my cafe website" left unticked
        self.assertEqual(Client().get("/cafe/spice-garden/").status_code, 404)
        self.assertEqual(Client().get("/cafe/no-such-cafe/").status_code, 404)
        self.assertEqual(Client().get("/cafe/blue-bay/").status_code, 200)
        self.restaurant.membership_start, self.restaurant.membership_end = date(2020, 1, 1), date(2020, 1, 31)
        self.restaurant.save()
        self.assertEqual(Client().get("/cafe/spice-garden/").status_code, 404)

    def test_only_menu_cafe_shows_the_menu_without_ordering(self):
        self.restaurant.tier = "MENU"
        self.restaurant.save()
        page = Client().get("/cafe/spice-garden/")
        self.assertNotContains(page, "Order online")
        self.assertContains(page, 'href="/r/spice-garden/view/"')
        self.assertEqual(self.admin.get("/restaurant/website/").status_code, 200)  # its Website tab works too

    def test_guests_send_feedback_and_the_cafe_reads_it(self):
        from web.models import Feedback
        guest = Client()
        stars = {"food_rating": "5", "staff_rating": "4", "cafe_rating": "5"}
        missing = guest.post("/cafe/spice-garden/feedback/", {"food_rating": "5", "message": "Great", "name": "Meera"})
        self.assertContains(missing, "Please pick the stars for staff.")
        self.assertContains(missing, "Please pick the stars for cafe.")
        sent = guest.post("/cafe/spice-garden/feedback/", {**stars, "message": "Loved the paneer!",
                                                           "name": "Meera", "phone": "98765 00011"})
        self.assertContains(sent, "Thank you, Meera!")
        feedback = Feedback.objects.get()
        self.assertEqual((feedback.restaurant, feedback.phone), (self.restaurant, "9876500011"))
        self.assertEqual((feedback.food_rating, feedback.staff_rating, feedback.cafe_rating, feedback.rating),
                         (5, 4, 5, 5))  # overall: 4.67 rounds to 5
        self.assertIsNone(feedback.order)
        # the message is optional
        self.assertContains(guest.post("/cafe/spice-garden/feedback/", {**stars, "name": "Meera"}), "Thank you, Meera!")
        # the robot trap, and one visitor sending again and again: thanked, not kept
        guest.post("/cafe/spice-garden/feedback/", {**stars, "message": "spam", "name": "x", "website": "spam.example"})
        for n in range(4):
            guest.post("/cafe/spice-garden/feedback/", {**stars, "message": f"again {n}", "name": "Meera"})
        self.assertEqual(Feedback.objects.count(), 3)  # 3 an hour from one visitor

        self.assertContains(self.admin.get("/restaurant/website/"), 'class="tab-count"')  # new ones on the tab
        page = self.admin.get("/restaurant/feedback/")
        self.assertContains(page, "Loved the paneer!")
        self.assertContains(page, 'tel:9876500011')
        self.assertFalse(Feedback.objects.filter(is_read=False).exists())  # opened: read

    def test_the_cafe_picks_which_feedback_to_show(self):
        from web.models import Feedback
        good = Feedback.objects.create(restaurant=self.restaurant, name="Ravi", phone="9123456789", rating=5,
                                       message="Best biryani in town")
        Feedback.objects.create(restaurant=self.restaurant, name="Anon", rating=1, message="Too slow")
        self.assertNotContains(Client().get("/cafe/spice-garden/"), "Best biryani in town")
        response = self.admin.post(f"/restaurant/feedback/{good.pk}/show/", HTTP_HX_REQUEST="true")
        self.assertContains(response, "Shown on website")
        page = Client().get("/cafe/spice-garden/")
        self.assertContains(page, "What our guests say")
        self.assertContains(page, "Best biryani in town")
        self.assertNotContains(page, "Too slow")
        self.assertNotContains(page, "9123456789")  # a guest's number is never shown

    def test_only_the_cafes_admin_and_manager(self):
        from web.models import Feedback
        other = Feedback.objects.create(restaurant=make_restaurant("Green Leaf"), name="X", rating=3, message="ok")
        self.assertEqual(self.admin.post(f"/restaurant/feedback/{other.pk}/show/").status_code, 404)
        self.assertEqual(client_for(make_staff(self.restaurant, "MANAGER")).get("/restaurant/website/").status_code, 200)
        for role in ("CASHIER", "WAITER"):
            self.assertEqual(client_for(make_staff(self.restaurant, role)).get("/restaurant/feedback/").status_code, 403)


class RestaurantSettingsTests(TestCase):
    def setUp(self):
        self.restaurant = make_restaurant()
        self.client = client_for(make_staff(self.restaurant, "ADMIN"))
        self.data = {"name": "Spice Garden Camp", "address": "MG Road", "phone": "020 1234", "email": "hi@sg.in",
                     "gstin": "27abcde1234f1z5", "gst_percent": "5", "fssai_no": "11520034000123"}

    def test_admin_saves_details_and_gstin_is_upper_cased(self):
        response = self.client.post("/restaurant/", {**self.data, "plan": "YEARLY", "max_users": "99"})
        self.assertRedirects(response, "/restaurant/", fetch_redirect_response=False)
        self.restaurant.refresh_from_db()
        self.assertEqual((self.restaurant.name, self.restaurant.gstin), ("Spice Garden Camp", "27ABCDE1234F1Z5"))
        # membership is not the restaurant's to change
        self.assertEqual((self.restaurant.plan, self.restaurant.max_users), ("MONTHLY", 5))

    def test_bad_gstin_and_gst_are_refused(self):
        response = self.client.post("/restaurant/", {**self.data, "gstin": "12345", "gst_percent": "40"})
        self.assertContains(response, "valid 15-character GSTIN")
        self.assertContains(response, "between 0% and 28%")

    def test_only_admin_and_manager(self):
        """core/roles.py: the company's profile is the admin's and the manager's (they see everything)."""
        self.assertEqual(client_for(make_staff(self.restaurant, "MANAGER")).get("/restaurant/").status_code, 200)
        for role in ("RM", "ALL", "CASHIER"):
            self.assertEqual(client_for(make_staff(self.restaurant, role)).get("/restaurant/").status_code, 403)


class RateYourVisitTests(TestCase):
    """After the bill: "Rate your visit" with the guest's bill and Food, Staff, Cafe stars,
    once per order; the cafe's website shows the average stars."""

    def setUp(self):
        from core.testing import guest_orders
        from orders.models import Order
        self.restaurant = make_restaurant(upi_id="spicegarden@okicici")
        _, self.paneer, _ = make_menu(self.restaurant)
        self.guest = Client()
        guest_orders(self.guest, make_table(self.restaurant), [self.paneer, self.paneer], name="Meera")
        self.order = Order.objects.get()
        self.order.customer_phone = "9876500011"
        self.order.save()
        self.url = f"/feedback/{self.order.public_token}/"
        self.cashier = client_for(make_staff(self.restaurant, "CASHIER"))
        self.stars = {"food_rating": "5", "staff_rating": "4", "cafe_rating": "3"}

    def make_bill(self):
        from billing.models import Bill
        self.cashier.post(f"/billing/create/{self.order.pk}/", {"discount_type": "AMOUNT"})
        return Bill.objects.get()

    def test_only_once_the_bill_is_made(self):
        from web.models import Feedback
        self.assertContains(self.guest.get(self.url), "once your bill is ready")
        self.guest.post(self.url, self.stars)
        self.assertFalse(Feedback.objects.exists())
        self.assertNotContains(self.guest.get(f"/track/{self.order.public_token}/"), "Rate your visit")

    def test_the_guest_rates_with_their_bill_in_view_once(self):
        from core.templatetags.money import inr
        from web.models import Feedback
        bill = self.make_bill()
        track = self.guest.get(f"/track/{self.order.public_token}/")
        self.assertContains(track, "How was everything? Rate your visit")
        self.assertContains(track, f'href="{self.url}"')

        page = self.guest.get(self.url)
        self.assertContains(page, "How was everything?")
        for label in ("Food", "Staff", "Cafe"):
            self.assertContains(page, label)
        self.assertContains(page, f"Bill #{bill.bill_no}")
        self.assertContains(page, "2 × Paneer Tikka")
        self.assertContains(page, inr(bill.grand_total))

        missing = self.guest.post(self.url, {"food_rating": "5"})
        self.assertContains(missing, "Please pick the stars for staff.")
        sent = self.guest.post(self.url, self.stars)
        self.assertRedirects(sent, self.url, fetch_redirect_response=False)
        feedback = Feedback.objects.get()
        self.assertEqual((feedback.order, feedback.restaurant, feedback.name, feedback.phone),
                         (self.order, self.restaurant, "Meera", "9876500011"))
        self.assertEqual((feedback.food_rating, feedback.staff_rating, feedback.cafe_rating, feedback.rating), (5, 4, 3, 4))
        thanks = self.guest.get(self.url)
        self.assertContains(thanks, "Thank you!")
        self.assertContains(thanks, f"Bill #{bill.bill_no}")  # the bill stays there to look back at

        self.guest.post(self.url, {"food_rating": "1", "staff_rating": "1", "cafe_rating": "1"})  # once per order
        self.assertEqual(Feedback.objects.get().rating, 4)
        self.assertContains(self.guest.get(f"/track/{self.order.public_token}/"), "Thank you for rating us")

    def test_staff_send_the_link_and_see_the_stars(self):
        from web.models import Feedback
        bill = self.make_bill()
        page = self.cashier.get(f"/billing/{bill.pk}/")
        self.assertContains(page, "Guest feedback")
        self.assertContains(page, f'data-copy="http://testserver{self.url}"')
        self.assertContains(page, "https://wa.me/919876500011?text=")
        self.guest.post(self.url, self.stars)
        page = self.cashier.get(f"/billing/{bill.pk}/")
        self.assertNotContains(page, "Copy link")
        self.assertContains(page, "Staff")
        admin = client_for(make_staff(self.restaurant, "ADMIN"))
        listing = admin.get("/restaurant/feedback/")
        self.assertContains(listing, "After the bill")
        self.assertContains(listing, f"Bill #{bill.bill_no}")
        self.assertTrue(Feedback.objects.get().is_read)

    def test_the_customer_screen_shows_a_rating_qr_after_paying(self):
        bill = self.make_bill()
        self.assertNotContains(self.cashier.get(f"/billing/{bill.pk}/upi/screen/"), "Rate your visit")
        self.cashier.post(f"/billing/{bill.pk}/upi/paid/", {"reference_no": ""}, HTTP_HX_REQUEST="true")
        screen = self.cashier.get(f"/billing/{bill.pk}/upi/screen/")
        self.assertContains(screen, "Payment received")
        self.assertContains(screen, "Rate your visit")
        self.assertContains(screen, 'src="data:image/png;base64,')

    def test_the_website_shows_the_average_stars(self):
        from web.models import CafeWebsite, Feedback
        Feedback.objects.create(restaurant=self.restaurant, name="A", rating=4, food_rating=5, staff_rating=4, cafe_rating=4)
        Feedback.objects.create(restaurant=self.restaurant, name="B", rating=3, food_rating=4, staff_rating=2, cafe_rating=3)
        Feedback.objects.create(restaurant=self.restaurant, name="Old", rating=5, message="Lovely")  # before the 3 questions
        site = Client().get(f"/cafe/{self.restaurant.slug}/")
        self.assertContains(site, 'class="cafe-ratings"')
        self.assertContains(site, "<strong>4.0</strong>")  # (4 + 3 + 5) / 3
        self.assertContains(site, "from 3 guests")
        self.assertContains(site, '<strong class="tnum">4.5</strong>')  # food (5 + 4) / 2
        self.assertContains(site, '<strong class="tnum">3.0</strong>')  # staff
        self.assertContains(site, 'href="#reviews"')
        website = CafeWebsite.of(self.restaurant)
        website.show_ratings = False
        website.save()
        self.assertNotContains(Client().get(f"/cafe/{self.restaurant.slug}/"), 'class="cafe-ratings"')
