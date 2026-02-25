import json
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"

FUNDING_PATH = DATA_DIR / "latam_funding.json"
STARTUPS_PATH = DATA_DIR / "latam_startups.json"

# ты писал что поправил sent_state -> поддерживаем оба варианта:
SENT_STATE_PATH = DATA_DIR / "sent_state.json"
SENT_STATE_LEGACY = DATA_DIR / "state.json"  # на всякий


# ---- Telegram ----

def tg_send_message(token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",  # чтобы делать кликабельные ссылки <a href="">
        "disable_web_page_preview": True,
    }
    r = requests.post(url, json=payload, timeout=30)
    if r.status_code < 200 or r.status_code >= 300:
        raise RuntimeError(f"Telegram sendMessage failed: HTTP {r.status_code} {r.text}")


# ---- IO ----

def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))

def save_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


# ---- Utils ----

def parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if not dt.tzinfo:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None

def esc_html(s: str) -> str:
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )

def compact_source(it: Dict[str, Any]) -> str:
    # короткий источник/страна для подписи
    src = (it.get("source") or "").strip()
    bucket = (it.get("bucket") or it.get("country") or "").strip()
    if bucket and src:
        return f"{bucket} · {src}"
    return bucket or src or "LATAM"

def guess_sector(it: Dict[str, Any]) -> str:
    text = " ".join([
        (it.get("title") or ""),
        " ".join(it.get("categories") or []),
        (it.get("summary") or "")
    ]).lower()

    rules = [
        ("Fintech", ["fintech", "payment", "payments", "wallet", "bank", "crypto", "usdt"]),
        ("HRTech", ["hr", "hiring", "recruit", "talent", "payroll", "benefits"]),
        ("EdTech", ["edtech", "education", "learning", "course", "university", "school"]),
        ("HealthTech", ["health", "med", "hospital", "clinic", "biotech", "pharma"]),
        ("AI/ML", ["ai", "artificial intelligence", "machine learning", "llm", "model"]),
        ("Mobility", ["mobility", "ride", "transport", "logistics", "delivery", "fleet"]),
        ("SaaS", ["saas", "b2b", "platform", "software"]),
        ("E-commerce", ["ecommerce", "e-commerce", "marketplace", "retail"]),
        ("Climate", ["climate", "energy", "solar", "carbon", "sustainab"]),
    ]
    for sector, keys in rules:
        if any(k in text for k in keys):
            return sector
    return "Other"

def tiny_ru_hint(title: str) -> str:
    """
    НЕ полноценный перевод.
    Короткая RU-подсказка по ключевым словам, чтобы пост был "с переводом"
    без платных API. Лучше, чем ничего, но без иллюзий.
    """
    t = (title or "").strip()
    low = t.lower()

    # финансирование
    m = re.search(r"(raises|raised|levanta|levant[oó]|cierra|closed)\s*\$?u?\$?s?\s*([0-9]+(?:\.[0-9]+)?)\s*m", low)
    if m:
        amt = m.group(2)
        return f"RU: привлекли ~${amt}M"

    if "series a" in low:
        return "RU: раунд Series A"
    if "series b" in low:
        return "RU: раунд Series B"
    if "seed" in low or "pre-seed" in low:
        return "RU: seed/предпосев"

    if "acquires" in low or "acquired" in low or "acquisition" in low:
        return "RU: сделка M&A / покупка"

    # безопасный дефолт
    return "RU: кратко — важная новость (см. ссылку)"


# ---- Dedup (sent_state) ----

def load_sent_state() -> Dict[str, str]:
    """
    { "sent": { "<id>": "<iso_utc>" } }
    """
    if SENT_STATE_PATH.exists():
        obj = load_json(SENT_STATE_PATH, {"sent": {}})
        return obj.get("sent", {}) if isinstance(obj, dict) else {}
    # если случайно остался legacy
    if SENT_STATE_LEGACY.exists():
        obj = load_json(SENT_STATE_LEGACY, {})
        # не ломаемся, просто стартуем чисто
    return {}

def save_sent_state(sent: Dict[str, str]) -> None:
    save_json(SENT_STATE_PATH, {"updated_at": datetime.now(timezone.utc).isoformat(), "sent": sent})

def prune_sent(sent: Dict[str, str], keep_hours: int = 36) -> Dict[str, str]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=keep_hours)
    out = {}
    for k, v in sent.items():
        dt = parse_dt(v)
        if dt and dt >= cutoff:
            out[k] = v
    return out


# ---- Selection ----

def pick_items(items: List[Dict[str, Any]], sent: Dict[str, str], limit: int, max_age_hours: int = 24) -> List[Dict[str, Any]]:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=max_age_hours)

    fresh = []
    for it in items:
        it_id = it.get("id")
        if not it_id:
            continue
        if it_id in sent:
            continue
        dt = parse_dt(it.get("published_at"))
        # если дата есть — берём только свежее, если даты нет — пропускаем (чтобы не тащить древнее)
        if dt and dt >= cutoff:
            fresh.append(it)

    # сортировка по дате, новые первыми
    def sk(x: Dict[str, Any]):
        dt = parse_dt(x.get("published_at"))
        return dt or datetime(1970, 1, 1, tzinfo=timezone.utc)

    fresh.sort(key=sk, reverse=True)
    return fresh[:limit]


def build_post(funding: List[Dict[str, Any]], startups: List[Dict[str, Any]]) -> str:
    now_ba = datetime.now(timezone.utc) - timedelta(hours=3)  # BA UTC-3
    stamp = now_ba.strftime("%d %b · %H:%M BA")

    # 1 строка "главное"
    headline = f"🧠 LATAM Tech Digest · {stamp}"

    lines = [headline]

    if funding:
        lines.append("")
        lines.append("💰 Funding (2):")
        for it in funding:
            sector = guess_sector(it)
            title = (it.get("title") or "").strip()
            url = (it.get("url") or "").strip()
            src = compact_source(it)

            # делаем красивую кликабельную ссылку: <a href="...">...</a>
            # важно экранировать текст
            title_html = esc_html(title)
            url_html = esc_html(url)

            lines.append(f"• <a href=\"{url_html}\">{title_html}</a> <i>({sector})</i>")
            lines.append(f"  {esc_html(tiny_ru_hint(title))} · {esc_html(src)}")

    if startups:
        lines.append("")
        lines.append("🚀 Startup news (2):")
        for it in startups:
            sector = guess_sector(it)
            title = (it.get("title") or "").strip()
            url = (it.get("url") or "").strip()
            src = compact_source(it)

            title_html = esc_html(title)
            url_html = esc_html(url)

            lines.append(f"• <a href=\"{url_html}\">{title_html}</a> <i>({sector})</i>")
            lines.append(f"  {esc_html(tiny_ru_hint(title))} · {esc_html(src)}")

    # если вообще пусто — коротко и без мусора
    if len(lines) == 1:
        lines.append("")
        lines.append("Сегодня в окне мониторинга нет новых релевантных публикаций.")

    # Telegram limit ~4096
    msg = "\n".join(lines).strip()
    if len(msg) > 3900:
        msg = msg[:3900] + "\n…"
    return msg


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if not token or not chat_id:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID in GitHub Secrets.")

    funding_items = load_json(FUNDING_PATH, [])
    startup_items = load_json(STARTUPS_PATH, [])

    if not isinstance(funding_items, list):
        funding_items = []
    if not isinstance(startup_items, list):
        startup_items = []

    sent = prune_sent(load_sent_state(), keep_hours=36)

    top_funding = pick_items(funding_items, sent, limit=2, max_age_hours=48)
    top_startups = pick_items(startup_items, sent, limit=2, max_age_hours=48)

    post = build_post(top_funding, top_startups)

    # отправляем
    tg_send_message(token, chat_id, post)

    # отмечаем отправленные
    now_iso = datetime.now(timezone.utc).isoformat()
    for it in top_funding + top_startups:
        it_id = it.get("id")
        if it_id:
            sent[it_id] = now_iso

    save_sent_state(sent)
    print(f"Sent: funding={len(top_funding)}, startups={len(top_startups)}")


if __name__ == "__main__":
    main()
