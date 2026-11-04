"""A report as a CSV file that opens in Excel: the letterhead on top, then each table."""

import csv

from django.http import HttpResponse

from .letterhead import generated_text, letterhead, period_text, plain


def csv_response(slug, title, location, start, end, sections, search=""):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{slug}_{start}_{end}.csv"'
    response.write("﻿")  # tells Excel the file is UTF-8
    writer = csv.writer(response)

    head = letterhead(location)
    writer.writerow([head["name"]])
    if head["trade_name"]:
        writer.writerow([head["trade_name"]])
    for line in head["lines"]:
        writer.writerow([line])
    writer.writerow([])
    writer.writerow([title])
    writer.writerow(["Period", period_text(start, end)])
    if head["location"]:
        writer.writerow(["Location", head["location"]])
    if search:
        writer.writerow(["Search", search])
    writer.writerow(["Generated", generated_text()])

    for section in sections:
        writer.writerow([])
        if section["title"]:
            writer.writerow([section["title"]])
        kinds = [kind for _, kind in section["columns"]]
        writer.writerow([label for label, _ in section["columns"]])
        for row in section["rows"]:
            writer.writerow([plain(value, kind) for value, kind in zip(row, kinds)])
        if section["totals"]:
            writer.writerow([plain(value, kind) for value, kind in zip(section["totals"], kinds)])
    return response
