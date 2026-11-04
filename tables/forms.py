from datetime import datetime, timedelta

from django import forms
from django.utils import timezone

from core.forms import add_bootstrap_classes
from core.utils import clean_indian_mobile

from .models import DEFAULT_BOOKING_LENGTH, Booking, DiningTable, length_text, overlapping

BOOK_DAYS_AHEAD = 30                  # how far ahead a table can be booked
MAX_BOOKING_LENGTH = timedelta(days=7)  # the longest booking (a wedding: two or three days)
# how long a guest can book on the public menu (longer, e.g. a whole day: they call)
GUEST_LENGTHS = [(30, "30 minutes"), (60, "1 hour"), (90, "1½ hours"), (120, "2 hours"),
                 (180, "3 hours"), (240, "4 hours")]


class DiningTableForm(forms.ModelForm):
    """Add / edit a table. The QR token is made automatically and never typed."""

    class Meta:
        model = DiningTable
        fields = ["name", "section", "capacity", "is_active"]
        labels = {"name": "Table name", "capacity": "Seats", "is_active": "Table is in use"}
        help_texts = {
            "name": "Short and printed on the QR card, e.g. T1, T2, Garden 3.",
            "section": "Optional, e.g. AC Hall, Rooftop. Used to group tables.",
            "is_active": "Switched off: its QR code stops opening the menu.",
        }
        widgets = {
            "section": forms.TextInput(attrs={"list": "sectionOptions", "autocomplete": "off"}),
            "capacity": forms.NumberInput(attrs={"min": "1", "inputmode": "numeric"}),
        }

    def __init__(self, *args, location, **kwargs):
        super().__init__(*args, **kwargs)
        self.location = location  # names are unique per location: two outlets may both have a T1
        self.fields["name"].widget.attrs["placeholder"] = "e.g. T1"
        add_bootstrap_classes(self)

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        same_name = DiningTable.objects.filter(location=self.location, name__iexact=name).exclude(pk=self.instance.pk)
        if same_name.exists():
            raise forms.ValidationError("A table with this name already exists here.")
        return name

    def clean_section(self):
        return self.cleaned_data["section"].strip()


class BookingForm(forms.ModelForm):
    """A table booking: when, how many, who. The guest's form on the public menu.

    The date is today up to BOOK_DAYS_AHEAD days ahead; today's time must not
    have passed. A mobile number is needed (the restaurant calls to confirm).
    The same name or number may book more than once a day (lunch and dinner,
    or two families with one phone).
    """

    # the guest picks how long; the booking's "until" is worked out in save()
    length = forms.TypedChoiceField(
        label="How long?", choices=GUEST_LENGTHS, coerce=int, initial=120, required=False, empty_value=None,
        help_text="Longer, e.g. a whole day for a wedding? Please call us.",
    )

    class Meta:
        model = Booking
        fields = ["date", "time", "guests", "customer_name", "customer_phone", "note"]
        labels = {"customer_name": "Your name", "customer_phone": "Mobile number", "guests": "Guests",
                  "note": "Anything we should know?"}
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "time": forms.TimeInput(attrs={"type": "time", "step": 900}, format="%H:%M"),
            "guests": forms.NumberInput(attrs={"min": 1, "max": 50, "inputmode": "numeric"}),
            "customer_phone": forms.TextInput(attrs={"inputmode": "tel", "autocomplete": "tel", "placeholder": "10-digit mobile"}),
            "note": forms.TextInput(attrs={"placeholder": "Optional, e.g. birthday, a high chair, window seat"}),
        }

    def __init__(self, *args, restaurant, **kwargs):
        super().__init__(*args, **kwargs)
        self.restaurant = restaurant
        today = timezone.localdate()
        self.fields["date"].widget.attrs.update({"min": today.isoformat(),
                                                 "max": (today + timedelta(days=BOOK_DAYS_AHEAD)).isoformat()})
        self.fields["customer_name"].widget.attrs.update({"autocomplete": "name", "placeholder": "Your name"})
        self.fields["customer_name"].error_messages["required"] = "Please enter a name for the booking."
        self.fields["customer_phone"].error_messages["required"] = "Please enter your mobile number, so we can confirm the booking."
        self.fields["date"].error_messages["required"] = "Please choose a day."
        self.fields["time"].error_messages["required"] = "Please choose a time."
        add_bootstrap_classes(self)

    def clean_customer_name(self):
        return " ".join(self.cleaned_data["customer_name"].split())

    def clean_customer_phone(self):
        phone = clean_indian_mobile(self.cleaned_data["customer_phone"])
        if not phone:
            raise forms.ValidationError("Please enter your mobile number, so we can confirm the booking.")
        return phone

    def clean_guests(self):
        guests = self.cleaned_data["guests"]
        if guests > 50:
            raise forms.ValidationError("For more than 50 guests, please call us.")
        return guests

    def clean_note(self):
        return self.cleaned_data["note"].strip()

    def clean(self):
        cleaned = super().clean()
        day, time = cleaned.get("date"), cleaned.get("time")
        today = timezone.localdate()
        # an existing booking keeping its date and time (now maybe past) is fine
        unchanged = self.instance.pk and day == self.instance.date and time == self.instance.time
        if day and not unchanged:
            if day < today:
                self.add_error("date", "Please choose today or a later day.")
            elif day > today + timedelta(days=BOOK_DAYS_AHEAD):
                self.add_error("date", f"Bookings can be made up to {BOOK_DAYS_AHEAD} days ahead.")
            elif time and day == today and time < timezone.localtime().time():
                self.add_error("time", "This time has already passed today.")
        return cleaned

    def save(self, commit=True):
        """The guest's "How long?" (two hours if not picked) sets the booking's "until"."""
        booking = super().save(commit=False)
        if "length" in self.fields:  # the guest's form (staff set "until" themselves)
            minutes = self.cleaned_data.get("length") or 120
            ends = booking.starts_at + timedelta(minutes=minutes)
            booking.end_date, booking.end_time = ends.date(), ends.time()
        if commit:
            booking.save()
        return booking


class StaffBookingForm(BookingForm):
    """A booking added or changed by staff (a phone call): from a day and time
    until a day and time (30 minutes, or two days for a wedding), the guest's
    details, the table and the status. Two upcoming bookings cannot hold the same
    table at overlapping times. Staff may change the status (Seated, Cancelled,
    No-show) of any booking."""

    length = None  # staff set the "until" itself (the quick buttons fill it)

    class Meta(BookingForm.Meta):
        fields = ["date", "time", "end_date", "end_time", "guests", "customer_name", "customer_phone", "note",
                  "table", "status"]
        labels = {**BookingForm.Meta.labels, "date": "From (day)", "time": "From (time)",
                  "end_date": "Until (day)", "end_time": "Until (time)",
                  "customer_name": "Guest name", "customer_phone": "Guest mobile", "note": "Note", "table": "Table"}
        widgets = {
            **BookingForm.Meta.widgets,
            "end_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "end_time": forms.TimeInput(attrs={"type": "time", "step": 900}, format="%H:%M"),
        }

    def __init__(self, *args, restaurant, location, **kwargs):
        super().__init__(*args, restaurant=restaurant, **kwargs)
        self.location = location  # the tables to choose from: this location's
        self.fields["table"].queryset = DiningTable.objects.filter(location=location, is_active=True, is_takeaway=False)
        self.fields["table"].empty_label = "Choose later"
        self.fields["table"].required = False
        self.fields["end_date"].required = False
        self.fields["end_time"].required = False
        if not self.instance.pk:
            self.fields["status"].initial = Booking.Status.CONFIRMED  # staff took it on the phone
        self.fields["customer_name"].widget.attrs["placeholder"] = "Guest name"
        self.fields["note"].widget.attrs["placeholder"] = "Optional"

    def clean(self):
        cleaned = super().clean()
        day, time = cleaned.get("date"), cleaned.get("time")
        if not (day and time):
            return cleaned

        # until: empty -> the usual two hours; a time without a day -> the same day
        starts = datetime.combine(day, time)
        end_day, end_time = cleaned.get("end_date"), cleaned.get("end_time")
        if end_time is None:
            ends = starts + DEFAULT_BOOKING_LENGTH
        else:
            ends = datetime.combine(end_day or day, end_time)
        if ends <= starts:
            self.add_error("end_time", "The booking has to end after it starts.")
            return cleaned
        if ends - starts > MAX_BOOKING_LENGTH:
            self.add_error("end_date", f"A booking can last up to {length_text(MAX_BOOKING_LENGTH)}.")
            return cleaned
        cleaned["end_date"], cleaned["end_time"] = ends.date(), ends.time()

        # the table: not booked by someone else at an overlapping time
        table = cleaned.get("table")
        if table and cleaned.get("status") in Booking.UPCOMING:
            others = Booking.objects.filter(location=self.location, table=table,
                                            status__in=Booking.UPCOMING).exclude(pk=self.instance.pk)
            clash = overlapping(others, starts, ends)
            if clash:
                other = clash[0]
                self.add_error("table", f"{table.label} is booked {other.starts_at:%d %b, %I:%M %p} – "
                                        f"{other.ends_at:%d %b, %I:%M %p} by {other.customer_name}. "
                                        f"Choose another table or time.")
        return cleaned
