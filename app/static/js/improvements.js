(function () {
  var content = document.getElementById("improvements-content");

  // --- Refresh (re-fetches the back catalog from PodcastIndex) ---
  var refreshForm = document.getElementById("improvements-refresh-form");
  if (refreshForm) {
    var refreshBtn = refreshForm.querySelector("button[type=submit]");
    refreshForm.addEventListener("submit", function (e) {
      e.preventDefault();
      PS.clearInlineError(refreshForm);
      refreshBtn.disabled = true;
      fetch(refreshForm.action, { method: "POST" })
        .then(function (res) {
          return res.text().then(function (html) {
            if (!res.ok) throw new Error("Refresh failed");
            return html;
          });
        })
        .then(function (html) {
          content.innerHTML = html;
          PS.flashSaved(refreshBtn, "Refreshed");
        })
        .catch(function (err) {
          PS.showInlineError(refreshForm, err.message);
        })
        .finally(function () {
          refreshBtn.disabled = false;
        });
    });
  }

  // --- Per-episode "Suggest improvements" / "Regenerate" ---
  content.addEventListener("click", function (e) {
    var btn = e.target.closest(".js-suggest-btn");
    if (!btn) return;
    var row = btn.closest(".improvement-row");
    var col = row.querySelector(".improvement-col-ai");
    var suggestionCol = col.querySelector(".js-suggestion-col");
    var status = btn.parentElement.querySelector(".js-suggest-status");
    var key = btn.getAttribute("data-episode-key");
    btn.disabled = true;
    if (status) status.style.display = "inline-flex";
    PS.clearInlineError(col);

    fetch("/improvements/suggest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ episode_key: key }),
    })
      .then(function (res) {
        return res.text().then(function (html) {
          if (!res.ok) {
            var data = null;
            try { data = JSON.parse(html); } catch (parseErr) { /* not JSON */ }
            throw new Error((data && data.detail) || "Couldn't generate a suggestion.");
          }
          return html;
        });
      })
      .then(function (html) {
        // Server-rendered fragment replaces the whole column: one source of truth for the
        // "has a suggestion" vs. "still empty" markup, and it comes back already showing
        // the non-busy Regenerate state, so there's nothing left to patch by hand here.
        suggestionCol.innerHTML = html;
      })
      .catch(function (err) {
        PS.showInlineError(col, err.message);
        btn.disabled = false;
        if (status) status.style.display = "none";
      });
  });

  // --- Per-episode "Suggest using transcript" (download + transcribe + suggest, background job) ---
  var deepStepLabels = {
    downloading: "Downloading audio…",
    transcribing: "Transcribing…",
    suggesting: "Generating suggestion…",
  };

  content.addEventListener("click", function (e) {
    var btn = e.target.closest(".js-suggest-deep-btn");
    if (!btn) return;
    var row = btn.closest(".improvement-row");
    var col = row.querySelector(".improvement-col-ai");
    var suggestionCol = col.querySelector(".js-suggestion-col");
    var status = btn.parentElement.querySelector(".js-suggest-deep-status");
    var stepText = status ? status.querySelector(".js-suggest-deep-step") : null;
    var key = btn.getAttribute("data-episode-key");
    btn.disabled = true;
    if (status) status.style.display = "inline-flex";
    if (stepText) stepText.textContent = "Starting…";
    PS.clearInlineError(col);

    fetch("/improvements/suggest-deep", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ episode_key: key }),
    })
      .then(function (res) {
        return res.text().then(function (text) {
          if (!res.ok) {
            var data = null;
            try { data = JSON.parse(text); } catch (parseErr) { /* not JSON */ }
            throw new Error((data && data.detail) || "Couldn't start the job.");
          }
          return JSON.parse(text);
        });
      })
      .then(function (data) {
        var source = new EventSource("/improvements/suggest-deep/status/stream?job_id=" + data.job_id);
        source.onmessage = function (evt) {
          var payload = JSON.parse(evt.data);
          if (stepText && payload.status === "running" && payload.current_step) {
            stepText.textContent = deepStepLabels[payload.current_step] || payload.current_step;
          }
          if (payload.status === "done") {
            source.close();
            fetch("/improvements/suggest-deep/result?key=" + encodeURIComponent(key))
              .then(function (r) { return r.text(); })
              .then(function (html) {
                suggestionCol.innerHTML = html;
              });
          } else if (payload.status === "error") {
            source.close();
            PS.showInlineError(col, payload.error_message || "Couldn't finish the job.");
            btn.disabled = false;
            if (status) status.style.display = "none";
          }
        };
      })
      .catch(function (err) {
        PS.showInlineError(col, err.message);
        btn.disabled = false;
        if (status) status.style.display = "none";
      });
  });

  // --- Copy title / description to clipboard ---
  content.addEventListener("click", function (e) {
    var copyBtn = e.target.closest(".js-copy-btn");
    if (!copyBtn) return;
    var col = copyBtn.closest(".improvement-col-ai");
    var fieldSelector = copyBtn.getAttribute("data-copy-target") === "title" ? ".js-suggested-title" : ".js-suggested-description";
    var field = col.querySelector(fieldSelector);
    if (!field) return;
    PS.copyToClipboard(field);
    var original = copyBtn.innerHTML;
    copyBtn.textContent = "Copied!";
    setTimeout(function () { copyBtn.innerHTML = original; }, 1200);
  });

  // --- Bulk "Generate all missing suggestions" ---
  var generateAllBtn = document.getElementById("generate-all-btn");
  if (!generateAllBtn) return;
  var progressTrack = document.getElementById("generate-all-progress");
  var progressFill = progressTrack.querySelector(".progress-fill");
  var statusText = document.getElementById("generate-all-status");

  generateAllBtn.addEventListener("click", function () {
    generateAllBtn.disabled = true;
    progressTrack.style.display = "block";
    progressFill.style.width = "0%";
    statusText.textContent = "Starting…";

    fetch("/improvements/generate-all", { method: "POST" })
      .then(function (r) { return r.json(); })
      .then(function () {
        var source = new EventSource("/improvements/generate-all/status/stream");
        source.onmessage = function (evt) {
          var payload = JSON.parse(evt.data);
          progressFill.style.width = (payload.progress_pct || 0) + "%";
          if (payload.status === "running" && payload.current_step) {
            statusText.textContent = "Suggesting " + payload.current_step;
          }
          if (payload.status === "done") {
            source.close();
            statusText.textContent = "Done.";
            fetch("/improvements/rows-fragment")
              .then(function (r) { return r.text(); })
              .then(function (html) {
                content.innerHTML = html;
                generateAllBtn.disabled = false;
                progressTrack.style.display = "none";
              });
          } else if (payload.status === "error") {
            source.close();
            statusText.textContent = "Couldn't finish: " + (payload.error_message || "unknown error");
            generateAllBtn.disabled = false;
          }
        };
      });
  });
})();
