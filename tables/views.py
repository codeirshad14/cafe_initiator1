"""
Tables & QR (roles.MENU_SETUP): the current location's tables and their QR
codes, and the location's two menu QR codes (order menu, view-only menu).
"""

from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify

from core import roles
from core.decorators import role_required
from core.utils import delete_with_confirm, get_user_location, htmx_saved, is_htmx

from .forms import DiningTableForm
from .models import DiningTable
from .qr import MENU_QRS, menu_qr_url, qr_data_uri, qr_png_bytes, table_menu_url
from .qr_card import TABLE_CARD, qr_card_png


def location_sections(location):
    """The section names in use here, e.g. ["AC Hall", "Rooftop"], for filters and suggestions."""
    return (
        DiningTable.objects.filter(location=location).exclude(section="")
        .order_by("section").values_list("section", flat=True).distinct()
    )


def filtered_tables(request):
    """This location's tables, narrowed by search and section, each with its menu address."""
    tables = DiningTable.objects.filter(location=get_user_location(request))

    q = request.GET.get("q", "").strip()
    if q:
        tables = tables.filter(Q(name__icontains=q) | Q(section__icontains=q))

    section = request.GET.get("section", "")
    if section:
        tables = tables.filter(section=section)

    tables = list(tables)
    for table in tables:
        table.menu_url = table_menu_url(request, table)
    return tables


def menu_qr_cards(request, location):
    """The order menu's and the view-only menu's QR: [{"kind", "title", "url", ...}].
    An Only Menu cafe (core/plans.py) has the view-only one alone."""
    kinds = ["view"] if location.restaurant.menu_only else list(MENU_QRS)
    return [{"kind": kind, "url": menu_qr_url(request, location, kind), **MENU_QRS[kind]} for kind in kinds]


@role_required(*roles.MENU_SETUP)
def table_list(request):
    """Tables & QR page: the two menu QR codes (order, view only), then a card per table with its QR code."""
    place = get_user_location(request)
    return render(request, "tables/table_list.html", {
        "tables": filtered_tables(request),
        "sections": location_sections(place),
        "menu_qrs": menu_qr_cards(request, place),
    })


def qr_response(request, url, filename, words, table_name=""):
    """A QR code as a PNG: the code alone, or with ?card=1 the printable card with its
    words (tables/qr_card.py). ?download=1 saves it as a file."""
    if request.GET.get("card"):
        place = get_user_location(request)
        png = qr_card_png(url, place.restaurant.name, words["band"], words["label"], words["help"], table_name)
        filename += "-card"
    else:
        png = qr_png_bytes(url)
    response = HttpResponse(png, content_type="image/png")
    if request.GET.get("download"):
        response["Content-Disposition"] = f'attachment; filename="{filename}.png"'
    return response


@role_required(*roles.MENU_SETUP)
def menu_qr(request, kind):
    """The order menu's or the view-only menu's QR code (or card, ?card=1) as a PNG."""
    if kind not in MENU_QRS or (kind != "view" and get_user_location(request).restaurant.menu_only):
        raise Http404
    return qr_response(request, menu_qr_url(request, get_user_location(request), kind), f"qr-{kind}-menu", MENU_QRS[kind])


@role_required(*roles.MENU_SETUP)
def table_rows(request):
    """HTMX: just the table cards, after a filter change, save or delete."""
    return render(request, "tables/_table_cards.html", {"tables": filtered_tables(request)})


@role_required(*roles.MENU_SETUP)
def table_add(request):
    """Side panel: add a table at the current location. Its QR token is created automatically."""
    if not is_htmx(request):
        return redirect("tables:table_list")
    place = get_user_location(request)

    if request.method == "POST":
        form = DiningTableForm(request.POST, location=place)
        if form.is_valid():
            table = form.save(commit=False)
            table.restaurant, table.location = place.restaurant, place
            table.save()
            return htmx_saved(f"{table.label} added. Its QR code is ready.")
    else:
        form = DiningTableForm(location=place)

    return render(request, "tables/_table_form.html", {
        "form": form, "sections": location_sections(place),
        "title": "Add table", "submit_label": "Add table",
    })


@role_required(*roles.MENU_SETUP)
def table_edit(request, pk):
    """Side panel: rename a table, move it to a section or switch it off."""
    if not is_htmx(request):
        return redirect("tables:table_list")
    place = get_user_location(request)
    table = get_object_or_404(DiningTable, pk=pk, location=place)

    if request.method == "POST":
        form = DiningTableForm(request.POST, instance=table, location=place)
        if form.is_valid():
            form.save()
            return htmx_saved(f"{table.label} updated.")
    else:
        form = DiningTableForm(instance=table, location=place)

    return render(request, "tables/_table_form.html", {
        "form": form, "sections": location_sections(place),
        "title": f"Edit {table.label}", "submit_label": "Save changes",
    })


@role_required(*roles.MENU_SETUP)
def table_delete(request, pk):
    """Side panel: delete a table. Blocked once it has orders."""
    if not is_htmx(request):
        return redirect("tables:table_list")
    table = get_object_or_404(DiningTable, pk=pk, location=get_user_location(request))
    return delete_with_confirm(
        request, table, "Table",
        "It has orders in the records. Switch off “Table is in use” instead; "
        "its QR code will then stop working.",
    )


@role_required(*roles.MENU_SETUP)
def table_qr(request, pk):
    """The table's QR code (or card, ?card=1) as a PNG. The counter's is the Order menu's."""
    table = get_object_or_404(DiningTable, pk=pk, location=get_user_location(request))
    if table.is_takeaway:
        words, table_name = MENU_QRS["order"], ""
    else:
        words, table_name = TABLE_CARD, table.name
    return qr_response(request, table_menu_url(request, table), f"qr-{slugify(table.name) or table.pk}", words, table_name)


@role_required(*roles.MENU_SETUP)
def qr_sheet(request):
    """Printable page: one "Scan to order" card per active table here (optionally one
    section). ?menus=1: the order menu's and the view-only menu's cards instead."""
    place = get_user_location(request)
    restaurant = place.restaurant
    if request.GET.get("menus") or restaurant.menu_only:  # Only Menu: no table QR codes
        menus = [{**card, "qr": qr_data_uri(card["url"])} for card in menu_qr_cards(request, place)]
        return render(request, "tables/qr_sheet.html", {"restaurant": restaurant, "menus": menus, "cards": []})

    tables = DiningTable.objects.filter(location=place, is_active=True)
    section = request.GET.get("section", "")
    if section:
        tables = tables.filter(section=section)

    cards = [{"table": table, "qr": qr_data_uri(table_menu_url(request, table))} for table in tables]
    return render(request, "tables/qr_sheet.html", {
        "restaurant": restaurant,
        "cards": cards,
        "sections": location_sections(place),
        "section": section,
    })
