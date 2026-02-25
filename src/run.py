import os
import json
from pathlib import Path
from datetime import datetime, timezone

from collect import main as collect_one
from enrich_groq import enrich_with_groq
from tagger import flag, detect_sectors, detect_events, detect_country
from utils import extract_og_image
from telegram import (
    download_image,
    generate_fallback_image,
    build_caption_html,
    send_telegram_post
)

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "data" / "state.json"

def load_state():
    if not STATE_PATH.exists():
        return {"sent_ids": {}, "seen_ids": {}, "updated_at": None}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))

def save_state(st):
    STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")

def main():
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    groq_key = os.environ["GROQ_API_KEY"]

    item = collect_one()
    if not item:
        print("No item to post.")
        return

    # Groq enrich
    item = enrich_with_groq(item, groq_key)

    # country flag
    c = item.get("country", "LATAM")
    cflag = flag(c if len(c) == 2 else "")

    # tags backstop
    blob = f"{item.get('title','')} {item.get('summary','')}"
    if not item.get("industry_tags"):
        item["industry_tags"] = detect_sectors(blob)
    if not item.get("event_tags"):
        item["event_tags"] = detect_events(blob)
    if not item.get("country"):
        item["country"] = detect_country(blob, hint=item.get("country_hint","LATAM"))

    # image
    og = extract_og_image(item["url"])
    img_bytes = download_image(og) if og else None
    if not img_bytes:
        img_bytes = generate_fallback_image(cflag, item.get("title",""), item["industry_tags"] + item["event_tags"])

    caption = build_caption_html(
        country_flag=cflag,
        ru_summary=item.get("ru_summary") or item.get("title",""),
        ru_insight=item.get("ru_insight") or "Краткое пояснение: влияние на рынок/конкуренцию и региональную динамику.",
        url=item["url"],
        industry_tags=item.get("industry_tags", []),
        event_tags=item.get("event_tags", [])
    )

    send_telegram_post(token, chat_id, img_bytes, caption)

    # mark as sent (extra safety)
    st = load_state()
    sent = st.get("sent_ids", {}) or {}
    sent[item["id"]] = datetime.now(timezone.utc).isoformat()
    st["sent_ids"] = sent
    st["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_state(st)

    print("Posted OK.")

if __name__ == "__main__":
    main()
