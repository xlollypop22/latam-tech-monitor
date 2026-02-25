import json
import requests
from typing import Dict, Any

from tagger import detect_country, detect_events, detect_sectors

SYSTEM = (
    "Ты — аналитик венчурного рынка и бизнес-редактор. "
    "Сделай короткий канальный текст на русском: суть + 1-2 предложения аналитики. "
    "Без воды. Без заглушек."
)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# Пробуем модели по очереди (самая совместимая — 8b instant)
MODEL_CANDIDATES = [
    "llama-3.1-8b-instant",
    "llama-3.1-70b-versatile",
    "llama3-8b-8192",
    "llama3-70b-8192",
]

def _groq_chat(api_key: str, user_prompt: str) -> str:
    api_key = (api_key or "").strip()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is empty")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    last_err = None

    for model in MODEL_CANDIDATES:
        payload = {
            "model": model,
            "temperature": 0.2,
            "max_tokens": 650,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
        }

        try:
            r = requests.post(GROQ_URL, headers=headers, json=payload, timeout=60)

            # Если ошибка — покажем тело, но попробуем следующую модель
            if r.status_code != 200:
                last_err = f"[Groq {r.status_code}] model={model} body={r.text[:1200]}"
                continue

            data = r.json()
            return (data["choices"][0]["message"]["content"] or "").strip()

        except Exception as e:
            last_err = f"[Groq EXC] model={model} err={repr(e)}"
            continue

    raise RuntimeError(f"Groq request failed. {last_err}")


def enrich_with_groq(item: Dict[str, Any], groq_api_key: str) -> Dict[str, Any]:
    title = item.get("title", "")
    summary = item.get("summary", "")
    url = item.get("url", "")
    source = item.get("source", "")
    hint = item.get("country_hint", "LATAM")

    text_blob = f"{title}\n\n{summary}\n\nИсточник: {source}\nURL: {url}"

    prompt = f"""
Новость:
{text_blob}

Верни СТРОГО JSON такого вида:
{{
  "ru_summary": "1-2 предложения: что произошло",
  "ru_insight": "1-2 предложения: почему это важно / к чему приведет",
  "industry_tags": ["FinTech","AI"],
  "event_tags": ["Funding","MarketEntry"],
  "country": "ISO2 или LATAM"
}}

Правила:
- industry_tags: 1-3 отрасли из списка:
  FinTech, MedTech, EdTech, AI, SaaS, HRTech, Climate, Energy, AgriTech, Mobility,
  E-commerce, InsurTech, PropTech, Cybersecurity, Manufacturing, GovTech, RetailTech, LegalTech
- event_tags: 1-2 из:
  Funding, M&A, MarketEntry, NewPlant, Partnership, Regulation, ProductLaunch, News
- country: ISO2 если явная страна, иначе LATAM.
"""

    blob = f"{title} {summary}"

    try:
        content = _groq_chat(groq_api_key, prompt)
        try:
            data = json.loads(content)
        except Exception:
            # иногда модель добавляет текст вокруг JSON — попробуем вытащить JSON блок
            start = content.find("{")
            end = content.rfind("}")
            if start != -1 and end != -1 and end > start:
                data = json.loads(content[start:end+1])
            else:
                raise

        item["ru_summary"] = (data.get("ru_summary") or title).strip()
        item["ru_insight"] = (data.get("ru_insight") or "").strip()
        item["industry_tags"] = (data.get("industry_tags") or [])[:3]
        item["event_tags"] = (data.get("event_tags") or [])[:2]
        item["country"] = (data.get("country") or "").upper()

    except Exception as e:
        # 🔥 ВАЖНО: НЕ ВАЛИМ WORKFLOW.
        # Просто делаем fallback без Groq.
        print(f"[WARN] Groq disabled for this run: {e}")

        item["ru_summary"] = title.strip() if title else "Новость из LATAM"
        item["ru_insight"] = "Коротко: событие может повлиять на конкуренцию, инвестиции и скорость масштабирования в регионе."
        item["industry_tags"] = detect_sectors(blob)
        item["event_tags"] = detect_events(blob)
        item["country"] = detect_country(blob, hint=hint)

    # backstops
    if not item.get("industry_tags"):
        item["industry_tags"] = detect_sectors(blob)
    if not item.get("event_tags"):
        item["event_tags"] = detect_events(blob)
    if not item.get("country"):
        item["country"] = detect_country(blob, hint=hint)

    item["country"] = (item.get("country") or "LATAM").upper()
    item["ru_summary"] = (item.get("ru_summary") or title).strip()
    item["ru_insight"] = (item.get("ru_insight") or "").strip()

    return item
