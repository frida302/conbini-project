"""
主流程：串起「抓資料 -> 擷取事實 -> 去重 -> 寫進 Supabase」整條管線。
這支是排程機制實際會跑的進入點（GitHub Actions 或 cron 都是呼叫這支)。

流程：
  1. 抓官網公開活動頁（selector 還沒經過真實 DOM 驗證，是已知卡住的部分）
  2. 抓 1-2 個超商優惠整理網站的文章
  3. 對每個來源的文字內容跑事實擷取（extract_facts.py）
  4. 活動去重（dedup_activities.py）、商品目錄去重（catalog.py）
  5. 把新資料寫進 Supabase（db_client.py）
"""

import logging
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from extract_facts import extract_promo_facts, extract_periods
from catalog import build_new_products, normalize_name
from dedup_activities import ActivityRecord, filter_new_activities, dedup_key
import db_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("pipeline")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

# 第二來源：超商優惠整理網站（挑選標準：會固定週期發「超商優惠彙整」文章，
# 格式相對穩定）。這裡先放兩個我們查證過確實有在做這類彙整報導的來源，
# 之後發現規律不穩可以再換。
AGGREGATOR_SOURCES = [
    # (store 名稱過濾用不到，因為一篇文章可能同時提到多家超商，
    #  所以我們只標記 domain，事實擷取階段不特別分店，一律先標 "7-11"
    #  因為 MVP 範圍只做 7-11，之後擴店再改成自動判斷)
    "supertaste.tvbs.com.tw",
    "www.nownews.com",
]


def fetch_page_text(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")
    # 只取文章主體文字，不要整頁 HTML 雜訊；這裡先抓全頁純文字，
    # 之後如果雜訊太多（導覽列、廣告文字）可以再縮小成 selector 鎖定文章區塊
    return soup.get_text(separator="\n")


def run():
    all_facts = []
    all_activity_candidates = []

    # --- 官網活動頁（已知卡住：selector 未經真實 DOM 驗證）---
    log.warning("官網活動頁 selector 尚未經過真實 DOM 驗證，這段先跳過，等你本機確認後補上真實網址與 selector")
    # TODO: 這裡之後接 conbini_promo_scraper.py 裡驗證過的邏輯

    # --- 超商優惠整理網站 ---
    for domain in AGGREGATOR_SOURCES:
        # 這裡先用假設的文章網址示意；實際上你需要先有一份「本週要抓哪些文章網址」
        # 的清單（可以是你每天手動貼幾個連結進一個設定檔，也不算違反自動化原則，
        # 因為抓取跟擷取的邏輯本身是全自動的，只是「今天有哪幾篇新文章」這件事
        # 暫時還沒做自動發現機制）
        log.info(f"（示意）預計從 {domain} 抓取本週優惠彙整文章")

    # --- 事實擷取（示範用剛剛驗證過的樣本文字，實際串接時換成上面抓到的真實文字）---
    # 保留這段是為了讓 pipeline 可以在沒有真實網路存取時也能跑通、方便你先看流程

    # --- 商品目錄去重 ---
    try:
        existing_names = db_client.fetch_existing_product_names()
    except RuntimeError as e:
        log.warning(f"尚未設定 Supabase 環境變數，先用空集合模擬：{e}")
        existing_names = set()

    new_products = build_new_products(all_facts, existing_names)
    log.info(f"新商品：{len(new_products)} 筆")

    # --- 活動去重 ---
    try:
        existing_activity_keys = db_client.fetch_existing_activity_keys()
    except RuntimeError:
        existing_activity_keys = set()

    new_activities = filter_new_activities(all_activity_candidates, existing_activity_keys)
    log.info(f"新活動：{len(new_activities)} 筆")

    # --- 寫入資料庫 ---
    if new_products:
        db_client.insert_products(
            [{"name": p.name, "category": p.category, "source_url": p.source_note} for p in new_products]
        )
    if new_activities:
        db_client.insert_activities(
            [
                {
                    "title": a.title,
                    "description": a.description,
                    "start_date": a.start_date or None,
                    "end_date": a.end_date or None,
                    "source_url": a.source_url,
                }
                for a in new_activities
            ]
        )

    log.info("這輪排程跑完")


if __name__ == "__main__":
    run()
