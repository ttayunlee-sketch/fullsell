#!/bin/bash
# FullSell — установка скрейпера UZUM на Ubuntu VPS в Узбекистане.
# Запускается ОДИН РАЗ на свежем сервере. Конфиг pinned на твой AWS Postgres.
#
# Требования:
#   - Ubuntu 22.04 LTS (или 20.04)
#   - SSH-доступ root или ubuntu
#   - 1 GB RAM минимум
#   - Public IPv4
#
# Использование:
#   1. SSH на новый VPS у hoster.uz / ps.uz
#   2. Заскачать этот файл:
#      wget https://raw.githubusercontent.com/ttayunlee-sketch/fullsell/main/setup-tashkent-scraper.sh
#   3. Запустить:
#      chmod +x setup-tashkent-scraper.sh
#      sudo bash setup-tashkent-scraper.sh
#   4. Скрипт спросит два секрета (Postgres URL + опционально 2captcha key)

set -e

echo "═══════════════════════════════════════════════════"
echo "  🇺🇿  FullSell — установка скрейпера UZUM (Tashkent VPS)"
echo "═══════════════════════════════════════════════════"
echo ""

# ── 1. Проверяем что мы root или sudoer ──
if [ "$EUID" -ne 0 ]; then
  echo "❌ Запусти как root: sudo bash setup-tashkent-scraper.sh"
  exit 1
fi

# ── 2. Спрашиваем секреты ──
echo "📝 Введи DATABASE_URL — это URL к твоему Postgres на AWS."
echo "   Формат: postgresql://fullsell:PASSWORD@AWS_IP:5432/fullsell"
echo "   (PASSWORD из .env на AWS-сервере, AWS_IP = 65.1.25.194 для текущей AWS Lightsail)"
read -p "   DATABASE_URL: " DATABASE_URL

if [ -z "$DATABASE_URL" ]; then
  echo "❌ DATABASE_URL пустой — без него скрейпер не сможет писать в БД."
  exit 1
fi

read -p "   TWOCAPTCHA_API_KEY (опционально, Enter чтобы пропустить): " TWOCAPTCHA_API_KEY

# ── 3. Устанавливаем Docker ──
echo ""
echo "📦 Устанавливаю Docker..."
if ! command -v docker &> /dev/null; then
  apt-get update -q
  apt-get install -y -q ca-certificates curl gnupg
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -q
  apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  echo "✅ Docker установлен"
else
  echo "✅ Docker уже установлен"
fi

# ── 4. Клонируем репо в /opt/fullsell-scraper ──
echo ""
echo "📥 Клонирую FullSell..."
mkdir -p /opt
if [ ! -d /opt/fullsell-scraper ]; then
  git clone https://github.com/ttayunlee-sketch/fullsell.git /opt/fullsell-scraper
else
  cd /opt/fullsell-scraper && git pull
fi
cd /opt/fullsell-scraper

# ── 5. Создаём .env только с нужными переменными для скрейпера ──
cat > /opt/fullsell-scraper/.env <<EOF
DATABASE_URL=$DATABASE_URL
TWOCAPTCHA_API_KEY=$TWOCAPTCHA_API_KEY
SCRAPER_TOP_CATS=50
SCRAPER_PRODUCTS_PER_CAT=200
SCRAPER_SCROLLS=8
EOF
chmod 600 /opt/fullsell-scraper/.env

# ── 6. Создаём минимальный docker-compose только для scraper ──
cat > /opt/fullsell-scraper/docker-compose.scraper.yml <<'EOF'
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

# ── 7. Билдим образ один раз ──
echo ""
echo "🐳 Сборка образа scraper (~3-5 мин, 700MB Playwright base)..."
docker compose -f docker-compose.scraper.yml --profile scrape build scraper

# ── 8. Скрипт ежедневного запуска ──
cat > /usr/local/bin/fullsell-scrape-tashkent.sh <<'EOF'
#!/bin/bash
# Ежедневный запуск скрейпера UZUM на Tashkent VPS.
cd /opt/fullsell-scraper
echo "[$(date)] === SCRAPE START ===" >> /var/log/fullsell-scrape.log
docker compose -f docker-compose.scraper.yml --profile scrape build scraper >> /var/log/fullsell-scrape.log 2>&1
docker compose -f docker-compose.scraper.yml --profile scrape run --rm scraper >> /var/log/fullsell-scrape.log 2>&1
echo "[$(date)] === SCRAPE END ===" >> /var/log/fullsell-scrape.log
EOF
chmod +x /usr/local/bin/fullsell-scrape-tashkent.sh

# ── 9. Cron daily 04:00 Tashkent (UTC+5) = 23:00 UTC ──
(crontab -l 2>/dev/null | grep -v fullsell-scrape-tashkent; \
  echo "0 23 * * * /usr/local/bin/fullsell-scrape-tashkent.sh") | crontab -

# ── 10. Auto-update репо каждый час ──
cat > /usr/local/bin/fullsell-pull.sh <<'EOF'
#!/bin/bash
cd /opt/fullsell-scraper && git pull -q 2>&1 >> /var/log/fullsell-pull.log
EOF
chmod +x /usr/local/bin/fullsell-pull.sh
(crontab -l 2>/dev/null | grep -v fullsell-pull; \
  echo "0 * * * * /usr/local/bin/fullsell-pull.sh") | crontab -

# ── 11. Готово! Запускаем первый раз руками ──
echo ""
echo "═══════════════════════════════════════════════════"
echo "  ✅ Установка завершена!"
echo "═══════════════════════════════════════════════════"
echo ""
echo "Cron установлен:"
crontab -l | grep fullsell || true
echo ""
echo "Запустить вручную сейчас:"
echo "  sudo /usr/local/bin/fullsell-scrape-tashkent.sh"
echo ""
echo "Логи:"
echo "  tail -f /var/log/fullsell-scrape.log"
echo ""
echo "Хочешь запустить прямо сейчас? [y/N]"
read -p "  > " answer
if [[ "$answer" == "y" || "$answer" == "Y" ]]; then
  echo "🚀 Запускаю первый прогон..."
  /usr/local/bin/fullsell-scrape-tashkent.sh &
  sleep 3
  echo ""
  echo "📊 Прогон идёт в фоне. Лог:"
  echo "   tail -f /var/log/fullsell-scrape.log"
fi
