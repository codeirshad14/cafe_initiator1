"""Menu reports: what sells (item-wise, category-wise) and what does not."""

from django.db.models import Count, Sum

from menu.models import MenuItem

from .common import ZERO, average, bill_items, money, section, share, to_bills, to_report


def item_sales(location, start, end, category=""):
    """Each dish: bills, quantity sold, amount (before discount and tax), average price and share, best seller first."""
    items = bill_items(location, start, end)
    if category:  # opened from Category-wise sales
        items = items.filter(category_name=category)
    grouped = list(items.values("item_name", "category_name").annotate(
        qty=Sum("qty"), amount=Sum("amount"), bills=Count("bill", distinct=True)).order_by("-amount", "item_name"))
    total = items.aggregate(qty=Sum("qty"), amount=Sum("amount"))
    grand = money(total["amount"])
    rows = [[row["item_name"], row["category_name"], row["bills"], row["qty"], row["amount"],
             average(row["amount"], row["qty"]), share(row["amount"], grand)] for row in grouped]
    return [section([("Item", "text"), ("Category", "text"), ("Bills", "int"), ("Qty sold", "int"), ("Amount", "money"),
                     ("Average price", "money"), ("Share", "percent")],
                    rows, ["Total", "", "", total["qty"] or 0, grand, "", ""],
                    links=[to_bills(item=row["item_name"]) for row in grouped])]


def category_sales(location, start, end):
    """Each menu category: dishes sold, quantity, amount and share."""
    items = bill_items(location, start, end)
    grouped = list(items.values("category_name").annotate(
        dishes=Count("item_name", distinct=True), qty=Sum("qty"), amount=Sum("amount")).order_by("-amount"))
    total = items.aggregate(qty=Sum("qty"), amount=Sum("amount"))
    grand = money(total["amount"])
    rows = [[row["category_name"], row["dishes"], row["qty"], row["amount"], share(row["amount"], grand)] for row in grouped]
    return [section([("Category", "text"), ("Dishes sold", "int"), ("Qty sold", "int"), ("Amount", "money"),
                     ("Share", "percent")], rows, ["Total", "", total["qty"] or 0, grand, ""],
                    links=[to_report("item-sales", category=row["category_name"]) for row in grouped])]


def slow_items(location, start, end):
    """Every dish on the menu with what it sold, least first: dishes not sold at all come on top."""
    sold = {row["menu_item"]: row for row in bill_items(location, start, end).values("menu_item").annotate(
        qty=Sum("qty"), amount=Sum("amount"))}
    dishes = MenuItem.objects.filter(restaurant=location.restaurant, is_active=True).select_related("category")
    lines = []  # (row, the dish's bills when it sold)
    for dish in dishes:
        row = sold.get(dish.pk, {"qty": 0, "amount": ZERO})
        lines.append(([dish.name, dish.category.name, dish.price, "Yes" if dish.is_available else "No (out today)",
                       row["qty"], row["amount"]], to_bills(dish=dish.pk) if row["qty"] else None))
    lines.sort(key=lambda line: (line[0][4], line[0][0]))
    rows = [row for row, _ in lines]
    not_sold = sum(1 for row in rows if not row[4])
    return [section([("Item", "text"), ("Category", "text"), ("Menu price", "money"), ("In stock", "text"),
                     ("Qty sold", "int"), ("Amount", "money")],
                    rows, [f"{not_sold} not sold", "", "", "", sum(row[4] for row in rows), sum((row[5] for row in rows), ZERO)],
                    links=[link for _, link in lines])]
