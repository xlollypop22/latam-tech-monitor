import requests
from bs4 import BeautifulSoup

def extract_image(url):
    try:
        r = requests.get(url, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")

        og = soup.find("meta", property="og:image")
        if og:
            return og.get("content")

        img = soup.find("img")
        if img:
            return img.get("src")

    except:
        return None

    return None
