const MODE_RADIO_SELECTOR = 'input[name="menu-order-mode"]';
const statusElement = document.getElementById("status");
const form = document.getElementById("mode-form");

function setStatus(message, isError = false) {
  statusElement.textContent = message || "";
  statusElement.classList.toggle("is-error", Boolean(isError));
}

async function sendModeMessage(target, text = "") {
  return browser.runtime.sendNativeMessage("avtext_helper", { target, text });
}

function setModeSelection(mode) {
  const radio = document.querySelector(`${MODE_RADIO_SELECTOR}[value="${mode}"]`);
  if (radio) {
    radio.checked = true;
  }
}

async function loadMode() {
  try {
    setStatus("読込中...");
    const response = await sendModeMessage("get_menu_order_mode");
    const mode = response?.mode || "top";
    setModeSelection(mode);
    setStatus("");
  } catch (error) {
    console.error("get_menu_order_mode failed:", error);
    setStatus("設定を読めませんでした。", true);
  }
}

async function handleModeChange(event) {
  const mode = event.target?.value;
  if (!mode) {
    return;
  }

  form.setAttribute("aria-busy", "true");
  try {
    setStatus("保存中...");
    const response = await sendModeMessage("set_menu_order_mode", mode);
    setModeSelection(response?.mode || mode);
    setStatus("保存しました。");
  } catch (error) {
    console.error("set_menu_order_mode failed:", error);
    setStatus("保存に失敗しました。", true);
  } finally {
    form.removeAttribute("aria-busy");
  }
}

for (const radio of document.querySelectorAll(MODE_RADIO_SELECTOR)) {
  radio.addEventListener("change", handleModeChange);
}

document.addEventListener("DOMContentLoaded", loadMode);
