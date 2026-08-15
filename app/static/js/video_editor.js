(function () {
  var cfg = window.PODSCRIBER_CLIP;
  var base = cfg.base;

  var bgLayer = document.getElementById("bg-layer");
  var uploadHint = document.getElementById("upload-hint");
  var bgFileInput = document.getElementById("bg-file-input");
  var logoFileInput = document.getElementById("logo-file-input");
  var wavesEl = document.getElementById("waveform-bars");

  // --- Waveform bars, seeded from real amplitude data ---
  function renderWaveform(color) {
    wavesEl.innerHTML = "";
    cfg.envelope.forEach(function (v, i) {
      var bar = document.createElement("span");
      var height = 8 + v * 34;
      bar.style.cssText = "width:3px;border-radius:2px;background:" + color + ";height:" + height.toFixed(1) +
        "px;animation:pulse " + (1 + (i % 5) * 0.15).toFixed(2) + "s ease-in-out infinite;animation-delay:" +
        (i * 0.04).toFixed(2) + "s";
      wavesEl.appendChild(bar);
    });
  }
  renderWaveform(cfg.waveformColor);

  function saveSettings(partial) {
    fetch(base + "/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(partial),
    });
  }

  // --- Background image upload ---
  function uploadImage(file, endpoint, onDone) {
    var formData = new FormData();
    formData.append("file", file);
    fetch(base + endpoint, { method: "POST", body: formData })
      .then(function (r) { return r.json(); })
      .then(onDone);
  }

  document.getElementById("upload-bg-btn").addEventListener("click", function () { bgFileInput.click(); });
  if (uploadHint) uploadHint.addEventListener("click", function () { bgFileInput.click(); });
  bgFileInput.addEventListener("change", function () {
    var file = bgFileInput.files[0];
    if (!file) return;
    uploadImage(file, "/image", function (data) {
      bgLayer.style.backgroundImage = "url('" + data.url + "')";
      if (uploadHint) uploadHint.style.display = "none";
      document.getElementById("remove-bg-btn").style.display = "inline-flex";
    });
  });
  document.getElementById("remove-bg-btn").addEventListener("click", function () {
    fetch(base + "/remove-image", { method: "POST" }).then(function () {
      bgLayer.style.backgroundImage = "none";
      if (uploadHint) uploadHint.style.display = "flex";
      document.getElementById("remove-bg-btn").style.display = "none";
    });
  });

  // --- Logo upload ---
  var logoLayer = document.getElementById("logo-layer");
  var logoImg = document.getElementById("logo-img");
  document.getElementById("upload-logo-btn").addEventListener("click", function () { logoFileInput.click(); });
  logoFileInput.addEventListener("change", function () {
    var file = logoFileInput.files[0];
    if (!file) return;
    uploadImage(file, "/logo", function (data) {
      logoImg.style.backgroundImage = "url('" + data.url + "')";
      logoLayer.style.display = "flex";
      document.getElementById("remove-logo-btn").style.display = "inline-flex";
    });
  });
  document.getElementById("remove-logo-btn").addEventListener("click", function () {
    fetch(base + "/remove-logo", { method: "POST" }).then(function () {
      logoLayer.style.display = "none";
      document.getElementById("remove-logo-btn").style.display = "none";
    });
  });

  // --- Brightness ---
  var brightnessInput = document.getElementById("brightness-input");
  var brightnessLabel = document.getElementById("brightness-label");
  brightnessInput.addEventListener("input", function () {
    var val = parseFloat(brightnessInput.value);
    bgLayer.style.filter = "brightness(" + val + ")";
    brightnessLabel.textContent = Math.round(val * 100) + "%";
  });
  brightnessInput.addEventListener("change", function () {
    saveSettings({ brightness: parseFloat(brightnessInput.value) });
  });

  // --- Waveform color ---
  function setWaveformColor(color) {
    cfg.waveformColor = color;
    renderWaveform(color);
    document.getElementById("hex-input").value = color;
    document.querySelectorAll(".waveform-swatch").forEach(function (btn) {
      btn.style.borderColor = btn.getAttribute("data-color").toLowerCase() === color.toLowerCase() ? "var(--accent)" : "var(--border)";
    });
    saveSettings({ waveform_color: color });
  }
  document.querySelectorAll(".waveform-swatch").forEach(function (btn) {
    btn.addEventListener("click", function () { setWaveformColor(btn.getAttribute("data-color")); });
  });
  document.getElementById("hex-input").addEventListener("change", function (e) {
    var val = e.target.value;
    if (val && val[0] !== "#") val = "#" + val;
    setWaveformColor(val);
  });

  // --- Caption ---
  var captionInput = document.getElementById("caption-input");
  captionInput.addEventListener("change", function () {
    saveSettings({ caption: captionInput.value });
  });

  // --- Download file name ---
  var filenameInput = document.getElementById("filename-input");
  filenameInput.addEventListener("change", function () {
    saveSettings({ download_filename: filenameInput.value });
  });

  // --- Drag the waveform band up/down (vertical-only — x never changes) ---
  var waveformBand = document.getElementById("waveform-band");
  var WAVEFORM_OFFSET_MIN = cfg.waveformOffsetMin, WAVEFORM_OFFSET_MAX = cfg.waveformOffsetMax;
  var waveformOffsetY = cfg.waveformOffsetY || 0;
  var waveDrag = null;

  waveformBand.addEventListener("pointerdown", function (e) {
    waveformBand.setPointerCapture(e.pointerId);
    waveDrag = { y: e.clientY, offY: waveformOffsetY };
    waveformBand.style.cursor = "grabbing";
  });
  waveformBand.addEventListener("pointermove", function (e) {
    if (!waveDrag) return;
    var next = waveDrag.offY + (e.clientY - waveDrag.y);
    waveformOffsetY = Math.max(WAVEFORM_OFFSET_MIN, Math.min(WAVEFORM_OFFSET_MAX, next));
    waveformBand.style.transform = "translateY(" + waveformOffsetY + "px)";
  });
  function endWaveDrag() {
    if (!waveDrag) return;
    waveDrag = null;
    waveformBand.style.cursor = "grab";
    saveSettings({ waveform_offset_y: Math.round(waveformOffsetY) });
  }
  waveformBand.addEventListener("pointerup", endWaveDrag);
  waveformBand.addEventListener("pointercancel", endWaveDrag);

  // --- Export ---
  var exportBtn = document.getElementById("export-btn");
  var exportStatus = document.getElementById("export-status");
  exportBtn.addEventListener("click", function () {
    exportBtn.disabled = true;
    exportStatus.textContent = "Starting export…";
    fetch(base + "/export", { method: "POST" })
      .then(function (r) { return r.json(); })
      .then(function () {
        var source = new EventSource(base + "/status/stream");
        source.onmessage = function (evt) {
          var payload = JSON.parse(evt.data);
          if (payload.status === "running") {
            exportStatus.textContent = "Exporting… " + (payload.progress_pct || 0) + "%";
          } else if (payload.status === "done") {
            exportStatus.textContent = "Export complete — downloading…";
            source.close();
            window.location.href = base + "/download";
            setTimeout(function () { window.location.reload(); }, 600);
          } else if (payload.status === "error") {
            exportStatus.textContent = "Export failed: " + (payload.error_message || "unknown error");
            exportBtn.disabled = false;
            source.close();
          }
        };
      });
  });
})();
