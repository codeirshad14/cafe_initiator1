"""The bill as a thermal-printer slip (ESC/POS bytes): the same as print/bill.html.
What it shows is set in Cafe profile > Bill & print (name, title, logo, tax lines, UPI)."""

from django.utils import timezone

from core.escpos import Slip
from core.templatetags.money import inr, percent

ITEM_COLUMNS = (24, 5, 9, 10)  # Item, Qty, Rate, Amt: 48 characters
LOGO_DOTS = 384  # 48 mm wide at most
UPI_QR_DOTS = 256  # 32 mm: big enough for any phone to scan


def money(amount):
    return f"{amount:.2f}"


def bill_slip(bill):
    restaurant, order = bill.restaurant, bill.order
    slip = Slip()

    if restaurant.print_logo and restaurant.logo:
        slip.image(restaurant.logo, LOGO_DOTS)
    slip.text(restaurant.bill_name, center=True, bold=True, big=True)
    for line in restaurant.address.splitlines():
        slip.text(line, center=True)
    if restaurant.phone:
        slip.text(f"Ph: {restaurant.phone}", center=True)
    if restaurant.print_tax_details and restaurant.gstin:
        slip.text(f"GSTIN: {restaurant.gstin}", center=True)
    if restaurant.fssai_no:
        slip.text(f"FSSAI: {restaurant.fssai_no}", center=True)
    slip.rule()
    slip.text("CANCELLED BILL" if bill.status == "CANCELLED" else restaurant.invoice_title, center=True, bold=True)
    slip.rule()

    slip.row(f"Bill No: {bill.bill_no}", f"{bill.bill_date:%d-%m-%Y}")
    slip.row(order.print_label, f"{timezone.localtime(bill.created_at):%I:%M %p}")
    if order.is_parcel and order.customer_phone:
        slip.row("Mobile", order.customer_phone)
    slip.row(f"Order: #{order.order_no}", order.customer_name[:16])
    if order.customer_address:
        slip.text(f"Address: {order.customer_address}")
    if order.is_delivery and order.rider:
        slip.row("Rider", order.rider.name)
    slip.rule()

    slip.columns(["Item", "Qty", "Rate", "Amt"], ITEM_COLUMNS, bold=True)
    slip.rule()
    for line in bill.items.all():
        slip.columns([line.item_name, line.qty, money(line.rate), money(line.amount)], ITEM_COLUMNS)
    slip.rule()

    slip.row("Subtotal", money(bill.subtotal))
    if bill.discount_amount:
        offer = f" ({bill.offer_name})" if bill.offer_name else ""
        slip.row(f"Discount{offer}", f"-{money(bill.discount_amount)}")
    if bill.delivery_charge:
        slip.row("Delivery charge", money(bill.delivery_charge))
    if restaurant.print_tax_details:
        if bill.discount_amount or bill.delivery_charge:
            slip.row("Taxable", money(bill.taxable_amount))
        slip.row(f"CGST @ {percent(bill.half_percent)}%", money(bill.cgst_amount))
        slip.row(f"SGST @ {percent(bill.half_percent)}%", money(bill.sgst_amount))
    elif bill.tax_amount:
        slip.row("Taxes", money(bill.tax_amount))  # so the lines still add up to the total
    slip.row("Round off", money(bill.round_off))
    slip.rule("=")
    slip.row("TOTAL", inr(bill.grand_total), bold=True, big=True)
    slip.rule("=")

    payments = list(bill.payments.all())
    for payment in payments:
        reference = f" ({payment.reference_no})" if payment.reference_no else ""
        slip.row(f"{payment.get_mode_display()}{reference}", money(payment.amount))
    if payments:
        if bill.balance:
            slip.row("Balance due", money(bill.balance), bold=True)
        slip.rule()

    if restaurant.shows_upi_on_bill and bill.is_open_for_payment:
        slip.text("Scan & pay by UPI", center=True, bold=True)
        if restaurant.upi_qr:
            slip.image(restaurant.upi_qr, UPI_QR_DOTS, sharp=True)
        if restaurant.upi_id:
            slip.text(f"UPI ID: {restaurant.upi_id}", center=True)
        slip.rule()

    slip.text("Thank you! Visit again.", center=True, bold=True)
    slip.text("Prices in Rs." + (" GST included as shown above." if restaurant.print_tax_details else ""), center=True)
    slip.cut()
    return slip.to_bytes()
