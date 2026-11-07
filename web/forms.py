from django import forms

from core.forms import add_bootstrap_classes
from core.utils import clean_indian_mobile

from .models import ASPECTS, HIGHLIGHTS, CafeWebsite, DemoRequest, Feedback


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
        fields = ["is_on", "tagline", "about", "cover", "opening_hours", "whatsapp", "instagram", "facebook",
                  "show_ratings"]
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


STAR_CHOICES = [(n, f"{n} star{'s' if n > 1 else ''}") for n in range(5, 0, -1)]  # 5 … 1: drawn right to left


def star_field(label):
    return forms.TypedChoiceField(label=label, coerce=int, choices=STAR_CHOICES, widget=forms.RadioSelect,
                                  error_messages={"required": f"Please pick the stars for {label.lower()}."})


class StarQuestions(forms.Form):
    """The three questions, 1 to 5 stars each: Food, Staff, Cafe (web.models.ASPECTS)."""

    food_rating = star_field("Food")
    staff_rating = star_field("Staff")
    cafe_rating = star_field("Cafe")

    def star_questions(self):
        """The three fields with their icons, for the template's star pickers."""
        return [(self[field], icon) for field, _, icon in ASPECTS]


class OrderFeedbackForm(StarQuestions):
    """"Rate your visit" from the bill's link: the three questions, stars only."""


class FeedbackForm(StarQuestions, forms.ModelForm):
    """The feedback form on a cafe's website: the three questions, a message if they like,
    a name, the mobile if they want a call back. `website` is the same robot trap as on the demo form."""

    website = forms.CharField(required=False, widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off"}))

    class Meta:
        model = Feedback
        fields = ["food_rating", "staff_rating", "cafe_rating", "message", "name", "phone"]
        labels = {"message": "Your feedback (optional)", "phone": "Mobile number (optional)"}
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

    def save(self, commit=True):
        feedback = super().save(commit=False)
        feedback.set_overall()
        if commit:
            feedback.save()
        return feedback
