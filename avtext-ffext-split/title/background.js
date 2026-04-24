const menus = browser.menus || browser.contextMenus;

menus.create({
  id: "avtext-title",
  title: "選択文字列を title.txt に送る",
  contexts: ["selection"]
});

menus.onClicked.addListener(async (info) => {
  if (info.menuItemId !== "avtext-title") return;
  if (!info.selectionText) return;

  try {
    await browser.runtime.sendNativeMessage("avtext_helper", {
      target: "title",
      text: info.selectionText
    });
  } catch (e) {
    console.error("sendNativeMessage failed:", e);
  }
});
