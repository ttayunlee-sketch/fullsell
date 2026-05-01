#!/bin/bash
# Запускается ОДИН РАЗ на Tashkent VPS: спрашивает DATABASE_URL,
# создаёт .env, билдит scraper, делает первый прогон, регистрирует cron.
#
# Использование:
#   bash <(curl -fsSL https://raw.githubusercontent.com/ttayunlee-sketch/fullsell/main/scripts/tashkent-deploy.sh)

set -e

REPO=/opt/fullsell-scraper

echo "═══════════════════════════════════════════════════"
echo "  🇺🇿  FullSell scraper — деплой на Tashkent VPS"
echo "═══════════════════════════════════════════════════"
echo ""

# 1. Проверяем что Docker есть
if ! command -v docker &>/dev/null; then
  echo "❌ Docker не установлен. Сначала: curl -fsSL https://get.docker.com | sudo sh"
  exit 1
fi

# 2. Проверяем/клонируем репо
if [ ! -d "$REPO" ]; then
  echo "📥 Клонирую репо в $REPO..."
  sudo mkdir -p /opt && sudo chown $USER:$USER /opt
  git clone https://github.com/ttayunlee-sketch/fullsell.git "$REPO"
else
  echo "📥 Обновляю репо..."
  cd "$REPO" && git pull
fi
cd "$REPO"

# 3. Спрашиваем DATABASE_URL
echo ""
echo "📋 Вставь DATABASE_URL который тебе выдал aws-open-postgres.sh:"
echo "   (формат: postgresql://fullsell:PASSWORD@65.1.25.194:5432/fullsell)"
echo ""
read -p "   DATABASE_URL: " DB_URL

if [ -z "$DB_URL" ]; then
  echo "❌ DATABASE_URL пустой"
  exit 1
fi

# 4. Опционально 2captcha
echo ""
read -p "   TWOCAPTCHA_API_KEY (Enter чтобы пропустить): " TWO_CAP
TWO_CAP=${TWO_CAP:-}

# 5. Создаём .env
cat > "$REPO/.env" <<EOF
DATABASE_URL=$DB_URL
TWOCAPTCHA_API_KEY=$TWO_CAP
SCRAPER_TOP_CATS=50
SCRAPER_PRODUCTS_PER_CAT=200
SCRAPER_SCROLLS=8
EOF
chmod 600 "$REPO/.env"
echo "✅ .env создан"

# 6. Минимальный docker-compose для скрейпера
cat > "$REPO/docker-compose.scraper.yml" <<'EOF'
services:
  scraper:
    build: ./scraper
    profiles: ["scrape"]
    env_file: .env
    volumes:
      - scraper_state:/state
volumes:
  scraper_state:
EOF

# 7. Тест подключения к БД
echo ""
echo "🔌 Тест подключения к Postgres..."
if ! command -v psql &>/dev/null; then
  echo "📦 Устанавливаю postgresql-client..."
  sudo apt update -q && sudo apt install -y -q postgresql-client
fi

if timeout 10 psql "$DB_URL" -c "SELECT 1;" &>/dev/null; then
  echo "✅ БД доступна"
else
  echo "❌ БД недоступна. Проверь:"
  echo "   1. На AWS Lightsail Console открыт ли порт 5432 для 138.249.248.45/32"
  echo "   2. Правильный ли DATABASE_URL"
  echo "   3. На AWS работает ли 'docker compose ps db'"
  exit 1
fi

# 8. Билдим scraper-образ (3-5 минут)
echo ""
echo "🐳 Сборка scraper (тащит ~700MB Playwright base — 3-5 мин)..."
sudo docker compose -f docker-compose.scraper.yml --profile scrape build scraper

# 9. Скрипт ежедневного запуска
sudo tee /usr/local/bin/fullsell-scrape.sh > /dev/null <<EOF
#!/bin/bash
cd $REPO
echo "[\$(date)] === SCRAPE START ===" >> /var/log/fullsell-scrape.log
docker compose -f docker-compose.scraper.yml --profile scrape build scraper >> /var/log/fullsell-scrape.log 2>&1
docker compose -f docker-compose.scraper.yml --profile scrape run --rm scraper >> /var/log/fullsell-scrape.log 2>&1
echo "[\$(date)] === SCRAPE END ===" >> /var/log/fullsell-scrape.log
EOF
sudo chmod +x /usr/local/bin/fullsell-scrape.sh
sudo touch /var/log/fullsell-scrape.log && sudo chown $USER /var/log/fullsell-scrape.log

# 10. Cron 04:00 Tashkent (= 23:00 UTC)
(sudo crontab -l 2>/dev/null | grep -v fullsell-scrape; \
  echo "0 23 * * * /usr/local/bin/fullsell-scrape.sh") | sudo crontab -

# 11. Hourly git pull для авто-обновлений
sudo tee /usr/local/bin/fullsell-pull.sh > /dev/null <<EOF
#!/bin/bash
cd $REPO && git pull -q 2>&1 >> /var/log/fullsell-pull.log
EOF
sudo chmod +x /usr/local/bin/fullsell-pull.sh
(sudo crontab -l 2>/dev/null | grep -v fullsell-pull; \
  echo "0 * * * * /usr/local/bin/fullsell-pull.sh") | sudo crontab -

echo ""
echo "═══════════════════════════════════════════════════"
echo "  ✅ Установка завершена"
echo "═══════════════════════════════════════════════════"
echo ""
echo "Cron установлен:"
sudo crontab -l | grep fullsell
echo ""
echo "Запустить первый прогон сейчас (5-15 минут)?"
read -p "  [Y/n]: " ANSWER
ANSWER=${ANSWER:-Y}

if [[ "$ANSWER" =~ ^[YyДд] ]]; then
  echo "🚀 Запускаю..."
  sudo /usr/local/bin/fullsell-scrape.sh &
  sleep 3
  echo ""
  echo "📊 Прогон идёт в фоне. Смотри лог:"
  echo "   tail -f /var/log/fullsell-scrape.log"
  echo ""
  echo "Через 5-15 минут на https://fullsell.uz/market должны появиться данные."
fi
