(function () {
  var dropzone = document.getElementById("dropzone");
  var fileInput = document.getElementById("file-input");
  var browseBtn = document.getElementById("browse-btn");
  var fileCard = document.getElementById("file-card");
  var fileNameEl = document.getElementById("file-name");
  var fileMetaEl = document.getElementById("file-meta");
  var startBtn = document.getElementById("start-processing-btn");
  var errorBox = document.getElementById("error-box");
  var stepsCard = document.getElementById("steps-card");
  var selectAllCheckbox = document.getElementById("steps-select-all");
  var stepCheckboxes = Array.prototype.slice.call(document.querySelectorAll(".step-checkbox"));

  var currentEpisodeId = null;

  selectAllCheckbox.addEventListener("change", function () {
    stepCheckboxes.forEach(function (cb) { cb.checked = selectAllCheckbox.checked; });
  });
  stepCheckboxes.forEach(function (cb) {
    cb.addEventListener("change", function () {
      selectAllCheckbox.checked = stepCheckboxes.every(function (c) { return c.checked; });
    });
  });

  function showError(msg) {
    errorBox.textContent = msg;
    errorBox.style.display = "block";
  }

  function clearError() {
    errorBox.style.display = "none";
  }

  function formatBytes(bytes) {
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  function uploadFile(file) {
    clearError();
    startBtn.disabled = true;
    fileCard.style.display = "flex";
    fileNameEl.textContent = file.name;
    fileMetaEl.textContent = "Uploading…";

    var formData = new FormData();
    formData.append("file", file);

    fetch("/episodes", { method: "POST", body: formData })
      .then(function (res) {
        return res.json().then(function (data) {
          if (!res.ok) throw new Error(data.error || "Upload failed");
          return data;
        });
      })
      .then(function (data) {
        currentEpisodeId = data.episode_id;
        fileMetaEl.textContent = formatBytes(data.size_bytes) + " · ready to process";
        startBtn.disabled = false;
        stepsCard.style.display = "block";
      })
      .catch(function (err) {
        fileCard.style.display = "none";
        showError(err.message);
      });
  }

  browseBtn.addEventListener("click", function () { fileInput.click(); });
  fileInput.addEventListener("change", function () {
    if (fileInput.files[0]) uploadFile(fileInput.files[0]);
  });

  ["dragenter", "dragover"].forEach(function (evt) {
    dropzone.addEventListener(evt, function (e) {
      e.preventDefault();
      dropzone.classList.add("dragover");
    });
  });
  ["dragleave", "drop"].forEach(function (evt) {
    dropzone.addEventListener(evt, function (e) {
      e.preventDefault();
      dropzone.classList.remove("dragover");
    });
  });
  dropzone.addEventListener("drop", function (e) {
    var file = e.dataTransfer.files[0];
    if (file) uploadFile(file);
  });

  startBtn.addEventListener("click", function () {
    if (!currentEpisodeId) return;
    startBtn.disabled = true;
    startBtn.textContent = "Starting…";
    var formData = new FormData();
    stepCheckboxes.forEach(function (cb) {
      if (cb.checked) formData.append("steps", cb.value);
    });
    fetch("/episodes/" + currentEpisodeId + "/process", { method: "POST", body: formData }).then(function (res) {
      window.location.href = res.url;
    });
  });
})();
