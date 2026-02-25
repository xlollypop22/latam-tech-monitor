import re
import html
import requests
from bs4 import BeautifulSoup

def norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()

def strip_html(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return norm_space(s)

def safe_url(u: str) -> str:
    return (u or "").strip()

def fetch_html(url: str, timeout: int = 25) -> str:
    headers = {
        "User-Agent": "latam-startup-bot/1.0",
        "Accept": "text/html,application/xhtml+xml",
    }
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.text

def extract_og_image(url: str) -> str | None:
    try:
        html_text = fetch_html(url)
        soup = BeautifulSoup(html_text, "html.parser")
        og = soup.find("meta", property="og:image")
        if og and og.get("content"):
            return og["content"].strip()
        tw = soup.find("meta", attrs={"name": "twitter:image"})
        if tw and tw.get("content"):
            return tw["content"].strip()
        return None
    except Exception:
        return None

def escape_html(s: str) -> str:
    # for Telegram HTML
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
