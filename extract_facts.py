"""
從「超商優惠整理網站」的文章內文中,擷取結構化事實資料
（品項、原價、特價、折扣方式、期間),不保留原文敘述。

設計邏輯：
這類文章有很固定的寫作套路，常見兩種格式：
  1. 「品項名稱 X杯/份 Y元,Z折(原價A元、特價B元)」
  2. 「品項名稱 買X送Y」（不一定有原價/特價數字）

我們只抓「事實欄位」進資料庫，原始句子丟掉不存。
"""

import re
from dataclasses import dataclass, asdict
from typing import List, Optional


@dataclass
class PromoFact:
    store: str
    product_name: str
    deal_type: Optional[str]     # 例如 "買2送2" / "11杯520元" / None
    original_price: Optional[int]
    special_price: Optional[int]
    discount_ratio: Optional[str]  # 例如 "7.3折"
    period: Optional[str]
    source_note: str  # 只記來源網域，不記文章內文


# 抓「品項名稱 + 交易方式描述 + (原價A元、特價B元)」這種最有結構的句型
# 不同來源網站標點習慣不一致（頓號/逗號都有），且「交易方式」跟逗號的
# 先後順序也會變（有些是「名稱,交易方式(...)」有些是「名稱,交易方式,折(...)」），
# 這裡放寬成逗號可以出現在交易方式前後任一位置。
PATTERN_WITH_PRICE = re.compile(
    r"(?P<name>[\u4e00-\u9fffA-Za-z0-9\s\-\+&]{2,20}?)"       # 品項名稱（中英文/數字）
    r"[,，]?\s*"
    r"(?P<deal>[\d一二三四五六七八九十]+杯\d+元|買\d+送\d+|[\d一二三四五六七八九十]+份\d+元|任選\d+件\d+折)?"  # 交易方式（可省略）
    r"[,，]?\s*"
    r"(?:(?P<ratio>\d+(?:\.\d+)?折)\s*)?"
    r"\(原價(?P<orig>\d+)元[、,，]\s*特價(?P<special>\d+)元\)"
)

# 抓沒有「原價/特價」但有「買X送Y」的簡單句型
PATTERN_BUY_GET = re.compile(
    r"(?P<name>[\u4e00-\u9fffA-Za-z0-9\s\-\+&]{2,20}?)"
    r"(?P<deal>買\d+送\d+)"
)


def extract_promo_facts(text: str, store: str, source_domain: str) -> List[PromoFact]:
    facts: List[PromoFact] = []
    seen = set()
    seen_names = set()  # 追蹤已經抓到「有價格」的品項名稱，避免被無價格規則重複加入

    for m in PATTERN_WITH_PRICE.finditer(text):
        name = m.group("name").strip(" ,，、\n")
        if not name or len(name) < 2:
            continue
        key = (name, m.group("orig"), m.group("special"))
        if key in seen:
            continue
        seen.add(key)
        seen_names.add(name)
        facts.append(
            PromoFact(
                store=store,
                product_name=name,
                deal_type=m.group("deal"),
                original_price=int(m.group("orig")),
                special_price=int(m.group("special")),
                discount_ratio=m.group("ratio"),
                period=None,  # 期間通常在文章別處（如標題日期),另外用規則抓
                source_note=source_domain,
            )
        )

    for m in PATTERN_BUY_GET.finditer(text):
        name = m.group("name").strip(" ,，、\n")
        if not name or len(name) < 2:
            continue
        if name in seen_names:
            continue
        key = (name, m.group("deal"), None)
        if key in seen:
            continue
        seen.add(key)
        seen_names.add(name)
        facts.append(
            PromoFact(
                store=store,
                product_name=name,
                deal_type=m.group("deal"),
                original_price=None,
                special_price=None,
                discount_ratio=None,
                period=None,
                source_note=source_domain,
            )
        )

    return facts


# 抓活動期間，例如「4/14(一)~4/20(日)」「10月1日至10月6日」
PERIOD_PATTERN = re.compile(
    r"(\d{1,2}[/月]\d{1,2}日?(?:\([一二三四五六日]\))?"
    r"\s*[~至到]\s*"
    r"\d{1,2}[/月]\d{1,2}日?(?:\([一二三四五六日]\))?)"
)


def extract_periods(text: str) -> List[str]:
    return PERIOD_PATTERN.findall(text)


if __name__ == "__main__":
    # 真實測試資料：直接取自今天查證時搜到的超商優惠整理文章片段
    sample_1 = """
    APP|4/14(一)~4/20(日)
    大杯厚乳拿鐵11杯520元,7.3折(原價65元、特價47元)
    大杯卡布奇諾11杯520元,7.3折(原價65元、特價47元)
    大杯濃萃美式12杯520元,7.2折(原價60元、特價43元)
    大杯濃萃拿鐵12杯520元,7.2折(原價60元、特價43元)
    珍珠焙火烏龍奶茶買2送2,5折(原價75元、特價38元)
    青梅冰茶買2送2,5折(原價60元、特價30元)
    """

    sample_2 = """
    大杯熱厚乳拿鐵,買1送1(原價65元,特價33元)。
    大杯冰精品美式,買1送1(原價100元,特價50元)。
    大杯精品馥芮白,買1送1(原價120元,特價60元)。
    """

    print("=== 樣本1擷取結果 ===")
    for fact in extract_promo_facts(sample_1, store="7-11", source_domain="tw.stock.yahoo.com"):
        print(asdict(fact))
    print("期間：", extract_periods(sample_1))

    print("\n=== 樣本2擷取結果 ===")
    for fact in extract_promo_facts(sample_2, store="7-11", source_domain="news.tvbs.com.tw"):
        print(asdict(fact))
