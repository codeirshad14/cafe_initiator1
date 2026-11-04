from decimal import Decimal

from django import forms

from core.forms import add_bootstrap_classes

from .models import MAX_IMAGE_MB, Category, MenuItem, MenuItemPortion


class CategoryForm(forms.ModelForm):
    """Add / edit a menu category."""

    class Meta:
        model = Category
        fields = ["name", "sort_order", "is_active"]
        labels = {"is_active": "Show on the menu"}
        help_texts = {"sort_order": "Smaller numbers come first on the menu."}

    def __init__(self, *args, restaurant, **kwargs):
        super().__init__(*args, **kwargs)
        self.restaurant = restaurant
        self.fields["name"].widget.attrs["placeholder"] = "e.g. Starters"
        add_bootstrap_classes(self)

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        same_name = Category.objects.filter(restaurant=self.restaurant, name__iexact=name).exclude(pk=self.instance.pk)
        if same_name.exists():
            raise forms.ValidationError("A category with this name already exists.")
        return name


class MenuItemForm(forms.ModelForm):
    """Add / edit a dish. Only this restaurant's categories can be picked."""

    remove_image = forms.BooleanField(required=False, label="Remove the current photo")

    class Meta:
        model = MenuItem
        fields = [
            "category", "name", "food_type", "price", "description", "ingredients", "prep_time",
            "image", "sort_order", "is_available", "is_active",
        ]
        labels = {
            "food_type": "Type",
            "price": "Price (₹)",
            "is_available": "In stock today",
            "is_active": "Show on the menu",
        }
        help_texts = {
            "price": "Leave empty when the dish has portions below.",
            "image": f"JPG or PNG, up to {MAX_IMAGE_MB} MB. Square photos look best.",
            "sort_order": "Order inside its category. Smaller numbers come first.",
            "is_available": "The kitchen can also switch this when an item runs out.",
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 2, "placeholder": "Short line shown under the name"}),
            "ingredients": forms.Textarea(attrs={"rows": 2, "placeholder": "e.g. chicken, butter, tomato, cream, spices"}),
            "prep_time": forms.TextInput(attrs={"placeholder": "e.g. 15-20 min"}),
            "price": forms.NumberInput(attrs={"step": "0.01", "min": "0", "inputmode": "decimal"}),
            "image": forms.FileInput(attrs={"accept": "image/*"}),
        }

    def __init__(self, *args, restaurant, **kwargs):
        super().__init__(*args, **kwargs)
        self.restaurant = restaurant
        self.fields["category"].queryset = Category.objects.filter(restaurant=restaurant)
        self.fields["category"].empty_label = "Choose a category"
        self.fields["name"].widget.attrs["placeholder"] = "e.g. Paneer Tikka"
        self.fields["price"].required = False  # a dish with portions takes its prices from them
        if not self.instance.image:
            del self.fields["remove_image"]
        add_bootstrap_classes(self)

    def clean_price(self):
        """Empty is allowed here (portions may give the prices). The view checks
        that one or the other is there; price_given says which."""
        price = self.cleaned_data.get("price")
        self.price_given = price is not None
        return price if price is not None else Decimal("0")

    # the photo's size (up to MAX_IMAGE_MB) is checked by the model field (menu.models.validate_photo_size)

    def clean(self):
        cleaned = super().clean()
        name = cleaned.get("name")
        category = cleaned.get("category")
        if name and category:
            same_name = MenuItem.objects.filter(
                restaurant=self.restaurant, category=category, name__iexact=name.strip()
            ).exclude(pk=self.instance.pk)
            if same_name.exists():
                self.add_error("name", f"“{name}” is already in {category}.")
        return cleaned

    def save_for(self, restaurant, price):
        """Save the item for this restaurant at this price, removing the photo if asked."""
        item = self.save(commit=False)
        item.restaurant = restaurant
        item.price = price
        if self.cleaned_data.get("remove_image") and not self.files.get("image"):
            item.image.delete(save=False)
            item.image = ""
        item.save()
        return item


class PortionForm(forms.ModelForm):
    """One portion row: its name and price."""

    class Meta:
        model = MenuItemPortion
        fields = ["name", "price"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "e.g. Half", "list": "portionNames", "data-portion-name": ""}),
            "price": forms.NumberInput(attrs={"step": "0.01", "min": "0", "inputmode": "decimal", "placeholder": "₹"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        add_bootstrap_classes(self)

    def clean_name(self):
        return self.cleaned_data["name"].strip()


class BasePortionFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        names = []
        for form in self.forms:
            if not hasattr(form, "cleaned_data") or form.cleaned_data.get("DELETE"):
                continue
            name = (form.cleaned_data.get("name") or "").lower()
            if name and name in names:
                raise forms.ValidationError("Each portion needs its own name.")
            names.append(name)


def portion_formset(*args, extra=1, **kwargs):
    """The portion rows of a dish (up to 6). `extra` empty rows are shown for new ones."""
    formset_class = forms.inlineformset_factory(
        MenuItem, MenuItemPortion, form=PortionForm, formset=BasePortionFormSet,
        extra=extra, max_num=6, validate_max=True, can_delete=True,
    )
    return formset_class(*args, prefix="portions", **kwargs)


def kept_portions(formset):
    """The portion rows that will be saved: filled in and not marked for deletion."""
    return [
        form.cleaned_data for form in formset.forms
        if form.cleaned_data and not form.cleaned_data.get("DELETE")
    ]
