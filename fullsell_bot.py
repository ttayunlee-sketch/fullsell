"""
FullSell Telegram Bot — Мониторинг товаров на UZUM
Автор: FullSell Agency
"""

import os
import logging
import requests
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes
)

# =============================================
# КОНФИГУРАЦИЯ
# =============================================
TELEGRAM_TOKEN  = os.environ.get("TELEGRAM_TOKEN", "")
UZUM_API_KEY    = os.environ.get("UZUM_API_KEY", "")
SHOP_ID         = 110091
UZUM_SELLER_URL = "https://api-seller.uzum.uz/api/seller-openapi"
CHECK_INTERVAL  = 60 * 60  # каждый час

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

state = {
    "subscribers": set(),
    "positions": {},
    "last_check": None,
}

def _msg(update: Update):
    return update.message or update.callback_query.message

async def _loading(update: Update, text: str = "🔍 Загружаю..."):
    return await _msg(update).reply_text(text)

# =============================================
# UZUM API
# =============================================

def get_headers():
    return {
        "Authorization": UZUM_API_KEY,
        "Content-Type": "application/json"
    }

def get_products(filter_type="ALL"):
    try:
        r = requests.get(
            f"{UZUM_SELLER_URL}/v1/product/shop/{SHOP_ID}",
            headers=get_headers(),
            params={"page": 0, "size": 50, "filter": filter_type},
            timeout=10
        )
        if r.status_code == 200:
            return r.json().get("productList", [])
        else:
            logger.error(f"Ошибка API: {r.status_code}")
    except Exception as e:
        logger.error(f"Ошибка запроса: {e}")
    return []

# =============================================
# МОНИТОРИНГ
# =============================================

async def check_positions(context: ContextTypes.DEFAULT_TYPE):
    if not state["subscribers"]:
        return

    products = get_products("ACTIVE")
    if not products:
        return

    alerts = []
    for p in products:
        pid      = str(p.get("productId", ""))
        name     = p.get("title", "")[:40]
        viewers  = p.get("viewers", 0) or 0
        old      = state["positions"].get(pid, {})

        if old:
            old_viewers = old.get("viewers", 0)
            if viewers > old_viewers * 1.2 and old_viewers > 0:
                alerts.append(f"📈 <b>{name}</b>\n   Просмотры выросли: {old_viewers} → {viewers}")
            elif viewers < old_viewers * 0.8 and old_viewers > 0:
                alerts.append(f"📉 <b>{name}</b>\n   Просмотры упали: {old_viewers} → {viewers}")

        state["positions"][pid] = {"viewers": viewers}

    state["last_check"] = datetime.now().strftime("%d.%m.%Y %H:%M")

    if alerts:
        text = (
            "🔔 <b>FullSell — Изменения на UZUM</b>\n\n"
            + "\n\n".join(alerts)
            + f"\n\n🕐 {state['last_check']}"
        )
        for chat_id in state["subscribers"]:
            try:
                await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
            except Exception as e:
                logger.error(f"Ошибка отправки: {e}")

# =============================================
# КОМАНДЫ БОТА
# =============================================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state["subscribers"].add(update.effective_chat.id)
    keyboard = [
        [InlineKeyboardButton("📦 Все товары",         callback_data="products_all")],
        [InlineKeyboardButton("✅ Активные товары",    callback_data="products_active")],
        [InlineKeyboardButton("📊 Аналитика",          callback_data="analytics")],
        [InlineKeyboardButton("🔔 Статус мониторинга", callback_data="status")],
    ]
    await update.message.reply_text(
        "👋 Добро пожаловать в <b>FullSell Bot</b>!\n\n"
        "Я слежу за вашими товарами на UZUM и уведомляю об изменениях.\n\n"
        "🏪 Магазин: <b>procosmetics.uz</b>\n"
        "🆔 Shop ID: <b>110091</b>\n\n"
        "Выберите действие:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )

async def cmd_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await _loading(update, "🔍 Загружаю товары...")
    products = get_products("ALL")

    if not products:
        await msg.edit_text("❌ Не удалось получить товары.")
        return

    active   = [p for p in products if p.get("status", {}).get("value") == "IN_STOCK"]
    archived = [p for p in products if p.get("status", {}).get("value") == "ARCHIVED"]

    lines = [f"📦 <b>Товары магазина procosmetics.uz</b>\n"]
    lines.append(f"Всего: {len(products)} | Активных: {len(active)} | Архив: {len(archived)}\n")

    for p in products[:15]:
        name    = p.get("title", "—")[:45]
        price   = p.get("price", 0)
        rating  = p.get("rating", "0")
        status  = p.get("status", {}).get("value", "—")
        viewers = p.get("viewers") or 0
        icon    = "✅" if status == "IN_STOCK" else "🗄️"
        lines.append(f"{icon} <b>{name}</b>\n   💰 {price:,} сум | ⭐ {rating} | 👁 {viewers}")

    await msg.edit_text("\n".join(lines), parse_mode="HTML")

async def cmd_active(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await _loading(update, "🔍 Загружаю активные товары...")
    products = get_products("ACTIVE")

    if not products:
        await msg.edit_text("❌ Активных товаров не найдено.")
        return

    lines = [f"✅ <b>Активные товары ({len(products)} шт.)</b>\n"]
    for i, p in enumerate(products, 1):
        name       = p.get("title", "—")[:40]
        price      = p.get("price", 0)
        rating     = p.get("rating", "0")
        viewers    = p.get("viewers") or 0
        conversion = p.get("conversion") or 0
        fbs        = p.get("quantityFbs", 0)
        rank       = p.get("rankInfo", {}).get("rank", "—")
        lines.append(
            f"{i}. <b>{name}</b>\n"
            f"   💰 {price:,} сум | ⭐ {rating} | 👁 {viewers} | 🔄 {conversion}% | 📦 {fbs} шт | 🏆 {rank}"
        )

    await msg.edit_text("\n".join(lines), parse_mode="HTML")

async def cmd_analytics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await _loading(update, "📊 Считаю аналитику...")
    products = get_products("ALL")

    if not products:
        await msg.edit_text("❌ Нет данных.")
        return

    active      = [p for p in products if p.get("status", {}).get("value") == "IN_STOCK"]
    total_fbs   = sum(p.get("quantityFbs", 0) for p in products)
    total_sold  = sum(p.get("quantitySold", 0) for p in products)
    total_views = sum(p.get("viewers") or 0 for p in products)
    avg_rating  = sum(float(p.get("rating", 0)) for p in products) / len(products)
    rank_a      = [p for p in products if p.get("rankInfo", {}).get("rank") == "A"]
    rank_d      = [p for p in products if p.get("rankInfo", {}).get("rank") == "D"]

    lines = [
        "📊 <b>Аналитика магазина procosmetics.uz</b>\n",
        f"📦 Всего товаров: <b>{len(products)}</b>",
        f"✅ Активных: <b>{len(active)}</b>",
        f"📦 Остаток FBS: <b>{total_fbs} шт.</b>",
        f"💸 Продано: <b>{total_sold} шт.</b>",
        f"👁 Просмотров: <b>{total_views}</b>",
        f"⭐ Средний рейтинг: <b>{avg_rating:.1f}</b>",
        f"\n🏆 Ранг A (лучшие): <b>{len(rank_a)} товаров</b>",
        f"📉 Ранг D (нет данных): <b>{len(rank_d)} товаров</b>",
        f"\n🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}",
    ]

    await msg.edit_text("\n".join(lines), parse_mode="HTML")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    last  = state["last_check"] or "ещё не запускался"
    count = len(state["positions"])
    subs  = len(state["subscribers"])
    await _msg(update).reply_text(
        f"🔔 <b>Статус мониторинга FullSell</b>\n\n"
        f"✅ Бот активен\n"
        f"🏪 Магазин: procosmetics.uz\n"
        f"📦 Отслеживается: {count} товаров\n"
        f"👥 Подписчиков: {subs}\n"
        f"🕐 Последняя проверка: {last}\n"
        f"⏱️ Интервал: каждый час",
        parse_mode="HTML"
    )

# =============================================
# ОБРАБОТЧИК КНОПОК
# =============================================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "products_all":
        await cmd_products(update, context)
    elif query.data == "products_active":
        await cmd_active(update, context)
    elif query.data == "analytics":
        await cmd_analytics(update, context)
    elif query.data == "status":
        await cmd_status(update, context)

# =============================================
# ЗАПУСК
# =============================================

def main():
    if not TELEGRAM_TOKEN:
        print("TELEGRAM_TOKEN не найден!")
        return
    if not UZUM_API_KEY:
        print("UZUM_API_KEY не найден!")
        return

    print("FullSell Bot запускается...")
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("products",  cmd_products))
    app.add_handler(CommandHandler("active",    cmd_active))
    app.add_handler(CommandHandler("analytics", cmd_analytics))
    app.add_handler(CommandHandler("status",    cmd_status))
    app.add_handler(CallbackQueryHandler(button_handler))

    app.job_queue.run_repeating(check_positions, interval=CHECK_INTERVAL, first=60)

    print("Бот запущен! Ctrl+C для остановки.")
    app.run_polling()

if __name__ == "__main__":
    main()
