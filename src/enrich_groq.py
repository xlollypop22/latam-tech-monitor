import json
import requests
from typing import Dict, Any

from tagger import detect_country, detect_events, detect_sectors

SYSTEM = (
    "Ты — аналитик венчурного рынка и бизнес-редактор. "
    "Сделай короткий канальный текст на русском: суть + 1-2 предложения аналитики. "
    "Без воды. Без заглушек."
)

def _groq_chat(api_key: str, user_prompt: str, model: str = "llama-3.1-70b-versatile") -> str:
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "temperature": 0.2,
        "max_tokens": 600,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user_prompt},
        ],
    }
    r = requests.post(url, headers=headers, json=payload, timeout=60)
    r.raise_for_status()
    data = r.json()
    return (data["choices"][0]["message"]["content"] or "").strip()

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

    content = _groq_chat(groq_api_key, prompt)

    # Парсим JSON; если модель вернула мусор — fallback на эвристики
    try:
        data = json.loads(content)
    except Exception:
        blob = f"{title} {summary}"
        data = {
            "ru_summary": title.strip(),
            "ru_insight": "Это может повлиять на конкуренцию, инвестиционную активность и темпы роста рынка в регионе.",
            "industry_tags": detect_sectors(blob),
            "event_tags": detect_events(blob),
            "country": detect_country(blob, hint=hint),
        }

    blob = f"{title} {summary}"
    item["ru_summary"] = (data.get("ru_summary") or title).strip()
    item["ru_insight"] = (data.get("ru_insight") or "").strip() or "Контекст: возможное влияние на рынок и масштабирование в регионе."
    item["industry_tags"] = (data.get("industry_tags") or detect_sectors(blob))[:3]
    item["event_tags"] = (data.get("event_tags") or detect_events(blob))[:2]
    item["country"] = (data.get("country") or detect_country(blob, hint=hint)).upper()

    return item
