import json
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, List, Optional

import feedparser
import requests
from dateutil import parser as dtparser

from tagger import is_relevant_startup_news
from utils import strip_html, safe_url

ROOT = Path(__file__).resolve().parents[1]
FEEDS_PATH = ROOT / "feeds.json"
DATA_DIR = ROOT / "data"
STATE_PATH = DATA_DIR / "state.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)

@dataclass
class Item:
    id: str
    source: str
    country_hint: str
    title: str
    url: str
    published_at: Optional[str]
    summary: str

def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))

def save_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

def make_id(url: str, source: str) -> str:
    base = f"{source}||{url}"
    return sha256(base.encode("utf-8")).hexdigest()[:20]

def parse_datetime(entry: Dict[str, Any]) -> Optional[str]:
    for key in ("published", "updated", "created"):
        if entry.get(key):
            try:
                dt = dtparser.parse(entry[key])
                if not dt.tzinfo:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc).isoformat()
            except Exception:
                pass
    for key in ("published_parsed", "updated_parsed"):
        if entry.get(key):
            try:
                dt = datetime.fromtimestamp(time.mktime(entry[key]), tz=timezone.utc)
                return dt.isoformat()
            except Exception:
                pass
    return None

def fetch_feed(url: str, timeout: int = 25) -> feedparser.FeedParserDict:
    headers = {"User-Agent": "latam-startup-bot/1.0"}
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return feedparser.parse(r.content)

def score_item(title: str, summary: str) -> int:
    text = f"{title} {summary}".lower()
    score = 0
    # signals
    for w in ["raised", "raises", "funding", "series", "seed", "investment", "acquired", "acquisition", "expands", "launches"]:
        if w in text:
            score += 3
    for w in ["inversión", "ronda", "financiación", "levantó", "adquirió", "expande", "desembarca"]:
        if w in text:
            score += 3
    for w in ["factory", "manufacturing", "plant", "production", "planta", "fábrica", "producción"]:
        if w in text:
            score += 2
    # startup relevance
    if is_relevant_startup_news(text):
        score += 5
    return score

def pick_one_new(items: List[Item], seen_ids: Dict[str, str]) -> Optional[Item]:
    # sort by score then date
    def dtkey(it: Item):
        return it.published_at or ""

    items_sorted = sorted(items, key=lambda x: (score_item(x.title, x.summary), dtkey(x)), reverse=True)
    for it in items_sorted:
        if it.id not in seen_ids:
            return it
    return None

def main() -> Optional[Dict[str, Any]]:
    cfg = load_json(FEEDS_PATH, {})
    sources = cfg.get("sources", [])
    if not sources:
        raise RuntimeError("feeds.json has no sources")

    state = load_json(STATE_PATH, {"sent_ids": {}, "seen_ids": {}, "updated_at": None})
    seen_ids = state.get("seen_ids", {}) or {}

    collected: List[Item] = []
    ok = 0
    fail = 0

    for src in sources:
        name = src.get("name", "Unknown")
        hint = src.get("country_hint", "LATAM")
        url = src.get("url")
        if not url:
            continue

        try:
            feed = fetch_feed(url)
            ok += 1
        except Exception as e:
            fail += 1
            print(f"[WARN] feed fail: {name}: {e}")
            continue

        for entry in (feed.entries or [])[:40]:
            title = (entry.get("title") or "").strip()
            link = safe_url(entry.get("link") or "")
            if not title or not link:
                continue

            summ = strip_html(entry.get("summary") or entry.get("description") or "")
            summ = summ[:800]

            blob = f"{title} {summ}"
            if not is_relevant_startup_news(blob):
                continue

            item_id = make_id(link, name)
            published_at = parse_datetime(entry)

            collected.append(Item(
                id=item_id,
                source=name,
                country_hint=hint,
                title=title,
                url=link,
                published_at=published_at,
                summary=summ
            ))

    if not collected:
        print(f"[WARN] Collected 0 relevant items (feeds ok={ok}, fail={fail}).")
        return None

    chosen = pick_one_new(collected, seen_ids)
    if not chosen:
        print("No new items (all already seen).")
        return None

    # mark as seen immediately to avoid duplicates next run
    seen_ids[chosen.id] = datetime.now(timezone.utc).isoformat()
    state["seen_ids"] = seen_ids
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_json(STATE_PATH, state)

    print(f"Chosen: {chosen.source} :: {chosen.title}")
    return asdict(chosen)

if __name__ == "__main__":
    main()
