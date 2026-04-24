// background.js (MV2)

"use strict";

const NATIVE_APP = "avtext_helper";

let port = null;
let nextReqId = 1;

// req_id -> { tabId, kind }
const pending = new Map();

function log(...args) {
  // console.log("[AVTextChecker]", ...args);
}

function connectNative() {
  if (port) return;

  try {
    port = browser.runtime.connectNative(NATIVE_APP);
    port.onMessage.addListener(onNativeMessage);
    port.onDisconnect.addListener(() => {
      log("native disconnected", browser.runtime.lastError);
      port = null;

      // pending は全部落とす（content 側は次の selectionchange で再送される）
      pending.clear();
    });
    log("native connected");
  } catch (e) {
    port = null;
    pending.clear();
  }
}

function ensureNative() {
  if (!port) connectNative();
  return !!port;
}

function postToNative(payload) {
  if (!ensureNative()) return false;
  try {
    port.postMessage(payload);
    return true;
  } catch (e) {
    port = null;
    pending.clear();
    return false;
  }
}

function onNativeMessage(msg) {
  try {
    const reqId = msg && msg.req_id;
    if (!reqId || !pending.has(reqId)) return;

    const p = pending.get(reqId);
    pending.delete(reqId);

    browser.tabs.sendMessage(p.tabId, {
      type: "native_result",
      kind: p.kind,
      req_id: reqId,
      payload: msg
    }).catch(() => {});
  } catch (e) {
    // noop
  }
}

browser.runtime.onMessage.addListener((message, sender) => {
  if (!message || !sender || !sender.tab) return;

  const tabId = sender.tab.id;

  if (message.type === "check_actress") {
    const text = message.text || "";
    const reqId = nextReqId++;
    pending.set(reqId, { tabId, kind: "check_actress" });

    const ok = postToNative({ target: "check_actress", text, req_id: reqId });
    if (!ok) {
      pending.delete(reqId);
      browser.tabs.sendMessage(tabId, {
        type: "native_result",
        kind: "check_actress",
        req_id: reqId,
        payload: { status: "error", target: "check_actress", req_id: reqId, error: "native host not available" }
      }).catch(() => {});
    }
    return;
  }

  if (message.type === "register_actress") {
    const text = message.text || "";
    const reqId = nextReqId++;
    pending.set(reqId, { tabId, kind: "register_actress" });

    const ok = postToNative({ target: "register_actress", text, req_id: reqId });
    if (!ok) {
      pending.delete(reqId);
      browser.tabs.sendMessage(tabId, {
        type: "native_result",
        kind: "register_actress",
        req_id: reqId,
        payload: { status: "error", target: "register_actress", req_id: reqId, error: "native host not available" }
      }).catch(() => {});
    }
    return;
  }
});
