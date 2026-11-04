import io
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from core.testing import HTMX, client_for, make_menu, make_restaurant, make_staff, make_table

PHOTOS = tempfile.mkdtemp(prefix="menu-photos-")


def photo_of(megabytes):
    """A real (tiny) PNG made this big by padding after its end: the size is what counts."""
    data = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(data, "PNG")
    padded = data.getvalue() + b"\0" * int(megabytes * 1024 * 1024)
    return SimpleUploadedFile("dish.png", padded, content_type="image/png")


@override_settings(MEDIA_ROOT=PHOTOS)
class DishPhotoTests(TestCase):
    """A dish photo may be up to 5 MB, on Menu items and in the Django admin alike."""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(PHOTOS, ignore_errors=True)

    def setUp(self):
        from menu.models import Category
        self.category = Category.objects.create(restaurant=make_restaurant(), name="Mains")
        self.client = client_for(make_staff(self.category.restaurant, "ADMIN"))

    def add(self, upload):
        return self.client.post("/menu/items/add/", {
            "category": self.category.pk, "name": "Paneer Tikka", "food_type": "VEG", "price": "249",
            "sort_order": 0, "is_available": "on", "is_active": "on", "image": upload,
            "portions-TOTAL_FORMS": "0", "portions-INITIAL_FORMS": "0", "portions-MIN_NUM_FORMS": "0",
            "portions-MAX_NUM_FORMS": "6"}, **HTMX)

    def test_up_to_5_mb_is_taken(self):
        self.assertEqual(self.add(photo_of(4.9)).status_code, 204)
        from menu.models import MenuItem
        self.assertTrue(MenuItem.objects.get().image)

    def test_over_5_mb_is_refused(self):
        self.assertContains(self.add(photo_of(5.2)), "Please use one under 5 MB.")
        self.assertContains(self.client.get("/menu/items/add/", **HTMX), "up to 5 MB")

    def test_the_admin_checks_it_too(self):
        from menu.models import MenuItem, validate_photo_size
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            validate_photo_size(MenuItem(image=photo_of(5.2)).image)


class PortionTests(TestCase):
    """Qtr / Half / Full: a dish with sizes, each with its own price."""

    def setUp(self):
        from menu.models import Category
        self.restaurant = make_restaurant()
        self.category = Category.objects.create(restaurant=self.restaurant, name="Mains")
        self.client = client_for(make_staff(self.restaurant, "ADMIN"))

    def dish(self, rows, **extra):
        data = {"category": self.category.pk, "name": "Butter Chicken", "food_type": "NON_VEG", "sort_order": 0,
                "is_available": "on", "is_active": "on", "portions-TOTAL_FORMS": str(len(rows)),
                "portions-INITIAL_FORMS": "0", "portions-MIN_NUM_FORMS": "0", "portions-MAX_NUM_FORMS": "6", **extra}
        for index, (name, price) in enumerate(rows):
            data[f"portions-{index}-name"] = name
            data[f"portions-{index}-price"] = price
        return self.client.post("/menu/items/add/", data, **HTMX)

    def test_dish_with_qtr_half_full(self):
        response = self.dish([("Qtr", "149"), ("Half", "249"), ("Full", "449")])
        self.assertEqual(response.status_code, 204)
        from menu.models import MenuItem
        item = MenuItem.objects.get()
        self.assertEqual([(p.name, str(p.price)) for p in item.portions.all()],
                         [("Qtr", "149.00"), ("Half", "249.00"), ("Full", "449.00")])
        self.assertEqual(str(item.price), "149.00")  # "from" the smallest portion
        self.assertContains(self.client.get("/menu/items/"), "Half")

    def test_needs_a_price_or_portions(self):
        self.assertContains(self.dish([("", ""), ("", "")]), "add portions")

    def test_portion_names_must_differ(self):
        self.assertContains(self.dish([("Half", "249"), ("half", "299")]), "its own name")

    def test_single_price_dish_still_works(self):
        self.assertEqual(self.dish([("", "")], price="199").status_code, 204)


class IsolationTests(TestCase):
    """Staff of restaurant A must never open restaurant B's menu or tables (404, not 403)."""

    def setUp(self):
        self.a = make_restaurant("Spice Garden")
        self.b = make_restaurant("Blue Bay")
        self.client = client_for(make_staff(self.a, "ADMIN"))
        self.b_category, self.b_dish, _ = make_menu(self.b)
        self.b_table = make_table(self.b, "B1")

    def test_other_restaurants_menu_items_are_not_found(self):
        self.assertEqual(self.client.get(f"/menu/items/{self.b_dish.pk}/edit/", **HTMX).status_code, 404)
        self.assertEqual(self.client.post(f"/menu/items/{self.b_dish.pk}/delete/", **HTMX).status_code, 404)
        self.assertEqual(self.client.post(f"/menu/items/{self.b_dish.pk}/toggle/", **HTMX).status_code, 404)
        self.assertEqual(self.client.get(f"/menu/categories/{self.b_category.pk}/edit/", **HTMX).status_code, 404)

    def test_other_restaurants_items_are_not_listed(self):
        self.assertNotContains(self.client.get("/menu/items/"), "Paneer Tikka")

    def test_other_restaurants_tables_and_qr_are_not_found(self):
        self.assertEqual(self.client.get(f"/tables/{self.b_table.pk}/edit/", **HTMX).status_code, 404)
        self.assertEqual(self.client.get(f"/tables/{self.b_table.pk}/qr.png").status_code, 404)

    def test_a_category_with_items_cannot_be_deleted(self):
        category, _, _ = make_menu(self.a)
        response = self.client.post(f"/menu/categories/{category.pk}/delete/", **HTMX)
        self.assertContains(response, "cannot be deleted")
