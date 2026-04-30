const baseEl = document.getElementById("base");
const secretEl = document.getElementById("secret");
const saveBtn = document.getElementById("save");
const statusEl = document.getElementById("status");

function fmtTime(ts) {
  if (!ts) return "—";
  const d = new Date(ts);
  return d.toLocaleString("ru-RU");
}

function refresh() {
  chrome.storage.local.get(null, (data) => {
    baseEl.value = data.base || "https://fullsell.onrender.com";
    secretEl.value = data.secret || "";
    let html = "";
    if (data.lastSent) {
      const ageMin = Math.round((Date.now() - data.lastSent) / 60000);
      const cls = data.lastStatus === "ok" ? "ok" : "err";
      html += `<div class="row">Статус: <span class="${cls}">${data.lastStatus || "—"}</span></div>`;
      html += `<div class="row muted">Последний токен отправлен ${ageMin === 0 ? "только что" : ageMin + " мин назад"}</div>`;
      html += `<div class="row muted">Seller ID: ${data.lastSeller || "—"}</div>`;
      html += `<div class="row muted">Время: ${fmtTime(data.lastSent)}</div>`;
    } else {
      html = '<div class="muted">Токен ещё не перехвачен. Откройте кабинет UZUM → раздел «Продвижение».</div>';
    }
    statusEl.innerHTML = html;
  });
}

saveBtn.addEventListener("click", () => {
  const base = (baseEl.value || "").trim().replace(/\/$/, "");
  const secret = (secretEl.value || "").trim();
  chrome.storage.local.set({base, secret}, () => {
    saveBtn.textContent = "Сохранено ✓";
    setTimeout(() => { saveBtn.textContent = "Сохранить"; refresh(); }, 1200);
  });
});

refresh();
setInterval(refresh, 3000);
