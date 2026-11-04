from datetime import timedelta
from decimal import Decimal

from django import forms
from django.utils import timezone

from core.forms import add_bootstrap_classes

from .models import Bill, Offer, Payment


class DiscountForm(forms.Form):
    """The discount on the "Generate bill" screen: an amount in rupees, or a percent."""

    discount_type = forms.ChoiceField(
        choices=[("AMOUNT", "₹ Amount"), ("PERCENT", "% Percent")],
        initial="AMOUNT", widget=forms.RadioSelect,
    )
    discount_value = forms.DecimalField(
        label="Discount", required=False, min_value=Decimal("0"), max_digits=10, decimal_places=2,
        widget=forms.NumberInput(attrs={"step": "0.01", "min": "0", "inputmode": "decimal", "placeholder": "0"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["discount_value"].widget.attrs["class"] = "form-control"

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("discount_type") == "PERCENT" and (cleaned.get("discount_value") or 0) > 100:
            self.add_error("discount_value", "A percent discount cannot be more than 100%.")
        return cleaned

    def discount(self):
        """(type, value) to bill with; no discount while the form has errors."""
        if self.is_valid():
            return self.cleaned_data["discount_type"], self.cleaned_data["discount_value"] or 0
        return "AMOUNT", 0


class OfferForm(forms.ModelForm):
    """Add / edit a festival offer (Cafe profile > Offers)."""

    class Meta:
        model = Offer
        fields = ["name", "start_date", "end_date", "kind", "value", "min_bill", "is_active"]
        labels = {"name": "Offer name"}
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "e.g. Valentine's Day, Diwali week"}),
            "start_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "end_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "kind": forms.RadioSelect,
            "value": forms.NumberInput(attrs={"step": "0.01", "min": "0", "inputmode": "decimal", "placeholder": "e.g. 5"}),
            "min_bill": forms.NumberInput(attrs={"step": "1", "min": "0", "inputmode": "decimal"}),
        }
        help_texts = {"end_date": "The same day as From for a one-day offer."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.initial.setdefault("start_date", timezone.localdate())
            self.initial.setdefault("end_date", timezone.localdate())
        add_bootstrap_classes(self)

    def clean_name(self):
        return " ".join(self.cleaned_data["name"].split())

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", "The offer has to end on or after the day it starts.")
        value = cleaned.get("value")
        if value is not None:
            if value <= 0:
                self.add_error("value", "Give the discount, e.g. 5.")
            elif cleaned.get("kind") == Offer.Kind.PERCENT and value > 100:
                self.add_error("value", "A percent discount cannot be more than 100%.")
        return cleaned


def amount_field(label, required=True):
    return forms.DecimalField(
        label=label, required=required, min_value=Decimal("0.01"), max_digits=12, decimal_places=2,
        widget=forms.NumberInput(attrs={"step": "0.01", "min": "0", "inputmode": "decimal"}),
    )


def reference_field():
    return forms.CharField(
        label="Reference", max_length=50, required=False,
        help_text="Card last 4 digits or UPI reference (optional).",
    )


class PaymentForm(forms.Form):
    """One payment, or two at once when the guest splits it ("Split: 2 modes", e.g. cash + UPI).

    For cash, "cash given" only works out the change: it is not stored.
    """

    mode = forms.ChoiceField(choices=Payment.Mode.choices, initial=Payment.Mode.CASH, widget=forms.RadioSelect)
    amount = amount_field("Amount (₹)")
    reference_no = reference_field()
    # the second payment, only with "Split: 2 modes"
    split = forms.BooleanField(label="Split: 2 modes", required=False)
    mode2 = forms.ChoiceField(choices=Payment.Mode.choices, initial=Payment.Mode.UPI, widget=forms.RadioSelect, required=False)
    amount2 = amount_field("Amount (₹)", required=False)
    reference_no2 = reference_field()
    tendered = forms.DecimalField(
        label="Cash given by guest (₹)", required=False, min_value=Decimal("0"), max_digits=12, decimal_places=2,
        help_text="Optional. Shows the change to return.",
        widget=forms.NumberInput(attrs={"step": "1", "min": "0", "inputmode": "decimal"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("amount", "reference_no", "amount2", "reference_no2", "tendered"):
            self.fields[name].widget.attrs["class"] = "form-control"
        self.fields["split"].widget.attrs.update({"class": "form-check-input", "role": "switch"})

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("split"):
            if not cleaned.get("amount2"):
                self.add_error("amount2", "Enter the amount paid the second way.")
            if cleaned.get("mode2") == cleaned.get("mode"):
                self.add_error("mode2", "Pick a different mode for the second payment.")
        cash = self.cash_amount(cleaned)
        tendered = cleaned.get("tendered")
        if cash is None:
            cleaned["tendered"] = None  # no cash in this payment: nothing to give change on
        elif tendered and tendered < cash:
            self.add_error("tendered", "The cash given is less than the cash amount.")
        return cleaned

    @staticmethod
    def cash_amount(cleaned):
        """The part paid in cash (for the change), or None when nothing is cash."""
        if cleaned.get("mode") == Payment.Mode.CASH:
            return cleaned.get("amount")
        if cleaned.get("split") and cleaned.get("mode2") == Payment.Mode.CASH:
            return cleaned.get("amount2")
        return None

    def payments(self):
        """[(mode, amount, reference), ...]: one row, or two for a split payment."""
        data = self.cleaned_data
        rows = [(data["mode"], data["amount"], data["reference_no"].strip())]
        if data.get("split"):
            rows.append((data["mode2"], data["amount2"], data["reference_no2"].strip()))
        return rows

    def change_to_return(self):
        """Cash given minus the cash part, or None."""
        tendered = self.cleaned_data.get("tendered")
        cash = self.cash_amount(self.cleaned_data)
        if tendered and cash:
            return tendered - cash
        return None


class BillCancelForm(forms.Form):
    reason = forms.CharField(
        label="Reason", max_length=255,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "e.g. wrong table billed, guest walked out"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        add_bootstrap_classes(self)

    def clean_reason(self):
        return self.cleaned_data["reason"].strip()


class BillFilterForm(forms.Form):
    """Bill register filters. Dates default to today."""

    date_from = forms.DateField(label="From", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    date_to = forms.DateField(label="To", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    status = forms.ChoiceField(label="Status", required=False, choices=[("", "All bills")] + Bill.Status.choices)
    q = forms.CharField(label="Search", required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        add_bootstrap_classes(self)
        # bills are made today, never on a future day: the pickers stop at today
        for name in ("date_from", "date_to"):
            self.fields[name].widget.attrs["max"] = timezone.localdate().isoformat()

    def dates(self):
        """(from, to), today when empty; swapped round if typed backwards; never after today."""
        today = timezone.localdate()
        if not self.is_valid():
            return today, today
        date_from = min(self.cleaned_data["date_from"] or today, today)
        date_to = min(self.cleaned_data["date_to"] or date_from, today)
        if date_from > date_to:
            date_from, date_to = date_to, date_from
        if (date_to - date_from) > timedelta(days=366):
            date_from = date_to - timedelta(days=366)
        return date_from, date_to
