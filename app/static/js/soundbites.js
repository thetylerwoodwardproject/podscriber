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
})();
