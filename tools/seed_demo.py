"""Seed / clear isolated demo data for previewing the public dashboard.

Usage:
    python tools/seed_demo.py          # reset + insert exercise/focus/mood/notes demo data
    python tools/seed_demo.py --clear  # remove demo data only

The demo data lives in a separate data directory and never touches your
real local database or notes folder.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import load_settings
from core.store import Store

DEMO_DATA_DIR = PROJECT_ROOT / "data_demo"

EXERCISE_SESSIONS = [
    {"days_ago": 0, "activity": "跑步", "minutes": 38, "km": 6.2, "raw": "傍晚跑步 38分钟 6.2公里"},
    {"days_ago": 1, "activity": "力量训练", "minutes": 46, "km": None, "raw": "下班后练腿 46分钟"},
    {"days_ago": 3, "activity": "步行", "minutes": 62, "km": 4.8, "raw": "晚饭后快走 62分钟 4.8公里"},
    {"days_ago": 5, "activity": "羽毛球", "minutes": 75, "km": None, "raw": "周末羽毛球 75分钟"},
    {"days_ago": 8, "activity": "跑步", "minutes": 31, "km": 5.0, "raw": "晨跑 31分钟 5公里"},
    {"days_ago": 10, "activity": "瑜伽", "minutes": 28, "km": None, "raw": "睡前瑜伽 28分钟"},
    {"days_ago": 12, "activity": "骑行", "minutes": 58, "km": 14.6, "raw": "通勤骑行 58分钟 14.6公里"},
    {"days_ago": 15, "activity": "力量训练", "minutes": 42, "km": None, "raw": "上肢训练 42分钟"},
    {"days_ago": 19, "activity": "游泳", "minutes": 40, "km": None, "raw": "游泳 40分钟"},
    {"days_ago": 22, "activity": "步行", "minutes": 54, "km": 4.1, "raw": "午后散步 54分钟 4.1公里"},
    {"days_ago": 26, "activity": "篮球", "minutes": 70, "km": None, "raw": "朋友局篮球 70分钟"},
    {"days_ago": 29, "activity": "跑步", "minutes": 35, "km": 5.6, "raw": "夜跑 35分钟 5.6公里"},
]

FOCUS_DAYS = [
    {"days_ago": 0, "focus_seconds": 5400, "trees": 4, "projects": {"微信助手": (3600, 3), "阅读": (1800, 1)}},
    {"days_ago": 1, "focus_seconds": 4200, "trees": 3, "projects": {"贴纸番茄钟": (2400, 2), "课程": (1800, 1)}},
    {"days_ago": 2, "focus_seconds": 3000, "trees": 2, "projects": {"微信助手": (3000, 2)}},
    {"days_ago": 4, "focus_seconds": 6600, "trees": 5, "projects": {"论文": (3600, 3), "阅读": (3000, 2)}},
    {"days_ago": 6, "focus_seconds": 2400, "trees": 2, "projects": {"贴纸番茄钟": (2400, 2)}},
    {"days_ago": 7, "focus_seconds": 4800, "trees": 4, "projects": {"课程": (1800, 1), "微信助手": (3000, 3)}},
    {"days_ago": 9, "focus_seconds": 3600, "trees": 3, "projects": {"论文": (1800, 1), "阅读": (1800, 2)}},
    {"days_ago": 11, "focus_seconds": 4500, "trees": 3, "projects": {"微信助手": (2700, 2), "贴纸番茄钟": (1800, 1)}},
    {"days_ago": 13, "focus_seconds": 5100, "trees": 4, "projects": {"课程": (2100, 2), "论文": (3000, 2)}},
]

MOOD_LOGS = [
    {"days_ago": 0, "emotion": "平静", "note": "今天推进稳定，没有硬扛。"},
    {"days_ago": 1, "emotion": "开心", "note": "运动和专注都达标，节奏挺顺。"},
    {"days_ago": 2, "emotion": "焦虑", "note": "白天切任务太频繁。"},
    {"days_ago": 4, "emotion": "平静", "note": ""},
    {"days_ago": 5, "emotion": "很难描述", "note": "有点累，但不是坏情绪。"},
    {"days_ago": 7, "emotion": "开心", "note": "晚上复盘时状态很好。"},
    {"days_ago": 9, "emotion": "难过", "note": "有个计划推进不太顺。"},
    {"days_ago": 12, "emotion": "平静", "note": ""},
]

NOTES = [
    {
        "title": "把情绪记录变成日历而不是列表",
        "category": "产品灵感",
        "tags": ["情绪", "日历", "交互"],
        "markdown": (
            "---\n"
            "title: 把情绪记录变成日历而不是列表\n"
            "category: 产品灵感\n"
            "tags: [情绪, 日历, 交互]\n"
            f"created: {date.today().isoformat()}\n"
            "---\n\n"
            "## 核心内容\n"
            "情绪这种东西更适合按天回看，不适合只堆成一列记录。月历能让波动和连续性一下子被看见。\n\n"
            "## 背景 / 动机\n"
            "如果只看今天的心情，很容易漏掉过去一周其实一直在变好或变差的趋势。\n\n"
            "## 可行的下一步\n"
            "- [ ] 点图标弹备注，而不是常驻大文本框\n"
            "- [ ] 保留月选择，不跟 12 周热力图混在一起\n"
        ),
    },
    {
        "title": "代码廉价后更值钱的是取舍",
        "category": "AI碎碎念",
        "tags": ["AI", "产品", "取舍"],
        "markdown": (
            "---\n"
            "title: 代码廉价后更值钱的是取舍\n"
            "category: AI碎碎念\n"
            "tags: [AI, 产品, 取舍]\n"
            f"created: {date.today().isoformat()}\n"
            "---\n\n"
            "## 核心内容\n"
            "人人都能更快地做功能时，真正稀缺的反而是审美、判断和克制。\n\n"
            "## 背景 / 动机\n"
            "不是不会做，而是做什么、不做什么，决定了产品最后留下来的体验。\n"
        ),
    },
    {
        "title": "贴纸番茄钟的周回顾入口",
        "category": "工作",
        "tags": ["番茄钟", "复盘", "功能设计"],
        "markdown": (
            "---\n"
            "title: 贴纸番茄钟的周回顾入口\n"
            "category: 工作\n"
            "tags: [番茄钟, 复盘, 功能设计]\n"
            f"created: {date.today().isoformat()}\n"
            "---\n\n"
            "## 核心内容\n"
            "如果用户已经在周内记了运动、专注和情绪，周日晚应该有一个自动生成的复盘入口。\n\n"
            "## 可行的下一步\n"
            "- [ ] 把本周训练 / 专注 / 心情拼成一页摘要\n"
            "- [ ] 周日晚 9 点生成但不强制推送\n"
        ),
    },
]


def clear(store: Store, settings) -> None:
    with store._connect() as conn:  # noqa: SLF001 - demo utility
        conn.execute("DELETE FROM expenses")
        conn.execute("DELETE FROM exercise_sessions")
        conn.execute("DELETE FROM focus_days")
        conn.execute("DELETE FROM mood_logs")
        conn.execute("DELETE FROM notes")
        conn.execute("DELETE FROM note_sessions")
        conn.execute("DELETE FROM mood_state")
    for md in settings.notes_dir.rglob("*.md"):
        md.unlink()
    print(f"已清空演示数据：{settings.data_dir}")


def seed(store: Store, settings) -> None:
    clear(store, settings)
    today = date.today()

    for row in EXERCISE_SESSIONS:
        ts = (today - timedelta(days=row["days_ago"])).isoformat()
        store.add_exercise_session(
            {
                "activity": row["activity"],
                "duration_minutes": row["minutes"],
                "distance_km": row["km"],
                "calories": None,
                "source": "demo",
            },
            raw_text=row["raw"],
            ts=ts,
        )

    focus_rows = []
    for row in FOCUS_DAYS:
        ts = (today - timedelta(days=row["days_ago"])).isoformat()
        focus_rows.append(
            {
                "day": ts,
                "focus_seconds": row["focus_seconds"],
                "trees_completed": row["trees"],
                "projects": {
                    name: {
                        "focus_seconds": seconds,
                        "trees_completed": trees,
                    }
                    for name, (seconds, trees) in row["projects"].items()
                },
            }
        )
    store.replace_focus_days(focus_rows, source_path=str(PROJECT_ROOT / "tools" / "demo-focus.json"))

    for row in MOOD_LOGS:
        day = (today - timedelta(days=row["days_ago"])).isoformat()
        store.add_mood(row["emotion"], row["note"], source="demo", day=day)

    for note in NOTES:
        store.add_note(note)

    print(
        "已写入演示数据："
        f"{len(EXERCISE_SESSIONS)} 条运动，"
        f"{len(focus_rows)} 天专注，"
        f"{len(MOOD_LOGS)} 条情绪，"
        f"{len(NOTES)} 条想法。"
    )
    print(f"演示数据目录：{settings.data_dir}")
    print("启动演示看板：")
    print(f"  ASSISTANT_DATA_DIR={settings.data_dir} python3 dashboard/app.py")
    print("清空演示数据：")
    print("  python3 tools/seed_demo.py --clear")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed or clear dashboard demo data")
    parser.add_argument("--clear", action="store_true", help="remove all demo data")
    args = parser.parse_args()

    settings = load_settings(data_dir_override=DEMO_DATA_DIR)
    store = Store(settings)
    if args.clear:
        clear(store, settings)
    else:
        seed(store, settings)


if __name__ == "__main__":
    main()
