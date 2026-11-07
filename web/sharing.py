"""
The "Rate your visit" link for an order (web.views.order_feedback), the ways staff hand
it to the guest, and the guest's stars once given. Used by the bill page (Bills > a bill >
Ask for feedback) and the customer screen after paying (billing.views).
"""

from urllib.parse import quote

from django.urls import reverse

from tables.qr import full_url, qr_data_uri

from .models import Feedback


def feedback_url(request, order):
    """The full address, e.g. https://cafe.example.com/feedback/<order's token>/ (SITE_URL first)."""
    return full_url(request, reverse("web:order_feedback", args=[order.public_token]))


def whatsapp_link(phone, text):
    """wa.me link that opens WhatsApp to this Indian mobile with the text typed in (None without a mobile)."""
    digits = "".join(ch for ch in phone or "" if ch.isdigit())
    if len(digits) == 10:
        digits = "91" + digits
    return f"https://wa.me/{digits}?text={quote(text)}" if len(digits) >= 11 else None


def feedback_context(request, bill):
    """For the bill page's "Guest feedback" box: the stars given, or the link to send."""
    order = bill.order
    url = feedback_url(request, order)
    restaurant = bill.restaurant
    message = (f"Thank you for visiting {restaurant.name}! Your bill #{bill.bill_no} and a quick "
               f"3-tap rating (food, staff, cafe): {url}")
    return {
        "feedback": Feedback.objects.filter(order=order).first(),
        "feedback_url": url,
        "feedback_whatsapp": whatsapp_link(order.customer_phone, message),
    }


def feedback_qr(request, order):
    """The link as a QR code picture (data: URI), for the customer screen after paying."""
    return qr_data_uri(feedback_url(request, order))
