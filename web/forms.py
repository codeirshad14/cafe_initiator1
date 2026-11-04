from django import forms

from core.forms import add_bootstrap_classes
from core.utils import clean_indian_mobile

from .models import DemoRequest


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
