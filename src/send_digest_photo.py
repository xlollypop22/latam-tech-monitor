import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import requests


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
ASSETS_DIR = ROOT / "assets"

FUNDING_PATH = DATA_DIR / "latam_funding.json"
STARTUPS_PATH = DATA_DIR / "latam_startups.json"
SENT_STATE_PATH = DATA_DIR / "sent_state.json"

HEADER_IMAGE = ASSETS_DIR / "header.jpg"


# ---------- TELEGRAM ----------

def tg_send_photo(token: str, chat_id: str, caption: str):
    url = f"https://api.telegram.org/bot{token}/sendPhoto"

    with open(HEADER_IMAGE, "rb") as img:
        files = {"photo": img}
        data = {
            "chat_id": chat_id,
            "caption": caption,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        r = requests.post(url, data=data, files=files, timeout=60)

    if r.status_code != 200:
        raise RuntimeError(f"Telegram photo error: {r.text}")


# ---------- IO ----------

def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))

def save_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------- HELPERS ----------

def parse_dt(s: Optional[str]):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except:
        return None

def is_latam_relevant(item: Dict) -> bool:
    text = (
        (item.get("title") or "") + " " +
        (item.get("summary") or "") + " " +
        " ".join(item.get("categories") or [])
    ).lower()

    latam_keywords = [
        "latam", "latin america", "brazil", "mexico",
        "argentina", "colombia", "chile", "peru"
    ]

    return any(k in text for k in latam_keywords)

def compact_source(it: Dict):
    bucket = it.get("bucket") or it.get("country") or ""
    source = it.get("source") or ""
    return f"{bucket} · {source}".strip(" ·")

def pick(items: List[Dict], sent: Dict, limit=2):
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=48)

    filtered = []
    for it in items:
        if not it.get("id"):
            continue
        if it["id"] in sent:
            continue
        if not is_latam_relevant(it):
            continue

        dt = parse_dt(it.get("published_at"))
        if dt and dt < cutoff:
            continue

        filtered.append(it)

    filtered.sort(
        key=lambda x: parse_dt(x.get("published_at")) or datetime(1970,1,1,tzinfo=timezone.utc),
        reverse=True
    )

    return filtered[:limit]


# ---------- MAIN ----------

def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        raise RuntimeError("Missing TELEGRAM secrets")

    funding = load_json(FUNDING_PATH, [])
    startups = load_json(STARTUPS_PATH, [])
    sent = load_json(SENT_STATE_PATH, {})

    top_funding = pick(funding, sent, 2)
    top_startups = pick(startups, sent, 2)

    now_ba = datetime.now(timezone.utc) - timedelta(hours=3)
    stamp = now_ba.strftime("%d %b · %H:%M BA")

    lines = [f"*LATAM Tech Digest* · {stamp}"]

    if top_funding:
        lines.append("\n💰 *Funding*")
        for it in top_funding:
            lines.append(
                f"- [{it['title']}]({it['url']})\n  {compact_source(it)}"
            )

    if top_startups:
        lines.append("\n🚀 *Startup News*")
        for it in top_startups:
            lines.append(
                f"- [{it['title']}]({it['url']})\n  {compact_source(it)}"
            )

    caption = "\n".join(lines)

    tg_send_photo(token, chat_id, caption)

    # mark sent
    now_iso = datetime.now(timezone.utc).isoformat()
    for it in top_funding + top_startups:
        sent[it["id"]] = now_iso

    save_json(SENT_STATE_PATH, sent)

    print("Digest sent.")


if __name__ == "__main__":
    main()
