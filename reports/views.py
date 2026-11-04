"""
Reports (roles.REPORTS), for the current location.

  report_index   the reports, grouped: Sales, Menu, Operations, Guests, Team, Audit
  report_view    one report: the period (Today / This week / This month / Range, the same
                 filter row as Bookings), a search over every row (?q=), its tables (striped,
                 100 rows a page: ?page=2 or ?page=all), and Export CSV / PDF / Print
                 (?export=csv|pdf&q=...: every row, not just the page)

Drill down, as in Tally: a click on a summary row opens the list behind it, and a
click on that list's row opens the bill. Order types "Dine in" -> the dine-in
bills (/reports/bill-register/?type=DINE_IN&live=1&back=...) -> Bill #212.
?back= is the report it came from: its Back link (and the bill's).

The reports themselves are in reports/catalog/, the exports in reports/exports/.
"""

from urllib.parse import parse_qsl, urlencode, urlsplit

from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from core import roles
from core.analytics import period_filter_context
from core.decorators import role_required
from core.pagination import paginate
from core.utils import get_user_location, is_htmx, report_back

from .catalog import GROUPS, REPORTS
from .catalog.common import NUMERIC, filter_text
from .exports import EXPORTERS
from .exports.letterhead import letterhead, period_text


@role_required(*roles.REPORTS)
def report_index(request):
    """Reports page: a card for each report, in its group."""
    groups = [(group, [{"slug": slug, **REPORTS[slug]} for slug in slugs]) for group, slugs in GROUPS]
    return render(request, "reports/index.html", {"groups": groups})


def matching(sections, search):
    """Only the rows that hold the searched words (in any column); totals are left out then,
    as they were for every row."""
    words = search.lower().split()
    found = []
    for section in sections:
        kept = [(row, link) for row, link in zip(section["rows"], section["links"])
                if all(word in " ".join(str(value).lower() for value in row) for word in words)]
        found.append({**section, "rows": [row for row, _ in kept], "links": [link for _, link in kept], "totals": None})
    return found


def cell(value, kind, label=""):
    """One value for the template: how to show it ("text" for words, even in a number
    column, e.g. "Total"), whether it sits on the right (numbers), and its column's label."""
    shown_as = "text" if isinstance(value, str) else kind
    return {"value": value, "kind": shown_as, "numeric": kind in NUMERIC, "label": label}


def with_cells(sections):
    """Ready every table for the template: header cells, row cells (with the words the
    search box looks in and where a click goes) and total cells."""
    for section in sections:
        section["heads"] = [{"label": label, "numeric": kind in NUMERIC} for label, kind in section["columns"]]
        section["cells"] = [{"values": [cell(value, kind, label) for value, (label, kind) in zip(row, section["columns"])],
                             "search": " ".join(str(value).lower() for value in row), "href": href}
                            for row, href in zip(section["rows"], section["hrefs"])]
        section["total_cells"] = ([cell(value, kind, label) for value, (label, kind) in zip(section["totals"], section["columns"])]
                                  if section["totals"] else None)
    return sections


def drill_filters(report, params):
    """What this report was narrowed to by the row that opened it (?type=DINE_IN): only what it knows."""
    return {key: params[key].strip() for key in report["filters"] if params.get(key, "").strip()}


def back_title(back):
    """The title of the report a Back link goes to."""
    parts = urlsplit(back).path.strip("/").split("/")
    report = REPORTS.get(parts[1]) if len(parts) > 1 else None
    return report["title"] if report else "the report"


def row_href(link, period_params, back_here):
    """Where a click on a row goes (catalog/common.py to_report / to_bill), with the way back."""
    if not link:
        return ""
    if "bill" in link:
        return reverse("billing:bill_detail", args=[link["bill"]]) + "?" + urlencode({"back": back_here})
    if link["period"]:  # one day or one month of this period
        start, end = link["period"]
        query = {"when": "range", "from": start.isoformat(), "to": end.isoformat()}
    else:
        query = dict(period_params)
    return reverse("reports:report", args=[link["report"]]) + "?" + urlencode({**query, **link["filters"], "back": back_here})


@role_required(*roles.REPORTS)
def report_view(request, slug):
    report = REPORTS.get(slug)
    if report is None:
        raise Http404("No such report.")
    place = get_user_location(request)
    period = period_filter_context(request.GET, timezone.localdate())
    filters = drill_filters(report, request.GET)
    back = report_back(request.GET.get("back"))
    search = request.GET.get("q", "").strip()
    sections = report["function"](place, period["start"], period["end"], **filters)
    if search:
        sections = matching(sections, search)

    # "Bill register · Order type: Dine in": on screen, on paper and in the files
    narrowed = [filter_text(place, key, value) for key, value in filters.items()]
    title = report["title"] + "".join(f" · {name}: {shown}" for name, shown in narrowed)

    exporter = EXPORTERS.get(request.GET.get("export"))
    if exporter:  # every row of the period (and search), not just the page on screen
        return exporter(slug, title, place, period["start"], period["end"], sections, search)

    # the period filter, the pages and the exports carry the narrowing and the way back on
    period_params = dict(parse_qsl(period["filter_query"]))
    keep = {**filters, **({"back": back} if back else {})}
    back_here = request.path + "?" + urlencode({**period_params, **keep, **({"q": search} if search else {})})
    for section in sections:  # 100 rows a page (?page=2, ?page=all); the totals stay the period's
        entries, section["pager"] = paginate(list(zip(section["rows"], section["links"])), request.GET)
        section["rows"] = [row for row, _ in entries]
        section["hrefs"] = [row_href(link, period_params, back_here) for _, link in entries]
    context = {
        "slug": slug,
        "report": report,
        "report_title": title,
        "narrowed": narrowed,
        "back": back,
        "back_title": back_title(back) if back else "",
        "search": search,
        "sections": with_cells(sections),
        "drillable": any(href for section in sections for href in section["hrefs"]),
        "letterhead": letterhead(place),
        "period_text": period_text(period["start"], period["end"]),
        "switch_groups": [(group, [(other, REPORTS[other]["title"]) for other in slugs]) for group, slugs in GROUPS],
        **period,
        "filter_query": urlencode({**period_params, **keep}),
        "filter_keep": list(keep.items()),
    }
    template = "reports/partials/_body.html" if is_htmx(request) else "reports/report.html"
    return render(request, template, context)
