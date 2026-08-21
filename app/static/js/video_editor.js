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
      bgLayer.style.backgroundImage = "url('" + data.url + "?v=" + Date.now() + "')";
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
      logoImg.style.backgroundImage = "url('" + data.url + "?v=" + Date.now() + "')";
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

  // --- Caption (full-episode video only) ---
  var captionInput = document.getElementById("caption-input");
  if (captionInput) {
    captionInput.addEventListener("change", function () {
      saveSettings({ caption: captionInput.value });
    });
  }

  // --- Social post + YouTube title (soundbite video only) ---
  var socialPostInput = document.getElementById("social-post-input");
  if (socialPostInput) {
    socialPostInput.addEventListener("change", function () {
      saveSettings({ social_post: socialPostInput.value });
    });
  }

  var youtubeTitleInput = document.getElementById("youtube-title-input");
  var youtubeTitleCount = document.getElementById("youtube-title-count");
  if (youtubeTitleInput) {
    youtubeTitleInput.addEventListener("input", function () {
      youtubeTitleCount.textContent = youtubeTitleInput.value.length + "/99";
    });
    youtubeTitleInput.addEventListener("change", function () {
      saveSettings({ youtube_title: youtubeTitleInput.value });
    });
  }

  var socialRegenBtn = document.getElementById("social-regen-btn");
  if (socialRegenBtn) {
    var socialRegenStatus = document.getElementById("social-regen-status");
    socialRegenBtn.addEventListener("click", function () {
      socialRegenBtn.disabled = true;
      socialRegenStatus.textContent = "Generating…";
      fetch(base + "/social/regenerate", { method: "POST" })
        .then(function (r) { return r.json(); })
        .then(function () {
          PS.streamStatus(base + "/social/status/stream", function (payload) {
            if (payload.status === "done") {
              socialPostInput.value = payload.social_post || "";
              if (youtubeTitleInput && !youtubeTitleInput.value) {
                youtubeTitleInput.value = payload.youtube_title || "";
                if (youtubeTitleCount) youtubeTitleCount.textContent = youtubeTitleInput.value.length + "/99";
              }
              socialRegenStatus.textContent = "Includes hashtags — same text works for both platforms.";
              socialRegenBtn.style.display = "none";
            } else if (payload.status === "error") {
              socialRegenStatus.textContent = "Couldn't generate — check your text-generation provider in Settings.";
              socialRegenBtn.disabled = false;
            }
          });
        });
    });
  }

  // --- Attach video/image to the Postiz publish (shared upload + option-population logic) ---
  function parseAttachmentSource(value) {
    if (!value) return null;
    if (value === "episode_video") return { type: "episode_video" };
    if (value.indexOf("clip:") === 0) return { type: "clip", clip_id: parseInt(value.slice(5), 10) };
    if (value.indexOf("upload:") === 0) return { type: "upload", attachment_id: parseInt(value.slice(7), 10) };
    return null;
  }

  function uploadAttachment(file, kind, onDone, onError) {
    var formData = new FormData();
    formData.append("file", file);
    formData.append("kind", kind);
    fetch("/episodes/" + cfg.episodeId + "/social/attachments", { method: "POST", body: formData })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.ok === false) { onError(data.error || "Upload failed."); return; }
        onDone(data.attachment);
      })
      .catch(function () { onError("Upload failed."); });
  }

  var videoSourceSelect = document.getElementById("social-video-source");
  var imageSourceSelect = document.getElementById("social-image-source");
  var videoPreview = document.getElementById("social-video-preview");
  var imagePreview = document.getElementById("social-image-preview");
  var attachmentNote = document.getElementById("social-attachment-note");
  var attachmentFileInput = document.createElement("input");
  attachmentFileInput.type = "file";
  attachmentFileInput.style.display = "none";
  document.body.appendChild(attachmentFileInput);
  var pendingUploadSelect = null;

  function previewElFor(kind) { return kind === "video" ? videoPreview : imagePreview; }

  function updateAttachmentPreview(select, kind) {
    var previewEl = previewElFor(kind);
    if (!previewEl) return;
    var opt = select.options[select.selectedIndex];
    var url = opt ? opt.getAttribute("data-url") : null;
    previewEl.innerHTML = "";
    if (!url) {
      previewEl.classList.remove("attachment-preview-visible");
      return;
    }
    var el = document.createElement(kind === "video" ? "video" : "img");
    el.src = url;
    if (kind === "video") { el.muted = true; el.setAttribute("playsinline", ""); }
    previewEl.appendChild(el);
    previewEl.classList.add("attachment-preview-visible");
  }

  function handleSourceSelectChange(select, kind) {
    if (select.value === "__upload_" + kind + "__") {
      pendingUploadSelect = { select: select, kind: kind };
      attachmentFileInput.accept = kind === "image" ? "image/*" : "video/*";
      attachmentFileInput.value = "";
      attachmentFileInput.click();
    }
  }
  if (videoSourceSelect) {
    videoSourceSelect.addEventListener("change", function () {
      handleSourceSelectChange(videoSourceSelect, "video");
      updateAttachmentPreview(videoSourceSelect, "video");
      updatePublishHint();
    });
    updateAttachmentPreview(videoSourceSelect, "video");
  }
  if (imageSourceSelect) {
    imageSourceSelect.addEventListener("change", function () {
      handleSourceSelectChange(imageSourceSelect, "image");
      updateAttachmentPreview(imageSourceSelect, "image");
    });
    updateAttachmentPreview(imageSourceSelect, "image");
  }
  attachmentFileInput.addEventListener("change", function () {
    var file = attachmentFileInput.files[0];
    var target = pendingUploadSelect;
    if (!file || !target) return;
    uploadAttachment(
      file,
      target.kind,
      function (attachment) {
        var option = document.createElement("option");
        option.value = "upload:" + attachment.id;
        option.textContent = attachment.filename;
        option.setAttribute("data-url", attachment.url);
        target.select.appendChild(option);
        target.select.value = option.value;
        updateAttachmentPreview(target.select, target.kind);
        if (target.kind === "image" && attachmentNote) {
          attachmentNote.style.display = attachment.instagram_ok ? "none" : "block";
          attachmentNote.textContent = attachment.instagram_ok
            ? ""
            : "This image (" + attachment.width + "×" + attachment.height + ") doesn't fit Instagram's accepted range (4:5 to 1.91:1).";
        }
        updatePublishHint();
      },
      function (message) {
        target.select.value = "";
        updateAttachmentPreview(target.select, target.kind);
        if (attachmentNote) { attachmentNote.style.display = "block"; attachmentNote.textContent = message; }
      }
    );
  });

  var publishHint = document.getElementById("publish-hint");
  function updatePublishHint() {
    if (!publishHint || !videoSourceSelect) return;
    publishHint.style.display = videoSourceSelect.value ? "none" : "block";
  }
  updatePublishHint();

  // --- Publish to Postiz ---
  var publishBtn = document.getElementById("publish-btn");
  if (publishBtn) {
    var publishStatus = document.getElementById("publish-status");
    var publishDatetimeInput = document.getElementById("publish-datetime-input");

    function updatePublishModeUI() {
      var scheduled = document.querySelector('input[name="publish-mode"][value="scheduled"]').checked;
      publishDatetimeInput.style.display = scheduled ? "inline-block" : "none";
    }
    document.querySelectorAll('input[name="publish-mode"]').forEach(function (radio) {
      radio.addEventListener("change", updatePublishModeUI);
    });
    updatePublishModeUI();

    publishBtn.addEventListener("click", function () {
      var platforms = Array.prototype.slice
        .call(document.querySelectorAll(".publish-platform-checkbox:checked"))
        .map(function (cb) { return cb.value; });
      if (!platforms.length) {
        publishStatus.textContent = "Select at least one platform.";
        return;
      }
      var videoSource = parseAttachmentSource(videoSourceSelect ? videoSourceSelect.value : "");
      if (!videoSource) {
        publishStatus.textContent = "Pick a video to attach.";
        return;
      }
      var imageSource = parseAttachmentSource(imageSourceSelect ? imageSourceSelect.value : "");
      var mode = document.querySelector('input[name="publish-mode"]:checked').value;
      var scheduledAt = null;
      if (mode === "scheduled") {
        if (!publishDatetimeInput.value) {
          publishStatus.textContent = "Pick a date and time.";
          return;
        }
        scheduledAt = new Date(publishDatetimeInput.value).toISOString();
      }
      publishBtn.disabled = true;
      publishStatus.textContent = "Publishing…";
      fetch(base + "/social/publish", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          platforms: platforms,
          mode: mode,
          scheduled_at: scheduledAt,
          video_source: videoSource,
          image_source: imageSource,
        }),
      })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.ok === false) {
            publishStatus.textContent = data.error || "Couldn't publish.";
            publishBtn.disabled = false;
            return;
          }
          PS.streamStatus(base + "/social/publish/status/stream", function (payload) {
            if (payload.status === "running") {
              publishStatus.textContent = "Publishing…";
              return;
            }
            if (payload.status !== "done" && payload.status !== "error") return;
            var results = payload.publishes || [];
            results.forEach(function (r) {
              var el = document.querySelector('.publish-platform-status[data-platform="' + r.platform + '"]');
              if (el) {
                el.textContent = r.status === "done"
                  ? "· published"
                  : "· failed" + (r.error_message ? " — " + r.error_message : "");
              }
            });
            var okCount = results.filter(function (r) { return r.status === "done"; }).length;
            publishStatus.textContent = results.length && okCount === results.length
              ? "Published to " + okCount + " platform" + (okCount > 1 ? "s" : "") + "."
              : okCount + "/" + results.length + " succeeded" + (payload.error_message ? " — " + payload.error_message : "");
            publishBtn.disabled = false;
          });
        });
    });
  }

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
        PS.streamStatus(base + "/status/stream", function (payload) {
          if (payload.status === "running") {
            exportStatus.textContent = "Exporting… " + (payload.progress_pct || 0) + "%";
          } else if (payload.status === "done") {
            exportStatus.textContent = "Export complete — downloading…";
            window.location.href = base + "/download";
            setTimeout(function () { window.location.reload(); }, 600);
          } else if (payload.status === "error") {
            exportStatus.textContent = "Export failed: " + (payload.error_message || "unknown error");
            exportBtn.disabled = false;
          }
        });
      });
  });

  // --- Duplicate to a new video variant ---
  var duplicateBtn = document.getElementById("duplicate-clip-btn");
  var duplicateStatus = document.getElementById("duplicate-clip-status");
  if (duplicateBtn) {
    duplicateBtn.addEventListener("click", function () {
      duplicateBtn.disabled = true;
      duplicateStatus.textContent = "Duplicating…";
      fetch(base + "/duplicate", { method: "POST" })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.ok === false) {
            duplicateStatus.textContent = data.error || "Couldn't duplicate.";
            duplicateBtn.disabled = false;
            return;
          }
          window.location.href = data.url;
        })
        .catch(function () {
          duplicateStatus.textContent = "Couldn't duplicate.";
          duplicateBtn.disabled = false;
        });
    });
  }
})();
