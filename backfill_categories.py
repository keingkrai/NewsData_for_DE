"""
รันครั้งเดียว — จัดหมวด (category) ให้แถวข่าวเก่าที่มีอยู่แล้วในชีต

    python backfill_categories.py          # จัดเฉพาะแถวที่คอลัมน์ category ยังว่าง
    python backfill_categories.py --all    # จัดใหม่ทุกแถว (เขียนทับค่าเดิม)

ต้องตั้ง env เหมือน main.py: GCP_SA_KEY, GOOGLE_SHEET_ID, TYPHOON_API_KEY
(ไม่มี TYPHOON_API_KEY ก็รันได้ แต่จะใช้ keyword fallback)

idempotent: รันซ้ำได้ ถ้าไม่ใส่ --all จะข้ามแถวที่มี category แล้ว
"""

import re
import sys
import time
from collections import Counter

from gspread.utils import rowcol_to_a1

from main import get_worksheet, classify_articles

WRITE_CHUNK = 200  # จำนวน cell ต่อ 1 batch_update call


def main() -> None:
    reclassify_all = "--all" in sys.argv

    ws = get_worksheet()  # ensure_header() ถูกเรียกในนี้แล้ว → มีคอลัมน์ category แน่นอน
    records = ws.get_all_values()
    if len(records) <= 1:
        print("ชีตยังไม่มีข้อมูลข่าว — ไม่มีอะไรให้ทำ")
        return

    header = records[0]
    idx = {name: i for i, name in enumerate(header)}
    cat_col = idx["category"]
    title_col = idx.get("title", 0)
    url_col = idx.get("url", 1)
    summary_col = idx.get("summary", 4)

    def cell(row, col):
        return row[col] if len(row) > col else ""

    targets = []  # (row_number_1based, article_dict)
    for row_number, row in enumerate(records[1:], start=2):
        if not reclassify_all and cell(row, cat_col).strip():
            continue
        targets.append(
            (
                row_number,
                {
                    "title": cell(row, title_col),
                    "link": cell(row, url_col),
                    "summary": cell(row, summary_col),
                    "source": "",
                },
            )
        )

    if not targets:
        print("ไม่มีแถวที่ต้องจัดหมวด (ทุกแถวมี category แล้ว)")
        return

    print(f"กำลังจัดหมวด {len(targets)} แถว...")
    categories = classify_articles([article for _, article in targets])

    col_letter = re.sub(r"\d+", "", rowcol_to_a1(1, cat_col + 1))
    updates = [
        {"range": f"{col_letter}{row_number}", "values": [[category]]}
        for (row_number, _), category in zip(targets, categories)
    ]

    for i in range(0, len(updates), WRITE_CHUNK):
        if i:
            time.sleep(1)
        ws.batch_update(updates[i:i + WRITE_CHUNK], value_input_option="RAW")

    print("เสร็จแล้ว:", dict(Counter(categories)))


if __name__ == "__main__":
    main()
