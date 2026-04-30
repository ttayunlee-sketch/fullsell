import os, requests
from dotenv import load_dotenv
load_dotenv()

key = os.getenv('UZUM_API_KEY')
SHOP_ID = 110091

# БЕЗ Bearer — просто ключ!
headers = {
    'Authorization': key,
    'Content-Type': 'application/json'
}

url = f'https://api-seller.uzum.uz/api/seller-openapi/v1/product/shop/{SHOP_ID}'
r = requests.get(url, headers=headers, params={
    'page': 0,
    'size': 20,
    'filter': 'ACTIVE'
}, timeout=10)

print(f'Статус: {r.status_code}')
if r.status_code == 200:
    data = r.json()
    products = data.get('productList', [])
    print(f'✅ Найдено товаров: {len(products)}')
    for p in products:
        print(f"  • {p['title'][:50]} | Цена: {p['price']:,} сум | Рейтинг: {p['rating']}")