"""
Парсер CSV-экспортов из ZoomSelling.
Превращает три файла (Рейтинг магазинов / Ниши / Категории) в нормализованные структуры
для дашборда «Рынок UZUM».
"""
from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import List, Dict, Any, Optional

BASE_DIR = Path(__file__).parent
MARKET_DIR = BASE_DIR / "market_data"
MARKET_DIR.mkdir(exist_ok=True)

SELLERS_FILE    = MARKET_DIR / "sellers.csv"
NICHES_FILE     = MARKET_DIR / "niches.csv"
CATEGORIES_FILE = MARKET_DIR / "categories.csv"
META_FILE       = MARKET_DIR / "meta.txt"


# ─────────────────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────────────────

def _to_float(v: Any) -> float:
    if v is None: return 0.0
    s = str(v).replace(" ", "").replace(" ", "").replace(",", ".")
    if not s or s.lower() in ("null", "nan", "none", "—", "-"): return 0.0
    try: return float(s)
    except ValueError: return 0.0

def _to_int(v: Any) -> int:
    return int(_to_float(v))

def _format_money(value: float) -> str:
    """578903588048 → '578,9 млрд'"""
    v = abs(value)
    sign = "-" if value < 0 else ""
    if v >= 1_000_000_000:
        return f"{sign}{v/1_000_000_000:.1f} млрд".replace(".", ",")
    if v >= 1_000_000:
        return f"{sign}{v/1_000_000:.1f} млн".replace(".", ",")
    if v >= 1_000:
        return f"{sign}{v/1_000:.0f} тыс".replace(".", ",")
    return f"{sign}{v:.0f}"

def _parse_money_str(s: str) -> float:
    """'40,6 млрд' / '6,1 млн' / '578 903 588 048' → float (sum)"""
    if not s: return 0.0
    s = str(s).strip().lower().replace(" ", " ")
    mult = 1.0
    if "млрд" in s: mult = 1_000_000_000
    elif "млн" in s: mult = 1_000_000
    elif "тыс" in s: mult = 1_000
    s = s.replace("млрд", "").replace("млн", "").replace("тыс", "")
    s = s.replace("сум", "").replace("сум.", "").strip()
    s = s.replace(" ", "").replace(",", ".")
    try: return float(s) * mult
    except ValueError: return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# parsing
# ─────────────────────────────────────────────────────────────────────────────

def _read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists(): return []
    rows: List[Dict[str, str]] = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({(k or "").strip(): (v or "").strip() for k, v in r.items()})
    return rows


def parse_sellers() -> List[Dict[str, Any]]:
    """
    CSV: Магазин, Селлер (юрлицо), Выручка сум., % роста, Доля рынка,
         Продажи штук, Продажи в день, Оборот дней, Заказы за период, Заказы за все время
    """
    out: List[Dict[str, Any]] = []
    for r in _read_csv(SELLERS_FILE):
        revenue = _to_float(r.get("Выручка, сум.") or r.get("Выручка"))
        growth  = _to_float(r.get("% роста"))           # доля (0.148 = 14.8%) или %?
        share   = _to_float(r.get("Доля рынка"))         # доля (0.014 = 1.4%)
        # Z-S отдает либо доли (0.05) либо проценты (5) — нормализуем
        if abs(growth) > 5: growth = growth / 100.0
        if share > 1: share = share / 100.0
        out.append({
            "name":          r.get("Магазин") or "—",
            "legal":         r.get("Селлер (юрлицо)") or "",
            "revenue":       revenue,
            "revenue_str":   _format_money(revenue),
            "growth":        growth,                      # как доля, для UI *100
            "share":         share,                       # как доля
            "sold":          _to_int(r.get("Продажи, штук")),
            "sold_per_day":  _to_float(r.get("Продажи в день")),
            "turnover_days": _to_float(r.get("Оборот, дней")),
            "orders_period": _to_int(r.get("Заказы за период")),
            "orders_total":  _to_int(r.get("Заказы за все время")),
        })
    out.sort(key=lambda x: x["revenue"], reverse=True)
    return out


def parse_niches() -> List[Dict[str, Any]]:
    """
    CSV: Категория, Выручка, % роста, Продажи штук, Цена средняя (медиана),
         Магазинов, c продажами, Карточек, с продажами, Выручка на магазин, Оборот дней
    """
    out: List[Dict[str, Any]] = []
    for r in _read_csv(NICHES_FILE):
        revenue = _parse_money_str(r.get("Выручка") or "")
        growth_raw = (r.get("% роста") or "").replace("%", "").strip()
        try: growth = float(growth_raw.replace(",", ".")) / 100.0
        except ValueError: growth = 0.0
        rev_per_shop = _parse_money_str(r.get("Выручка на магазин") or "")
        out.append({
            "category":      r.get("Категория") or "—",
            "revenue":       revenue,
            "revenue_str":   _format_money(revenue),
            "growth":        growth,
            "sold":          _to_int(r.get("Продажи, штук")),
            "price_median":  _to_int(r.get("Цена средняя (медиана)")),
            "shops":         _to_int(r.get("Магазинов")),
            "shops_with_sales_pct": _to_float(r.get("c продажами")),
            "cards":         _to_int(r.get("Карточек")),
            "cards_with_sales_pct": _to_float(r.get("с продажами")),
            "rev_per_shop":  rev_per_shop,
            "rev_per_shop_str": _format_money(rev_per_shop),
            "turnover_days": _to_float(r.get("Оборот, дней")),
        })
    out.sort(key=lambda x: x["revenue"], reverse=True)
    return out


def parse_categories() -> List[Dict[str, Any]]:
    """
    CSV: Категория 2ур., Категория 3ур., Категория 4ур., Категория 5ур., Выручка сум.
    Группируем по верхнему уровню (2ур.) для пирога.
    """
    rows = _read_csv(CATEGORIES_FILE)
    out: List[Dict[str, Any]] = []
    for r in rows:
        rev = _to_float(r.get("Выручка, сум.") or r.get("Выручка"))
        out.append({
            "lvl2": r.get("Категория 2ур.") or "—",
            "lvl3": r.get("Категория 3ур.") or "",
            "lvl4": r.get("Категория 4ур.") or "",
            "lvl5": r.get("Категория 5ур.") or "",
            "revenue": rev,
        })
    return out


def aggregate_categories_top(rows: List[Dict[str, Any]], top: int = 12) -> List[Dict[str, Any]]:
    by_top: Dict[str, float] = {}
    for r in rows:
        if r["lvl2"] in ("", "null", "—"): continue
        by_top[r["lvl2"]] = by_top.get(r["lvl2"], 0.0) + r["revenue"]
    items = [{"name": k, "revenue": v, "revenue_str": _format_money(v)} for k, v in by_top.items()]
    items.sort(key=lambda x: x["revenue"], reverse=True)
    total = sum(x["revenue"] for x in items) or 1.0
    for x in items:
        x["share"] = x["revenue"] / total
    return items[:top]


# ─────────────────────────────────────────────────────────────────────────────
# overview / KPI
# ─────────────────────────────────────────────────────────────────────────────

def overview(sellers: List[Dict[str, Any]], niches: List[Dict[str, Any]]) -> Dict[str, Any]:
    total_rev = sum(s["revenue"] for s in sellers)
    sellers_count = len(sellers)
    sellers_growing = sum(1 for s in sellers if s["growth"] > 0)
    sellers_falling = sum(1 for s in sellers if s["growth"] < 0)
    niches_count = len(niches)
    avg_check = 0.0
    if sellers_count > 0:
        total_orders = sum(s["orders_period"] for s in sellers)
        if total_orders > 0:
            avg_check = total_rev / total_orders

    # выручка-взвешенный средний рост — реальная динамика рынка
    weighted_growth = 0.0
    if total_rev > 0:
        weighted_growth = sum(s["revenue"] * s["growth"] for s in sellers) / total_rev

    return {
        "total_revenue":     total_rev,
        "total_revenue_str": _format_money(total_rev),
        "sellers_count":     sellers_count,
        "sellers_growing":   sellers_growing,
        "sellers_falling":   sellers_falling,
        "niches_count":      niches_count,
        "avg_check":         avg_check,
        "avg_check_str":     _format_money(avg_check),
        "weighted_growth":   weighted_growth,
    }


# ─────────────────────────────────────────────────────────────────────────────
# meta / state
# ─────────────────────────────────────────────────────────────────────────────

def has_data() -> bool:
    return SELLERS_FILE.exists() and NICHES_FILE.exists() and CATEGORIES_FILE.exists()

def get_meta() -> Dict[str, Any]:
    if not META_FILE.exists():
        return {"uploaded_at": None, "period": None}
    try:
        text = META_FILE.read_text(encoding="utf-8").strip()
        parts = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
        return {"uploaded_at": parts.get("uploaded_at"), "period": parts.get("period")}
    except Exception:
        return {"uploaded_at": None, "period": None}

def save_meta(period: str = "30 дней"):
    from datetime import datetime
    META_FILE.write_text(
        f"uploaded_at={datetime.now().strftime('%Y-%m-%d %H:%M')}\nperiod={period}\n",
        encoding="utf-8",
    )


# ─────────────────────────────────────────────────────────────────────────────
# main bundler
# ─────────────────────────────────────────────────────────────────────────────

def load_market_data(top_sellers: int = 50, top_niches: int = 50, top_cats: int = 12) -> Dict[str, Any]:
    """Возвращает всё что нужно market.html: KPI + топы + категории."""
    sellers = parse_sellers()
    niches  = parse_niches()
    cats    = parse_categories()

    return {
        "has_data":   has_data(),
        "meta":       get_meta(),
        "kpi":        overview(sellers, niches),
        "top_sellers": sellers[:top_sellers],
        "all_sellers_count": len(sellers),
        "top_niches": niches[:top_niches],
        "all_niches_count": len(niches),
        "top_categories": aggregate_categories_top(cats, top=top_cats),
        "growers":    sorted([s for s in sellers if s["growth"] > 0], key=lambda x: x["growth"], reverse=True)[:10],
        "fallers":    sorted([s for s in sellers if s["growth"] < 0], key=lambda x: x["growth"])[:10],
    }
