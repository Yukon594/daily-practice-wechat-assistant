# 日课 · WeChat AI Assistant

一个本地优先的微信助手，把四类日常记录收进同一套工作流里：

- 运动记录
- 贴纸番茄钟专注同步
- 情绪记录
- 想法笔记整理

微信、CLI 和本地看板共用同一套 SQLite + Markdown 数据。仓库默认 **不附带任何个人数据**；安装后是空数据状态，需要你自己开始记录，或者单独导入演示数据预览界面。

## 截图预览

> 以下截图全部来自仓库内置的隔离演示数据，不包含任何真实个人记录。

![Dashboard Exercise](assets/screenshots/dashboard-exercise.jpg)
![Dashboard Mood](assets/screenshots/dashboard-mood.jpg)
![Dashboard Focus](assets/screenshots/dashboard-focus.jpg)

## 现在能做什么

### 1. 记录运动

示例：

- `今天跑步 5 公里 32 分钟`
- `晚上练胸 45 分钟`
- `今天练了个上肢，差不多半小时`

当前会识别并记录这些运动类别：

- `跑步`
- `骑行`
- `游泳`
- `步行`
- `瑜伽`
- `羽毛球`
- `篮球`
- `足球`
- `力量训练`

解析逻辑是 **本地规则优先，LLM 结构化补全兜底**。也就是说，常规句子走本地解析；更口语、模糊的表达才会调用模型补齐字段。

### 2. 同步贴纸番茄钟专注数据

示例：

- `看看这个月专注了多久`
- `这周专注怎么样`
- `同步一下番茄钟`

如果你已经在 macOS 上使用贴纸番茄钟，程序会优先尝试自动读取这些常见路径：

- `~/Library/Application Support/com.liuyuhang.stickerpomodoro.mac/settings.json`
- `~/Library/Application Support/com.liuyuhang.stickerpomodoro/settings.json`

如果你的路径不同，再手动填写 `pomodoro_settings_path` 即可。

### 3. 记录情绪

示例：

- `今天有点焦虑`
- `心情不错`
- `记录情绪`

看板里会按月历展示当天情绪，点击图标可以查看备注。

### 4. 整理想法笔记

示例：

- `我想给番茄钟加个多人协作`
- `我突然觉得代码廉价后更值钱的是取舍`
- `记下来`

想法会被整理成 Markdown 文件，存到 `data/notes/<分类>/` 下，并同步进入本地看板。

## 安装后默认是什么状态

这个仓库默认是 **空数据**：

- 没有内置你的运动记录
- 没有内置你的专注历史
- 没有内置你的情绪和想法
- `config.json` 不会被提交
- `data/` 目录下的本地数据不会被提交

相关忽略规则在 [.gitignore](.gitignore) 里已经配好。

## 快速开始

### 1. 安装依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 创建配置文件

```bash
cp config.example.json config.json
```

至少需要填写：

- `deepseek_api_key`

可选填写：

- `pomodoro_settings_path`

如果你就是标准的 macOS 贴纸番茄钟用户，通常可以先把 `pomodoro_settings_path` 留空，让程序自动找常见路径。

### 3. 先用 CLI 跑通

```bash
python3 cli.py
```

单条测试也可以：

```bash
python3 cli.py --once "今天跑步5公里 32分钟"
python3 cli.py --once "看看这个月专注了多久"
python3 cli.py --once "我想给番茄钟加个周回顾入口"
```

### 4. 启动本地看板

```bash
python3 dashboard/app.py
```

然后打开：

- [http://127.0.0.1:9900](http://127.0.0.1:9900)

## 想先看效果？用隔离演示数据

仓库带了一个单独的演示数据工具，写入的是 `data_demo/`，**不会碰你的真实数据**。

### 导入演示数据

```bash
python3 tools/seed_demo.py
```

### 用演示数据启动看板

```bash
ASSISTANT_DATA_DIR=./data_demo python3 dashboard/app.py
```

### 清空演示数据

```bash
python3 tools/seed_demo.py --clear
```

演示数据包含：

- 示例运动记录
- 示例番茄钟专注天
- 示例情绪月历
- 示例想法笔记

## 数据存在哪里

- SQLite：`data/ledger.db`
- 想法笔记：`data/notes/<分类>/`
- 演示数据：`data_demo/`

## 微信接入

仓库已经包含 OpenClaw skill：

- [skills/wechat-assistant/SKILL.md](skills/wechat-assistant/SKILL.md)
- [skills/wechat-assistant/handle.py](skills/wechat-assistant/handle.py)

它的设计原则是：

- 微信消息只做通道适配
- 本地 Python 引擎负责真正的解析、入库、查询
- CLI / 微信 / 看板三条链路共用同一套数据

### 1. 初始化 OpenClaw

```bash
~/.openclaw/bin/openclaw onboard \
  --non-interactive \
  --accept-risk \
  --mode local \
  --workspace "$(pwd)" \
  --auth-choice deepseek-api-key \
  --deepseek-api-key "$DEEPSEEK_API_KEY" \
  --install-daemon
```

### 2. 安装微信渠道插件

```bash
PATH="$HOME/.openclaw/bin:$PATH" npx -y @tencent-weixin/openclaw-weixin-cli install
```

### 3. 建议配置

```bash
~/.openclaw/bin/openclaw config set session.dmScope per-account-channel-peer
~/.openclaw/bin/openclaw config set channels.openclaw-weixin.botAgent "WeChatAssistant/0.3.0"
```

### 4. 本地验证适配层

```bash
python3 skills/wechat-assistant/handle.py --text "今天跑步5公里 32分钟" --format json
python3 skills/wechat-assistant/handle.py --text "看看这个月专注了多久" --format json
python3 skills/wechat-assistant/handle.py --text "我想给番茄钟加个周回顾入口" --session-id wechat:test
python3 skills/wechat-assistant/handle.py --text "记下来" --session-id wechat:test
```

## 对贴纸番茄钟用户最简单的安装方式

如果你已经在 macOS 上使用贴纸番茄钟，最简流程其实只有三步：

1. 安装依赖
2. 在 `config.json` 里填上 `deepseek_api_key`
3. 直接运行：

```bash
python3 cli.py
python3 dashboard/app.py
```

如果专注数据没有自动出现，再回头补 `pomodoro_settings_path`。

## 测试

```bash
python3 -m unittest tests.test_exercise tests.test_assistant_engine tests.test_mood tests.test_notes tests.test_dashboard_data tests.test_focus_sync
```

## 当前边界

- 数据默认是纯本地存储，不自动上云
- 看板不是实时轮询，刷新页面时会重新拉摘要
- 番茄钟同步是按需触发：打开看板、查询专注、或手动要求同步时执行
- 微信端目前更适合被动响应，不建议依赖它做稳定的定时主动推送
