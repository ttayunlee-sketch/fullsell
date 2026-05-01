#!/bin/bash
# Регистрирует две crontab-задачи:
#   1) Daily 04:00 UTC — полный прогон скрейпера UZUM
#   2) Каждую минуту — проверка refresh-flag (юзер нажал «Обновить сейчас»)
# Запускается ОДИН РАЗ. Идемпотентен.

set -e

echo "═══════════════════════════════════════════"
echo "  🤖 Установка cron для UZUM-скрейпера"
echo "═══════════════════════════════════════════"
echo ""

# 1. Скрипт ежедневного запуска
sudo tee /usr/local/bin/fullsell-scrape-daily.sh > /dev/null << 'DEPLOY_EOF'
#!/bin/bash
# Ежедневный полный прогон скрейпера UZUM.
# Перед каждым запуском пересобираем образ — на случай если в репе обновился код.
cd /home/ubuntu/fullsell || exit 1
echo "[$(date)] === DAILY SCRAPE START ===" >> /tmp/fullsell-scrape.log
/usr/bin/docker compose --profile scrape build scraper >> /tmp/fullsell-scrape.log 2>&1
/usr/bin/docker compose --profile scrape run --rm scraper >> /tmp/fullsell-scrape.log 2>&1
echo "[$(date)] === DAILY SCRAPE END ===" >> /tmp/fullsell-scrape.log
DEPLOY_EOF
sudo chmod +x /usr/local/bin/fullsell-scrape-daily.sh

# 2. Watcher для ручного refresh-flag
sudo tee /usr/local/bin/fullsell-scrape-watch.sh > /dev/null << 'DEPLOY_EOF'
#!/bin/bash
# Каждую минуту проверяет флаг refresh.flag в volume scraper_state.
# Если есть — удаляет флаг и запускает один прогон скрейпера.
cd /home/ubuntu/fullsell || exit 1
FLAG="/var/lib/docker/volumes/fullsell_scraper_state/_data/refresh.flag"
if [ -f "$FLAG" ]; then
    sudo rm -f "$FLAG"
    echo "[$(date)] === MANUAL REFRESH START ===" >> /tmp/fullsell-scrape.log
    /usr/bin/docker compose --profile scrape build scraper >> /tmp/fullsell-scrape.log 2>&1
    /usr/bin/docker compose --profile scrape run --rm scraper >> /tmp/fullsell-scrape.log 2>&1
    echo "[$(date)] === MANUAL REFRESH END ===" >> /tmp/fullsell-scrape.log
fi
DEPLOY_EOF
sudo chmod +x /usr/local/bin/fullsell-scrape-watch.sh

# 3. Регистрируем cron-задачи (idempotent)
CRON_DAILY="0 4 * * * /usr/local/bin/fullsell-scrape-daily.sh"
CRON_WATCH="* * * * * /usr/local/bin/fullsell-scrape-watch.sh"
(crontab -l 2>/dev/null \
  | grep -v 'fullsell-scrape-daily.sh' \
  | grep -v 'fullsell-scrape-watch.sh'; \
  echo "$CRON_DAILY"; \
  echo "$CRON_WATCH") | crontab -

echo "✅ Cron установлен:"
crontab -l | grep fullsell-scrape || true
echo ""
echo "Логи скрейпинга: tail -f /tmp/fullsell-scrape.log"
echo ""
echo "Запустить вручную сейчас: sudo /usr/local/bin/fullsell-scrape-daily.sh"
