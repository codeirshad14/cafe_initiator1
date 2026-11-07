"""
The public websites and their settings.

  home              /                          our own website (Mr Cafe): features, plans, demo
  demo_request      POST /demo/                its "Book a free demo" form
  cafe_site         /cafe/<slug>/              a cafe's own one-page website: the same look, the
                                               cafe's name, story, menu, locations and contacts
  cafe_feedback     POST /cafe/<slug>/feedback/  its feedback form (Food, Staff, Cafe stars, a message)
  order_feedback    /feedback/<order token>/   "Rate your visit" after the bill: the guest's bill
                                               and Food, Staff, Cafe stars (once per order)
  website_settings  /restaurant/website/       Cafe profile > Website: what that page says
  feedback_list     /restaurant/feedback/      Cafe profile > Feedback: what guests wrote
  feedback_show     POST .../<pk>/show/        show (or hide) one on the website
"""

import time

from django.conf import settings
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from billing.models import Bill
from core import roles
from core.decorators import role_required
from core.models import DEFAULT_MAX_USERS, Restaurant
from core.pagination import paginate
from core.utils import get_user_restaurant, is_htmx
from orders.cart import menu_with_cart
from orders.models import Order
from tables.models import takeaway_table

from .forms import CafeWebsiteForm, DemoRequestForm, FeedbackForm, OrderFeedbackForm
from .models import CafeWebsite, Feedback, rating_summary

FEEDBACK_PER_HOUR = 3  # from one visitor (their session): more is kept out, with the same thank-you


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


# ================================================================ a cafe's own website

def open_cafe(slug):
    """The cafe of /cafe/<slug>/ while it runs (switched on, membership running), else None."""
    restaurant = Restaurant.objects.filter(slug=slug).first()
    return restaurant if restaurant and restaurant.is_usable() else None


def on_disk(picture):
    """The picture is set and its file is really there (not lost in a move or a restore)."""
    try:
        return bool(picture) and picture.storage.exists(picture.name)
    except Exception:
        return False


def about_text(restaurant, categories, orders_online):
    """A few words about the cafe from what we know, while it has not written its own story."""
    dishes = sum(len(category.menu_items) for category in categories)
    text = f"Welcome to {restaurant.name}!"
    if dishes:
        names = ", ".join(category.name for category in categories[:3])
        more = " and more" if len(categories) > 3 else ""
        text += f" We serve {dishes} dish{'es' if dishes > 1 else ''}: {names}{more}."
    if orders_online and restaurant.delivery_enabled:
        text += " Eat here, take it away or get it delivered."
    elif orders_online:
        text += " Eat here or take it away."
    else:
        text += " Come and eat with us."
    return text


def cafe_site(request, slug):
    """A cafe's one-page website. Its words come from Cafe profile > Website; the rest
    (name, logo, address, phone, menu, locations, photos) from the cafe as it is now.
    Nothing of ours on it but a small "Website by" at the foot."""
    restaurant = open_cafe(slug)
    if restaurant is None:
        return render(request, "orders/customer_closed.html", {"public": True}, status=404)
    # not saved here: a cafe that never opened its Website tab shows the defaults
    website = getattr(restaurant, "website", None) or CafeWebsite(restaurant=restaurant)
    if not website.is_on:
        raise Http404("This cafe has switched its website off.")

    categories = menu_with_cart(restaurant)
    counter = takeaway_table(restaurant)
    orders_online = counter.is_active and restaurant.takes_orders
    photos = [photo for photo in restaurant.slides() if on_disk(photo["image"])]
    return render(request, "web/cafe.html", {
        "restaurant": restaurant,
        "website": website,
        "logo": restaurant.logo if on_disk(restaurant.logo) else None,
        "cover": website.cover if on_disk(website.cover) else (photos[0]["image"] if photos else None),
        "about": website.about or about_text(restaurant, categories, orders_online),
        "highlights": website.chosen_highlights(),
        "hours": website.hours_lines(),
        "categories": categories,
        "picks": [item for category in categories for item in category.menu_items if on_disk(item.image)][:4],
        "dish_count": sum(len(category.menu_items) for category in categories),
        "orders_online": orders_online,
        "can_book": restaurant.booking_enabled and restaurant.takes_orders,
        "locations": list(restaurant.locations.filter(is_active=True)),
        "photos": photos,
        "reviews": list(restaurant.feedback.filter(show_on_site=True)[:6]),
        "ratings": rating_summary(restaurant.feedback.all()) if website.show_ratings else None,
        "form": FeedbackForm(),
    })


def sent_lately(request):
    """How many feedback forms this visitor sent in the last hour (kept in their session)."""
    hour_ago = time.time() - 3600
    sent = [moment for moment in request.session.get("feedback_sent", []) if moment > hour_ago]
    request.session["feedback_sent"] = sent
    return sent


@require_POST
def cafe_feedback(request, slug):
    """HTMX: keep a guest's feedback for the cafe, then say thank you in place of the form."""
    restaurant = open_cafe(slug)
    if restaurant is None:
        raise Http404("No such cafe.")
    form = FeedbackForm(request.POST)
    if not form.is_valid():
        return render(request, "web/_feedback_form.html", {"form": form, "restaurant": restaurant})

    sent = sent_lately(request)
    # a robot filled the trap, or one visitor keeps sending: thank them, keep nothing
    if not form.cleaned_data["website"] and len(sent) < FEEDBACK_PER_HOUR:
        feedback = form.save(commit=False)
        feedback.restaurant = restaurant
        feedback.save()
        request.session["feedback_sent"] = sent + [time.time()]
    return render(request, "web/_feedback_thanks.html", {"name": form.cleaned_data["name"], "restaurant": restaurant})


# ================================================================ "Rate your visit" from the bill

def feedback_bill(order):
    """The order's bill the guest rates (its own, or the one it was billed together on),
    while it is made and not cancelled; else None."""
    bill = order.current_bill()  # no bill yet: None
    return bill if bill is not None and bill.status != Bill.Status.CANCELLED else None


def order_feedback(request, public_token):
    """/feedback/<order's token>/: the guest's own bill (to look back at) and three questions,
    Food, Staff and Cafe, 1 to 5 stars each. Once per order; after that it thanks them and
    shows their stars. Reached from the order's status page, the customer screen after
    paying, or the link staff send (Bills > a bill > Ask for feedback)."""
    order = get_object_or_404(Order.objects.select_related("restaurant", "table"), public_token=public_token)
    restaurant = order.restaurant
    bill = feedback_bill(order)
    given = Feedback.objects.filter(order=order).first()
    form = OrderFeedbackForm(request.POST or None)

    if request.method == "POST" and bill and not given and form.is_valid():
        given = Feedback(
            restaurant=restaurant, order=order,
            name=order.customer_name or "Guest", phone=order.customer_phone, **form.cleaned_data,
        )
        given.set_overall()
        try:
            with transaction.atomic():
                given.save()
        except IntegrityError:  # sent twice at the same moment: the first one counts
            given = Feedback.objects.get(order=order)
        return redirect("web:order_feedback", public_token=order.public_token)

    return render(request, "web/order_feedback.html", {
        "order": order,
        "restaurant": restaurant,
        "subtitle": f"{restaurant.name} · Bill #{bill.bill_no}" if bill else restaurant.name,
        "bill": bill,
        "items": bill.items.all() if bill else [],
        "payments": bill.payments.all() if bill else [],
        "given": given,
        "form": form,
        "website_on": getattr(restaurant, "website", None) is None or restaurant.website.is_on,
    })


# ================================================================ Cafe profile > Website, Feedback

@role_required(*roles.COMPANY)
def website_settings(request):
    """The cafe's admin writes what its website says, and sees where it is."""
    restaurant = get_user_restaurant(request)
    website = CafeWebsite.of(restaurant)
    form = CafeWebsiteForm(request.POST or None, request.FILES or None, instance=website)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Website saved. Open it to see how your guests see it.")
        return redirect("web:website_settings")
    return render(request, "web/website_settings.html", {
        "form": form,
        "restaurant": restaurant,
        "website": website,
        "site_url": request.build_absolute_uri(reverse("web:cafe", args=[restaurant.slug])),
    })


@role_required(*roles.COMPANY)
def feedback_list(request):
    """Guests' feedback (after the bill, and from the website), newest first; opening the
    page reads them. The side shows the average stars, also for Food, Staff and Cafe."""
    restaurant = get_user_restaurant(request)
    every = restaurant.feedback.select_related("order__bill")
    page, pager = paginate(every, request.GET)
    page = list(page)
    unread = {item.pk for item in page if not item.is_read}
    restaurant.feedback.filter(pk__in=unread).update(is_read=True)
    counts = {n: 0 for n in range(5, 0, -1)}
    for rating in every.values_list("rating", flat=True):
        counts[rating] += 1
    total = sum(counts.values())
    template = "web/_feedback_rows.html" if is_htmx(request) else "web/feedback_list.html"  # the pager: rows only
    return render(request, template, {
        "restaurant": restaurant,
        "items": page,
        "unread": unread,
        "pager": pager,
        "total": total,
        "average": round(sum(n * c for n, c in counts.items()) / total, 1) if total else None,
        "bars": [{"stars": n, "count": c, "share": round(c * 100 / total) if total else 0} for n, c in counts.items()],
        "summary": rating_summary(every) if total else None,
    })


@require_POST
@role_required(*roles.COMPANY)
def feedback_show(request, pk):
    """HTMX: show one feedback on the website ("What guests say"), or take it off."""
    item = get_object_or_404(get_user_restaurant(request).feedback, pk=pk)
    item.show_on_site = not item.show_on_site
    item.save(update_fields=["show_on_site"])
    return render(request, "web/_feedback_item.html", {"item": item})
