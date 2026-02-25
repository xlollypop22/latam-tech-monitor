import base64
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

# 1x1 valid PNG (always accepted). Used as fallback if Telegram rejects your jpg.
FALLBACK_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8A"
    "AqMB9o0XqQAAAABJRU5ErkJggg=="
)


# ----------------- IO -----------------

def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


# ----------------- Helpers -----------------

def parse_dt(s: Optional[str]):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def compact_source(it: Dict):
    bucket = it.get("bucket") or it.get("country") or ""
    source = it.get("source") or ""
    return f"{bucket} · {source}".strip(" ·")


def is_latam_relevant(item: Dict) -> bool:
    # Simple heuristic: keep LATAM-ish content and filter out global unrelated items.
    text = (
        (item.get("title") or "") + " " +
        (item.get("summary") or "") + " " +
        " ".join(item.get("categories") or [])
    ).lower()

    latam_keywords = [
        "latam", "latin america",
        "argentina", "brazil", "brasil", "mexico", "colombia", "chile", "peru",
        "uruguay", "paraguay", "bolivia", "ecuador", "venezuela", "costa rica",
        "guatemala", "panama", "dominican", "salvador", "honduras", "nicaragua",
    ]
    return any(k in text for k in latam_keywords)


def pick(items: List[Dict], sent: Dict, limit=2) -> List[Dict]:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=48)

    filtered = []
    for it in items:
        it_id = it.get("id")
        if not it_id:
            continue
        if it_id in sent:
            continue

        # keep only recent
        dt = parse_dt(it.get("published_at"))
        if dt and dt < cutoff:
            continue

        # keep only LATAM-ish
        if not is_latam_relevant(it):
            continue

        filtered.append(it)

    filtered.sort(
        key=lambda x: parse_dt(x.get("published_at")) or datetime(1970, 1, 1, tzinfo=timezone.utc),
        reverse=True
    )
    return filtered[:limit]


def escape_md(s: str) -> str:
    # Telegram Markdown (legacy) is fragile. Escape key chars.
    # We use simple escaping to avoid breaking links/titles.
    if not s:
        return s
    for ch in ["_", "*", "[", "]", "(", ")", "~", "`", ">", "#", "+", "-", "=", "|", "{", "}", ".", "!"]:
        s = s.replace(ch, "\\" + ch)
    return s


# ----------------- Telegram -----------------

def tg_send_message(token: str, chat_id: str, text: str):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": True,
    }
    r = requests.post(url, json=payload, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"Telegram sendMessage error: {r.text}")


def _photo_bytes_primary_or_none() -> Optional[bytes]:
    if HEADER_IMAGE.exists():
        try:
            b = HEADER_IMAGE.read_bytes()
            # quick sanity: avoid sending tiny/broken files
            if len(b) > 2000:
                return b
        except Exception:
            return None
    return None


def _photo_bytes_fallback_png() -> bytes:
    return base64.b64decode(FALLBACK_PNG_B64)


def tg_send_photo_with_fallback(token: str, chat_id: str, caption: str):
    url = f"https://api.telegram.org/bot{token}/sendPhoto"

    # We use MarkdownV2 in caption (more stable if escaped).
    data = {
        "chat_id": chat_id,
        "caption": caption,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": True,
    }

    def post_photo(photo_bytes: bytes, filename: str):
        files = {"photo": (filename, photo_bytes)}
        return requests.post(url, data=data, files=files, timeout=60)

    primary = _photo_bytes_primary_or_none()
    if primary:
        r = post_photo(primary, "header.jpg")
        if r.status_code == 200:
            return
        # If Telegram can't process the image — retry with fallback PNG
        if "IMAGE_PROCESS_FAILED" in r.text or r.status_code == 400:
            fb = _photo_bytes_fallback_png()
            r2 = post_photo(fb, "fallback.png")
            if r2.status_code == 200:
                return
            # Last resort: message without photo
            tg_send_message(token, chat_id, caption)
            return
        # other errors: message without photo
        tg_send_message(token, chat_id, caption)
        return

    # No header.jpg → fallback PNG
    fb = _photo_bytes_fallback_png()
    r = post_photo(fb, "fallback.png")
    if r.status_code == 200:
        return

    # last resort
    tg_send_message(token, chat_id, caption)


# ----------------- Build digest -----------------

def build_caption(top_funding: List[Dict], top_startups: List[Dict]) -> str:
    now_ba = datetime.now(timezone.utc) - timedelta(hours=3)
    stamp = now_ba.strftime("%d %b · %H:%M BA")

    lines = []
    lines.append(f"*LATAM Tech Digest* \\- {escape_md(stamp)}")
    lines.append("")

    if top_funding:
        lines.append("💰 *Funding*")
        for it in top_funding:
            title = escape_md(it.get("title", ""))
            url = it.get("url", "").strip()
            meta = escape_md(compact_source(it))
            # MarkdownV2 link format: [text](url)
            lines.append(f"• [{title}]({url})")
            lines.append(f"  _{meta}_")
        lines.append("")

    if top_startups:
        lines.append("🚀 *Startup news*")
        for it in top_startups:
            title = escape_md(it.get("title", ""))
            url = it.get("url", "").strip()
            meta = escape_md(compact_source(it))
            lines.append(f"• [{title}]({url})")
            lines.append(f"  _{meta}_")
        lines.append("")

    # ultra-short “главное”
    if top_funding or top_startups:
        main_it = (top_funding + top_startups)[0]
        main_title = escape_md(main_it.get("title", ""))
        lines.insert(1, f"Главное: {main_title}")

    # Telegram caption limit ~1024 for sendPhoto sometimes strict; keep compact.
    caption = "\n".join(lines).strip()
    if len(caption) > 900:
        caption = caption[:900] + "…"
    return caption


# ----------------- Main -----------------

def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID secrets")

    funding = load_json(FUNDING_PATH, [])
    startups = load_json(STARTUPS_PATH, [])
    sent = load_json(SENT_STATE_PATH, {})

    top_funding = pick(funding, sent, 2)

    # чтобы не дублировать одну и ту же новость в обе секции
    used_ids = {it["id"] for it in top_funding}
    startups_no_dupes = [it for it in startups if it.get("id") not in used_ids]
    top_startups = pick(startups_no_dupes, sent, 2)

    if not top_funding and not top_startups:
        print("No new items.")
        return

    caption = build_caption(top_funding, top_startups)
    tg_send_photo_with_fallback(token, chat_id, caption)

    now_iso = datetime.now(timezone.utc).isoformat()
    for it in top_funding + top_startups:
        sent[it["id"]] = now_iso
    save_json(SENT_STATE_PATH, sent)

    print("Digest sent.")


if __name__ == "__main__":
    main()
