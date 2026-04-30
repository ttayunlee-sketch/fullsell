#!/bin/bash
# FullSell — настройка автоматического деплоя через cron.
# Запускается ОДИН РАЗ. После этого все изменения с GitHub автоматически
# попадают на сервер каждую минуту — SSH больше не нужен.

set -e

echo "═══════════════════════════════════════════"
echo "  🤖 Установка авто-деплоя FullSell"
echo "═══════════════════════════════════════════"
echo ""

# 1. Создаём скрипт авто-деплоя
sudo tee /usr/local/bin/fullsell-auto-deploy.sh > /dev/null << 'DEPLOY_EOF'
#!/bin/bash
# Каждую минуту проверяет GitHub. Если есть новый коммит — обновляет и перезапускает.
cd /home/ubuntu/fullsell || exit 1

# Если нет git — переинициализируем
if [ ! -d .git ]; then
  git init -q
  git remote add origin https://github.com/ttayunlee-sketch/fullsell.git 2>/dev/null
  git fetch -q origin main
  git checkout -q -f main
fi

git fetch -q origin main 2>&1 | tee /tmp/fullsell-deploy.log
LOCAL=$(git rev-parse HEAD 2>/dev/null)
REMOTE=$(git rev-parse origin/main 2>/dev/null)

if [ "$LOCAL" != "$REMOTE" ] && [ -n "$REMOTE" ]; then
  echo "[$(date)] New commit detected: $LOCAL → $REMOTE" >> /tmp/fullsell-deploy.log
  git reset -q --hard origin/main
  /usr/bin/docker compose up -d --build 2>&1 >> /tmp/fullsell-deploy.log
  echo "[$(date)] ✅ Deployed" >> /tmp/fullsell-deploy.log
fi
DEPLOY_EOF

sudo chmod +x /usr/local/bin/fullsell-auto-deploy.sh

# 2. Если папка fullsell не git-репо — переподключаем
cd /home/ubuntu/fullsell
if [ ! -d .git ]; then
  echo "📥 Клонирую репо..."
  cd /home/ubuntu
  if [ -f /home/ubuntu/fullsell/.env ]; then
    cp /home/ubuntu/fullsell/.env /tmp/fullsell-env-backup
  fi
  rm -rf /home/ubuntu/fullsell.tmp 2>/dev/null
  git clone -q https://github.com/ttayunlee-sketch/fullsell.git /home/ubuntu/fullsell.tmp
  rsync -a --exclude='.env' /home/ubuntu/fullsell.tmp/ /home/ubuntu/fullsell/
  rm -rf /home/ubuntu/fullsell.tmp
  cd /home/ubuntu/fullsell
  if [ -f /tmp/fullsell-env-backup ]; then
    cp /tmp/fullsell-env-backup .env
    rm /tmp/fullsell-env-backup
  fi
fi

# 3. Регистрируем cron-задачу
CRON_JOB="* * * * * /usr/local/bin/fullsell-auto-deploy.sh"
(crontab -l 2>/dev/null | grep -v fullsell-auto-deploy.sh; echo "$CRON_JOB") | crontab -

# 4. Запускаем сразу один раз
echo "🚀 Запускаю первый деплой..."
sudo /usr/local/bin/fullsell-auto-deploy.sh

# 5. Проверка
echo ""
echo "═══════════════════════════════════════════"
echo "  ✅ Авто-деплой настроен!"
echo "═══════════════════════════════════════════"
echo ""
echo "Каждую минуту сервер сам проверяет GitHub."
echo "Любой git push на main → автоматический деплой."
echo ""
echo "Логи деплоя:    cat /tmp/fullsell-deploy.log"
echo "Cron-задача:    crontab -l"
echo "Статус:         sudo docker compose ps"
echo ""
