from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import load_settings
from core.assistant import AssistantEngine


def _sanitize_part(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip())
    return cleaned.strip("-_.") or "unknown"


def build_session_id(
    channel: str,
    account_id: Optional[str] = None,
    peer_id: Optional[str] = None,
    sender_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> str:
    if session_id:
        return session_id

    parts = [_sanitize_part(channel or "wechat")]
    if account_id:
        parts.append(_sanitize_part(account_id))
    if peer_id:
        parts.append(_sanitize_part(peer_id))
    elif sender_id:
        parts.append(_sanitize_part(sender_id))
    else:
        parts.append("default")

    candidate = ":".join(parts)
    if len(candidate) <= 96:
        return candidate

    digest = hashlib.sha1(candidate.encode("utf-8")).hexdigest()[:16]
    return f"{parts[0]}:{digest}"


def read_message(args: argparse.Namespace) -> str:
    if args.text is not None:
        return args.text
    if args.stdin:
        return sys.stdin.read().strip()
    raise SystemExit("Pass --text or --stdin.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="WeChat adapter for the local assistant engine.")
    parser.add_argument("--text", help="Input text message.")
    parser.add_argument("--stdin", action="store_true", help="Read the input text from stdin.")
    parser.add_argument("--session-id", help="Explicit session id override.")
    parser.add_argument("--channel", default="wechat", help="Channel name used in the derived session id.")
    parser.add_argument("--account-id", help="WeChat account id for multi-account isolation.")
    parser.add_argument("--peer-id", help="Peer id for DM/session isolation.")
    parser.add_argument("--sender-id", help="Sender id fallback when peer id is missing.")
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format.",
    )
    parser.add_argument(
        "--data-dir",
        help="Optional data directory override, mainly for testing or demo mode.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    text = read_message(args)
    session_id = build_session_id(
        channel=args.channel,
        account_id=args.account_id,
        peer_id=args.peer_id,
        sender_id=args.sender_id,
        session_id=args.session_id,
    )

    settings = load_settings(data_dir_override=args.data_dir)
    engine = AssistantEngine(settings)
    reply = engine.handle_message(text, session_id=session_id)

    if args.format == "json":
        print(
            json.dumps(
                {
                    "reply": reply,
                    "session_id": session_id,
                },
                ensure_ascii=False,
            )
        )
        return

    print(reply)


if __name__ == "__main__":
    main()
