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
