(function () {
  var episodeId = window.PODSCRIBER_EPISODE_ID;
  var progressFill = document.getElementById("progress-fill");
  var errorBox = document.getElementById("error-box");
  var queueBox = document.getElementById("queue-box");
  var stepRows = Array.prototype.slice.call(document.querySelectorAll("#steps [data-step]"));
  var stepKeys = stepRows.map(function (row) { return row.getAttribute("data-step"); });

  var doneSvg = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M5 13l4 4L19 7"></path></svg>';

  function render(payload) {
    queueBox.style.display = payload.status === "pending" ? "block" : "none";
    progressFill.style.width = (payload.progress_pct || 0) + "%";
    var currentIdx = stepKeys.indexOf(payload.current_step);

    stepRows.forEach(function (row, i) {
      var icon = row.querySelector("[data-icon]");
      var label = row.querySelector("[data-label]");
      icon.classList.remove("done", "current", "pending");
      label.classList.remove("current", "pending");

      var isDone = payload.status === "done" || i < currentIdx || (i === currentIdx && payload.status === "done");
      if (isDone) {
        icon.classList.add("done");
        icon.innerHTML = doneSvg;
      } else if (i === currentIdx && payload.status !== "error") {
        icon.classList.add("current");
        icon.innerHTML = "";
        label.classList.add("current");
      } else {
        icon.classList.add("pending");
        icon.innerHTML = "";
        label.classList.add("pending");
      }
    });

    if (payload.status === "error") {
      errorBox.textContent = "Something went wrong: " + (payload.error_message || "unknown error") +
        ". Check Settings and try uploading again.";
      errorBox.style.display = "block";
    }

    if (payload.status === "done") {
      setTimeout(function () {
        window.location.href = "/episodes/" + episodeId;
      }, 500);
    }
  }

  var source = PS.streamStatus("/episodes/" + episodeId + "/status/stream", render);
  source.onerror = function () {
    // Connection dropped; the browser will retry automatically unless we've already closed it.
  };
})();
