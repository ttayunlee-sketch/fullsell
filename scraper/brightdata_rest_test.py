"""
Тест Bright Data Web Unlocker → простой GET на api.uzum.uz REST endpoints.
Имитируем mobile приложение.
"""
import asyncio
import json
import os
import sys
import uuid

import httpx

API_URL = "https://api.brightdata.com/request"
API_KEY = os.environ.get("BRIGHTDATA_API_KEY", "").strip()
ZONE    = os.environ.get("BRIGHTDATA_ZONE", "fullsell").strip()

# Список endpoints для проверки — от простого к сложному
TARGETS = [
    "https://api.uzum.uz/api/main/root-categories",
    "https://api.uzum.uz/api/main/banners",
    "https://api.uzum.uz/api/main/promo-categories",
    "https://api.uzum.uz/api/v2/main/",
    "https://api.uzum.uz/api/v2/product/popular",
]


async def try_url(client, url):
    mobile_headers = {
        "Accept":          "application/json",
        "Accept-Language": "ru-RU",
        "User-Agent":      "Uzum/Market/Android/1.83.2 (Android 13; SM-G990B)",
        "X-Iid":           str(uuid.uuid4()),
        "X-Platform":      "android",
        "X-App-Version":   "1.83.2",
    }
    payload = {
        "zone":    ZONE,
        "url":     url,
        "method":  "GET",
        "format":  "raw",
        "country": "uz",
        "headers": mobile_headers,
    }
    print(f"\n🎯 GET {url}")
    try:
        r = await client.post(
            API_URL,
            json=payload,
            headers={"Authorization": f"Bearer {API_KEY}"},
        )
    except Exception as e:
        print(f"   ❌ network: {e}")
        return

    print(f"   📥 HTTP {r.status_code}, {len(r.text)} bytes")
    text = r.text

    # Признаки бана
    if "showcaptcha" in text or "Доступ к&nbsp;сервису" in text or "Доступ к сервису" in text:
        print("   ❌ Yandex Cloud 403")
        return
    if not text.strip():
        print("   ⚠ пустое тело")
        return

    # JSON?
    try:
        data = json.loads(text)
        print(f"   ✅ JSON: тип={type(data).__name__}")
        if isinstance(data, list):
            print(f"      items: {len(data)}")
            if data:
                first = data[0] if isinstance(data[0], dict) else None
                if first:
                    print(f"      keys[0]: {list(first.keys())[:8]}")
        elif isinstance(data, dict):
            print(f"      keys: {list(data.keys())[:8]}")
            if "payload" in data:
                pl = data["payload"]
                if isinstance(pl, list):
                    print(f"      payload[items]: {len(pl)}")
                    if pl and isinstance(pl[0], dict):
                        print(f"      payload[0].keys: {list(pl[0].keys())[:8]}")
        # Сохраняем удачные
        with open(f"/tmp/uzum_{url.split('/')[-1] or 'main'}.json", "w") as f:
            f.write(text[:5000])
        print(f"   💾 saved")
        return data
    except json.JSONDecodeError:
        print(f"   ⚠ не JSON. Первые 200: {text[:200]}")


async def main() -> int:
    if not API_KEY:
        print("❌ BRIGHTDATA_API_KEY не задан")
        return 1
    print(f"🔑 {API_KEY[:6]}...{API_KEY[-4:]} · zone={ZONE}")

    async with httpx.AsyncClient(timeout=120) as c:
        for url in TARGETS:
            await try_url(c, url)

    print("\n✅ Тесты завершены — смотри какой endpoint вернул JSON")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
