"""
台灣三大超商「官網公開活動頁」爬蟲 — 起手式

⚠️ 範疇說明（很重要）：
這支腳本只抓「官網上公開瀏覽、不需登入」的促銷活動頁面（例如 7-11 的
「本期優惠 / 精品集點活動」列表），不會、也不應該碰各家 App 內的私有
商品目錄或即時單店價格 API —— 那些是需要登入驗證的私有介面，法律與
穩定性風險都高，不建議作為平台的主要資料來源（詳見我們前面討論的
階段0資料來源評估）。

已驗證：
- 7-11 官網首頁 (https://www.7-11.com.tw) 的選單結構，確認「本期優惠」
  對應網址為 /special/newsList.aspx，底下再分「主題活動 / 精選美味 /
  嚴選商品 / 便利生活」四個分類錨點。

尚未驗證（需要你本機執行後，用瀏覽器開發者工具比對實際 DOM 再調整）：
- newsList.aspx 實際的活動卡片 HTML 結構（class name、是否為 JS 動態載入）
- 全家 (family.com.tw) 與萊爾富 (hilife.com.tw) 對應的活動頁網址與結構
  → 因為我這邊的網路環境無法直接連到這些網域做即時比對，這部分的
    SELECTOR 我先留一個清楚的 TODO 框架，你本機跑起來後用瀏覽器「檢查」
    功能對照修正即可，通常只要改 CSS selector 就好，架構不用動。

安裝：
    pip install requests beautifulsoup4 --break-system-packages   (若在此環境跑)
    pip install requests beautifulsoup4                            (一般本機環境)

執行：
    python conbini_promo_scraper.py
"""

import csv
import json
import time
import random
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Optional

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("conbini_scraper")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9",
}

REQUEST_DELAY_RANGE = (1.5, 3.0)  # 每次請求間隔秒數，別把人家網站當靶打
TIMEOUT = 10


@dataclass
class Promo:
    store: str          # "7-11" / "全家" / "萊爾富"
    category: str       # 例如「主題活動」「精選美味」
    title: str
    url: Optional[str]
    scraped_at: str


# ---------------------------------------------------------------------------
# 各店設定：網址 + CSS selector。這是最需要你本機核對調整的部分。
# ---------------------------------------------------------------------------
STORE_CONFIGS = {
    "7-11": {
        "url": "https://www.7-11.com.tw/special/newsList.aspx",
        # TODO: 已知頁面有 #cont1(主題活動) #cont2(精選美味) #cont3(嚴選商品) #cont4(便利生活)
        # 但活動卡片本身的 class 需要你開 devtools 確認，先給一個常見猜測結構
        "item_selector": "div.newsList li, div.newsList div.item",
        "title_selector": "a, .title",
        "link_selector": "a",
    },
    "全家": {
        "url": "https://www.family.com.tw/Marketing/ActivityList",  # TODO: 需確認實際網址
        "item_selector": "div.activity-item, li.activity",
        "title_selector": "a, .title",
        "link_selector": "a",
    },
    "萊爾富": {
        "url": "https://www.hilife.com.tw/promotionList.aspx",  # TODO: 需確認實際網址
        "item_selector": "div.promo-item, li.promo",
        "title_selector": "a, .title",
        "link_selector": "a",
    },
}


def fetch_html(url: str) -> Optional[str]:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
        return resp.text
    except requests.RequestException as e:
        log.warning(f"抓取失敗 {url}: {e}")
        return None


def parse_store(store_name: str, config: dict) -> List[Promo]:
    html = fetch_html(config["url"])
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    items = soup.select(config["item_selector"])

    if not items:
        log.warning(
            f"[{store_name}] 沒抓到任何項目 — item_selector 可能需要調整。"
            f" 目前 selector: {config['item_selector']}"
        )
        return []

    results = []
    now = datetime.now().isoformat(timespec="seconds")
    for item in items:
        title_el = item.select_one(config["title_selector"])
        link_el = item.select_one(config["link_selector"])
        title = title_el.get_text(strip=True) if title_el else None
        link = link_el.get("href") if link_el else None
        if not title:
            continue
        results.append(
            Promo(
                store=store_name,
                category="",  # 若頁面有分類錨點，可依 item 所在的 section id 補上
                title=title,
                url=link,
                scraped_at=now,
            )
        )
    log.info(f"[{store_name}] 抓到 {len(results)} 筆")
    return results


def save_json(records: List[Promo], path: str = "promos.json"):
    with open(path, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in records], f, ensure_ascii=False, indent=2)
    log.info(f"已存成 {path}")


def save_csv(records: List[Promo], path: str = "promos.csv"):
    if not records:
        return
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(records[0]).keys()))
        writer.writeheader()
        for r in records:
            writer.writerow(asdict(r))
    log.info(f"已存成 {path}")


def main():
    all_records: List[Promo] = []
    for store_name, config in STORE_CONFIGS.items():
        records = parse_store(store_name, config)
        all_records.extend(records)
        time.sleep(random.uniform(*REQUEST_DELAY_RANGE))

    save_json(all_records)
    save_csv(all_records)
    log.info(f"總共抓到 {len(all_records)} 筆促銷活動資料")


if __name__ == "__main__":
    main()
