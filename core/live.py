"""
Live screens: one screen's change shows on the others within ~3 seconds.

Every saved or deleted order, KOT, bill, payment or booking adds 1 to its
restaurant's live_version. Each staff page asks for that number every 3 seconds
(core.views.live, static/js/app.js part 10); when it moved, the page fires the
"liveChanged" event and its live blocks (floor, table, kitchen, bills to make,
deliveries, ready list ...) reload themselves at once. So the kitchen marking a
KOT Ready shows on the Floor, the table's page and Bills without a page reload.
The blocks' own every-N-seconds refresh stays as a fallback.
"""

from django.db.models import F
from django.db.models.signals import post_delete, post_save


def bump(restaurant_id):
    from .models import Restaurant
    Restaurant.objects.filter(pk=restaurant_id).update(live_version=F("live_version") + 1)


def something_changed(sender, instance, **kwargs):
    bump(instance.restaurant_id)


def watch_changes():
    """Called once at start-up (core.apps.CoreConfig.ready)."""
    from billing.models import Bill, Payment
    from orders.models import KOT, Order
    from tables.models import Booking

    for model in (Order, KOT, Bill, Payment, Booking):
        post_save.connect(something_changed, sender=model, dispatch_uid=f"live-save-{model.__name__}")
        post_delete.connect(something_changed, sender=model, dispatch_uid=f"live-delete-{model.__name__}")
