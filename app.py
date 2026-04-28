import os
import hashlib
from pathlib import Path
from fastapi import FastAPI, Request, Form, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from jinja2 import Environment, FileSystemLoader
from database import init_db, get_clients, get_client, add_client, delete_client, get_alerts, add_alert, save_snapshot
from uzum import get_products, test_connection
from ai import ask as ai_ask

BASE_DIR = Path(__file__).parent

app = FastAPI()

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
        pid     = str(p.get("productId", ""))
        viewers = p.get("viewers") or 0
        rating  = float(p.get("rating") or 0)
        fbs     = p.get("quantityFbs") or 0
        title   = (p.get("title") or "")[:50]
        save_snapshot(client["shop_id"], pid, viewers, rating, fbs)
        if fbs > 0 and fbs <= 10:
            add_alert(client["shop_id"], pid, title, "warn", f"Мало остатков FBS: {fbs} шт.")

    active = [p for p in products if p.get("status", {}).get("value") == "IN_STOCK"]
    stats = {
        "total":  len(products),
        "active": len(active),
        "views":  sum(p.get("viewers") or 0 for p in products),
        "rating": round(sum(float(p.get("rating") or 0) for p in products) / len(products), 1) if products else 0,
        "fbs":    sum(p.get("quantityFbs") or 0 for p in products),
    }

    return templates.TemplateResponse(request, "shop.html", {
        "client":   client,
        "products": products,
        "alerts":   get_alerts(client["shop_id"]),
        "stats":    stats,
    })

# ── AI ────────────────────────────────────────────────────────────────────────

class AskBody(BaseModel):
    message: str

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
