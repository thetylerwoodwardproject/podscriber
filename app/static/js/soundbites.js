(function () {
  var playIcon = '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M7 5.5v13a1 1 0 001.5.87l11-6.5a1 1 0 000-1.74l-11-6.5A1 1 0 007 5.5z"></path></svg>';
  var pauseIcon = '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="5" width="4" height="14" rx="1"></rect><rect x="14" y="5" width="4" height="14" rx="1"></rect></svg>';

  var buttons = Array.prototype.slice.call(document.querySelectorAll("[data-play-btn]"));
  if (!buttons.length) return;

  var currentAudio = null;
  var currentBtn = null;

  function stopCurrent() {
    if (currentAudio) {
      currentAudio.pause();
      currentAudio.currentTime = 0;
    }
    if (currentBtn) {
      currentBtn.querySelector("[data-play-icon]").outerHTML = playIcon.replace("<svg", '<svg data-play-icon');
    }
    currentAudio = null;
    currentBtn = null;
  }

  buttons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      var src = btn.getAttribute("data-src");
      if (currentBtn === btn) {
        stopCurrent();
        return;
      }
      stopCurrent();
      var audio = new Audio(src);
      audio.play().catch(function () {});
      audio.addEventListener("ended", stopCurrent);
      btn.querySelector("[data-play-icon]").outerHTML = pauseIcon.replace("<svg", '<svg data-play-icon');
      currentAudio = audio;
      currentBtn = btn;
    });
  });

  // --- Video variant picker ("Video 1"/"Video 2" dropdown + Edit) ---
  Array.prototype.slice.call(document.querySelectorAll(".video-variant-edit-btn")).forEach(function (btn) {
    btn.addEventListener("click", function () {
      var select = btn.parentElement.querySelector(".video-variant-select");
      var opt = select && select.options[select.selectedIndex];
      if (opt) window.location.href = opt.getAttribute("data-url");
    });
  });

  // --- Bulk "export selected" ---
  var selectAllCb = document.getElementById("select-all-soundbites");
  var exportSelectedBtn = document.getElementById("export-selected-btn");
  var exportSelectedStatus = document.getElementById("export-selected-status");
  var checkboxes = Array.prototype.slice.call(document.querySelectorAll(".soundbite-checkbox"));

  function updateExportBtnState() {
    if (!exportSelectedBtn) return;
    exportSelectedBtn.disabled = !checkboxes.some(function (cb) { return cb.checked; });
  }
  checkboxes.forEach(function (cb) { cb.addEventListener("change", updateExportBtnState); });
  if (selectAllCb) {
    selectAllCb.addEventListener("change", function () {
      checkboxes.forEach(function (cb) { cb.checked = selectAllCb.checked; });
      updateExportBtnState();
    });
  }

  if (exportSelectedBtn) {
    exportSelectedBtn.addEventListener("click", function () {
      var ids = checkboxes.filter(function (cb) { return cb.checked; }).map(function (cb) { return parseInt(cb.value, 10); });
      if (!ids.length) return;
      var episodeId = exportSelectedBtn.getAttribute("data-episode-id");
      exportSelectedBtn.disabled = true;
      exportSelectedStatus.textContent = "Starting " + ids.length + " export" + (ids.length > 1 ? "s" : "") + "…";

      fetch("/episodes/" + episodeId + "/soundbites/video/export-selected", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ soundbite_ids: ids }),
      })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          var jobs = data.jobs || [];
          if (!jobs.length) {
            exportSelectedStatus.textContent = "Nothing to export.";
            exportSelectedBtn.disabled = false;
            return;
          }
          var remaining = jobs.length;
          var failed = 0;
          jobs.forEach(function (j) {
            var statusEl = document.querySelector('.soundbite-export-status[data-soundbite-id="' + j.soundbite_id + '"]');
            if (statusEl) statusEl.textContent = "Queued…";
            PS.streamStatus(
              "/episodes/" + episodeId + "/soundbites/" + j.soundbite_id + "/video/" + j.clip_id + "/status/stream",
              function (payload) {
                if (statusEl) {
                  if (payload.status === "running") statusEl.textContent = "Exporting… " + (payload.progress_pct || 0) + "%";
                  else if (payload.status === "done") statusEl.textContent = "Done";
                  else if (payload.status === "error") statusEl.textContent = "Failed";
                }
                if (payload.status === "done" || payload.status === "error") {
                  remaining -= 1;
                  if (payload.status === "error") failed += 1;
                  if (remaining === 0) {
                    exportSelectedStatus.textContent = failed
                      ? (jobs.length - failed) + "/" + jobs.length + " exported (" + failed + " failed)"
                      : "All " + jobs.length + " exported.";
                    exportSelectedBtn.disabled = false;
                  }
                }
              }
            );
          });
        });
    });
  }
})();
