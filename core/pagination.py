"""
Long lists in pages of 100 rows (?page=2), or every row at once (?page=all).

One helper for every list (Bills, Menu items, Categories, Staff, Offers,
Locations) and every report table. Its foot is partials/_pager.html:
"1–100 of 834 bills", the page buttons and All.

    bills, pager = paginate(bills, request.GET)
"""

from django.core.paginator import Paginator

PER_PAGE = 100


def page_links(number, pages):
    """‹ 1 … 4 5 [6] 7 8 … 20 ›: the first and last page, and two either side of this one."""
    shown = sorted({1, pages, *range(max(1, number - 2), min(pages, number + 2) + 1)})
    links = [{"label": "‹", "value": number - 1 if number > 1 else None, "aria": "Previous page"}]
    last = 0
    for page in shown:
        if page - last > 1:
            links.append({"label": "…", "gap": True})
        links.append({"label": str(page), "value": page, "current": page == number, "aria": f"Page {page}"})
        last = page
    links.append({"label": "›", "value": number + 1 if number < pages else None, "aria": "Next page"})
    return links


def paginate(rows, params, per_page=PER_PAGE):
    """(the rows to show, the pager) for ?page=N or ?page=all in params (request.GET).
    rows: a queryset or a list. A page number out of range shows the nearest page."""
    paginator = Paginator(rows, per_page)
    count = paginator.count
    show_all = str(params.get("page", "")).lower() == "all"
    if show_all:
        shown, start, end, number = rows, (1 if count else 0), count, None
    else:
        page = paginator.get_page(params.get("page"))
        shown, start, end, number = page.object_list, page.start_index(), page.end_index(), page.number
    many = count > per_page
    return shown, {
        "count": count,
        "start": start,
        "end": end,
        "per_page": per_page,
        "show_all": show_all,
        "value": "all" if show_all else number,  # sent again when the list redraws itself
        "many": many,
        "links": page_links(number, paginator.num_pages) if many and not show_all else [],
    }
