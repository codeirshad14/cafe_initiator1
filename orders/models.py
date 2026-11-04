import uuid

from django.db import models
from django.utils import timezone

from core.models import Location, Restaurant, Staff
from menu.models import MenuItem
from tables.models import DiningTable


class Order(models.Model):
    """One bill's worth of ordering: from the first round until it is paid. Has many KOTs.

    Usually a table has one order. When people at the same table want to pay
    separately, each starts their own order there ("My own bill"), so a table
    can hold several running orders, each with its own bill.

    Take-away and delivery orders ("parcels") sit on the restaurant's counter
    table (the default Takeaway table); many can be open there at once.

    A delivery asked for on the public menu starts as PENDING ("To confirm"):
    its KOT stays out of the kitchen until staff call the customer and confirm.
    A rider then takes it, delivers it and collects the payment.
    """

    class Source(models.TextChoices):
        QR = "QR", "QR scan"
        WAITER = "WAITER", "Waiter"

    class OrderType(models.TextChoices):
        DINE_IN = "DINE_IN", "Dine in"
        TAKEAWAY = "TAKEAWAY", "Take away"
        DELIVERY = "DELIVERY", "Delivery"

    class Status(models.TextChoices):
        PENDING = "PENDING", "To confirm"  # a delivery from the public menu, not in the kitchen yet
        OPEN = "OPEN", "Open"
        BILLED = "BILLED", "Billed"
        CLOSED = "CLOSED", "Closed"
        CANCELLED = "CANCELLED", "Cancelled"

    # an order that still holds its table
    RUNNING = [Status.OPEN, Status.BILLED]
    # an order staff may still cancel (a billed one: with its bill, while nothing is paid)
    CANCELLABLE = [Status.PENDING, Status.OPEN, Status.BILLED]

    restaurant = models.ForeignKey(Restaurant, on_delete=models.PROTECT, related_name="orders")
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="orders")  # save(): the table's
    table = models.ForeignKey(DiningTable, on_delete=models.PROTECT, null=True, blank=True, related_name="orders")
    order_no = models.PositiveIntegerField()  # counts per location
    public_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    customer_name = models.CharField(max_length=100)
    customer_phone = models.CharField(max_length=15, blank=True)
    customer_address = models.CharField("address", max_length=255, blank=True)  # needed for delivery
    waiter = models.ForeignKey(Staff, on_delete=models.SET_NULL, null=True, blank=True, related_name="orders")
    # delivery: who takes it, when it left the counter and when it reached the customer
    rider = models.ForeignKey(Staff, on_delete=models.SET_NULL, null=True, blank=True, related_name="deliveries")
    picked_up_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.QR)
    order_type = models.CharField(max_length=10, choices=OrderType.choices, default=OrderType.DINE_IN)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    cancel_reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["location", "order_no"], name="unique_order_no_per_location"),
        ]

    def __str__(self):
        return f"Order #{self.order_no}"

    def save(self, *args, **kwargs):
        if not self.location_id:  # where it is eaten or packed: its table's location
            self.location = self.table.location if self.table_id else self.restaurant.main_location()
        super().save(*args, **kwargs)

    @property
    def is_takeaway(self):
        return self.order_type == self.OrderType.TAKEAWAY

    @property
    def is_delivery(self):
        return self.order_type == self.OrderType.DELIVERY

    @property
    def is_parcel(self):
        """Packed to leave: take away or delivery (not at a table)."""
        return self.order_type in (self.OrderType.TAKEAWAY, self.OrderType.DELIVERY)

    @property
    def place_label(self):
        """Where the order is for, for screens and lists: "Table T1", "Take away" or "Delivery"."""
        if self.is_delivery:
            return "Delivery"
        if self.is_takeaway:
            return "Take away"
        return self.table.label if self.table_id else "—"

    @property
    def print_label(self):
        """The order type as bills and KOTs print it: "Dine in · Table T1", "Takeaway" or "Delivery"."""
        if self.is_delivery:
            return "Delivery"
        if self.is_takeaway:
            return "Takeaway"
        return f"Dine in · Table {self.table.name}" if self.table_id else "Dine in"

    @property
    def ride_minutes(self):
        """A delivery's ride, from Picked up to Delivered, in minutes: so far while it is
        on the way, the full ride once delivered, None before it leaves."""
        if not self.picked_up_at:
            return None
        end = self.delivered_at or timezone.now()
        return max(0, int((end - self.picked_up_at).total_seconds() // 60))

    @property
    def is_pending(self):
        """A public delivery order still waiting for the restaurant to confirm it."""
        return self.status == self.Status.PENDING

    @property
    def delivery_stage(self):
        """Where a delivery is: "to confirm", "in kitchen", "with rider", "delivered" (None for others)."""
        if not self.is_delivery:
            return None
        if self.status == self.Status.CANCELLED:
            return "cancelled"
        if self.is_pending:
            return "to confirm"
        if self.delivered_at:
            return "delivered"
        if self.picked_up_at:
            return "with rider"
        return "in kitchen"

    @property
    def is_running(self):
        """True while the guests are still at the table (not paid or cancelled)."""
        return self.status in self.RUNNING

    @property
    def is_live(self):
        """Still moving, so the guest's status page keeps refreshing: running, waiting
        to be confirmed, or a delivery not handed over yet (even when paid ahead)."""
        if self.status == self.Status.CANCELLED:
            return False
        return self.is_running or self.is_pending or (self.is_delivery and not self.delivered_at)


class KOT(models.Model):
    """Kitchen Order Ticket: one round of ordering inside an Order."""

    class Status(models.TextChoices):
        HELD = "HELD", "To confirm"  # a public delivery not confirmed yet: kept out of the kitchen
        NEW = "NEW", "New"
        PREPARING = "PREPARING", "Preparing"
        READY = "READY", "Ready"
        SERVED = "SERVED", "Served"
        CANCELLED = "CANCELLED", "Cancelled"

    restaurant = models.ForeignKey(Restaurant, on_delete=models.PROTECT, related_name="kots")
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="kots")  # save(): the order's
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="kots")
    kot_no = models.PositiveIntegerField()  # counts per location
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.NEW)
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    served_at = models.DateTimeField(null=True, blank=True)
    served_by = models.ForeignKey(Staff, on_delete=models.SET_NULL, null=True, blank=True, related_name="served_kots")

    class Meta:
        ordering = ["created_at"]
        verbose_name = "KOT"
        constraints = [
            models.UniqueConstraint(fields=["location", "kot_no"], name="unique_kot_no_per_location"),
        ]

    def __str__(self):
        return f"KOT #{self.kot_no}"

    def save(self, *args, **kwargs):
        if not self.location_id:
            self.location = self.order.location
        super().save(*args, **kwargs)


class KOTItem(models.Model):
    """One line on a KOT. Name and rate are copied, so later price changes don't affect it."""

    kot = models.ForeignKey(KOT, on_delete=models.CASCADE, related_name="items")
    menu_item = models.ForeignKey(MenuItem, on_delete=models.PROTECT, related_name="kot_items")
    item_name = models.CharField(max_length=150)                   # snapshot
    rate = models.DecimalField(max_digits=10, decimal_places=2)    # snapshot
    qty = models.PositiveIntegerField(default=1)
    amount = models.DecimalField(max_digits=12, decimal_places=2)  # rate x qty
    is_cancelled = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.item_name} x {self.qty}"


class Notification(models.Model):
    """ "New order" in the bell of the top bar (orders/notification_views.py), for everyone
    working at the order's location. It is made with the order (services.place_kot).

    Read once means read for all: when one person opens it (or Mark all as read),
    the order has been seen to, so it leaves every bell.
    """

    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name="notifications")
    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="notifications")
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="notifications")
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)
    read_by = models.ForeignKey(Staff, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["location", "read_at"], name="notification_unread")]

    def __str__(self):
        return f"New order #{self.order.order_no}"
