"""
7-11 小七食堂商品目錄擷取（正式版）

資料源：https://www.7-11.com.tw/freshfoods/read_food_xml.aspx?={分類編號}
這是一支乾淨的 XML API，不用處理 JS 渲染，也不用 headless browser。

分類編號是 7-11 網站內部自己用的，跟資料夾名稱對不上，是我們實際探測
0~40 才摸出來的（詳見 discover_categories.py 的探測結果）。這裡刻意把
7-11 自己的品牌命名（Ohlala、御料小館、星級饗宴...）轉成「跨店通用」
的分類名稱，這樣未來加全家、萊爾富的商品時可以套同一組分類，不用
因為換店家又重新設計一套分類系統。
"""

import re
import time
import logging
from dataclasses import dataclass
from typing import List, Optional

import requests

log = logging.getLogger("product_catalog")

BASE_URL = "https://www.7-11.com.tw/freshfoods/read_food_xml.aspx?={}"
IMAGE_BASE_URL = "https://www.7-11.com.tw/freshfoods/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

# 編號 -> 跨店通用分類名稱。8、9、11、14、20、23、24+ 是空的或跟其他編號
# 重複，不列入。這份清單之後如果發現分類不準，只要改這裡就好，
# 不用動下面的擷取邏輯。
CATEGORY_MAP = {
    0: "飯糰/壽司",
    1: "沙拉輕食",
    2: "便當",
    3: "熟食小點",
    4: "便當",
    5: "麵食",
    6: "關東煮",
    7: "熱狗",
    10: "麵包甜點",
    12: "關東煮",
    13: "調理即食",
    15: "三明治/漢堡",
    16: "麵食",
    17: "沙拉輕食",
    18: "便當",
    19: "麵包甜點",
    21: "冰品",
    22: "便當",
}

ITEM_BLOCK = re.compile(r"<Item[^>]*>(.*?)</Item>", re.DOTALL)
FIELD = lambda tag: re.compile(rf"<{tag}>(.*?)</{tag}>", re.DOTALL)

FIELDS = {
    "name": FIELD("name"),
    "price": FIELD("price"),
    "kcal": FIELD("kcal"),
    "image": FIELD("image"),
    "special_sale": FIELD("special_sale"),
    "new": FIELD("new"),
    "content": FIELD("content"),
}


@dataclass
class ProductItem:
    name: str
    category: str
    price: Optional[int]
    kcal: Optional[int]
    image_url: Optional[str]
    is_new: bool
    is_special_sale: bool
    description: str
    source_url: str


def parse_category_xml(xml_text: str, category_label: str, source_url: str) -> List[ProductItem]:
    items = []
    for block in ITEM_BLOCK.finditer(xml_text):
        content = block.group(1)
        values = {}
        for key, pattern in FIELDS.items():
            m = pattern.search(content)
            values[key] = m.group(1).strip() if m else ""

        if not values["name"]:
            continue

        price = None
        price_match = re.search(r"\d+", values["price"])
        if price_match:
            price = int(price_match.group())

        kcal = int(values["kcal"]) if values["kcal"].isdigit() else None

        image_url = None
        if values["image"]:
            image_url = IMAGE_BASE_URL + values["image"]

        items.append(
            ProductItem(
                name=values["name"],
                category=category_label,
                price=price,
                kcal=kcal,
                image_url=image_url,
                is_new=(values["new"].lower() == "true"),
                is_special_sale=(values["special_sale"].lower() == "true"),
                description=values["content"],
                source_url=source_url,
            )
        )
    return items


def fetch_all_categories() -> List[ProductItem]:
    all_items: List[ProductItem] = []
    for category_id, label in CATEGORY_MAP.items():
        url = BASE_URL.format(category_id)
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            resp.raise_for_status()
            resp.encoding = "utf-8"
            items = parse_category_xml(resp.text, label, url)
            log.info(f"分類 {label}（編號{category_id}）：{len(items)} 項")
            all_items.extend(items)
        except requests.RequestException as e:
            log.warning(f"編號 {category_id} 抓取失敗：{e}")
        time.sleep(0.5)  # 別把人家網站當靶打
    return all_items


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    items = fetch_all_categories()
    print(f"\n總共抓到 {len(items)} 項商品")
    for it in items[:5]:
        print(f"  [{it.category}] {it.name} - {it.price}元 - {it.image_url}")
