"""
Festival offers: Cafe profile > Offers (admin, manager). Offers are the company's: every location.

  offer_list    the offers: running today, upcoming, ended
  offer_rows    HTMX: just the list, after a save or delete
  offer_add     side panel: a new offer
  offer_edit    side panel: change it, or switch it off
  offer_delete  side panel: delete it (bills keep the offer's name they printed)

A running offer is filled in as the discount on the bill screen by itself
(billing.views.bill_create, billing.services.offer_for).
"""

from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core import roles
from core.decorators import role_required
from core.pagination import paginate
from core.utils import delete_with_confirm, get_user_restaurant, htmx_saved, is_htmx

from .forms import OfferForm
from .models import Offer

OFFER_ROLES = roles.COMPANY


def offers_with_state(request):
    """This restaurant's offers, each with state: running / upcoming / ended / off."""
    today = timezone.localdate()
    offers = list(Offer.objects.filter(restaurant=get_user_restaurant(request)))
    for offer in offers:
        if not offer.is_active:
            offer.state = "off"
        elif offer.end_date < today:
            offer.state = "ended"
        elif offer.start_date > today:
            offer.state = "upcoming"
        else:
            offer.state = "running"
    return offers


@role_required(*OFFER_ROLES)
def offer_list(request):
    offers, pager = paginate(offers_with_state(request), request.GET)
    return render(request, "billing/offer_list.html", {"offers": offers, "pager": pager})


@role_required(*OFFER_ROLES)
def offer_rows(request):
    offers, pager = paginate(offers_with_state(request), request.GET)
    return render(request, "billing/_offer_rows.html", {"offers": offers, "pager": pager})


@role_required(*OFFER_ROLES)
def offer_add(request):
    if not is_htmx(request):
        return redirect("billing:offer_list")
    form = OfferForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        offer = form.save(commit=False)
        offer.restaurant = get_user_restaurant(request)
        offer.save()
        return htmx_saved(f"Offer “{offer.name}” added.")
    return render(request, "billing/_offer_form.html", {"form": form, "title": "Add offer", "submit_label": "Add offer"})


@role_required(*OFFER_ROLES)
def offer_edit(request, pk):
    if not is_htmx(request):
        return redirect("billing:offer_list")
    offer = get_object_or_404(Offer, pk=pk, restaurant=get_user_restaurant(request))
    form = OfferForm(request.POST or None, instance=offer)
    if request.method == "POST" and form.is_valid():
        form.save()
        return htmx_saved(f"Offer “{offer.name}” saved.")
    return render(request, "billing/_offer_form.html", {"form": form, "title": f"Edit {offer.name}", "submit_label": "Save changes"})


@role_required(*OFFER_ROLES)
def offer_delete(request, pk):
    if not is_htmx(request):
        return redirect("billing:offer_list")
    offer = get_object_or_404(Offer, pk=pk, restaurant=get_user_restaurant(request))
    return delete_with_confirm(request, offer, "Offer", "")
