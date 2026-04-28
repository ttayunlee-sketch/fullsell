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
