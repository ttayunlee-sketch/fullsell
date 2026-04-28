import requests

SELLER_URL = "https://api-seller.uzum.uz/api/seller-openapi"

def get_products(api_key: str, shop_id: int, filter_type: str = "ALL") -> list:
    try:
        r = requests.get(
            f"{SELLER_URL}/v1/product/shop/{shop_id}",
            headers={"Authorization": api_key},
            params={"page": 0, "size": 50, "filter": filter_type},
            timeout=10
        )
        if r.status_code == 200:
            return r.json().get("productList", [])
    except Exception:
        pass
    return []

def test_connection(api_key: str, shop_id: int) -> bool:
    try:
        r = requests.get(
            f"{SELLER_URL}/v1/product/shop/{shop_id}",
            headers={"Authorization": api_key},
            params={"page": 0, "size": 1, "filter": "ALL"},
            timeout=8
        )
        return r.status_code == 200
    except Exception:
        return False
