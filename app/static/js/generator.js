(function () {
  var copyBtn = document.getElementById("copy-script-btn");
  if (copyBtn) {
    copyBtn.addEventListener("click", function () {
      var text = document.getElementById("script-text").textContent;
      navigator.clipboard.writeText(text).then(function () {
        var original = copyBtn.textContent;
        copyBtn.textContent = "Copied";
        setTimeout(function () { copyBtn.textContent = original; }, 1500);
      });
    });
  }

  if (!window.PODSCRIBER_IN_PROGRESS) return;

  var scriptId = window.PODSCRIBER_SCRIPT_ID;
  var progressBox = document.getElementById("progress-box");
  var errorBox = document.getElementById("error-box");
  var errorMessage = document.getElementById("error-message");

  var source = new EventSource("/generator/" + scriptId + "/status/stream");
  source.onmessage = function (evt) {
    var payload = JSON.parse(evt.data);
    if (payload.status === "done") {
      source.close();
      window.location.reload();
    } else if (payload.status === "error") {
      source.close();
      progressBox.style.display = "none";
      errorMessage.textContent = payload.error_message || "unknown error";
      errorBox.style.display = "block";
    }
  };
})();
