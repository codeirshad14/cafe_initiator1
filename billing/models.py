from decimal import Decimal

from django.db import models
from django.utils import timezone

from core.models import Location, Restaurant, Staff
from menu.models import MenuItem
from orders.models import Order

ZERO = Decimal("0.00")


class Bill(models.Model):
    """The voucher for one Order, built from all its KOTs."""

    class Status(models.TextChoices):
        UNPAID = "UNPAID", "Unpaid"
        PARTIAL = "PARTIAL", "Partly paid"
        PAID = "PAID", "Paid"
        CANCELLED = "CANCELLED", "Cancelled"

    restaurant = models.ForeignKey(Restaurant, on_delete=models.PROTECT, related_name="bills")
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="bills")  # save(): the order's
    order = models.OneToOneField(Order, on_delete=models.PROTECT, related_name="bill")
    bill_no = models.PositiveIntegerField()  # counts per location
    bill_date = models.DateField(default=timezone.localdate)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    offer_name = models.CharField(max_length=60, blank=True)  # the festival offer behind the discount, if any
    delivery_charge = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO)  # delivery orders only
    taxable_amount = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    gst_percent = models.DecimalField(max_digits=5, decimal_places=2, default=ZERO)  # snapshot
    cgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    sgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    round_off = models.DecimalField(max_digits=6, decimal_places=2, default=ZERO)
    grand_total = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.UNPAID)
    cancel_reason = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(Staff, on_delete=models.SET_NULL, null=True, blank=True, related_name="bills_created")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-bill_no"]
        constraints = [
            models.UniqueConstraint(fields=["location", "bill_no"], name="unique_bill_no_per_location"),
        ]

    def __str__(self):
        return f"Bill #{self.bill_no}"

    def save(self, *args, **kwargs):
        if not self.location_id:
            self.location = self.order.location
        super().save(*args, **kwargs)

    def all_orders(self):
        """Its order, then the orders billed together on it (billing.services.make_bill join)."""
        return [self.order, *sorted(self.joined_orders.all(), key=lambda order: order.order_no)]

    def _tables(self):
        names = []
        for order in self.all_orders():
            if order.table_id and order.table.name not in names:
                names.append(order.table.name)
        return names

    @property
    def place_label(self):
        """For screens: "Table T1", or billed together across tables: "Tables T1 + T2"."""
        names = self._tables() if self.joined_orders.exists() else []
        return f"Tables {' + '.join(names)}" if len(names) > 1 else self.order.place_label

    @property
    def print_label(self):
        """As the bill prints it: "Dine in · Table T1", or "Dine in · Tables T1 + T2"."""
        names = self._tables() if self.joined_orders.exists() else []
        return f"Dine in · Tables {' + '.join(names)}" if len(names) > 1 else self.order.print_label

    @property
    def order_numbers(self):
        """"#210", or billed together: "#210 + #211"."""
        return " + ".join(f"#{order.order_no}" for order in self.all_orders())

    @property
    def balance(self):
        """Amount still to be paid (never below zero)."""
        return max(self.grand_total - self.paid_amount, ZERO)

    @property
    def tax_amount(self):
        return self.cgst_amount + self.sgst_amount

    @property
    def half_percent(self):
        """Each of CGST and SGST, e.g. 2.5 for 5% GST."""
        return self.gst_percent / 2

    @property
    def is_open_for_payment(self):
        """Payments can still be added or removed."""
        return self.status in (self.Status.UNPAID, self.Status.PARTIAL)


class BillItem(models.Model):
    """One merged line on the bill (same item at the same rate across KOTs = one line)."""

    bill = models.ForeignKey(Bill, on_delete=models.CASCADE, related_name="items")
    menu_item = models.ForeignKey(MenuItem, on_delete=models.PROTECT, related_name="bill_items")
    item_name = models.CharField(max_length=150)      # snapshot
    category_name = models.CharField(max_length=100)  # snapshot, for category-wise report
    rate = models.DecimalField(max_digits=10, decimal_places=2)
    qty = models.PositiveIntegerField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"{self.item_name} x {self.qty}"


class Payment(models.Model):
    """One payment row. Several rows on one bill = multi-mode payment."""

    class Mode(models.TextChoices):
        CASH = "CASH", "Cash"
        CREDIT_CARD = "CREDIT_CARD", "Credit card"
        DEBIT_CARD = "DEBIT_CARD", "Debit card"
        UPI = "UPI", "UPI"
        ONLINE = "ONLINE", "Online"

    restaurant = models.ForeignKey(Restaurant, on_delete=models.PROTECT, related_name="payments")
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="payments")  # save(): the bill's
    bill = models.ForeignKey(Bill, on_delete=models.PROTECT, related_name="payments")
    mode = models.CharField(max_length=12, choices=Mode.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reference_no = models.CharField(max_length=50, blank=True)  # card last 4 / UPI ref
    received_by = models.ForeignKey(Staff, on_delete=models.SET_NULL, null=True, blank=True, related_name="payments_received")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.get_mode_display()} ₹{self.amount}"

    def save(self, *args, **kwargs):
        if not self.location_id:
            self.location = self.bill.location
        super().save(*args, **kwargs)


class Offer(models.Model):
    """A festival / special-day discount (Valentine's Day, Diwali week ...): ₹ or %
    off every bill made on those dates, from an optional minimum bill amount.
    Applied by itself on the bill screen (billing.services.offer_for); the
    cashier can still change or remove it on a bill."""

    class Kind(models.TextChoices):
        AMOUNT = "AMOUNT", "₹ off"
        PERCENT = "PERCENT", "% off"

    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name="offers")
    name = models.CharField(max_length=60)
    start_date = models.DateField("from")
    end_date = models.DateField("until")
    kind = models.CharField("discount in", max_length=8, choices=Kind.choices, default=Kind.PERCENT)
    value = models.DecimalField("discount", max_digits=10, decimal_places=2)
    min_bill = models.DecimalField("for bills from (₹)", max_digits=10, decimal_places=2, default=ZERO,
                                   help_text="The food total (before GST) a bill needs. 0 = every bill.")
    is_active = models.BooleanField("switched on", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date", "name"]

    def __str__(self):
        return self.name

    @property
    def label(self):
        """e.g. "5% off" or "₹50 off"."""
        value = f"{self.value.normalize():f}"
        return f"{value}% off" if self.kind == self.Kind.PERCENT else f"₹{value} off"

    def runs_on(self, day):
        return self.is_active and self.start_date <= day <= self.end_date
