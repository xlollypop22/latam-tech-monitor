import os
import requests
import json
import sys
from groq import Groq
from utils import extract_image

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]

client = Groq(api_key=GROQ_API_KEY)

data = json.loads(sys.stdin.read())

title = data["title"]
summary = data["summary"]
link = data["link"]

prompt = f"""
Ты финансовый, экономический и политический аналитик.
Переведи новость на русский язык, структурируй и кратко интерпретируй новость.

Новость:
{title}
{summary}

Формат:
1-2 абзаца перевода
Определи отрасль (одну или две) из списка:
FinTech, EdTech, MedTech, AI, Energy, Climate, SaaS, Mobility, Manufacturing
"""

response = client.chat.completions.create(
    model="llama-3.1-8b-instant",
    messages=[{"role": "user", "content": prompt}],
)

text = response.choices[0].message.content

image = extract_image(link)

message = f"""
{text}

🔗 <a href="{link}">Источник</a>
"""

if image:
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
        data={
            "chat_id": CHAT_ID,
            "caption": message,
            "parse_mode": "HTML"
        },
        files={"photo": requests.get(image).content}
    )
else:
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        data={
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }
    )
