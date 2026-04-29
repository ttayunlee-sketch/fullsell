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
