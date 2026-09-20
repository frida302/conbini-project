"""
Supabase 資料庫存取層 — 用 REST API（PostgREST）直接打，不裝額外的 SDK,
降低依賴、也方便你之後看懂在幹嘛。

需要兩個環境變數（在 Supabase 專案設定 > API 頁面可以找到）：
  SUPABASE_URL          例如 https://xxxxx.supabase.co
  SUPABASE_SERVICE_KEY  service_role key（有寫入權限，只能在後端/排程用，
                         絕對不能放進前端程式碼或公開 repo）
"""

import os
import requests
from typing import List, Set, Tuple

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal",
}


def _check_config():
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError(
            "缺少 SUPABASE_URL 或 SUPABASE_SERVICE_KEY 環境變數，"
            "本機測試請先 export，排程機制（GitHub Actions）則設定在 repo 的 Secrets 裡"
        )


def fetch_existing_product_names() -> Set[str]:
    _check_config()
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/products",
        headers=HEADERS,
        params={"select": "name"},
        timeout=10,
    )
    resp.raise_for_status()
    return {row["name"] for row in resp.json()}


def insert_products(products: List[dict]) -> None:
    """products: [{"name":..., "category":..., "price":..., "image_url":..., "source_url":...}, ...]"""
    if not products:
        return
    _check_config()
    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/products",
        headers=HEADERS,
        json=products,
        timeout=10,
    )
    resp.raise_for_status()


def fetch_existing_activity_keys() -> Set[Tuple[str, str]]:
    _check_config()
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/activities",
        headers=HEADERS,
        params={"select": "title,start_date"},
        timeout=10,
    )
    resp.raise_for_status()
    return {(row["title"], row.get("start_date") or "") for row in resp.json()}


def insert_activities(activities: List[dict]) -> None:
    """activities: [{"title":..., "description":..., "start_date":..., "end_date":..., "source_url":...}, ...]"""
    if not activities:
        return
    _check_config()
    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/activities",
        headers=HEADERS,
        json=activities,
        timeout=10,
    )
    resp.raise_for_status()
