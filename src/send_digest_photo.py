import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

# Optional offline translation (Argos)
ARGOS_READY = False
try:
    from argostranslate import translate as argos_translate
    ARGOS_READY = True
except Exception:
    ARGOS_READY = False

ROOT = Path(__file__).resolve().parents[1]

FUNDING_PATH = ROOT / "data" / "latam_funding.json"
STARTUPS_PATH = ROOT / "data" / "latam_startups.json"

SENT_STATE = ROOT / "data" / "sent_state.json"
BANNER_PATH = ROOT / "assets" / "digest_banner.jpg"

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# Для старта ставим 24ч (чтобы пост точно был). Потом можешь вернуть 6ч.
WINDOW_HOURS = 24

# Чтобы caption не был простынёй (лимит ~1024)
TOP_FUNDING = 3
TOP_STARTUPS = 3
MAX_CAPTION_CHARS = 980

# --- Sector classifier ---
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
    # У тебя есть EN и ES источники. Португальский будет как ES (не идеально, но ок).
    src = (it.get("source") or "").lower()
    if "contxto en" in src or "mexico news daily" in src:
        return "en"
    return "es"

def translate_ru(text: str, src_lang: str) -> str:
    if not ARGOS_READY or not text:
        return ""
    try:
        # Argos uses ISO codes like "en", "es", "ru"
        return argos_translate.translate(text[:280], src_lang, "ru").strip()
    except Exception:
        return ""

def load_json(path: Path):
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))

def in_window(it, cutoff: datetime) -> bool:
    dt = it.get("published_at")
    if not dt:
        return True
    try:
        t = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        return t >= cutoff
    except Exception:
        return True

def load_window_lists():
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=WINDOW_HOURS)

    funding = [it for it in load_json(FUNDING_PATH) if in_window(it, cutoff)]
    startups = [it for it in load_json(STARTUPS_PATH) if in_window(it, cutoff)]

    # newest first
    funding.sort(key=lambda x: x.get("published_at") or "", reverse=True)
    startups.sort(key=lambda x: x.get("published_at") or "", reverse=True)
    return funding, startups

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

def pick_items(funding_items, startups_items, sent):
    funding_fresh = [it for it in funding_items if it.get("id") and it["id"] not in sent]
    startups_fresh = [it for it in startups_items if it.get("id") and it["id"] not in sent]

    for it in funding_fresh + startups_fresh:
        it["_sector"] = sector_of(it)

    top_funding = funding_fresh[:TOP_FUNDING]
    top_startups = startups_fresh[:TOP_STARTUPS]

    for it in top_funding + top_startups:
        sent.add(it["id"])

    return top_funding, top_startups, sent

def build_caption(top_funding, top_startups, funding_window, startups_window):
    # Buenos Aires time (UTC-3)
    now_ba = datetime.now(timezone.utc) - timedelta(hours=3)
    stamp = now_ba.strftime("%d %b · %H:%M BA")

    funding_cnt = len(funding_window)
    startup_cnt = len(startups_window)

    lines = []
    lines.append(f"🧭 <b>LATAM Tech Digest</b> · {stamp}")
    lines.append(f"💰 {funding_cnt} funding · 🚀 {startup_cnt} startup news")
    lines.append("")

    if top_funding:
        lines.append("<b>💰 Funding</b>")
        for it in top_funding:
            sec = SECTOR_LABEL.get(it.get("_sector", "other"), "Other")
            ru = translate_ru(it.get("title", ""), guess_lang(it))
            ru_line = f"\n<i>— {ru}</i>" if ru else ""
            lines.append(f"{flag(it.get('country'))} {it.get('title','')} ({sec}) {icon_link(it.get('url',''))}{ru_line}")
        lines.append("")

    if top_startups:
        lines.append("<b>🚀 Startup news</b>")
        for it in top_startups:
            sec = SECTOR_LABEL.get(it.get("_sector", "other"), "Other")
            ru = translate_ru(it.get("title", ""), guess_lang(it))
            ru_line = f"\n<i>— {ru}</i>" if ru else ""
            lines.append(f"{flag(it.get('country'))} {it.get('title','')} ({sec}) {icon_link(it.get('url',''))}{ru_line}")
        lines.append("")

    caption = "\n".join(lines).strip()
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

    if r.status_code >= 400:
        # Печатаем точный ответ Telegram, чтобы понять причину
        print("Telegram sendPhoto failed:", r.status_code, r.text)

        # Fallback: отправляем текстом без HTML
        send_message_fallback(strip_html(caption))
        return

    print("Telegram sendPhoto OK:", r.status_code)

def strip_html(s: str) -> str:
    # грубо убираем HTML теги, чтобы точно прошло
    return re.sub(r"<[^>]+>", "", s)

def send_message_fallback(text: str):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text[:3500],
        "disable_web_page_preview": True
    }
    r = requests.post(url, json=payload, timeout=60)
    if r.status_code >= 400:
        print("Telegram sendMessage failed:", r.status_code, r.text)
        r.raise_for_status()
    print("Telegram sendMessage OK:", r.status_code)

def main():
    if not BANNER_PATH.exists():
        raise FileNotFoundError("Banner image not found: assets/digest_banner.jpg")

    if not FUNDING_PATH.exists() and not STARTUPS_PATH.exists():
        raise FileNotFoundError("Funding/startups datasets not found in data/")

    funding_window, startups_window = load_window_lists()
    sent = load_sent()

    top_funding, top_startups, sent = pick_items(funding_window, startups_window, sent)

    # чтобы не засорять канал "пустыми" постами — просто молчим
    if not top_funding and not top_startups:
        print("No new relevant items in this window (or already sent).")
        return

    caption = build_caption(top_funding, top_startups, funding_window, startups_window)
    send_photo(caption)
    save_sent(sent)

    print("Sent digest photo + caption.")

if __name__ == "__main__":
    main()
