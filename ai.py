import os
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
