"""
商品目錄去重邏輯

設計原則（呼應決策：目錄不開放使用者手動新增，只從擷取結果長出來）：
- 輸入：extract_facts.py 產出的 PromoFact 清單
- 輸出：需要新寫入 Product 表的清單（已存在的品名不重複插入）
- 比對方式：MVP 階段先用「精確字串比對」（去除空白後完全相同才算同一品項）
  已知限制：不會處理「大杯厚乳拿鐵」vs「大杯 厚乳拿鐵」這種空白/全形半形差異
  以外的近似重複（例如全家 vs 全家便利商店這種別名問題）。這是刻意先不做的
  技術債，等真的發現目錄裡有明顯重複再處理，不要在驗證階段先優化這個。
"""

from dataclasses import dataclass
from typing import List, Set
from extract_facts import PromoFact


@dataclass
class ProductRecord:
    name: str
    category: str          # MVP 先給空字串或 "未分類"，之後有需要再人工補分類規則
    source_note: str
    first_seen_from: str   # 記錄這個品項第一次是從哪則活動/新品資訊冒出來的


def normalize_name(name: str) -> str:
    """統一品名格式，減少最明顯的重複（全形空白、前後空白）"""
    return name.strip().replace("\u3000", " ").strip()


def build_new_products(facts: List[PromoFact], existing_names: Set[str]) -> List[ProductRecord]:
    """
    比對已存在的商品名稱，只回傳「目錄裡還沒有的」新商品，
    呼叫端負責把回傳結果寫進資料庫，並把名稱加進 existing_names 集合。
    """
    new_products: List[ProductRecord] = []
    seen_this_batch: Set[str] = set()

    for fact in facts:
        name = normalize_name(fact.product_name)
        if not name:
            continue
        if name in existing_names or name in seen_this_batch:
            continue
        seen_this_batch.add(name)
        new_products.append(
            ProductRecord(
                name=name,
                category="未分類",
                source_note=fact.source_note,
                first_seen_from=fact.deal_type or "",
            )
        )
    return new_products


if __name__ == "__main__":
    from extract_facts import extract_promo_facts

    sample = """
    大杯厚乳拿鐵11杯520元,7.3折(原價65元、特價47元)
    大杯厚乳拿鐵11杯520元,7.3折(原價65元、特價47元)
    珍珠焙火烏龍奶茶買2送2,5折(原價75元、特價38元)
    """
    facts = extract_promo_facts(sample, store="7-11", source_domain="test.example.com")

    # 模擬：目錄裡已經有「珍珠焙火烏龍奶茶」了
    existing = {"珍珠焙火烏龍奶茶"}

    new_ones = build_new_products(facts, existing)
    print(f"這批抓到 {len(facts)} 筆事實，其中 {len(new_ones)} 個是目錄裡沒有的新商品：")
    for p in new_ones:
        print(f"  - {p.name}（來源：{p.source_note}）")
