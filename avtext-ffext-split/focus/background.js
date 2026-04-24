const menus = browser.menus || browser.contextMenus;

menus.create({
  id: "avtext-focus-sakura",
  title: "サクラエディタを前面に",
  contexts: ["all"]
});

menus.onClicked.addListener(async (info) => {
  if (info.menuItemId !== "avtext-focus-sakura") return;

  try {
    await browser.runtime.sendNativeMessage("avtext_helper", {
      target: "focus_sakura",
      text: ""
    });
  } catch (e) {
    console.error("sendNativeMessage failed:", e);
  }
});
