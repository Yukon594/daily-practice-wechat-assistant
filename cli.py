from __future__ import annotations

import argparse

from config import load_settings
from core.assistant import AssistantEngine


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local AI exercise, focus, and notes assistant.")
    parser.add_argument("--once", help="Run a single message and exit.")
    parser.add_argument("--session-id", default="cli", help="Session id for note collection.")
    return parser


def repl(engine: AssistantEngine, session_id: str) -> None:
    print("WeChat AI Assistant CLI")
    print("输入 /exit 退出，输入 /help 查看示例。")
    while True:
        try:
            text = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见。")
            break

        if text in {"/exit", "exit", "quit"}:
            print("再见。")
            break
        if text == "/help":
            print("示例：")
            print("- 今天跑步5公里 32分钟")
            print("- 晚上练胸45分钟")
            print("- 看看这个月专注了多久")
            print("- 这周运动了几次")
            print("- 我想给番茄钟加个多人协作")
            print("- 记下来")
            continue

        print(engine.handle_message(text, session_id=session_id))


def main() -> None:
    args = build_parser().parse_args()
    settings = load_settings()
    engine = AssistantEngine(settings)

    if args.once:
        print(engine.handle_message(args.once, session_id=args.session_id))
        return

    repl(engine, session_id=args.session_id)


if __name__ == "__main__":
    main()
