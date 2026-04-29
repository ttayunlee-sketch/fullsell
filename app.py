import os
import hashlib
from pathlib import Path
from fastapi import FastAPI, Request, Form, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel
from jinja2 import Environment, FileSystemLoader
from database import (
    init_db, get_clients, get_client, add_client, delete_client,
    get_alerts, add_alert, save_snapshots_batch, last_snapshot_age_minutes,
)
from uzum import get_products, test_connection, get_finance_orders, get_finance_expenses, debug_finance_orders
from ai import ask as ai_ask, audit_product

_AUDIT_CACHE = {}  # (shop_id, product_id) -> (timestamp, text)
_AUDIT_TTL = 3600  # 1 час

BASE_DIR = Path(__file__).parent

app = FastAPI()
app.add_middleware(GZipMiddleware, minimum_size=500)


def _extract_image(p: dict) -> str:
    """Извлекает URL фото товара из разных форматов UZUM API."""
    photos = p.get("photos") or []
    if photos and isinstance(photos, list):
        ph = photos[0]
        if isinstance(ph, str):
            return ph
        if isinstance(ph, dict):
            for k in ("link", "url", "src", "photoUrl"):
                v = ph.get(k)
                if v and isinstance(v, str):
                    return v
            photo = ph.get("photo")
            if isinstance(photo, str):
                return photo
            if isinstance(photo, dict):
                for size in ("800", "540", "480", "400", "320", "240", "200"):
                    val = photo.get(size)
                    if isinstance(val, str):
                        return val
                    if isinstance(val, dict):
                        for q in ("high", "low", "url", "src"):
                            if val.get(q):
                                return val[q]
                for v in photo.values():
                    if isinstance(v, str) and v.startswith("http"):
                        return v
                    if isinstance(v, dict):
                        for q in ("high", "low", "url", "src"):
                            if v.get(q):
                                return v[q]
            key = ph.get("key") or ph.get("hash") or ph.get("id")
            if key:
                return f"https://images.uzum.uz/{key}/t800.jpg"
    for k in ("coverPhoto", "photoUrl", "image", "imageUrl", "mainPhoto", "main_photo"):
        v = p.get(k)
        if isinstance(v, str) and v:
            return v
        if isinstance(v, dict):
            for q in ("url", "link", "src", "high", "low"):
                if v.get(q):
                    return v[q]
    return ""


def _pick_num(p: dict, keys, default=0):
    """Возвращает первое числовое значение по списку ключей (учитывая вложенные dict)."""
    for k in keys:
        v = p.get(k)
        if isinstance(v, dict):
            for sub in ("value", "amount", "current", "min", "max"):
                if v.get(sub) is not None:
                    v = v[sub]
                    break
        if v is None or v == "":
            continue
        try:
            return float(v) if not isinstance(v, bool) else default
        except (TypeError, ValueError):
            continue
    return default


def _pick_ru_title(p: dict) -> str:
    """Выбирает русское название товара из разных форматов UZUM API."""
    for k in ("titleRu", "title_ru", "nameRu", "name_ru", "russianTitle"):
        v = p.get(k)
        if isinstance(v, str) and v.strip():
            return v
    for k in ("title", "name", "productName"):
        v = p.get(k)
        if isinstance(v, dict):
            for sub in ("ru", "ru_RU", "russian", "RU"):
                if isinstance(v.get(sub), str) and v[sub].strip():
                    return v[sub]
            for sub in ("uz", "default", "value"):
                if isinstance(v.get(sub), str) and v[sub].strip():
                    return v[sub]
        if isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    lang = (item.get("language") or item.get("lang") or item.get("locale") or "").lower()
                    val = item.get("value") or item.get("text") or item.get("title") or item.get("name")
                    if lang.startswith("ru") and isinstance(val, str) and val.strip():
                        return val
            for item in v:
                if isinstance(item, dict):
                    val = item.get("value") or item.get("text") or item.get("title") or item.get("name")
                    if isinstance(val, str) and val.strip():
                        return val
        if isinstance(v, str) and v.strip():
            return v
    locs = p.get("localizedTitles") or p.get("translations") or p.get("locales")
    if isinstance(locs, dict):
        for sub in ("ru", "ru_RU", "russian", "RU"):
            if isinstance(locs.get(sub), str) and locs[sub].strip():
                return locs[sub]
    return "—"


def _normalize(p: dict) -> dict:
    """Добавляет нормализованные поля price/views/rating/fbs/title."""
    p["image_url"] = _extract_image(p)
    p["title_norm"] = _pick_ru_title(p)
    p["price_norm"] = int(_pick_num(p, [
        "price", "salePrice", "fullPrice", "commercialPrice",
        "priceMin", "minPrice", "currentPrice", "mainPrice",
        "sellPrice", "purchasePrice"
    ]))
    p["views_norm"] = int(_pick_num(p, [
        "viewers", "views", "viewCount", "viewsCount",
        "totalViews", "showCount", "shows", "impressions"
    ]))
    p["rating_norm"] = round(_pick_num(p, [
        "rating", "productRating", "averageRating", "avgRating", "score"
    ]), 1)
    p["fbs_norm"] = int(_pick_num(p, [
        "quantityFbs", "fbsQuantity", "fbsStock", "stockFbs",
        "quantity", "stock", "remaining", "available"
    ]))
    status = p.get("status")
    if isinstance(status, dict):
        p["status_norm"] = status.get("value") or status.get("name") or status.get("code") or "—"
    elif isinstance(status, str):
        p["status_norm"] = status
    else:
        p["status_norm"] = "—"
    rank = p.get("rankInfo")
    if isinstance(rank, dict):
        p["rank_norm"] = rank.get("rank") or "—"
    else:
        p["rank_norm"] = p.get("rank") or "—"
    return p

_jinja_env = Environment(
    loader=FileSystemLoader(str(BASE_DIR / "templates")),
    cache_size=0,
)
templates = Jinja2Templates(env=_jinja_env)

PASSWORD   = os.environ.get("DASHBOARD_PASSWORD", "fullsell2026")
SECRET_KEY = os.environ.get("SECRET_KEY", "fs-secret-change-me")

def _token():
    return hashlib.sha256(f"{SECRET_KEY}:ok".encode()).hexdigest()

def _auth(session: str = None) -> bool:
    return session == _token()

init_db()

# ── Auth ──────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root(session: str = Cookie(default=None)):
    return RedirectResponse("/clients" if _auth(session) else "/login")

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = ""):
    return templates.TemplateResponse(request, "login.html", {"error": error})

@app.post("/login")
async def login(password: str = Form(...)):
    if password == PASSWORD:
        resp = RedirectResponse("/clients", status_code=303)
        resp.set_cookie("session", _token(), httponly=True, samesite="lax")
        return resp
    return RedirectResponse("/login?error=1", status_code=303)

@app.get("/logout")
async def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie("session")
    return resp

# ── Clients ───────────────────────────────────────────────────────────────────

@app.get("/clients", response_class=HTMLResponse)
async def clients_page(request: Request, session: str = Cookie(default=None)):
    if not _auth(session):
        return RedirectResponse("/login")
    return templates.TemplateResponse(request, "clients.html", {
        "clients": get_clients(),
    })

@app.post("/clients/add")
async def client_add(
    name:    str = Form(...),
    shop_id: int = Form(...),
    api_key: str = Form(...),
    session: str = Cookie(default=None),
):
    if not _auth(session):
        return RedirectResponse("/login")
    add_client(name, shop_id, api_key)
    return RedirectResponse("/clients", status_code=303)

@app.post("/clients/{cid}/delete")
async def client_delete(cid: int, session: str = Cookie(default=None)):
    if not _auth(session):
        return RedirectResponse("/login")
    delete_client(cid)
    return RedirectResponse("/clients", status_code=303)

# ── Shop dashboard ────────────────────────────────────────────────────────────

@app.get("/shop/{cid}", response_class=HTMLResponse)
async def shop_page(cid: int, request: Request, session: str = Cookie(default=None)):
    if not _auth(session):
        return RedirectResponse("/login")
    client = get_client(cid)
    if not client:
        return RedirectResponse("/clients")

    products = get_products(client["api_key"], client["shop_id"])

    for p in products:
        _normalize(p)

    # Снимки сохраняем максимум раз в час, и одним батчем
    if last_snapshot_age_minutes(client["shop_id"]) >= 60:
        rows = []
        for p in products:
            pid = str(p.get("productId") or p.get("id") or "")
            rows.append((client["shop_id"], pid, p["views_norm"], p["rating_norm"], p["fbs_norm"]))
            if 0 < p["fbs_norm"] <= 10:
                add_alert(client["shop_id"], pid, p["title_norm"][:50], "warn", f"Мало остатков FBS: {p['fbs_norm']} шт.")
        save_snapshots_batch(rows)

    active = [p for p in products if p["status_norm"] in ("IN_STOCK", "ACTIVE")]
    rated  = [p["rating_norm"] for p in products if p["rating_norm"] > 0]
    stats = {
        "total":  len(products),
        "active": len(active),
        "views":  sum(p["views_norm"] for p in products),
        "rating": round(sum(rated) / len(rated), 1) if rated else 0,
        "fbs":    sum(p["fbs_norm"] for p in products),
    }

    orders_raw = get_finance_orders(client["api_key"], client["shop_id"], days=30)
    finance = _finance_summary(orders_raw, products)

    return templates.TemplateResponse(request, "shop.html", {
        "client":   client,
        "products": products,
        "alerts":   get_alerts(client["shop_id"]),
        "stats":    stats,
        "finance":  finance,
    })


def _extract_order_image(o: dict) -> str:
    """Извлекает URL фото товара из заказа UZUM."""
    pi = o.get("productImage") or {}
    photo = pi.get("photo") if isinstance(pi, dict) else None
    if isinstance(photo, dict):
        for size in ("240", "320", "480", "540", "120", "80", "800", "720"):
            v = photo.get(size)
            if isinstance(v, dict):
                url = v.get("low") or v.get("high")
                if url:
                    return url
            elif isinstance(v, str):
                return v
    if isinstance(pi, dict):
        key = pi.get("photoKey")
        if key:
            return f"https://images.uzum.uz/{key}/t_product_240_low.jpg"
    return ""


def _norm_order(o: dict) -> dict:
    """Нормализует заказ под реальную схему UZUM Seller API /v1/finance/orders."""
    pid = str(o.get("productId") or "")
    title = o.get("productTitle") or o.get("skuTitle") or ""
    qty = int(o.get("amount") or 0)  # реально проданное; для CANCELED = 0
    sell_price = float(o.get("sellPrice") or 0)
    revenue = sell_price * qty
    profit = float(o.get("sellerProfit") or 0)
    commission = float(o.get("commission") or 0)
    status = str(o.get("status") or "")
    date_ms = o.get("date") or 0
    date_str = ""
    if isinstance(date_ms, (int, float)) and date_ms > 0:
        from datetime import datetime as _dt
        try:
            date_str = _dt.fromtimestamp(date_ms / 1000).date().isoformat()
        except Exception:
            pass
    return {
        "productId": pid,
        "title": title,
        "qty": qty,
        "amount": revenue,
        "sell_price": sell_price,
        "profit": profit,
        "commission": commission,
        "status": status,
        "date": date_str,
        "image_url": _extract_order_image(o),
    }


def _finance_summary(orders_raw: list, products: list) -> dict:
    """Считает выручку, прибыль, ТОП-10 товаров, продажи по дням, конверсию."""
    orders = [_norm_order(o) for o in orders_raw]
    # валидные = не отменённые (у них qty > 0)
    valid = [o for o in orders if o["qty"] > 0 and o["status"].upper() != "CANCELED"]
    cancelled = [o for o in orders if o["status"].upper() == "CANCELED" or o["qty"] == 0]

    total_revenue = sum(o["amount"] for o in valid)
    total_profit = sum(o["profit"] for o in valid)
    total_qty = sum(o["qty"] for o in valid)
    avg_check = (total_revenue / len(valid)) if valid else 0

    # ТОП по выручке (агрегируем по productId, копим image_url из заказа если есть)
    by_product = {}
    for o in valid:
        pid = o["productId"]
        if not pid:
            continue
        slot = by_product.setdefault(pid, {
            "pid": pid, "title": o["title"], "qty": 0, "amount": 0.0,
            "profit": 0.0, "image_url": o.get("image_url") or "",
        })
        slot["qty"] += o["qty"]
        slot["amount"] += o["amount"]
        slot["profit"] += o["profit"]
        if not slot["image_url"] and o.get("image_url"):
            slot["image_url"] = o["image_url"]

    # подтягиваем фото и название из таблицы товаров если в заказе пусто
    by_pid_product = {str(p.get("productId") or p.get("id") or ""): p for p in products}
    for slot in by_product.values():
        prod = by_pid_product.get(slot["pid"])
        if prod:
            if not slot["image_url"]:
                slot["image_url"] = prod.get("image_url") or ""
            if not slot["title"] and prod.get("title_norm"):
                slot["title"] = prod["title_norm"]
        if not slot["title"]:
            slot["title"] = "Товар " + slot["pid"]

    top = sorted(by_product.values(), key=lambda x: -x["amount"])[:10]

    # продажи по дням
    by_day = {}
    for o in valid:
        d = o["date"]
        if not d:
            continue
        slot = by_day.setdefault(d, {"qty": 0, "amount": 0.0})
        slot["qty"] += o["qty"]
        slot["amount"] += o["amount"]
    days_sorted = sorted(by_day.items())

    # конверсия = заказы / просмотры
    total_views = sum(p.get("views_norm") or 0 for p in products)
    conversion = (total_qty / total_views * 100) if total_views else 0

    return {
        "total_revenue": int(total_revenue),
        "total_profit": int(total_profit),
        "total_qty": total_qty,
        "orders_count": len(valid),
        "avg_check": int(avg_check),
        "conversion": round(conversion, 2),
        "top": top,
        "days": days_sorted,
        "raw_count": len(orders),
        "cancelled_count": len(cancelled),
    }



# ── AI ────────────────────────────────────────────────────────────────────────

class AskBody(BaseModel):
    message: str

@app.get("/shop/{cid}/finance/debug")
async def finance_debug(cid: int, session: str = Cookie(default=None)):
    if not _auth(session):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    client = get_client(cid)
    if not client:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return JSONResponse(debug_finance_orders(client["api_key"], client["shop_id"]))


@app.post("/shop/{cid}/product/{pid}/audit")
async def product_audit(cid: int, pid: str, session: str = Cookie(default=None)):
    import time as _t
    if not _auth(session):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    client = get_client(cid)
    if not client:
        return JSONResponse({"error": "Not found"}, status_code=404)

    cache_key = (client["shop_id"], pid)
    cached = _AUDIT_CACHE.get(cache_key)
    if cached and _t.time() - cached[0] < _AUDIT_TTL:
        return JSONResponse({"audit": cached[1], "cached": True})

    products = get_products(client["api_key"], client["shop_id"])
    target = None
    for p in products:
        ppid = str(p.get("productId") or p.get("id") or "")
        if ppid == pid:
            _normalize(p)
            target = p
            break
    if not target:
        return JSONResponse({"error": "Товар не найден"}, status_code=404)

    audit = audit_product(target, shop_name=client["name"])
    _AUDIT_CACHE[cache_key] = (_t.time(), audit)
    return JSONResponse({"audit": audit, "cached": False})


@app.post("/shop/{cid}/ai")
async def shop_ai(cid: int, body: AskBody, session: str = Cookie(default=None)):
    if not _auth(session):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    client = get_client(cid)
    if not client:
        return JSONResponse({"error": "Not found"}, status_code=404)
    products = get_products(client["api_key"], client["shop_id"])
    response = ai_ask(dict(client), products, body.message)
    return JSONResponse({"response": response})

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
