/* ==========================================================================
   billing.js — the payment form on a bill (billing/_payment_box.html).

   1. "Split: 2 modes" shows the second payment; cash shows "Cash given",
      card / UPI / online show "Reference" (for each payment)
   2. Split: the second amount fills itself with the rest of the balance
   3. "Full balance" puts the balance (or, split, what is left) in the amount
   4. Cash: the change to return is worked out while typing (never stored)

   The box is replaced after every payment (HTMX), so everything listens on
   the document and runs again after each swap.
   ========================================================================== */

(function () {
  function payForm() {
    return document.getElementById("payForm");
  }

  function balance() {
    const box = document.getElementById("payBox");
    return box ? parseFloat(box.dataset.balance) || 0 : 0;
  }

  function modeOf(form, name) {
    const checked = form.querySelector("input[name=" + name + "]:checked");
    return checked ? checked.value : "";
  }

  function isSplit(form) {
    return Boolean(form.elements.split && form.elements.split.checked);
  }

  function number(input) {
    return input ? parseFloat(input.value) || 0 : 0;
  }

  function rupees(value) {
    return "₹" + value.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  /* 1. show the parts that fit the choices */
  function showParts() {
    const form = payForm();
    if (!form) return;
    const split = isSplit(form);
    const mode1 = modeOf(form, "mode");
    const mode2 = modeOf(form, "mode2");
    form.classList.toggle("is-split", split); // CSS shows [data-split-only], hides [data-split-hide]
    form.querySelector('[data-ref-only="1"]').hidden = mode1 === "CASH";
    form.querySelector('[data-ref-only="2"]').hidden = mode2 === "CASH";
    form.querySelector("[data-cash-only]").hidden = !(mode1 === "CASH" || (split && mode2 === "CASH"));
    showSums();
  }

  /* 2. the second amount = the rest of the balance */
  function fillRest() {
    const form = payForm();
    if (!form || !isSplit(form)) return;
    const rest = Math.max(balance() - number(form.elements.amount), 0);
    form.elements.amount2.value = rest ? rest.toFixed(2) : "";
  }

  /* 4. change = cash given - the cash part; and the split total */
  function showSums() {
    const form = payForm();
    if (!form) return;
    const split = isSplit(form);
    const amount1 = number(form.elements.amount);
    const amount2 = split ? number(form.elements.amount2) : 0;

    const total = document.getElementById("splitTotal");
    if (total) {
      total.textContent = rupees(amount1 + amount2);
      total.classList.toggle("text-danger", amount1 + amount2 > balance() + 0.001);
    }

    const hint = document.getElementById("changeHint");
    if (!hint) return;
    let cash = 0;
    if (modeOf(form, "mode") === "CASH") cash = amount1;
    else if (split && modeOf(form, "mode2") === "CASH") cash = amount2;
    const given = number(form.elements.tendered);
    hint.classList.remove("change-live", "text-danger");
    if (!given) {
      hint.textContent = "Optional. Shows the change to return.";
    } else if (given < cash) {
      hint.textContent = "Cash given is less than the cash amount.";
      hint.classList.add("text-danger");
    } else {
      hint.textContent = "Return " + rupees(given - cash) + " change";
      hint.classList.add("change-live");
    }
  }

  document.addEventListener("change", function (event) {
    if (!event.target.closest("#payForm")) return;
    if (event.target.name === "split") fillRest();
    if (["mode", "mode2", "split"].indexOf(event.target.name) !== -1) showParts();
  });
  document.addEventListener("input", function (event) {
    if (!event.target.closest("#payForm")) return;
    if (event.target.name === "amount") fillRest();
    showSums();
  });

  /* 3. Full balance (split: what the second payment leaves) */
  document.addEventListener("click", function (event) {
    if (!event.target.closest("[data-fill-balance]")) return;
    const form = payForm();
    const left = isSplit(form) ? Math.max(balance() - number(form.elements.amount2), 0) : balance();
    form.elements.amount.value = left.toFixed(2);
    showSums();
  });

  showParts();
  document.body.addEventListener("htmx:afterSettle", showParts);
})();
