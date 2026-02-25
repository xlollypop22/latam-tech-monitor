import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

# =========================
# Paths
# =========================
ROOT = Path(__file__).resolve().parents[1]

FUNDING_PATH = ROOT / "data" / "latam_funding.json"
STARTUPS_PATH = ROOT / "data" / "latam_startups.json"
STATE_PATH = ROOT / "data" / "sent_state.json"

BANNER_PATH = ROOT / "assets" / "digest_banner.jpg"

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

WINDOW_HOURS = 72
TOP_FUNDING = 2
TOP_STARTUPS = 2
MAX_CAPTION = 950


# =========================
# Utils
# =========================
def clean_html(text):
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&amp;", "&")
    return text.strip()


def parse_date(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except:
        return None


def load_json(path):
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_state():
    if not STATE_PATH.exists():
        return {"sent_ids": []}
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# =========================
# Sector detection
# =========================
def detect_sector(item):
    cats = " ".join(item.get("categories", [])).lower()
    title = item.get("title", "").lower()

    if "fintech" in cats or "payment" in title:
        return "Fintech"
    if "hr" in cats or "hrtech" in title:
        return "HRTech"
    if "ai" in title:
        return "AI"
    if "health" in cats:
        return "Health"
    return "Other"


# =========================
# Ultra short RU rewrite
# =========================
def to_ru_short(title):
    t = title.lower()

    if "raises" in t:
        return re.sub(r"raises", "привлёк", title, flags=re.IGNORECASE)
    if "acquires" in t:
        return re.sub(r"acquires", "поглотил", title, flags=re.IGNORECASE)
    if "series a" in t:
        return title.replace("Series A", "раунд A")
    if "series b" in t:
        return title.replace("Series B", "раунд B")

    return title


# =========================
# Select new items
# =========================
def filter_new(items, sent_ids):
    now = datetime.now(timezone.utc)
    window = timedelta(hours=WINDOW_HOURS)

    fresh = []
    for it in items:
        if it.get("id") in sent_ids:
            continue

        dt = parse_date(it.get("published_at", ""))
        if dt and now - dt > window:
            continue

        fresh.append(it)

    return fresh


# =========================
# Build ultra short caption
# =========================
def build_caption(funding, startups):
    stamp = datetime.now().strftime("%d %b · %H:%M")

    lines = []
    lines.append(f"🧭 LATAM Tech — {stamp}")
    lines.append("")

    # Главное
    main_line = None
    if funding:
        main_line = to_ru_short(clean_html(funding[0]["title"]))
    elif startups:
        main_line = to_ru_short(clean_html(startups[0]["title"]))

    if main_line:
        lines.append(f"🔥 Главное: {main_line}")
        lines.append("")

    # Funding
    if funding:
        lines.append("💰 Funding:")
        for it in funding[:TOP_FUNDING]:
            ru = to_ru_short(clean_html(it["title"]))
            sector = detect_sector(it)
            lines.append(f"• {ru} ({sector})")
        lines.append("")

    # Startup
    if startups:
        lines.append("🚀 Startup:")
        for it in startups[:TOP_STARTUPS]:
            ru = to_ru_short(clean_html(it["title"]))
            sector = detect_sector(it)
            lines.append(f"• {ru} ({sector})")

    caption = "\n".join(lines).strip()

    if len(caption) > MAX_CAPTION:
        caption = caption[:MAX_CAPTION - 3] + "..."

    return caption


# =========================
# Telegram send
# =========================
def send_photo(caption):
    if not TOKEN or not CHAT_ID:
        raise RuntimeError("Telegram token/chat_id missing")

    url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"

    with open(BANNER_PATH, "rb") as img:
        r = requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "caption": caption,
            },
            files={"photo": img},
        )

    if r.status_code != 200:
        raise RuntimeError(r.text)


# =========================
# Main
# =========================
def main():
    funding = load_json(FUNDING_PATH)
    startups = load_json(STARTUPS_PATH)
    state = load_state()

    sent_ids = set(state.get("sent_ids", []))

    new_funding = filter_new(funding, sent_ids)
    new_startups = filter_new(startups, sent_ids)

    if not new_funding and not new_startups:
        print("No new items.")
        return

    caption = build_caption(new_funding, new_startups)

    send_photo(caption)

    # save state
    for it in new_funding[:TOP_FUNDING]:
        sent_ids.add(it["id"])
    for it in new_startups[:TOP_STARTUPS]:
        sent_ids.add(it["id"])

    state["sent_ids"] = list(sent_ids)
    save_state(state)


if __name__ == "__main__":
    main()
