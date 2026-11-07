import logging
import re
from decimal import Decimal

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.validators import RegexValidator

from .models import MAX_SLIDE_MB, Location, Restaurant, Staff

GSTIN_CHECK = RegexValidator(
    r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$",
    "Enter a valid 15-character GSTIN, e.g. 27ABCDE1234F1Z5.",
)
FSSAI_CHECK = RegexValidator(r"^[0-9]{14}$", "The FSSAI licence number is 14 digits.")
MAX_LOGO_MB = 1
# password guessing: after this many wrong passwords for one email, its logins wait this long
LOGIN_TRIES, LOGIN_WAIT_MINUTES = 5, 15
logger = logging.getLogger(__name__)


def count_wrong_password(tries_key):
    try:
        cache.incr(tries_key)
    except ValueError:  # the first wrong one (or the wait just ended)
        cache.set(tries_key, 1, LOGIN_WAIT_MINUTES * 60)


def tries_counted(action, *args):
    """Run one step of the wrong-password count; 0 (and a line in the log) when the cache fails."""
    try:
        return action(*args)
    except Exception:  # e.g. PermissionError on the cache folder: never an error 500 at login
        logger.exception("The login cache could not be used (CACHE_DIR). Logins go on without the count.")
        return 0


def add_bootstrap_classes(form):
    """Give every field of a form the right Bootstrap 5 class."""
    for field in form.fields.values():
        widget = field.widget
        if isinstance(widget, (forms.RadioSelect, forms.HiddenInput)):
            continue  # radio choices are drawn by their template; hidden needs no look
        if isinstance(widget, forms.CheckboxInput):
            css = "form-check-input"
        elif isinstance(widget, forms.Select):
            css = "form-select"
        else:
            css = "form-control"
        widget.attrs["class"] = (widget.attrs.get("class", "") + " " + css).strip()


class StaffLoginForm(AuthenticationForm):
    """The /login/ form: email, password and "Sign in as restaurant admin".

    The tick box must match the login: ticked for the restaurant admin,
    empty for every other role. So each person says who they are, and a wrong
    choice is told plainly instead of logging in anyway.
    Also refuses logins that are switched off or whose membership has ended,
    and stops password guessing: 5 wrong passwords for an email, then 15 minutes' wait.
    """

    username = forms.CharField(
        label="Email", max_length=254,
        widget=forms.TextInput(attrs={
            "autofocus": True, "autocomplete": "username", "inputmode": "email", "placeholder": "you@restaurant.com",
        }),
    )
    as_admin = forms.BooleanField(label="Sign in as restaurant admin", required=False)

    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "Email and password did not match. Please try again.",
        "no_restaurant": "This login is not linked to any restaurant.",
        "developer": "This is the developer's login: it signs in at /admin/ only. Restaurant staff sign in "
                     "here with their own email.",
        "staff_off": "Your login has been switched off. Please ask your restaurant admin.",
        "restaurant_off": "This restaurant has been switched off. Please contact us.",
        "membership_ended": "Your restaurant's membership ended on %(ended)s. Please contact us to renew it.",
        "not_admin": "This is a staff login. Untick “Sign in as restaurant admin”.",
        "is_admin": "This is the restaurant admin's login. Tick “Sign in as restaurant admin”.",
        "too_many_tries": f"Too many wrong passwords. Please wait {LOGIN_WAIT_MINUTES} minutes and try again, "
                          "or ask your restaurant admin to reset it.",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        add_bootstrap_classes(self)

    def clean(self):
        """Count wrong passwords per email (Django's cache); a good login clears the count.
        The count must never stop a login: when the cache cannot be used (its folder
        missing or not writable on the server), logins go on without it and the log says so."""
        tries_key = "login-tries:" + (self.data.get("username") or "").strip().lower()
        if tries_counted(cache.get, tries_key, 0) >= LOGIN_TRIES:
            raise forms.ValidationError(self.error_messages["too_many_tries"], code="too_many_tries")
        try:
            cleaned = super().clean()
        except forms.ValidationError as error:
            if error.code == "invalid_login":
                tries_counted(count_wrong_password, tries_key)
            raise
        tries_counted(cache.delete, tries_key)
        return cleaned

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)  # a switched-off User stops here
        staff = getattr(user, "staff", None)

        if staff is None:
            if user.is_superuser:  # the developer: /admin/ only (it has a login of its own: core/middleware.py)
                raise forms.ValidationError(self.error_messages["developer"], code="developer")
            raise forms.ValidationError(self.error_messages["no_restaurant"], code="no_restaurant")

        restaurant = staff.restaurant
        if not staff.is_active:
            raise forms.ValidationError(self.error_messages["staff_off"], code="staff_off")
        if not restaurant.is_active:
            raise forms.ValidationError(self.error_messages["restaurant_off"], code="restaurant_off")
        if not restaurant.membership_active:
            ended = restaurant.membership_end.strftime("%d %b %Y")
            raise forms.ValidationError(
                self.error_messages["membership_ended"] % {"ended": ended}, code="membership_ended",
            )

        is_admin = staff.role == Staff.Role.ADMIN
        as_admin = self.cleaned_data.get("as_admin")
        if as_admin and not is_admin:
            raise forms.ValidationError(self.error_messages["not_admin"], code="not_admin")
        if is_admin and not as_admin:
            raise forms.ValidationError(self.error_messages["is_admin"], code="is_admin")


class RestaurantForm(forms.ModelForm):
    """The restaurant admin's own profile: printed on bills and shown on the public menu.

    The membership (plan, dates, logins allowed) and the web address (slug) are
    not here: only the platform owner changes those, in the Django admin.
    """

    remove_logo = forms.BooleanField(required=False, label="Remove the current logo")
    remove_slide_1 = forms.BooleanField(required=False, label="Remove this photo")
    remove_slide_2 = forms.BooleanField(required=False, label="Remove this photo")
    remove_slide_3 = forms.BooleanField(required=False, label="Remove this photo")

    class Meta:
        model = Restaurant
        fields = [
            "name", "address", "phone", "email", "gstin", "gst_percent", "fssai_no", "logo",
            "slide_1", "slide_1_text", "slide_2", "slide_2_text", "slide_3", "slide_3_text",
            "delivery_enabled", "delivery_charge", "free_delivery_above", "booking_enabled",
        ]
        labels = {"name": "Restaurant name", "gst_percent": "GST %", "fssai_no": "FSSAI licence no.",
                  "delivery_enabled": "Take home-delivery orders", "delivery_charge": "Delivery charge (₹)",
                  "free_delivery_above": "Free delivery from (₹)", "booking_enabled": "Take table bookings"}
        help_texts = {
            "delivery_enabled": "The public menu offers Delivery (you call to confirm each order). "
                                "Staff can take deliveries on a call either way.",
            "booking_enabled": "Guests can ask for a table on your booking page (/r/<your-slug>/book/). "
                               "You call to confirm each booking.",
            "gst_percent": "Usually 5% for restaurants. Split half CGST, half SGST on every bill.",
            "gstin": "Printed on bills. Leave empty if you are not GST registered.",
            "logo": f"PNG or JPG, up to {MAX_LOGO_MB} MB. Shown on the menu, QR cards and bills.",
        }
        widgets = {
            "address": forms.Textarea(attrs={"rows": 3}),
            "gst_percent": forms.NumberInput(attrs={"step": "0.01", "min": "0", "max": "28"}),
            "logo": forms.FileInput(attrs={"accept": "image/*"}),
            "slide_1": forms.FileInput(attrs={"accept": "image/*"}),
            "slide_2": forms.FileInput(attrs={"accept": "image/*"}),
            "slide_3": forms.FileInput(attrs={"accept": "image/*"}),
            "delivery_charge": forms.NumberInput(attrs={"step": "1", "min": "0", "inputmode": "decimal"}),
            "free_delivery_above": forms.NumberInput(attrs={"step": "1", "min": "0", "inputmode": "decimal"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field, _ in Restaurant.PROFILE_NEEDS:  # printed on every bill: the profile is not done without them
            self.fields[field].required = True
        if not self.instance.logo:
            del self.fields["remove_logo"]
        for n in Restaurant.SLIDE_SLOTS:
            self.fields[f"slide_{n}"].label = "Photo"
            self.fields[f"slide_{n}"].help_text = f"Wide photo (about 2:1), JPG or PNG, up to {MAX_SLIDE_MB} MB."
            self.fields[f"slide_{n}_text"].widget.attrs["placeholder"] = "Optional, e.g. 20% off on weekdays"
            if not getattr(self.instance, f"slide_{n}"):
                del self.fields[f"remove_slide_{n}"]
        add_bootstrap_classes(self)
        self.fields["gstin"].widget.attrs["style"] = "text-transform: uppercase"

    def slide_slots(self):
        """For the template: each slider slot's photo field, caption, remove box and current photo."""
        return [
            {
                "number": n + 1,  # slide 1 on the menu is the restaurant itself
                "photo": self[f"slide_{n}"],
                "text": self[f"slide_{n}_text"],
                "remove": self[f"remove_slide_{n}"] if f"remove_slide_{n}" in self.fields else None,
                "current": getattr(self.instance, f"slide_{n}"),
            }
            for n in Restaurant.SLIDE_SLOTS
        ]

    def clean_gstin(self):
        gstin = self.cleaned_data["gstin"].strip().upper()  # typed in small letters is fine
        if gstin:
            GSTIN_CHECK(gstin)
        return gstin

    def clean_fssai_no(self):
        fssai = self.cleaned_data["fssai_no"].replace(" ", "")
        if fssai:
            FSSAI_CHECK(fssai)
        return fssai

    def clean_gst_percent(self):
        value = self.cleaned_data["gst_percent"]
        if value < 0 or value > Decimal("28"):
            raise forms.ValidationError("GST must be between 0% and 28%.")
        return value

    def clean_logo(self):
        logo = self.cleaned_data.get("logo")
        upload = self.files.get("logo")  # only a newly chosen file
        if upload and upload.size > MAX_LOGO_MB * 1024 * 1024:
            raise forms.ValidationError(f"The logo is too big. Please use one under {MAX_LOGO_MB} MB.")
        return logo

    def save(self, commit=True):
        restaurant = super().save(commit=False)
        if self.cleaned_data.get("remove_logo") and not self.files.get("logo"):
            restaurant.logo.delete(save=False)
            restaurant.logo = ""
        for n in Restaurant.SLIDE_SLOTS:
            if self.cleaned_data.get(f"remove_slide_{n}") and not self.files.get(f"slide_{n}"):
                getattr(restaurant, f"slide_{n}").delete(save=False)
                setattr(restaurant, f"slide_{n}", "")
                setattr(restaurant, f"slide_{n}_text", "")
        if commit:
            restaurant.save()
        return restaurant


class BillSettingsForm(forms.ModelForm):
    """Cafe profile > Bill & print: what every printed bill shows. Set once, used for all bills."""

    remove_upi_qr = forms.BooleanField(required=False, label="Remove the current QR code")

    class Meta:
        model = Restaurant
        fields = ["print_name", "invoice_title", "print_logo", "print_tax_details", "upi_id", "upi_qr", "print_upi"]
        widgets = {
            "print_name": forms.TextInput(attrs={"placeholder": "e.g. Spice Garden Foods Pvt Ltd"}),
            "invoice_title": forms.TextInput(attrs={"list": "invoiceTitles", "autocomplete": "off"}),
            "upi_id": forms.TextInput(attrs={"autocomplete": "off", "inputmode": "email"}),
            "upi_qr": forms.FileInput(attrs={"accept": "image/*"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.upi_qr:
            del self.fields["remove_upi_qr"]
        add_bootstrap_classes(self)

    def clean_print_name(self):
        return " ".join(self.cleaned_data["print_name"].split())

    def clean_invoice_title(self):
        return " ".join(self.cleaned_data["invoice_title"].split()).upper() or "TAX INVOICE"

    def clean_upi_id(self):
        upi_id = self.cleaned_data["upi_id"].strip().lower()
        if upi_id and not re.fullmatch(r"[a-z0-9.\-_]{2,}@[a-z]{2,}", upi_id):
            raise forms.ValidationError("A UPI ID looks like name@bank, e.g. spicegarden@okicici.")
        return upi_id

    def save(self, commit=True):
        restaurant = super().save(commit=False)
        if self.cleaned_data.get("remove_upi_qr") and not self.files.get("upi_qr"):
            restaurant.upi_qr.delete(save=False)
            restaurant.upi_qr = ""
        if commit:
            restaurant.save()
        return restaurant


class LocationForm(forms.ModelForm):
    """Cafe profile > Locations: add or change an outlet."""

    class Meta:
        model = Location
        fields = ["name", "address", "phone", "is_active"]
        labels = {"is_active": "Open (staff work here, its QR codes take orders)"}
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "e.g. MG Road, Koregaon Park"}),
            "address": forms.Textarea(attrs={"rows": 2}),
            "phone": forms.TextInput(attrs={"inputmode": "tel"}),
        }

    def __init__(self, *args, restaurant, **kwargs):
        super().__init__(*args, **kwargs)
        self.restaurant = restaurant
        add_bootstrap_classes(self)

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        same = Location.objects.filter(restaurant=self.restaurant, name__iexact=name).exclude(pk=self.instance.pk)
        if same.exists():
            raise forms.ValidationError("Another location already has this name.")
        return name

    def clean_is_active(self):
        is_open = self.cleaned_data["is_active"]
        if not is_open and self.instance.pk and self.instance.is_main:
            raise forms.ValidationError("The main location stays open.")
        # a new open location, or a closed one opened again: within the plan's number (core/plans.py)
        opening = is_open and not (self.instance.pk and self.instance.is_active)
        if opening and not self.restaurant.can_open_location():
            raise forms.ValidationError(self.restaurant.location_limit_message())
        return is_open


class StaffForm(forms.ModelForm):
    """Create or edit a staff member together with their login (email + password).

    Refused when the restaurant's "logins allowed" (max_users) are all in use:
    for a new active login, and for switching an inactive one back on.
    """

    email = forms.EmailField(max_length=150, label="Email (logs in with this)")
    password = forms.CharField(
        required=False, strip=False,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
    )

    class Meta:
        model = Staff
        fields = ["name", "phone", "role", "locations", "is_active"]
        labels = {"is_active": "Login is active (can log in)", "locations": "Works at"}
        widgets = {"locations": forms.CheckboxSelectMultiple}

    def __init__(self, *args, restaurant, editing_self=False, editor_role="ADMIN", **kwargs):
        super().__init__(*args, **kwargs)
        self.restaurant = restaurant
        self.was_active = bool(self.instance.pk and self.instance.is_active)

        # only the admin makes (or changes) an admin login
        if editor_role != Staff.Role.ADMIN:
            self.fields["role"].choices = [c for c in self.fields["role"].choices if c[0] != Staff.Role.ADMIN]

        # where they work: shown once the company has more than one location
        places = restaurant.locations.filter(is_active=True)
        if places.count() > 1:
            self.fields["locations"].queryset = places
            self.fields["locations"].help_text = ("Admin and manager work at every location. A restaurant manager "
                                                  "runs one; others may work at several. None ticked: the main one.")
        else:
            del self.fields["locations"]

        if self.instance.pk:
            self.fields["email"].initial = self.instance.user.email
            self.fields["password"].help_text = "Leave empty to keep the current password."
        else:
            self.fields["password"].required = True
            self.fields["password"].help_text = "At least 8 characters, not only numbers."

        # an admin cannot lock themselves out
        if editing_self:
            self.fields["role"].disabled = True
            self.fields["is_active"].disabled = True
            self.fields["role"].help_text = "You cannot change your own role."

        self.fields["email"].widget.attrs.update({"autocomplete": "off", "inputmode": "email"})
        add_bootstrap_classes(self)

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        users = User.objects.filter(email__iexact=email) | User.objects.filter(username__iexact=email)
        if self.instance.pk:
            users = users.exclude(pk=self.instance.user_id)
        if users.exists():
            raise forms.ValidationError("Another login already uses this email.")
        return email

    def clean_password(self):
        password = self.cleaned_data.get("password")
        if password:
            validate_password(password)
        return password

    def clean(self):
        cleaned = super().clean()
        # a login that will be active and was not active before needs a free place
        turning_on = cleaned.get("is_active") and not self.was_active
        if turning_on and not self.restaurant.can_add_user:
            raise forms.ValidationError(self.restaurant.user_limit_message())
        # a restaurant manager runs one location
        if "locations" in self.fields and cleaned.get("role") == Staff.Role.RM and len(cleaned.get("locations") or []) != 1:
            self.add_error("locations", "Tick the one location this restaurant manager runs.")
        return cleaned

    def save_with_user(self):
        """Save the login User and the Staff row. Call inside transaction.atomic()."""
        staff = self.save(commit=False)
        user = staff.user if staff.pk else User()
        user.email = self.cleaned_data["email"]
        user.username = self.cleaned_data["email"]  # the email is the login ID
        user.first_name = staff.name[:150]
        user.is_active = staff.is_active
        if self.cleaned_data["password"]:
            user.set_password(self.cleaned_data["password"])
        user.save()

        staff.user = user
        staff.restaurant = self.restaurant
        staff.save()
        self.save_m2m()  # the locations
        return staff
