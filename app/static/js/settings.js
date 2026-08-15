(function () {
  var checkbox = document.getElementById("openai-share-key");
  if (!checkbox) return;

  var radios = document.querySelectorAll('#text-provider-radios input[name="text_provider"]');
  var radiosWrap = document.getElementById("text-provider-radios");
  var textApiKeyInput = document.getElementById("openai_api_key");

  function applyShareState(shared) {
    radios.forEach(function (radio) {
      radio.disabled = shared;
      if (shared) radio.checked = radio.value === "openai";
    });
    if (textApiKeyInput) {
      textApiKeyInput.disabled = shared;
      textApiKeyInput.style.opacity = shared ? "0.5" : "1";
    }
    if (radiosWrap) radiosWrap.style.opacity = shared ? "0.5" : "1";
  }

  checkbox.addEventListener("change", function () {
    applyShareState(checkbox.checked);
  });

  applyShareState(checkbox.checked);
})();

(function () {
  var preset = document.getElementById("ollama-keep-alive-preset");
  var custom = document.getElementById("ollama-keep-alive-custom");
  if (!preset || !custom) return;

  function applyKeepAliveState() {
    var isCustom = preset.value === "custom";
    custom.classList.toggle("field-subinput-visible", isCustom);
    if (isCustom) {
      preset.removeAttribute("name");
      custom.setAttribute("name", "ollama_keep_alive");
    } else {
      preset.setAttribute("name", "ollama_keep_alive");
      custom.removeAttribute("name");
    }
  }

  preset.addEventListener("change", applyKeepAliveState);
  applyKeepAliveState();
})();
