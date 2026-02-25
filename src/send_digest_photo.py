import json
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

# Optional offline translation (Argos)
ARGOS_READY = False
try:
    from argostranslate import package, translate
    ARGOS_READY = True
except Exception:
    ARGOS_READY = False

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "latam_digest.json"
SENT_STATE = ROOT / "data" / "sent_state.json"
BANNER_PATH = ROOT / "assets" / "digest_banner.jpg"

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# 4 поста/день => окно ~6 часов
WINDOW_HOURS = 6

# Чтобы caption не превращался в простыню (лимит Telegram у caption ~1024)
TOP_FUNDING = 3
TOP_STARTUPS = 3
MAX_CAPTION_CHARS = 980

# --- Sector classifier (simple + robust) ---
SECTOR_RULES = [
    ("edtech",    r"\b(education|learning|lms|course|school|university|edtech|обучен|школ|вуз|курс|учеб)\b"),
    ("medtech",   r"\b(health|medical|clinic|hospital|patient|medtech|biotech|pharma|diagnos|мед|клиник|пациент|диагност|фарма)\b"),
    ("fintech",   r"\b(fintech|bank|payment|payments|card|lending|loan|credit|wallet|crypto|insur|bnpl|банк|платеж|кредит)\b"),
    ("hrtech",    r"\b(hrtech|recruit|talent|hiring|payroll|benefit|workforce|кадр|найм|рекрут)\b"),
    ("ai",        r"\b(ai|artificial intelligence|machine learning|llm|genai|нейросет|ии|машинн)\b"),
    ("cyber",     r"\b(cyber|security|infosec|fraud|risk|threat|безопасн|фрод)\b"),
    ("retail",    r"\b(ecommerce|marketplace|retail|shop|commerce|d2c|e-commerce|маркетплейс|ритейл)\b"),
    ("logistics", r"\b(logistics|delivery|shipping|freight|warehouse|supply chain|логист|доставк|склад)\b"),
    ("proptech",  r"\b(proptech|real estate|mortgage|rental|construction|недвижим|ипотек|строй)\b"),
    ("agritech",  r"\b(agritech|farm|farming|crop|agro|агро|ферм|урож)\b"),
    ("climate",   r"\b(climate|energy|solar|carbon|sustain|green|климат|энерг|солнеч|углерод)\b"),
    ("mobility",  r"\b(mobility|ride|fleet|transport|ev|vehicle|такси|флот|транспорт)\b"),
]
SECTOR_RE = [(name, re.compile(rx, re.IGNORECASE)) for name, rx in SECTOR_RULES]

SECTOR_LABEL = {
    "edtech": "EdTech",
    "medtech": "MedTech",
    "fintech": "FinTech",
    "hrtech": "HRTech",
    "ai": "AI",
    "cyber": "Cyber",
    "retail": "Retail/eCom",
    "logistics": "Logistics",
    "proptech": "PropTech",
    "agritech": "AgriTech",
    "climate": "Climate/Energy",
    "mobility": "Mobility",
    "other": "Other",
}

FLAG = {
    "AR": "🇦🇷", "BR": "🇧🇷", "MX": "🇲🇽", "CO": "🇨🇴", "CL": "🇨🇱", "PE": "🇵🇪",
    "UY": "🇺🇾", "PY": "🇵🇾", "EC": "🇪🇨", "BO": "🇧🇴",
    "LATAM": "🌎",
}

def flag(country: str) -> str:
    return FLAG.get((country or "").upper(), "🌎")

def icon_link(url: str) -> str:
    return f'<a href="{url}">🔗</a>' if url else "🔗"

def sector_of(it) -> str:
    text = " ".join([
        it.get("title") or "",
        it.get("summary") or "",
        " ".join(it.get("categories") or [])
    ])
    for name, rx in SECTOR_RE:
        if rx.search(text):
            return name
    return "other"

def guess_lang(it) -> str:
    # минимальная эвристика: большинство LATAM-источников испанские/порт/… но у нас модели EN и ES
    src = (it.get("source") or "").lower()
    if "mexico news daily" in src:
        return "en"
    if "wired" in src and "espa" not in src:
        return "en"
    # дефолт — испанский (для португальского будет хуже, но лучше чем ничего)
    return "es"

def translate_ru(text: str, src_lang: str) -> str:
    """
    Off-line translation via Argos.
    If Argos isn't available (models not installed), returns "".
    """
    if not ARGOS_READY or not text:
        return ""
    try:
        # Argos sometimes handles pivoting via intermediate language if needed
        return translate.translate(text[:280], src_lang, "ru").strip()
    except Exception:
        return ""

def load_items():
    items = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=WINDOW_HOURS)

    out = []
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

    # newest first (best effort)
    out.sort(key=lambda x: x.get("published_at") or "", reverse=True)
    return out

def load_sent() -> set:
    if not SENT_STATE.exists():
        return set()
    try:
        obj = json.loads(SENT_STATE.read_text(encoding="utf-8"))
        return set(obj.get("sent_ids", []))
    except Exception:
        return set()

def save_sent(sent_ids: set):
    SENT_STATE.parent.mkdir(parents=True, exist_ok=True)
    obj = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "sent_ids": list(sent_ids)[-50000:]
    }
    SENT_STATE.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

def pick_items(items, sent):
    fresh = [it for it in items if it.get("id") and it["id"] not in sent]
    if not fresh:
        return [], [], sent

    # enrich
    for it in fresh:
        it["_sector"] = sector_of(it)

    funding_all = [it for it in fresh if "funding" in (it.get("detected") or [])]
    startups_all = [it for it in fresh if "startup_news" in (it.get("detected") or [])]

    funding_top = funding_all[:TOP_FUNDING]
    startups_top = startups_all[:TOP_STARTUPS]

    # mark as sent
    for it in funding_top + startups_top:
        if it.get("id"):
            sent.add(it["id"])

    return funding_top, startups_top, sent

def build_caption(funding_top, startups_top, all_items_window):
    # BA time for header
    now_ba = datetime.now(timezone.utc) - timedelta(hours=3)
    stamp = now_ba.strftime("%d %b · %H:%M BA")

    # stats for header
    funding_cnt = sum(1 for it in all_items_window if "funding" in (it.get("detected") or []))
    startup_cnt = sum(1 for it in all_items_window if "startup_news" in (it.get("detected") or []))

    lines = []
    lines.append(f"🧭 <b>LATAM Tech Digest</b> · {stamp}")
    lines.append(f"💰 {funding_cnt} funding · 🚀 {startup_cnt} startup news")
    lines.append("")

    if funding_top:
        lines.append("<b>💰 Funding</b>")
        for it in funding_top:
            sec = SECTOR_LABEL.get(it.get("_sector","other"), "Other")
            ru = translate_ru(it.get("title",""), guess_lang(it))
            ru_line = f"\n<i>— {ru}</i>" if ru else ""
            lines.append(f"{flag(it.get('country'))} {it.get('title','')} ({sec}) {icon_link(it.get('url',''))}{ru_line}")
        lines.append("")

    if startups_top:
        lines.append("<b>🚀 Startup news</b>")
        for it in startups_top:
            sec = SECTOR_LABEL.get(it.get("_sector","other"), "Other")
            ru = translate_ru(it.get("title",""), guess_lang(it))
            ru_line = f"\n<i>— {ru}</i>" if ru else ""
            lines.append(f"{flag(it.get('country'))} {it.get('title','')} ({sec}) {icon_link(it.get('url',''))}{ru_line}")
        lines.append("")

    caption = "\n".join(lines).strip()

    # Trim to fit caption limit safely
    if len(caption) > MAX_CAPTION_CHARS:
        caption = caption[:MAX_CAPTION_CHARS] + "\n…"
    return caption

def send_photo(caption: str):
    url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
    with open(BANNER_PATH, "rb") as f:
        files = {"photo": f}
        data = {
            "chat_id": CHAT_ID,
            "caption": caption,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        r = requests.post(url, data=data, files=files, timeout=60)
        r.raise_for_status()

def main():
    if not BANNER_PATH.exists():
        raise FileNotFoundError("Banner image not found: assets/digest_banner.jpg")

    if not DATA_PATH.exists():
        raise FileNotFoundError("Dataset not found: data/latam_digest.json")

    items_window = load_items()
    sent = load_sent()

    funding_top, startups_top, sent = pick_items(items_window, sent)
    if not funding_top and not startups_top:
        print("No new relevant items in this window (or already sent).")
        return

    caption = build_caption(funding_top, startups_top, items_window)
    send_photo(caption)
    save_sent(sent)

    print("Sent digest photo + caption.")

if __name__ == "__main__":
    main()
