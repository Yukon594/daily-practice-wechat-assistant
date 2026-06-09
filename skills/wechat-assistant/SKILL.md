---
name: wechat-assistant
description: Route WeChat exercise logging, Pomodoro focus summaries, and note capture through the local Python engine in this workspace.
version: 0.3.0
---

# WeChat Assistant

Use this skill when this workspace is serving as a WeChat-facing assistant through OpenClaw.
The goal is to keep message handling deterministic by routing exercise logging, focus-sync queries, and idea capture through the local Python engine instead of re-implementing the logic in free-form chat.

## Strict proxy mode

When this skill applies, you are acting as a thin transport layer in front of the local Python engine.

Required behavior:

- Treat every incoming WeChat DM message as adapter input first, not as a free-form chat prompt.
- Pass the user's raw message to the adapter unchanged.
- Return the adapter's `reply` to the user as-is or with only trivial formatting cleanup.
- Reuse the same stable session id so the local engine can manage multi-turn note collection.

Forbidden behavior:

- Do not answer from your own reasoning before calling the adapter.
- Do not summarize, reinterpret, expand, or "improve" the user's message before passing it in.
- Do not append your own follow-up like "要不要我也帮你记下来" unless the adapter itself says that.
- Do not paraphrase a successful save into a different category/path than what the adapter returned.
- Do not use old bookkeeping / spending behavior from earlier versions of this workspace.

## When to use it

- The incoming message is a WeChat private message in this workspace.
- The user is trying to记录运动, 查询番茄钟专注情况, 记录想法, or continue an earlier note-collection flow.
- You want the same local SQLite + Markdown storage used by `cli.py` and the dashboard.

## How to handle a message

1. Call the local adapter from the workspace root before producing any user-facing answer:

```bash
python3 skills/wechat-assistant/handle.py --stdin --format json --channel wechat --session-id "<stable-session-id>"
```

2. Pipe the raw user message into stdin with no extra prefix, summary, or added context.

3. Return the adapter's `reply` field to the user with no substantive rewriting.

4. If the adapter succeeds, stop there. Do not continue the conversation on your own.

## Session rules

- Reuse the same session id across turns for the same WeChat conversation.
- Prefer a session id that isolates by account + channel + peer.
- Recommended patterns:
  - DM with account id: `wechat:<account-id>:<peer-id>`
  - DM without account id: `wechat:<peer-id>`
  - Last resort: `wechat:default`

This matters because note collection is multi-turn. If the session id changes, `记下来` will not finalize the right draft.

## Behavior expectations

- For运动记录, trust the local adapter's structured parsing and storage.
- For想法记录, let the adapter manage the multi-turn note session.
- For查询, let the adapter answer from SQLite and the Pomodoro sync layer instead of estimating from memory.
- If the message is ordinary chat, the adapter can still return a short reply.
- After a note is saved, treat the next user message as a fresh adapter turn. Do not keep offering to save the previous discussion again.

## Failure handling

- If the adapter reports missing config or runtime issues, explain the problem briefly.
- Mention that the local dashboard lives at `http://127.0.0.1:9900`.
- Do not run `tools/seed_demo.py` or clear any data in response to WeChat messages.
