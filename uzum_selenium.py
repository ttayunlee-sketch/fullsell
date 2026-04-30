import os, time
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

load_dotenv()

LOGIN = os.getenv("UZUM_LOGIN")
PASSWORD = os.getenv("UZUM_PASSWORD")

def get_uzum_data():
    print("🚀 Открываю браузер...")
    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")
    # options.add_argument("--headless")  # раскомментируй для скрытого режима

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )

    try:
        # Открываем кабинет
        print("🌐 Захожу на cabinet.uzum.uz...")
        driver.get("https://cabinet.uzum.uz/ru/login")
        time.sleep(3)

        # Вводим логин
        print("🔐 Ввожу логин...")
        login_field = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='text'], input[name='login'], input[placeholder*='логин'], input[placeholder*='email']"))
        )
        login_field.clear()
        login_field.send_keys(LOGIN)
        time.sleep(1)

        # Вводим пароль
        print("🔑 Ввожу пароль...")
        password_field = driver.find_element(By.CSS_SELECTOR, "input[type='password']")
        password_field.clear()
        password_field.send_keys(PASSWORD)
        time.sleep(1)

        # Нажимаем войти
        print("✅ Нажимаю войти...")
        submit_btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
        submit_btn.click()
        time.sleep(5)

        print(f"📄 Текущая страница: {driver.current_url}")
        print("✅ Успешно вошли в кабинет!")

        # Ждём чтобы увидеть страницу
        time.sleep(3)
        print(f"📋 Заголовок страницы: {driver.title}")

        # Делаем скриншот
        driver.save_screenshot("C:\\FullSell\\cabinet_screenshot.png")
        print("📸 Скриншот сохранён: C:\\FullSell\\cabinet_screenshot.png")

    except Exception as e:
        print(f"❌ Ошибка: {e}")
        driver.save_screenshot("C:\\FullSell\\error_screenshot.png")
    finally:
        time.sleep(3)
        driver.quit()

if __name__ == "__main__":
    get_uzum_data()