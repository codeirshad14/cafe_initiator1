"""
Bill arithmetic. Plain functions with Decimal only (never float), so they are
easy to test (billing/tests.py).

    subtotal         sum of the dishes
  - discount         an amount, or a percent of the subtotal
  + delivery charge  delivery orders only (taxed with the food)
  = taxable amount
  + CGST + SGST      the restaurant's GST %, split half and half
  + round off        up or down to the nearest rupee
  = grand total
"""

from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal("0.00")
PAISE = Decimal("0.01")
RUPEE = Decimal("1")


def money(value):
    """Round to paise, the usual way (0.005 goes up)."""
    return Decimal(value).quantize(PAISE, rounding=ROUND_HALF_UP)


def discount_amount_for(subtotal, discount_type, discount_value):
    """The discount in rupees. A percent is taken of the subtotal; never more than the subtotal."""
    value = Decimal(discount_value or 0)
    if value <= 0:
        return ZERO
    if discount_type == "PERCENT":
        value = subtotal * min(value, Decimal("100")) / Decimal("100")
    return money(min(value, subtotal))


def bill_totals(subtotal, discount_amount, gst_percent, delivery_charge=ZERO):
    """Every figure printed at the bottom of a bill, as a dict of Decimals."""
    subtotal = money(subtotal)
    discount_amount = money(min(discount_amount, subtotal))
    delivery_charge = money(delivery_charge)
    taxable = subtotal - discount_amount + delivery_charge

    half_rate = Decimal(gst_percent) / Decimal("2")
    cgst = money(taxable * half_rate / Decimal("100"))
    sgst = cgst  # always the same half

    before_round = taxable + cgst + sgst
    grand_total = before_round.quantize(RUPEE, rounding=ROUND_HALF_UP)
    return {
        "subtotal": subtotal,
        "discount_amount": discount_amount,
        "delivery_charge": delivery_charge,
        "taxable_amount": taxable,
        "gst_percent": Decimal(gst_percent),
        "half_percent": half_rate,  # shown as "CGST 2.5%"; not saved
        "cgst_amount": cgst,
        "sgst_amount": sgst,
        "round_off": money(grand_total - before_round),
        "grand_total": money(grand_total),
    }
