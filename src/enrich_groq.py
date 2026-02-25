import json
from typing import Dict, Any, List
from groq import Groq

from tagger import detect_country, detect_events, detect_sectors

SYSTEM = (
    "Ты — аналитик венчурного рынка и бизнес-редактор. "
    "Твоя задача: по новости сделать короткий канальный пост на русском: "
    "суть + 1-2 предложения аналитики (зачем это важно). "
    "Без воды. Без эмодзи в тексте (эмодзи добавит код)."
)

def enrich_with_groq(item: Dict[str, Any], groq_api_key: str, model: str = "llama-3.1-70b-versatile") -> Dict[str, Any]:
    client = Groq(api_key=groq_api_key)

    title = item.get("title", "")
    summary = item.get("summary", "")
    url = item.get("url", "")
    source = item.get("source", "")
    hint = item.get("country_hint", "LATAM")

    text_blob = f"{title}\n\n{summary}\n\nИсточник: {source}\nURL: {url}"

    prompt = f"""
Новость (может быть на испанском/португальском/английском):
{text_blob}

Сделай JSON СТРОГО такого вида:
{{
  "ru_summary": "1-2 предложения: что произошло",
  "ru_insight": "1-2 предложения: почему это важно / к чему приведет",
  "industry_tags": ["FinTech","AI"],
  "event_tags": ["Funding","MarketEntry"],
  "country": "ISO2 или LATAM"
}}

Правила:
- industry_tags: выбери 1-3 отрасли (FinTech, MedTech, EdTech, AI, SaaS, HRTech, Climate, Energy, AgriTech, Mobility, E-commerce, InsurTech, PropTech, Cybersecurity, Manufacturing).
- event_tags: 1-2 (Funding, M&A, MarketEntry, NewPlant, Partnership, News).
- country: ISO2 если явная страна, иначе LATAM.
"""

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=500,
    )

    content = resp.choices[0].message.content.strip()

    # robust parse: try to find JSON block
    try:
        data = json.loads(content)
    except Exception:
        # fallback: minimal tagging from heuristics
        blob = f"{title} {summary}"
        data = {
            "ru_summary": title,
            "ru_insight": "Новость может повлиять на рынок/конкуренцию в регионе.",
            "industry_tags": detect_sectors(blob),
            "event_tags": detect_events(blob),
            "country": detect_country(blob, hint=hint),
        }

    # finalize with heuristic backstops
    blob = f"{title} {summary}"
    if not data.get("industry_tags"):
        data["industry_tags"] = detect_sectors(blob)
    if not data.get("event_tags"):
        data["event_tags"] = detect_events(blob)
    if not data.get("country"):
        data["country"] = detect_country(blob, hint=hint)

    item["ru_summary"] = (data.get("ru_summary") or "").strip()
    item["ru_insight"] = (data.get("ru_insight") or "").strip()
    item["industry_tags"] = (data.get("industry_tags") or [])[:3]
    item["event_tags"] = (data.get("event_tags") or [])[:2]
    item["country"] = (data.get("country") or "LATAM").upper()

    return item
