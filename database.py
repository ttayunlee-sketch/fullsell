import os
import sqlite3
from pathlib import Path
from datetime import datetime

DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL:
    import psycopg2
    import psycopg2.extras
    _PH = "%s"

    def _get_conn():
        url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
        return psycopg2.connect(url)

    def _dict_cur(conn):
        return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def _cur(conn):
        return conn.cursor()

    _SERIAL = "SERIAL"
    _AUTOINCREMENT = ""
else:
    _DB = os.environ.get("DB_PATH", str(Path(__file__).parent / "fullsell.db"))
    _PH = "?"

    def _get_conn():
        conn = sqlite3.connect(_DB)
        conn.row_factory = sqlite3.Row
        return conn

    def _dict_cur(conn):
        return conn.cursor()

    def _cur(conn):
        return conn.cursor()

    _SERIAL = "INTEGER"
    _AUTOINCREMENT = "AUTOINCREMENT"


def init_db():
    conn = _get_conn()
    try:
        c = _cur(conn)
        c.execute(f"""
            CREATE TABLE IF NOT EXISTS clients (
                id       {_SERIAL} PRIMARY KEY {_AUTOINCREMENT},
                name     TEXT NOT NULL,
                shop_id  INTEGER NOT NULL,
                api_key  TEXT NOT NULL,
                added_at TEXT NOT NULL
            )
        """)
        c.execute(f"""
            CREATE TABLE IF NOT EXISTS alerts (
                id         {_SERIAL} PRIMARY KEY {_AUTOINCREMENT},
                shop_id    INTEGER NOT NULL,
                product_id TEXT NOT NULL,
                title      TEXT,
                kind       TEXT,
                message    TEXT,
                created_at TEXT NOT NULL
            )
        """)
        c.execute(f"""
            CREATE TABLE IF NOT EXISTS snapshots (
                id         {_SERIAL} PRIMARY KEY {_AUTOINCREMENT},
                shop_id    INTEGER NOT NULL,
                product_id TEXT NOT NULL,
                viewers    INTEGER,
                rating     REAL,
                fbs        INTEGER,
                taken_at   TEXT NOT NULL
            )
        """)
        c.execute(f"""
            CREATE TABLE IF NOT EXISTS promotions (
                id         {_SERIAL} PRIMARY KEY {_AUTOINCREMENT},
                shop_id    INTEGER NOT NULL,
                product_id TEXT NOT NULL,
                title      TEXT,
                keyword    TEXT NOT NULL,
                position   INTEGER,
                target     INTEGER,
                status     TEXT,
                added_at   TEXT NOT NULL
            )
        """)
        conn.commit()
    finally:
        conn.close()


def get_clients():
    conn = _get_conn()
    try:
        c = _dict_cur(conn)
        c.execute("SELECT * FROM clients ORDER BY id DESC")
        return c.fetchall()
    finally:
        conn.close()


def get_client(client_id: int):
    conn = _get_conn()
    try:
        c = _dict_cur(conn)
        c.execute(f"SELECT * FROM clients WHERE id={_PH}", (client_id,))
        return c.fetchone()
    finally:
        conn.close()


def add_client(name: str, shop_id: int, api_key: str):
    conn = _get_conn()
    try:
        c = _cur(conn)
        c.execute(
            f"INSERT INTO clients (name, shop_id, api_key, added_at) VALUES ({_PH},{_PH},{_PH},{_PH})",
            (name, shop_id, api_key, datetime.now().strftime("%d.%m.%Y"))
        )
        conn.commit()
    finally:
        conn.close()


def delete_client(client_id: int):
    conn = _get_conn()
    try:
        c = _cur(conn)
        c.execute(f"DELETE FROM clients WHERE id={_PH}", (client_id,))
        conn.commit()
    finally:
        conn.close()


def get_alerts(shop_id: int, limit: int = 30):
    conn = _get_conn()
    try:
        c = _dict_cur(conn)
        c.execute(
            f"SELECT * FROM alerts WHERE shop_id={_PH} ORDER BY id DESC LIMIT {_PH}",
            (shop_id, limit)
        )
        return c.fetchall()
    finally:
        conn.close()


def add_alert(shop_id: int, product_id: str, title: str, kind: str, message: str):
    conn = _get_conn()
    try:
        c = _cur(conn)
        c.execute(
            f"INSERT INTO alerts (shop_id, product_id, title, kind, message, created_at) VALUES ({_PH},{_PH},{_PH},{_PH},{_PH},{_PH})",
            (shop_id, product_id, title, kind, message, datetime.now().strftime("%d.%m.%Y %H:%M"))
        )
        conn.commit()
    finally:
        conn.close()


def save_snapshot(shop_id: int, product_id: str, viewers: int, rating: float, fbs: int):
    conn = _get_conn()
    try:
        c = _cur(conn)
        c.execute(
            f"INSERT INTO snapshots (shop_id, product_id, viewers, rating, fbs, taken_at) VALUES ({_PH},{_PH},{_PH},{_PH},{_PH},{_PH})",
            (shop_id, product_id, viewers, rating, fbs, datetime.now().strftime("%d.%m.%Y %H:%M"))
        )
        conn.commit()
    finally:
        conn.close()


def save_snapshots_batch(rows):
    """rows: список кортежей (shop_id, product_id, viewers, rating, fbs)."""
    if not rows:
        return
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    payload = [(s, p, v, r, f, now) for (s, p, v, r, f) in rows]
    conn = _get_conn()
    try:
        c = _cur(conn)
        c.executemany(
            f"INSERT INTO snapshots (shop_id, product_id, viewers, rating, fbs, taken_at) VALUES ({_PH},{_PH},{_PH},{_PH},{_PH},{_PH})",
            payload
        )
        conn.commit()
    finally:
        conn.close()


def add_promotion(shop_id: int, product_id: str, title: str, keyword: str, target: int = 10):
    conn = _get_conn()
    try:
        c = _cur(conn)
        c.execute(
            f"INSERT INTO promotions (shop_id, product_id, title, keyword, position, target, status, added_at) VALUES ({_PH},{_PH},{_PH},{_PH},{_PH},{_PH},{_PH},{_PH})",
            (shop_id, product_id, title, keyword, None, target, "active", datetime.now().strftime("%d.%m.%Y"))
        )
        conn.commit()
    finally:
        conn.close()


def get_promotions(shop_id: int):
    conn = _get_conn()
    try:
        c = _dict_cur(conn)
        c.execute(f"SELECT * FROM promotions WHERE shop_id={_PH} ORDER BY id DESC", (shop_id,))
        return c.fetchall()
    finally:
        conn.close()


def delete_promotion(promo_id: int):
    conn = _get_conn()
    try:
        c = _cur(conn)
        c.execute(f"DELETE FROM promotions WHERE id={_PH}", (promo_id,))
        conn.commit()
    finally:
        conn.close()


def update_promotion_status(promo_id: int, status: str):
    conn = _get_conn()
    try:
        c = _cur(conn)
        c.execute(f"UPDATE promotions SET status={_PH} WHERE id={_PH}", (status, promo_id))
        conn.commit()
    finally:
        conn.close()


def last_snapshot_age_minutes(shop_id: int) -> float:
    """Возраст последнего снимка в минутах (или 9999 если снимков нет)."""
    conn = _get_conn()
    try:
        c = _dict_cur(conn)
        c.execute(
            f"SELECT taken_at FROM snapshots WHERE shop_id={_PH} ORDER BY id DESC LIMIT 1",
            (shop_id,)
        )
        row = c.fetchone()
        if not row:
            return 9999.0
        taken_at = row["taken_at"] if isinstance(row, dict) or hasattr(row, "keys") else row[0]
        try:
            dt = datetime.strptime(taken_at, "%d.%m.%Y %H:%M")
            return (datetime.now() - dt).total_seconds() / 60
        except Exception:
            return 9999.0
    finally:
        conn.close()


def get_snapshots(shop_id: int, product_id: str, limit: int = 14):
    conn = _get_conn()
    try:
        c = _dict_cur(conn)
        c.execute(
            f"SELECT * FROM snapshots WHERE shop_id={_PH} AND product_id={_PH} ORDER BY id DESC LIMIT {_PH}",
            (shop_id, product_id, limit)
        )
        return c.fetchall()
    finally:
        conn.close()
