"""
Тест Bright Data Web Unlocker REST API + GraphQL POST на uzum.uz
Стратегия: имитируем mobile приложение Uzum Market.

Запуск:
  BRIGHTDATA_API_KEY="..." BRIGHTDATA_ZONE="fullsell" python3 brightdata_graphql_test.py
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

# GraphQL Search query — извлечён из APK uz.uzum.app v1.83.2
SEARCH_QUERY = """
query NewSearch($queryInput: MakeSearchQueryInput!, $requestTodayDealsStocks: Boolean!, $redesignFomoEnabled: Boolean!) {
  makeSearch(query: $queryInput) {
    id total
    category { id title }
    offerCategory { id title }
    items {
      catalogCard {
        __typename
        ... on SkuGroupCard {
          id productId title
          minSellPrice minFullPrice
          rating feedbackQuantity ordersQuantity
        }
      }
      bidId cpoId
    }
  }
}
"""


async def main() -> int:
    if not API_KEY:
        print("❌ BRIGHTDATA_API_KEY не задан")
        return 1

    print(f"🔑 API key: {API_KEY[:6]}...{API_KEY[-4:]}")
    print(f"🌐 Zone:    {ZONE}")
    print()

    # Mobile headers — имитируем Uzum/Market/Android
    mobile_headers = {
        "Content-Type":    "application/json",
        "Accept":          "application/json",
        "Accept-Language": "ru-RU",
        "User-Agent":      "Uzum/Market/Android/1.83.2 (Android 13; SM-G990B)",
        "X-Iid":           str(uuid.uuid4()),
        "X-Platform":      "android",
        "X-App-Version":   "1.83.2",
    }

    # GraphQL body — поиск в категории Electronics (id=1)
    graphql_body = {
        "operationName": "NewSearch",
        "variables": {
            "queryInput": {
                "categoryId": 1,
                "page":       0,
                "showAdultContent": "FALSE",
                "filters":    [],
                "sort":       "BY_RELEVANCE_DESC",
            },
            "requestTodayDealsStocks": False,
            "redesignFomoEnabled":     True,
        },
        "query": SEARCH_QUERY,
    }

    # Bright Data Unlocker payload — proxy запроса с произвольным методом/телом
    bd_payload = {
        "zone":    ZONE,
        "url":     "https://graphql.uzum.uz/",
        "method":  "POST",
        "format":  "raw",
        "country": "uz",
        "headers": mobile_headers,
        "body":    json.dumps(graphql_body),
    }

    print("📦 Отправляю на Bright Data...")
    print(f"   target:  https://graphql.uzum.uz/")
    print(f"   method:  POST")
    print(f"   ua:      {mobile_headers['User-Agent']}")
    print()

    async with httpx.AsyncClient(timeout=180) as c:
        r = await c.post(
            API_URL,
            json=bd_payload,
            headers={"Authorization": f"Bearer {API_KEY}"},
        )

    print(f"📥 HTTP {r.status_code}, размер {len(r.text)} байт")

    if r.status_code != 200:
        print(f"❌ Ошибка от Bright Data:")
        print(r.text[:1000])
        return 2

    text = r.text
    # Сохраняем для разбора
    try:
        with open("/tmp/uzum_graphql.json", "w", encoding="utf-8") as f:
            f.write(text)
        print(f"💾 Saved to /tmp/uzum_graphql.json")
    except Exception:
        pass

    # Капча/бан?
    if "showcaptcha" in text or "Доступ к&nbsp;сервису" in text or "Доступ к сервису" in text:
        print("❌ Yandex Cloud 403 — даже mobile-style не пройдёт")
        print(text[:500])
        return 3

    # Парсим JSON
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        print(f"⚠ Не JSON: {e}")
        print(text[:1000])
        return 4

    if "errors" in data:
        print(f"⚠ GraphQL errors:")
        for err in data["errors"][:5]:
            print(f"   {err.get('message', err)[:200]}")
        # Может быть всё равно полезный data

    search = (((data or {}).get("data") or {}).get("makeSearch") or {})
    items = search.get("items") or []
    total = search.get("total")

    print()
    print(f"📊 makeSearch.total: {total}")
    print(f"📦 items.length:     {len(items)}")

    if items:
        print()
        print("🎉🎉🎉 ПОБЕДА — реальные данные UZUM через mobile API!")
        print()
        for i, item in enumerate(items[:5], 1):
            card = (item or {}).get("catalogCard") or {}
            title = (card.get("title") or "?")[:60]
            price = card.get("minSellPrice")
            rating = card.get("rating")
            orders = card.get("ordersQuantity")
            print(f"   {i}. {title}")
            print(f"      💰 {price} сум | ⭐ {rating} | 📦 {orders} заказов")
        return 0

    print()
    print("⚠ items пустой. Полный ответ:")
    print(json.dumps(data, indent=2, ensure_ascii=False)[:2000])
    return 5


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
