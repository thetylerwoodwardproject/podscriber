(function () {
  var toggle = document.getElementById("dark-mode-toggle");
  if (!toggle) return;
  toggle.addEventListener("click", function () {
    var root = document.documentElement;
    var current = root.getAttribute("data-theme") === "dark" ? "dark" : "light";
    var next = current === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    localStorage.setItem("podscriber-theme", next);
  });
})();

(function () {
  var toggle = document.getElementById("sidebar-toggle");
  var overlay = document.getElementById("sidebar-overlay");
  if (!toggle || !overlay) return;
  function setOpen(open) {
    document.body.classList.toggle("sidebar-open", open);
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
  }
  toggle.addEventListener("click", function () {
    setOpen(!document.body.classList.contains("sidebar-open"));
  });
  overlay.addEventListener("click", function () { setOpen(false); });
})();

// Shared AJAX-form helpers, available on every page (this file is loaded from base.html).
// Forms marked data-ajax are submitted via fetch instead of a normal navigation, and the
// JSON response drives a small, declarative DOM patch — see data-ajax-on-success below.
window.PS = window.PS || {};

(function () {
  "use strict";

  PS.flashSaved = function (anchorEl, text) {
    if (!anchorEl) return;
    var flash = anchorEl.nextElementSibling;
    if (!flash || !flash.classList.contains("ps-saved-flash")) {
      flash = document.createElement("span");
      flash.className = "ps-saved-flash";
      anchorEl.insertAdjacentElement("afterend", flash);
    }
    flash.textContent = text || "Saved";
    // Restart the CSS animation even if it's already mid-flash.
    flash.classList.remove("ps-saved-flash-show");
    // eslint-disable-next-line no-unused-expressions
    flash.offsetWidth;
    flash.classList.add("ps-saved-flash-show");
  };

  PS.copyToClipboard = function (field) {
    if (window.isSecureContext && navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(field.value);
    }
    // navigator.clipboard requires a secure context (https:// or localhost) — it's undefined
    // when testing over plain http:// from a phone on the LAN, which silently breaks copy
    // buttons with no error. Fall back to the older select()+execCommand path, which still
    // works there.
    field.focus();
    field.select();
    try {
      document.execCommand("copy");
    } catch (err) {
      // best effort — the text is still selected for a manual copy either way
    }
    return Promise.resolve();
  };

  PS.showInlineError = function (container, message) {
    if (!container) return;
    var banner = container.querySelector(":scope > .ps-inline-error");
    if (!banner) {
      banner = document.createElement("div");
      banner.className = "error-banner ps-inline-error";
      container.appendChild(banner);
    }
    banner.textContent = message;
  };

  PS.clearInlineError = function (container) {
    if (!container) return;
    var banner = container.querySelector(":scope > .ps-inline-error");
    if (banner) banner.remove();
  };

  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (!(form instanceof HTMLFormElement) || !form.hasAttribute("data-ajax")) return;
    e.preventDefault();

    var submitter = e.submitter;
    var url = (submitter && submitter.getAttribute("formaction")) || form.action;
    var method = ((submitter && submitter.getAttribute("formmethod")) || form.method || "POST").toUpperCase();
    var body = new FormData(form, submitter || undefined);

    if (submitter) submitter.disabled = true;
    PS.clearInlineError(form);

    fetch(url, { method: method, body: body })
      .then(function (res) {
        return res.json().catch(function () { return null; }).then(function (data) {
          if (!res.ok) {
            var message = (data && data.detail) || ("Request failed (" + res.status + ")");
            throw new Error(message);
          }
          return data;
        });
      })
      .then(function (data) {
        if (submitter) submitter.disabled = false;
        var mode = form.getAttribute("data-ajax-on-success") || "flash";
        if (mode === "flash") {
          var flashSel = form.getAttribute("data-ajax-flash-target");
          var target = (flashSel && form.querySelector(flashSel)) || form.querySelector("button[type=submit]") || form;
          PS.flashSaved(target);
        } else if (mode === "remove") {
          var removeSel = form.getAttribute("data-ajax-remove");
          var el = removeSel ? form.closest(removeSel) : null;
          if (el) el.remove();
        } else if (mode === "set-class") {
          var setSel = form.getAttribute("data-ajax-set-target");
          var setEl = setSel ? (form.querySelector(setSel) || form.closest(setSel)) : null;
          var field = form.getAttribute("data-ajax-set-field");
          var cls = form.getAttribute("data-ajax-set-class");
          if (setEl && field && cls) setEl.classList.toggle(cls, !!(data && data[field]));
        }
        form.dispatchEvent(new CustomEvent("ps:ajax-success", { bubbles: true, detail: { data: data } }));
      })
      .catch(function (err) {
        if (submitter) submitter.disabled = false;
        PS.showInlineError(form, err.message);
        form.dispatchEvent(new CustomEvent("ps:ajax-error", { bubbles: true, detail: { error: err } }));
      });
  });
})();
