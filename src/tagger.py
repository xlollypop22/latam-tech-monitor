import re
from typing import Dict, List, Tuple

# ISO2 -> flag emoji
def flag(iso2: str) -> str:
    iso2 = (iso2 or "").upper()
    if len(iso2) != 2 or not iso2.isalpha():
        return "🌎"
    return chr(127397 + ord(iso2[0])) + chr(127397 + ord(iso2[1]))

COUNTRY_KEYWORDS = {
    "AR": ["argentina", "argentino", "buenos aires", "mendoza", "cordoba"],
    "BR": ["brazil", "brasil", "são paulo", "rio de janeiro", "bahia"],
    "MX": ["mexico", "méxico", "cdmx", "guadalajara", "jalisco", "monterrey"],
    "CL": ["chile", "santiago", "valparaíso"],
    "CO": ["colombia", "bogotá", "medellín", "cali"],
    "PE": ["peru", "lima"],
    "UY": ["uruguay", "montevideo"],
    "PY": ["paraguay", "asunción"],
    "EC": ["ecuador", "quito", "guayaquil"],
    "BO": ["bolivia", "la paz", "santa cruz"],
    "PA": ["panama", "panamá"],
    "CR": ["costa rica", "san josé"],
    "DO": ["dominican", "república dominicana", "santo domingo"],
    "SV": ["el salvador", "san salvador"],
    "GT": ["guatemala", "guatemala city"],
}

SECTOR_RULES: List[Tuple[str, List[str]]] = [
    ("FinTech", ["fintech", "payments", "payment", "wallet", "bank", "lending", "credit", "crypto", "usdt", "remittance"]),
    ("MedTech", ["medtech", "healthtech", "health", "hospital", "clinic", "biotech", "pharma", "diagnostic"]),
    ("EdTech", ["edtech", "education", "learning", "school", "university", "lms", "course", "student"]),
    ("AI", ["ai", "artificial intelligence", "machine learning", "llm", "model", "genai"]),
    ("SaaS", ["saas", "b2b software", "subscription", "platform", "enterprise software"]),
    ("HRTech", ["hrtech", "hr", "hiring", "recruit", "talent", "payroll", "benefits"]),
    ("Climate", ["climate", "carbon", "sustainab", "recycling", "clean energy", "solar", "wind"]),
    ("Energy", ["energy", "oil", "gas", "grid", "renewable"]),
    ("AgriTech", ["agritech", "agro", "farm", "crops", "livestock"]),
    ("Mobility", ["mobility", "ride", "transport", "logistics", "delivery", "fleet"]),
    ("E-commerce", ["ecommerce", "e-commerce", "marketplace", "retail", "shop"]),
    ("InsurTech", ["insurtech", "insurance"]),
    ("PropTech", ["proptech", "real estate", "housing"]),
    ("Cybersecurity", ["cyber", "security", "infosec", "fraud"]),
    ("Manufacturing", ["factory", "manufacturing", "plant", "production", "industrial", "new facility", "gigafactory"]),
]

EVENT_RULES: List[Tuple[str, List[str]]] = [
    ("Funding", ["raised", "raises", "round", "series a", "series b", "seed", "pre-seed", "investment", "financing", "funding", "ronda", "inversión", "levantó", "financiación"]),
    ("M&A", ["acquired", "acquires", "acquisition", "merger", "m&a", "compró", "adquirió"]),
    ("MarketEntry", ["launches in", "enters", "expands to", "expansion", "new market", "arrives to", "llega a", "desembarca", "expande"]),
    ("NewPlant", ["opens", "opening", "new plant", "new factory", "builds", "manufacturing", "production facility", "planta", "fábrica", "producción"]),
    ("Partnership", ["partners", "partnership", "agreement", "allianc", "acuerdo", "alianza"]),
]

STARTUP_FILTER_HINTS = [
    "startup", "start-up", "scaleup", "unicorn", "vc", "venture", "accelerator", "incubator",
    "funding", "series", "seed", "round", "investment", "acquired", "acquisition",
    "fintech", "saas", "ai", "platform", "raises", "raised",
    "inversión", "ronda", "financiación", "levantó", "adquirió", "acuerdo"
]

def detect_country(text: str, hint: str = "LATAM") -> str:
    t = (text or "").lower()
    for iso2, keys in COUNTRY_KEYWORDS.items():
        if any(k in t for k in keys):
            return iso2
    # fallback to hint if it looks like ISO2
    h = (hint or "").upper()
    if len(h) == 2 and h.isalpha():
        return h
    return "LATAM"

def detect_sectors(text: str) -> List[str]:
    t = (text or "").lower()
    out = []
    for sector, keys in SECTOR_RULES:
        if any(k in t for k in keys):
            out.append(sector)
    return out[:3] if out else ["Tech"]

def detect_events(text: str) -> List[str]:
    t = (text or "").lower()
    out = []
    for ev, keys in EVENT_RULES:
        if any(k in t for k in keys):
            out.append(ev)
    return out[:2] if out else ["News"]

def is_relevant_startup_news(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in STARTUP_FILTER_HINTS)
