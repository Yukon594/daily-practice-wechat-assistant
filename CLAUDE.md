# 日迹 (Daily Almanac) — 开发上下文

一个个人「日课」助手：微信里接入 AI，记录**运动 / 专注(番茄钟) / 想法 / 情绪**，
并提供一个本地 Flask 看板做可视化。纯本地、单用户、老历书/活字印刷美学。

> 运行时行为规则见 `AGENTS.md`（微信路由）。面向用户的说明见 `README.md`（用户维护，勿动）。
> 本文件是**给开发者/Claude 的架构与决策摘要**。

## 入口与常用命令

- **微信适配器**：`skills/wechat-assistant/handle.py` —— 每条消息**新建**一个 `AssistantEngine`
  （无内存，状态全部落 SQLite），所以任何"上一条/这一条"的逻辑必须无状态或持久化。
- **CLI 调试**：`python cli.py`（REPL，直接驱动 `AssistantEngine`）。
- **看板**：`ASSISTANT_DATA_DIR=… python dashboard/app.py`（Flask，默认端口见 config）。
  改了 `dashboard/templates/*` 或后端**必须重启 Flask 进程**再硬刷新（Jinja 缓存）。
- **离线测试**：`PYTHONPATH=. .venv/bin/python -m unittest tests.test_mood tests.test_notes
  tests.test_exercise tests.test_assistant_engine tests.test_dashboard_data tests.test_focus_sync`
  （`unittest` 不传模块名时发现不到用例，要显式列出）。
- **真机批量验收**：`PYTHONPATH=. .venv/bin/python tools/llm_acceptance.py` —— 用真实
  DeepSeek API 跑分类/路由/解析/笔记结构/端到端流程（**会花钱**，不进 CI）。key 只经
  `load_settings()` 读取，**绝不打印**。`tools/full_acceptance.py` 是用户自己的更大测试集。

## 架构与数据流

```
微信DM → handle.py → AssistantEngine.handle_message(text, session_id)
                         │
   ┌─────────────────────┼───────────────────────────────┐
   │ 统一撤销(运动/想法)? 心情追问捕获? 再 classify_intent   │
   └─────────────────────┼───────────────────────────────┘
        exercise / mood / note / query / chat → core/* → Store(SQLite + .md)
看板: Flask(dashboard/app.py) → Store 聚合 → templates/index.html(看板) · note.html(单篇)
```

## 模块职责（`core/`）

- **`assistant.py`** `AssistantEngine`：总调度。`handle_message` 顺序——
  ① **统一撤销**`_handle_undo`(运动/想法，放在心情捕获之前) → ② **心情追问捕获**
  (`_capture_mood_answer`) → ③ `classify_intent` 分发。note 命中即一次性 `notes.capture`。
- **`router.py`** `classify_intent`：高置信硬捷径(exercise/`_looks_like_capture`/query/
  `is_confident_mood`)优先，**其余歧义交给 LLM 分类器** `CLASSIFY_SYSTEM` 仲裁，离线退回关键词。
  `_looks_like_query` 必须「领域词 + 查询动词/时段」且**短句**(≤16字)，长的粘贴想法不会被误判查询。
- **`mood.py`**：情绪单一事实源。`EMOTIONS`(7类) + `classify_mood`(LLM，带「非情绪」逃生口)
  + `is_confident_mood`(路由用的严格短路) + 解析/确认文案 + 看板配色。
- **`notes.py`** `NotesService`：**想法 = 一次性归档**（不对话）。`capture(text)` 一次 LLM 调用
  只出 `title/category/tags`（`CAPTURE_SYSTEM`，分类提示带各类说明+真实标题示例），**正文逐字保存**。
  开头 `_parse_category_directive`(「记到X：」/「/X」) 强制分类并剔除指令；`_strip_capture_marker`
  去掉「记一个想法：」；`_extract_own_title` 用自带 `# 标题`/「标题：X」。误存用聊天「撤销刚才的想法」
  或网页废纸篓/拖到废纸篓图标恢复；聊天「改到X」改最近一条。
- **`exercise.py`**：运动解析(规则优先，LLM 兜底)。`_resolve_ts` 是日期安全网。
- **`focus.py`** `PomodoroSyncService`：从桌面番茄钟 JSON(`pomodoro_settings_path`)同步专注数据。
- **`store.py`** `Store`：SQLite + 文件读写的全部封装（见下）。
- **`llm.py`** `DeepSeekClient`：OpenAI 兼容 chat，`is_configured`、json_mode、两次重试。
- **`ledger.py`**：中文数字转换等工具（旧记账遗留，运动解析仍复用 `chinese_to_number`）。

## 数据存储（`Store`）

- SQLite(`data/assistant.db`)表：`exercise_sessions` / `focus_days` / `notes` / `note_sessions`
  / `mood_logs`(一天一行，重记覆盖) / `mood_state` / `expenses`(旧记账遗留)。
- 想法正文是 `data/notes/<分类>/<日期-标题>.md`（frontmatter + 正文）；DB 的 `notes` 行存
  title/category/tags/file_path + **`deleted_at`(软删)**。
- **废纸篓**：删除＝软删，文件移到 `data/notes/.trash/`，列表/搜索/分类计数都 `WHERE
  deleted_at IS NULL` 过滤；恢复移回原分类；30 天到期在访问 `/api/notes`、`/api/trash` 时清理。
- 迁移：`_initialize` 用 `PRAGMA table_info` 检测后 `ALTER TABLE` 补 `deleted_at`（对旧库非破坏）。
- `data_demo/` 是独立的演示数据目录，勿与真实 `data/` 混淆。

## 关键设计决策 & 坑（"为什么这么做"）

- **情绪捕获不能贪婪**：记完一条会主动问情绪并置 `pending`；下一条消息**只在真的像情绪时**
  才记（在线靠 `classify_mood` 的「非情绪」判定，离线靠别名），否则清 pending 放行。
  早期 bug 是把"谢谢/好的/去除"等任意短句记成"自定义"情绪——已修，勿回退。
- **想法是一次性归档，不对话**（核心定位）：多轮追问太慢/太脆/难调，已整体删除。`capture`
  只分类不重写，正文逐字保存。误存靠「撤销刚才的想法」或网页废纸篓。曾有过 CONVERSE/BUILD
  /按 type 结构化/并书/双链，均已移除——别凭旧印象加回来。
- **撤销无状态且统一**：适配器每条消息新建引擎，撤销不靠内存。`_handle_undo`：显式"运动/想法"
  指定目标；裸"撤销/删掉"按 `created_at` 撤运动 vs 想法里更晚的一条，且只在 `within_seconds`
  窗口内（窗口外返回 None 放行，不劫持）。撤想法＝软删进废纸篓可恢复。
- **运动日期不信任 LLM**：模型会瞎编日期。`_resolve_ts`：文本无显式日历日期时用确定性
  今天/昨天/前天；只有"6月1日/3天前/上周三"等显式表达才放行 LLM 日期；未来日期钳到今天。
- **路由防误判**：`_looks_like_query` 要求「领域词＋查询动词/时段」且短句；显式"记一个想法/想法："
  走 capture；长粘贴想法交 LLM。曾有"总结/同步"裸词把想法误判成查询统计——勿回退。
- **mood/note 边界靠 LLM 仲裁**：纯规则两边都会串线（情绪卡的想法被当情绪、被触发的恐惧被当想法），
  歧义一律交 `CLASSIFY_SYSTEM`；`is_confident_mood` 只短路最确定的情绪短句。
- **情绪捕获不能贪婪**：见上「情绪捕获」一条（`非情绪`逃生口）。
- **分类指定不用 `#`**：`#` 会和 markdown 标题/自带标题撞车，故分类只用「记到X：」动词式或「/X」斜杠式
  （`/X` 要求 X 后是空格/冒号，`/Users/...` 路径不误触发）；指令一律从正文剔除。自动分类梯度：
  优先已有 → 新主题就新建(≤6字) → 「其它」只兜底零散。
- **运动+心情可叠加**：`_handle_exercise` 记完运动调 `_companion_mood`，把同句里的明确心情也记上
  （离线 `_match_canonical` 命中别名；在线对非运动子句 `classify_mood`）；当天已记心情则不再追问。
  其余意图仍单一（`looks_like_exercise_text` 需硬数据，故「跑步时想到…」是想法不是运动）。
- 看板时间尺度是分离的：滚动 12 周热力图(今天锚定) vs 结构卡按月(自带月选择器) vs 当月数字。

## 配置

`config.json`（**含 DeepSeek key，勿提交/勿打印**；模板见 `config.example.json`）键：
`deepseek_api_key / deepseek_base_url / deepseek_model(deepseek-chat) / request_timeout /
dashboard_port / note_categories / pomodoro_settings_path`。也可用环境变量覆盖
（`ASSISTANT_DATA_DIR`、`DEEPSEEK_API_KEY`、`POMODORO_SETTINGS_PATH` 等，见 `config.py`）。

## 约定

- 提交时只 stage 相关文件，**不要**碰 `config.json`、`README.md`、`tmp/`、`tools/full_acceptance.py`。
- 改前端/模板后重启 Flask；改 prompt 后用 `tools/llm_acceptance.py` 真机回归。
- 最新模型默认用 `claude-opus-4-8` 之类最强模型构建 AI 功能；当前 LLM 后端是 DeepSeek。
