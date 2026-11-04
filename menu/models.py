from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from core.models import Restaurant

MAX_IMAGE_MB = 5


def validate_photo_size(photo):
    """A dish photo may be up to 5 MB (checked on Menu items and in the Django admin alike).
    Only a newly chosen photo is measured: a saved one passed when it came in."""
    if getattr(photo, "_committed", False):
        return
    if photo.size > MAX_IMAGE_MB * 1024 * 1024:
        raise ValidationError(f"The photo is too big. Please use one under {MAX_IMAGE_MB} MB.")


class Category(models.Model):
    """A menu section, e.g. Starters, Main Course, Desserts."""

    restaurant = models.ForeignKey(Restaurant, on_delete=models.PROTECT, related_name="categories")
    name = models.CharField(max_length=100)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name_plural = "categories"
        constraints = [
            models.UniqueConstraint(fields=["restaurant", "name"], name="unique_category_per_restaurant"),
        ]

    def __str__(self):
        return self.name


class MenuItem(models.Model):
    """One dish or drink the restaurant sells."""

    class FoodType(models.TextChoices):
        VEG = "VEG", "Veg"
        NON_VEG = "NON_VEG", "Non-veg"  # egg dishes count as non-veg

    restaurant = models.ForeignKey(Restaurant, on_delete=models.PROTECT, related_name="menu_items")
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="items")
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    # shown on the guest's dish details and cart; both optional
    ingredients = models.TextField(blank=True)
    prep_time = models.CharField("preparation time", max_length=30, blank=True)  # "15-20 min"
    price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))])
    image = models.ImageField(upload_to="menu/", blank=True, validators=[validate_photo_size])
    food_type = models.CharField(max_length=10, choices=FoodType.choices, default=FoodType.VEG)
    is_available = models.BooleanField(default=True)  # kitchen: "out of stock" today
    is_active = models.BooleanField(default=True)     # admin: shown on the menu at all
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["category__sort_order", "sort_order", "name"]

    def __str__(self):
        return self.name


class MenuItemPortion(models.Model):
    """A size of a dish with its own price: Qtr / Half / Full, or 250 ml / 500 ml.

    A dish with portions is ordered by portion; its own `price` is then kept as
    the smallest portion's price (for "from ₹99" and sorting). KOT and bill lines
    copy "Dish (Half)" and the portion's price, so a portion can change or go
    later without touching old orders.
    """

    item = models.ForeignKey(MenuItem, on_delete=models.CASCADE, related_name="portions")
    name = models.CharField(max_length=30)  # "Half"
    price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))])
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "price"]
        constraints = [
            models.UniqueConstraint(fields=["item", "name"], name="unique_portion_name_per_item"),
        ]

    def __str__(self):
        return f"{self.item.name} ({self.name})"
