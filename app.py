import re
import html
import hashlib
from datetime import datetime, timezone
from typing import List, Dict, Any

import requests
import feedparser
import streamlit as st
import pytz
import streamlit.components.v1 as components
from dateutil import parser as dtparser

TZ = pytz.timezone("Europe/Istanbul")

DEFAULT_FEEDS = {
    "BloombergHT": "https://www.bloomberght.com/rss",
    "Bigpara": "https://bigpara.hurriyet.com.tr/rss/",
    "Ekonomim": "https://www.ekonomim.com/rss",
    # optional extras
    "CNBC-e": "https://www.cnbce.com/rss",
    "Doviz.com": "https://www.doviz.com/news/rss",
    "Foreks": "https://www.foreks.com/rss/",
}

SECTOR_KEYWORDS = {
    "Bankacılık/Finans": ["banka", "bankac", "kredi", "faiz", "tcmb", "merkez bank", "tahvil"],
    "Sanayi": ["sanayi", "çimento", "demir", "çelik", "otomotiv", "ihracat"],
    "Enerji": ["enerji", "petrol", "doğalgaz", "elektrik", "yenilenebilir", "akaryakıt"],
    "Holding": ["holding"],
    "GYO": ["gyo", "gayrimenkul", "konut"],
    "Teknoloji/Savunma": ["teknoloji", "yazılım", "savunma", "havacılık", "uydu", "drone"],
    "Perakende/Gıda": ["gıda", "perakende", "tüketim", "içecek", "market"],
}

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
def fetch_feed_items(name: str, url: str, limit: int = 30, timeout_sec: int = 8) -> List[Dict[str, Any]]:
    """
    Fetch RSS with requests timeout (prevents blank-page hang),
    then parse using feedparser.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; LettaEarthRSS/1.0; +https://example.com)"
    }

    try:
        r = requests.get(url, headers=headers, timeout=timeout_sec)
        r.raise_for_status()
        parsed = feedparser.parse(r.content)
    except Exception as e:
        # Return a special "error item" so UI can show feed failure without crashing
        return [{
            "source": name,
            "title": f"Feed error: {name}",
            "link": url,
            "summary": str(e),
            "published": None,
            "hash": item_hash(name, url),
            "is_error": True
        }]

    out: List[Dict[str, Any]] = []
    for e in (parsed.entries or [])[:limit]:
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
            "is_error": False
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
    stop = set(["bugün","son","dakika","piyasa","borsa","bist","bist100","yüzde",
                "ile","daha","olarak","gibi","için","şirket","hisse","endeks"])
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
    sectors = sector_buckets(items)

    top_items = [it for it in items if not it.get("is_error")][:10]
    links_md = "\n".join(
        [f"- [{it['source']}] [{it['title']}]({it['link']})"
         for it in top_items if it.get("link")]
    )

    theme_line = " / ".join(themes[:3]) if themes else "Genel piyasa akışı"
    sector_line = ", ".join(
        [f"{k}({v})" for k, v in sorted(sectors.items(), key=lambda x: x[1], reverse=True)[:4]]
    ) if sectors else "Sektörel dağılım net değil"

    today_str = datetime.now(TZ).strftime("%d %b %Y")
    md = f"""
### Borsa İstanbul — Günlük Piyasa Özeti ({today_str})

**Günün Teması:** *{theme_line}*  
**Yoğunlaşma:** {sector_line}

Bugün haber akışında **{theme_line}** temaları öne çıktı. Manşet yoğunluğu özellikle **{sector_line}** çevresinde toplandı. Genel resim, sektörler arası rota değişimi ve şirket-özel gelişmelerle seçici bir fiyatlamaya işaret ediyor.

#### Öne Çıkanlar
{links_md if links_md else "- (Bugün için öne çıkan başlık bulunamadı)"}
""".strip()
    return md

def tradingview_embed_url(symbol: str, interval: str, theme: str) -> str:
    sym = symbol.replace(" ", "")
    params = {
        "symbol": sym,
        "interval": interval,
        "hidesidetoolbar": "1",
        "symboledit": "0",
        "saveimage": "0",
        "toolbarbg": "F1F3F6",
        "studies": "[]",
        "theme": theme,
    }
    query = "&".join([f"{k}={v}" for k, v in params.items()])
    return f"https://s.tradingview.com/widgetembed/?{query}"

# ---------------------------
# UI
# ---------------------------
st.set_page_config(page_title="Letta Earth — Borsa İstanbul Daily", layout="wide")

# If it still looks blank, this line should appear instantly.
st.title("Letta Earth — Borsa İstanbul (Daily)")
st.caption("RSS → Günlük özet • TradingView grafik • Looker Studio embed")

with st.sidebar:
    st.subheader("RSS Kaynakları")
    use_extras = st.checkbox("Ek kaynakları dahil et (CNBC-e / Doviz / Foreks)", value=True)
    only_today = st.checkbox("Sadece bugünün haberleri", value=True)
    per_feed_limit = st.slider("Feed başına max haber", 10, 80, 30, 5)
    timeout_sec = st.slider("RSS timeout (sn)", 4, 20, 8, 1)

    st.divider()
    st.subheader("TradingView Grafik")
    preset = st.selectbox("Preset", list(TV_PRESETS.keys()), index=1)
    symbol = st.text_input("Symbol (TradingView)", value=TV_PRESETS[preset])
    interval = st.selectbox("Interval", ["D", "240", "60", "15"], index=0)
    theme = st.selectbox("Theme", ["light", "dark"], index=0)
    tv_height = st.slider("Grafik yüksekliği", 420, 900, 520, 20)

    st.divider()
    st.subheader("Looker Studio (iframe)")
    looker_urls = st.text_area(
        "Her satıra bir embed URL",
        value="",
        placeholder="https://lookerstudio.google.com/embed/reporting/....\nhttps://lookerstudio.google.com/embed/reporting/...."
    )
    iframe_height = st.slider("Iframe yüksekliği", 400, 1400, 700, 50)

feeds = dict(DEFAULT_FEEDS)
if not use_extras:
    feeds = {k: v for k, v in feeds.items() if k in ["BloombergHT", "Bigpara", "Ekonomim"]}

# Add a manual refresh button to clear cache
if st.button("🔄 Refresh now (clear cache)"):
    st.cache_data.clear()
    st.rerun()

col1, col2 = st.columns([1.15, 0.85], gap="large")

with col1:
    st.subheader("📰 Piyasa Haberleri (RSS) — Günlük Özet")

    all_items: List[Dict[str, Any]] = []
    for name, url in feeds.items():
        all_items.extend(fetch_feed_items(name, url, limit=per_feed_limit, timeout_sec=timeout_sec))

    all_items = dedupe(all_items)

    # Show feed errors clearly
    errors = [it for it in all_items if it.get("is_error")]
    if errors:
        st.warning("Some feeds failed to load (shown below). The app will still work with the remaining feeds.")
        for er in errors:
            st.markdown(f"- **{er['source']}** → {er['summary']}")

    # Keep only non-error items for digest
    news_items = [it for it in all_items if not it.get("is_error")]
    news_items = filter_today(news_items, only_today)

    if not news_items:
        st.info("No items matched your filters. Try turning off **Only today's news**.")
    else:
        st.markdown(build_digest(news_items))

        with st.expander("Tüm başlıklar"):
            rows = [{
                "published": (it["published"].strftime("%Y-%m-%d %H:%M") if it.get("published") else ""),
                "source": it["source"],
                "title": it["title"],
                "link": it["link"],
            } for it in sorted(news_items, key=lambda x: x.get("published") or datetime(1970,1,1,tzinfo=TZ), reverse=True)]
            st.dataframe(rows, use_container_width=True, hide_index=True)

with col2:
    st.subheader("📈 TradingView Grafik Widget")

    if not symbol or ":" not in symbol:
        st.info("Use TradingView format like **BIST:THYAO** or **BIST:XU100**.")
    else:
        tv_url = tradingview_embed_url(symbol=symbol, interval=interval, theme=theme)
        components.iframe(tv_url, height=tv_height, scrolling=False)

st.divider()
st.subheader("📊 Looker Studio Raporları")

urls = [u.strip() for u in looker_urls.splitlines() if u.strip()]
if not urls:
    st.info("Add Looker Studio embed links in the sidebar to display them here.")
else:
    for i, u in enumerate(urls, start=1):
        st.markdown(f"**Rapor {i}**")
        components.iframe(u, height=iframe_height, scrolling=True)
        st.markdown("---")
