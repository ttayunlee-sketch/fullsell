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


def get_finance_orders(api_key: str, shop_id: int, days: int = 30, force: bool = False) -> list:
    """Получает реальные заказы продавца за N последних дней."""
    from datetime import datetime, timedelta
    key = (shop_id, "orders", days)
    now = time.time()
    if not force:
        cached = _CACHE.get(key)
        if cached and now - cached[0] < _CACHE_TTL:
            return cached[1]
    to_d = datetime.now().date()
    from_d = to_d - timedelta(days=days)
    base_params = {
        "shopId": shop_id,
        "page": 0,
        "size": 500,
        "lang": "ru",
    }
    # пробуем разные форматы дат — UZUM может использовать любой
    date_variants = [
        {"dateFrom": from_d.isoformat(), "dateTo": to_d.isoformat()},
        {"from": from_d.isoformat(), "to": to_d.isoformat()},
        {"startDate": from_d.isoformat(), "endDate": to_d.isoformat()},
        {},  # без дат — последние заказы
    ]
    for dp in date_variants:
        try:
            r = requests.get(
                f"{SELLER_URL}/v1/finance/orders",
                headers=_h(api_key),
                params={**base_params, **dp},
                timeout=15,
            )
            if r.status_code == 200:
                data = r.json()
                orders = (
                    data.get("orderList") if isinstance(data, dict) else None
                ) or (
                    data.get("orders") if isinstance(data, dict) else None
                ) or (
                    data.get("data") if isinstance(data, dict) else None
                ) or (
                    data.get("content") if isinstance(data, dict) else None
                ) or (data if isinstance(data, list) else [])
                _CACHE[key] = (now, orders)
                return orders
        except Exception:
            continue
    cached = _CACHE.get(key)
    return cached[1] if cached else []


def get_finance_expenses(api_key: str, shop_id: int, days: int = 30, force: bool = False) -> list:
    from datetime import datetime, timedelta
    key = (shop_id, "expenses", days)
    now = time.time()
    if not force:
        cached = _CACHE.get(key)
        if cached and now - cached[0] < _CACHE_TTL:
            return cached[1]
    to_d = datetime.now().date()
    from_d = to_d - timedelta(days=days)
    for dp in [
        {"dateFrom": from_d.isoformat(), "dateTo": to_d.isoformat()},
        {"from": from_d.isoformat(), "to": to_d.isoformat()},
        {},
    ]:
        try:
            r = requests.get(
                f"{SELLER_URL}/v1/finance/expenses",
                headers=_h(api_key),
                params={"shopId": shop_id, "page": 0, "size": 500, **dp},
                timeout=15,
            )
            if r.status_code == 200:
                data = r.json()
                items = (
                    data.get("expenseList") if isinstance(data, dict) else None
                ) or (
                    data.get("expenses") if isinstance(data, dict) else None
                ) or (
                    data.get("data") if isinstance(data, dict) else None
                ) or (data if isinstance(data, list) else [])
                _CACHE[key] = (now, items)
                return items
        except Exception:
            continue
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
