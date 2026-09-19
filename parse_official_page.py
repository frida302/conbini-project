"""
針對 7-11 官網真實頁面驗證過的格式寫的擷取邏輯。

已驗證網址：https://www.7-11.com.tw/7app/coupon/receipts.html
（靜態頁面，不是 JS 渲染，requests 直接抓得到內容）
"""

import re
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class OfficialPromoItem:
    deal_label: str          # 例如 "特價12元"、"買1送1"、"任2件79元"
    product_name: str
    period: Optional[str]
    source_url: str


PERIOD_LINE = re.compile(r"活動日期[:：]\s*([\d/]+\s*[~至]\s*[\d/]+)")
DEAL_HEADER = re.compile(r"【([^】]+)】")


def parse_official_coupon_page(markdown_text: str, source_url: str) -> List[OfficialPromoItem]:
    lines = markdown_text.splitlines()

    period = None
    period_match = PERIOD_LINE.search(markdown_text)
    if period_match:
        period = period_match.group(1).replace(" ", "")

    results: List[OfficialPromoItem] = []
    current_deal: Optional[str] = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        header_match = DEAL_HEADER.match(line)
        if header_match:
            current_deal = header_match.group(1)
            continue

        if PERIOD_LINE.search(line):
            continue

        if current_deal:
            name = re.sub(r"^-\s*", "", line).strip()
            if not name:
                continue
            results.append(
                OfficialPromoItem(
                    deal_label=current_deal,
                    product_name=name,
                    period=period,
                    source_url=source_url,
                )
            )

    return results


if __name__ == "__main__":
    sample = """
活動日期:2026/9/2~2026/9/29

【特價12元】
統一UNI water純水PET550

【買1送1】
立得清酒精擦濕巾35抽 單包
"""
    items = parse_official_coupon_page(sample, source_url="https://www.7-11.com.tw/7app/coupon/receipts.html")
    for it in items:
        print(f"[{it.deal_label}] {it.product_name}（期間：{it.period}）")
