/* ==========================================================================
   app.js — small helpers for every page (staff and guest). Plain JavaScript,
   no framework. Each part works through an HTML attribute, so a template
   switches it on just by adding that attribute. (One fixed colour theme:
   there is no light / dark switching.)

   1. Side panel: opens when HTMX puts a form in #panel, closes on "closePanel"
   2. Messages (toasts): Django's and the "showMessage" event from the server
   3. HTMX errors become a friendly message instead of doing nothing
   4. Copy-link buttons                                 data-copy="text"
   5. Dish form: fill portion names                     data-fill-portions="Qtr,Half,Full"
   6. Parts that follow the chosen order type           data-show-for="TAKEAWAY DELIVERY"
   7. Fold the staff menu to icons (desktop)            #navToggle, data-nav-tip="name"
   8. One tap = one order (no double send)              <form data-submit-once>
   9. Booking: "How long" buttons fill "Until"          data-length="30" / "day"
  10. Live screens: another screen's change reloads     <body data-live-url>, hx-trigger="liveChanged from:body"
      the live blocks here at once


   The server talks to this file through the HX-Trigger header, e.g.
     HX-Trigger: {"closePanel": true, "rowsChanged": true,
                  "showMessage": {"text": "Ravi added.", "level": "success"}}
   (see core/utils.py, htmx_saved). HTMX fires each name as an event on <body>.
   ========================================================================== */

(function () {
  /* ------------------------------------------------------- 1. side panel */
  const panelElement = document.getElementById("sidePanel");
  const panelBox = document.getElementById("panel");

  function sidePanel() {
    return bootstrap.Offcanvas.getOrCreateInstance(panelElement);
  }

  function focusFirstField() {
    const field =
      panelBox.querySelector(".has-error input, .has-error select, .has-error textarea") ||
      panelBox.querySelector("input:not([type=hidden]):not([disabled]), select:not([disabled]), textarea");
    if (field) field.focus();
  }

  if (panelElement) {
    // a form (or the same form with errors) has just arrived in #panel
    document.body.addEventListener("htmx:afterSwap", function (event) {
      if (event.detail.target !== panelBox) return;
      if (panelElement.classList.contains("show")) {
        focusFirstField();
      } else {
        sidePanel().show();
      }
    });
    panelElement.addEventListener("shown.bs.offcanvas", focusFirstField);

    // saved: close it. Wait one tick so HTMX can fire the other events first.
    document.body.addEventListener("closePanel", function () {
      setTimeout(function () { sidePanel().hide(); }, 0);
    });

    // empty it once closed, so an old form never flashes up next time
    panelElement.addEventListener("hidden.bs.offcanvas", function () {
      panelBox.innerHTML = "";
    });
  }

  /* --------------------------------------------------------- 2. messages */
  const toastArea = document.getElementById("toastArea");
  const ICONS = {
    success: "bi-check-circle-fill",
    error: "bi-exclamation-octagon-fill",
    warning: "bi-exclamation-triangle-fill",
    info: "bi-info-circle-fill",
  };

  function hideLater(toast) {
    setTimeout(function () {
      toast.classList.add("is-leaving");
      setTimeout(function () { toast.remove(); }, 300);
    }, 4000);
  }

  function showMessage(text, level) {
    if (!toastArea || !text) return;
    level = ICONS[level] ? level : "info";
    const toast = document.createElement("div");
    toast.className = "app-toast app-toast--" + level;
    toast.setAttribute("role", level === "error" ? "alert" : "status");
    const icon = document.createElement("i");
    icon.className = "bi " + ICONS[level];
    icon.setAttribute("aria-hidden", "true");
    const span = document.createElement("span");
    span.textContent = text;
    toast.append(icon, span);
    toastArea.appendChild(toast);
    hideLater(toast);
  }

  // messages Django rendered with the page
  if (toastArea) toastArea.querySelectorAll(".app-toast").forEach(hideLater);

  document.body.addEventListener("showMessage", function (event) {
    showMessage(event.detail.text, event.detail.level);
  });

  /* ------------------------------------------------------- 3. HTMX errors */
  document.body.addEventListener("htmx:responseError", function (event) {
    const status = event.detail.xhr.status;
    const text = {
      403: "You do not have permission to do that.",
      404: "That record no longer exists. Please refresh the page.",
    }[status] || "Something went wrong (error " + status + "). Please try again.";
    showMessage(text, "error");
  });

  document.body.addEventListener("htmx:sendError", function () {
    showMessage("Could not reach the server. Check the connection and try again.", "error");
  });

  /* ------------------------------------------------------ 4. copy a link */
  // <button data-copy="https://...">: copies the text. The clipboard only
  // works on https or localhost, so elsewhere the link is shown to copy by hand.
  document.addEventListener("click", function (event) {
    const button = event.target.closest("[data-copy]");
    if (!button) return;
    const text = button.dataset.copy;
    if (!navigator.clipboard) {
      window.prompt("Copy this link:", text);
      return;
    }
    navigator.clipboard.writeText(text).then(
      function () { showMessage("Link copied.", "success"); },
      function () { window.prompt("Copy this link:", text); }
    );
  });

  /* --------------------------------------- 5. dish form: fill portion names */
  // <button data-fill-portions="Qtr,Half,Full"> puts those names into the
  // empty portion rows of the dish form, in order. Prices stay for the user.
  document.addEventListener("click", function (event) {
    const button = event.target.closest("[data-fill-portions]");
    if (!button) return;
    const names = button.dataset.fillPortions.split(",");
    const form = button.closest("form");
    const empty = Array.from(form.querySelectorAll("[data-portion-name]")).filter(function (input) {
      return !input.value.trim();
    });
    names.forEach(function (name, index) {
      if (empty[index]) empty[index].value = name;
    });
    const firstPrice = empty.length ? empty[0].closest(".portion-row").querySelector("input[type=number]") : null;
    if (firstPrice) firstPrice.focus();
  });

  /* ------------------------------------------- 6. follow the order type */
  // Inside a form with order_type radios (cart, waiter screen), an element with
  // data-show-for="TAKEAWAY DELIVERY" shows only while one of those is chosen.
  function followOrderType(form) {
    const picked = form.querySelector("input[name=order_type]:checked") || form.querySelector("input[name=order_type]");
    const type = picked ? picked.value : "DINE_IN";
    form.querySelectorAll("[data-show-for]").forEach(function (box) {
      box.hidden = box.dataset.showFor.split(" ").indexOf(type) === -1;
    });
  }

  document.querySelectorAll("form").forEach(function (form) {
    if (form.querySelector("[data-show-for]")) followOrderType(form);
  });
  document.addEventListener("change", function (event) {
    if (event.target.name === "order_type" && event.target.form) followOrderType(event.target.form);
  });

  /* -------------------------------------- 7. fold the menu to icons */
  // The top-bar button folds the sidebar down to icons (html.nav-collapsed) and
  // back; the choice is remembered on this computer. While folded (desktop only),
  // every icon with data-nav-tip shows its name in a tooltip on hover or focus.
  const navToggle = document.getElementById("navToggle");
  const desktop = window.matchMedia("(min-width: 992px)");
  const navTips = window.bootstrap ? Array.from(document.querySelectorAll("[data-nav-tip]")).map(function (item) {
    return new bootstrap.Tooltip(item, { title: item.dataset.navTip, placement: "right", trigger: "hover focus" });
  }) : [];

  function showNavState() {
    const folded = document.documentElement.classList.contains("nav-collapsed");
    navTips.forEach(function (tip) {
      if (folded && desktop.matches) {
        tip.enable();
      } else {
        tip.hide();
        tip.disable();
      }
    });
    if (!navToggle) return;
    const label = folded ? "Expand menu" : "Collapse menu";
    navToggle.setAttribute("aria-expanded", folded ? "false" : "true");
    navToggle.setAttribute("aria-label", label);
    navToggle.title = label;
    navToggle.querySelector("i").className = folded ? "bi bi-layout-sidebar" : "bi bi-layout-sidebar-inset";
  }

  showNavState();
  desktop.addEventListener("change", showNavState);  // window resized across 992px
  if (navToggle) {
    navToggle.addEventListener("click", function () {
      const folded = document.documentElement.classList.toggle("nav-collapsed");
      try {
        localStorage.setItem("resto-nav", folded ? "collapsed" : "open");
      } catch (e) {}
      showNavState();
    });
  }

  /* --------------------------------------------- 8. one tap = one order */
  // <form data-submit-once>: after the first tap its submit buttons (also those
  // outside it with form="...") are switched off and say "Sending…".
  document.addEventListener("submit", function (event) {
    const form = event.target;
    if (!form.hasAttribute("data-submit-once")) return;
    const buttons = Array.from(form.querySelectorAll("button[type=submit]"));
    if (form.id) buttons.push.apply(buttons, document.querySelectorAll('button[type=submit][form="' + form.id + '"]'));
    buttons.forEach(function (button) {
      button.disabled = true;
      button.innerHTML = '<span class="spinner-border spinner-border-sm" aria-hidden="true"></span> Sending…';
    });
  });

  /* ----------------------------------------- 9. booking: how long */
  // The booking form (tables/_booking_form.html): a button with data-length
  // ("30" minutes, "2880" = two days, or "day" = to the end of that day)
  // fills "Until" (end_date, end_time) from "From" (date, time).
  function twoDigits(number) {
    return String(number).padStart(2, "0");
  }

  document.addEventListener("click", function (event) {
    const button = event.target.closest("[data-length]");
    if (!button) return;
    const form = button.closest("form");
    const day = form.elements.date.value;
    const time = form.elements.time.value;
    if (!day || !time) {
      (day ? form.elements.time : form.elements.date).focus();
      return;
    }
    const end = button.dataset.length === "day"
      ? new Date(day + "T23:59")
      : new Date(new Date(day + "T" + time).getTime() + Number(button.dataset.length) * 60000);
    form.elements.end_date.value = end.getFullYear() + "-" + twoDigits(end.getMonth() + 1) + "-" + twoDigits(end.getDate());
    form.elements.end_time.value = twoDigits(end.getHours()) + ":" + twoDigits(end.getMinutes());
    form.querySelectorAll("[data-length]").forEach(function (other) {
      other.classList.toggle("is-active", other === button);
    });
  });

  /* ------------------------------------------------- 10. live screens */
  // Every 3 seconds (while the page is in view) ask the restaurant's change
  // number (core/live.py). When it moved, someone somewhere changed an order,
  // KOT, bill, payment or booking: fire "liveChanged" on <body>, and every live
  // block with hx-trigger="... liveChanged from:body" reloads itself.
  const liveUrl = document.body.dataset.liveUrl;
  if (liveUrl) {
    let liveVersion = null;
    const checkLive = function () {
      if (document.hidden) return;
      fetch(liveUrl, { credentials: "same-origin" })
        .then(function (response) { return response.ok ? response.json() : null; })
        .then(function (answer) {
          if (!answer) return;
          if (liveVersion !== null && answer.v !== liveVersion) {
            document.body.dispatchEvent(new CustomEvent("liveChanged"));
          }
          liveVersion = answer.v;
        })
        .catch(function () {});  // offline for a moment: the next check catches up
    };
    checkLive();
    setInterval(checkLive, 3000);
    document.addEventListener("visibilitychange", checkLive);  // back on this tab: at once
  }

})();
