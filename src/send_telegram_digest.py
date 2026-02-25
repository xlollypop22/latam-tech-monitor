import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "latam_digest.json"

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

MAX_AGE_HOURS = 24
TOP_FUNDING = 3
TOP_STARTUPS = 3


def load_items():
    items = json.loads(DATA.read_text(encoding="utf-8"))
    out = []
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=MAX_AGE_HOURS)
    for it in items:
        detected = it.get("detected") or []
        if not detected:
            continue
        dt = it.get("published_at")
        if dt:
            try:
                t = datetime.fromisoformat(dt.replace("Z", "+00:00"))
                if t < cutoff:
                    continue
            except Exception:
                pass
        out.append(it)
    return out


def build_message(items):
    funding = [it for it in items if "funding" in (it.get("detected") or [])][:TOP_FUNDING]
    startups = [it for it in items if "startup_news" in (it.get("detected") or [])][:TOP_STARTUPS]

    if not funding and not startups:
        return None

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = []
    lines.append(f"🧾 LATAM Tech Digest — {stamp}")
    lines.append(f"За 24ч: funding={len([i for i in items if 'funding' in (i.get('detected') or [])])}, "
                 f"startups={len([i for i in items if 'startup_news' in (i.get('detected') or [])])}")
    lines.append("")

    if funding:
        lines.append(f"💰 Funding (топ-{len(funding)}):")
        for it in funding:
            lines.append(f"• {it.get('title','')}")
            lines.append(it.get("url", ""))
            lines.append("")

    if startups:
        lines.append(f"🚀 Startup news (топ-{len(startups)}):")
        for it in startups:
            lines.append(f"• {it.get('title','')}")
            lines.append(it.get("url", ""))
            lines.append("")

    msg = "\n".join(lines).strip()
    return msg[:3800] + "\n…(truncated)" if len(msg) > 3800 else msg


def send(msg: str):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    r = requests.post(url, json={
        "chat_id": CHAT_ID,
        "text": msg,
        "disable_web_page_preview": True
    }, timeout=30)
    r.raise_for_status()


def main():
    items = load_items()
    msg = build_message(items)
    if not msg:
        print("No relevant items to send.")
        return
    send(msg)
    print("Sent digest.")


if __name__ == "__main__":
    main()
