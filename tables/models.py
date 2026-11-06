import uuid
from datetime import datetime, timedelta

from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse

from core.models import Location, Restaurant

DEFAULT_BOOKING_LENGTH = timedelta(hours=2)  # a booking without an "until" lasts this long


class DiningTable(models.Model):
    """A physical table of one location. Its QR code opens /m/<qr_token>/ (never the table id).

    Each location also has one default "Takeaway" table (is_takeaway=True),
    made automatically by takeaway_table(). Take-away and delivery orders go
    on it, and it can hold many open orders at once (a dining table holds one).
    And one "Common table" (is_common=True, common_table()): a guest who orders
    Dine in from the public menu without picking a table sits there. It is a
    dining table that is never full: every guest's order on it is their own.
    Orders take their location from their table.
    """

    restaurant = models.ForeignKey(Restaurant, on_delete=models.PROTECT, related_name="tables")
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="tables")  # save() fills it
    name = models.CharField(max_length=30)                 # "T1"
    section = models.CharField(max_length=50, blank=True)  # "AC Hall"
    capacity = models.PositiveSmallIntegerField(default=4, validators=[MinValueValidator(1)])
    qr_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    is_active = models.BooleanField(default=True)
    is_takeaway = models.BooleanField(default=False, editable=False)
    is_common = models.BooleanField(default=False, editable=False)

    class Meta:
        ordering = ["section", "name"]
        constraints = [
            models.UniqueConstraint(fields=["location", "name"], name="unique_table_name_per_location"),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.location_id:  # a company with one outlet: its main location
            self.location = self.restaurant.main_location()
        super().save(*args, **kwargs)

    @property
    def label(self):
        """The table in a sentence: "Table T1". A name that already says it
        ("Table 1") is used as it is, so it never reads "Table Table 1"."""
        return self.name if self.name.lower().startswith("table") else f"Table {self.name}"

    @property
    def menu_path(self):
        """Where this table's guests order. A dining table: its own QR menu
        (/m/<token>/). The counter (take away and delivery): the restaurant's one
        public menu (/r/<slug>/), so every take-away / delivery guest sees the same
        menu; ?at=<location> for a location other than the main one."""
        if self.is_takeaway:
            return public_path("orders:public_menu", self.location)
        return reverse("orders:customer_menu", args=[self.qr_token])


def public_path(url_name, location):
    """A public page of the company (menu, booking) for this location: ?at=<id> unless it is the main one."""
    path = reverse(url_name, args=[location.restaurant.slug])
    return path if location.is_main else f"{path}?at={location.pk}"


class Booking(models.Model):
    """A table booking from a date and time until a date and time (30 minutes
    for a birthday cake, two days for a wedding), asked for on the public menu
    or taken by staff. Without an "until" it lasts DEFAULT_BOOKING_LENGTH.

    A booking from the public menu is a request until staff confirm it
    (usually after a call), so a fake booking never blocks a table.
    Staff may give it a table; on arrival it is marked Seated and the guests
    order from that table's QR as usual.
    """

    class Status(models.TextChoices):
        REQUESTED = "REQUESTED", "Requested"
        CONFIRMED = "CONFIRMED", "Confirmed"
        SEATED = "SEATED", "Seated"
        CANCELLED = "CANCELLED", "Cancelled"
        NO_SHOW = "NO_SHOW", "No-show"

    class Source(models.TextChoices):
        PUBLIC = "PUBLIC", "Public menu"
        STAFF = "STAFF", "Staff"

    # still to come: shown on the bookings screen and the floor
    UPCOMING = [Status.REQUESTED, Status.CONFIRMED]

    restaurant = models.ForeignKey(Restaurant, on_delete=models.PROTECT, related_name="bookings")
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="bookings")  # save() fills it
    booking_no = models.PositiveIntegerField()  # counts per location
    public_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)  # the guest's status page
    customer_name = models.CharField("name", max_length=100)
    customer_phone = models.CharField("mobile", max_length=15)
    guests = models.PositiveSmallIntegerField(default=2, validators=[MinValueValidator(1)])
    date = models.DateField()  # from
    time = models.TimeField()
    end_date = models.DateField("until (day)", blank=True)  # filled by save() when left empty
    end_time = models.TimeField("until (time)", blank=True)
    note = models.CharField(max_length=255, blank=True)
    table = models.ForeignKey(DiningTable, on_delete=models.SET_NULL, null=True, blank=True, related_name="bookings")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.REQUESTED)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.PUBLIC)
    cancel_reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "time"]
        constraints = [
            models.UniqueConstraint(fields=["location", "booking_no"], name="unique_booking_no_per_location"),
        ]

    def __str__(self):
        return f"Booking #{self.booking_no}"

    def save(self, *args, **kwargs):
        if not self.location_id:  # its table's location, else the main one
            self.location = self.table.location if self.table_id else self.restaurant.main_location()
        if self.end_date is None or self.end_time is None:  # no "until": the usual length
            ends = datetime.combine(self.date, self.time) + DEFAULT_BOOKING_LENGTH
            self.end_date, self.end_time = ends.date(), ends.time()
        super().save(*args, **kwargs)

    @property
    def is_upcoming(self):
        return self.status in self.UPCOMING

    @property
    def starts_at(self):
        """When it starts (a naive date and time, the restaurant's local time)."""
        return datetime.combine(self.date, self.time)

    @property
    def ends_at(self):
        return datetime.combine(self.end_date, self.end_time)

    @property
    def is_multi_day(self):
        return self.end_date != self.date

    @property
    def length_text(self):
        """How long: "30 min", "2 h", "1 h 30 min", "2 days", "1 day 4 h"."""
        return length_text(self.ends_at - self.starts_at)


def length_text(length):
    """A timedelta in words for a booking: "30 min", "2 h", "1 h 30 min", "2 days", "1 day 4 h"."""
    minutes = max(int(length.total_seconds() // 60), 0)
    days, minutes = divmod(minutes, 24 * 60)
    hours, minutes = divmod(minutes, 60)
    parts = []
    if days:
        parts.append(f"{days} day{'s' if days > 1 else ''}")
    if hours:
        parts.append(f"{hours} h")
    if minutes and not days:
        parts.append(f"{minutes} min")
    return " ".join(parts) or "0 min"


def overlapping(bookings, starts, ends):
    """The bookings (a queryset) that overlap starts..ends (naive local datetimes).
    One ending exactly when the other starts does not overlap."""
    near = bookings.filter(date__lte=ends.date(), end_date__gte=starts.date())
    return [booking for booking in near if booking.starts_at < ends and starts < booking.ends_at]


TAKEAWAY_NAME = "Takeaway"


def takeaway_table(restaurant, location=None):
    """The location's (default: the main one's) Takeaway table, made the first time it is needed."""
    location = location or restaurant.main_location()
    table = DiningTable.objects.filter(location=location, is_takeaway=True).first()
    if table is None:
        # a dining table may already be called "Takeaway"; then use another name
        name = TAKEAWAY_NAME
        if DiningTable.objects.filter(location=location, name__iexact=name).exists():
            name = "Takeaway counter"
        table = DiningTable.objects.create(
            restaurant=restaurant, location=location, name=name, section="Counter", capacity=1, is_takeaway=True,
        )
    return table


COMMON_NAME = "Common table"


def common_table(restaurant, location=None):
    """The location's Common table: Dine in from the public menu without a table picked.
    Made the first time it is needed; never checked for free seats (each order is its own)."""
    location = location or restaurant.main_location()
    table = DiningTable.objects.filter(location=location, is_common=True).first()
    if table is None:
        name = COMMON_NAME
        if DiningTable.objects.filter(location=location, name__iexact=name).exists():
            name = "Common"
        table = DiningTable.objects.create(
            restaurant=restaurant, location=location, name=name, section="Common", capacity=1, is_common=True,
        )
    return table


def tables_to_pick(location):
    """The tables a guest may pick on the public menu (Dine in): this location's open dining tables."""
    return DiningTable.objects.filter(location=location, is_active=True, is_takeaway=False, is_common=False)
