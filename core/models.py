import calendar
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.functional import cached_property

from .plans import LIMITS, NEAR_LIMIT, TIER_CHOICES

# ---------------------------------------------------------------- membership
#
# Each restaurant pays for a plan, monthly or yearly. While today is inside
# its membership dates its staff can log in and its QR menus take orders;
# once it ends they cannot. Its membership type (Only Menu, Basic, Standard,
# Enterprise, Ultimate: core/plans.py) says what it may use. Only the platform
# owner sets or renews it, in the Django admin ("Renew membership" action).
# The restaurant's own screens never show these fields for editing.

DEFAULT_MAX_USERS = 5  # e.g. admin + cashier + kitchen + 2 waiters


def add_months(day, months):
    """Same day `months` later; a day the month lacks becomes its last day
    (31 Jan + 1 month = 28/29 Feb)."""
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return day.replace(year=year, month=month, day=min(day.day, last_day))


def membership_end_for(start, plan):
    """Last day of one plan period, both days counted:
    monthly 7 Oct -> 6 Nov, yearly 7 Oct 2026 -> 6 Oct 2027."""
    months = 12 if plan == Restaurant.Plan.YEARLY else 1
    return add_months(start, months) - timedelta(days=1)


def first_membership_end():
    """A new restaurant starts with one monthly period from today."""
    return membership_end_for(timezone.localdate(), "MONTHLY")


MAX_SLIDE_MB = 2


def validate_slide_size(photo):
    """A slider photo may be up to 2 MB (checked in Restaurant settings and the Django admin alike).
    Only a newly chosen photo is measured: a saved one passed when it came in, and its file
    may be gone (site moved, backup restored), which must not block saving the profile."""
    if getattr(photo, "_committed", False):
        return
    if photo.size > MAX_SLIDE_MB * 1024 * 1024:
        raise ValidationError(f"The photo is too big. Please use one under {MAX_SLIDE_MB} MB.")


class Restaurant(models.Model):
    """One restaurant = one SaaS customer. Every business row points here."""

    class Plan(models.TextChoices):
        MONTHLY = "MONTHLY", "Monthly"
        YEARLY = "YEARLY", "Yearly"

    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=160, unique=True)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    gstin = models.CharField("GSTIN", max_length=15, blank=True)
    gst_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("5.00"))
    fssai_no = models.CharField("FSSAI no.", max_length=20, blank=True)
    logo = models.ImageField(upload_to="logos/", blank=True)

    # the public menu's slider: slide 1 is the restaurant itself, then these photos
    # (offers, the place, signature dishes), each with an optional short caption
    slide_1 = models.ImageField("slider photo 1", upload_to="slides/", blank=True, validators=[validate_slide_size])
    slide_1_text = models.CharField("caption", max_length=80, blank=True)
    slide_2 = models.ImageField("slider photo 2", upload_to="slides/", blank=True, validators=[validate_slide_size])
    slide_2_text = models.CharField("caption", max_length=80, blank=True)
    slide_3 = models.ImageField("slider photo 3", upload_to="slides/", blank=True, validators=[validate_slide_size])
    slide_3_text = models.CharField("caption", max_length=80, blank=True)

    # home delivery: customers ask from the public menu (staff confirm first) or
    # staff take it on a call; a rider delivers and collects the payment
    delivery_enabled = models.BooleanField("take delivery orders", default=True)
    # blank = 0 (save() fills it in), so older forms without these fields still save
    delivery_charge = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal("0.00"), blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Added to every delivery bill. 0 = free delivery.",
    )
    free_delivery_above = models.DecimalField(
        "free delivery from", max_digits=10, decimal_places=2, default=Decimal("0.00"), blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Orders of this amount or more are delivered free. 0 = no free-delivery amount.",
    )
    # table bookings asked from the public menu (staff confirm them)
    booking_enabled = models.BooleanField("take table bookings", default=True)

    # the printed bill (Cafe profile > Bill & print), the same for every bill
    print_name = models.CharField(
        "name on the bill", max_length=150, blank=True,
        help_text="The company name printed on the bill, when it differs from the cafe name. "
                  "Empty = the cafe name.",
    )
    invoice_title = models.CharField("bill title", max_length=40, default="TAX INVOICE",
                                     help_text="Printed at the top of every bill, e.g. TAX INVOICE, BILL, ESTIMATE.")
    print_logo = models.BooleanField("print the logo on the bill", default=True)
    print_tax_details = models.BooleanField(
        "print tax details", default=True,
        help_text="GSTIN, and CGST / SGST lines. Off: one Taxes line (only when there is GST on the bill).",
    )
    upi_id = models.CharField("UPI ID", max_length=60, blank=True, help_text="e.g. spicegarden@okicici")
    upi_qr = models.ImageField("UPI QR code", upload_to="upi/", blank=True, validators=[validate_slide_size],
                               help_text="The QR code picture from your bank or UPI app (PNG or JPG).")
    print_upi = models.BooleanField("print UPI QR code and ID on the bill", default=True)

    # membership: Django admin only
    tier = models.CharField(
        "membership type", max_length=10, choices=TIER_CHOICES, default="BASIC",
        help_text="Only Menu: the menu only. Basic / Standard: every app, 10,000 / 50,000 bills a year, "
                  "1 location. Enterprise: 50,00,000 bills a year, 20 locations. Ultimate: no limits.",
    )
    plan = models.CharField("membership plan", max_length=10, choices=Plan.choices, default=Plan.MONTHLY)
    membership_start = models.DateField("membership from", default=timezone.localdate)
    membership_end = models.DateField(
        "membership valid till", default=first_membership_end,
        help_text="Last day the staff can log in and QR menus take orders. "
                  "Use the “Renew membership” action to add one more plan period.",
    )
    max_users = models.PositiveSmallIntegerField(
        "logins allowed", default=DEFAULT_MAX_USERS, validators=[MinValueValidator(1)],
        help_text="How many staff logins may be active at once, the restaurant admin included.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # +1 on every order / KOT / bill / payment / booking change: live screens (core/live.py)
    live_version = models.PositiveBigIntegerField(default=0, editable=False)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # an empty delivery charge / free-delivery amount means 0
        self.delivery_charge = self.delivery_charge or Decimal("0.00")
        self.free_delivery_above = self.free_delivery_above or Decimal("0.00")
        super().save(*args, **kwargs)

    SLIDE_SLOTS = (1, 2, 3)

    def slides(self):
        """The slider photos that are set, in order: [{"image": ..., "text": ...}]."""
        return [
            {"image": getattr(self, f"slide_{n}"), "text": getattr(self, f"slide_{n}_text")}
            for n in self.SLIDE_SLOTS if getattr(self, f"slide_{n}")
        ]

    @property
    def bill_name(self):
        """The name printed on bills: the company's, else the cafe's."""
        return self.print_name or self.name

    @property
    def shows_upi_on_bill(self):
        return self.print_upi and bool(self.upi_id or self.upi_qr)

    def delivery_charge_for(self, food_amount):
        """The delivery charge for an order whose food comes to food_amount (after discount)."""
        if self.free_delivery_above > 0 and food_amount >= self.free_delivery_above:
            return Decimal("0.00")
        return self.delivery_charge

    # ---- membership
    @property
    def membership_active(self):
        """Today is inside the membership dates (both days included)."""
        return self.membership_start <= timezone.localdate() <= self.membership_end

    @property
    def membership_days_left(self):
        """Days left, today included; 0 once it has ended."""
        return max(0, (self.membership_end - timezone.localdate()).days + 1)

    def renew_membership(self):
        """Add one plan period. Still running: it starts after the current end,
        so no paid day is lost. Already ended: a fresh period from today."""
        today = timezone.localdate()
        if self.membership_end >= today:
            self.membership_end = membership_end_for(self.membership_end + timedelta(days=1), self.plan)
        else:
            self.membership_start = today
            self.membership_end = membership_end_for(today, self.plan)

    def is_usable(self):
        """True when the restaurant is switched on and its membership is running."""
        return self.is_active and self.membership_active

    # ---- membership type (core/plans.py): what the cafe may use
    @property
    def menu_only(self):
        """Only Menu: the cafe profile and the menu; guests look, they do not order."""
        return self.tier == "MENU"

    @property
    def takes_orders(self):
        """Its QR menus take orders (and bookings): running, and not Only Menu."""
        return self.is_usable() and not self.menu_only

    @property
    def bill_limit(self):
        """Bills a membership year, or None for no limit."""
        return LIMITS[self.tier]["bills"]

    @property
    def location_limit(self):
        """Open locations allowed, or None for no limit."""
        return LIMITS[self.tier]["locations"]

    def plan_year(self, today=None):
        """(first day, last day) of the membership year today is in: 12 months from the
        day the membership started, then again from each anniversary."""
        today = today or timezone.localdate()
        start, years = self.membership_start, 0
        while add_months(start, 12 * (years + 1)) <= today:
            years += 1
        return add_months(start, 12 * years), add_months(start, 12 * (years + 1)) - timedelta(days=1)

    @cached_property
    def plan_usage(self):
        """This membership year's bills against the plan, for the account menu and the Bills page:
        {"bills", "limit", "left", "percent", "near", "full", "start", "end"} (limit None: no limit)."""
        start, end = self.plan_year()
        used = self.bills.filter(bill_date__range=(start, end)).exclude(status="CANCELLED").count()
        limit = self.bill_limit
        return {
            "bills": used, "limit": limit, "start": start, "end": end,
            "left": None if limit is None else max(0, limit - used),
            "percent": 0 if not limit else min(100, round(used * 100 / limit)),
            "near": limit is not None and used >= limit * NEAR_LIMIT,
            "full": limit is not None and used >= limit,
        }

    def can_make_bill(self):
        """One more bill fits in this membership year (counted afresh, not from plan_usage)."""
        if self.bill_limit is None:
            return True
        start, end = self.plan_year()
        return self.bills.filter(bill_date__range=(start, end)).exclude(status="CANCELLED").count() < self.bill_limit

    def bill_limit_message(self):
        """What "Make bill" says once the year's bills are used."""
        from .templatetags.money import indian_grouping
        start, end = self.plan_year()
        if self.menu_only:
            return "Your Only Menu plan has no billing. Upgrade to Basic or higher to make bills: contact us."
        return (f"Your {self.get_tier_display()} plan includes {indian_grouping(str(self.bill_limit))} bills a year "
                f"({start:%d %b %Y} – {end:%d %b %Y}), and all are used. Upgrade your plan to make more bills: "
                f"contact us.")

    def can_open_location(self):
        """One more open location fits in the plan."""
        limit = self.location_limit
        return limit is None or self.locations.filter(is_active=True).count() < limit

    def location_limit_message(self):
        limit = self.location_limit
        s = "s" if limit != 1 else ""
        return (f"Your {self.get_tier_display()} plan includes {limit} open location{s}, and all are in use. "
                f"Upgrade to Enterprise (20 locations) or Ultimate to open more: contact us.")

    # ---- logins allowed (max_users)
    @property
    def active_users(self):
        """How many staff logins of this restaurant can log in right now."""
        return self.staff_members.filter(is_active=True, user__is_active=True).count()

    @property
    def can_add_user(self):
        """One more active login fits in the plan."""
        return self.active_users < self.max_users

    def user_limit_message(self):
        """What the restaurant admin is told when every allowed login is in use."""
        s = "s" if self.max_users != 1 else ""
        return (f"Your plan allows {self.max_users} active login{s} (you included), and all are in use. "
                f"Switch off a login you no longer need, or contact us to allow more.")

    # ---- locations (outlets)
    def main_location(self):
        """The first location; made ("Main") the first time it is needed, so a
        company with one outlet never has to think about locations."""
        location = self.locations.order_by("created_at", "pk").first()
        if location is None:
            location = Location.objects.create(restaurant=self, name="Main", address=self.address, phone=self.phone)
        return location


class Location(models.Model):
    """One outlet of a company (Restaurant), e.g. "MG Road" of a chain of ten cafes.

    Each has its own tables (and Takeaway counter), and its own order, KOT, bill
    and booking numbers. Every order, KOT, bill, payment and booking carries its
    location, filled in by itself from the table (or the order / bill). The menu,
    the bill settings and the offers are the company's, shared by every location.
    Staff are mapped to locations (Staff.locations); admin and manager see all.
    """

    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name="locations")
    name = models.CharField("location name", max_length=100)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField("open", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["restaurant", "name"], name="unique_location_name_per_restaurant"),
        ]

    def __str__(self):
        return self.name

    @property
    def is_main(self):
        return self.pk == self.restaurant.main_location().pk


class Staff(models.Model):
    """A login that works at one restaurant (company). The role decides what they
    can open (core/roles.py); the locations, where (admin and manager: everywhere).

    One restaurant per login (OneToOne with User): logging in decides the
    restaurant, so there is nothing to pick and no way into another one.
    The login ID is the email address (core/auth.py).
    """

    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Admin"
        MANAGER = "MANAGER", "Manager"  # everything, every location
        RM = "RM", "Restaurant manager"  # everything at their own location(s)
        ALL = "ALL", "All-rounder"  # every service screen, the waiter's and the rider's too
        CASHIER = "CASHIER", "Cashier (bills)"
        KITCHEN = "KITCHEN", "Kitchen"
        WAITER = "WAITER", "Waiter"
        RIDER = "RIDER", "Rider"  # delivers orders and collects the payment

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="staff")
    restaurant = models.ForeignKey(Restaurant, on_delete=models.PROTECT, related_name="staff_members")
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20, blank=True)
    role = models.CharField(max_length=10, choices=Role.choices)
    # where they work; none = the main location. Admin and manager work everywhere.
    locations = models.ManyToManyField(Location, blank=True, related_name="staff_members")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "staff"

    def __str__(self):
        return f"{self.name} ({self.get_role_display()})"

    @property
    def initials(self):
        """Up to two letters for the round avatar, e.g. "Ravi Kumar" -> "RK"."""
        parts = self.name.split()
        return "".join(part[0] for part in parts[:2]).upper() or "?"

    @property
    def works_everywhere(self):
        return self.role in (self.Role.ADMIN, self.Role.MANAGER)

    def allowed_locations(self):
        """The open locations this login may work at (at least the main one)."""
        open_ones = self.restaurant.locations.filter(is_active=True)
        if self.works_everywhere:
            allowed = list(open_ones)
        else:
            allowed = list(open_ones.filter(pk__in=self.locations.values("pk")))
        return allowed or [self.restaurant.main_location()]
