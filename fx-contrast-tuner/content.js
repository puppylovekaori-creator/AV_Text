(() => {
  "use strict";

  const ROOT_ATTR = "data-fx-contrast-mode";
  const ROOT_MODE = "light-page";
  const SURFACE_ATTR = "data-fx-contrast-surface";
  const OWNED_ATTR = "data-fx-contrast-owned";

  const CONFIG = {
    selectors: [
      "main",
      "[role='main']",
      "article",
      ".content",
      ".main",
      "#content",
      ".post",
      ".entry",
      ".article",
      "section",
      "body"
    ],
    perChannelThreshold: 236,
    luminanceThreshold: 0.9,
    minArea: 16000,
    debounceMs: 80
  };

  let refreshTimer = null;

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
      rgb.r >= CONFIG.perChannelThreshold &&
      rgb.g >= CONFIG.perChannelThreshold &&
      rgb.b >= CONFIG.perChannelThreshold &&
      luminance(rgb) >= CONFIG.luminanceThreshold
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
    return rect.width * rect.height >= CONFIG.minArea;
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

    for (const selector of CONFIG.selectors) {
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

  function applyContrastTuning() {
    clearManagedState();

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
    }, CONFIG.debounceMs);
  }

  scheduleRefresh();

  window.addEventListener("load", scheduleRefresh, true);
  window.addEventListener("resize", scheduleRefresh, true);

  const observer = new MutationObserver(() => {
    scheduleRefresh();
  });

  observer.observe(document, {
    childList: true,
    subtree: true,
    attributes: true
  });
})();
