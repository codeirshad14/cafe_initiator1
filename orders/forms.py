from django import forms

from core.forms import add_bootstrap_classes
from core.utils import clean_indian_mobile

from .models import Order

DINE_IN = Order.OrderType.DINE_IN
TAKEAWAY = Order.OrderType.TAKEAWAY
DELIVERY = Order.OrderType.DELIVERY


def order_type_field():
    """The order type, shown as big choices (which ones: OrderTypeMixin).

    Not required: a form sent without it (an older page still open) gets the
    first choice (Dine in at a table, Take away at the counter).
    """
    return forms.ChoiceField(
        label="How would you like it?", choices=Order.OrderType.choices, initial=DINE_IN,
        widget=forms.RadioSelect, required=False,
    )


def address_field():
    return forms.CharField(
        label="Address", max_length=255, required=False,
        help_text="Optional for take-away. Needed for delivery.",
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "House / flat, street, landmark, area",
                                     "autocomplete": "street-address"}),
    )


def bill_field():
    """Dine in at a table that already has an order: which bill this round goes on.
    "" = the usual (this phone's / the table's order), "new" = my own bill, "12" = order 12.
    The template shows it as radio buttons (orders/_bill_choice.html)."""
    return forms.CharField(required=False, max_length=12)


class OrderTypeMixin:
    """Order type choices and the delivery rules, shared by the guest's and the waiter's form.

    At a dining table: Dine in, or Take away (the guest's QR menu only; staff
    at a table take Dine in, takeaway is the floor's own "New takeaway").
    At the counter (the Takeaway table, also the public menu): Take away, or
    Delivery when the restaurant takes deliveries. With one choice left it is
    not shown at all.
    Delivery needs a name, a mobile number and an address (a rider goes there).
    """

    def set_order_types(self, counter, delivery, takeaway_at_table=True):
        if counter:
            choices = [(TAKEAWAY, "Take away")]
        else:
            choices = [(DINE_IN, "Dine in")] + ([(TAKEAWAY, "Take away")] if takeaway_at_table else [])
        if counter and delivery:
            choices.append((DELIVERY, "Delivery"))
        field = self.fields["order_type"]
        field.choices = choices
        field.initial = choices[0][0]
        if len(choices) == 1:
            field.widget = forms.HiddenInput()
        self.default_type = choices[0][0]

    def clean_order_type(self):
        return self.cleaned_data["order_type"] or self.default_type

    def clean_customer_name(self):
        return " ".join(self.cleaned_data["customer_name"].split())

    def clean_customer_phone(self):
        return clean_indian_mobile(self.cleaned_data["customer_phone"])

    def clean_customer_address(self):
        return " ".join(self.cleaned_data["customer_address"].split())

    def clean_note(self):
        return self.cleaned_data["note"].strip()

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("order_type") == DELIVERY:
            for field, text in [
                ("customer_name", "Please give a name for the delivery."),
                ("customer_phone", "Please give a mobile number, so the rider can call."),
                ("customer_address", "Please give the address to deliver to."),
            ]:
                if field in cleaned and not cleaned[field]:
                    self.add_error(field, text)
        return cleaned


class CustomerOrderForm(OrderTypeMixin, forms.Form):
    """The guest's details on the cart page.

    Dine in / take away: name, mobile and address are optional; without a
    name the order shows "Guest at <table>" / "Takeaway guest".
    Delivery (public menu only): name, mobile and address are needed, and
    the restaurant calls to confirm before cooking.
    """

    order_type = order_type_field()
    bill = bill_field()
    customer_name = forms.CharField(label="Your name", max_length=60, required=False)
    customer_phone = forms.CharField(
        label="Mobile number", max_length=15, required=False,
        help_text="Optional for take-away. Needed for delivery.",
        widget=forms.TextInput(attrs={"inputmode": "tel", "autocomplete": "tel", "placeholder": "10-digit mobile"}),
    )
    customer_address = address_field()
    note = forms.CharField(
        label="Note for the kitchen", max_length=200, required=False,
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "e.g. less spicy, no onion"}),
    )

    def __init__(self, *args, counter=False, delivery=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_order_types(counter, delivery)
        self.fields["customer_name"].widget.attrs.update({"autocomplete": "name", "placeholder": "Your name"})
        add_bootstrap_classes(self)


class WaiterOrderForm(OrderTypeMixin, forms.Form):
    """What staff add when sending a round: the order type, the guest's details, a kitchen note.

    One order type per screen: a table is Dine in; the counter is "New takeaway"
    or "New delivery" (the screen sends its type, both are valid here).
    A delivery taken by staff (a call or a walk-in) goes straight to the kitchen.
    """

    order_type = order_type_field()
    bill = bill_field()
    customer_name = forms.CharField(
        label="Guest name", max_length=60, required=False,
        widget=forms.TextInput(attrs={"placeholder": "e.g. Ravi", "autocomplete": "off"}),
    )
    customer_phone = forms.CharField(
        label="Guest mobile", max_length=15, required=False,
        widget=forms.TextInput(attrs={"placeholder": "e.g. 98765 43210", "inputmode": "tel", "autocomplete": "off"}),
    )
    customer_address = address_field()
    note = forms.CharField(
        label="Note for the kitchen", max_length=200, required=False,
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "e.g. less spicy, serve together"}),
    )

    def __init__(self, *args, counter=False, delivery=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_order_types(counter, delivery, takeaway_at_table=False)
        add_bootstrap_classes(self)


class OrderCancelForm(forms.Form):
    """Why an order is cancelled. Kept on the order for the cancelled report."""

    reason = forms.CharField(
        label="Reason", max_length=255,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "e.g. guests left before ordering, wrong table"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        add_bootstrap_classes(self)

    def clean_reason(self):
        return self.cleaned_data["reason"].strip()


class TrackLookupForm(forms.Form):
    """Find an order by its number (shown on the order-placed screen)."""

    order_no = forms.IntegerField(
        label="Order number", min_value=1,
        widget=forms.NumberInput(attrs={"inputmode": "numeric", "placeholder": "e.g. 12", "autofocus": True}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        add_bootstrap_classes(self)
