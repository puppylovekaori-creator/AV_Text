const menus = browser.menus || browser.contextMenus;

menus.create({
  id: "avtext-actress",
  title: "選択文字列を actress.txt に送る",
  contexts: ["selection"]
});

menus.onClicked.addListener(async (info) => {
  if (info.menuItemId !== "avtext-actress") return;
  if (!info.selectionText) return;

  try {
    await browser.runtime.sendNativeMessage("avtext_helper", {
      target: "actress",
      text: info.selectionText
    });
  } catch (e) {
    console.error("sendNativeMessage failed:", e);
  }
});
