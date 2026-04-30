// FullSell Connector — перехватывает Bearer-токен из api-seller.uzum.uz/api/seller/*
// и отправляет в FullSell для использования рекламных endpoint'ов кабинета.

const DEFAULT_BASE = "https://fullsell.onrender.com";

async function getConfig() {
  const data = await chrome.storage.local.get(["base", "secret", "lastToken", "lastSeller", "lastSent"]);
  return {
    base: data.base || DEFAULT_BASE,
    secret: data.secret || "",
    lastToken: data.lastToken || "",
    lastSeller: data.lastSeller || "",
    lastSent: data.lastSent || 0,
  };
}

async function sendToFullSell(token, sellerId) {
  const cfg = await getConfig();
  if (!cfg.secret) {
    console.warn("[FullSell] secret не задан, токен не отправлен");
    return;
  }
  // не дёргаем сервер чаще раза в 30 сек на тот же токен
  if (cfg.lastToken === token && cfg.lastSeller === String(sellerId) && (Date.now() - cfg.lastSent) < 30000) {
    return;
  }
  try {
    const resp = await fetch(`${cfg.base}/api/extension/token`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({token, sellerId: parseInt(sellerId), secret: cfg.secret}),
    });
    const ok = resp.ok;
    await chrome.storage.local.set({
      lastToken: token, lastSeller: String(sellerId), lastSent: Date.now(),
      lastStatus: ok ? "ok" : `error ${resp.status}`,
    });
    console.log(`[FullSell] Token sent for seller ${sellerId}: ${ok ? "OK" : resp.status}`);
  } catch (err) {
    console.error("[FullSell] Не удалось отправить токен:", err);
    await chrome.storage.local.set({lastStatus: "network error"});
  }
}

chrome.webRequest.onBeforeSendHeaders.addListener(
  (details) => {
    const auth = details.requestHeaders?.find(h => h.name.toLowerCase() === "authorization");
    if (!auth || !auth.value) return;
    const token = auth.value.replace(/^Bearer\s+/i, "").trim();
    if (!token || token.length < 10) return;

    // sellerId либо из query, либо из path /seller/{id}/...
    let sellerId = null;
    try {
      const u = new URL(details.url);
      sellerId = u.searchParams.get("sellerId");
      if (!sellerId) {
        const m = u.pathname.match(/\/seller\/(\d+)/);
        if (m) sellerId = m[1];
      }
    } catch {}
    if (!sellerId) return;

    sendToFullSell(token, sellerId);
  },
  {urls: ["https://api-seller.uzum.uz/api/seller/*"]},
  ["requestHeaders"]
);

// Pong для popup чтобы посмотреть статус
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg?.type === "getStatus") {
    chrome.storage.local.get(null, (data) => sendResponse(data));
    return true;
  }
});
