// content_script.js

"use strict";

const MAX_LEN = 12;          // ユーザー要望：とりあえず12文字
const DEBOUNCE_MS = 120;     // 体感即時寄り
const OVERLAY_Z = 2147483647;
const ASCII_PRINTABLE_PATTERN = /^[\x21-\x7E]+$/;
const ASCII_ALNUM_PATTERN = /[A-Za-z0-9]/;

let overlay = null;
let overlayText = null;
let overlayBtn = null;

let lastSentText = "";
let lastSelectionKey = "";
let debounceTimer = null;

// 表示中の対象名（クリック登録の誤爆防止）
let currentName = "";
let currentCheckKind = "";
let currentLocateFallbackText = "";
let currentCanRegister = false;

// 直近 req_id（古い返事で上書きしないため）
let lastReqIdCheck = 0;
let lastReqIdRegister = 0;

function makeOverlay() {
  if (overlay) return;

  overlay = document.createElement("div");
  overlay.style.position = "fixed";
  overlay.style.zIndex = String(OVERLAY_Z);
  overlay.style.fontSize = "14px";
  overlay.style.lineHeight = "1.2";
  overlay.style.padding = "6px 8px";
  overlay.style.borderRadius = "8px";
  overlay.style.boxShadow = "0 2px 10px rgba(0,0,0,0.25)";
  overlay.style.background = "rgba(20,20,20,0.92)";
  overlay.style.color = "#fff";
  overlay.style.userSelect = "none";
  overlay.style.pointerEvents = "auto";
  overlay.style.display = "none";

  overlayText = document.createElement("span");
  overlay.appendChild(overlayText);

  overlayBtn = document.createElement("button");
  overlayBtn.textContent = "登録";
  overlayBtn.style.marginLeft = "10px";
  overlayBtn.style.padding = "2px 8px";
  overlayBtn.style.borderRadius = "999px";
  overlayBtn.style.border = "0";
  overlayBtn.style.cursor = "pointer";
  overlayBtn.style.fontSize = "13px";
  overlayBtn.style.lineHeight = "1.2";
  overlayBtn.style.background = "rgba(255,255,255,0.9)";
  overlayBtn.style.color = "#111";
  overlayBtn.style.display = "none";

  // クリックで selection が崩れてオーバーレイが消えるのを防ぐ
  overlayBtn.addEventListener("mousedown", (e) => {
    e.preventDefault();
    e.stopPropagation();
  }, true);

  overlayBtn.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (!currentName || !currentCanRegister) return;
    showLoading(`登録中: ${currentName}`);
    browser.runtime.sendMessage({ type: "register_actress", text: currentName }).catch(() => {});
  }, true);

  overlay.appendChild(overlayBtn);

  document.documentElement.appendChild(overlay);
}

function hideOverlay() {
  if (!overlay) return;
  overlay.style.display = "none";
  overlayBtn.style.display = "none";
  currentName = "";
  currentCheckKind = "";
  currentLocateFallbackText = "";
  currentCanRegister = false;
}

function showOverlayAt(rect) {
  makeOverlay();

  const margin = 10;
  let x = rect.left;
  let y = rect.bottom + margin;

  // 画面外に出ないように軽く補正
  const maxX = window.innerWidth - 10;
  const maxY = window.innerHeight - 10;

  overlay.style.display = "block";
  overlay.style.left = "0px";
  overlay.style.top = "0px";
  overlay.style.transform = "translate(-9999px, -9999px)"; // 一旦退避

  const w = overlay.offsetWidth;
  const h = overlay.offsetHeight;

  if (x + w > maxX) x = Math.max(10, maxX - w);
  if (y + h > maxY) y = Math.max(10, rect.top - margin - h);

  overlay.style.transform = `translate(${Math.round(x)}px, ${Math.round(y)}px)`;
}

function setOverlayText(text) {
  makeOverlay();
  overlayText.textContent = text;
}

function setOverlayTooltip(text) {
  makeOverlay();
  const value = text || "";
  overlay.title = value;
  overlayText.title = value;
}

function showLoading(label) {
  setOverlayText(label || "判定中...");
  setOverlayTooltip("");
  overlayBtn.style.display = "none";
}

function showRegistered(name, hasAlias = false) {
  const label = hasAlias ? "登録済み(別名あり)" : "登録済";
  setOverlayText(`${label}: ${name}`);
  setOverlayTooltip("");
  overlayBtn.style.display = "none";
}

function showUnregistered(name, canRegister = true) {
  setOverlayText(`未登録: ${name}`);
  setOverlayTooltip("");
  overlayBtn.style.display = canRegister ? "inline-block" : "none";
}

function getLeafName(pathText) {
  const normalized = String(pathText || "").trim();
  if (!normalized) return "";
  const parts = normalized.split(/[\\/]/);
  return parts.length > 0 ? (parts[parts.length - 1] || "") : normalized;
}

function showLocateFound(text, count, firstResult, canRegister = false) {
  const fileName = getLeafName(firstResult) || text;
  setOverlayText(`${fileName} (${count})`);
  setOverlayTooltip(firstResult || "");
  overlayBtn.style.display = canRegister ? "inline-block" : "none";
}

function showLocateMissing(text, count = 0, canRegister = false) {
  setOverlayText(`ファイルなし(${count}): ${text}`);
  setOverlayTooltip("");
  overlayBtn.style.display = canRegister ? "inline-block" : "none";
}

function getSelectionRect() {
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0) return null;
  const range = sel.getRangeAt(0);
  const rect = range.getBoundingClientRect();
  if (rect && rect.width === 0 && rect.height === 0) {
    // 文字列だけ選択だとゼロになるケースがあるので、clientRects を使う
    const rects = range.getClientRects();
    if (rects && rects.length > 0) return rects[0];
  }
  return rect;
}

function normalizeSelectedText(raw) {
  if (!raw) return "";

  // 前後空白（半角/全角）除去
  let s = raw.replace(/^[\s\u3000]+|[\s\u3000]+$/g, "");

  // 末尾や先頭の「、」「。」など、明らかに名前に使わない記号を落とす
  // （中の「・」「＝」「-」等は残す）
  s = s.replace(/^[、，。．・]+/, "");
  s = s.replace(/[、，。．・]+$/, "");

  // 改行やタブは対象外。半角スペースは locate 用に残す。
  if (/[\t\r\n\u3000]/.test(s)) return "";

  if (s.length === 0) return "";
  return s;
}

function normalizeLocateQuery(text) {
  return String(text || "").replace(/ +/g, " ").trim();
}

function normalizeActressText(text) {
  return String(text || "").replace(/ +/g, "").trim();
}

function isLocateCodeText(text) {
  return ASCII_PRINTABLE_PATTERN.test(text) && ASCII_ALNUM_PATTERN.test(text);
}

function classifySelectedText(raw) {
  const text = normalizeSelectedText(raw);
  if (!text) return null;
  const locateText = normalizeLocateQuery(text);
  const actressText = normalizeActressText(text);
  if (!locateText) return null;

  if (text.includes(" ")) {
    if (!ASCII_ALNUM_PATTERN.test(text) && actressText.length <= MAX_LEN) {
      return {
        displayText: actressText,
        requestText: actressText,
        kind: "check_actress",
        canRegister: true,
        locateFallbackText: locateText
      };
    }

    return {
      displayText: text,
      requestText: locateText,
      kind: "check_locate_exists",
      canRegister: false,
      locateFallbackText: ""
    };
  }

  if (isLocateCodeText(text)) {
    return {
      displayText: text,
      requestText: text,
      kind: "check_locate_exists",
      canRegister: false,
      locateFallbackText: ""
    };
  }

  if (text.length > MAX_LEN) {
    return {
      displayText: text,
      requestText: locateText,
      kind: "check_locate_exists",
      canRegister: false,
      locateFallbackText: ""
    };
  }

  return {
    displayText: text,
    requestText: text,
    kind: "check_actress",
    canRegister: true,
    locateFallbackText: locateText
  };
}

function scheduleCheck() {
  if (debounceTimer) clearTimeout(debounceTimer);
  debounceTimer = setTimeout(runCheckNow, DEBOUNCE_MS);
}

function runCheckNow() {
  debounceTimer = null;

  const sel = window.getSelection();
  const raw = sel ? String(sel.toString() || "") : "";
  const classified = classifySelectedText(raw);

  if (!classified) {
    hideOverlay();
    lastSentText = "";
    lastSelectionKey = "";
    return;
  }

  const rect = getSelectionRect();
  if (!rect) return;

  showOverlayAt(rect);

  // 同じ選択に対して連打しない
  const key = `${classified.kind}|${classified.requestText}|${Math.round(rect.left)}|${Math.round(rect.top)}|${Math.round(rect.width)}|${Math.round(rect.height)}`;
  if (key === lastSelectionKey) return;

  lastSelectionKey = key;
  currentName = classified.displayText;
  currentCheckKind = classified.kind;
  currentLocateFallbackText = classified.locateFallbackText || "";
  currentCanRegister = !!classified.canRegister;
  showLoading(classified.kind === "check_locate_exists" ? "ファイル確認中..." : "判定中...");

  lastSentText = classified.requestText;
  browser.runtime.sendMessage({ type: classified.kind, text: classified.requestText }).catch(() => {});
}

document.addEventListener("selectionchange", () => {
  scheduleCheck();
}, true);

document.addEventListener("scroll", () => {
  // スクロールで選択位置が変わるので、表示中なら追従更新
  if (!overlay || overlay.style.display === "none") return;
  scheduleCheck();
}, true);

browser.runtime.onMessage.addListener((message) => {
  if (!message || message.type !== "native_result") return;

  const kind = message.kind;
  const payload = message.payload || {};

  if (kind === "check_actress") {
    // 古い返事で上書きしない（background 側で req_id は振っているが content 側は見えない）
    // なので currentName と一致しない返事は捨てる
    if (!currentName || currentCheckKind !== "check_actress") return;

    if (payload.status !== "ok") {
      setOverlayText(`判定失敗: ${currentName}`);
      setOverlayTooltip("");
      overlayBtn.style.display = "none";
      return;
    }

    const found = !!payload.found;
    const hasAlias = !!payload.has_alias;
    const displayName = payload.display_name || currentName;
    if (found) showRegistered(displayName, hasAlias);
    else if (currentLocateFallbackText) {
      currentCheckKind = "check_locate_exists";
      showLoading("ファイル確認中...");
      browser.runtime.sendMessage({ type: "check_locate_exists", text: currentLocateFallbackText }).catch(() => {});
    } else {
      showUnregistered(currentName, currentCanRegister);
    }
    return;
  }

  if (kind === "check_locate_exists") {
    if (!currentName || currentCheckKind !== "check_locate_exists") return;

    if (payload.status !== "ok") {
      if (currentCanRegister) currentCheckKind = "check_actress";
      setOverlayText(`確認失敗: ${currentName}`);
      setOverlayTooltip("");
      overlayBtn.style.display = currentCanRegister ? "inline-block" : "none";
      return;
    }

    const count = Number.isFinite(payload.count) ? payload.count : (payload.found ? 1 : 0);
    if (payload.found) {
      if (currentCanRegister) currentCheckKind = "check_actress";
      showLocateFound(currentName, count, payload.first_result || "", currentCanRegister);
    }
    else if (currentCanRegister) {
      currentCheckKind = "check_actress";
      showLocateMissing(currentName, count, true);
    }
    else showLocateMissing(currentName, count);
    return;
  }

  if (kind === "register_actress") {
    if (!currentName || currentCheckKind !== "check_actress") return;

    if (payload.status !== "ok") {
      setOverlayText(`登録失敗: ${currentName}`);
      setOverlayTooltip("");
      overlayBtn.style.display = "none";
      return;
    }

    // registered=true なら即表示更新
    if (payload.registered === true) {
      showRegistered(payload.display_name || currentName, !!payload.has_alias);
      return;
    }

    // 既に存在していた等
    if (payload.already_exists === true) {
      showRegistered(payload.display_name || currentName, !!payload.has_alias);
      return;
    }

    // 想定外：一旦「未登録」に戻す
    showUnregistered(currentName);
  }
});
