(() => {
  "use strict";

  const ROOT_ATTR = "data-fx-contrast-mode";
  const ROOT_MODE = "light-page";
  const SURFACE_ATTR = "data-fx-contrast-surface";
  const OWNED_ATTR = "data-fx-contrast-owned";
  const DEFAULTS = globalThis.FX_CONTRAST_DEFAULTS || {};
  const STORAGE_KEYS = [
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

  let refreshTimer = null;
  let settings = { ...DEFAULTS };

  function clampNumber(value, min, max, fallback) {
    const numeric = Number(value);
    if (Number.isNaN(numeric)) {
      return fallback;
    }
    return Math.min(max, Math.max(min, numeric));
  }

  function sanitizeSettings(raw) {
    const source = raw || {};
    return {
      ...DEFAULTS,
      enabled: typeof source.enabled === "boolean" ? source.enabled : DEFAULTS.enabled,
      perChannelThreshold: clampNumber(source.perChannelThreshold, 0, 255, DEFAULTS.perChannelThreshold),
      luminanceThreshold: clampNumber(source.luminanceThreshold, 0, 1, DEFAULTS.luminanceThreshold),
      minArea: clampNumber(source.minArea, 1, 10000000, DEFAULTS.minArea),
      debounceMs: clampNumber(source.debounceMs, 0, 5000, DEFAULTS.debounceMs),
      surfaceBg: source.surfaceBg || DEFAULTS.surfaceBg,
      textColor: source.textColor || DEFAULTS.textColor,
      linkColor: source.linkColor || DEFAULTS.linkColor,
      linkHoverColor: source.linkHoverColor || DEFAULTS.linkHoverColor,
      linkVisitedColor: source.linkVisitedColor || DEFAULTS.linkVisitedColor,
      selectionBg: source.selectionBg || DEFAULTS.selectionBg
    };
  }

  function parseRgb(text) {
    if (!text) {
      return null;
    }

    const match = text.match(/rgba?\(([^)]+)\)/i);
    if (!match) {
      return null;
    }

    const parts = match[1].split(",").map((value) => value.trim());
    if (parts.length < 3) {
      return null;
    }

    const rgb = {
      r: Number(parts[0]),
      g: Number(parts[1]),
      b: Number(parts[2]),
      a: parts.length >= 4 ? Number(parts[3]) : 1
    };

    if ([rgb.r, rgb.g, rgb.b, rgb.a].some((value) => Number.isNaN(value))) {
      return null;
    }

    return rgb;
  }

  function srgbToLinear(value) {
    const normalized = value / 255;
    return normalized <= 0.04045
      ? normalized / 12.92
      : ((normalized + 0.055) / 1.055) ** 2.4;
  }

  function luminance(rgb) {
    return (
      0.2126 * srgbToLinear(rgb.r) +
      0.7152 * srgbToLinear(rgb.g) +
      0.0722 * srgbToLinear(rgb.b)
    );
  }

  function isNearWhite(rgb) {
    return (
      rgb &&
      rgb.a > 0 &&
      rgb.r >= settings.perChannelThreshold &&
      rgb.g >= settings.perChannelThreshold &&
      rgb.b >= settings.perChannelThreshold &&
      luminance(rgb) >= settings.luminanceThreshold
    );
  }

  function isVisibleElement(element) {
    if (!element || element.nodeType !== Node.ELEMENT_NODE) {
      return false;
    }

    const style = window.getComputedStyle(element);
    if (style.display === "none" || style.visibility === "hidden") {
      return false;
    }

    const rect = element.getBoundingClientRect();
    return rect.width * rect.height >= settings.minArea;
  }

  function resolveBackgroundColor(element) {
    let current = element;

    while (current && current.nodeType === Node.ELEMENT_NODE) {
      const rgb = parseRgb(window.getComputedStyle(current).backgroundColor);
      if (rgb && rgb.a > 0) {
        return rgb;
      }
      current = current.parentElement;
    }

    return null;
  }

  function collectCandidateElements() {
    const seen = new Set();
    const candidates = [];

    for (const selector of DEFAULTS.selectors) {
      for (const element of document.querySelectorAll(selector)) {
        if (!seen.has(element)) {
          seen.add(element);
          candidates.push(element);
        }
      }
    }

    return candidates;
  }

  function clearManagedState() {
    document.documentElement.removeAttribute(ROOT_ATTR);

    for (const element of document.querySelectorAll(`[${OWNED_ATTR}="true"]`)) {
      element.removeAttribute(SURFACE_ATTR);
      element.removeAttribute(OWNED_ATTR);
    }
  }

  function applyRootVariables() {
    const rootStyle = document.documentElement.style;
    rootStyle.setProperty("--fx-contrast-surface-bg", settings.surfaceBg);
    rootStyle.setProperty("--fx-contrast-text", settings.textColor);
    rootStyle.setProperty("--fx-contrast-link", settings.linkColor);
    rootStyle.setProperty("--fx-contrast-link-hover", settings.linkHoverColor);
    rootStyle.setProperty("--fx-contrast-link-visited", settings.linkVisitedColor);
    rootStyle.setProperty("--fx-contrast-selection-bg", settings.selectionBg);
  }

  function applyContrastTuning() {
    clearManagedState();
    applyRootVariables();

    if (!settings.enabled) {
      return;
    }

    const tuned = [];

    for (const element of collectCandidateElements()) {
      if (!isVisibleElement(element)) {
        continue;
      }

      const background = resolveBackgroundColor(element);
      if (!isNearWhite(background)) {
        continue;
      }

      element.setAttribute(SURFACE_ATTR, "true");
      element.setAttribute(OWNED_ATTR, "true");
      tuned.push(element);
    }

    if (tuned.length > 0) {
      document.documentElement.setAttribute(ROOT_ATTR, ROOT_MODE);
    }
  }

  function scheduleRefresh() {
    if (refreshTimer !== null) {
      clearTimeout(refreshTimer);
    }

    refreshTimer = window.setTimeout(() => {
      refreshTimer = null;
      applyContrastTuning();
    }, settings.debounceMs);
  }

  async function loadSettings() {
    try {
      const stored = await browser.storage.local.get(STORAGE_KEYS);
      settings = sanitizeSettings(stored);
    } catch (error) {
      settings = sanitizeSettings({});
    }
    scheduleRefresh();
  }

  loadSettings();

  window.addEventListener("load", scheduleRefresh, true);
  window.addEventListener("resize", scheduleRefresh, true);
  browser.storage.onChanged.addListener((changes, areaName) => {
    if (areaName !== "local") {
      return;
    }

    const next = { ...settings };
    for (const key of STORAGE_KEYS) {
      if (changes[key]) {
        next[key] = changes[key].newValue;
      }
    }
    settings = sanitizeSettings(next);
    scheduleRefresh();
  });

  const observer = new MutationObserver(() => {
    scheduleRefresh();
  });

  observer.observe(document, {
    childList: true,
    subtree: true,
    attributes: true
  });
})();
