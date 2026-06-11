const menus = browser.menus || browser.contextMenus;

const menuItems = [
  { id: "avtext-title", title: "タイトルに送る", target: "title" },
  { id: "avtext-actress", title: "女優名に送る", target: "actress" },
  { id: "avtext-actress-with-alias", title: "女優名に送る（別名付き）", target: "actress_with_alias" },
  { id: "avtext-actress-append", title: "女優に追加", target: "actress_append" },
  { id: "avtext-actress-append-with-alias", title: "女優に別名で追加", target: "actress_append_with_alias" },
  { id: "avtext-no", title: "品番に送る", target: "no" },
  { id: "avtext-focus-sakura", title: "サクラエディタを前面に", target: "focus_sakura", contexts: ["all"] }
];

const menuById = new Map(menuItems.map((item) => [item.id, item]));

async function sendToNative(target, text) {
  return browser.runtime.sendNativeMessage("avtext_helper", {
    target,
    text
  });
}

for (const item of menuItems) {
  menus.create({
    id: item.id,
    title: item.title,
    contexts: item.contexts || ["selection"]
  });
}

menus.onClicked.addListener(async (info) => {
  const item = menuById.get(info.menuItemId);
  if (!item) {
    return;
  }

  if (item.contexts?.includes("selection") && !info.selectionText) {
    return;
  }

  const target = item.target;
  const text = info.selectionText || "";

  try {
    await sendToNative(target, text);
  } catch (e) {
    console.error("sendNativeMessage failed:", e);
  }
});
