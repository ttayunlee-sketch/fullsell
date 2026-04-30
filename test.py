import os, requests

key = os.environ.get('UZUM_API_KEY')
print('Ключ найден:', bool(key))
print('Первые 5 символов:', key[:5] if key else 'нет')

SHOP_ID = 110091
headers = {'Authorization': key}

url = f'https://api-seller.uzum.uz/api/seller-openapi/v1/product/shop/{SHOP_ID}'
r = requests.get(url, headers=headers, params={'page':0,'size':5,'filter':'ALL'}, timeout=10)
print('Статус:', r.status_code)

if r.status_code == 200:
    data = r.json()
    products = data.get('productList', [])
    print('Товаров:', len(products))
    for p in products[:3]:
        print(' -', p['title'][:50])
else:
    print('Ответ:', r.text[:200])
