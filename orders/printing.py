"""The KOT as a thermal-printer slip (ESC/POS bytes): the same as print/kot.html.
Dishes and quantities in big letters for the kitchen, no prices."""

from django.utils import timezone

from core.escpos import Slip


def kot_slip(kot, round_no):
    order = kot.order
    slip = Slip()

    slip.text(kot.restaurant.name, center=True, bold=True)
    slip.text("KITCHEN ORDER TICKET", center=True)
    slip.rule()

    if order.is_delivery:
        where = "DELIVERY"
    elif order.is_takeaway:
        where = "TAKEAWAY"
    else:
        where = str(order.table)
    slip.row(f"KOT #{kot.kot_no}", where, bold=True, big=True)
    if order.is_delivery:
        slip.text("*** DELIVERY - PACK IT ***", center=True, bold=True)
    elif order.is_takeaway:
        slip.text("*** TAKEAWAY - PACK IT ***", center=True, bold=True)
    else:
        slip.text("DINE IN", center=True, bold=True)
    created = timezone.localtime(kot.created_at)
    slip.row(f"Order #{order.order_no}", f"Round {round_no}")
    slip.row(f"{created:%d-%m-%Y}", f"{created:%I:%M %p}")
    if order.waiter:
        slip.row("Waiter", order.waiter.name)
    slip.row("Source", order.get_source_display())
    slip.rule()

    items = list(kot.items.filter(is_cancelled=False))
    slip.add("QTY  ITEM", bold=True)
    slip.rule()
    for line in items:
        slip.text(f"{line.qty:>3}  {line.item_name}", bold=True, big=True)
    slip.rule()
    slip.row("Total items", len(items))

    if kot.note:
        slip.rule()
        slip.text(f"NOTE: {kot.note}", bold=True)
    slip.rule()
    slip.text(f"Printed {timezone.localtime():%d-%m-%Y %I:%M %p}", center=True)
    slip.cut()
    return slip.to_bytes()
