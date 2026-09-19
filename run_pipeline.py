"""
主流程：串起「抓資料 -> 擷取事實 -> 去重 -> 寫進 Supabase」整條管線。
這支是排程機制實際會跑的進入點（GitHub Actions 或 cron 都是呼叫這支)。

流程：
  1. 抓官網公開活動頁（已驗證可用）
  2. 抓 1-2 個超商優惠整理網站的文章（尚未接自動發現文章網址，先留位置）
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
import db_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("pipeline")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

# 官網已驗證可用的公開頁面
OFFICIAL_COUPON_URL = "https://www.7-11.com.tw/7app/coupon/receipts.html"

# 第二來源：超商優惠整理網站（挑選標準：會固定週期發「超商優惠彙整」文章，
# 格式相對穩定）。這裡先放兩個我們查證過確實有在做這類彙整報導的來源，
# 之後發現規律不穩可以再換。
AGGREGATOR_SOURCES = [
    "supertaste.tvbs.com.tw",
    "www.nownews.com",
]


def fetch_page_text(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")
    return soup.get_text(separator="\n")


def build_official_candidates(items):
    """把官網優惠頁擷取到的項目，轉成商品名稱清單 + 活動候選清單"""
    product_names = set()
    activity_groups = {}

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
                description="、".join(info["names"][:10]),
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

    # --- 超商優惠整理網站 ---
    for domain in AGGREGATOR_SOURCES:
        log.info(f"（示意）預計從 {domain} 抓取本週優惠彙整文章")

    # --- 商品目錄去重 ---
    try:
        existing_names = db_client.fetch_existing_product_names()
    except RuntimeError as e:
        log.warning(f"尚未設定 Supabase 環境變數，先用空集合模擬：{e}")
        existing_names = set()

    new_product_names = [n for n in all_product_names if n not in existing_names]
    log.info(f"新商品：{len(new_product_names)} 筆")

    # --- 活動去重 ---
    try:
        existing_activity_keys = db_client.fetch_existing_activity_keys()
    except RuntimeError:
        existing_activity_keys = set()

    new_activities = filter_new_activities(all_activity_candidates, existing_activity_keys)
    log.info(f"新活動：{len(new_activities)} 筆")

    # --- 寫入資料庫 ---
    if new_product_names:
        db_client.insert_products(
            [{"name": n, "category": "未分類", "source_url": OFFICIAL_COUPON_URL} for n in new_product_names]
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
