import os
import sqlite3
from pathlib import Path
from datetime import datetime

DB = os.environ.get("DB_PATH", str(Path(__file__).parent / "fullsell.db"))

def init_db():
    with sqlite3.connect(DB) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS clients (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                name     TEXT NOT NULL,
                shop_id  INTEGER NOT NULL,
                api_key  TEXT NOT NULL,
                added_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                shop_id    INTEGER NOT NULL,
                product_id TEXT NOT NULL,
                title      TEXT,
                kind       TEXT,
                message    TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS snapshots (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                shop_id    INTEGER NOT NULL,
                product_id TEXT NOT NULL,
                viewers    INTEGER,
                rating     REAL,
                fbs        INTEGER,
                taken_at   TEXT NOT NULL
            )
        """)
        conn.commit()

def _row(conn):
    conn.row_factory = sqlite3.Row
    return conn

def get_clients():
    with _row(sqlite3.connect(DB)) as conn:
        return conn.execute("SELECT * FROM clients ORDER BY id DESC").fetchall()

def get_client(client_id: int):
    with _row(sqlite3.connect(DB)) as conn:
        return conn.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()

def add_client(name: str, shop_id: int, api_key: str):
    with sqlite3.connect(DB) as conn:
        conn.execute(
            "INSERT INTO clients (name, shop_id, api_key, added_at) VALUES (?,?,?,?)",
            (name, shop_id, api_key, datetime.now().strftime("%d.%m.%Y"))
        )
        conn.commit()

def delete_client(client_id: int):
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM clients WHERE id=?", (client_id,))
        conn.commit()

def get_alerts(shop_id: int, limit: int = 30):
    with _row(sqlite3.connect(DB)) as conn:
        return conn.execute(
            "SELECT * FROM alerts WHERE shop_id=? ORDER BY id DESC LIMIT ?",
            (shop_id, limit)
        ).fetchall()

def add_alert(shop_id: int, product_id: str, title: str, kind: str, message: str):
    with sqlite3.connect(DB) as conn:
        conn.execute(
            "INSERT INTO alerts (shop_id, product_id, title, kind, message, created_at) VALUES (?,?,?,?,?,?)",
            (shop_id, product_id, title, kind, message, datetime.now().strftime("%d.%m.%Y %H:%M"))
        )
        conn.commit()

def save_snapshot(shop_id: int, product_id: str, viewers: int, rating: float, fbs: int):
    with sqlite3.connect(DB) as conn:
        conn.execute(
            "INSERT INTO snapshots (shop_id, product_id, viewers, rating, fbs, taken_at) VALUES (?,?,?,?,?,?)",
            (shop_id, product_id, viewers, rating, fbs, datetime.now().strftime("%d.%m.%Y %H:%M"))
        )
        conn.commit()

def get_snapshots(shop_id: int, product_id: str, limit: int = 14):
    with _row(sqlite3.connect(DB)) as conn:
        return conn.execute(
            "SELECT * FROM snapshots WHERE shop_id=? AND product_id=? ORDER BY id DESC LIMIT ?",
            (shop_id, product_id, limit)
        ).fetchall()
