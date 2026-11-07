from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from core.models import Restaurant
from menu.models import validate_photo_size


class DemoRequest(models.Model):
    """A restaurant owner asking for a demo from the public website.

    Not restaurant data: these are leads for the platform owner, read in the
    Django admin.
    """

    name = models.CharField("your name", max_length=100)
    restaurant_name = models.CharField("restaurant name", max_length=150)
    phone = models.CharField("mobile number", max_length=15)
    city = models.CharField(max_length=80, blank=True)
    tables = models.PositiveSmallIntegerField("number of tables", null=True, blank=True)
    message = models.TextField(blank=True)
    is_contacted = models.BooleanField("contacted", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.restaurant_name} ({self.name})"


# what a cafe can say about itself on its website: (key, label, Bootstrap icon)
HIGHLIGHTS = [
    ("pure_veg", "Pure veg", "flower1"),
    ("family", "Family friendly", "people"),
    ("ac", "Air-conditioned", "snow"),
    ("wifi", "Free Wi-Fi", "wifi"),
    ("parking", "Parking", "p-square"),
    ("outdoor", "Outdoor seating", "tree"),
    ("music", "Live music", "music-note-beamed"),
    ("parties", "Parties & events", "balloon"),
    ("delivery", "Home delivery", "bicycle"),
    ("takeaway", "Takeaway", "bag-check"),
    ("upi", "UPI & cards", "credit-card"),
    ("late", "Open late", "moon-stars"),
]


class CafeWebsite(models.Model):
    """A cafe's own one-page website, /cafe/<slug>/: the same look as our website,
    with the cafe's name, story, menu, locations and contacts. Filled in by the
    cafe's admin (Cafe profile > Website); the rest comes from the cafe's profile,
    menu and locations. Made the first time the cafe opens that tab or its page."""

    restaurant = models.OneToOneField(Restaurant, on_delete=models.CASCADE, related_name="website")
    is_on = models.BooleanField("show my cafe website", default=True)
    tagline = models.CharField(max_length=120, blank=True,
                               help_text="One line under your name, e.g. Wood-fired pizzas and the best cold coffee in town.")
    about = models.TextField("our story", blank=True,
                             help_text="A few lines about your cafe: since when, what you are known for, who cooks.")
    cover = models.ImageField("cover photo", upload_to="covers/", blank=True, validators=[validate_photo_size],
                              help_text="The big photo at the top: your place or your best dish. Wide, JPG or PNG, up to 5 MB.")
    opening_hours = models.TextField(blank=True, help_text="One line each, e.g. Mon – Fri: 11 am – 11 pm")
    highlights = models.CharField(max_length=300, blank=True)  # keys of HIGHLIGHTS, comma separated
    whatsapp = models.CharField("WhatsApp number", max_length=15, blank=True,
                                help_text="10-digit mobile. Empty = no WhatsApp button.")
    instagram = models.URLField(blank=True, help_text="e.g. https://instagram.com/yourcafe")
    facebook = models.URLField(blank=True, help_text="e.g. https://facebook.com/yourcafe")
    show_ratings = models.BooleanField("show my guests' star ratings", default=True,
                                       help_text="The average stars for Food, Staff and Cafe, from guests' feedback.")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.restaurant.name} website"

    @classmethod
    def of(cls, restaurant):
        """The cafe's website settings, made with the defaults the first time."""
        return cls.objects.get_or_create(restaurant=restaurant)[0]

    def highlight_keys(self):
        return [key for key in self.highlights.split(",") if key]

    def chosen_highlights(self):
        """[(label, icon)] of the ticked highlights, in the list's order."""
        keys = set(self.highlight_keys())
        return [(label, icon) for key, label, icon in HIGHLIGHTS if key in keys]

    def hours_lines(self):
        return [line.strip() for line in self.opening_hours.splitlines() if line.strip()]


STARS = [MinValueValidator(1), MaxValueValidator(5)]
# the three questions, 1 to 5 stars each: (field, label, Bootstrap icon)
ASPECTS = [
    ("food_rating", "Food", "egg-fried"),
    ("staff_rating", "Staff", "person-heart"),
    ("cafe_rating", "Cafe", "shop"),
]


class Feedback(models.Model):
    """A guest's stars for Food, Staff and the Cafe (1 to 5 each), from:

      the bill's "Rate your visit" link (web.views.order_feedback): stars only, tied
        to that order, once per order; the page shows the guest their bill
      the cafe website's form (web.views.cafe_feedback): the stars and a message

    `rating` is the overall stars (the three's average, rounded); older website
    feedback has only that. The cafe reads it all in Cafe profile > Feedback; its
    website shows the average stars, and the ones it picks under "Reviews"."""

    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name="feedback")
    order = models.OneToOneField("orders.Order", on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="feedback")
    name = models.CharField("your name", max_length=80)
    phone = models.CharField("mobile number", max_length=15, blank=True)
    rating = models.PositiveSmallIntegerField(validators=STARS)
    food_rating = models.PositiveSmallIntegerField("food", null=True, blank=True, validators=STARS)
    staff_rating = models.PositiveSmallIntegerField("staff", null=True, blank=True, validators=STARS)
    cafe_rating = models.PositiveSmallIntegerField("cafe", null=True, blank=True, validators=STARS)
    message = models.TextField("your feedback", max_length=1000, blank=True)
    show_on_site = models.BooleanField("show on the website", default=False)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "feedback"

    def __str__(self):
        return f"{self.restaurant.name}: {self.rating}★ {self.name}"

    def aspects(self):
        """[(label, icon, stars)] of the questions answered (none for older website feedback)."""
        return [(label, icon, getattr(self, field)) for field, label, icon in ASPECTS if getattr(self, field)]

    def set_overall(self):
        """`rating` from the three answers: their average, rounded (4, 5, 4 -> 4)."""
        given = [getattr(self, field) for field, _, _ in ASPECTS if getattr(self, field)]
        if given:
            self.rating = max(1, min(5, int(sum(given) / len(given) + 0.5)))


def rating_summary(feedback):
    """The stars a cafe shows: overall and each question's average, with how many rated.
    {"average": 4.6, "stars": 5, "count": 23,
     "aspects": [{"label": "Food", "icon": ..., "average": 4.7, "stars": 5, "count": 20}, ...]}
    ("stars": the average as whole stars to fill) or None when nobody has rated yet."""
    rows = list(feedback.values("rating", *[field for field, _, _ in ASPECTS]))
    if not rows:
        return None

    def mean(values):
        average = round(sum(values) / len(values), 1)
        return {"average": average, "stars": int(average + 0.5), "count": len(values)}

    aspects = []
    for field, label, icon in ASPECTS:
        given = [row[field] for row in rows if row[field]]
        if given:
            aspects.append({"label": label, "icon": icon, **mean(given)})
    return {**mean([row["rating"] for row in rows]), "aspects": aspects}
