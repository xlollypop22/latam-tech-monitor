import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import feedparser
import requests
from dateutil import parser as dtparser

ROOT = Path(__file__).resolve().parents[1]
FEEDS_PATH = ROOT / "feeds" / "feeds_latam.json"
DATA_DIR = ROOT / "data"

# IMPORTANT: this is collector "seen" state (not telegram sent_state)
STATE_PATH = DATA_DIR / "state.json"

DIGEST_PATH = DATA_DIR / "latam_digest.json"
FUNDING_PATH = DATA_DIR / "latam_funding.json"
STARTUPS_PATH = DATA_DIR / "latam_startups.json"


FUNDING_RE = re.compile(
    r"\b("
    r"funding|raised|raise|round|seed|pre-seed|series\s*[abcs]|series\s*[0-9]+|"
    r"inversi[oó]n|inversiones|ronda|levant[oó]|financiaci[oó]n|capital|vc|venture|"
    r"angel|term\s*sheet|valuat|valuation|m\&a|acquisition|acquired"
    r")\b",
    re.IGNORECASE,
)

STARTUP_RE = re.compile(
    r"\b(startup|start-ups|emprendim|emprendedor|acelerador|accelerator|incubator|"
    r"scaleup|scale-up|unicorn|founded|launch|product)\b",
    re.IGNORECASE,
)


@dataclass
class Item:
    id: str
    country: str
    bucket: str
    source: str
    title: str
    url: str
    published_at: Optional[str]
    summary: Optional[str]
    categories: List[str]
    detected: List[str]   # ["funding", "startup_news"]


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def save_json_safe(path: Path, obj: Any) -> None:
    """Atomic-ish save: write to temp then replace."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    _write_json(tmp, obj)
    tmp.replace(path)


def norm_url(url: str) -> str:
    return (url or "").strip()


def make_id(url: str, title: str, source: str) -> str:
    base = f"{source}||{norm_url(url)}||{(title or '').strip()}"
    return sha256(base.encode("utf-8")).hexdigest()[:20]


def parse_datetime(entry: Dict[str, Any]) -> Optional[str]:
    # feedparser fields can vary
    for key in ("published", "updated", "created"):
        if key in entry and entry[key]:
            try:
                dt = dtparser.parse(entry[key])
                if not dt.tzinfo:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc).isoformat()
            except Exception:
                pass

    # try structured fields
    for key in ("published_parsed", "updated_parsed"):
        if key in entry and entry[key]:
            try:
                dt = datetime.fromtimestamp(time.mktime(entry[key]), tz=timezone.utc)
                return dt.isoformat()
            except Exception:
                pass
    return None


def detect_types(text: str) -> List[str]:
    found = []
    if FUNDING_RE.search(text):
        found.append("funding")
    if STARTUP_RE.search(text):
        found.append("startup_news")
    return found


def summarize(entry: Dict[str, Any]) -> Optional[str]:
    s = entry.get("summary") or entry.get("description")
    if not s:
        return None
    s = re.sub(r"\s+", " ", s).strip()
    return s[:500] if len(s) > 500 else s


def fetch_feed(url: str, timeout: int = 25) -> feedparser.FeedParserDict:
    headers = {
        "User-Agent": "latam-tech-monitor/1.0 (+https://github.com/)",
        "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
    }
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return feedparser.parse(r.content)


def sort_items_newest_first(items: List[Item]) -> List[Item]:
    def sort_key(x: Item) -> Tuple[int, str]:
        # unknown dates go last
        if not x.published_at:
            return (1, "0000-00-00T00:00:00+00:00")
        return (0, x.published_at)

    return sorted(items, key=sort_key, reverse=True)


def main() -> None:
    ensure_dirs()

    cfg = load_json(FEEDS_PATH, {})
    sources = cfg.get("sources", [])
    if not sources:
        raise RuntimeError("No sources in feeds_latam.json")

    # Load state
    state = load_json(STATE_PATH, {"seen_ids": [], "seen_urls": []})
    seen_ids = set(state.get("seen_ids", []))
    seen_urls = set(state.get("seen_urls", []))

    all_items: List[Item] = []
    new_seen_ids = set(seen_ids)
    new_seen_urls = set(seen_urls)

    fetched_ok = 0
    fetched_fail = 0

    for src in sources:
        if src.get("type") != "rss":
            continue

        country = src.get("country", "LATAM")
        bucket = src.get("bucket", country)
        source_name = src.get("source", "Unknown")
        feed_url = src.get("url")

        try:
            feed = fetch_feed(feed_url)
            fetched_ok += 1
        except Exception as e:
            fetched_fail += 1
            print(f"[WARN] failed to fetch {source_name}: {e}")
            continue

        for entry in feed.entries[:60]:
            title = (entry.get("title") or "").strip()
            link = norm_url(entry.get("link") or "")
            if not title or not link:
                continue

            item_id = make_id(link, title, source_name)
            if item_id in seen_ids or link in seen_urls:
                continue

            published_at = parse_datetime(entry)
            summ = summarize(entry)

            cats: List[str] = []
            for c in entry.get("tags", []) or []:
                t = (c.get("term") or "").strip()
                if t:
                    cats.append(t)

            blob = " ".join([title, summ or "", " ".join(cats)]).strip()
            detected = detect_types(blob)

            it = Item(
                id=item_id,
                country=country,
                bucket=bucket,
                source=source_name,
                title=title,
                url=link,
                published_at=published_at,
                summary=summ,
                categories=cats[:12],
                detected=detected,
            )
            all_items.append(it)

            # IMPORTANT: update seen only if we actually found an item
            new_seen_ids.add(item_id)
            new_seen_urls.add(link)

    all_items = sort_items_newest_first(all_items)

    digest = [asdict(x) for x in all_items]
    funding = [asdict(x) for x in all_items if "funding" in x.detected]
    startups = [asdict(x) for x in all_items if "startup_news" in x.detected]

    # =========================
    # CRITICAL: Do NOT overwrite datasets with empty results
    # =========================
    if len(digest) == 0:
        print(
            f"[WARN] Collected 0 items (feeds ok={fetched_ok}, fail={fetched_fail}). "
            "Keeping previous data/*.json unchanged."
        )
        # Do not update state either (prevents "eating" items)
        return

    # Save datasets
    save_json_safe(DIGEST_PATH, digest)
    save_json_safe(FUNDING_PATH, funding)
    save_json_safe(STARTUPS_PATH, startups)

    # Keep state bounded (only after successful collect)
    state_out = {
        "updated_at": datetime.now(tz=timezone.utc).isoformat(),
        "seen_ids": list(new_seen_ids)[-20000:],
        "seen_urls": list(new_seen_urls)[-20000:],
    }
    save_json_safe(STATE_PATH, state_out)

    print(
        f"Collected: digest={len(digest)}, funding={len(funding)}, startups={len(startups)} "
        f"(feeds ok={fetched_ok}, fail={fetched_fail})"
    )


if __name__ == "__main__":
    main()
