"""QR codes for tables, made with the `qrcode` library."""

import base64
from io import BytesIO

import qrcode
from django.conf import settings

from .models import public_path


def full_url(request, path):
    """The address with the site in front, e.g. http://192.168.1.10:8000/m/<token>/."""
    if settings.SITE_URL:
        return settings.SITE_URL.rstrip("/") + path
    return request.build_absolute_uri(path)


def table_menu_url(request, table):
    """The full address a table's QR code opens.

    A dining table's uses its secret qr_token, never the table id. The counter's
    (take away / delivery) opens the restaurant's public menu, the one menu for parcels.
    """
    return full_url(request, table.menu_path)


# the restaurant's two menu QR codes besides the tables' (Tables & QR page)
# band / label / help: the words on its printable card (qr_card.py, "QR + label")
MENU_QRS = {
    "order": {"title": "Order menu", "url_name": "orders:public_menu", "icon": "bag-check",
              "text": "Takeaway and delivery orders. For WhatsApp, Instagram, Google Maps, the counter.",
              "cta": "Scan to order takeaway or delivery",
              "band": "Order online", "label": "Scan me to Order", "help": "Takeaway or delivery, right from your phone"},
    "view": {"title": "View-only menu", "url_name": "orders:menu_view", "icon": "eye",
             "text": "Guests can only look: no ordering. For the door, the wall or flyers.",
             "cta": "Scan to see our menu",
             "band": "Our menu", "label": "Scan me for Menu", "help": "Point your phone camera at the code"},
}


def menu_qr_url(request, location, kind):
    """The full address of the location's order menu or view-only menu."""
    return full_url(request, public_path(MENU_QRS[kind]["url_name"], location))


def qr_png_bytes(text, width=None):
    """A black-on-white QR code for `text`, as PNG bytes. width: at most that many
    pixels wide, at whole pixels a square (sharp on a thermal printer)."""
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2)
    qr.add_data(text)
    qr.make(fit=True)
    if width:
        qr.box_size = max(1, width // (qr.modules_count + 2 * qr.border))
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    image.save(buffer)
    return buffer.getvalue()


def qr_data_uri(text):
    """The same PNG written straight into an <img src="...">, for the print sheet."""
    encoded = base64.b64encode(qr_png_bytes(text)).decode("ascii")
    return f"data:image/png;base64,{encoded}"
