"""
Instagram Messaging API client.

Используется для отправки исходящих DM в ответ на webhook-события.
Документация: https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/messaging-api

Требуется:
- IG_ACCESS_TOKEN — Long-lived Instagram Access Token (получается через
  Instagram Business Login OAuth flow или через UI Use Case → Generate Access Tokens)
- IG_BUSINESS_ID  — Instagram Business Account ID (числовой), которому принадлежит токен
"""
import os
import json
import httpx

GRAPH_VERSION = "v25.0"
GRAPH_BASE    = f"https://graph.instagram.com/{GRAPH_VERSION}"

# Обратите внимание: для Instagram Login API endpoint = graph.instagram.com
# (для старого Instagram Graph API через Facebook Page = graph.facebook.com)


def send_message(recipient_id: str, text: str, access_token: str = None,
                 ig_business_id: str = None) -> dict:
    """Отправить текстовый DM пользователю.

    recipient_id — Instagram-Scoped User ID (IGSID) собеседника (берём из webhook event sender.id)
    text         — текст ответа (макс 1000 символов по политике Meta)
    access_token — Long-lived Instagram Access Token (если не задан, берётся из env)
    ig_business_id — наш Instagram Business Account ID (если не задан — из env)

    Возвращает: {"recipient_id": "...", "message_id": "..."} от Meta или {"error": "..."}
    """
    token = access_token or os.environ.get("IG_ACCESS_TOKEN", "").strip()
    biz   = ig_business_id or os.environ.get("IG_BUSINESS_ID", "").strip()
    if not token:
        return {"error": "IG_ACCESS_TOKEN не задан"}
    if not biz:
        return {"error": "IG_BUSINESS_ID не задан"}
    if not recipient_id:
        return {"error": "recipient_id пустой"}
    if not text or not text.strip():
        return {"error": "text пустой"}

    text = text.strip()[:990]  # Meta limit ~1000 chars

    url = f"{GRAPH_BASE}/{biz}/messages"
    payload = {
        "recipient": {"id": str(recipient_id)},
        "message":   {"text": text},
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    }

    try:
        with httpx.Client(timeout=20) as c:
            r = c.post(url, headers=headers, content=json.dumps(payload))
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}: {r.text[:400]}"}
        return r.json()
    except Exception as e:
        return {"error": f"send_message exception: {e}"}


def parse_event(data: dict) -> list:
    """Извлекает входящие сообщения из webhook-события Meta.

    Real-life формат (Instagram Login API, через graph.instagram.com):
    {
      "object": "instagram",
      "entry": [
        {
          "id": "<page_or_business_id>",
          "time": 1727723500,
          "messaging": [
            {
              "sender":    {"id": "<igsid>"},
              "recipient": {"id": "<our_business_id>"},
              "timestamp": 1727723500000,
              "message":   {"mid": "...", "text": "..."}
            }
          ]
        }
      ]
    }

    Test formatfrom Meta Console:
    {"sample": {"field": "messages", "value": {"sender": {...}, ...}}}

    Возвращает список dict-ов: [{"sender_id": "...", "text": "...", "mid": "...", "timestamp": ...}, ...]
    """
    out = []

    # Live формат
    if data.get("object") == "instagram" and isinstance(data.get("entry"), list):
        for entry in data["entry"]:
            for msg_event in (entry.get("messaging") or []):
                sender = (msg_event.get("sender") or {}).get("id")
                msg    = msg_event.get("message") or {}
                text   = msg.get("text") or ""
                # Пропускаем echo (наши же ответы) и read-events
                if msg_event.get("message", {}).get("is_echo"):
                    continue
                if not text:
                    continue
                out.append({
                    "sender_id": str(sender) if sender else "",
                    "text":      text,
                    "mid":       msg.get("mid", ""),
                    "timestamp": msg_event.get("timestamp"),
                })

    # Тестовый формат от консоли Meta
    sample = (data.get("sample") or {}).get("value") or {}
    if sample:
        sender = (sample.get("sender") or {}).get("id")
        msg    = sample.get("message") or {}
        text   = msg.get("text") or ""
        if sender and text:
            out.append({
                "sender_id": str(sender),
                "text":      text,
                "mid":       msg.get("mid", ""),
                "timestamp": sample.get("timestamp"),
                "is_test":   True,
            })

    return out
