"""
Cosmetic Industry News Aggregator — GitHub Actions + Google Sheets Edition
============================================================================
ออกแบบให้รันบน GitHub Actions (scheduled workflow) แล้วเขียนผลลัพธ์ลง
Google Sheets โดยตรง เพื่อให้ DE ทีมต่อ Power BI (Get Data > Google Sheets)
ได้เลย โดยไม่ต้องมีสิทธิ์ SharePoint/OneDrive

เนื่องจาก GitHub Actions runner เป็นเครื่อง ephemeral (รันจบแล้วหายไปทั้งเครื่อง
ไม่มี disk ที่จำสถานะข้ามรอบ) จึงใช้ตัว Google Sheet เองเป็นแหล่งเก็บสถานะ
(แทน SQLite แบบเดิม) — ทุกรอบจะอ่าน URL ที่มีอยู่แล้วในชีตก่อน แล้วเติมเฉพาะ
ข่าวใหม่ที่ยังไม่เคยมี

การจัดหมวดหมู่ (คอลัมน์ category):
  แต่ละข่าวจะถูกจัดเข้า 1 ใน 4 หมวด
    - direct_customer  : ข่าวเจาะจงรายลูกค้า (จับด้วยชื่อ/แบรนด์ใน customers.py)
    - channel_retailer : ข่าวช่องทางจำหน่าย / รีเทลเลอร์
    - trend_innovation : ข่าวนวัตกรรมและสารสกัดใหม่
    - industry_market  : ข่าวภาพรวมอุตสาหกรรม / ตลาดโลก
  ข่าวที่ไม่เข้าหมวด / จัดไม่สำเร็จ → "uncategorized" (ยังบันทึกลงชีต)
  ขั้นตอน: (1) จับชื่อลูกค้า/รีเทลเลอร์แบบ deterministic ก่อน
           (2) ที่เหลือส่งให้ Typhoon (opentyphoon.ai) จัดหมวด — ไม่มี key ก็ fallback
           เป็น keyword rules

Setup ที่ต้องทำครั้งเดียว (ฝั่งคุณ):
  1. สร้าง Google Cloud Project > เปิดใช้งาน Google Sheets API + Google Drive API
  2. สร้าง Service Account > สร้างและดาวน์โหลด JSON key
  3. สร้าง Google Sheet เปล่า 1 ไฟล์ ไม่ต้องใส่หัวคอลัมน์เอง (สคริปต์จะใส่ให้
     อัตโนมัติถ้าชีตว่าง / จะเติมคอลัมน์ category ให้ถ้าชีตเดิมยังไม่มี)
  4. แชร์ Google Sheet นั้นให้ service account (อีเมลอยู่ใน JSON key ลงท้าย
     ด้วย @<project-id>.iam.gserviceaccount.com) สิทธิ์ Editor
  5. แชร์ Google Sheet เดียวกันนี้ให้ DE ทีม (สิทธิ์ Viewer ก็พอ) เพื่อให้เขา
     ต่อ Power BI ผ่าน native Google Sheets connector ได้เลย
  6. เอา JSON key ทั้งไฟล์ (ทั้งก้อน) ไปใส่เป็น GitHub Secret ชื่อ GCP_SA_KEY
     (Settings > Secrets and variables > Actions > New repository secret)
  7. เอา Google Sheet ID (ส่วนที่อยู่ใน URL ระหว่าง /d/ กับ /edit) ไปใส่เป็น
     GitHub Secret ชื่อ GOOGLE_SHEET_ID
  8. สมัคร opentyphoon.ai > Playground > API Keys > สร้าง key แล้วใส่เป็น
     GitHub Secret ชื่อ TYPHOON_API_KEY (ถ้าไม่ใส่ ระบบจะจัดหมวดแบบ keyword แทน)

ติดตั้ง (สำหรับรัน local ทดสอบ):
    pip install feedparser requests gspread google-auth
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

import feedparser
import gspread
import requests
from google.oauth2.service_account import Credentials

from customers import CUSTOMER_TH, CUSTOMER_EN, RETAILER_TH, RETAILER_EN

# กัน UnicodeEncodeError เวลารัน local บน Windows (console เป็น cp874)
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def _load_dotenv(path: str = ".env") -> None:
    """โหลดไฟล์ .env สำหรับรัน local (ไม่ทับค่า env ที่ตั้งไว้แล้ว)
    บน GitHub Actions ไม่มีไฟล์นี้ → ไม่ทำอะไร"""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_dotenv()

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

KEYWORDS = [
    "เครื่องสำอาง", "ความงาม", "สกินแคร์", "ผิวพรรณ", "บิวตี้", "น้ำหอม",
    "cosmetic", "cosmetics", "skincare", "beauty industry", "makeup",
    "personal care", "fragrance", "k-beauty", "clean beauty", "beauty brand",
]


def google_news_rss_url(query: str, hl: str = "th", gl: str = "TH", ceid: str = "TH:th") -> str:
    params = urlencode({"q": query, "hl": hl, "gl": gl, "ceid": ceid})
    return f"https://news.google.com/rss/search?{params}"


RSS_FEEDS = [
    google_news_rss_url("เครื่องสำอาง OR ความงาม OR สกินแคร์"),
    google_news_rss_url("cosmetics industry OR beauty brand OR skincare", hl="en-US", gl="US", ceid="US:en"),
]

NEWSDATA_API_KEY = os.environ.get("NEWSDATA_API_KEY", "")
NEWSDATA_ENDPOINT = "https://newsdata.io/api/1/news"

SHEET_HEADER = ["title", "url", "source", "published_at", "summary", "fetched_at_utc", "category"]

# --- การจัดหมวด ---
TYPHOON_API_KEY = os.environ.get("TYPHOON_API_KEY", "")
TYPHOON_ENDPOINT = "https://api.opentyphoon.ai/v1/chat/completions"
TYPHOON_MODEL = os.environ.get("TYPHOON_MODEL", "typhoon-v2.5-30b-a3b-instruct")
CLASSIFY_BATCH_SIZE = 10

# หมวดที่ให้โมเดล/keyword เลือก (หมวด direct_customer จับด้วยรายชื่อก่อนหน้านี้แล้ว)
MODEL_CATEGORIES = {"channel_retailer", "trend_innovation", "industry_market", "uncategorized"}

CLASSIFY_SYSTEM_PROMPT = (
    "คุณเป็นผู้ช่วยจัดหมวดหมู่ข่าวสำหรับบริษัทผู้ผลิตเครื่องสำอาง / personal care\n"
    "จัดข่าวแต่ละชิ้นเข้า 1 หมวด โดยตอบเป็น key ภาษาอังกฤษเท่านั้น:\n\n"
    "- channel_retailer : ช่องทางจำหน่าย ร้านค้าปลีก ดรักสโตร์ โมเดิร์นเทรด อีคอมเมิร์ซ "
    "มาร์เก็ตเพลส การกระจายสินค้า การเปิด/ปิดสาขา\n"
    "- trend_innovation : นวัตกรรม สารสกัด/สารออกฤทธิ์ใหม่ เทคโนโลยีการผลิต งานวิจัย "
    "สิทธิบัตร เทรนด์ความงามใหม่ที่เป็นโอกาสทางธุรกิจ\n"
    "- industry_market : ภาพรวมอุตสาหกรรมเครื่องสำอาง/ความงาม ขนาดและการเติบโตของตลาด "
    "การควบรวมกิจการ กฎระเบียบ เศรษฐกิจมหภาคที่กระทบทั้งอุตสาหกรรม\n"
    "- uncategorized : ไม่ตรงหมวดใดเลย ข่าวขยะ ข่าวเตือนภัย/สินค้าปลอม หรือไม่เกี่ยวกับ"
    "อุตสาหกรรมความงาม\n\n"
    'ตอบกลับเป็น JSON array เท่านั้น รูปแบบ: [{"id": <number>, "category": "<key>"}] '
    "ห้ามมีข้อความอื่นนอก JSON และต้องมีครบทุก id ที่ได้รับ"
)

# keyword fallback (ใช้เมื่อไม่มี TYPHOON_API_KEY หรือเรียก API ไม่สำเร็จ)
_KW_CHANNEL = [
    "ร้านค้าปลีก", "ช่องทางจำหน่าย", "ช่องทางขาย", "โมเดิร์นเทรด", "อีคอมเมิร์ซ",
    "e-commerce", "ecommerce", "marketplace", "มาร์เก็ตเพลส", "ดรักสโตร์", "drugstore",
    "ค้าปลีก", "หน้าร้าน", "ขายออนไลน์", "retailer", "retail chain", "distribution",
]
_KW_TREND = [
    "สารสกัด", "สารออกฤทธิ์", "นวัตกรรม", "งานวิจัย", "สิทธิบัตร", "สูตรใหม่",
    "active ingredient", "peptide", "เปปไทด์", "ไมโครไบโอม", "microbiome",
    "biotech", "ไบโอเทค", "เทคโนโลยีการผลิต", "innovation", "new ingredient",
    "clinical study", "patent",
]
_KW_MARKET = [
    "มูลค่าตลาด", "ส่วนแบ่งตลาด", "ขนาดตลาด", "การเติบโตของตลาด", "แนวโน้มตลาด",
    "ตลาดเครื่องสำอาง", "ตลาดความงาม", "ตลาดสกินแคร์", "ตลาดบิวตี้", "ตลาดเครื่องสำอางไทย",
    "ภาพรวมอุตสาหกรรม", "อุตสาหกรรมความงาม", "อุตสาหกรรมเครื่องสำอาง",
    "market size", "market share", "market growth", "cagr", "forecast",
    "ควบรวมกิจการ", "เข้าซื้อกิจการ", "m&a", "acquisition", "merger",
    "ส่งออก", "นำเข้า", "export", "import", "regulation", "กฎระเบียบ", "อย.",
]

# ---------------------------------------------------------------------------
# GOOGLE SHEETS
# ---------------------------------------------------------------------------

def get_worksheet():
    """เชื่อมต่อ Google Sheets โดยใช้ Service Account credential จาก env var"""
    creds_json = os.environ["GCP_SA_KEY"]
    sheet_id = os.environ["GOOGLE_SHEET_ID"]

    creds_dict = json.loads(creds_json)
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)

    ws = client.open_by_key(sheet_id).sheet1
    ensure_header(ws)
    return ws


def ensure_header(ws) -> None:
    """ใส่หัวคอลัมน์ถ้าชีตว่าง / เติมคอลัมน์ที่ยังไม่มี (เช่น category สำหรับชีตเดิม)
    เติมต่อท้ายเสมอ ไม่ขยับข้อมูลเดิม"""
    values = ws.get_all_values()
    if not values:
        ws.append_row(SHEET_HEADER)
        return
    header = values[0]
    next_col = len(header) + 1
    for col in SHEET_HEADER:
        if col not in header:
            ws.update_cell(1, next_col, col)
            next_col += 1


def append_articles(ws, articles: list) -> int:
    """dedup ด้วย URL → จัดหมวด → เขียนแถวใหม่ (จัดคอลัมน์ให้ตรง header จริงของชีต)"""
    records = ws.get_all_values()
    header = records[0] if records else list(SHEET_HEADER)
    url_col = header.index("url") if "url" in header else 1
    existing = {row[url_col] for row in records[1:] if len(row) > url_col}

    new_articles = []
    for a in articles:
        link = a.get("link", "")
        if not link or link in existing:
            continue
        new_articles.append(a)
        existing.add(link)  # กันข่าวซ้ำภายในรอบเดียวกันด้วย (เช่น RSS 2 แหล่งได้ข่าวเดียวกัน)

    if not new_articles:
        return 0

    categories = classify_articles(new_articles)
    now_iso = datetime.now(timezone.utc).isoformat()

    rows = []
    for a, category in zip(new_articles, categories):
        values = {
            "title": a.get("title", ""),
            "url": a.get("link", ""),
            "source": a.get("source", ""),
            "published_at": a.get("published", ""),
            "summary": a.get("summary", ""),
            "fetched_at_utc": now_iso,
            "category": category,
        }
        rows.append([values.get(col, "") for col in header])

    ws.append_rows(rows, value_input_option="RAW")
    return len(rows)


# ---------------------------------------------------------------------------
# CLASSIFY
# ---------------------------------------------------------------------------

def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _match_any(text: str, thai_terms: list, ascii_terms: list) -> bool:
    """text ต้อง normalize (lowercase) มาแล้ว
    - ไทย: substring
    - อังกฤษ: ขอบคำ (ไม่มี a-z0-9 ประกบหน้า/หลัง)"""
    for term in thai_terms:
        if term and term.lower() in text:
            return True
    for term in ascii_terms:
        term = term.lower().strip()
        if term and re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text):
            return True
    return False


def _classify_by_keyword(article: dict) -> str:
    text = _norm(f"{article.get('title', '')} {article.get('summary', '')}")
    if any(k in text for k in _KW_CHANNEL):
        return "channel_retailer"
    if any(k in text for k in _KW_TREND):
        return "trend_innovation"
    if any(k in text for k in _KW_MARKET):
        return "industry_market"
    return "uncategorized"


CLASSIFY_DEBUG = os.environ.get("CLASSIFY_DEBUG", "").lower() in ("1", "true", "yes")

ALL_CATEGORIES = ("direct_customer", "channel_retailer", "trend_innovation", "industry_market", "uncategorized")


def _canon_category(raw: str) -> str:
    """map คำตอบของโมเดลให้เป็น key มาตรฐาน (โมเดลอาจตอบ Thai / เว้นวรรค / ขีดกลาง)"""
    r = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    for key in ALL_CATEGORIES:
        if key in r:
            return key
    if "ลูกค้า" in r:
        return "direct_customer"
    if "ช่องทาง" in r or "รีเทล" in r or "ค้าปลีก" in r or "retail" in r or "channel" in r:
        return "channel_retailer"
    if "นวัตกรรม" in r or "สารสกัด" in r or "เทรนด์" in r or "trend" in r or "innovation" in r:
        return "trend_innovation"
    if "อุตสาหกรรม" in r or "ตลาด" in r or "market" in r or "industry" in r:
        return "industry_market"
    return ""


def _extract_json_array(s: str):
    m = re.search(r"\[\s*\{.*\}\s*\]", s, re.DOTALL)  # จาก [{ ตัวแรก ถึง }] ตัวสุดท้าย
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    start, end = s.find("["), s.rfind("]")
    if 0 <= start < end:
        try:
            return json.loads(s[start:end + 1])
        except json.JSONDecodeError:
            pass
    return None


def _typhoon_classify_batch(batch: list) -> list:
    payload = {
        "model": TYPHOON_MODEL,
        "messages": [
            {"role": "system", "content": CLASSIFY_SYSTEM_PROMPT},
            {"role": "user", "content": "จัดหมวดข่าวต่อไปนี้:\n" + json.dumps(
                [
                    {"id": i, "title": a.get("title", ""), "summary": (a.get("summary") or "")[:200]}
                    for i, a in enumerate(batch)
                ],
                ensure_ascii=False,
            )},
        ],
        "temperature": 0.2,
        "max_tokens": 1500,
        "repetition_penalty": 1.05,
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {TYPHOON_API_KEY}", "Content-Type": "application/json"}

    last_err = None
    for attempt in range(3):
        try:
            resp = requests.post(TYPHOON_ENDPOINT, json=payload, headers=headers, timeout=90)
            if resp.status_code in (429, 500, 502, 503, 504):
                last_err = f"HTTP {resp.status_code}"
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            if CLASSIFY_DEBUG:
                print(f"  [debug] Typhoon ตอบ: {content[:400]!r}")
            parsed = _extract_json_array(content)
            if not parsed:
                raise ValueError(f"อ่าน JSON ไม่ได้ — คำตอบขึ้นต้น: {content[:200]!r}")

            by_id = {}
            for item in parsed:
                try:
                    by_id[int(item["id"])] = _canon_category(item.get("category", ""))
                except (KeyError, ValueError, TypeError):
                    continue

            out = []
            for i, a in enumerate(batch):
                cat = by_id.get(i, "")
                out.append(cat if cat in MODEL_CATEGORIES else _classify_by_keyword(a))
            return out
        except (requests.RequestException, ValueError, KeyError) as e:
            last_err = str(e)
            time.sleep(2 ** attempt)

    print(f"  [เตือน] Typhoon ล้มเหลว ({last_err}) — ใช้ keyword fallback {len(batch)} ข่าว")
    return [_classify_by_keyword(a) for a in batch]


def _classify_with_model(articles: list) -> list:
    if not articles:
        return []
    if not TYPHOON_API_KEY:
        print(f"[เตือน] ไม่พบ TYPHOON_API_KEY — จัดหมวด {len(articles)} ข่าวด้วย keyword ล้วน (แม่นยำต่ำ)")
        return [_classify_by_keyword(a) for a in articles]

    out = []
    for i in range(0, len(articles), CLASSIFY_BATCH_SIZE):
        if i:
            time.sleep(0.5)  # เผื่อ rate limit (opentyphoon free tier = 5 req/s, 200 req/m)
        out.extend(_typhoon_classify_batch(articles[i:i + CLASSIFY_BATCH_SIZE]))
    return out


def classify_articles(articles: list) -> list:
    """คืน list ของ category key เรียงตรงกับ articles
    ขั้นตอน: จับชื่อลูกค้า/รีเทลเลอร์ก่อน → ที่เหลือส่งให้โมเดล/keyword"""
    results = [None] * len(articles)
    pending, pending_idx = [], []

    for i, a in enumerate(articles):
        text = _norm(f"{a.get('title', '')} {a.get('summary', '')}")
        if _match_any(text, CUSTOMER_TH, CUSTOMER_EN):
            results[i] = "direct_customer"
        elif _match_any(text, RETAILER_TH, RETAILER_EN):
            results[i] = "channel_retailer"
        else:
            pending.append(a)
            pending_idx.append(i)

    for idx, cat in zip(pending_idx, _classify_with_model(pending)):
        results[idx] = cat

    from collections import Counter
    dist = ", ".join(f"{k}={v}" for k, v in sorted(Counter(results).items()))
    matched = len(articles) - len(pending)
    print(f"จัดหมวด {len(articles)} ข่าว (จับชื่อลูกค้า/รีเทลเลอร์ได้ {matched}) -> {dist}")

    return results


# ---------------------------------------------------------------------------
# FILTER
# ---------------------------------------------------------------------------

def is_relevant(text: str) -> bool:
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in KEYWORDS)


def strip_html(text: str) -> str:
    return re.sub(r"<[^<]+?>", "", text or "").strip()


# ---------------------------------------------------------------------------
# FETCHERS
# ---------------------------------------------------------------------------

def fetch_rss() -> list:
    articles = []
    for url in RSS_FEEDS:
        feed = feedparser.parse(url)
        feed_title = feed.feed.get("title", url) if hasattr(feed, "feed") else url
        for entry in feed.entries:
            title = entry.get("title", "")
            summary = strip_html(entry.get("summary", ""))
            if is_relevant(f"{title} {summary}"):
                articles.append(
                    {
                        "title": title,
                        "link": entry.get("link", ""),
                        "source": feed_title,
                        "published": entry.get("published", ""),
                        "summary": summary[:300],
                    }
                )
    return articles


def fetch_newsdata(query: str = "cosmetics OR skincare OR beauty industry", language: str = "en") -> list:
    if not NEWSDATA_API_KEY:
        return []
    params = {"apikey": NEWSDATA_API_KEY, "q": query, "language": language}
    resp = requests.get(NEWSDATA_ENDPOINT, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    articles = []
    for item in data.get("results", []):
        articles.append(
            {
                "title": item.get("title", ""),
                "link": item.get("link", ""),
                "source": item.get("source_id", "newsdata"),
                "published": item.get("pubDate", ""),
                "summary": (item.get("description") or "")[:300],
            }
        )
    return articles


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main() -> None:
    ws = get_worksheet()
    all_articles = fetch_rss() + fetch_newsdata()
    new_count = append_articles(ws, all_articles)
    print(f"ดึงข่าวทั้งหมด {len(all_articles)} รายการ | เพิ่มข่าวใหม่ลงชีต {new_count} รายการ")


if __name__ == "__main__":
    main()
