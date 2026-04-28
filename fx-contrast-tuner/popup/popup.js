(() => {
  "use strict";

  const DEFAULTS = globalThis.FX_CONTRAST_DEFAULTS;
  const enabledElement = document.getElementById("enabled");
  const statusElement = document.getElementById("status");
  const openOptionsButton = document.getElementById("open-options");

  function setStatus(message) {
    statusElement.textContent = message || "";
  }

  async function loadSettings() {
    try {
      const result = await browser.storage.local.get(["enabled"]);
      enabledElement.checked = typeof result.enabled === "boolean" ? result.enabled : DEFAULTS.enabled;
      setStatus("");
    } catch (error) {
      console.error(error);
      enabledElement.checked = DEFAULTS.enabled;
      setStatus("設定を読めませんでした。");
    }
  }

  enabledElement.addEventListener("change", async () => {
    try {
      await browser.storage.local.set({ enabled: enabledElement.checked });
      setStatus("保存しました。");
    } catch (error) {
      console.error(error);
      setStatus("保存に失敗しました。");
    }
  });

  openOptionsButton.addEventListener("click", async () => {
    await browser.runtime.openOptionsPage();
    window.close();
  });

  loadSettings();
})();
