import re
import html
import hashlib
from datetime import datetime, timezone
from typing import List, Dict, Any

import feedparser
import pandas as pd
import streamlit as st
import pytz
import streamlit.components.v1 as components
from dateutil import parser as dtparser

TZ = pytz.timezone("Europe/Istanbul")

# --- Your RSS feeds + optional extras
DEFAULT_FEEDS = {
    "BloombergHT": "https://www.bloomberght.com/rss",
    "Bigpara": "https://bigpara.hurriyet.com.tr/rss/",
    "Ekonomim": "https://www.ekonomim.com/rss",
    # Extras (you can turn off from sidebar)
    "CNBC-e": "https://www.cnbce.com/rss",
    "Doviz.com": "https://www.doviz.com/news/rss",
    "Foreks": "https://www.foreks.com/rss/",
}

# Optional lightweight tagging (no LLM)
SECTOR_KEYWORDS = {
    "Bankacılık/Finans": ["banka", "bankac", "kredi", "faiz", "tcmb", "merkez bank", "tahvil"],
    "Sanayi": ["sanayi", "çimento", "demir", "çelik", "otomotiv", "ihracat"],
    "Enerji": ["enerji", "petrol", "doğalgaz", "elektrik", "yenilenebilir", "akaryakıt"],
    "Holding": ["holding"],
    "GYO": ["gyo", "gayrimenkul", "konut"],
    "Teknoloji/Savunma": ["teknoloji", "yazılım", "savunma", "havacılık", "drone", "uydu"],
    "Perakende/Gıda": ["gıda", "perakende", "tüketim", "içecek", "market"],
}

# TradingView presets (Borsa Istanbul)
TV_PRESETS = {
    "BIST 100 (Index)": "BIST:XU100",
    "THYAO": "BIST:THYAO",
    "ASELS": "BIST:ASELS",
    "KCHOL": "BIST:KCHOL",
    "BIMAS": "BIST:BIMAS",
    "GARAN": "BIST:GARAN",
    "AKBNK": "BIST:AKBNK",
    "TUPRS": "BIST:TUPRS",
    "EREGL": "BIST:EREGL",
    "FROTO": "BIST:FROTO",
    "SISE": "BIST:SISE",
}

# ---------------------------
# Helpers
# ---------------------------
def clean_text(s: str) -> str:
    s = html.unescape(s or "")
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def safe_parse_dt(x: Any) -> datetime | None:
    if not x:
        return None
    try:
        dt = dtparser.parse(str(x))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(TZ)
    except Exception:
        return None

def item_hash(title: str, link: str) -> str:
    h = hashlib.sha256((title + "||" + link).encode("utf-8")).hexdigest()
    return h[:16]

@st.cache_data(ttl=600, show_spinner=False)
def fetch_feed(name: str, url: str, limit: int = 30) -> List[Dict[str, Any]]:
    d = feedparser.parse(url)
    out: List[Dict[str, Any]] = []
    for e in (d.entries or [])[:limit]:
        title = clean_text(getattr(e, "title", "") or "")
        link = getattr(e, "link", "") or ""
        summary = clean_text(getattr(e, "summary", "") or getattr(e, "description", "") or "")
        published = safe_parse_dt(getattr(e, "published", None) or getattr(e, "updated", None))
        out.append({
            "source": name,
            "title": title,
            "link": link,
            "summary": summary,
            "published": published,
            "hash": item_hash(title, link),
        })
    return out

def dedupe(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for it in items:
        key = it.get("hash") or (it.get("title", "") + it.get("link", ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out

def filter_today(items: List[Dict[str, Any]], only_today: bool) -> List[Dict[str, Any]]:
    if not only_today:
        return items
    today = datetime.now(TZ).date()
    return [it for it in items if it.get("published") and it["published"].date() == today]

def keyword_theme(items: List[Dict[str, Any]]) -> List[str]:
    text = " ".join([(it["title"] + " " + it.get("summary", "")) for it in items]).lower()
    text = re.sub(r"[^a-zçğıöşü0-9\s]", " ", text)
    tokens = [t for t in text.split() if len(t) >= 4]
    stop = set(["bugün", "son", "dakika", "piyasa", "borsa", "bist", "bist100", "yüzde",
                "ile", "daha", "olarak", "gibi", "için", "şirket", "hisse", "endeks"])
    tokens = [t for t in tokens if t not in stop]
    freq: Dict[str, int] = {}
    for t in tokens:
        freq[t] = freq.get(t, 0) + 1
    top = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:6]
    return [w for w, _ in top]

def sector_buckets(items: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {k: 0 for k in SECTOR_KEYWORDS.keys()}
    for it in items:
        blob = (it["title"] + " " + it.get("summary", "")).lower()
        for sector, kws in SECTOR_KEYWORDS.items():
            if any(kw in blob for kw in kws):
                counts[sector] += 1
    return {k: v for k, v in counts.items() if v > 0}

def build_digest(items: List[Dict[str, Any]]) -> str:
    items = sorted(
        items,
        key=lambda x: x.get("published") or datetime(1970, 1, 1, tzinfo=TZ),
        reverse=True
    )

    themes = keyword_theme(items)
    sectors = sect
