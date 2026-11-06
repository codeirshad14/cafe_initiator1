from django import forms

from core.forms import add_bootstrap_classes
from core.utils import clean_indian_mobile

from .models import HIGHLIGHTS, CafeWebsite, DemoRequest, Feedback


class DemoRequestForm(forms.ModelForm):
    """The "Book a free demo" form on the website.

    `website` is a trap for spam robots: hidden from people, so a real visitor
    leaves it empty. When it is filled in, the view throws the request away.
    """

    website = forms.CharField(required=False, widget=forms.TextInput(attrs={
        "tabindex": "-1", "autocomplete": "off",
    }))

    class Meta:
        model = DemoRequest
        fields = ["name", "restaurant_name", "phone", "city", "tables", "message"]
        widgets = {
            "name": forms.TextInput(attrs={"autocomplete": "name", "placeholder": "Your name"}),
            "restaurant_name": forms.TextInput(attrs={"autocomplete": "organization", "placeholder": "e.g. Spice Garden"}),
            "phone": forms.TextInput(attrs={"inputmode": "tel", "autocomplete": "tel", "placeholder": "10-digit mobile"}),
            "city": forms.TextInput(attrs={"autocomplete": "address-level2", "placeholder": "e.g. Pune"}),
            "tables": forms.NumberInput(attrs={"min": "1", "inputmode": "numeric", "placeholder": "e.g. 12"}),
            "message": forms.Textarea(attrs={"rows": 3, "placeholder": "Anything we should know? (optional)"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        add_bootstrap_classes(self)

    def clean_phone(self):
        phone = clean_indian_mobile(self.cleaned_data["phone"])
        if not phone:
            raise forms.ValidationError("Please enter your mobile number so we can call you.")
        return phone


class CafeWebsiteForm(forms.ModelForm):
    """Cafe profile > Website: what the cafe's own page says (the name, address, phone,
    logo, menu and locations come from the rest of the profile)."""

    highlight_choices = forms.MultipleChoiceField(
        label="Highlights", required=False, widget=forms.CheckboxSelectMultiple,
        choices=[(key, label) for key, label, _ in HIGHLIGHTS],
        help_text="Shown as a strip under the top of your page.",
    )
    remove_cover = forms.BooleanField(required=False, label="Remove the cover photo")

    class Meta:
        model = CafeWebsite
        fields = ["is_on", "tagline", "about", "cover", "opening_hours", "whatsapp", "instagram", "facebook"]
        widgets = {
            "tagline": forms.TextInput(attrs={"placeholder": "e.g. Wood-fired pizzas and the best cold coffee in town"}),
            "about": forms.Textarea(attrs={"rows": 5, "placeholder": "Since 2015 we have been serving…"}),
            "cover": forms.FileInput(attrs={"accept": "image/*"}),
            "opening_hours": forms.Textarea(attrs={"rows": 3, "placeholder": "Mon – Fri: 11 am – 11 pm\nSat – Sun: 9 am – midnight"}),
            "whatsapp": forms.TextInput(attrs={"inputmode": "tel", "placeholder": "10-digit mobile"}),
            "instagram": forms.URLInput(attrs={"placeholder": "https://instagram.com/yourcafe"}),
            "facebook": forms.URLInput(attrs={"placeholder": "https://facebook.com/yourcafe"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial.setdefault("highlight_choices", self.instance.highlight_keys())
        if not self.instance.cover:
            del self.fields["remove_cover"]
        add_bootstrap_classes(self)

    def clean_whatsapp(self):
        return clean_indian_mobile(self.cleaned_data["whatsapp"])

    def save(self, commit=True):
        website = super().save(commit=False)
        website.highlights = ",".join(self.cleaned_data["highlight_choices"])
        if self.cleaned_data.get("remove_cover") and not self.files.get("cover"):
            website.cover.delete(save=False)
            website.cover = ""
        if commit:
            website.save()
        return website


class FeedbackForm(forms.ModelForm):
    """The feedback form on a cafe's website: stars, a message, a name, the mobile if they like.
    `website` is the same robot trap as on the demo form."""

    rating = forms.TypedChoiceField(coerce=int, choices=[(n, f"{n} star{'s' if n > 1 else ''}") for n in range(5, 0, -1)],
                                    widget=forms.RadioSelect, error_messages={"required": "Please pick the stars."})
    website = forms.CharField(required=False, widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off"}))

    class Meta:
        model = Feedback
        fields = ["rating", "message", "name", "phone"]
        labels = {"phone": "Mobile number (optional)"}
        widgets = {
            "message": forms.Textarea(attrs={"rows": 3, "placeholder": "What did you like? What can we do better?"}),
            "name": forms.TextInput(attrs={"autocomplete": "name", "placeholder": "Your name"}),
            "phone": forms.TextInput(attrs={"inputmode": "tel", "autocomplete": "tel", "placeholder": "If you want a call back"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        add_bootstrap_classes(self)

    def clean_phone(self):
        return clean_indian_mobile(self.cleaned_data["phone"])
