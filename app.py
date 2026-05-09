import os
import hmac
import hashlib
import json as _json_lib
from pathlib import Path
from fastapi import FastAPI, Request, Form, Cookie, UploadFile, File, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from jinja2 import Environment, FileSystemLoader
from database import (
    init_db, get_clients, get_client, add_client, delete_client,
    get_alerts, add_alert, save_snapshots_batch, last_snapshot_age_minutes,
    update_client_seller_id, save_cabinet_token, get_cabinet_token,
)
from uzum import (
    get_products, test_connection, get_finance_orders, get_finance_expenses,
    debug_finance_orders, debug_ad_campaigns,
    get_ad_campaigns, get_boost_orders_products, get_ad_campaign_stats,
)
from ai import ask as ai_ask, audit_product, promotion_strategy, keywords_for_product
import market

_AUDIT_CACHE = {}  # (shop_id, product_id) -> (timestamp, text)
_AUDIT_TTL = 3600  # 1 час

BASE_DIR = Path(__file__).parent

app = FastAPI()
app.add_middleware(GZipMiddleware, minimum_size=500)
# CORS для Chrome-расширения (FullSell Connector)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"chrome-extension://.*",
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    allow_credentials=False,
)


@app.exception_handler(Exception)
async def _all_exc(request, exc):
    import traceback as _tb
    tb = _tb.format_exc()
    print(f"[FullSell ERROR] {request.url.path}\n{tb}", flush=True)
    return JSONResponse({"error": str(exc), "path": str(request.url.path), "trace": tb[-1500:]}, status_code=500)


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

PASSWORD         = os.environ.get("DASHBOARD_PASSWORD", "fullsell2026")
SECRET_KEY       = os.environ.get("SECRET_KEY", "fs-secret-change-me")
CONNECTOR_SECRET = os.environ.get("CONNECTOR_SECRET", "")  # секрет для расширения; если пусто — берём DASHBOARD_PASSWORD

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

# ── Market intelligence (UZUM-wide, ZoomSelling import) ──────────────────────

@app.get("/market", response_class=HTMLResponse)
async def market_page(request: Request, session: str = Cookie(default=None)):
    if not _auth(session):
        return RedirectResponse("/login")
    return templates.TemplateResponse(request, "market.html", market.load_market_data())


@app.post("/market/upload")
async def market_upload(
    sellers:   UploadFile = File(...),
    niches:    UploadFile = File(...),
    categories: UploadFile = File(...),
    period:    str        = Form("30 дней"),
    session:   str        = Cookie(default=None),
):
    if not _auth(session):
        return RedirectResponse("/login")
    market.MARKET_DIR.mkdir(exist_ok=True)
    for upload, dest in (
        (sellers,    market.SELLERS_FILE),
        (niches,     market.NICHES_FILE),
        (categories, market.CATEGORIES_FILE),
    ):
        data = await upload.read()
        dest.write_bytes(data)
    market.save_meta(period=period or "30 дней")
    return RedirectResponse("/market", status_code=303)


@app.post("/market/clear")
async def market_clear(session: str = Cookie(default=None)):
    if not _auth(session):
        return RedirectResponse("/login")
    for f in (market.SELLERS_FILE, market.NICHES_FILE, market.CATEGORIES_FILE, market.META_FILE):
        if f.exists(): f.unlink()
    return RedirectResponse("/market", status_code=303)


@app.post("/market/refresh")
async def market_refresh(session: str = Cookie(default=None)):
    """Кладёт флаг-файл в shared volume scraper_state. Хостовый cron каждую минуту
    проверяет флаг и запускает скрейпер. Возвращается сразу — скрейпер 5-15 мин."""
    if not _auth(session):
        return RedirectResponse("/login")
    try:
        flag_dir = Path("/state")
        if flag_dir.exists():
            (flag_dir / "refresh.flag").write_text("requested\n")
    except Exception as e:
        print(f"[market.refresh] failed to set flag: {e}", flush=True)
    return RedirectResponse("/market?refreshing=1", status_code=303)


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
    promo = _promotion_segments(products, finance.get("by_pid") or {})

    # Cabinet API: реклама (если есть seller_id и токен)
    seller_id = client.get("seller_id") if isinstance(client, dict) else None
    if not seller_id:
        try:
            seller_id = client["seller_id"]
        except (KeyError, TypeError):
            seller_id = None
    cabinet = {
        "has_token": False, "campaigns": [], "error": None,
        "token_age": None,
        "totals": {"impressions": 0, "clicks": 0, "expenses": 0,
                   "revenue": 0, "sold_qty": 0, "atc": 0, "crr": 0},
    }
    try:
        if seller_id:
            try:
                sid = int(seller_id)
            except (TypeError, ValueError):
                sid = None
            tok = get_cabinet_token(sid) if sid else None
            if tok and tok.get("token"):
                cabinet["has_token"] = True
                cabinet["token_age"] = tok.get("updated_at")
                res = get_ad_campaigns(tok["token"], sid, days=30)
                cabinet["campaigns"] = res.get("items") or []
                cabinet["error"] = res.get("error")
                # Обогащаем метриками из Cube.js (опционально, не падаем если что-то не так)
                if cabinet["campaigns"]:
                    try:
                        ids = [c.get("id") for c in cabinet["campaigns"] if c.get("id")]
                        ad_stats = get_ad_campaign_stats(tok["token"], ids, days=30) or {}
                        totals = {"impressions": 0, "clicks": 0, "expenses": 0,
                                  "revenue": 0, "sold_qty": 0, "atc": 0, "crr": 0}
                        for c in cabinet["campaigns"]:
                            s = ad_stats.get(str(c.get("id")), {}) or {}
                            c["stats"] = s
                            for k in ("impressions", "clicks", "expenses", "revenue", "sold_qty", "atc"):
                                try:
                                    totals[k] += int(s.get(k) or 0)
                                except (TypeError, ValueError):
                                    pass
                        if totals["revenue"]:
                            totals["crr"] = round(totals["expenses"] / totals["revenue"] * 100, 2)
                        cabinet["totals"] = totals
                    except Exception as e:
                        cabinet["error"] = f"stats_error: {e}"
    except Exception as e:
        cabinet["error"] = f"cabinet_error: {e}"

    return templates.TemplateResponse(request, "shop.html", {
        "client":    client,
        "products":  products,
        "alerts":    get_alerts(client["shop_id"]),
        "stats":     stats,
        "finance":   finance,
        "promo":     promo,
        "seller_id": seller_id,
        "cabinet":   cabinet,
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
        "by_pid": by_product,  # для аналитики продвижения
    }


def _promotion_segments(products: list, by_pid: dict) -> dict:
    """Сегментация товаров для продвижения по матрице «продажи × конверсия»."""
    rows = []
    for p in products:
        pid = str(p.get("productId") or p.get("id") or "")
        if not pid or p.get("status_norm") not in ("IN_STOCK", "ACTIVE"):
            continue
        sale = by_pid.get(pid, {})
        views = p.get("views_norm") or 0
        qty = sale.get("qty", 0)
        revenue = sale.get("amount", 0.0)
        profit = sale.get("profit", 0.0)
        rating = p.get("rating_norm") or 0
        fbs = p.get("fbs_norm") or 0
        # Конверсия = заказы / просмотры (в %)
        conv = (qty / views * 100) if views > 0 else 0
        rows.append({
            "pid": pid,
            "title": p.get("title_norm") or "—",
            "image_url": p.get("image_url") or sale.get("image_url") or "",
            "views": views,
            "qty": qty,
            "revenue": revenue,
            "profit": profit,
            "rating": rating,
            "fbs": fbs,
            "conv": round(conv, 2),
        })

    if not rows:
        return {"stars": [], "pearls": [], "stagnant": [], "ballast": [], "all": []}

    # Распределяем по сегментам
    stars, pearls, stagnant, ballast, cows = [], [], [], [], []
    for r in rows:
        v, q, rev, c = r["views"], r["qty"], r["revenue"], r["conv"]
        if rev > 0 and c >= 1.0 and v >= 200:
            # Хорошие продажи + конверсия + видимость = ⭐ Звёзды
            stars.append(r)
        elif c >= 1.5 and v < 500 and r["fbs"] > 0:
            # Высокая конверсия, но мало показов = 💎 Жемчужины (ПРОДВИГАТЬ!)
            pearls.append(r)
        elif v >= 300 and (q == 0 or c < 0.3):
            # Много показов, нет/почти нет продаж = 😴 Стагнация (улучшить карточку)
            stagnant.append(r)
        elif rev > 0 and v >= 500:
            # Стабильные продажи = 💰 Дойные коровы
            cows.append(r)
        else:
            ballast.append(r)

    stars.sort(key=lambda x: -x["revenue"])
    pearls.sort(key=lambda x: -x["conv"])
    stagnant.sort(key=lambda x: -x["views"])
    cows.sort(key=lambda x: -x["revenue"])
    ballast.sort(key=lambda x: -x["views"])

    return {
        "stars": stars[:8],
        "pearls": pearls[:8],
        "stagnant": stagnant[:8],
        "cows": cows[:6],
        "ballast": ballast[:5],
        "all": sorted(rows, key=lambda x: -x["views"]),
    }



# ── AI ────────────────────────────────────────────────────────────────────────

class AskBody(BaseModel):
    message: str

_PROMO_AI_CACHE = {}  # shop_id -> (ts, text)


@app.post("/shop/{cid}/promo/strategy")
async def promo_strategy(cid: int, session: str = Cookie(default=None)):
    import time as _t
    if not _auth(session):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    client = get_client(cid)
    if not client:
        return JSONResponse({"error": "Not found"}, status_code=404)

    cached = _PROMO_AI_CACHE.get(client["shop_id"])
    if cached and _t.time() - cached[0] < 1800:  # 30 мин
        return JSONResponse({"strategy": cached[1], "cached": True})

    products = get_products(client["api_key"], client["shop_id"])
    for p in products:
        _normalize(p)
    orders_raw = get_finance_orders(client["api_key"], client["shop_id"], days=30)
    finance = _finance_summary(orders_raw, products)
    segments = _promotion_segments(products, finance.get("by_pid") or {})
    text = promotion_strategy(dict(client), products, finance, segments)
    _PROMO_AI_CACHE[client["shop_id"]] = (_t.time(), text)
    return JSONResponse({"strategy": text, "cached": False})


_KEYWORDS_AI_CACHE = {}  # (shop_id, product_id) -> (ts, dict)
_KEYWORDS_AI_TTL = 3600 * 6  # 6 часов


@app.post("/shop/{cid}/product/{pid}/keywords")
async def product_keywords(cid: int, pid: str, session: str = Cookie(default=None)):
    """AI-рекомендации ключей и минус-слов для ОДНОГО товара (стиль ZoomSelling-AI)."""
    import time as _t
    if not _auth(session):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    client = get_client(cid)
    if not client:
        return JSONResponse({"error": "Not found"}, status_code=404)

    cache_key = (client["shop_id"], str(pid))
    cached = _KEYWORDS_AI_CACHE.get(cache_key)
    if cached and _t.time() - cached[0] < _KEYWORDS_AI_TTL:
        return JSONResponse({**cached[1], "cached": True})

    products = get_products(client["api_key"], client["shop_id"])
    for p in products:
        _normalize(p)

    target = None
    for p in products:
        if str(p.get("id") or p.get("productId") or "") == str(pid):
            target = p
            break
    if not target:
        return JSONResponse({"error": f"Товар pid={pid} не найден в магазине"}, status_code=404)

    # Картинку прицепляем если есть
    if not target.get("image_url"):
        target["image_url"] = _extract_image(target)

    result = keywords_for_product(target, shop_name=client.get("name", ""))
    if "error" in result:
        return JSONResponse(result, status_code=500)
    _KEYWORDS_AI_CACHE[cache_key] = (_t.time(), result)
    return JSONResponse({**result, "cached": False})


class ExtTokenBody(BaseModel):
    token: str
    sellerId: int
    secret: str


@app.post("/api/extension/token")
async def extension_token(body: ExtTokenBody):
    """Принимает токен сессии кабинета от Chrome-расширения. Авторизация — connector secret."""
    expected = CONNECTOR_SECRET or PASSWORD
    if not expected or body.secret != expected:
        return JSONResponse({"error": "Forbidden"}, status_code=403)
    if not body.token or len(body.token) < 10 or not body.sellerId:
        return JSONResponse({"error": "Invalid token/sellerId"}, status_code=400)
    save_cabinet_token(body.sellerId, body.token)
    return JSONResponse({"ok": True, "sellerId": body.sellerId})


@app.post("/clients/{cid}/seller-id")
async def set_seller_id(cid: int, seller_id: int = Form(...), session: str = Cookie(default=None)):
    if not _auth(session):
        return RedirectResponse("/login")
    update_client_seller_id(cid, seller_id)
    return RedirectResponse(f"/shop/{cid}", status_code=303)


@app.post("/clients/{cid}/cabinet-token")
async def set_cabinet_token_manual(
    cid: int,
    token: str = Form(...),
    session: str = Cookie(default=None),
):
    """Ручной ввод токена кабинета — без расширения."""
    if not _auth(session):
        return RedirectResponse("/login")
    client = get_client(cid)
    if not client:
        return RedirectResponse("/clients")
    seller_id = None
    try:
        seller_id = client["seller_id"]
    except (KeyError, TypeError):
        pass
    if not seller_id:
        return RedirectResponse(f"/shop/{cid}", status_code=303)
    # Чистим: убираем Bearer prefix, кавычки, пробелы
    token = token.strip().strip('"').strip("'")
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if len(token) < 10:
        return RedirectResponse(f"/shop/{cid}", status_code=303)
    save_cabinet_token(int(seller_id), token)
    return RedirectResponse(f"/shop/{cid}", status_code=303)


@app.get("/shop/{cid}/finance/debug")
async def finance_debug(cid: int, session: str = Cookie(default=None)):
    if not _auth(session):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    client = get_client(cid)
    if not client:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return JSONResponse(debug_finance_orders(client["api_key"], client["shop_id"]))


@app.get("/shop/{cid}/promo/debug")
async def promo_debug(cid: int, seller_id: int, session: str = Cookie(default=None)):
    if not _auth(session):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    client = get_client(cid)
    if not client:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return JSONResponse(debug_ad_campaigns(client["api_key"], seller_id))


@app.get("/shop/{cid}/promo/raw")
async def promo_raw(cid: int, session: str = Cookie(default=None)):
    """Возвращает сырой ответ cabinet API — нужен для диагностики структуры payload."""
    import requests as _r
    if not _auth(session):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    client = get_client(cid)
    if not client:
        return JSONResponse({"error": "Not found"}, status_code=404)
    seller_id = client.get("seller_id") if isinstance(client, dict) else None
    try:
        seller_id = client["seller_id"]
    except (KeyError, TypeError):
        pass
    if not seller_id:
        return JSONResponse({"error": "no_seller_id"})
    tok = get_cabinet_token(int(seller_id))
    if not tok or not tok.get("token"):
        return JSONResponse({"error": "no_token"})

    from datetime import datetime, timedelta
    to_d = datetime.now().date()
    from_d = to_d - timedelta(days=30)
    headers = {
        "Authorization": f"Bearer {tok['token']}",
        "Accept": "application/json",
        "Accept-Language": "ru",
        "Origin": "https://seller.uzum.uz",
        "Referer": "https://seller.uzum.uz/",
    }
    try:
        r = _r.get(
            "https://api-seller.uzum.uz/api/seller/advertising/management/ad-campaign",
            headers=headers,
            params={
                "sellerId": int(seller_id),
                "page": 0, "size": 20,
                "from": from_d.isoformat(), "to": to_d.isoformat(),
                "statusGroup": "ALL",
            },
            timeout=15,
        )
        body = None
        try:
            body = r.json()
        except Exception:
            body = r.text[:1000]
        return JSONResponse({
            "status": r.status_code,
            "url": r.url,
            "token_age": tok.get("updated_at"),
            "body": body,
        })
    except Exception as e:
        return JSONResponse({"error": str(e)})


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

# ── INSTAGRAM WEBHOOK ─────────────────────────────────────────────────────────
# Принимает события от Meta (входящие DM, реакции, etc.) и подтверждает подписку.
# Документация: https://developers.facebook.com/docs/instagram-platform/webhooks

IG_VERIFY_TOKEN = os.environ.get("IG_VERIFY_TOKEN", "")
IG_APP_SECRET   = os.environ.get("IG_APP_SECRET", "")

_IG_LOG_PATH = Path("/app/instagram_events.log")


def _ig_log(msg: str) -> None:
    """Пишет лог Instagram-событий в файл — для дебага в режиме разработки."""
    try:
        _IG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _IG_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception as e:
        print(f"[IG LOG ERROR] {e}", flush=True)


@app.get("/webhook/instagram")
async def instagram_verify(request: Request):
    """Проверка подписки Meta. Meta делает GET с hub.* параметрами и ждёт challenge обратно."""
    params = request.query_params
    mode      = params.get("hub.mode")
    token     = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")
    print(f"[IG VERIFY] mode={mode} token_match={token == IG_VERIFY_TOKEN} challenge={challenge}", flush=True)
    if mode == "subscribe" and token and IG_VERIFY_TOKEN and token == IG_VERIFY_TOKEN:
        # Meta ждёт PLAIN TEXT с challenge, без JSON-обёртки
        return PlainTextResponse(challenge or "")
    return JSONResponse({"error": "verify_token mismatch or empty"}, status_code=403)


def _verify_ig_signature(body: bytes, signature: str) -> bool:
    """Проверяет X-Hub-Signature-256 от Meta — гарантия что запрос от них."""
    if not IG_APP_SECRET:
        return True  # в Dev-режиме без секрета пропускаем
    if not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        IG_APP_SECRET.encode("utf-8"), body, hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@app.post("/webhook/instagram")
async def instagram_event(request: Request, background_tasks: BackgroundTasks):
    """Приём входящих DM и других событий от Instagram.
    Meta даёт нам 5 секунд на ответ — поэтому AI-обработку отправляем в фон."""
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")

    if not _verify_ig_signature(body, signature):
        print(f"[IG WEBHOOK] invalid signature: {signature[:30]}", flush=True)
        return JSONResponse({"error": "invalid signature"}, status_code=403)

    try:
        data = _json_lib.loads(body.decode("utf-8") or "{}")
    except Exception as e:
        return JSONResponse({"error": f"invalid json: {e}"}, status_code=400)

    # Логируем событие (для дебага — потом смотрим формат)
    import datetime as _dt
    log_line = f"[{_dt.datetime.utcnow().isoformat()}Z] {_json_lib.dumps(data, ensure_ascii=False)}"
    _ig_log(log_line)
    print(f"[IG WEBHOOK] {log_line[:500]}", flush=True)

    # TODO: следующий этап — фоновая задача с AI-ответом через Send API
    # background_tasks.add_task(handle_ig_event, data)

    return JSONResponse({"ok": True})


@app.get("/webhook/instagram/log")
async def instagram_log_view(session: str = Cookie(default=None), tail: int = 50):
    """Просмотр последних входящих событий — для дебага в браузере."""
    if not _auth(session):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    if not _IG_LOG_PATH.exists():
        return PlainTextResponse("(no events yet)\n")
    try:
        lines = _IG_LOG_PATH.read_text(encoding="utf-8").splitlines()
        return PlainTextResponse("\n".join(lines[-tail:]) + "\n")
    except Exception as e:
        return PlainTextResponse(f"error: {e}\n", status_code=500)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
