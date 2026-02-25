import json
import feedparser
from pathlib import Path
from hashlib import sha256

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
FEEDS = ROOT / "feeds.json"
SEEN = DATA / "seen.json"

DATA.mkdir(exist_ok=True)

def load_json(p, default):
    if not p.exists():
        return default
    return json.loads(p.read_text())

def save_json(p, obj):
    p.write_text(json.dumps(obj, indent=2))

feeds = load_json(FEEDS, {}).get("sources", [])
seen = load_json(SEEN, [])

for src in feeds:
    feed = feedparser.parse(src["url"])

    for entry in feed.entries[:20]:
        link = entry.get("link")
        title = entry.get("title")

        if not link or not title:
            continue

        uid = sha256(link.encode()).hexdigest()

        if uid in seen:
            continue

        print(json.dumps({
            "id": uid,
            "title": title,
            "link": link,
            "summary": entry.get("summary", "")
        }))

        seen.append(uid)
        save_json(SEEN, seen)
        exit()

print("No new items.")
