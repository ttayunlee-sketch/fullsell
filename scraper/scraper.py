"""
UZUM market scraper.
Открывает категории uzum.uz через headless Chrome, перехватывает GraphQL-ответы
makeSearch (которые делает фронтенд при скролле) и складывает товары в БД.
"""
import asyncio
import json
import os
from datetime import date
from typing import List, Dict, Any, Optional

from playwright.async_api import async_playwright, Page, BrowserContext, Response
from captcha import solve_yandex_captcha

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
STATE_FILE = "/state/state.json"

# Fallback-список топ-категорий uzum.uz (slug'и видны в навигации сайта).
# Используется если API /api/main/root-categories не отвечает.
FALLBACK_CATEGORY_SLUGS = [
    "elektronika-i-bytovaya-tehnika-1",
    "smartfony-i-telefony-2",
    "kompyutery-i-noutbuki-3",
    "odezhda-4",
    "obuv-5",
    "krasota-i-zdorove-6",
    "produkty-pitaniya-7",
    "tovary-dlya-doma-8",
    "detskie-tovary-9",
    "sport-i-otdyh-10",
    "knigi-i-hobby-11",
    "avtotovary-12",
    "stroitelstvo-i-remont-13",
    "zoologicheskie-tovary-14",
    "uhod-za-soboi-15",
]

# ── Конфигурация прогона ─────────────────────────────────────────────────────
TOP_CATEGORIES_LIMIT = int(os.environ.get("SCRAPER_TOP_CATS", "50"))
PRODUCTS_PER_CATEGORY = int(os.environ.get("SCRAPER_PRODUCTS_PER_CAT", "200"))
SCROLL_ROUNDS = int(os.environ.get("SCRAPER_SCROLLS", "8"))
PAGE_TIMEOUT = int(os.environ.get("SCRAPER_PAGE_TIMEOUT", "45000"))


# ─────────────────────────────────────────────────────────────────────────────
# Browser context
# ─────────────────────────────────────────────────────────────────────────────

async def _launch_context(p):
    """Запуск Chromium с реалистичными параметрами + сохранённой сессией.
    Если задан UZUM_PROXY (http://user:pass@host:port) — весь трафик идёт через него."""
    proxy_url = os.environ.get("UZUM_PROXY", "").strip()
    # Удобный alias: если задан ZENROWS_API_KEY — собираем proxy URL автоматически
    zr_key = os.environ.get("ZENROWS_API_KEY", "").strip()
    if zr_key and not proxy_url:
        # ZenRows proxy-mode: API key как username, параметры как password
        # premium_proxy=true → residential IPs (платный план)
        # без него — datacenter IPs (бесплатный trial)
        zr_password = "premium_proxy=true" if os.environ.get("ZENROWS_PREMIUM") else ""
        proxy_url = f"http://{zr_key}:{zr_password}@proxy.zenrows.com:8001"
    launch_kwargs = {
        "headless": True,
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ],
    }
    browser = await p.chromium.launch(**launch_kwargs)

    storage_state = STATE_FILE if os.path.exists(STATE_FILE) else None
    ctx_kwargs = {
        "user_agent": USER_AGENT,
        "viewport": {"width": 1920, "height": 1080},
        "locale": "ru-RU",
        "timezone_id": "Asia/Tashkent",
        "storage_state": storage_state,
        "java_script_enabled": True,
    }
    if proxy_url:
        # Playwright proxy spec: {server, username?, password?}
        from urllib.parse import urlparse, unquote
        u = urlparse(proxy_url)
        proxy_spec = {"server": f"{u.scheme}://{u.hostname}:{u.port or 8080}"}
        if u.username: proxy_spec["username"] = unquote(u.username)
        if u.password: proxy_spec["password"] = unquote(u.password)
        ctx_kwargs["proxy"] = proxy_spec
        ctx_kwargs["ignore_https_errors"] = True   # на случай если прокси перевыпускает TLS
        print(f"[scraper] proxy enabled: {u.hostname}:{u.port} (user={u.username[:8] if u.username else 'none'}...)", flush=True)

    ctx = await browser.new_context(**ctx_kwargs)
    # Маскируем webdriver-флаг
    await ctx.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
    )
    return browser, ctx


async def _save_state(ctx: BrowserContext):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    await ctx.storage_state(path=STATE_FILE)


# ─────────────────────────────────────────────────────────────────────────────
# Captcha detection (Yandex SmartCaptcha)
# ─────────────────────────────────────────────────────────────────────────────

async def _is_captcha(page: Page) -> bool:
    url = page.url
    return "showcaptcha" in url or "tmgrdfrend" in url


async def _warmup(page: Page):
    """Заходит на главную, при необходимости решает капчу через 2captcha."""
    print(f"[scraper] warmup: navigating to uzum.uz", flush=True)
    try:
        await page.goto("https://uzum.uz/ru", timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")
    except Exception as e:
        print(f"[scraper] warmup goto error: {e}", flush=True)
        return False
    await page.wait_for_timeout(3000)

    # Если попали на капчу — решаем через 2captcha
    if await _is_captcha(page):
        print(f"[scraper] CAPTCHA on warmup → trying 2captcha", flush=True)
        ok = await solve_yandex_captcha(page)
        if not ok:
            print(f"[scraper] CAPTCHA solve FAILED — aborting", flush=True)
            return False
        # после решения капчи ждём догрузки страницы
        await page.wait_for_timeout(2000)

    print(f"[scraper] warmup OK: {page.url}", flush=True)
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Categories tree
# ─────────────────────────────────────────────────────────────────────────────

async def fetch_root_categories(page: Page) -> List[Dict[str, Any]]:
    """Достаём дерево категорий через APIRequestContext (минует CORS, идёт через прокси).
    Если эндпоинт ничего не отдал — возвращаем пустой список (потом scrape_category всё
    равно работает, мы просто не сохраним красивое дерево)."""
    raw = None
    try:
        # context.request — серверный HTTP через тот же прокси, без браузерного CORS
        resp = await page.context.request.get(
            "https://api.uzum.uz/api/main/root-categories",
            headers={
                "Accept": "application/json",
                "Accept-Language": "ru,en;q=0.9",
                "Referer": "https://uzum.uz/ru",
            },
            timeout=30000,
        )
        if resp.ok:
            raw = await resp.json()
        else:
            print(f"[scraper] root-categories HTTP {resp.status}", flush=True)
    except Exception as e:
        print(f"[scraper] root-categories request error: {e}", flush=True)

    if not raw:
        print("[scraper] root-categories empty — будем сканить хардкод-список slug'ов", flush=True)
        return []
    # Структура зависит от API, обычно {payload: [...]} или сразу массив
    items = raw.get("payload") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        items = []
    flat: List[Dict[str, Any]] = []

    def walk(node, parent_id, level):
        cat_id = node.get("id")
        if cat_id is None:
            return
        title = node.get("title") or node.get("title_ru") or node.get("name") or ""
        slug = node.get("seoLink") or node.get("seo") or node.get("slug") or ""
        if isinstance(title, dict):
            title = title.get("ru") or title.get("uz") or ""
        flat.append({
            "category_id": cat_id,
            "slug": slug,
            "title_ru": title,
            "parent_id": parent_id,
            "level": level,
        })
        for child in (node.get("children") or []):
            walk(child, cat_id, level + 1)

    for top in items:
        walk(top, None, 1)

    print(f"[scraper] categories: total {len(flat)}", flush=True)
    return flat


# ─────────────────────────────────────────────────────────────────────────────
# Per-category scraping via response interception
# ─────────────────────────────────────────────────────────────────────────────

def _parse_card(item: Dict[str, Any], category_id: int) -> Optional[Dict[str, Any]]:
    """Извлекает поля из item.catalogCard."""
    card = item.get("catalogCard") or item
    if not isinstance(card, dict):
        return None
    pid = card.get("productId") or card.get("id")
    if not pid:
        return None
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None

    title = card.get("title") or card.get("title_ru") or ""
    if isinstance(title, dict):
        title = title.get("ru") or title.get("uz") or ""

    seller_id = card.get("sellerId") or (card.get("seller") or {}).get("id")
    seller_title = card.get("sellerTitle") or (card.get("seller") or {}).get("title") or ""

    # Цена: minSellPrice / sellPrice / fullPrice / price.value
    price = card.get("minSellPrice") or card.get("sellPrice") or card.get("fullPrice")
    if isinstance(price, dict):
        price = price.get("value") or price.get("amount")
    if price is None:
        priceobj = card.get("price")
        if isinstance(priceobj, dict):
            price = priceobj.get("value") or priceobj.get("amount")

    orders = card.get("ordersAmount") or card.get("orders_amount") or card.get("salesCount") or 0

    rating = card.get("rating")
    if isinstance(rating, dict):
        rating = rating.get("value")

    reviews = card.get("reviewsAmount") or card.get("reviews_count") or card.get("commentsCount") or 0

    try:
        return {
            "product_id":    int(pid),
            "category_id":   int(category_id) if category_id else None,
            "seller_id":     int(seller_id) if seller_id else None,
            "title_ru":      str(title)[:500] if title else None,
            "price":         int(price) if price else None,
            "orders_amount": int(orders) if orders else 0,
            "rating":        float(rating) if rating else None,
            "reviews_count": int(reviews) if reviews else 0,
            "_seller_title": str(seller_title)[:300] if seller_title else None,
        }
    except (TypeError, ValueError):
        return None


async def scrape_category(page: Page, slug: str, category_id: int) -> List[Dict[str, Any]]:
    """Открывает категорию, скроллит, перехватывает GraphQL-ответы и парсит карточки."""
    captured: List[Dict[str, Any]] = []
    seen_ids: set = set()

    async def on_response(response: Response):
        if "graphql.uzum.uz" not in response.url:
            return
        try:
            data = await response.json()
        except Exception:
            return
        # Ответ MakeSearch содержит data.makeSearch.items
        items = (((data or {}).get("data") or {}).get("makeSearch") or {}).get("items") or []
        if not items:
            return
        for it in items:
            row = _parse_card(it, category_id)
            if row and row["product_id"] not in seen_ids:
                seen_ids.add(row["product_id"])
                captured.append(row)

    page.on("response", on_response)
    url = f"https://uzum.uz/ru/category/{slug}"
    try:
        await page.goto(url, timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")
    except Exception as e:
        print(f"[scraper] category goto failed {slug}: {e}", flush=True)
        page.remove_listener("response", on_response)
        return []

    if await _is_captcha(page):
        print(f"[scraper] CAPTCHA on category {slug} → 2captcha", flush=True)
        ok = await solve_yandex_captcha(page)
        if not ok:
            print(f"[scraper] could not solve captcha on {slug}", flush=True)
            page.remove_listener("response", on_response)
            return []
        # После решения переходим заново чтобы триггернуть GraphQL заново
        try:
            await page.goto(url, timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")
        except Exception:
            pass

    # Скроллим, чтобы фронт догрузил товары
    for i in range(SCROLL_ROUNDS):
        if len(captured) >= PRODUCTS_PER_CATEGORY:
            break
        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        except Exception:
            break
        await page.wait_for_timeout(1500)

    # Финальный wait
    await page.wait_for_timeout(2000)

    page.remove_listener("response", on_response)
    print(f"[scraper] {slug}: captured {len(captured)} cards", flush=True)
    return captured[:PRODUCTS_PER_CATEGORY]


# ─────────────────────────────────────────────────────────────────────────────
# Main entry
# ─────────────────────────────────────────────────────────────────────────────

async def run_full_scrape(snap: date, save_categories_fn, save_products_fn,
                          aggregate_fn, update_titles_fn) -> dict:
    stats = {"categories": 0, "products": 0, "sellers": 0, "captcha_hits": 0}

    async with async_playwright() as p:
        browser, ctx = await _launch_context(p)
        page = await ctx.new_page()

        ok = await _warmup(page)
        if not ok:
            stats["captcha_hits"] += 1
            await browser.close()
            return stats

        # 1. Категории
        cats = await fetch_root_categories(page)
        if cats:
            save_categories_fn(snap, cats)
            stats["categories"] = len(cats)
            # Берём только категории с непустым slug
            candidates = [c for c in cats if c.get("slug") and c.get("level", 1) <= 2][:TOP_CATEGORIES_LIMIT]
        else:
            # Fallback: используем хардкод slug-список
            print("[scraper] using FALLBACK_CATEGORY_SLUGS", flush=True)
            candidates = [
                {"slug": slug, "category_id": -i}
                for i, slug in enumerate(FALLBACK_CATEGORY_SLUGS, start=1)
            ][:TOP_CATEGORIES_LIMIT]
            stats["categories"] = len(candidates)
        print(f"[scraper] scraping {len(candidates)} top categories", flush=True)

        seller_titles: Dict[int, str] = {}

        for i, cat in enumerate(candidates, 1):
            print(f"[scraper] [{i}/{len(candidates)}] {cat['slug']}", flush=True)
            try:
                items = await scrape_category(page, cat["slug"], cat["category_id"])
            except Exception as e:
                print(f"[scraper] category {cat['slug']} error: {e}", flush=True)
                items = []

            if items:
                # Собираем seller_title отдельно (поле _seller_title не идёт в save_products)
                for it in items:
                    sid = it.get("seller_id")
                    st = it.pop("_seller_title", None)
                    if sid and st:
                        seller_titles.setdefault(sid, st)
                save_products_fn(snap, items)
                stats["products"] += len(items)

            # Пауза между категориями — снижаем шанс капчи
            await page.wait_for_timeout(800)

        # 3. Сохраняем cookies для следующего запуска
        try:
            await _save_state(ctx)
        except Exception as e:
            print(f"[scraper] save state error: {e}", flush=True)

        await browser.close()

    # 4. Агрегация
    agg = aggregate_fn(snap)
    stats["sellers"] = agg.get("sellers", 0)

    # 5. Обновляем seller titles
    if seller_titles:
        update_titles_fn(snap, seller_titles)
        print(f"[scraper] updated {len(seller_titles)} seller titles", flush=True)

    return stats
