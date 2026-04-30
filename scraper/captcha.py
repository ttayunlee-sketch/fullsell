"""
Решение Яндекс SmartCaptcha через 2captcha.com.

API: https://2captcha.com/2captcha-api#yandex_smart
"""
import asyncio
import os
import re
import httpx

API_KEY = os.environ.get("TWOCAPTCHA_API_KEY", "").strip()
TWOCAP_URL = "https://2captcha.com"


async def _2cap_in(sitekey: str, pageurl: str) -> str | None:
    """Отправляет задачу, возвращает captcha_id."""
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(
            f"{TWOCAP_URL}/in.php",
            data={
                "key":     API_KEY,
                "method":  "yandex",
                "sitekey": sitekey,
                "pageurl": pageurl,
                "json":    "1",
            },
        )
    j = r.json()
    if j.get("status") == 1:
        return j.get("request")
    print(f"[captcha] in.php error: {j}", flush=True)
    return None


async def _2cap_res(captcha_id: str, max_wait: int = 180) -> str | None:
    """Поллит результат каждые 5 сек, до max_wait сек. Возвращает токен или None."""
    deadline = max_wait
    elapsed = 0
    async with httpx.AsyncClient(timeout=20) as c:
        while elapsed < deadline:
            await asyncio.sleep(5)
            elapsed += 5
            r = await c.get(
                f"{TWOCAP_URL}/res.php",
                params={"key": API_KEY, "action": "get", "id": captcha_id, "json": 1},
            )
            j = r.json()
            if j.get("status") == 1:
                return j.get("request")
            req = str(j.get("request") or "")
            if req == "CAPCHA_NOT_READY":
                continue
            if req.startswith("ERROR"):
                print(f"[captcha] res.php error: {req}", flush=True)
                return None
    print("[captcha] timeout waiting for token", flush=True)
    return None


async def solve_yandex_captcha(page) -> bool:
    """Если текущая страница — showcaptcha, решаем через 2captcha и сабмитим форму.
    Возвращает True если после решения капча ушла."""
    if not API_KEY:
        print("[captcha] no TWOCAPTCHA_API_KEY env, skipping", flush=True)
        return False

    if "showcaptcha" not in page.url and "tmgrdfrend" not in page.url:
        return True   # уже не на капче

    print(f"[captcha] solving on {page.url[:120]}...", flush=True)

    # 1. Извлекаем sitekey — он живёт в iframe src или в window.SmartCaptcha
    sitekey = await page.evaluate(
        """
        () => {
          // ищем iframe с captcha
          for (const f of document.querySelectorAll('iframe')) {
            const src = f.src || '';
            const m = src.match(/sitekey=([A-Za-z0-9_-]+)/) || src.match(/key=([A-Za-z0-9_-]+)/);
            if (m) return m[1];
          }
          // ищем в data-атрибутах
          for (const el of document.querySelectorAll('[data-sitekey]')) {
            const v = el.getAttribute('data-sitekey');
            if (v) return v;
          }
          return null;
        }
        """
    )
    if not sitekey:
        # fallback: парсим HTML страницы
        html = await page.content()
        m = re.search(r'(?:sitekey|data-sitekey)["\']?\s*[=:]\s*["\']([A-Za-z0-9_-]+)', html)
        sitekey = m.group(1) if m else None

    if not sitekey:
        print("[captcha] could NOT extract sitekey", flush=True)
        return False

    print(f"[captcha] sitekey={sitekey[:30]}...", flush=True)

    # 2. Отправляем в 2captcha
    cid = await _2cap_in(sitekey, page.url)
    if not cid:
        return False
    print(f"[captcha] submitted to 2captcha id={cid}, waiting...", flush=True)

    # 3. Ждём решения (среднее время ~30s)
    token = await _2cap_res(cid)
    if not token:
        return False
    print(f"[captcha] got token (len={len(token)}), submitting...", flush=True)

    # 4. Вставляем токен в форму и сабмитим
    submitted = await page.evaluate(
        f"""
        (token) => {{
          const inp = document.querySelector('input[name="smart-token"]')
                   || document.querySelector('input[name="rep"]')
                   || document.querySelector('input[name="captcha-token"]');
          if (inp) {{ inp.value = token; }}
          // Попытка submit'а через стандартный механизм Яндекс SmartCaptcha
          if (window.smartCaptcha && window.smartCaptcha.execute) {{
            try {{ window.smartCaptcha.execute(token); return 'execute'; }} catch(e) {{}}
          }}
          const form = document.querySelector('form');
          if (form) {{ form.submit(); return 'form-submit'; }}
          return 'no-form';
        }}
        """,
        token,
    )
    print(f"[captcha] submit method: {submitted}", flush=True)

    # 5. Ждём редирект обратно на uzum.uz
    try:
        await page.wait_for_url(lambda u: "showcaptcha" not in u and "tmgrdfrend" not in u, timeout=30000)
    except Exception:
        pass

    success = "showcaptcha" not in page.url and "tmgrdfrend" not in page.url
    print(f"[captcha] post-submit url: {page.url[:120]}, success={success}", flush=True)
    return success
