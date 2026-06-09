# Workspace Rules

This workspace is serving a WeChat-facing assistant through OpenClaw.

## WeChat routing

For direct messages arriving from the `openclaw-weixin` channel:

- Always route the raw incoming message through `skills/wechat-assistant/handle.py` before composing any reply.
- Reuse a stable session id for the same DM so the local Python engine can keep multi-turn state.
- Return the adapter's `reply` with no substantive rewriting.

## Do not improvise around the adapter

- Do not answer with your own free-form reasoning before calling the adapter.
- Do not turn a short command like `保存到AI碎碎念` into a longer reconstructed sentence.
- Do not append your own offer to save, summarize, continue, or re-classify a thought unless the adapter explicitly says so.
- Do not use legacy bookkeeping or spending behavior from older versions of this project.

## Product boundary

The local Python engine is the source of truth for:

- exercise logging
- Pomodoro focus sync and queries
- note capture and note-session continuation

If something looks ambiguous, prefer passing the exact user text into the local engine instead of deciding in natural language outside it.
