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

Setup ที่ต้องทำครั้งเดียว (ฝั่งคุณ):
  1. สร้าง Google Cloud Project > เปิดใช้งาน Google Sheets API + Google Drive API
  2. สร้าง Service Account > สร้างและดาวน์โหลด JSON key
  3. สร้าง Google Sheet เปล่า 1 ไฟล์ ไม่ต้องใส่หัวคอลัมน์เอง (สคริปต์จะใส่ให้
     อัตโนมัติถ้าชีตว่าง)
  4. แชร์ Google Sheet นั้นให้ service account (อีเมลอยู่ใน JSON key ลงท้าย
     ด้วย @<project-id>.iam.gserviceaccount.com) สิทธิ์ Editor
  5. แชร์ Google Sheet เดียวกันนี้ให้ DE ทีม (สิทธิ์ Viewer ก็พอ) เพื่อให้เขา
     ต่อ Power BI ผ่าน native Google Sheets connector ได้เลย
  6. เอา JSON key ทั้งไฟล์ (ทั้งก้อน) ไปใส่เป็น GitHub Secret ชื่อ GCP_SA_KEY
     (Settings > Secrets and variables > Actions > New repository secret)
  7. เอา Google Sheet ID (ส่วนที่อยู่ใน URL ระหว่าง /d/ กับ /edit) ไปใส่เป็น
     GitHub Secret ชื่อ GOOGLE_SHEET_ID

ติดตั้ง (สำหรับรัน local ทดสอบ):
    pip install feedparser requests gspread google-auth
"""

import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlencode

import feedparser
import gspread
import requests
from google.oauth2.service_account import Credentials

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

SHEET_HEADER = ["title", "url", "source", "published_at", "summary", "fetched_at_utc"]

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

    sh = client.open_by_key(sheet_id)
    ws = sh.sheet1

    values = ws.get_all_values()
    if not values:
        ws.append_row(SHEET_HEADER)

    return ws


def get_existing_links(ws) -> set:
    """อ่าน URL ที่มีอยู่แล้วในชีต ใช้แทน SQLite dedup เพราะ GitHub Actions
    runner ไม่มี state ข้ามรอบ"""
    records = ws.get_all_values()
    if len(records) <= 1:
        return set()
    header = records[0]
    url_col = header.index("url") if "url" in header else 1
    return {row[url_col] for row in records[1:] if len(row) > url_col}


def append_articles(ws, articles: list) -> int:
    existing = get_existing_links(ws)
    rows = []
    for a in articles:
        link = a.get("link", "")
        if not link or link in existing:
            continue
        rows.append(
            [
                a["title"],
                link,
                a["source"],
                a.get("published", ""),
                a.get("summary", ""),
                datetime.now(timezone.utc).isoformat(),
            ]
        )
        existing.add(link)  # กันข่าวซ้ำภายในรอบเดียวกันด้วย (เช่น RSS 2 แหล่งได้ข่าวเดียวกัน)
    if rows:
        ws.append_rows(rows, value_input_option="RAW")
    return len(rows)


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