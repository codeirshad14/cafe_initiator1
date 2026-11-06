"""
A UPI payment link with the bill's amount in it, for the QR code the guest scans at the
counter (Bills > a bill > Show UPI QR). Every UPI app (GPay, PhonePe, Paytm, BHIM …)
reads it and opens with the cafe's UPI ID, its name and the amount already filled in:

    upi://pay?pa=spicegarden@okicici&pn=Spice%20Garden&am=586.00&cu=INR&tn=Bill%2012

The money goes straight to the cafe's own account; we only show the code. Once the
guest has paid, the cashier records it as a UPI payment (one tap).
"""

from urllib.parse import quote

from tables.qr import qr_png_bytes


def upi_link(restaurant, amount, note=""):
    """The upi://pay link for this amount (the cafe's UPI ID from Cafe profile > Bill & print)."""
    params = [("pa", restaurant.upi_id), ("pn", restaurant.bill_name[:50]), ("am", f"{amount:.2f}"), ("cu", "INR")]
    if note:
        params.append(("tn", note[:50]))
    return "upi://pay?" + "&".join(f"{key}={quote(str(value), safe='@.-_')}" for key, value in params)


def bill_upi_png(bill):
    """The QR code of the bill's balance, as PNG bytes."""
    note = f"Bill {bill.bill_no} {bill.restaurant.name}"
    return qr_png_bytes(upi_link(bill.restaurant, bill.balance, note))
