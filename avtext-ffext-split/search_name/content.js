// content_script.js

"use strict";

const MAX_LEN = 12;          // ユーザー要望：とりあえず12文字
const DEBOUNCE_MS = 120;     // キーボード選択や微調整用
const MOUSEUP_CHECK_DELAY_MS = 40;
const LOCATE_COUNT_DELAY_MS = 350;
const OVERLAY_Z = 2147483647;
const ASCII_PRINTABLE_PATTERN = /^[\x21-\x7E]+$/;
const ASCII_ALNUM_PATTERN = /[A-Za-z0-9]/;

let overlay = null;
let overlayText = null;
let overlayBtn = null;

let lastSentText = "";
let lastSelectionKey = "";
let debounceTimer = null;
let locateCountTimer = null;
let isMouseSelecting = false;

// 表示中の対象名（クリック登録の誤爆防止）
let currentName = "";
let currentCheckKind = "";
let currentLocateQuery = "";
let currentCanRegister = false;

// content 側の要求トークン（古い返事を捨てるため）
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
    clearLocateCountTimer();
    const reqId = ++lastReqIdRegister;
    currentCheckKind = "register_actress";
    showLoading(`登録中: ${currentName}`);
    browser.runtime.sendMessage({ type: "register_actress", text: currentName, client_req_id: reqId }).catch(() => {});
  }, true);

  overlay.appendChild(overlayBtn);

  document.documentElement.appendChild(overlay);
}

function hideOverlay() {
  if (!overlay) return;
  overlay.style.display = "none";
  overlayBtn.style.display = "none";
  clearLocateCountTimer();
  currentName = "";
  currentCheckKind = "";
  currentLocateQuery = "";
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

function showLocatePreview(text, count, firstResult, canRegister = false, countExact = false) {
  const fileName = getLeafName(firstResult) || text;
  const countLabel = countExact ? `${count}件` : `${count}件以上`;
  setOverlayText(`${countLabel} ${fileName}`);
  setOverlayTooltip(firstResult || "");
  overlayBtn.style.display = canRegister ? "inline-block" : "none";
}

function showLocateFound(text, count, firstResult, canRegister = false) {
  const fileName = getLeafName(firstResult) || text;
  setOverlayText(`${count}件 ${fileName}`);
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
        locateQuery: locateText
      };
    }

    return {
      displayText: text,
      requestText: locateText,
      kind: "check_locate_preview",
      canRegister: false,
      locateQuery: locateText
    };
  }

  if (isLocateCodeText(text)) {
    return {
      displayText: text,
      requestText: text,
      kind: "check_locate_preview",
      canRegister: false,
      locateQuery: text
    };
  }

  if (text.length > MAX_LEN) {
    return {
      displayText: text,
      requestText: locateText,
      kind: "check_locate_preview",
      canRegister: false,
      locateQuery: locateText
    };
  }

  return {
    displayText: text,
    requestText: text,
    kind: "check_actress",
    canRegister: true,
    locateQuery: locateText
  };
}

function scheduleCheck() {
  scheduleCheckWithDelay(DEBOUNCE_MS);
}

function scheduleCheckWithDelay(delayMs) {
  if (debounceTimer) clearTimeout(debounceTimer);
  debounceTimer = setTimeout(runCheckNow, delayMs);
}

function clearLocateCountTimer() {
  if (!locateCountTimer) return;
  clearTimeout(locateCountTimer);
  locateCountTimer = null;
}

function scheduleLocateCount(clientReqId) {
  clearLocateCountTimer();
  if (!currentLocateQuery) return;

  locateCountTimer = setTimeout(() => {
    locateCountTimer = null;
    if (!clientReqId || clientReqId !== lastReqIdCheck) return;
    if (!currentName || currentCheckKind !== "check_locate_exists") return;
    browser.runtime.sendMessage({
      type: "check_locate_exists",
      text: currentLocateQuery,
      client_req_id: clientReqId
    }).catch(() => {});
  }, LOCATE_COUNT_DELAY_MS);
}

function isOverlayEventTarget(target) {
  return !!(overlay && target && overlay.contains(target));
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

  clearLocateCountTimer();
  lastSelectionKey = key;
  const reqId = ++lastReqIdCheck;
  currentName = classified.displayText;
  currentCheckKind = classified.kind;
  currentLocateQuery = classified.locateQuery || "";
  currentCanRegister = !!classified.canRegister;
  showLoading(classified.kind === "check_locate_preview" ? "ファイル確認中..." : "判定中...");

  lastSentText = classified.requestText;
  browser.runtime.sendMessage({ type: classified.kind, text: classified.requestText, client_req_id: reqId }).catch(() => {});
}

document.addEventListener("selectionchange", () => {
  if (isMouseSelecting) return;
  scheduleCheck();
}, true);

document.addEventListener("mousedown", (e) => {
  if (e.button !== 0) return;
  if (isOverlayEventTarget(e.target)) return;
  clearLocateCountTimer();
  isMouseSelecting = true;
}, true);

document.addEventListener("mouseup", (e) => {
  if (e.button !== 0) return;
  if (isOverlayEventTarget(e.target)) return;
  if (!isMouseSelecting) return;
  isMouseSelecting = false;
  scheduleCheckWithDelay(MOUSEUP_CHECK_DELAY_MS);
}, true);

document.addEventListener("scroll", () => {
  // スクロールで選択位置が変わるので、表示中なら追従更新
  if (!overlay || overlay.style.display === "none") return;
  if (isMouseSelecting) return;
  scheduleCheck();
}, true);

browser.runtime.onMessage.addListener((message) => {
  if (!message || message.type !== "native_result") return;

  const kind = message.kind;
  const clientReqId = Number(message.client_req_id || 0);
  const payload = message.payload || {};

  if (kind === "check_actress") {
    if (!clientReqId || clientReqId !== lastReqIdCheck) return;
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
    if (found) {
      currentCheckKind = "check_actress";
      showRegistered(displayName, hasAlias);
    }
    else if (currentLocateQuery) {
      currentCheckKind = "check_locate_preview";
      showLoading("ファイル確認中...");
      browser.runtime.sendMessage({ type: "check_locate_preview", text: currentLocateQuery, client_req_id: clientReqId }).catch(() => {});
    } else {
      showUnregistered(currentName, currentCanRegister);
    }
    return;
  }

  if (kind === "check_locate_preview") {
    if (!clientReqId || clientReqId !== lastReqIdCheck) return;
    if (!currentName || currentCheckKind !== "check_locate_preview") return;

    if (payload.status !== "ok") {
      if (currentCanRegister) currentCheckKind = "check_actress";
      setOverlayText(`確認失敗: ${currentName}`);
      setOverlayTooltip("");
      overlayBtn.style.display = currentCanRegister ? "inline-block" : "none";
      return;
    }

    const count = Number.isFinite(payload.count) ? payload.count : (payload.found ? 1 : 0);
    const countExact = !!payload.count_exact;

    if (payload.found) {
      showLocatePreview(currentName, count, payload.first_result || "", currentCanRegister, countExact);
      if (countExact) {
        if (currentCanRegister) currentCheckKind = "check_actress";
      } else {
        currentCheckKind = "check_locate_exists";
        scheduleLocateCount(clientReqId);
      }
    }
    else if (currentCanRegister) {
      currentCheckKind = "check_actress";
      showLocateMissing(currentName, 0, true);
    }
    else {
      showLocateMissing(currentName, 0, false);
    }
    return;
  }

  if (kind === "check_locate_exists") {
    if (!clientReqId || clientReqId !== lastReqIdCheck) return;
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
    if (!clientReqId || clientReqId !== lastReqIdRegister) return;
    if (!currentName) return;

    if (payload.status !== "ok") {
      setOverlayText(`登録失敗: ${currentName}`);
      setOverlayTooltip("");
      overlayBtn.style.display = "none";
      return;
    }

    // registered=true なら即表示更新
    if (payload.registered === true) {
      currentCheckKind = "check_actress";
      showRegistered(payload.display_name || currentName, !!payload.has_alias);
      return;
    }

    // 既に存在していた等
    if (payload.already_exists === true) {
      currentCheckKind = "check_actress";
      showRegistered(payload.display_name || currentName, !!payload.has_alias);
      return;
    }

    // 想定外：一旦「未登録」に戻す
    showUnregistered(currentName);
  }
});
