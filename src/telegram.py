import io
import requests
from PIL import Image, ImageDraw, ImageFont

from utils import escape_html

def generate_fallback_image(country_flag: str, title: str, tags: list[str]) -> bytes:
    # Safe RGB PNG
    w, h = 1200, 630
    img = Image.new("RGB", (w, h), (20, 24, 32))
    draw = ImageDraw.Draw(img)

    # default PIL font (no extra files)
    font_big = ImageFont.load_default()
    font_small = ImageFont.load_default()

    # Header
    draw.text((40, 40), f"{country_flag} LATAM Startup Update", fill=(240, 240, 240), font=font_big)

    # Title (wrap)
    t = title.strip()
    lines = []
    max_len = 56
    while len(t) > max_len:
        cut = t[:max_len]
        sp = cut.rfind(" ")
        if sp <= 0:
            sp = max_len
        lines.append(t[:sp])
        t = t[sp:].strip()
    if t:
        lines.append(t)

    y = 120
    for ln in lines[:7]:
        draw.text((40, y), ln, fill=(220, 220, 220), font=font_big)
        y += 34

    # Tags
    tag_line = " ".join([f"#{x}" for x in tags[:6]])
    draw.text((40, h - 70), tag_line, fill=(120, 200, 255), font=font_small)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def download_image(url: str, timeout: int = 25) -> bytes | None:
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "latam-startup-bot/1.0"})
        r.raise_for_status()
        # Telegram likes jpeg/png; we just pass bytes, most og:image is OK
        if len(r.content) < 5000:
            return None
        return r.content
    except Exception:
        return None

def send_telegram_post(token: str, chat_id: str, image_bytes: bytes, caption_html: str) -> None:
    api = f"https://api.telegram.org/bot{token}/sendPhoto"
    files = {"photo": ("image.png", image_bytes)}
    data = {
        "chat_id": chat_id,
        "caption": caption_html,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    r = requests.post(api, data=data, files=files, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"Telegram sendPhoto failed: {r.text}")

def build_caption_html(country_flag: str, ru_summary: str, ru_insight: str, url: str, industry_tags: list[str], event_tags: list[str]) -> str:
    # Classic channel post
    tags = []
    tags += [f"#{t}" for t in industry_tags]
    tags += [f"#{t}" for t in event_tags]
    tags_str = " ".join(tags)

    ru_summary = escape_html(ru_summary)
    ru_insight = escape_html(ru_insight)
    url = escape_html(url)

    # link icon + clickable
    return (
        f"{country_flag} <b>{ru_summary}</b>\n\n"
        f"{ru_insight}\n\n"
        f"🔗 <a href=\"{url}\">Источник</a>\n"
        f"{escape_html(tags_str)}"
    )
