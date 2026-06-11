# 日迹 · WeChat AI Assistant

一个本地优先的微信助手，把几类日常记录放进同一套工作流里：

- 运动记录
- 贴纸番茄钟专注同步
- 情绪记录
- 想法笔记整理

你可以先只用命令行和本地网页，不接微信也能完整使用。  
等本地跑通后，再接 OpenClaw 和微信。

## 这是什么

这套项目分成两层：

1. 本地 Python 引擎  
   负责解析你的输入、存 SQLite、写 Markdown、生成看板数据。
2. 微信通道  
   负责把微信消息转发给本地引擎，再把结果回给微信。

所以它不是“微信里临时拼 prompt 的机器人”，而是：

- CLI、微信、本地看板共用一套数据
- 不接微信也能先跑
- 以后换模型、换通道，核心数据和逻辑都还在

## 截图预览

> 以下截图全部来自仓库自带的隔离演示数据，不包含任何真实个人记录。

![Dashboard Exercise](assets/screenshots/dashboard-exercise.jpg)
![Dashboard Mood](assets/screenshots/dashboard-mood.jpg)
![Dashboard Focus](assets/screenshots/dashboard-focus.jpg)

## 现在能做什么

### 1. 记录运动

你可以直接说：

- `今天跑步 5 公里 32 分钟`
- `晚上练胸 45 分钟`
- `今天练了个上肢，差不多半小时`

当前支持识别这些运动类别：

- `跑步`
- `骑行`
- `游泳`
- `步行`
- `瑜伽`
- `羽毛球`
- `篮球`
- `足球`
- `力量训练`

解析方式是：

- 先用本地规则直接识别
- 实在太口语、太模糊时，再调用 LLM 做结构化补全

### 2. 同步贴纸番茄钟专注数据

你可以直接说：

- `看看这个月专注了多久`
- `这周专注怎么样`
- `同步一下番茄钟`

如果你已经在 macOS 上用贴纸番茄钟，程序会优先尝试自动读取这些常见路径：

- `~/Library/Application Support/com.stickerpomodoro.mac/settings.json`
- `~/Library/Application Support/com.stickerpomodoro/settings.json`

如果你的路径不同，再手动填写 `pomodoro_settings_path`。

### 3. 记录情绪

你可以直接说：

- `今天有点焦虑`
- `今天心情很好`
- `今天因为开会有点难过`
- `记录情绪`

看板里会按月历展示每天的情绪，点图标可以看备注。

### 4. 记录想法

直接把想法发给它（在别处聊透、总结好的内容尤其合适），它会 **一次落库**：自动起标题、归类、打标签，**正文原样保存，不追问**。例如：

- `我想给番茄钟加个多人协作`
- `我突然觉得代码廉价后更值钱的是取舍`
- `记一个想法：把番茄钟数据同步到看板`

想法存成 Markdown 到 `data/notes/<分类>/`，同时进入本地看板。

> 运动里顺带提到心情时（如 `今天健身 30 分钟，开心`），会**同时**记一条运动 + 一条心情。

## 想法分类是怎么互动的

记想法只做一件“智能”的事——**归到合适的分类**。不追问，自然又能纠错。

### 指定优先

在开头点一下分类，就强制归类，并把这段指令从正文里剔除：

- 动词式：`记到工作：今天和领导谈了加薪`、`记录到AI碎碎念：……`
- 斜杠式：`/工作 今天和领导谈了加薪`

分类后面接 `：`、空格、逗号都能触发；指定的分类不存在就当场新建。

### 没指定就自动归类

没写分类时，模型会参考你**已有的分类（连带每类下的真实示例）**自动归类：能套已有就套已有；明显是个新主题就新建一个简洁分类；只有真正零散的内容才进「其它」。

### 自带标题就用自带

如果内容开头本身就是标题（`# 标题` 或 `标题：X`），直接用它，不另起。

### 记错了能改、能撤

- 改分类：记完回一句 `改到生活感悟`，就改最近一条；网页里也能把想法拖到别的分类标签。
- 撤回：说 `撤销刚才的想法`，或在网页把想法**拖到废纸篓图标**。删除会进废纸篓，保留 30 天，可恢复。

> 早期版本会就每个想法多轮追问、再按类型结构化。实测追问又慢又难定提示词，已改成上面的“一次归档 + 分类”——你可以在别处把想法聊透、总结好，再丢进来归档。

## 安装后默认是什么状态

这个仓库默认是 **空数据**：

- 没有任何你的运动记录
- 没有你的专注历史
- 没有你的情绪和想法
- `config.json` 不会被提交
- `data/` 目录下的本地数据不会被提交

也就是说，别人克隆后看到的是一个干净项目，不会拿到你的私人记录。

## 目录结构

```text
.
├── README.md
├── requirements.txt
├── config.example.json
├── config.py
├── cli.py
├── core/
├── dashboard/
├── skills/wechat-assistant/
├── tools/seed_demo.py
├── tests/
└── data/                  # 首次运行后自动生成，本仓库默认不提交真实数据
```

## 数据存在哪里

- SQLite：`data/ledger.db`
- 想法笔记：`data/notes/<分类>/`
- 演示数据：`data_demo/`

## 微信适配层在哪里

仓库已经内置了 OpenClaw skill 和本地适配入口：

- [skills/wechat-assistant/SKILL.md](skills/wechat-assistant/SKILL.md)
- [skills/wechat-assistant/handle.py](skills/wechat-assistant/handle.py)

它现在的原则是：

- 微信端只负责转发
- 本地 Python 引擎负责解析、入库、查询
- 不在微信适配层里额外发明业务逻辑

## 当前边界

- 数据默认纯本地存储，不自动上云
- 看板不是实时轮询，刷新页面时才会重新拉摘要
- 番茄钟同步是按需触发，不是后台每隔几分钟自动抓
- 微信端目前更适合“收到消息后响应”，不适合作为稳定定时任务平台

## 安装与接入

### 你需要先下载什么

1. `Python 3`
2. 这个仓库代码
3. 一个可用的 LLM API key
4. `Node.js`
5. `OpenClaw`

### 新电脑最简单的一条命令

如果你是新电脑、还没下载这个项目，直接复制这一条：

```bash
curl -fsSL https://raw.githubusercontent.com/Yukon594/daily-practice-wechat-assistant/main/tools/bootstrap_from_github_macos.sh | bash
```

它会自动帮你：

- 从 GitHub 下载这个项目
- 安装到固定目录 `$HOME/daily-practice-wechat-assistant`
- 创建 `.venv`
- 安装依赖
- 生成 `config.json`
- 让你直接输入 LLM API key

安装完成后，项目就会放在：

```bash
$HOME/daily-practice-wechat-assistant
```

### 安装 OpenClaw

根据 OpenClaw 官方 Getting Started 文档，建议：

- Node.js 24
- 或至少 Node.js 22.19+

先检查：

```bash
node --version
```

安装 OpenClaw：

```bash
curl -fsSL https://openclaw.ai/install.sh | bash
```

如果命令还找不到，先把它加入 PATH：

```bash
export PATH="$HOME/.openclaw/bin:$PATH"
```

初始化向导：

```bash
openclaw onboard --install-daemon
```

### 接微信

安装微信插件并登录：

```bash
npx -y @tencent-weixin/openclaw-weixin-cli install
openclaw gateway restart
openclaw channels login --channel openclaw-weixin
```

建议补两条配置：

```bash
openclaw config set session.dmScope per-account-channel-peer
openclaw config set channels.openclaw-weixin.botAgent "WeChatAssistant/0.3.0"
```

### 打开面板看数据

如果你想直接打开 OpenClaw 面板，最稳的方式是运行：

```bash
bash "$HOME/daily-practice-wechat-assistant/tools/open_openclaw_dashboard_macos.sh"
```

如果你想看这个项目自己的本地看板，运行：

```bash
bash "$HOME/daily-practice-wechat-assistant/tools/run_dashboard_macos.sh"
```

## 测试

```bash
python3 -m unittest \
  tests.test_config \
  tests.test_exercise \
  tests.test_assistant_engine \
  tests.test_mood \
  tests.test_notes \
  tests.test_dashboard_data \
  tests.test_focus_sync
```

## 参考文档

- OpenClaw Getting Started: [https://docs.openclaw.ai/start/getting-started](https://docs.openclaw.ai/start/getting-started)
- OpenClaw WeChat Channel: [https://docs.openclaw.ai/channels/wechat](https://docs.openclaw.ai/channels/wechat)
