"""
Тонкий клиент к Postgres для скрейпера.
Создаёт таблицы при первом запуске и пишет batch'ами.
"""
import os
from datetime import date
from typing import Iterable, Dict, Any

import psycopg2
import psycopg2.extras


def _conn():
    url = os.environ["DATABASE_URL"].replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url)


SCHEMA = """
CREATE TABLE IF NOT EXISTS market_categories_daily (
    snap_date        DATE NOT NULL,
    category_id      INTEGER NOT NULL,
    slug             TEXT,
    title_ru         TEXT,
    parent_id        INTEGER,
    level            INTEGER,
    products_count   INTEGER DEFAULT 0,
    revenue_estimate BIGINT  DEFAULT 0,
    PRIMARY KEY (snap_date, category_id)
);

CREATE TABLE IF NOT EXISTS market_sellers_daily (
    snap_date         DATE NOT NULL,
    seller_id         BIGINT NOT NULL,
    seller_title      TEXT,
    products_count    INTEGER DEFAULT 0,
    revenue_estimate  BIGINT  DEFAULT 0,
    orders_estimate   INTEGER DEFAULT 0,
    PRIMARY KEY (snap_date, seller_id)
);

CREATE TABLE IF NOT EXISTS market_products_daily (
    snap_date     DATE NOT NULL,
    product_id    BIGINT NOT NULL,
    category_id   INTEGER,
    seller_id     BIGINT,
    title_ru      TEXT,
    price         BIGINT,
    orders_amount INTEGER,
    rating        NUMERIC(3,2),
    reviews_count INTEGER,
    PRIMARY KEY (snap_date, product_id)
);

CREATE INDEX IF NOT EXISTS idx_sellers_date_rev    ON market_sellers_daily   (snap_date, revenue_estimate DESC);
CREATE INDEX IF NOT EXISTS idx_categories_date_rev ON market_categories_daily (snap_date, revenue_estimate DESC);
CREATE INDEX IF NOT EXISTS idx_products_date_cat   ON market_products_daily   (snap_date, category_id);
CREATE INDEX IF NOT EXISTS idx_products_date_sel   ON market_products_daily   (snap_date, seller_id);
"""


def init_schema():
    with _conn() as c, c.cursor() as cur:
        cur.execute(SCHEMA)


def save_categories(snap: date, rows: Iterable[Dict[str, Any]]):
    """rows: dicts with category_id, slug, title_ru, parent_id, level"""
    rows = list(rows)
    if not rows: return
    with _conn() as c, c.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO market_categories_daily
              (snap_date, category_id, slug, title_ru, parent_id, level)
            VALUES %s
            ON CONFLICT (snap_date, category_id) DO UPDATE SET
              slug = EXCLUDED.slug,
              title_ru = EXCLUDED.title_ru,
              parent_id = EXCLUDED.parent_id,
              level = EXCLUDED.level
            """,
            [(snap, r["category_id"], r.get("slug"), r.get("title_ru"),
              r.get("parent_id"), r.get("level")) for r in rows],
            page_size=500,
        )


def save_products(snap: date, rows: Iterable[Dict[str, Any]]):
    rows = list(rows)
    if not rows: return
    with _conn() as c, c.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO market_products_daily
              (snap_date, product_id, category_id, seller_id, title_ru,
               price, orders_amount, rating, reviews_count)
            VALUES %s
            ON CONFLICT (snap_date, product_id) DO UPDATE SET
              category_id   = EXCLUDED.category_id,
              seller_id     = EXCLUDED.seller_id,
              title_ru      = EXCLUDED.title_ru,
              price         = EXCLUDED.price,
              orders_amount = EXCLUDED.orders_amount,
              rating        = EXCLUDED.rating,
              reviews_count = EXCLUDED.reviews_count
            """,
            [(snap, r["product_id"], r.get("category_id"), r.get("seller_id"),
              r.get("title_ru"), r.get("price"), r.get("orders_amount"),
              r.get("rating"), r.get("reviews_count")) for r in rows],
            page_size=500,
        )


def aggregate_for_date(snap: date) -> dict:
    """
    Пересчитывает sellers_daily и products_count в categories_daily из products_daily.
    Возвращает счётчики для логов.
    """
    with _conn() as c, c.cursor() as cur:
        # Sellers aggregation
        cur.execute(
            """
            INSERT INTO market_sellers_daily
              (snap_date, seller_id, seller_title, products_count, revenue_estimate, orders_estimate)
            SELECT
              %s,
              p.seller_id,
              MAX(p.title_ru) FILTER (WHERE p.seller_id IS NOT NULL),  -- placeholder, we replace below
              COUNT(*),
              COALESCE(SUM(p.price * p.orders_amount), 0),
              COALESCE(SUM(p.orders_amount), 0)
            FROM market_products_daily p
            WHERE p.snap_date = %s AND p.seller_id IS NOT NULL
            GROUP BY p.seller_id
            ON CONFLICT (snap_date, seller_id) DO UPDATE SET
              products_count   = EXCLUDED.products_count,
              revenue_estimate = EXCLUDED.revenue_estimate,
              orders_estimate  = EXCLUDED.orders_estimate
            """,
            (snap, snap),
        )
        sellers_rows = cur.rowcount

        # Categories aggregation (products_count + revenue_estimate)
        cur.execute(
            """
            UPDATE market_categories_daily mc SET
              products_count   = sub.cnt,
              revenue_estimate = sub.rev
            FROM (
              SELECT category_id,
                     COUNT(*)                                AS cnt,
                     COALESCE(SUM(price * orders_amount),0)  AS rev
              FROM market_products_daily
              WHERE snap_date = %s
              GROUP BY category_id
            ) sub
            WHERE mc.snap_date = %s AND mc.category_id = sub.category_id
            """,
            (snap, snap),
        )
        cats_rows = cur.rowcount

        # Counts for log
        cur.execute("SELECT COUNT(*) FROM market_products_daily WHERE snap_date=%s", (snap,))
        products = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM market_sellers_daily  WHERE snap_date=%s", (snap,))
        sellers = cur.fetchone()[0]

    return {"products": products, "sellers": sellers, "sellers_rows": sellers_rows, "cats_rows": cats_rows}


def update_seller_titles(snap: date, titles: Dict[int, str]):
    """Обновляет seller_title для известных продавцов (название берётся из карточек товара)."""
    if not titles: return
    with _conn() as c, c.cursor() as cur:
        psycopg2.extras.execute_batch(
            cur,
            "UPDATE market_sellers_daily SET seller_title=%s WHERE snap_date=%s AND seller_id=%s",
            [(t, snap, sid) for sid, t in titles.items()],
            page_size=500,
        )
