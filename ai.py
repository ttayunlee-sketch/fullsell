import os
import json as _json
import anthropic

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")


def _build_context(client: dict, products: list) -> str:
    active = [p for p in products if p.get("status", {}).get("value") == "IN_STOCK"]
    low_fbs = [p for p in products if 0 < (p.get("quantityFbs") or 0) <= 10]
    total_views = sum(p.get("viewers") or 0 for p in products)
    avg_rating = round(
        sum(float(p.get("rating") or 0) for p in products) / len(products), 1
    ) if products else 0

    lines = [
        f"Магазин: {client['name']} (Shop ID: {client['shop_id']})",
        f"Всего товаров: {len(products)}, активных: {len(active)}",
        f"Суммарные просмотры: {total_views:,}, средний рейтинг: {avg_rating}",
        f"Товаров с критически низким FBS (≤10 шт): {len(low_fbs)}",
        "",
        "Список товаров:",
    ]
    for p in products[:30]:
        title   = (p.get("title") or "—")[:45]
        rating  = p.get("rating") or 0
        viewers = p.get("viewers") or 0
        fbs     = p.get("quantityFbs") or 0
        price   = p.get("price") or 0
        status  = p.get("status", {}).get("value", "—")
        rank    = p.get("rankInfo", {}).get("rank", "—")
        lines.append(
            f"  • {title} | цена {price:,} сум | рейтинг {rating} | "
            f"просмотры {viewers:,} | FBS {fbs} шт | ранг {rank} | статус {status}"
        )
    return "\n".join(lines)


_SYSTEM = (
    "Ты — эксперт по маркетплейсу UZUM (Узбекистан). "
    "Анализируй данные магазина и давай конкретные, практичные рекомендации. "
    "Всегда отвечай на русском языке. "
    "Называй конкретные товары и цифры. "
    "Не используй markdown-символы (* # ** и т.д.), пиши обычным текстом. "
    "Будь кратким и по делу."
)


def ask(client: dict, products: list, user_message: str) -> str:
    if not ANTHROPIC_API_KEY:
        return "Ошибка: ANTHROPIC_API_KEY не задан. Добавь его в переменные окружения."
    try:
        ai = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        context = _build_context(client, products)
        prompt = f"Данные магазина:\n{context}\n\nВопрос: {user_message}"
        message = ai.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text
    except Exception as e:
        return f"Ошибка AI: {e}"


_AUDIT_SYSTEM = (
    "Ты — эксперт по продажам на маркетплейсе UZUM (Узбекистан). "
    "Анализируй карточку товара и давай конкретный список проблем и задач. "
    "Всегда отвечай на русском языке, без markdown-символов (* # ** > и т.д.), пиши обычным текстом. "
    "Структура ответа строго такая:\n\n"
    "ПРОБЛЕМЫ:\n"
    "1. [конкретная проблема]\n"
    "2. [конкретная проблема]\n"
    "...\n\n"
    "ЧТО ПОЧИНИТЬ:\n"
    "1. [конкретное действие, что переписать/изменить/добавить]\n"
    "2. [конкретное действие]\n"
    "...\n\n"
    "ОЦЕНКА КАРТОЧКИ: N/10 — короткое резюме одной строкой.\n\n"
    "Будь конкретным: называй цифры, цитаты из названия, ссылайся на фото. "
    "Не пиши общих фраз вроде 'улучшите название' — пиши КАКИМ должно быть название."
)


_PROMO_SYSTEM = (
    "Ты — стратег продвижения на маркетплейсе UZUM (Узбекистан). "
    "Тебе дают: реальные продажи, конверсию, сегменты товаров. "
    "Ты пишешь конкретный план продвижения. На русском, без markdown (* # ** > и т.д.). "
    "Структура ответа строго такая:\n\n"
    "ПРОДВИГАТЬ РЕКЛАМОЙ (вкладывать бюджет):\n"
    "1. [Название товара] — почему: [конверсия N%, мало показов, есть остаток]. Бюджет: ~[сумма] на 7 дней. Эффект: ожидаем +N продаж.\n"
    "2. ...\n\n"
    "ИСПРАВИТЬ КАРТОЧКУ (низкая конверсия):\n"
    "1. [Название товара] — проблема: [конверсия 0.2%, 1500 просмотров, 0 продаж]. Что сделать: [конкретные шаги — название, фото, описание, цена].\n"
    "2. ...\n\n"
    "СНИЗИТЬ ЦЕНУ ИЛИ СНЯТЬ:\n"
    "1. [Название товара] — почему: [нет продаж 30+ дней, низкий рейтинг]. Действие: снизить на N% или архивировать.\n"
    "2. ...\n\n"
    "ОБЩАЯ ОЦЕНКА МАГАЗИНА: N/10 — одной строкой что главное.\n\n"
    "Будь конкретен: цифры, названия товаров, проценты. Не общие фразы."
)


def promotion_strategy(client: dict, products: list, finance: dict, segments: dict) -> str:
    """Генерирует план продвижения на основе реальных данных продаж и сегментации."""
    if not ANTHROPIC_API_KEY:
        return "Ошибка: ANTHROPIC_API_KEY не задан."

    def fmt_seg(name: str, items: list) -> str:
        if not items:
            return f"{name}: (пусто)"
        lines = [f"{name}:"]
        for r in items[:6]:
            lines.append(
                f"  • {r['title'][:60]} | просмотры {r['views']:,} | продано {r['qty']} шт | "
                f"выручка {int(r['revenue']):,} сум | конверсия {r['conv']}% | "
                f"рейтинг {r['rating']} | остаток {r['fbs']}"
            )
        return "\n".join(lines)

    parts = [
        f"Магазин: {client.get('name','—')} (Shop ID: {client.get('shop_id','—')})",
        f"Период: 30 дней",
        f"Выручка: {finance.get('total_revenue', 0):,} сум",
        f"Прибыль: {finance.get('total_profit', 0):,} сум",
        f"Заказов: {finance.get('orders_count', 0)} (отменено {finance.get('cancelled_count', 0)})",
        f"Средний чек: {finance.get('avg_check', 0):,} сум",
        f"Общая конверсия: {finance.get('conversion', 0)}%",
        "",
        fmt_seg("⭐ Звёзды (продажи + хорошая конверсия)", segments.get("stars") or []),
        "",
        fmt_seg("💎 Жемчужины (высокая конверсия, мало показов — кандидаты на продвижение)", segments.get("pearls") or []),
        "",
        fmt_seg("😴 Стагнация (много просмотров, нет/мало продаж — проблема в карточке)", segments.get("stagnant") or []),
        "",
        fmt_seg("💰 Дойные коровы (стабильные продажи)", segments.get("cows") or []),
        "",
        fmt_seg("💀 Балласт (низкие показы и продажи)", segments.get("ballast") or []),
        "",
        "На основе этих данных составь конкретный план продвижения по структуре, указанной в системном промпте."
    ]
    prompt = "\n".join(parts)

    try:
        ai = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = ai.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            system=_PROMO_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text
    except Exception as e:
        return f"Ошибка AI: {e}"


_KEYWORDS_SYSTEM = (
    "Ты — эксперт по рекламе на UZUM Market (Узбекистан). "
    "Твоя задача — собрать рекомендации по ключевым словам для рекламной кампании магазина. "
    "На основе ассортимента магазина и активных РК ты должен сформировать ДВА списка:\n"
    "1) Целевые ключевые запросы для запуска РК (конкретные товары, бренды, синонимы, нишевые запросы).\n"
    "2) Минус-слова (запросы, которые НЕ подходят, чтобы исключить их из РК).\n\n"
    "Учитывай реалии Узбекистана и UZUM:\n"
    "- Покупатели ищут на русском языке преимущественно (но и на узбекском бывает)\n"
    "- В нишах часто пересекаются смежные товары — их нужно отсеять\n"
    "- Бренды-конкуренты, нерелевантные характеристики, размеры/цвета, которых нет в наличии — это минус-слова\n\n"
    "Формат ответа — СТРОГО JSON, никаких markdown-блоков, никакого текста вокруг.\n"
    "Не добавляй комментарии, не оборачивай в ```json. Только чистый JSON-объект:\n"
    "{\n"
    "  \"target_keywords\": [\n"
    "    {\"query\": \"clio kill cover\", \"priority\": \"1\", \"reason\": \"точное название бренда+товара\"},\n"
    "    {\"query\": \"консилер для лица\", \"priority\": \"2\", \"reason\": \"общая категория, широкий охват\"}\n"
    "  ],\n"
    "  \"minus_words\": [\n"
    "    {\"query\": \"la roche posay\", \"rationale_ru\": \"Нецелевой бренд\", \"rationale_uz\": \"Maqsadli boʻlmagan brend\"},\n"
    "    {\"query\": \"контуринг\", \"rationale_ru\": \"⚠️ Требует проверки (Смежный товар)\", \"rationale_uz\": \"⚠️ Tekshirishni talab qiladi\"}\n"
    "  ]\n"
    "}\n\n"
    "Приоритеты целевых ключей:\n"
    "  \"1\" = Целевые (Dolzarb) — точное соответствие товару, бренду, модели\n"
    "  \"2\" = Широкие (Keng) — общие категории, широкие синонимы\n\n"
    "Дай 25-40 целевых ключей и 60-150 минус-слов. Будь конкретен."
)


def promo_keywords_recommendations(client: dict, products: list, ad_campaigns: list = None) -> dict:
    """Возвращает структурированный JSON с рекомендациями ключей и минус-слов в стиле ZoomSelling-AI."""
    if not ANTHROPIC_API_KEY:
        return {"error": "ANTHROPIC_API_KEY не задан"}

    ad_campaigns = ad_campaigns or []

    # Собираем данные о товарах — что продаётся в магазине
    product_lines = []
    for p in products[:60]:
        title  = (p.get("title") or "—")[:80]
        price  = p.get("price") or 0
        rating = p.get("rating") or 0
        views  = p.get("viewers") or 0
        cat    = ""
        try:
            cat = (p.get("category") or {}).get("title", {}) or {}
            cat = cat.get("ru", "") if isinstance(cat, dict) else str(cat or "")
        except Exception:
            cat = ""
        product_lines.append(
            f"  • {title} | категория: {cat[:40]} | {price:,} сум | рейтинг {rating} | просмотры {views:,}"
        )

    # Активные РК — какие ключи уже идут
    campaigns_lines = []
    if ad_campaigns:
        for c in ad_campaigns[:25]:
            cname  = (c.get("name") or c.get("title") or "—")[:60]
            status = c.get("status") or "—"
            stats  = c.get("stats") or {}
            impressions = stats.get("impressions") or 0
            clicks      = stats.get("clicks") or 0
            crr         = stats.get("crr") or 0
            campaigns_lines.append(
                f"  • {cname} | {status} | показы {impressions:,} | клики {clicks:,} | CRR {crr}%"
            )

    parts = [
        f"Магазин: {client.get('name','—')} (Shop ID: {client.get('shop_id','—')})",
        f"Всего товаров: {len(products)}",
        "",
        "АССОРТИМЕНТ МАГАЗИНА (выборка):",
        *product_lines,
    ]
    if campaigns_lines:
        parts += [
            "",
            "АКТИВНЫЕ РЕКЛАМНЫЕ КАМПАНИИ:",
            *campaigns_lines,
        ]
    parts += [
        "",
        "На основе ассортимента и активных РК сформируй target_keywords и minus_words как описано в системном промпте. Только JSON.",
    ]
    prompt = "\n".join(parts)

    try:
        ai = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = ai.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=4096,
            system=_KEYWORDS_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = message.content[0].text.strip()
        # На всякий случай чистим markdown-обёртку, если AI всё-таки её добавил
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.lower().startswith("json"):
                text = text[4:].lstrip()
        text = text.strip().rstrip("`").strip()
        try:
            data = _json.loads(text)
        except _json.JSONDecodeError:
            # Иногда модель возвращает несколько JSON-кусков — берём первый блок
            start = text.find("{")
            end   = text.rfind("}")
            if start >= 0 and end > start:
                data = _json.loads(text[start:end + 1])
            else:
                return {"error": "AI вернул не-JSON", "raw": text[:600]}
        targets = data.get("target_keywords") or []
        minus   = data.get("minus_words") or []
        # Нормализуем
        for t in targets:
            t["priority"] = str(t.get("priority", "")).strip() or "2"
        return {"target_keywords": targets, "minus_words": minus}
    except Exception as e:
        return {"error": f"Ошибка AI: {e}"}


def audit_product(product: dict, shop_name: str = "") -> str:
    if not ANTHROPIC_API_KEY:
        return "Ошибка: ANTHROPIC_API_KEY не задан."
    title  = product.get("title_norm") or product.get("title") or "—"
    price  = product.get("price_norm") or 0
    rating = product.get("rating_norm") or 0
    views  = product.get("views_norm") or 0
    fbs    = product.get("fbs_norm") or 0
    rank   = product.get("rank_norm") or "—"
    status = product.get("status_norm") or "—"
    image  = product.get("image_url") or ""
    desc   = product.get("description") or product.get("descriptionRu") or ""
    if isinstance(desc, dict):
        desc = desc.get("ru") or desc.get("value") or ""
    desc = (str(desc) or "").strip()[:800]

    text_block = (
        f"Магазин: {shop_name}\n"
        f"Название товара: {title}\n"
        f"Цена: {price:,} сум\n"
        f"Рейтинг: {rating} / 5\n"
        f"Просмотры: {views:,}\n"
        f"Остатки FBS: {fbs} шт\n"
        f"Ранг по площадке: {rank}\n"
        f"Статус: {status}\n"
        f"Описание (если есть): {desc or '— нет описания —'}\n\n"
        "Проведи аудит карточки товара по UZUM. "
        "Учти фото (если оно прикреплено): качество, фон, читаемость, привлекательность."
    )

    content = []
    if image and image.startswith("http"):
        content.append({
            "type": "image",
            "source": {"type": "url", "url": image},
        })
    content.append({"type": "text", "text": text_block})

    try:
        ai = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = ai.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            system=_AUDIT_SYSTEM,
            messages=[{"role": "user", "content": content}],
        )
        return message.content[0].text
    except Exception as e:
        if image:
            try:
                ai = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
                message = ai.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=1500,
                    system=_AUDIT_SYSTEM,
                    messages=[{"role": "user", "content": text_block}],
                )
                return message.content[0].text
            except Exception as e2:
                return f"Ошибка AI: {e2}"
        return f"Ошибка AI: {e}"
