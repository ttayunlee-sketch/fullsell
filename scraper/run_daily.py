"""
Точка входа cron / docker compose run --rm scraper.
Запускает скрейпер, пишет в БД, оставляет результат в /tmp/scraper.log.
"""
import asyncio
import os
import sys
import time
import traceback
from datetime import date, datetime

import db
import scraper


def main():
    started = time.time()
    snap = date.today()
    print(f"[run_daily] start snap={snap}", flush=True)

    # 1. Создаём схему если нет
    try:
        db.init_schema()
    except Exception as e:
        print(f"[run_daily] init_schema FAILED: {e}", flush=True)
        traceback.print_exc()
        sys.exit(1)

    # 2. Прогон
    try:
        stats = asyncio.run(scraper.run_full_scrape(
            snap,
            save_categories_fn=db.save_categories,
            save_products_fn=db.save_products,
            aggregate_fn=db.aggregate_for_date,
            update_titles_fn=db.update_seller_titles,
        ))
    except Exception as e:
        print(f"[run_daily] scrape FAILED: {e}", flush=True)
        traceback.print_exc()
        sys.exit(2)

    duration = time.time() - started
    print(f"[run_daily] done in {duration:.0f}s — {stats}", flush=True)
    print(f"[run_daily] snap_date={snap}", flush=True)
    print(f"[run_daily] DONE_OK", flush=True)


if __name__ == "__main__":
    main()
