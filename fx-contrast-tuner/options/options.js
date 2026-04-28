(() => {
  "use strict";

  const DEFAULTS = globalThis.FX_CONTRAST_DEFAULTS;
  const FIELD_NAMES = [
    "enabled",
    "perChannelThreshold",
    "luminanceThreshold",
    "minArea",
    "debounceMs",
    "surfaceBg",
    "textColor",
    "linkColor",
    "linkHoverColor",
    "linkVisitedColor",
    "selectionBg"
  ];

  const form = document.getElementById("settings-form");
  const statusElement = document.getElementById("status");
  const resetButton = document.getElementById("reset-button");

  function setStatus(message) {
    statusElement.textContent = message || "";
  }

  function setFieldValue(name, value) {
    const field = document.getElementById(name);
    if (!field) {
      return;
    }

    if (field.type === "checkbox") {
      field.checked = Boolean(value);
      return;
    }

    field.value = String(value);
  }

  function fillForm(values) {
    for (const name of FIELD_NAMES) {
      setFieldValue(name, values[name]);
    }
  }

  function clampNumber(value, min, max, fallback) {
    const numeric = Number(value);
    if (Number.isNaN(numeric)) {
      return fallback;
    }
    return Math.min(max, Math.max(min, numeric));
  }

  function readForm() {
    return {
      enabled: document.getElementById("enabled").checked,
      perChannelThreshold: clampNumber(document.getElementById("perChannelThreshold").value, 0, 255, DEFAULTS.perChannelThreshold),
      luminanceThreshold: clampNumber(document.getElementById("luminanceThreshold").value, 0, 1, DEFAULTS.luminanceThreshold),
      minArea: clampNumber(document.getElementById("minArea").value, 1, 10000000, DEFAULTS.minArea),
      debounceMs: clampNumber(document.getElementById("debounceMs").value, 0, 5000, DEFAULTS.debounceMs),
      surfaceBg: document.getElementById("surfaceBg").value || DEFAULTS.surfaceBg,
      textColor: document.getElementById("textColor").value || DEFAULTS.textColor,
      linkColor: document.getElementById("linkColor").value || DEFAULTS.linkColor,
      linkHoverColor: document.getElementById("linkHoverColor").value || DEFAULTS.linkHoverColor,
      linkVisitedColor: document.getElementById("linkVisitedColor").value || DEFAULTS.linkVisitedColor,
      selectionBg: document.getElementById("selectionBg").value || DEFAULTS.selectionBg
    };
  }

  async function loadSettings() {
    try {
      const values = await browser.storage.local.get(FIELD_NAMES);
      fillForm({ ...DEFAULTS, ...values });
      setStatus("");
    } catch (error) {
      console.error(error);
      fillForm(DEFAULTS);
      setStatus("設定を読めませんでした。");
    }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await browser.storage.local.set(readForm());
      setStatus("保存しました。");
    } catch (error) {
      console.error(error);
      setStatus("保存に失敗しました。");
    }
  });

  resetButton.addEventListener("click", async () => {
    try {
      await browser.storage.local.set({ ...DEFAULTS });
      fillForm(DEFAULTS);
      setStatus("初期値に戻しました。");
    } catch (error) {
      console.error(error);
      setStatus("初期化に失敗しました。");
    }
  });

  loadSettings();
})();
