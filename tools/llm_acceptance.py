"""Real-API acceptance test set for 日迹 (batch).

Runs the LLM-dependent paths against the configured DeepSeek API and prints a
PASS/FAIL/SOFT report. This is a *manual* acceptance runner (it costs real API
calls), so it is NOT part of the unittest suite.

    PYTHONPATH=. .venv/bin/python tools/llm_acceptance.py

The API key is read via load_settings() and never printed.
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from datetime import date, timedelta

from config import load_settings
from core.assistant import AssistantEngine
from core.exercise import parse_exercise
from core.llm import DeepSeekClient
from core.mood import classify_mood
from core.notes import NotesService
from core.router import classify_intent
from core.store import Store

GREEN, RED, YEL, DIM, RST = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"

settings = load_settings()
LLM = DeepSeekClient(settings)


def engine():
    s = load_settings(data_dir_override=Path(tempfile.mkdtemp()))
    return AssistantEngine(s)


def service():
    s = load_settings(data_dir_override=Path(tempfile.mkdtemp()))
    return NotesService(Store(s), s, DeepSeekClient(s))


results = []  # (group, name, status, detail)


def record(group, name, ok, detail, soft=False):
    status = "PASS" if ok else ("SOFT" if soft else "FAIL")
    results.append((group, name, status, detail))
    color = GREEN if status == "PASS" else (YEL if status == "SOFT" else RED)
    print(f"  {color}{status}{RST}  {name}  {DIM}{detail}{RST}")


# ---------------------------------------------------------------- mood classify
def run_mood():
    print(f"\n{'='*70}\nA) MOOD classify_mood — free text → canonical / 非情绪(None)\n{'='*70}")
    cases = [
        ("今天心情不错", {"开心"}),
        ("今天过得挺开心的", {"开心"}),
        ("还行吧，挺平静的", {"平静"}),
        ("有点烦躁", {"焦虑"}),
        ("最近压力好大", {"焦虑"}),
        ("今天有点难过", {"难过"}),
        ("不太开心", {"难过"}),
        ("心情不好", {"难过"}),
        ("累死了", {"难过", "焦虑", "很难描述"}),
        ("怕明天面试搞砸", {"恐惧"}),
        ("五味杂陈，说不上来", {"很难描述"}),
        # non-mood → must be None (非情绪)
        ("谢谢", {None}),
        ("好的", {None}),
        ("在吗", {None}),
        ("帮我查一下这周运动", {None}),
        ("写得不错", {None}),
    ]
    for text, expected in cases:
        try:
            r = classify_mood(text, LLM)
            got = r["emotion"] if r else None
            ok = got in expected
            soft = (not ok) and (got is not None) and (None not in expected)
            record("mood", f"{text!r:>24} → {got}", ok, f"expect {expected}", soft=soft)
        except Exception as e:  # noqa
            record("mood", f"{text!r}", False, f"ERROR {e}")
        time.sleep(0.2)


# ------------------------------------------------------------------- intent
def run_intent():
    print(f"\n{'='*70}\nB) INTENT classify_intent (rule+LLM)\n{'='*70}")
    cases = [
        ("今天跑步5公里32分钟", "exercise"),
        ("今天有点焦虑", "mood"),
        ("这周运动了几次", "query"),
        ("看看最近的想法", "query"),
        ("我突然觉得专注靠的是环境而不是意志力", "note"),
        ("在读纳瓦尔宝典，财富是睡后收入", "note"),
        ("你好啊", "chat"),
        ("你能帮我干嘛", "chat"),
    ]
    for text, expected in cases:
        try:
            got = classify_intent(text, LLM)
            record("intent", f"{text!r:>30} → {got}", got == expected, f"expect {expected}")
        except Exception as e:  # noqa
            record("intent", f"{text!r}", False, f"ERROR {e}")
        time.sleep(0.2)


# ----------------------------------------------------------------- exercise LLM
def run_exercise():
    print(f"\n{'='*70}\nC) EXERCISE parse (LLM fallback for fuzzy phrasing)\n{'='*70}")
    cases = [
        ("今天去健身房练了会儿胸，大概四十分钟", "力量训练"),
        ("晚上散步了半小时", "步行"),
        ("骑车上下班来回大概一个钟头", "骑行"),
    ]
    for text, expected in cases:
        try:
            s = parse_exercise(text, llm=LLM)
            record("exercise", f"{text!r:>30} → {s['activity']} {s['duration_minutes']}min",
                   s["activity"] == expected, f"expect {expected}")
        except Exception as e:  # noqa
            record("exercise", f"{text!r}", False, f"ERROR {e}")
        time.sleep(0.2)


# --------------------------------------------------------------- note building
def run_note_build():
    print(f"\n{'='*70}\nD) NOTE _build_note — type-specific structure\n{'='*70}")
    svc = service()

    def build(text):
        return svc._build_note([{"role": "user", "content": text}])

    # reflection → prose summary, no checklist
    n = build("今天走在路上突然觉得，和人的关系其实是靠一件件小事一点点攒出来的")
    record("note", f"随想 type={n['type']}", n["type"] == "随想" and bool(n["summary"]) and not n["next_steps"] and not n["lessons"],
           f"summary={bool(n['summary'])} steps={n['next_steps']} lessons={n['lessons']}")

    # action → has next_steps
    n = build("我想给看板加一个周对比功能，现在只能看月度，想横向比较每周的专注趋势")
    record("note", f"行动 type={n['type']}", n["type"] == "行动" and bool(n["next_steps"]),
           f"steps={n['next_steps']}")

    # review → lessons or next_steps present
    n = build("复盘一下这次上线，因为配置没同步回滚了一次，挺折腾的")
    record("note", f"复盘 type={n['type']}", n["type"] == "复盘" and (bool(n["lessons"]) or bool(n["next_steps"])),
           f"lessons={n['lessons']} steps={n['next_steps']}")

    # source → book note
    n = build("在读《纳瓦尔宝典》，觉得『财富是睡后收入』这个点很戳我")
    record("note", f"来源 is_book={n['is_book_note']} book={n['book']!r}",
           bool(n["is_book_note"]) and "纳瓦尔" in (n["book"] or ""), f"type={n['type']}")


# ------------------------------------------------- end-to-end footgun + undo
def run_flows():
    print(f"\n{'='*70}\nE) END-TO-END flows (real LLM): mood footgun + undo\n{'='*70}")

    # 1) record then a junk reply -> NOT logged as mood
    e = engine()
    e.handle_message("今天跑步5公里 32分钟", "s")
    e.handle_message("谢谢", "s")
    m = e.store.get_today_mood()
    record("flow", "record→'谢谢' not logged as mood", m is None, f"mood={m}")

    # 2) record then a real feeling -> logged
    e = engine()
    e.handle_message("今天跑步5公里 32分钟", "s")
    e.handle_message("有点累", "s")
    m = e.store.get_today_mood()
    record("flow", "record→'有点累' captured as mood", m is not None, f"mood={m and m['emotion']}")

    # 3) record then bare '去除' -> undo, no junk mood
    e = engine()
    e.handle_message("今天跑步5公里 32分钟", "s")
    r = e.handle_message("去除", "s")
    left = len(e.store.list_recent_exercise_sessions())
    m = e.store.get_today_mood()
    record("flow", "record→'去除' undoes, no mood", "已撤销" in r and left == 0 and m is None,
           f"left={left} mood={m} reply={r[:20]!r}")

    # 4) note session: legit content containing a cancel word keeps collecting
    e = engine()
    e.handle_message("我想记录一个产品点子", "s")
    opened = e.notes.has_active_session("s")
    e.handle_message("我打算先跳过登录这一块，直接做核心流程", "s")
    record("flow", "note: legit '跳过…' keeps session", opened and e.notes.has_active_session("s"),
           f"opened={opened} still_active={e.notes.has_active_session('s')}")


def run_dates():
    print(f"\n{'='*70}\nF) EXERCISE date resolution (LLM path must not invent dates)\n{'='*70}")
    today = date.today()
    cases = [
        ("骑车上下班来回大概一个钟头", today.isoformat()),
        ("今天晨跑了三十来分钟，差不多五公里", today.isoformat()),
        ("前天那会去爬山爬了俩钟头", (today - timedelta(days=2)).isoformat()),
        ("昨天傍晚去游了四十分钟的泳", (today - timedelta(days=1)).isoformat()),
    ]
    for text, exp in cases:
        try:
            s = parse_exercise(text, llm=LLM)
            record("date", f"{text!r:>28} → {s['ts']}", s["ts"] == exp, f"expect {exp}")
        except Exception as e:  # noqa
            record("date", f"{text!r}", False, f"ERROR {e}")
        time.sleep(0.2)


def run_routing():
    print(f"\n{'='*70}\nG) ROUTING mood↔note boundary (the reported cross-talk)\n{'='*70}")
    cases = [
        ("我想把情绪卡做成月历模式", "note"),
        ("刚刚散步时想到，很多焦虑本质上是对模糊的失控感", "note"),
        ("我想做个把想法按主题聚类的功能", "note"),
        ("想到那件事就有点恐惧", "mood"),
        ("一忙起来就特别烦", "mood"),
        ("今天心情不错", "mood"),
    ]
    for text, exp in cases:
        try:
            got = classify_intent(text, LLM)
            record("route", f"{text!r:>30} → {got}", got == exp, f"expect {exp}")
        except Exception as e:  # noqa
            record("route", f"{text!r}", False, f"ERROR {e}")
        time.sleep(0.2)


def run_source():
    print(f"\n{'='*70}\nH) SOURCE notes — reliability + medium-neutral (book/podcast/article/course)\n{'='*70}")
    svc = service()
    cases = [
        ("在读《纳瓦尔宝典》，财富是睡后收入这点很认同", "书"),
        ("听了一期播客《纵横四海》聊产品取舍，挺有启发", "播客"),
        ("看了篇公众号文章讲注意力管理，要给深度工作留整块时间", "文章"),
        ("上了门讲谈判的课程，BATNA 这个概念很有用", "课程"),
    ]
    for text, medium in cases:
        try:
            n = svc._build_note([{"role": "user", "content": text}])
            ok = bool(n["is_book_note"]) and bool(n["book"])
            record("source", f"{text[:20]!r} is_book={n['is_book_note']} src={n.get('source_type')!r}",
                   ok, f"book={n['book']!r}")
        except Exception as e:  # noqa
            record("source", f"{text[:20]!r}", False, f"ERROR {e}")
        time.sleep(0.2)


def summary():
    print(f"\n{'='*70}\nSUMMARY\n{'='*70}")
    by = {}
    for g, _, st, _ in results:
        by.setdefault(g, {"PASS": 0, "SOFT": 0, "FAIL": 0})[st] += 1
    total = {"PASS": 0, "SOFT": 0, "FAIL": 0}
    for g, c in by.items():
        for k in total:
            total[k] += c[k]
        print(f"  {g:<10} PASS={c['PASS']:<3} SOFT={c['SOFT']:<3} FAIL={c['FAIL']}")
    print(f"  {'-'*40}")
    print(f"  {'TOTAL':<10} {GREEN}PASS={total['PASS']}{RST}  {YEL}SOFT={total['SOFT']}{RST}  {RED}FAIL={total['FAIL']}{RST}")
    fails = [f"{g}/{n}: {d}" for g, n, st, d in results if st == "FAIL"]
    if fails:
        print(f"\n  {RED}Failures:{RST}")
        for f in fails:
            print("   -", f)


if __name__ == "__main__":
    if not settings.deepseek_api_key:
        print("No API key configured; aborting.")
        sys.exit(1)
    t0 = time.time()
    run_mood()
    run_intent()
    run_exercise()
    run_note_build()
    run_flows()
    run_dates()
    run_routing()
    run_source()
    summary()
    print(f"\n  elapsed {time.time()-t0:.1f}s")
