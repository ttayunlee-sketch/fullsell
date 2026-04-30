import os, requests
from dotenv import load_dotenv
load_dotenv()

# UZUM OAuth - авторизация через логин/пароль
LOGIN = input("Введи логин от cabinet.uzum.uz: ")
PASSWORD = input("Введи пароль: ")

# Пробуем получить токен
auth_urls = [
    "https://api-seller.uzum.uz/api/auth/token",
    "https://api-seller.uzum.uz/api/seller-openapi/auth/token",
    "https://api-seller.uzum.uz/auth/token",
    "https://api-seller.uzum.uz/api/seller-openapi/oauth/token",
]

for url in auth_urls:
    try:
        r = requests.post(url, json={
            "username": LOGIN,
            "password": PASSWORD,
            "grant_type": "password"
        }, timeout=10)
        print(f"{r.status_code} — {url}")
        if r.status_code == 200:
            print("Токен получен!", r.json())
        elif r.status_code != 404:
            print("Ответ:", r.text[:200])
    except Exception as e:
        print(f"Ошибка: {e}")