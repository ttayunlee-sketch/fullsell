"""
Тест Bright Data Unlocker API — пробуем скачать категорию uzum.uz
без Playwright/прокси/капчи. Bright Data сам обходит защиту.

Запуск:
  export BRIGHTDATA_API_KEY="..."
  export BRIGHTDATA_ZONE="fullsell"
  python brightdata_test.py
"""
import asyncio
import os
import re
import sys
from pathlib import Path

import httpx

API_URL  = "https://api.brightdata.com/request"
API_KEY  = os.environ.get("BRIGHTDATA_API_KEY", "").strip()
ZONE     = os.environ.get("BRIGHTDATA_ZONE", "fullsell").strip()
TEST_URL = os.environ.get("TEST_URL", "https://uzum.uz/ru/category/elektronika-i-bytovaya-tehnika-1")

DUMP_PATH = Path("/tmp/uzum_brightdata.html")


async def main() -> int:
    if not API_KEY:
        print("❌ BRIGHTDATA_API_KEY не задан. Сначала: export BRIGHTDATA_API_KEY='...'")
        return 1

    print(f"🌐 Запрос на {TEST_URL}")
    print(f"   Zone: {ZONE}")
    print(f"   API key: {API_KEY[:6]}...{API_KEY[-4:]}")
    print()

    async with httpx.AsyncClient(timeout=180) as c:
        try:
            r = await c.post(
                API_URL,
                json={
                    "zone":   ZONE,
                    "url":    TEST_URL,
                    "format": "raw",
                },
                headers={"Authorization": f"Bearer {API_KEY}"},
            )
        except Exception as e:
            print(f"❌ Ошибка сети: {e}")
            return 2

    print(f"📥 HTTP {r.status_code}, размер: {len(r.text)} байт")

    if r.status_code != 200:
        print(f"❌ Bright Data вернул ошибку:")
        print(r.text[:500])
        return 3

    # Сохраняем для анализа
    DUMP_PATH.write_text(r.text, encoding="utf-8")
    print(f"💾 Сохранено в {DUMP_PATH}")
    print()

    # Анализируем содержимое
    html = r.text

    if "showcaptcha" in html or "Доступ к&nbsp;сервису" in html or "Доступ к сервису" in html:
        print("❌ В ответе капча/403! Bright Data НЕ обошёл защиту.")
        print("   Первые 500 символов:")
        print(html[:500])
        return 4

    # Ищем признаки нормальной uzum-страницы
    has_uzum_title = "Uzum Market" in html or "uzum.uz" in html
    print(f"🏷  Есть 'Uzum Market' / 'uzum.uz' в HTML: {'✅' if has_uzum_title else '❌'}")

    # Ищем продукты — несколько стратегий
    product_id_matches = re.findall(r'(?:productId|"id")["\']?\s*[:=]\s*["\']?(\d{5,})', html)
    product_ids = sorted(set(product_id_matches))
    print(f"🛒 Уникальных product ID найдено: {len(product_ids)}")
    if product_ids:
        print(f"   Первые 5: {product_ids[:5]}")

    price_matches = re.findall(r'(\d[\d\s ]{3,})\s*(?:сум|som)', html)
    print(f"💰 Цен (с 'сум') найдено: {len(price_matches)}")

    title_matches = re.findall(r'"title"\s*:\s*"([^"]{5,80})"', html)
    print(f"📝 Title-полей в JSON: {len(title_matches)}")
    if title_matches:
        print(f"   Примеры: {title_matches[:3]}")

    # Smartphone? Электроника?
    has_brands = any(b in html for b in ["Samsung", "Xiaomi", "iPhone", "Apple", "Honor"])
    print(f"📱 Бренды (Samsung/Xiaomi/iPhone/...): {'✅' if has_brands else '❌'}")

    print()
    if product_ids and (price_matches or title_matches):
        print("🎉 УСПЕХ! Bright Data вернул реальные продукты uzum.uz")
        return 0
    else:
        print("⚠️  HTML получили, но продукты не распознаются.")
        print("   Загляни в /tmp/uzum_brightdata.html — посмотри структуру.")
        return 5


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
