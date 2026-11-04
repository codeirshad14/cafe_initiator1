from django import forms
from django.contrib import admin, messages
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.db.models import Count, Q
from django.utils.html import format_html

from .models import Location, Restaurant, Staff
from .templatetags.money import indian_grouping


class UserChoiceField(forms.ModelChoiceField):
    """The users dropdown: shows "email — name" instead of the username."""

    def label_from_instance(self, user):
        label = user.email or user.username
        if user.get_full_name():
            label += f" — {user.get_full_name()}"
        if user.is_superuser:
            label += " (superuser)"
        if not user.is_active:
            label += " (switched off)"
        return label


class StaffAdminForm(forms.ModelForm):
    """A staff row in the Django admin: pick an existing login from the list,
    or type an email and password to make a new login right here.

    The list only offers logins that are not staff of any restaurant yet
    (plus this row's own login), since one login belongs to one restaurant.
    """

    login = UserChoiceField(
        queryset=User.objects.none(), required=False, label="Login (user)",
        help_text="Pick an existing login, or leave empty and fill in the new email + password.",
    )
    new_email = forms.EmailField(required=False, label="or new login: email",
                                 widget=forms.EmailInput(attrs={"autocomplete": "off"}))
    new_password = forms.CharField(
        required=False, label="password", strip=False,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
    )

    class Meta:
        model = Staff
        fields = ["name", "phone", "role", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        free_logins = Q(staff__isnull=True)
        if self.instance.pk:
            free_logins |= Q(pk=self.instance.user_id)
            self.fields["login"].initial = self.instance.user_id
        self.fields["login"].queryset = User.objects.filter(free_logins).order_by("email", "username")

    def clean(self):
        cleaned = super().clean()
        login = cleaned.get("login")
        email = (cleaned.get("new_email") or "").strip().lower()
        password = cleaned.get("new_password")

        if login and email:
            raise forms.ValidationError("Pick an existing login OR type a new email, not both.")
        if not login and not email:
            raise forms.ValidationError("Pick a login from the list, or type a new email and password.")
        if email:
            restaurant_email = (self.data.get("email") or "").strip().lower()  # the Restaurant tab, same page
            if self.prefix and email == restaurant_email:
                self.add_error("new_email", "This is the restaurant admin's login (the email on the Restaurant tab). "
                                            "Use another email for this staff login.")
            elif User.objects.filter(Q(email__iexact=email) | Q(username__iexact=email)).exists():
                self.add_error("new_email", "A login with this email already exists. Pick it from the list instead.")
            if not password:
                self.add_error("new_password", "Give the new login a password.")
            else:
                try:
                    validate_password(password)
                except forms.ValidationError as error:
                    self.add_error("new_password", error)
        cleaned["new_email"] = email
        return cleaned

    def save(self, commit=True):
        staff = super().save(commit=False)
        email = self.cleaned_data.get("new_email")
        if email:
            # the email is the login ID (core/auth.py)
            staff.user = User.objects.create_user(
                username=email, email=email, password=self.cleaned_data["new_password"],
                first_name=staff.name[:150],
            )
        else:
            staff.user = self.cleaned_data["login"]
        if commit:
            staff.save()
        return staff


def login_taken(email, but_not=None):
    """Another login already has this email (as its email or its username)."""
    logins = User.objects.filter(Q(email__iexact=email) | Q(username__iexact=email))
    if but_not is not None:
        logins = logins.exclude(pk=but_not.pk)
    return logins.exists()


class RestaurantAdminForm(forms.ModelForm):
    """The Restaurant form in the Django admin, with the restaurant admin's login in it.

    The restaurant's email IS its admin's login: a new restaurant gets that login
    (role Admin) with the password typed here, so the restaurant can log in at once.
    Later the password box sets a new password, and a new email moves the login along.
    A restaurant without an admin login yet (made before) gets one when a password is typed.
    The other logins are the Staff tab's.
    """

    admin_password = forms.CharField(
        required=False, label="Admin login password", strip=False,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password", "class": "vTextField"}),
    )

    class Meta:
        model = Restaurant
        fields = "__all__"
        # vTextField: the admin's own look for text boxes; autocomplete off: the browser must not
        # fill in the developer's own saved login here
        widgets = {"email": forms.EmailInput(attrs={"autocomplete": "off", "class": "vTextField"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.admin_staff = self.instance.admin_login() if self.instance.pk else None
        self.fields["email"].label = "Email (the restaurant admin's login)"
        if self.admin_staff:
            self.fields["email"].help_text = (
                f"The restaurant admin logs in with this email (now {self.admin_staff.user.email}). "
                "Change it here to change the login.")
            self.fields["admin_password"].help_text = "Leave empty to keep the password. Type a new one to reset it."
        elif self.instance.pk:
            self.fields["email"].help_text = "No restaurant admin login yet: type a password below to make one with this email."
            self.fields["admin_password"].help_text = "Makes the restaurant admin login with the email above."
        else:
            self.fields["email"].required = True
            self.fields["email"].help_text = "The restaurant admin logs in with this email (and ticks “Sign in as restaurant admin”)."
            self.fields["admin_password"].required = True
            self.fields["admin_password"].help_text = "The restaurant admin's password. Other logins: the Staff tab."

    def moves_login(self, email):
        """The admin login gets this email: a new login is made, or the email was changed here
        (not when the cafe changed its own email in Cafe profile and this form is only saved)."""
        if self.admin_staff is None:
            return bool(self.cleaned_data.get("admin_password"))
        return "email" in self.changed_data and email != self.admin_staff.user.email.lower()

    def clean(self):
        cleaned = super().clean()
        email = (cleaned.get("email") or "").strip().lower()
        password = cleaned.get("admin_password")
        if "email" in cleaned:
            cleaned["email"] = email
        if password and not email:
            self.add_error("email", "Type the email the restaurant admin logs in with.")
        elif self.admin_staff and "email" in self.changed_data and not email:
            self.add_error("email", "The email is the restaurant admin's login, so it cannot be empty.")
        elif email and self.moves_login(email) and login_taken(email, but_not=self.admin_staff and self.admin_staff.user):
            self.add_error("email", "Another login already has this email. Use another email for the restaurant admin.")
        if password:
            try:
                validate_password(password)
            except forms.ValidationError as error:
                self.add_error("admin_password", error)
        return cleaned

    def save_admin_login(self, restaurant):
        """After the restaurant is saved: make its admin login, or bring its email and password up to date."""
        email, password = self.cleaned_data.get("email"), self.cleaned_data.get("admin_password")
        if self.admin_staff is None:
            if password:
                user = User.objects.create_user(username=email, email=email, password=password,
                                                first_name=restaurant.name[:150])
                Staff.objects.create(user=user, restaurant=restaurant, name=restaurant.name, role=Staff.Role.ADMIN)
            return
        user = self.admin_staff.user
        if self.moves_login(email):
            user.email = user.username = email
        if password:
            user.set_password(password)
        user.save()


class StaffInline(admin.TabularInline):
    """The restaurant's logins, right in the Restaurant form."""

    model = Staff
    form = StaffAdminForm
    extra = 1
    fields = ["login", "new_email", "new_password", "name", "phone", "role", "is_active"]


class LocationInline(admin.TabularInline):
    """The restaurant's outlets, in the Restaurant form (the cafe adds its own in Cafe profile > Locations)."""

    model = Location
    extra = 0
    fields = ["name", "address", "phone", "is_active"]


@admin.register(Restaurant)
class RestaurantAdmin(admin.ModelAdmin):
    """The membership is set and renewed here only; the restaurant's own screens never edit it.
    The email and password on the Restaurant tab are the restaurant admin's login (RestaurantAdminForm).

    "Membership type" (Only Menu ... Ultimate: core/plans.py) and "Logins allowed" can
    be changed right in the list. Lowering them never switches anything off: "Active
    logins", "Bills this year" and "Open locations" just show what is over, in red.
    """

    form = RestaurantAdminForm
    list_display = [
        "name", "tier", "plan", "membership_end", "membership_ok", "max_users", "logins_in_use",
        "bills_this_year", "open_locations", "is_active", "created_at",
    ]
    list_editable = ["tier", "max_users"]
    list_filter = ["tier", "plan", "is_active"]
    search_fields = ["name", "slug", "phone", "gstin"]
    date_hierarchy = "membership_end"
    prepopulated_fields = {"slug": ["name"]}
    fieldsets = [
        ("Restaurant", {"fields": ["name", "slug", "email", "admin_password", "address", "phone", "gstin", "gst_percent",
                                   "fssai_no", "logo"]}),
        ("Delivery & bookings", {
            "fields": ["delivery_enabled", ("delivery_charge", "free_delivery_above"), "booking_enabled"],
        }),
        ("Public menu slider", {
            "fields": [("slide_1", "slide_1_text"), ("slide_2", "slide_2_text"), ("slide_3", "slide_3_text")],
            "description": "Slide 1 on the public menu is the restaurant itself (name, address, logo). "
                           "These photos come after it and slide by themselves. Wide photos (about 2:1), up to 2 MB.",
        }),
        ("Membership", {"fields": ["tier", "plan", "membership_start", "membership_end", "max_users", "is_active"]}),
    ]
    inlines = [LocationInline, StaffInline]
    actions = ["renew_membership"]

    def get_queryset(self, request):
        # count each restaurant's active logins in the same query
        return super().get_queryset(request).annotate(
            active_logins=Count(
                "staff_members",
                filter=Q(staff_members__is_active=True, staff_members__user__is_active=True),
            ),
        )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        form.save_admin_login(obj)  # the email on the Restaurant tab is the restaurant admin's login

    @admin.display(boolean=True, description="Membership active")
    def membership_ok(self, obj):
        return obj.membership_active

    @admin.display(description="Active logins", ordering="active_logins")
    def logins_in_use(self, obj):
        """'3 / 5', in red when over the allowance."""
        text = f"{obj.active_logins} / {obj.max_users}"
        if obj.active_logins > obj.max_users:
            return format_html('<strong style="color:#c62828">{} (over)</strong>', text)
        return text

    @admin.display(description="Bills this year")
    def bills_this_year(self, obj):
        """'9,120 / 10,000' in this membership year; red once the plan's bills are used."""
        usage = obj.plan_usage
        if usage["limit"] is None:
            return indian_grouping(str(usage["bills"]))
        text = f"{indian_grouping(str(usage['bills']))} / {indian_grouping(str(usage['limit']))}"
        if usage["full"]:
            return format_html('<strong style="color:#c62828">{} (used up)</strong>', text)
        return text

    @admin.display(description="Open locations")
    def open_locations(self, obj):
        """'1 / 1'; red when more are open than the plan has (e.g. after a downgrade)."""
        count = obj.locations.filter(is_active=True).count()
        if obj.location_limit is None:
            return str(count)
        text = f"{count} / {obj.location_limit}"
        if count > obj.location_limit:
            return format_html('<strong style="color:#c62828">{} (over)</strong>', text)
        return text

    @admin.action(description="Renew membership (one more plan period)")
    def renew_membership(self, request, queryset):
        for restaurant in queryset:
            restaurant.renew_membership()
            restaurant.save(update_fields=["membership_start", "membership_end"])
        self.message_user(request, f"Renewed {queryset.count()} membership(s).", messages.SUCCESS)


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ["name", "restaurant", "phone", "is_active", "created_at"]
    list_filter = ["restaurant", "is_active"]
    search_fields = ["name", "address", "phone", "restaurant__name"]
    list_select_related = ["restaurant"]


@admin.register(Staff)
class StaffAdmin(admin.ModelAdmin):
    form = StaffAdminForm
    fields = ["restaurant", "login", "new_email", "new_password", "name", "phone", "role", "is_active"]
    list_display = ["name", "login_email", "restaurant", "role", "is_active"]
    list_filter = ["restaurant", "role", "is_active"]
    search_fields = ["name", "user__username", "user__email", "phone"]
    list_select_related = ["user", "restaurant"]

    @admin.display(description="Login", ordering="user__email")
    def login_email(self, obj):
        return obj.user.email or obj.user.username
