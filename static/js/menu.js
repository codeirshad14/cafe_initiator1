/* ==========================================================================
   menu.js — the guest menu (QR ordering menu, public menu, dish page).

   1. Category tabs: tap to jump to a category; the tab of the category on
      screen is underlined while scrolling.
   2. Search and All / Veg / Non-veg hide the dishes that do not match.
   3. Dish details sheet: HTMX puts it in #sheet; this opens it (slides up),
      closes it (×, backdrop, Esc, or "closeSheet" after adding), and keeps
      the page behind it still.
   4. In the details: − / + quantity and the size change the "Add ₹598" total.
   5. Public menu slider: moves on by itself every 4 s, swipe or tap a dot;
      it waits while touched, hidden, or when the phone asks for less motion.
   Adding to the cart is HTMX, not this file.
   ========================================================================== */

(function () {
  /* ---------------------------------------------------------------- 1. tabs */
  const bar = document.getElementById("menuBar");
  const board = document.getElementById("menuBoard");
  const tabs = Array.from(document.querySelectorAll("[data-chip]"));
  const sections = board ? Array.from(board.querySelectorAll("[data-section]")) : [];

  function lightTab(sectionId) {
    tabs.forEach(function (tab) {
      const on = tab.dataset.chip === sectionId;
      tab.classList.toggle("is-active", on);
      if (on) {
        const nav = tab.parentElement;
        nav.scrollTo({ left: tab.offsetLeft - nav.clientWidth / 2 + tab.clientWidth / 2, behavior: "smooth" });
      }
    });
  }

  tabs.forEach(function (tab) {
    tab.addEventListener("click", function (event) {
      event.preventDefault();
      const target = document.getElementById(tab.dataset.chip);
      if (!target || target.hidden) return;
      const offset = (bar ? bar.offsetHeight : 0) + 6;
      window.scrollTo({ top: target.getBoundingClientRect().top + window.scrollY - offset, behavior: "smooth" });
      lightTab(tab.dataset.chip);
    });
  });

  if ("IntersectionObserver" in window && sections.length) {
    const watcher = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) lightTab(entry.target.id);
      });
    }, { rootMargin: "-130px 0px -60% 0px" });
    sections.forEach(function (section) { watcher.observe(section); });
  }

  /* ------------------------------------------------- 2. search + food type */
  const search = document.getElementById("dishSearch");
  const dietButtons = Array.from(document.querySelectorAll("[data-diet]"));
  const noMatch = document.getElementById("noMatch");
  const clearButton = document.getElementById("clearFilters");
  let diet = "all";

  function applyFilters() {
    const words = search ? search.value.trim().toLowerCase() : "";
    let shown = 0;
    sections.forEach(function (section) {
      let anyShown = false;
      section.querySelectorAll(".gm-dish").forEach(function (dish) {
        const ok = (!words || dish.dataset.name.includes(words)) && (diet === "all" || dish.dataset.food === diet);
        dish.hidden = !ok;
        if (ok) {
          anyShown = true;
          shown += 1;
        }
      });
      section.hidden = !anyShown;
    });
    tabs.forEach(function (tab) {
      const section = document.getElementById(tab.dataset.chip);
      tab.hidden = section ? section.hidden : false;
    });
    if (noMatch) noMatch.hidden = shown > 0;
  }

  function pressDiet(button) {
    diet = button.dataset.diet;
    dietButtons.forEach(function (other) {
      other.classList.toggle("is-active", other === button);
      other.setAttribute("aria-pressed", other === button ? "true" : "false");
    });
  }

  if (search) search.addEventListener("input", applyFilters);
  dietButtons.forEach(function (button) {
    button.addEventListener("click", function () {
      pressDiet(button);
      applyFilters();
    });
  });
  if (clearButton) {
    clearButton.addEventListener("click", function () {
      if (search) search.value = "";
      if (dietButtons.length) pressDiet(dietButtons[0]);
      applyFilters();
    });
  }

  /* ----------------------------------------------------- 3. details sheet */
  const sheetBox = document.getElementById("sheet");
  let lastFocus = null;

  function openSheet() {
    const sheet = sheetBox.querySelector(".gm-sheet");
    if (!sheet) return;
    document.body.classList.add("gm-sheet-open");
    requestAnimationFrame(function () { sheet.classList.add("is-open"); });
    const first = sheet.querySelector("[data-sheet-close], button, a");
    if (first) first.focus({ preventScroll: true });
    updateTotal(sheet.querySelector("[data-dish-form]"));
  }

  function closeSheet() {
    const sheet = sheetBox && sheetBox.querySelector(".gm-sheet");
    if (!sheet) return;
    sheet.classList.remove("is-open");
    document.body.classList.remove("gm-sheet-open");
    setTimeout(function () { sheetBox.innerHTML = ""; }, 260);
    if (lastFocus) lastFocus.focus({ preventScroll: true });
  }

  if (sheetBox) {
    document.body.addEventListener("htmx:beforeRequest", function (event) {
      if (event.detail.target === sheetBox) lastFocus = document.activeElement;
    });
    document.body.addEventListener("htmx:afterSwap", function (event) {
      if (event.detail.target === sheetBox) openSheet();
    });
    document.body.addEventListener("closeSheet", function () {
      setTimeout(closeSheet, 0);
    });
    document.addEventListener("click", function (event) {
      if (event.target.closest("[data-sheet-close]") && sheetBox.querySelector(".gm-sheet")) {
        event.preventDefault();
        closeSheet();
      }
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") closeSheet();
    });
  }

  /* ------------------------------------------- 4. quantity + live total */
  function rupees(value) {
    return "₹" + value.toLocaleString("en-IN", { maximumFractionDigits: 2 });
  }

  function updateTotal(form) {
    if (!form) return;
    const qty = parseInt(form.elements.qty.value, 10) || 1;
    const size = form.querySelector("input[name=portion]:checked");
    const base = form.querySelector("[data-base-price]");
    const price = parseFloat(size ? size.dataset.price : base ? base.dataset.basePrice : 0) || 0;
    const total = form.querySelector("[data-total]");
    if (total) total.textContent = rupees(price * qty);
  }

  document.addEventListener("click", function (event) {
    const step = event.target.closest("[data-qty-step]");
    if (!step) return;
    const form = step.closest("[data-dish-form]");
    const input = form.elements.qty;
    const next = (parseInt(input.value, 10) || 1) + Number(step.dataset.qtyStep);
    input.value = Math.max(1, Math.min(20, next));
    updateTotal(form);
  });

  document.addEventListener("change", function (event) {
    if (event.target.matches("[data-dish-form] input[name=portion]")) {
      updateTotal(event.target.closest("[data-dish-form]"));
    }
  });

  // a dish page of its own (no sheet): show its total straight away
  document.querySelectorAll("[data-dish-form]").forEach(updateTotal);

  /* ------------------------------------------------------------ 5. slider */
  document.querySelectorAll("[data-slider]").forEach(function (slider) {
    const track = slider.querySelector("[data-slides]");
    const slides = Array.from(track.children);
    const dots = Array.from(slider.querySelectorAll("[data-slide-to]"));
    if (slides.length < 2) return;

    const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let current = 0;
    let timer = null;

    function show(index) {
      current = (index + slides.length) % slides.length;
      track.scrollTo({ left: slides[current].offsetLeft, behavior: calm ? "auto" : "smooth" });
    }

    function lightDot(index) {
      current = index;
      dots.forEach(function (dot, i) {
        dot.classList.toggle("is-active", i === index);
        if (i === index) dot.setAttribute("aria-current", "true");
        else dot.removeAttribute("aria-current");
      });
    }

    function play() {
      stop();
      if (!calm && !document.hidden) timer = setInterval(function () { show(current + 1); }, 4000);
    }

    function stop() {
      clearInterval(timer);
      timer = null;
    }

    // the dot follows the slide on screen, however it got there (auto, swipe, dot)
    track.addEventListener("scroll", function () {
      const index = Math.round(track.scrollLeft / track.clientWidth);
      if (index !== current && slides[index]) lightDot(index);
    }, { passive: true });

    dots.forEach(function (dot) {
      dot.addEventListener("click", function () {
        show(Number(dot.dataset.slideTo));
        play();  // start the 4 s again from this slide
      });
    });

    // wait while the guest is touching it (or a mouse is over it), then carry on
    ["pointerdown", "focusin"].forEach(function (name) { slider.addEventListener(name, stop); });
    ["pointerup", "pointercancel", "focusout"].forEach(function (name) { slider.addEventListener(name, play); });
    slider.addEventListener("pointerenter", function (event) { if (event.pointerType === "mouse") stop(); });
    slider.addEventListener("pointerleave", function (event) { if (event.pointerType === "mouse") play(); });
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) stop(); else play();
    });

    play();
  });
})();
