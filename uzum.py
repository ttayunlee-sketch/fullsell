import time
import requests

SELLER_URL = "https://api-seller.uzum.uz/api/seller-openapi"

_CACHE: dict = {}
_CACHE_TTL = 300  # 5 минут

_HEADERS = {
    "Authorization": "",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Accept": "application/json",
}

def _h(api_key: str) -> dict:
    return {**_HEADERS, "Authorization": api_key}

def get_products(api_key: str, shop_id: int, filter_type: str = "ALL", force: bool = False) -> list:
    key = (shop_id, filter_type)
    now = time.time()
    if not force:
        cached = _CACHE.get(key)
        if cached and now - cached[0] < _CACHE_TTL:
            return cached[1]
    try:
        r = requests.get(
            f"{SELLER_URL}/v1/product/shop/{shop_id}",
            headers=_h(api_key),
            params={"page": 0, "size": 50, "filter": filter_type, "lang": "ru"},
            timeout=10
        )
        if r.status_code == 200:
            data = r.json().get("productList", [])
            _CACHE[key] = (now, data)
            return data
    except Exception:
        pass
    cached = _CACHE.get(key)
    return cached[1] if cached else []


def invalidate_cache(shop_id: int = None):
    if shop_id is None:
        _CACHE.clear()
    else:
        for k in list(_CACHE.keys()):
            if k[0] == shop_id:
                _CACHE.pop(k, None)


CABINET_BASE = "https://api-seller.uzum.uz"


def _cabinet_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Accept-Language": "ru",
        "Origin": "https://seller.uzum.uz",
        "Referer": "https://seller.uzum.uz/",
    }


def get_ad_campaigns(cabinet_token: str, seller_id: int, days: int = 30) -> dict:
    """Список рекламных кампаний 'Буст в ТОП' из cabinet API."""
    if not cabinet_token or not seller_id:
        return {"items": [], "error": "no_token"}
    from datetime import datetime, timedelta
    to_d = datetime.now().date()
    from_d = to_d - timedelta(days=days)
    items = []
    page = 0
    error = None
    page_size = 20  # UZUM cabinet API возвращает 400 при size > 20
    while page < 50:
        try:
            r = requests.get(
                f"{CABINET_BASE}/api/seller/advertising/management/ad-campaign",
                headers=_cabinet_headers(cabinet_token),
                params={
                    "sellerId": int(seller_id),
                    "page": page, "size": page_size,
                    "from": from_d.isoformat(), "to": to_d.isoformat(),
                    "statusGroup": "ALL",
                },
                timeout=15,
            )
            if r.status_code == 401:
                error = "unauthorized"
                break
            if r.status_code != 200:
                error = f"http_{r.status_code}"
                break
            data = r.json() if r.content else {}
            payload = data.get("payload") if isinstance(data, dict) else None
            content = []
            # UZUM cabinet API: payload — это массив кампаний напрямую
            if isinstance(payload, list):
                content = payload
            elif isinstance(payload, dict):
                content = payload.get("content") or payload.get("items") or []
            elif isinstance(data, list):
                content = data
            elif isinstance(data, dict):
                content = data.get("content") or data.get("items") or []
            if not content:
                break
            items.extend(content)
            total = 0
            if isinstance(payload, dict):
                total = payload.get("totalElements") or payload.get("total") or 0
            elif isinstance(data, dict):
                total = data.get("totalElements") or 0
            if len(content) < page_size or (total and len(items) >= total):
                break
            page += 1
        except Exception as e:
            error = f"exception: {e}"
            break
    return {"items": items, "error": error}


def get_boost_orders_products(cabinet_token: str, seller_id: int, days: int = 30) -> dict:
    """Список товаров с настройками 'Буст заказов'."""
    if not cabinet_token or not seller_id:
        return {"items": [], "error": "no_token"}
    from datetime import datetime, timedelta
    to_d = datetime.now().date()
    from_d = to_d - timedelta(days=days)
    # Эндпоинт пока не подтверждён — пробуем несколько паттернов
    candidate_urls = [
        f"{CABINET_BASE}/api/seller/advertising/management/cpo",
        f"{CABINET_BASE}/api/seller/advertising/management/boost-orders",
        f"{CABINET_BASE}/api/seller/advertising/cpo/products",
    ]
    error = None
    for url in candidate_urls:
        try:
            r = requests.get(
                url,
                headers=_cabinet_headers(cabinet_token),
                params={
                    "sellerId": seller_id,
                    "page": 0, "size": 100,
                    "from": from_d.isoformat(), "to": to_d.isoformat(),
                },
                timeout=15,
            )
            if r.status_code == 200:
                data = r.json() if r.content else {}
                payload = data.get("payload") if isinstance(data, dict) else None
                content = []
                if isinstance(payload, dict):
                    content = payload.get("content") or payload.get("items") or []
                elif isinstance(data, list):
                    content = data
                return {"items": content, "error": None, "endpoint": url}
            elif r.status_code == 401:
                error = "unauthorized"
                break
            else:
                error = f"http_{r.status_code}"
        except Exception as e:
            error = f"exception: {e}"
    return {"items": [], "error": error or "endpoint_not_found"}


def debug_ad_campaigns(api_key: str, seller_id: int, days: int = 30) -> dict:
    """Пробует получить рекламные кампании через cabinet-API с разными форматами auth."""
    from datetime import datetime, timedelta
    to_d = datetime.now().date()
    from_d = to_d - timedelta(days=days)
    base_url = "https://api-seller.uzum.uz/api/seller/advertising/management/ad-campaign"
    params = {
        "sellerId": seller_id,
        "page": 0, "size": 20,
        "from": from_d.isoformat(), "to": to_d.isoformat(),
        "statusGroup": "ALL",
    }
    base_headers = {
        "Accept": "application/json",
        "Accept-Language": "ru",
        "Origin": "https://seller.uzum.uz",
        "Referer": "https://seller.uzum.uz/",
    }
    out = {"requests": []}
    auth_variants = [
        ("public-no-bearer", {"Authorization": api_key}),
        ("public-bearer", {"Authorization": f"Bearer {api_key}"}),
    ]
    for name, auth in auth_variants:
        attempt = {"variant": name}
        try:
            r = requests.get(base_url, headers={**base_headers, **auth}, params=params, timeout=15)
            attempt["status"] = r.status_code
            attempt["url"] = r.url
            try:
                attempt["body"] = r.json()
            except Exception:
                attempt["body_text"] = r.text[:600]
        except Exception as e:
            attempt["error"] = str(e)
        out["requests"].append(attempt)
    return out


def debug_finance_orders(api_key: str, shop_id: int, days: int = 30) -> dict:
    """Возвращает сырой ответ UZUM без кеша — для отладки."""
    now_ms = int(time.time() * 1000)
    from_ms = now_ms - days * 24 * 60 * 60 * 1000
    out = {"requests": []}
    variants = [
        # как в спеке — shopIds array, ms timestamps
        [("shopIds", shop_id), ("dateFrom", from_ms), ("dateTo", now_ms),
         ("page", 0), ("size", 20), ("group", "false")],
        # без дат
        [("shopIds", shop_id), ("page", 0), ("size", 20), ("group", "false")],
        # с очень широким диапазоном (3 года)
        [("shopIds", shop_id),
         ("dateFrom", now_ms - 3 * 365 * 24 * 60 * 60 * 1000),
         ("dateTo", now_ms),
         ("page", 0), ("size", 20), ("group", "false")],
    ]
    for params in variants:
        attempt = {"params": dict(params)}
        try:
            r = requests.get(
                f"{SELLER_URL}/v1/finance/orders",
                headers=_h(api_key),
                params=params,
                timeout=20,
            )
            attempt["status"] = r.status_code
            attempt["url"] = r.url
            try:
                attempt["body"] = r.json()
            except Exception:
                attempt["body_text"] = r.text[:500]
        except Exception as e:
            attempt["error"] = str(e)
        out["requests"].append(attempt)
    return out


def get_finance_orders(api_key: str, shop_id: int, days: int = 30, force: bool = False) -> list:
    """Заказы за N последних дней. UZUM глючит на dateFrom/dateTo — фильтруем по date на стороне Python."""
    key = (shop_id, "orders", days)
    now = time.time()
    if not force:
        cached = _CACHE.get(key)
        if cached and now - cached[0] < _CACHE_TTL:
            return cached[1]
    cutoff_ms = int((now - days * 24 * 60 * 60) * 1000)
    all_items = []
    page = 0
    page_size = 100
    while page < 100:  # safety: до 10 000 заказов
        try:
            r = requests.get(
                f"{SELLER_URL}/v1/finance/orders",
                headers=_h(api_key),
                params=[
                    ("shopIds", shop_id),
                    ("page", page),
                    ("size", page_size),
                    ("group", "false"),
                ],
                timeout=20,
            )
            if r.status_code != 200:
                break
            data = r.json() if r.content else {}
            items = (data.get("orderItems") if isinstance(data, dict) else None) or []
            if not items:
                break
            # фильтруем по дате — заказы UZUM приходят отсортированные по убыванию даты
            items_in_range = [o for o in items if (o.get("date") or 0) >= cutoff_ms]
            all_items.extend(items_in_range)
            # если на этой странице последний элемент уже за пределами — стоп
            last_date = items[-1].get("date") or 0
            if last_date < cutoff_ms:
                break
            total = data.get("totalElements", 0) if isinstance(data, dict) else 0
            if len(items) < page_size or (total and (page + 1) * page_size >= total):
                break
            page += 1
        except Exception:
            break
    _CACHE[key] = (now, all_items)
    return all_items


def get_finance_expenses(api_key: str, shop_id: int, days: int = 30, force: bool = False) -> list:
    """Расходы продавца. UZUM: shopIds (array), dateFrom/dateTo в мс."""
    key = (shop_id, "expenses", days)
    now = time.time()
    if not force:
        cached = _CACHE.get(key)
        if cached and now - cached[0] < _CACHE_TTL:
            return cached[1]
    now_ms = int(now * 1000)
    from_ms = now_ms - days * 24 * 60 * 60 * 1000
    try:
        r = requests.get(
            f"{SELLER_URL}/v1/finance/expenses",
            headers=_h(api_key),
            params=[
                ("shopIds", shop_id),
                ("dateFrom", from_ms),
                ("dateTo", now_ms),
                ("page", 0),
                ("size", 500),
            ],
            timeout=20,
        )
        if r.status_code == 200:
            data = r.json()
            items = (
                (data.get("payload") or {}).get("payments")
                if isinstance(data, dict) else None
            ) or []
            _CACHE[key] = (now, items)
            return items
    except Exception:
        pass
    cached = _CACHE.get(key)
    return cached[1] if cached else []

def test_connection(api_key: str, shop_id: int) -> bool:
    try:
        r = requests.get(
            f"{SELLER_URL}/v1/product/shop/{shop_id}",
            headers=_h(api_key),
            params={"page": 0, "size": 1, "filter": "ALL", "lang": "ru"},
            timeout=8
        )
        return r.status_code == 200
    except Exception:
        return False
