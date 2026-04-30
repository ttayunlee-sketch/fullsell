#!/bin/bash
# FullSell — автоматический установщик для Ubuntu Lightsail / Hetzner / etc.
# Использование:
#   bash <(curl -sL https://raw.githubusercontent.com/ttayunlee-sketch/fullsell/main/setup.sh)

set -e
cd "$HOME"

echo ""
echo "========================================"
echo "    🚀 FullSell автоустановщик"
echo "========================================"
echo ""

# ── 1. Docker ─────────────────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
  echo "[1/5] Устанавливаю Docker..."
  sudo apt-get update -qq
  sudo apt-get install -y -qq docker.io docker-compose-v2
  sudo usermod -aG docker "$USER"
  echo "✅ Docker установлен"
else
  echo "[1/5] Docker уже установлен: $(docker --version)"
fi

# ── 2. Скачиваем код ──────────────────────────────────────────────────────────
echo "[2/5] Скачиваю код FullSell..."
if [ -d "$HOME/fullsell" ]; then
  echo "    Папка fullsell уже есть, обновляю..."
  rm -rf "$HOME/fullsell.bak" 2>/dev/null || true
  mv "$HOME/fullsell" "$HOME/fullsell.bak"
fi
curl -sL https://github.com/ttayunlee-sketch/fullsell/archive/refs/heads/main.tar.gz | tar xz
mv fullsell-main fullsell
cd "$HOME/fullsell"
# Восстанавливаем .env если был
if [ -f "$HOME/fullsell.bak/.env" ]; then
  cp "$HOME/fullsell.bak/.env" .env
  echo "    Сохранён старый .env"
fi
echo "✅ Код скачан"

# ── 3. Запрос параметров ──────────────────────────────────────────────────────
if [ ! -f .env ]; then
  echo ""
  echo "[3/5] Настройка .env"
  echo ""
  read -rp "→ Домен (например fullsell.duckdns.org): " DOMAIN
  read -rp "→ Anthropic API ключ (sk-ant-...): " ANTHROPIC_KEY
  read -rp "→ Пароль входа в дашборд (без пробелов): " DASH_PASS

  PG_PASS=$(openssl rand -base64 24 | tr -d '/+=' | head -c 32)
  SECRET_KEY=$(openssl rand -base64 32 | tr -d '/+=' | head -c 48)

  cat > .env <<EOF
DOMAIN=$DOMAIN
POSTGRES_PASSWORD=$PG_PASS
DASHBOARD_PASSWORD=$DASH_PASS
SECRET_KEY=$SECRET_KEY
ANTHROPIC_API_KEY=$ANTHROPIC_KEY
CONNECTOR_SECRET=$DASH_PASS
EOF
  echo "✅ .env создан"
else
  echo "[3/5] .env уже есть, использую существующий"
fi

# ── 4. Запуск стека ───────────────────────────────────────────────────────────
echo ""
echo "[4/5] Запускаю Docker-стек (это займёт 1-3 минуты при первом запуске)..."

if groups "$USER" | grep -q docker; then
  docker compose up -d --build
else
  sudo docker compose up -d --build
fi

# ── 5. Проверка ───────────────────────────────────────────────────────────────
echo ""
echo "[5/5] Проверяю статус..."
sleep 3
if groups "$USER" | grep -q docker; then
  docker compose ps
else
  sudo docker compose ps
fi

echo ""
echo "========================================"
echo "    🎉 Готово!"
echo "========================================"
echo ""
DOMAIN=$(grep '^DOMAIN=' .env | cut -d= -f2)
echo "Открой в браузере: https://$DOMAIN"
echo ""
echo "Логи:        cd ~/fullsell && docker compose logs -f"
echo "Перезапуск:  cd ~/fullsell && docker compose restart"
echo "Остановка:   cd ~/fullsell && docker compose down"
echo ""
