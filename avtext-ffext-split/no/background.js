const menus = browser.menus || browser.contextMenus;

menus.create({
  id: "avtext-no",
  title: "選択文字列を no.txt に送る",
  contexts: ["selection"]
});

menus.onClicked.addListener(async (info) => {
  if (info.menuItemId !== "avtext-no") return;
  if (!info.selectionText) return;

  try {
    await browser.runtime.sendNativeMessage("avtext_helper", {
      target: "no",
      text: info.selectionText
    });
  } catch (e) {
    console.error("sendNativeMessage failed:", e);
  }
});
