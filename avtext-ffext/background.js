const menus = browser.menus || browser.contextMenus;

const ROOT_MENU_ID = "avtext-root";
const menuItems = [
  { id: "avtext-title", title: "タイトルに送る", target: "title" },
  { id: "avtext-actress", title: "女優名に送る", target: "actress" },
  { id: "avtext-actress-with-alias", title: "女優名に送る（別名付き）", target: "actress_with_alias" },
  { id: "avtext-no", title: "品番に送る", target: "no" }
];

const menuById = new Map(menuItems.map((item) => [item.id, item]));

menus.create({
  id: ROOT_MENU_ID,
  title: "AV Text",
  contexts: ["selection"]
});

for (const item of menuItems) {
  menus.create({
    id: item.id,
    parentId: ROOT_MENU_ID,
    title: item.title,
    contexts: ["selection"]
  });
}

menus.create({
  id: "avtext-focus-sakura",
  title: "サクラエディタを前面に",
  contexts: ["all"]
});

menus.onClicked.addListener(async (info) => {
  const item = menuById.get(info.menuItemId);
  let target = null;
  let text = "";

  if (item) {
    if (!info.selectionText) return;
    target = item.target;
    text = info.selectionText;
  } else if (info.menuItemId === "avtext-focus-sakura") {
    target = "focus_sakura";
  } else {
    return;
  }

  try {
    await browser.runtime.sendNativeMessage("avtext_helper", {
      target,
      text
    });
  } catch (e) {
    console.error("sendNativeMessage failed:", e);
  }
});
