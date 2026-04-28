(() => {
  "use strict";

  globalThis.FX_CONTRAST_DEFAULTS = Object.freeze({
    enabled: true,
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
    debounceMs: 80,
    surfaceBg: "#f4efe4",
    textColor: "#1f1f1f",
    linkColor: "#0c3f87",
    linkHoverColor: "#a83b16",
    linkVisitedColor: "#5e4c8d",
    selectionBg: "#d6c8a4"
  });
})();
