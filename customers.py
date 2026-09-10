"""
รายชื่อลูกค้า / แบรนด์ สำหรับจับข่าวหมวด direct_customer และ channel_retailer
(ที่มา: customer master ~400 บรรทัด → ทำความสะอาดใน customers_merged.md)

ใช้ยังไง:
  main.classify_articles() จะ normalize ข้อความข่าว (title + summary) เป็น lowercase
  แล้วเช็คว่ามีคำในลิสต์นี้โผล่หรือไม่
    - *_TH : เช็คแบบ substring (ภาษาไทยไม่มีขอบคำ)
    - *_EN : เช็คแบบขอบคำ (word boundary) กันชนคำภาษาอังกฤษทั่วไป

แก้ไข/เพิ่มได้อิสระ — ยิ่งลิสต์ครบ หมวด direct_customer / channel_retailer ยิ่งแม่น
คำที่ยังไม่ยืนยัน (🔹) หรือกว้างเกินไปถูกตัดออกเพื่อลด false positive
"""

# ---------------------------------------------------------------------------
# หมวด 1 — ลูกค้า/เจ้าของแบรนด์ (Direct Customer)
# ---------------------------------------------------------------------------

CUSTOMER_TH = [
    # เครือสหพัฒน์ / ผู้ผลิต–เจ้าของแบรนด์รายใหญ่
    "สหพัฒน์", "เบทเตอร์เวย์", "มิสทีน", "ไทยวาโก้", "วาโก้",
    "ไอ.ซี.ซี.", "โอซีซี", "เอส แอนด์ เจ", "เอสแอนด์เจ",
    "โอสถสภา", "โอสถอินเตอร์แลบ", "เบบี้มายด์", "ทเวลฟ์พลัส",
    "ศรีจันทร์", "คิวเพรส", "เดนทิสเต้", "ออกซีเคียว", "สมูทอี",
    "สยามเฮลท์", "โรจูคิส", "มิซึฮาดะ", "มิซึมิ", "โบมิ",
    "ฟีมิคส์", "ดีเซ้ย์", "เซนส์ยัง", "เจ้านาง", "นิติพล",
    "เลิฟโพชั่น", "เท็นโจ", "โทฟู สกินแคร์", "สกินซิสต้า",
    "เมคอัพเทคนิค", "สุรีย์พร", "เวอรีน่า", "เคลียร์โนส",
    "โยโกะ", "ชวาร์สคอฟ", "บิวตี้บุฟเฟ่ต์", "บิวตี้ คอมมูนิตี้",
    "บิวตี้ คอทเทจ", "ท้อปเทร็นด์ แมนูแฟคเจอริ่ง", "ยามาฮัทสึ",
    "มอนดามิน", "แจ๊บส์", "ดร.จิล",
]

CUSTOMER_EN = [
    "mistine", "faris", "wacoal", "s&j",
    "osotspa", "12plus", "babi mild",
    "cute press", "covermark", "srichand",
    "dentiste", "oxe'cure", "oxecure", "smooth e", "smooth-e", "smoothe",
    "rojukiss", "sdanso", "baby bright",
    "mizumi", "bomi", "deesay", "senyang",
    "dr.jill", "dr jill", "drjill", "4u2", "mti",
    "arty professional", "schwarzkopf", "syoss", "gliss",
    "beauty buffet", "beauty cottage", "verena",
    "clearnose", "clear nose", "skinsista",
    "colgate", "palmolive", "systema", "kodomo", "shokubutsu",
    "mondahmin",
    # ต่างประเทศ (ลูกค้างาน OEM/ODM)
    "the body shop", "kose", "coty", "e.l.f. cosmetics", "e.l.f. beauty",
    "pz cussons", "mcobeauty", "nutrimetics", "living nature", "meiyume",
]

# ---------------------------------------------------------------------------
# หมวด 2 — ช่องทางจำหน่าย / รีเทลเลอร์ / มาร์เก็ตเพลส (Channel & Retailer)
# ---------------------------------------------------------------------------

RETAILER_TH = [
    "วัตสัน", "บู๊ทส์", "โลตัส", "บิ๊กซี", "ลาซาด้า", "ช้อปปี้",
    "เดอะมอลล์", "สยามพารากอน", "เอ็มโพเรียม", "มูจิ", "ลอว์สัน",
    "ซูรูฮะ", "อีฟแอนด์บอย", "อีฟ แอนด์ บอย", "คอนวี่", "บิวเทรี่ยม",
    "ดองกิ", "เบอร์ลี่ ยุคเกอร์", "ทเวนตี้โฟร์ ช้อปปิ้ง",
]

RETAILER_EN = [
    "watsons", "boots", "lotus's", "big c", "lazada", "shopee",
    "the mall", "siam paragon", "emporium", "muji", "ryohin keikaku",
    "lawson", "tsuruha", "eveandboy", "eve and boy", "konvy", "beautrium",
    "don don donki", "donki", "don quijote", "pan pacific", "bjc",
    "mr. diy", "24 shopping", "tiktok shop", "ascend commerce",
    "rose pharmacy", "pharmacity",
]
