# ai-kb · 把跟 AI 的聊天变成能检索的知识库

> 让 AI 自动把每次讨论记下来，存进你自己的 GitHub **私有**仓库，换台机器也还在；还能做成**加密**网页看板，随时随地查。

```
❌ 没有它                    ✅ 有了它
今天聊了什么？ → 忘了          今天聊了什么？ → 问一句就有，按项目分好
结论是什么？   → 记不清         结论是什么？   → decisions/ 写得清清楚楚
待办有哪些？   → 混在几千条消息里  待办有哪些？   → todo.md 一眼看完，还标了优先级
换台电脑       → 什么都没有      换台电脑       → git clone 就有了
```

版本 **v2.2.1**（更新记录见 [CHANGELOG.md](CHANGELOG.md)）。仅需 `python3` + `git`；加密看板另需 `node`。

---

## 安装：一条命令

```bash
curl -fsSL https://raw.githubusercontent.com/GalaxyStar-w/ai-kb/main/bootstrap.sh | bash
```

不想直接执行远程脚本？先看一眼再装：

```bash
git clone https://github.com/GalaxyStar-w/ai-kb.git && cd ai-kb
./bootstrap.sh --dry-run        # 演练：只显示会改哪些配置，不写任何文件
./bootstrap.sh --check          # 只体检依赖与现状，什么都不改
./bootstrap.sh                  # 正式安装
```

`bootstrap.sh` 会：体检依赖 → 创建知识库骨架（默认 `~/ai-knowledge-base`）→ 把**完整工具**放进知识库 `_tool/`（换机器时从这里恢复）→ 安装到 `~/.ai-kb/` → 自动探测你的 agent 并配置 hook → 自动安装 skill → 跑 `doctor` 体检。**幂等**，重复运行安全。

| 参数 | 作用 |
|---|---|
| `--kb <路径>` | 指定知识库位置 |
| `--remote <私有仓库地址>` | 关联/克隆已有的知识库仓库（地址写成 `https://用户名@github.com/...` 可固定账号，见下） |
| `--check` | 只体检，不改任何东西（新机器推荐先跑） |
| `--dry-run` | 演练：预览 hook 配置会怎么改，不写任何文件 |
| `--no-hook` | 不配 hook（给没有 hook 的 agent 用） |
| `--sync-tool` | 已有知识库时，把最新工具同步进 `<KB>/_tool/`（被覆盖且不同的旧文件先备份到 `_meta/tool-backup/`） |

**装完只需两件事**：① 完全重启 agent 让 hook 生效（Claude Code 直接重启；WorkBuddy 用 Cmd+Q 彻底退出，关窗口不算）；② 对 agent 说一句：「按 `~/ai-knowledge-base/AI-START-HERE.md` 走」。

> **让另一个 AI agent 自己装**：对它说「阅读并执行本仓库的 `AGENT-SETUP.md`」。它会自己完成前置检查、隔离自测、预览并安装、申请最小权限、向你汇报，不需要你再提供额外信息。

---

## 它怎么工作

4 个 hook，**不用你提醒，AI 自己会记**：

| 时机 | 自动做什么 |
|---|---|
| 会话开始（启动/恢复/清屏/压缩后） | 注入完整规则 + 全部项目概览 + 「🔴 现在最该看的」 |
| 你每发一条消息 | 提醒 AI：这轮有新内容就记下来 |
| 上下文快满、要压缩前 | 要求 AI 先把没记的抢救下来 |
| AI 答完 | 检查有没有漏记 + 自动提交、后台推送到私有仓库 |

**知识库结构**（每个项目一个目录）：

```
<知识库>/
├── README.md              脚本自动生成的总页（所有项目汇总 + 待办导航）
├── AI-START-HERE.md       给 AI 的总入口
├── _meta/                 路径映射、配置、同步状态、工具备份
├── _tool/                 完整工具（换机器时从这里恢复）
└── projects/<项目名>/
    ├── README.md          项目首页（简介 / 状态 / 关键决议 + 自动生成的档案导航）
    ├── todo.md            待办与优化清单（未完成/已完成，带优先级、文件:行号、来源）
    ├── questions.md       待讨论问题（未决/已决议）——之前该聊的不会丢
    ├── log.md             只追加的时间线日志
    ├── glossary.md        术语、缩写、系统/表名含义
    ├── discussions/       讨论纪要：自包含，写明背景、过程、被否决的方案、结论依据
    ├── decisions/         重要决议记录
    └── artifacts/         讨论中生成的文件原件 + INDEX.md
```

- **忠实**：你明确说的照实记；AI 补充的分析标注「（AI 补充）」，不确定的标「（待核实）」。
- **项目归属**：项目名 = 当前目录的 git 根目录名；同名不同路径自动加哈希；临时目录、会话工作区、家目录归 `_general`；拿不准 AI 会先问你。
- **查细节**：问「上次为什么没选 X」，AI 会先 `search`、读原文再回答，而不是凭记忆。

---

## 命令

在装好后用 `AI_KB_DIR=<知识库> python3 ~/.ai-kb/kb.py <命令>`：

| 命令 | 作用 |
|---|---|
| `context` | 开会话时加载规则 + 全项目概览 + 🔴 现在最该看的 + 当前项目要点 |
| `search <词> …` | 全文搜索（多个词为「或」，支持正则），返回 `文件:行号:内容` |
| `status` | 各项目统计与同步状态 |
| **`doctor`** | **体检**：依赖 / 结构 / 仓库可见性 / 同步状态 / 路径映射 / 项目识别 / 看板安全，一次查完并给人话结论（**只读**） |
| **`audit`** | **盘点**：确认「所有内容都在」（只读） |
| `build` | 重新生成各项目 README 自动区块与根总页 |
| `sync` | 提交 + 拉取 + 推送（含私有校验与密钥扫描） |
| `init` | 初始化骨架（幂等） |
| `clean-stale` | 清理指向已不存在目录的路径映射（默认预览，`KB_CONFIRM=1` 才真改，只改 `map.json`） |
| `export [路径]` | 导出整个知识库为单个 markdown，便于离线阅读 |

**新机器装完后第一件事：`doctor`。**

---

## 🔒 加密看板

`build_dashboard.py` 把知识库做成**网页看板**（总览 / 项目页 / 文档 / 全文搜索），可部署到 Cloudflare Pages，手机电脑都能查。

**为什么需要加密**：仓库私有 ≠ 网页私有。`*.pages.dev` 默认任何拿到网址的人都能读；而 Cloudflare Zero Trust 需要自有域名，Worker 登录门在部分网络（如国内）的 `workers.dev` 不通，前端密码框又能被「直接访问文件」绕过。

**做法**：构建时用口令把**全部内容**（页面、导航、搜索索引、每篇文档、文件名）端到端加密成密文再部署，服务器上只有密文。浏览器里输入口令后，用 WebCrypto 在本地解密。**不依赖域名、不依赖 Worker、不依赖任何服务端配置**，所以在你被限制的网络环境下也能用。

```bash
# 1) 首次：生成强口令（只显示这一次，请立刻存进密码管理器）
python3 _tool/build_dashboard.py --gen-pass          # 或 --set-pass：自己输入（不回显，至少 12 位）
python3 _tool/build_dashboard.py --show-pass         # 之后在这台机器上随时再看一次口令（仅真实终端）
# 2) 本机预览（明文站，仅限本机 file:// 打开，禁止部署）
python3 _tool/build_dashboard.py --plain-local
# 3) 部署：把 Cloudflare API Token 放到 ~/.ai-kb/cf_token（chmod 600）
bash _tool/deploy_dashboard.sh --rotate              # 首次：新建随机名项目并部署加密站
bash _tool/deploy_dashboard.sh                       # 之后：构建 + 部署
```

**如果以前部署过明文版本**：Cloudflare Pages 会保留**所有历史部署**，每个都有独立网址，旧的明文版仍能访问。迁移步骤：

```bash
bash _tool/deploy_dashboard.sh --rotate                          # 新建随机名新项目并部署加密站（不删旧的）
# 确认新站能打开、口令能解锁之后：
KB_CONFIRM=1 bash _tool/deploy_dashboard.sh --purge-old          # 删除旧项目及其全部历史部署（旧网址失效）
```

清理是**删除操作**（删的是 Cloudflare 上的旧站点，不是知识库内容），必须加 `KB_CONFIRM=1`；也不会误删当前项目。只想清历史部署用 `--purge-history`；`--status` 只读查看。

**密码学**：PBKDF2-HMAC-SHA256（60 万次迭代）派生密钥，AES-256-GCM 认证加密（口令错误或密文被篡改都解密失败）；文件名是 HMAC 的哈希，服务器上看不出项目名；密文**确定性**（内容不变则逐字节不变，增量部署只传改动文件）；Node 与浏览器内置能力，无第三方依赖。口令只经环境变量/文件（`~/.ai-kb/dashboard_pass`，600）传给构建，**绝不进知识库、绝不进命令行参数**。

**请知道的局限**：
- 密文是公开的，别人可以**离线暴力猜口令**：口令强度决定安全性。请用 `--gen-pass`（约 120 位熵）或 ≥16 位混合字符。
- 能看到的元数据：文件个数与大小、构建时间。看不到：项目名、文件名、任何内容。
- **口令存哪、怎么找回**：口令存在构建机的 `~/.ai-kb/dashboard_pass`（600，不进知识库）；在那台机器上随时 `--show-pass` 查看。口令只会显示在**真实终端**里——由 AI 或脚本调用时（stdout 不是终端）不会打印，避免进入会话记录/日志。登录页是标准密码框，浏览器/密码管理器（1Password、iCloud 钥匙串等）可以保存并在手机上自动填充，不必手敲。
- 只有「构建机上的文件」和「你自己的备份」都丢了才无法解锁：那时只能换新口令重新构建部署（知识库本身不受影响）。为什么不能由服务端/AI 替你保管：端到端加密的意义就是除了你没人能解开，口令一旦放在别人能碰到的地方，加密就白做了。
- 浏览器需要 HTTPS（WebCrypto 限制；`localhost` 也可）。「在这台设备上记住」会把**派生后的密钥**存在该浏览器的本地存储里，公共电脑请不要勾选；页面右下角有「🔒 锁定」。
- 构建需要 Node.js ≥ 16；部署需要 `wrangler`（脚本会自动找，找不到用 `npx`）。

---

## 三层安全设计

| 保险 | 作用 |
|---|---|
| **只推私有仓库** | 推送前检查可见性，远程是 PUBLIC（或无法确认）就拒绝推送 |
| **密钥扫描** | 提交前扫描（AWS/GitHub/Slack token、`sk-` key、私钥、Bearer、URL 里的账号密码、`password=` 之类赋值），发现整批拦住并写出 `_meta/SYNC_BLOCKED.md`；确属误报的行内加 `kb-allow` |
| **不许删文件** | 10 个命令没有一个能删文件；规则里写死「删之前必须问用户」 |
| **改配置先备份** | 安装器改你的 `settings.json` 前自动备份、严格解析、解析失败就不动、只增删自己写的 hook |

---

## 兼容性

| 能力 | Claude Code | WorkBuddy / CodeBuddy | 其他 agent |
|---|---|---|---|
| 会话开始自动加载 | ✅ hook | ✅ hook | ⚠️ 靠指令让 agent 先跑 `kb.py context` |
| 每轮提醒 | ✅ hook | ✅ hook | ❌ |
| 压缩前保护 | ✅ hook | ✅ hook | ⚠️ 仅靠指令 |
| 回合结束自动提交推送 | ✅ hook | ✅ hook | ❌ 靠指令跑 `kb.py sync` |

实测：Claude Code（含全新环境端到端）、WorkBuddy 的四个 hook 事件。Codex / Gemini CLI / Cursor / Windsurf **未实测**，原理上能执行 shell、遵守全局指令即可用（无 hook 则自动化程度低一档）。多个 agent 可共用同一知识库目录；装了多个时安装器给每个都配 hook。

**平台**：macOS / Linux（需要 bash + python3 + git）。Windows 原生不支持，请用 WSL 2 或 Git Bash。

---

## 准备私有仓库与多账号

1. 在 GitHub 新建一个**私有（Private）**空仓库；已有仓库请确认是 Private（Settings → General → Danger Zone → Change visibility）。
2. `gh auth login` 登录对应账号，并确认有写权限（`gh auth status`）。
3. **同时有多个 GitHub 账号时**（如公司 + 个人）：`gh` 同一时间只有一个「活动账号」，后台自动推送会因此失败。把远程地址写成**带用户名**的形式，工具就固定用该账号检查和推送：

```bash
git -C ~/ai-knowledge-base remote set-url origin https://<你的用户名>@github.com/<你的用户名>/<仓库>.git
```

原理：用 `gh auth token --user <用户名>` 取该账号 token，仅通过环境变量传给 git 作临时凭据，不写入命令行、配置或磁盘（需 gh ≥ 2.40）。`bootstrap.sh --remote` 的克隆也遵循同样规则。

4. 没有 `gh` 时默认拒绝推送；可在 `_meta/config.json` 设 `"allow_unverified_push": true` 自行承担风险。

---

## 授权 agent 写入知识库（必做）

知识库在项目目录之外，agent 默认通常只能写当前项目目录。Claude Code：在 `~/.claude/settings.json` 加入（换成绝对路径；目录必须在会话启动前已存在）：

```json
{
  "permissions": { "additionalDirectories": ["/Users/你/ai-knowledge-base"] },
  "env": { "AI_KB_DIR": "/Users/你/ai-knowledge-base" }
}
```

想免确认，再在 `permissions.allow` 里为该目录加 `Edit(~/ai-knowledge-base/**)`。其他 agent 请把该目录加入其「可写目录/工作区」并允许执行 `python3 ~/.ai-kb/kb.py ...`。

---

## 手动配置 hook（可选）

安装器没识别出你的 agent，或想自己配：把下面合并到配置文件（Claude Code `~/.claude/settings.json`；WorkBuddy `~/.workbuddy/settings.json`；CodeBuddy `~/.codebuddy/settings.json`），把 `__KB__` 换成知识库绝对路径。**`SessionStart` 不要加 `startup` 限制**，否则会话恢复/清屏/压缩之后规则不会重新注入。

```json
{
  "hooks": {
    "SessionStart":     [{ "matcher": "*", "hooks": [{ "type": "command", "timeout": 45, "command": "AI_KB_DIR=\"__KB__\" python3 ~/.ai-kb/kb.py sessionstart" }] }],
    "UserPromptSubmit": [{ "matcher": "*", "hooks": [{ "type": "command", "timeout": 10, "command": "AI_KB_DIR=\"__KB__\" python3 ~/.ai-kb/kb.py prompt" }] }],
    "PreCompact":       [{ "matcher": "*", "hooks": [{ "type": "command", "timeout": 15, "command": "AI_KB_DIR=\"__KB__\" python3 ~/.ai-kb/kb.py precompact" }] }],
    "Stop":             [{ "matcher": "*", "hooks": [{ "type": "command", "timeout": 30, "command": "AI_KB_DIR=\"__KB__\" python3 ~/.ai-kb/kb.py stop" }] }]
  }
}
```

改完**必须完全重启 agent**。也可用 Claude Code 插件：`claude --plugin-dir <本仓库>/claude-code/ai-kb`（规则由 hook 注入，无需改 CLAUDE.md）。

---

## 同步机制

- **会话开始**：先本地提交，再 `pull --rebase --autostash`（冲突则放弃合并并告警，不会弄坏内容）。
- **每轮结束**：重建总页 → 密钥扫描 → 提交 → **后台推送**（不拖慢对话）。
- **推送前**：检查仓库私有；失败或被拒时写入 `_meta/.sync-status.json`，下次会话开场告警。
- **多机器**：推送前先拉取；两台机器同时改同一文件可能冲突，工具会告警而不自动覆盖。
- **换电脑 / 恢复**：`git clone <私有知识库> ~/ai-knowledge-base`，再 `bash ~/ai-knowledge-base/_tool/bootstrap.sh`，新会话开始时自动加载。

---

## 从旧会话导入（可选）

`extract_sessions.py` 把 **WorkBuddy**（`~/.workbuddy/projects`）和 **Claude Code**（`~/.claude/projects`）的历史会话提炼成可读纪要（只取用户提问与助手文字回答，每条回答截到 1500 字），**自动脱敏**疑似凭证后输出，纯只读；`distill_sessions.py` 再从中提取结论/待办/决议。

```bash
python3 extract_sessions.py --all ~/kb-extract [--source claude|workbuddy]
```

注意：会话原文比精炼档案敏感得多，**入库前请人工浏览**；这也与「只存精炼档案、不存原始对话」的默认做法相反，请自行决定是否导入。

---

## 日常使用

正常工作即可。想主动操作时直接说：「看下总页 / 还有什么没做」「之前为什么决定 X」「搜一下知识库里关于 Y」「整理一下这个项目的档案」「审计一下最近有没有漏记」「同步到 GitHub」。

**自测**：`bash universal/selftest.sh`（62 项，在临时知识库里跑，不碰真实数据；macOS 自带 bash 3.2 可直接运行）。涵盖：初始化与项目识别、总页与搜索、密钥拦截、推送保险、安装器改配置的安全性、bootstrap 与 `_tool/` 完整性、`doctor`/`audit`/`export`/`clean-stale`、看板加密（含错误口令、密文无明文泄露、确定性）、会话脱敏。

---

## 已知局限

- 自动记录依赖模型遵守规则；hook 与审计是兜底，不是绝对保证。Stop 检查是启发式的（回复较长或改了文件才检查），很短但含结论的回复可能漏检。
- 默认只存精炼档案和产物，不存完整原始对话：完整性取决于 AI 整理时不遗漏。
- 没有 hook 的 agent 漏记概率更高，建议定期让它「审计漏记」。
- 超长对话、多次压缩后的表现尚未长期验证。
- 密钥扫描基于规则，不保证发现所有敏感信息；**不要把敏感内容讲给 AI 后指望工具兜底**。
- 看板加密的安全性取决于口令强度（见上）。

## 隐私与安全

- 知识库可能含公司相关信息：只放你**自己的私有仓库**，不要放公开仓库或公开同步目录。
- 脚本不联网（除 `git` / `gh` / 你主动运行的 `deploy_dashboard.sh`），只读写知识库目录与 `~/.ai-kb/`。
- 分享本工具前，确认没有带入你自己的知识库内容（本仓库只含脚本与空模板）。

## 卸载

- Claude Code 插件：去掉 `--plugin-dir`（或在 `/plugin` 禁用）；hook 方式：删除 `settings.json` 里命令含 `kb.py` 的条目（改动前的备份在 `settings.json.bak-ai-kb-*`），删除 `AI_KB_DIR`。
- 通用层：删除 `~/.ai-kb/`，并从全局指令文件中删除 `<!-- ai-kb:begin -->` 到 `<!-- ai-kb:end -->` 之间的内容。
- 知识库目录和 GitHub 仓库是你的数据，想保留就保留。

## 仓库内容

```
bootstrap.sh            一键安装（支持 curl | bash 自举）
universal/              kb.py · rules.md · install.sh · selftest.sh · AGENT-INSTRUCTIONS.md
claude-code/ai-kb/      Claude Code 插件版（hooks + skill + 脚本）
skill/SKILL.md          让 agent 自动发现这套工具的 skill
AGENT-SETUP.md          给 AI agent 看的安装手册
AI-START-HERE.md        给使用知识库的 AI 的总入口
build_dashboard.py      构建（加密）看板
vault_encrypt.mjs       看板加密核心（Node 内置 crypto）
deploy_dashboard.sh     部署/轮换/清理 Cloudflare Pages
_dashboard_template/    看板页面模板
extract_sessions.py     从 WorkBuddy / Claude Code 会话提炼纪要（自动脱敏）
distill_sessions.py     从会话归档提取结论/待办/决议
LICENSE                 MIT
```
