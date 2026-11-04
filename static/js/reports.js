/* ==========================================================================
   reports.js — the report page (templates/reports/report.html).

   1. Export CSV / PDF ([data-export]) carry the words in the search box (q=),
      so the file holds the same rows as the screen.
   2. Print ([data-print-report]): the browser's print, with the letterhead on top.
   3. Another report ([data-report-switch]) opens for the same period.
   4. While the search box narrows the rows, the totals (of every row) are hidden,
      as in the exports.
   5. The search runs on the server over every row (the report shows 100 rows a
      page): typing asks for the report again, and every redraw of the report
      (period, page) carries the words (q=). A reload keeps them in the box.
   6. While the report loads again, three dots show over it (.is-loading).
   7. Drill down, as in Tally: a click anywhere on a row with details
      ([data-drill]) opens them; Esc goes back to the report it came from.
   ========================================================================== */

(function () {
  const search = document.querySelector("[data-search-in='#reportBody']");

  function withSearch(href) {
    const url = new URL(href, window.location.href);
    const words = search ? search.value.trim() : "";
    if (words) url.searchParams.set("q", words);
    else url.searchParams.delete("q");
    return url.pathname + url.search;
  }

  // 1. the export links, at the moment they are used (the body is redrawn by the period filter)
  document.addEventListener("click", function (event) {
    const link = event.target.closest("[data-export]");
    if (link) link.href = withSearch(link.getAttribute("href"));
  });

  // 2. print
  document.addEventListener("click", function (event) {
    if (event.target.closest("[data-print-report]")) window.print();
  });

  // 3. another report, the same period (the address holds it: the filter pushes it there),
  //    not narrowed to the row this one was opened from
  const switcher = document.querySelector("[data-report-switch]");
  if (switcher) {
    switcher.addEventListener("change", function () {
      const here = new URLSearchParams(window.location.search);
      const period = new URLSearchParams();
      ["when", "from", "to"].forEach(function (name) {
        if (here.get(name)) period.set(name, here.get(name));
      });
      const query = period.toString();
      window.location = switcher.value + (query ? "?" + query : "");
    });
  }

  // 7. drill down: the whole row opens its details (its first cell is the real link,
  //    for the keyboard, a new tab and the phone); Esc goes back
  document.addEventListener("click", function (event) {
    const row = event.target.closest("tr[data-drill]");
    if (!row || event.target.closest("a, button") || window.getSelection().toString()) return;
    if (event.ctrlKey || event.metaKey) window.open(row.dataset.drill, "_blank");
    else window.location = row.dataset.drill;
  });
  const back = document.querySelector("[data-report-back]");
  document.addEventListener("keydown", function (event) {
    if (!back || event.key !== "Escape" || event.defaultPrevented) return;
    if (event.target.closest("input, select, textarea, .dropdown")) return;  // Esc there closes the menu or clears the box
    if (document.querySelector(".dropdown-menu.show, .offcanvas.show, .modal.show")) return;
    window.location = back.href;
  });

  // 6. the loading dots: on when a redraw of the report starts, off when it ends
  //    (the new report comes without them; an error or a lost connection takes them off)
  function loading(event, on) {
    const target = event.detail.target;
    if (target && target.id === "reportBody") target.classList.toggle("is-loading", on);
  }
  document.body.addEventListener("htmx:beforeRequest", function (event) { loading(event, true); });
  document.body.addEventListener("htmx:afterRequest", function (event) { loading(event, false); });

  // 4. totals only for the whole period
  function showTotals() {
    const searching = Boolean(search && search.value.trim());
    document.querySelectorAll("#reportBody tfoot").forEach(function (foot) { foot.hidden = searching; });
  }
  if (search) search.addEventListener("input", showTotals);
  document.body.addEventListener("htmx:afterSettle", showTotals);

  // 5. the search on the server, page 1 again
  if (!search) return;
  const asked = new URLSearchParams(window.location.search).get("q");
  if (asked) search.value = asked;
  document.body.addEventListener("htmx:configRequest", function (event) {
    if (event.detail.target && event.detail.target.id === "reportBody") {
      const words = search.value.trim();
      if (words) event.detail.parameters.q = words;
      else delete event.detail.parameters.q;
    }
  });
  let waiting = null;
  search.addEventListener("input", function () {
    clearTimeout(waiting);
    waiting = setTimeout(function () { htmx.trigger("#periodFilter", "submit"); }, 400);
  });
})();
