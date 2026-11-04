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
