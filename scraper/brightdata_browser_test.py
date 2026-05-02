"""
Тест Bright Data Browser API через Playwright connect_over_cdp.
Bright Data сам играет browser, мы просто управляем им через CDP.

Запуск через docker (Playwright уже в образе):
  docker compose --profile scrape run --rm \
    -e BRIGHTDATA_BROWSER_WS="wss://brd-customer-...:PASS@brd.superproxy.io:9222" \
    scraper python brightdata_browser_test.py
"""
import asyncio
import os
import re
import sys
from pathlib import Path

from playwright.async_api import async_playwright

BRD_WS   = os.environ.get("BRIGHTDATA_BROWSER_WS", "").strip()
TEST_URL = os.environ.get("TEST_URL", "https://uzum.uz/ru/category/elektronika-i-bytovaya-tehnika-1")
DUMP     = Path("/state/uzum_brightdata_browser.html")


async def main() -> int:
    if not BRD_WS:
        print("❌ BRIGHTDATA_BROWSER_WS env не задан")
        return 1

    # Маскируем для лога
    masked = BRD_WS[:30] + "..." + BRD_WS[-30:] if len(BRD_WS) > 60 else "***"
    print(f"🌐 Browser API: {masked}")
    print(f"🎯 URL:         {TEST_URL}")
    print()

    async with async_playwright() as pw:
        print("🔌 Connecting to Bright Data Browser API (CDP)...")
        try:
            browser = await pw.chromium.connect_over_cdp(BRD_WS, timeout=60_000)
        except Exception as e:
            print(f"❌ connect_over_cdp failed: {e}")
            return 2
        print("✅ Connected")

        ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = await ctx.new_page()

        # Перехват GraphQL ответов uzum
        captured: list = []
        async def on_response(response):
            if "graphql.uzum.uz" not in response.url:
                return
            try:
                data = await response.json()
            except Exception:
                return
            items = (((data or {}).get("data") or {}).get("makeSearch") or {}).get("items") or []
            captured.extend(items)
        page.on("response", on_response)

        print(f"📥 Loading page (max 180s, wait=networkidle)...")
        try:
            # networkidle = ждём пока сеть утихнет (все XHR/fetch завершились)
            await page.goto(TEST_URL, timeout=180_000, wait_until="networkidle")
        except Exception as e:
            print(f"⚠ networkidle timeout, продолжаем: {e}")

        print(f"   final URL: {page.url}")

        if "showcaptcha" in page.url or "tmgrdfrend" in page.url:
            print("❌ Bright Data НЕ обошёл капчу/403 — попали на showcaptcha")
            await browser.close()
            return 4

        # Дополнительно ждём 15с чтобы SPA точно отрисовалась
        print("⏳ Waiting 15s for SPA render...")
        await page.wait_for_timeout(15_000)

        # Скроллим чтобы догрузить остальное
        print("📜 Scrolling 5x...")
        for _ in range(5):
            try:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            except Exception:
                break
            await page.wait_for_timeout(2000)

        # Финальный wait
        await page.wait_for_timeout(5000)

        # Screenshot для визуальной диагностики
        try:
            await page.screenshot(path="/state/uzum_brightdata_browser.png", full_page=False)
            print(f"📸 Screenshot saved to /state/uzum_brightdata_browser.png")
        except Exception as e:
            print(f"⚠ screenshot failed: {e}")

        # Извлекаем продукты прямо из DOM через querySelectorAll
        try:
            dom_products = await page.evaluate("""
                () => {
                  const cards = document.querySelectorAll('[class*="product"], [class*="card"], [data-test-id*="product"]');
                  return Array.from(cards).slice(0, 5).map(c => ({
                    tag: c.tagName,
                    classes: c.className,
                    text: (c.innerText || '').substring(0, 100),
                  }));
                }
            """)
            if dom_products:
                print(f"🏗 DOM cards found: {len(dom_products)}")
                for p in dom_products[:3]:
                    print(f"   {p}")
        except Exception as e:
            print(f"⚠ DOM query error: {e}")

        html = await page.content()
        try:
            DUMP.parent.mkdir(parents=True, exist_ok=True)
            DUMP.write_text(html, encoding="utf-8")
            print(f"💾 Dumped: {DUMP} ({len(html)} bytes)")
        except Exception as e:
            print(f"⚠ dump failed: {e}")

        # Проверки
        product_ids = sorted(set(re.findall(r'productId["\']?\s*[:=]\s*["\']?(\d{5,})', html)))
        prices = re.findall(r'(\d[\d\s]{3,})\s*сум', html)
        has_brands = any(b in html for b in ["Samsung", "Xiaomi", "iPhone", "Apple", "Honor"])

        print()
        print(f"🛒 Product IDs (regex): {len(product_ids)}")
        print(f"📡 Captured GraphQL items: {len(captured)}")
        print(f"💰 Prices found: {len(prices)}")
        print(f"📱 Brands present: {'✅' if has_brands else '❌'}")

        if captured:
            print()
            print("🎉 УСПЕХ — GraphQL items собраны!")
            for i, item in enumerate(captured[:5], 1):
                card = (item or {}).get("catalogCard") or item or {}
                title = (card.get("title") or "?")[:60]
                price = card.get("minSellPrice") or card.get("sellPrice")
                seller = card.get("sellerTitle") or "?"
                print(f"   {i}. {title} — {price} сум — {seller}")

        await browser.close()

        if captured or (product_ids and has_brands):
            print()
            print("🎉🎉🎉 ВИКТОРИЯ — Bright Data Browser API РАБОТАЕТ с uzum.uz")
            return 0

        print()
        print("⚠️ HTML получили, но продукты не найдены. Загляни в дамп.")
        return 5


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
