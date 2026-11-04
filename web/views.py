from django.conf import settings
from django.shortcuts import render
from django.views.decorators.http import require_POST

from core.models import DEFAULT_MAX_USERS

from .forms import DemoRequestForm


def home(request):
    """The public one-page website at /. Always shown, logged in or not (the top
    bar then offers "Open my restaurant" instead of "Staff login")."""
    return render(request, "web/home.html", {
        "form": DemoRequestForm(),
        "included_logins": DEFAULT_MAX_USERS,
        "contact_phone": settings.CONTACT_PHONE,
        "contact_email": settings.CONTACT_EMAIL,
    })


@require_POST
def demo_request(request):
    """HTMX: save a "Book a free demo" request, then say thank you in place of the form."""
    form = DemoRequestForm(request.POST)
    if not form.is_valid():
        return render(request, "web/_demo_form.html", {"form": form})

    # a robot filled the hidden trap field: thank it and keep nothing
    if not form.cleaned_data["website"]:
        form.save()
    return render(request, "web/_demo_thanks.html", {"name": form.cleaned_data["name"]})
