/* ==========================================================================
   waiter.js — the staff POS screen (orders/waiter_order.html).

   1. Categories: tap one to see only its dishes ("All items" shows every one)
   2. Search box and "Veg only" hide the dishes that do not match
   3. Choosing Delivery opens "Guest details" (name, mobile, address are needed)
   4. Phones: the bottom "Review & send" bar hides while the bill is on screen
   (Adding dishes is HTMX; the order-type parts and the single send are in app.js.)
   ========================================================================== */

(function () {
  const chips = Array.from(document.querySelectorAll("[data-chip]"));
  const sections = Array.from(document.querySelectorAll("[data-section]"));
  const search = document.getElementById("dishSearch");
  const vegOnly = document.getElementById("vegOnly");
  const noMatch = document.getElementById("noMatch");
  const menu = document.querySelector(".pos-menu");
  let category = "all";

  /* ------------------------------- 1 + 2. which dishes are on screen */
  function applyFilters() {
    const words = search ? search.value.trim().toLowerCase() : "";
    const veg = vegOnly ? vegOnly.checked : false;
    let sectionsShown = 0;

    sections.forEach(function (section) {
      // a search looks through every category
      const inCategory = words || category === "all" || section.id === category;
      let anyShown = false;
      section.querySelectorAll("[data-dish]").forEach(function (dish) {
        const matches = (!words || dish.dataset.name.includes(words)) && (!veg || dish.dataset.food === "VEG");
        dish.hidden = !matches;
        if (matches) anyShown = true;
      });
      section.hidden = !(inCategory && anyShown);
      if (!section.hidden) sectionsShown += 1;
    });
    if (noMatch) noMatch.hidden = sectionsShown > 0;
  }

  function pickCategory(chip) {
    category = chip.dataset.chip;
    chips.forEach(function (other) {
      other.classList.toggle("is-active", other === chip);
      other.setAttribute("aria-pressed", other === chip ? "true" : "false");
    });
    // the chip row on smaller screens: slide it so the picked chip is in view
    chip.scrollIntoView({ block: "nearest", inline: "center", behavior: "smooth" });
    if (search) search.value = "";
    applyFilters();
    // scrolled far down a long list? start the new category from its top
    if (menu && menu.getBoundingClientRect().top < 0) menu.scrollIntoView({ block: "start" });
  }

  chips.forEach(function (chip) {
    chip.setAttribute("aria-pressed", chip.classList.contains("is-active") ? "true" : "false");
    chip.addEventListener("click", function () { pickCategory(chip); });
  });
  if (search) search.addEventListener("input", applyFilters);
  if (vegOnly) vegOnly.addEventListener("change", applyFilters);

  /* ------------------------------ 3. Delivery opens the guest details */
  const guest = document.getElementById("guestDetails");
  document.addEventListener("change", function (event) {
    if (guest && event.target.name === "order_type" && event.target.value === "DELIVERY") guest.open = true;
  });

  /* ---------- 4. phones: hide the "Review & send" bar while the bill is on screen */
  const bill = document.getElementById("waiterSummaryBox");
  if (bill && "IntersectionObserver" in window) {
    new IntersectionObserver(function (entries) {
      document.body.classList.toggle("pos-bill-in-view", entries[0].isIntersecting);
    }).observe(bill);
  }
})();
