"""
A UPI payment link with the bill's amount in it, for the QR code the guest scans at the
counter (Bills > a bill > Show UPI QR). Every UPI app (GPay, PhonePe, Paytm, BHIM …)
reads it and opens with the cafe's UPI ID, its name and the amount already filled in:

    upi://pay?pa=spicegarden@okicici&pn=Spice%20Garden&am=586.00&cu=INR&tn=Bill%2012

The money goes straight to the cafe's own account; we only show the code. Once the
guest has paid, the cashier records it as a UPI payment (one tap).
"""

from urllib.parse import quote

from tables.qr import qr_data_uri, qr_png_bytes


def upi_link(restaurant, amount, note=""):
    """The upi://pay link for this amount (the cafe's UPI ID from Cafe profile > Bill & print)."""
    params = [("pa", restaurant.upi_id), ("pn", restaurant.bill_name[:50]), ("am", f"{amount:.2f}"), ("cu", "INR")]
    if note:
        params.append(("tn", note[:50]))
    return "upi://pay?" + "&".join(f"{key}={quote(str(value), safe='@.-_')}" for key, value in params)


def bill_upi_link(bill):
    """The link for the bill's balance (what is still to pay)."""
    return upi_link(bill.restaurant, bill.balance, f"Bill {bill.bill_no} {bill.restaurant.name}")


def bill_upi_png(bill, width=None):
    """The QR code of the bill's balance, as PNG bytes (width: see qr_png_bytes)."""
    return qr_png_bytes(bill_upi_link(bill), width)


def prints_amount_qr(bill):
    """The printed bill gets the QR code with the amount in it: UPI on the bill (Bill & print),
    a UPI ID to pay to, and something left to pay. Without a UPI ID the uploaded QR picture prints."""
    restaurant = bill.restaurant
    return (restaurant.shows_upi_on_bill and bool(restaurant.upi_id)
            and bill.is_open_for_payment and bill.balance > 0)


def bill_upi_data_uri(bill):
    """The same QR code written straight into an <img src="...">, for the printed bill."""
    return qr_data_uri(bill_upi_link(bill))
