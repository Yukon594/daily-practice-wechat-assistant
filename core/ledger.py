from __future__ import annotations

import re
from typing import Dict, List, Optional

from core.llm import DeepSeekClient, LLMError
from core.store import Store

CATEGORIES = ["餐饮", "交通", "购物", "娱乐", "居家", "医疗", "学习", "其它"]
CATEGORY_KEYWORDS = {
    "餐饮": ["饭", "餐", "奶茶", "咖啡", "火锅", "海底捞", "外卖", "早餐", "午餐", "晚餐", "吃"],
    "交通": ["地铁", "打车", "滴滴", "公交", "高铁", "火车", "机票", "停车", "过路费"],
    "购物": ["淘宝", "京东", "衣服", "鞋", "日用品", "买", "购物", "超市"],
    "娱乐": ["游戏", "电影", "ktv", "演出", "酒吧", "娱乐", "会员"],
    "居家": ["房租", "水电", "物业", "家具", "家居", "宽带"],
    "医疗": ["医院", "药", "挂号", "体检", "医疗"],
    "学习": ["课程", "书", "学习", "培训", "考试", "学费"],
}
AMOUNT_RE = re.compile(r"(?:\d+(?:\.\d+)?|[零一二两三四五六七八九十百千万半]+)\s*(?:元|块钱|块|钱)")
ENTRY_RE = re.compile(
    r"(?P<item>[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9_-]{0,24}?)\s*"
    r"(?P<amount>\d+(?:\.\d+)?|[零一二两三四五六七八九十百千万半]+)\s*"
    r"(?:元|块钱|块|钱)?"
)


def looks_like_ledger_text(text: str) -> bool:
    return bool(AMOUNT_RE.search(text))


def chinese_to_number(token: str) -> Optional[float]:
    if not token:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", token):
        return float(token)
    if token == "半":
        return 0.5

    digit_map = {
        "零": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    unit_map = {"十": 10, "百": 100, "千": 1000, "万": 10000}

    total = 0
    current = 0
    for char in token:
        if char in digit_map:
            current = digit_map[char]
            continue
        if char in unit_map:
            unit = unit_map[char]
            if current == 0:
                current = 1
            total += current * unit
            current = 0
            continue
        return None
    return float(total + current)


def classify_category(item: str) -> str:
    lower_item = item.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in lower_item for keyword in keywords):
            return category
    return "其它"


def _normalize_expense(item: Dict) -> Optional[Dict]:
    name = str(item.get("item", "")).strip()
    amount = chinese_to_number(str(item.get("amount", "")).strip())
    category = str(item.get("category", "")).strip() or classify_category(name)

    if not name or amount is None or amount <= 0:
        return None
    if category not in CATEGORIES:
        category = classify_category(name)

    return {
        "item": name,
        "amount": round(float(amount), 2),
        "category": category,
    }


def _parse_with_llm(text: str, llm: DeepSeekClient) -> List[Dict]:
    messages = [
        {
            "role": "system",
            "content": (
                "你是一个中文记账解析器。"
                "把输入里的消费拆成结构化 JSON。"
                "只返回 JSON 对象，格式为 "
                '{"expenses":[{"item":"项目","amount":12.5,"category":"餐饮"}]}。'
                f"分类只能是：{', '.join(CATEGORIES)}。"
            ),
        },
        {
            "role": "user",
            "content": f"请解析这段消费记录：{text}",
        },
    ]
    payload = llm.chat(messages, json_mode=True, temperature=0.1, max_tokens=600)
    expenses = payload.get("expenses", [])
    return [item for item in (_normalize_expense(entry) for entry in expenses) if item]


def _parse_with_rules(text: str) -> List[Dict]:
    expenses = []
    for match in ENTRY_RE.finditer(text):
        item = match.group("item").strip("，,、。；; ")
        amount = match.group("amount")
        normalized = _normalize_expense(
            {
                "item": item,
                "amount": amount,
                "category": classify_category(item),
            }
        )
        if normalized:
            expenses.append(normalized)
    return expenses


def parse_expenses(text: str, llm: Optional[DeepSeekClient] = None) -> List[Dict]:
    if llm and llm.is_configured:
        try:
            parsed = _parse_with_llm(text, llm)
            if parsed:
                return parsed
        except LLMError:
            pass
    return _parse_with_rules(text)


def save_expenses(text: str, store: Store, llm: Optional[DeepSeekClient] = None) -> str:
    expenses = parse_expenses(text, llm)
    if not expenses:
        return "我没能从这句话里拆出明确账目。你可以试试：海底捞250块 奶茶25元。"

    store.add_expenses(expenses, raw_text=text)
    total = round(sum(item["amount"] for item in expenses), 2)
    details = "；".join(
        f'{item["item"]} {item["amount"]:g}元({item["category"]})'
        for item in expenses
    )
    return f"已记 {len(expenses)} 笔，共 {total:g} 元：{details}"
