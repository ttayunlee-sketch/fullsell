#!/bin/bash
# Запускается ОДИН РАЗ на AWS Lightsail: подтягивает свежий docker-compose
# (с проброшенным портом 5432), пересоздаёт Postgres-контейнер и печатает
# DATABASE_URL который надо вставить на Tashkent VPS.
#
# Использование:
#   bash <(curl -fsSL https://raw.githubusercontent.com/ttayunlee-sketch/fullsell/main/scripts/aws-open-postgres.sh)

set -e

cd /home/ubuntu/fullsell || { echo "❌ /home/ubuntu/fullsell не найдена"; exit 1; }

echo "═══════════════════════════════════════════════════"
echo "  🌐  Открытие Postgres для Tashkent VPS"
echo "═══════════════════════════════════════════════════"
echo ""

# 1. Подтягиваем свежий docker-compose.yml с port mapping
echo "📥 git pull..."
sudo git pull

# 2. Пересоздаём только db контейнер
echo "🐳 docker compose up -d db (пересборка)..."
sudo docker compose up -d --force-recreate db

# 3. Ждём пока поднимется
echo "⏳ Жду 5 сек пока Postgres поднимется..."
sleep 5

# 4. Проверяем что слушает на 0.0.0.0:5432
echo ""
echo "🔍 Проверка слушает ли 5432 наружу:"
sudo ss -tlnp | grep 5432 || { echo "❌ 5432 не слушается"; exit 1; }

# 5. Достаём пароль и формируем DATABASE_URL
PASSWORD=$(grep '^POSTGRES_PASSWORD=' .env | cut -d= -f2- | tr -d '"' | tr -d "'")
PUB_IP=$(curl -s ifconfig.me)

if [ -z "$PASSWORD" ]; then
  echo "❌ POSTGRES_PASSWORD не найден в .env"
  exit 1
fi

DB_URL="postgresql://fullsell:${PASSWORD}@${PUB_IP}:5432/fullsell"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  ✅ Postgres открыт"
echo "═══════════════════════════════════════════════════"
echo ""
echo "⚠️  ВАЖНО: открой в Lightsail Console → Networking → Add rule:"
echo "    - Application: Custom"
echo "    - Protocol:    TCP"
echo "    - Port:        5432"
echo "    - Restrict to: 138.249.248.45/32"
echo ""
echo "📋 DATABASE_URL для Tashkent VPS (скопируй):"
echo ""
echo "   $DB_URL"
echo ""
echo "▶️  На Tashkent VPS затем выполни:"
echo ""
echo "   bash <(curl -fsSL https://raw.githubusercontent.com/ttayunlee-sketch/fullsell/main/scripts/tashkent-deploy.sh)"
echo ""
