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
import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from extract_facts import extract_promo_facts, extract_periods
from catalog import build_new_products, normalize_name
from dedup_activities import ActivityRecord, filter_new_activities, dedup_key
from parse_official_page import parse_official_coupon_page
from fetch_product_catalog import fetch_all_categories
import db_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("pipeline")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

# 官網已驗證可用的公開頁面（詳見 conbini_promo_scraper.py 的驗證註記）
OFFICIAL_COUPON_URL = "https://www.7-11.com.tw/7app/coupon/receipts.html"

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


def build_official_candidates(items):
    """把官網優惠頁擷取到的項目，轉成商品名稱清單 + 活動候選清單"""
    product_names = set()
    activity_groups = {}  # deal_label -> list of product names

    for it in items:
        name = normalize_name(it.product_name)
        if name:
            product_names.add(name)
        activity_groups.setdefault(it.deal_label, {"names": [], "period": it.period, "url": it.source_url})
        activity_groups[it.deal_label]["names"].append(name)

    activity_candidates = []
    for deal_label, info in activity_groups.items():
        period = info["period"] or ""
        start_date, end_date = "", ""
        if period and ("~" in period or "至" in period):
            parts = re.split(r"[~至]", period)
            if len(parts) == 2:
                start_date, end_date = parts[0].strip(), parts[1].strip()
        activity_candidates.append(
            ActivityRecord(
                title=deal_label,
                description="、".join(info["names"][:10]),  # 最多列10個品項名稱示意
                start_date=start_date,
                end_date=end_date,
                source_url=info["url"],
            )
        )
    return product_names, activity_candidates


def run():
    all_product_names = set()
    all_activity_candidates = []

    # --- 官網活動頁（已驗證可用）---
    try:
        official_text = fetch_page_text(OFFICIAL_COUPON_URL)
        official_items = parse_official_coupon_page(official_text, source_url=OFFICIAL_COUPON_URL)
        log.info(f"官網頁面擷取到 {len(official_items)} 筆項目")
        names, activities = build_official_candidates(official_items)
        all_product_names |= names
        all_activity_candidates.extend(activities)
    except requests.RequestException as e:
        log.warning(f"官網頁面抓取失敗（先略過，不擋其他來源）：{e}")

    # --- 商品目錄（小七食堂 XML，含價格/圖片，是主要商品來源）---
    catalog_products = {}  # name -> 完整商品資料（含價格/圖片/分類）
    try:
        catalog_items = fetch_all_categories()
        for it in catalog_items:
            name = normalize_name(it.name)
            if name:
                catalog_products[name] = {
                    "name": name,
                    "category": it.category,
                    "price": it.price,
                    "image_url": it.image_url,
                    "source_url": it.source_url,
                }
        log.info(f"商品目錄擷取到 {len(catalog_products)} 項不重複商品")
    except Exception as e:
        log.warning(f"商品目錄抓取失敗（先略過，不擋其他來源）：{e}")

    # 活動頁抓到、但不在商品目錄裡的名稱（例如飲料、零食這類目錄沒涵蓋的品項），
    # 補進來當「無價格/無圖片」的商品，至少讓使用者查得到、能留言
    for name in all_product_names:
        if name not in catalog_products:
            catalog_products[name] = {
                "name": name,
                "category": "未分類",
                "price": None,
                "image_url": None,
                "source_url": OFFICIAL_COUPON_URL,
            }

    # --- 超商優惠整理網站 ---
    for domain in AGGREGATOR_SOURCES:
        # 這裡先用假設的文章網址示意；實際上你需要先有一份「本週要抓哪些文章網址」
        # 的清單（可以是你每天手動貼幾個連結進一個設定檔，也不算違反自動化原則，
        # 因為抓取跟擷取的邏輯本身是全自動的，只是「今天有哪幾篇新文章」這件事
        # 暫時還沒做自動發現機制）
        log.info(f"（示意）預計從 {domain} 抓取本週優惠彙整文章")

    # --- 商品目錄去重 ---
    try:
        existing_names = db_client.fetch_existing_product_names()
    except RuntimeError as e:
        log.warning(f"尚未設定 Supabase 環境變數，先用空集合模擬：{e}")
        existing_names = set()

    new_products = [p for name, p in catalog_products.items() if name not in existing_names]
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
        db_client.insert_products(new_products)
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
