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
    print(f"\n{'='*70}\nD) NOTE capture — title/category/tags + verbatim body\n{'='*70}")
    svc = service()
    cases = [
        "今天走在路上突然觉得，和人的关系其实是靠一件件小事一点点攒出来的",
        "我想给看板加一个周对比功能，现在只能看月度，想横向比较每周的专注趋势",
        "在读《纳瓦尔宝典》，觉得『财富是睡后收入』这个点很戳我",
    ]
    for text in cases:
        try:
            meta = svc._classify(text)
            ok = bool(meta["title"]) and bool(meta["category"]) and bool(meta["tags"])
            record("note", f"{text[:16]!r} → {meta['title']!r} / {meta['category']} / {meta['tags']}", ok, "")
        except Exception as e:  # noqa
            record("note", f"{text[:16]!r}", False, f"ERROR {e}")
        time.sleep(0.2)


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
    # 4) one-shot capture then undo the thought
    e = engine()
    e.handle_message("随手记一个想法：试着每天先写三件最重要的事", "s")
    saved = len(e.store.list_notes())
    e.handle_message("撤销刚才的想法", "s")
    record("flow", "note capture→undo (to trash)",
           saved == 1 and len(e.store.list_notes()) == 0 and len(e.store.list_trashed_notes()) == 1,
           f"saved={saved} now={len(e.store.list_notes())} trash={len(e.store.list_trashed_notes())}")


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
        # the reported misroute: a meta sentence with 「总结」 must NOT become a stats query
        # (archiving it as a product idea is acceptable; the bug was returning 运动汇总)
        ("我现在想把这个助手做成只记录和分类，因为对话延迟高、提示词难写，不如聊完总结再发来归档", "note"),
        ("随手记一个想法：把番茄钟数据同步到看板会很有用", "note"),
        ("这周运动了几次", "query"),
        ("这个月专注了多久", "query"),
    ]
    for text, exp in cases:
        try:
            got = classify_intent(text, LLM)
            record("route", f"{text[:24]!r:>26} → {got}", got == exp, f"expect {exp}")
        except Exception as e:  # noqa
            record("route", f"{text!r}", False, f"ERROR {e}")
        time.sleep(0.2)


def run_interaction():
    print(f"\n{'='*70}\nI) CAPTURE interaction — directive / own-title / new-category / companion mood\n{'='*70}")
    # directive forces category + strips it from the body
    svc = service()
    svc.capture("记录到AI碎碎念：对话是最慢最脆的一块，不如聊完总结再发来归档")
    n = svc.store.list_notes()[0]
    body = svc.store.get_note_by_id(n["id"])["content"]
    record("interact", f"directive → 分类={n['category']}",
           n["category"] == "AI碎碎念" and "记录到AI碎碎念" not in body, "body stripped")

    # own title is used verbatim
    svc = service()
    svc.capture("# 看板周对比功能\n现在只能看月度，想横向比较每周趋势")
    n = svc.store.list_notes()[0]
    record("interact", f"own-title → {n['title']!r}", n["title"] == "看板周对比功能", "")

    # a clearly-new theme can mint a new category (not forced into 其它)
    svc = service()
    meta = svc._classify("研究了一下家里阳台种香草，薄荷和迷迭香很好养")
    record("interact", f"new-category → {meta['category']} (new={meta['category_is_new']})",
           meta["category"] != "其它", f"cat={meta['category']}", soft=(meta["category"] == "其它"))

    # exercise + a non-alias mood tail -> both logged via the LLM
    e = engine()
    e.handle_message("今天跑步五公里用了半小时，好累", "k")
    m = e.store.get_today_mood()
    record("interact", "exercise + '好累' → mood logged",
           m is not None, f"mood={m and m['emotion']}")


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
    run_interaction()
    summary()
    print(f"\n  elapsed {time.time()-t0:.1f}s")
