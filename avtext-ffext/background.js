const menus = browser.menus || browser.contextMenus;

// 右クリック直下に並べる（親メニューは作らない）
menus.create({
  id: "avtext-title",
  title: "選択文字列を title.txt に送る",
  contexts: ["selection"]
});

menus.create({
  id: "avtext-actress",
  title: "選択文字列を actress.txt に送る",
  contexts: ["selection"]
});

// no.txt
menus.create({
  id: "avtext-no",
  title: "選択文字列を no.txt に送る",
  contexts: ["selection"]
});

// 選択がある時だけ区切り線を出す（選択なし右クリックで線だけ残るのを防ぐ）
menus.create({
  id: "avtext-sep-1",
  type: "separator",
  contexts: ["selection"]
});

// 選択が無くても出したいなら all
menus.create({
  id: "avtext-focus-sakura",
  title: "サクラエディタを前面に",
  contexts: ["all"]
});

menus.onClicked.addListener(async (info) => {
  const hasSel = !!info.selectionText;

  let target = null;
  let text = "";

  if (info.menuItemId === "avtext-title") {
    if (!hasSel) return;
    target = "title";
    text = info.selectionText;
  } else if (info.menuItemId === "avtext-actress") {
    if (!hasSel) return;
    target = "actress";
    text = info.selectionText;
  } else if (info.menuItemId === "avtext-no") {
    if (!hasSel) return;
    target = "no";
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
