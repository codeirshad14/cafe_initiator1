/* ==========================================================================
   filter.js — the search box of a filter row (partials/_period_filter.html),
   on the Floor and the Bookings page.

   Typing hides the items ([data-search]) of its live block that do not match,
   and a group ([data-search-group], e.g. a section of tables or a day) with
   none left. The block redraws itself now and then (HTMX), so the search runs
   again after every redraw. (The Today / This week / ... buttons are plain HTMX.)
   ========================================================================== */

(function () {
  const boxes = Array.from(document.querySelectorAll("[data-search-in]"));
  if (!boxes.length) return;

  function applySearch(input) {
    const area = document.querySelector(input.dataset.searchIn);
    if (!area) return;
    const words = input.value.trim().toLowerCase();
    area.querySelectorAll("[data-search]").forEach(function (item) {
      item.hidden = Boolean(words) && !item.dataset.search.includes(words);
    });
    area.querySelectorAll("[data-search-group]").forEach(function (group) {
      const items = Array.from(group.querySelectorAll("[data-search]"));
      if (items.length) group.hidden = items.every(function (item) { return item.hidden; });
    });
  }

  boxes.forEach(function (input) {
    input.addEventListener("input", function () { applySearch(input); });
  });
  document.body.addEventListener("htmx:afterSettle", function () { boxes.forEach(applySearch); });
})();
