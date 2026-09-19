"""
活動資料清洗/去重邏輯

跟商品目錄的去重是兩件事：
- 商品去重（catalog.py）：同一個「品項名稱」不要重複出現在 Product 表
- 活動去重（這個檔案）：排程每天跑一次爬蟲，同一檔活動不能因為連續好幾天
  都抓得到，就在 Activity 表裡插入好幾筆重複紀錄

去重判斷依據：標題 + 開始日期（不用整篇內文比對，因為同一檔活動不同天被
抓到時，內文擷取出來的空白/標點可能有些微差異，但標題+日期通常穩定）
"""

import re
from typing import List, Set, Tuple
from dataclasses import dataclass


@dataclass
class ActivityRecord:
    title: str
    description: str
    start_date: str  # ISO format "YYYY-MM-DD"，抓不到就留空字串
    end_date: str
    source_url: str


def normalize_title(title: str) -> str:
    """去除標題中常見的雜訊字元，讓比對更穩定"""
    title = title.strip()
    title = re.sub(r"[!！?？「」『』()（）\s]", "", title)
    return title


def dedup_key(activity: ActivityRecord) -> Tuple[str, str]:
    return (normalize_title(activity.title), activity.start_date)


def filter_new_activities(
    candidates: List[ActivityRecord], existing_keys: Set[Tuple[str, str]]
) -> List[ActivityRecord]:
    """
    輸入這次爬到的候選活動，跟資料庫裡已經有的 (標題正規化, 起始日) 組合比對，
    只回傳真正新的活動，呼叫端負責寫入資料庫並把 key 加進 existing_keys。
    """
    new_ones = []
    seen_this_batch = set()

    for act in candidates:
        key = dedup_key(act)
        if key in existing_keys or key in seen_this_batch:
            continue
        seen_this_batch.add(key)
        new_ones.append(act)

    return new_ones


if __name__ == "__main__":
    # 模擬：同一檔活動被爬蟲連續兩天抓到，內文格式有些微差異
    candidates = [
        ActivityRecord(
            title="超值五六日!全店任選2件79折",
            description="8/29至8/31，全店指定商品任選2件79折",
            start_date="2025-08-29",
            end_date="2025-08-31",
            source_url="https://www.7-11.com.tw/special/newsList.aspx",
        ),
        ActivityRecord(
            title="超值五六日！全店任選2件79折",  # 標點符號不同（全形驚嘆號）
            description="8/29至8/31 全店指定商品任選2件79折優惠開跑",
            start_date="2025-08-29",
            end_date="2025-08-31",
            source_url="https://www.7-11.com.tw/special/newsList.aspx",
        ),
        ActivityRecord(
            title="中秋節限定禮盒新上市",
            description="9/1起中秋禮盒開賣",
            start_date="2025-09-01",
            end_date="2025-09-15",
            source_url="https://www.7-11.com.tw/special/newsList.aspx",
        ),
    ]

    existing: Set[Tuple[str, str]] = set()
    new_ones = filter_new_activities(candidates, existing)
    print(f"這批候選 {len(candidates)} 筆，去重後真正要寫入的有 {len(new_ones)} 筆：")
    for a in new_ones:
        print(f"  - {a.title}（{a.start_date} ~ {a.end_date}）")
