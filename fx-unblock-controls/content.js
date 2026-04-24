(() => {
  "use strict";

  const STYLE_ID = "fx-unblock-controls-style";

  const STYLE_TEXT = `
html, body, body *, body *::before, body *::after {
  user-select: text !important;
  -moz-user-select: text !important;
  -webkit-user-select: text !important;
}

input, textarea {
  user-select: auto !important;
  -moz-user-select: auto !important;
  -webkit-user-select: auto !important;
}
`;

  function injectStyle() {
    const root = document.documentElement;
    if (!root) {
      return;
    }

    let style = document.getElementById(STYLE_ID);
    if (!style) {
      style = document.createElement("style");
      style.id = STYLE_ID;
      style.textContent = STYLE_TEXT;
      root.appendChild(style);
      return;
    }

    if (style.textContent !== STYLE_TEXT) {
      style.textContent = STYLE_TEXT;
    }
  }

  function unblockEvent(event) {
    event.stopImmediatePropagation();
  }

  function registerUnblocker(eventName) {
    window.addEventListener(eventName, unblockEvent, true);
    document.addEventListener(eventName, unblockEvent, true);
  }

  registerUnblocker("contextmenu");
  registerUnblocker("dragstart");
  registerUnblocker("selectstart");

  injectStyle();

  document.addEventListener("readystatechange", injectStyle, true);

  const observer = new MutationObserver(() => {
    injectStyle();
  });

  observer.observe(document, {
    childList: true,
    subtree: true
  });
})();