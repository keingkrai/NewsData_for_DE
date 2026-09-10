"""
วิเคราะห์ว่าทำไมข่าวเป็น uncategorized หมด — รัน local (ใช้ .env)

    python diagnose.py

ไฟล์นี้ไม่แก้ชีต แค่อ่านมาตรวจ
"""
import os

os.environ.setdefault("CLASSIFY_DEBUG", "1")

import main

print("=" * 60)
print("1) TYPHOON_API_KEY มีค่าไหม :", bool(main.TYPHOON_API_KEY),
      f"(ขึ้นต้น {main.TYPHOON_API_KEY[:6]}... )" if main.TYPHOON_API_KEY else "")
print("   model                   :", main.TYPHOON_MODEL)
print("   endpoint                :", main.TYPHOON_ENDPOINT)

print("\n2) ยิง Typhoon ตรง ๆ 1 batch (3 ข่าวตัวอย่าง)")
sample = [
    {"title": "ตลาดสกินแคร์เอเชียโต 8% ปี 2027", "summary": ""},
    {"title": "นักวิจัยพบสารสกัดเปปไทด์ใหม่ลดริ้วรอย", "summary": ""},
    {"title": "ราคาน้ำมันปรับตัวขึ้น", "summary": ""},
]
try:
    print("   ->", main._typhoon_classify_batch(sample))
except Exception as e:
    print("   ล้มเหลว:", repr(e))

print("\n3) อ่านชีตจริง")
try:
    ws = main.get_worksheet()
    records = ws.get_all_values()
except Exception as e:
    print(f"   ข้ามขั้นตอนนี้ — เชื่อมชีตไม่ได้ ({e})")
    print("   (local .env ไม่มี GCP_SA_KEY/GOOGLE_SHEET_ID — ปกติ ใช้ผ่าน GitHub Actions)")
    raise SystemExit
print("   header        :", records[0] if records else "(ว่าง)")
print("   จำนวนแถวข่าว   :", max(0, len(records) - 1))
for row in records[1:4]:
    print("   ตัวอย่างแถว    :", row)

print("\n4) ลองจัดหมวด 15 แถวแรกของชีต")
header = records[0]
idx = {n: i for i, n in enumerate(header)}
tcol, scol = idx.get("title", 0), idx.get("summary", 4)


def cell(r, c):
    return r[c] if len(r) > c else ""


arts = [
    {"title": cell(r, tcol), "summary": cell(r, scol), "link": "", "source": ""}
    for r in records[1:16]
]
cats = main.classify_articles(arts)
for a, c in zip(arts, cats):
    print(f"   {c:<16} | {a['title'][:60]}")
print("=" * 60)
