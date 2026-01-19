import re
import html
import hashlib
from datetime import datetime, date, timezone
from typing import List, Dict, Any

import feedparser
import pandas as pd
import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
from dateutil import parser as dtparser
import pytz

import streamlit.components.v1 as components

TZ = pytz.timezone("Europe/Istanbul")

# --- Default RSS feeds (your list + a few extras)
DEFAULT_FEEDS = {
    "BloombergHT": "https://www.bloomberght.com/rss",
    "Bigpara": "https://bigpara.hurriyet.com.tr/rss/",
    "Ekonomim": "https://www.ekonomim.com/rss",
    # extras (optional)
    "CNBC-e": "https://www.cnbce.com/rss",
    "Doviz.com": "https://www.doviz.com/news/rss",
    "Foreks": "https://www.foreks.com/rss/",
}

# Basic sector keywords for grouping (optional)
SECTOR_KEYWORDS = {
    "Bankacılık/Finans": ["banka", "bankac", "kredi", "faiz", "tcmb", "merkez bank", "tahvil"],
    "Sanayi": ["sanayi", "çimento", "demir", "çelik", "otomotiv", "ihracat"],
    "Enerji": ["enerji", "petrol", "doğalgaz", "elektrik", "yenilenebilir", "akaryakıt"],
    "Holding": ["holding"],
    "GYO": ["gyo", "gayrimenkul", "konut"],
    "Teknoloji": ["teknoloji", "yazılım", "savunma", "havacılık"],
    "Perakende/Gıda": ["gıda", "perakende", "tüketim", "içecek"],
}

BIST_PRESETS = {
    "ASELSAN": "ASELS.IS",
    "THYAO": "THYAO.IS",
    "KCHOL": "KCHOL.IS",
    "BIMAS": "BIMAS.IS",
    "GARAN": "GARAN.IS",
    "AKBNK": "AKBNK.IS",
    "TUPRS": "TUPRS.IS",
    "EREGL": "EREGL.IS",
    "FROTO": "FROTO.IS",
    "SISE": "SISE.IS",
}

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
            # assume UTC if missing (best-effort)
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
    out = []
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

def filter_today(items: List[Dict[str, Any]], only_today: bool) -> List[Dict[str, Any]]:
    if not only_today:
        return items
    today = datetime.now(TZ).date()
    out = []
    for it in items:
        dt = it.get("published")
        if dt and dt.date() == today:
            out.append(it)
    return out

def dedupe(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for it in items:
        key = it.get("hash") or (it.get("title","") + it.get("link",""))
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out

def keyword_theme(items: List[Dict[str, Any]]) -> List[str]:
    # very lightweight "theme" extraction from titles+snippets (no LLM)
    text = " ".join([(it["title"] + " " + it.get("summary","")) for it in items]).lower()
    text = re.sub(r"[^a-zçğıöşü0-9\s]", " ", text)
    tokens = [t for t in text.split() if len(t) >= 4]
    stop = set(["bugün","son","dakika","piyasa","borsa","bist","bist100","yüzde","ile","daha","olarak","gibi","için","şirket","hisse"])
    tokens = [t for t in tokens if t not in stop]
    freq = {}
    for t in tokens:
        freq[t] = freq.get(t, 0) + 1
    top = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:6]
    return [w for w,_ in top]

def sector_buckets(items: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {k: 0 for k in SECTOR_KEYWORDS.keys()}
    for it in items:
        blob = (it["title"] + " " + it.get("summary","")).lower()
        for sector, kws in SECTOR_KEYWORDS.items():
            if any(kw in blob for kw in kws):
                counts[sector] += 1
    # remove zeros
    return {k:v for k,v in counts.items() if v > 0}

def build_digest(items: List[Dict[str, Any]]) -> str:
    items = sorted(items, key=lambda x: x.get("published") or datetime(1970,1,1,tzinfo=TZ), reverse=True)

    themes = keyword_theme(items)
    sectors = sector_buckets(items)

    # Pick a few items as "high signal"
    top_items = items[:8]
    links_md = "\n".join([f"- [{it['source']}] [{it['title']}]({it['link']})" for it in top_items if it.get("link")])

    theme_line = " / ".join(themes[:3]) if themes else "Genel piyasa akışı"
    sector_line = ", ".join([f"{k}({v})" for k,v in sorted(sectors.items(), key=lambda x: x[1], reverse=True)[:3]]) if sectors else "Sektörel dağılım net değil"

    today_str = datetime.now(TZ).strftime("%d %b %Y")
    md = f"""### Borsa İstanbul — Günlük Piyasa Özeti ({today_str})

**Günün Teması:** *{theme_line}*  
**Öne çıkan kümeler:** {sector_line}

Bugün haber akışında **{theme_line}** başlıkları öne çıktı. Manşet yoğunluğu özellikle **{sector_line}** etrafında toplandı. Genel görünüm, haber bazında “seçici” bir fiyatlama ve sektörler arası rota değişimlerine işaret ediyor.

Haberler içinde tekrar eden ortak noktalar; politika/faiz beklentileri, şirket özelinde gelişmeler (bilanço, yatırım, sözleşme), ve küresel risk iştahındaki dalgalanmalar. Aşağıda, sinyal gücü yüksek manşetlerin kısa listesi yer alıyor.

#### Öne Çıkanlar
{links_md}
"""
    return md

def plot_candles(df: pd.DataFrame, title: str):
    fig = go.Figure(data=[go.Candlestick(
        x=df.index,
        open=df["Open"],
        high=df["High"],
        low=df["Low"],
        close=df["Close"],
        name="Price"
    )])
    fig.update_layout(
        title=title,
        xaxis_title="Date",
        yaxis_title="Price",
        height=480,
        margin=dict(l=20, r=20, t=40, b=20),
    )
    st.plotly_chart(fig, use_container_width=True)

@st.cache_data(ttl=900, show_spinner=False)
def fetch_price(ticker: str, period: str = "6mo", interval: str = "1d") -> pd.DataFrame:
    df = yf.download(ticker, period=period, interval=interval, auto_adjust=False, progress=False)
    return df

# ---------------- UI ----------------
st.set_page_config(page_title="Letta Earth — Borsa İstanbul Daily", layout="wide")

st.title("Letta Earth — Borsa İstanbul (Daily)")
st.caption("RSS → Günlük özet • Hisse grafiği • Looker Studio embed")

with st.sidebar:
    st.subheader("RSS Kaynakları")
    use_extras = st.checkbox("Ek kaynakları dahil et (CNBC-e / Doviz / Foreks)", value=True)
    only_today = st.checkbox("Sadece bugünün haberleri", value=True)
    per_feed_limit = st.slider("Feed başına max haber", 10, 60, 30, 5)

    st.divider()
    st.subheader("Hisse Grafiği")
    preset = st.selectbox("Preset", ["(Seç)"] + list(BIST_PRESETS.keys()))
    default_ticker = BIST_PRESETS.get(preset, "") if preset != "(Seç)" else "THYAO.IS"
    ticker = st.text_input("Ticker (.IS)", value=default_ticker)
    period = st.selectbox("Period", ["1mo","3mo","6mo","1y","2y"], index=2)

    st.divider()
    st.subheader("Looker Studio (iframe)")
    st.caption("Public/Embed link kullan. Çoklu rapor ekleyebilirsin.")
    looker_urls = st.text_area(
        "Her satıra bir embed URL",
        value="",
        placeholder="https://lookerstudio.google.com/embed/reporting/....\nhttps://lookerstudio.google.com/embed/reporting/...."
    )
    iframe_height = st.slider("Iframe yüksekliği", 400, 1200, 700, 50)

# Choose feeds
feeds = dict(DEFAULT_FEEDS)
if not use_extras:
    feeds = {k:v for k,v in feeds.items() if k in ["BloombergHT", "Bigpara", "Ekonomim"]}

# --- Layout
col1, col2 = st.columns([1.05, 0.95], gap="large")

with col1:
    st.subheader("📰 Piyasa Haberleri (RSS) — Günlük Özet")

    all_items: List[Dict[str, Any]] = []
    for name, url in feeds.items():
        items = fetch_feed(name, url, limit=per_feed_limit)
        all_items.extend(items)

    all_items = dedupe(all_items)
    all_items = filter_today(all_items, only_today)

    if not all_items:
        st.warning("Filtreye göre haber bulunamadı. 'Sadece bugünün haberleri' seçimini kapatıp tekrar deneyebilirsin.")
    else:
        digest_md = build_digest(all_items)
        st.markdown(digest_md)

        with st.expander("Tüm başlıklar"):
            df = pd.DataFrame([{
                "published": (it["published"].strftime("%Y-%m-%d %H:%M") if it.get("published") else ""),
                "source": it["source"],
                "title": it["title"],
                "link": it["link"],
            } for it in sorted(all_items, key=lambda x: x.get("published") or datetime(1970,1,1,tzinfo=TZ), reverse=True)])

            st.dataframe(df, use_container_width=True, hide_index=True)

with col2:
    st.subheader("📈 Hisse Grafiği Widget")

    t = (ticker or "").strip().upper()
    if not t.endswith(".IS") and t:
        st.info("BIST için genelde .IS uzantısı kullanılır (örn: THYAO.IS).")

    if t:
        try:
            dfp = fetch_price(t, period=period, interval="1d")
            if dfp is None or dfp.empty:
                st.error("Fiyat verisi gelmedi. Ticker doğru mu? (örn: ASELS.IS)")
            else:
                plot_candles(dfp, title=f"{t} — Candlestick ({period})")
        except Exception as e:
            st.error(f"Fiyat verisi alınamadı: {e}")

st.divider()
st.subheader("📊 Looker Studio Raporları")

urls = [u.strip() for u in looker_urls.splitlines() if u.strip()]
if not urls:
    st.info("Sidebar’dan Looker Studio embed link(ler)i eklediğinde burada gözükecek.")
else:
    for i, u in enumerate(urls, start=1):
        st.markdown(f"**Rapor {i}**")
        # Streamlit iframe helper
        components.iframe(u, height=iframe_height)
        st.markdown("---")
