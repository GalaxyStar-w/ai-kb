# ai-kb · 把跟 AI 的聊天变成能检索的知识库

> 让AI 自动把每次讨论记下来，存进 GitHub私有仓库，换台机器也还在。

```
❌ 没有它          ✅ 有了它
今天聊了什么？→忘了   今天聊了什么？ → 问一句就有，按项目分好
结论是什么？   → 记不清   结论是什么？   → decisions/ 写得清清楚楚
待办有哪些？   → 混在几千条消息里  待办有哪些？   → todo.md 一眼看完，还标了优先级
换台电脑       → 什么都没有  换台电脑 → git clone 就有了
```

---

## 安装：一条命令

```bash
git clone https://github.com/GalaxyStar-w/ai-kb.git
cd ai-kb
./bootstrap.sh
```

`bootstrap.sh` 会自动完成：

| 步骤 | 做什么 |
|---|---|
| 1 | 体检依赖（python3 / git / gh 登录状态） |
| 2 | 创建知识库骨架 `~/ai-knowledge-base`（或 `--remote` 关联你的私有仓库） |
| 3 | 安装工具到 `~/.ai-kb/` |
| 4 | **自动探测你的 agent 平台**并配置 hook |
| 5 | 跑 `doctor` 体检 + `audit` 盘点 |

**装完只需两件事**：

1. **重启 agent**让 hook 生效
   （WorkBuddy 用 Cmd+Q 彻底退出，关窗口不算；Claude Code 直接重启）
2. **跟 agent 说一句话**：
   > 「按 `~/ai-knowledge-base/AI-START-HERE.md` 走」

它就会知道：你是谁、知识库怎么用、有哪些硬性规则、现在该管什么。

### 常用参数

```bash
./bootstrap.sh --check                    # 只体检，什么都不改（推荐新机器先跑）
./bootstrap.sh --remote <私有仓库地址>      # 关联已有的知识库仓库
./bootstrap.sh --kb <路径>                 # 指定知识库位置
./bootstrap.sh --no-hook                   # 不配 hook（无 hook 的 agent 用）
```

### 不用 agent 也能用

装完后你可以直接用命令：

```bash
AI_KB_DIR=~/ai-knowledge-base python3 ~/.ai-kb/kb.py doctor   # 体检
AI_KB_DIR=~/ai-knowledge-base python3 ~/.ai-kb/kb.py search 关键词
AI_KB_DIR=~/ai-knowledge-base python3 ~/.ai-kb/kb.py audit    # 盘点
```

---


---

## 🤖 让 AI 自动知道这个工具（推荐）

把 `skill/SKILL.md` 放到你的 agent 技能目录，AI 就会自动知道有这套东西：

| agent | 放哪 |
|---|---|
| WorkBuddy | `~/.workbuddy/skills/ai-kb/SKILL.md` |
| Claude Code | `~/.claude/skills/ai-kb/SKILL.md` |

**放完之后，用户只要说一句「装一下 ai-kb」**，AI 会自己：
读 skill → clone 仓库 → 跑 bootstrap → 提醒重启 → 开始按规则工作。

Skill 里写清了：安装命令、三条核心命令、**四条硬性规则**（不许删 / 改文件先问 /只认实测 / 不写凭证）、
知识库结构、每轮该写什么、回答历史问题的标准流程。

## 🖥 新机器一行命令

```bash
ai-kb
```

（首次会自动 clone 工具仓库然后执行 bootstrap。也可以用 `--check` 只体检。）


## 它怎么工作：4 个 hook（自动触发点）

**不用你提醒，AI 自己会记：**

| 时机 | 自动做什么 |
|---|---|
| 开会话时 | AI 一上来就知道你的知识库长什么样、有哪些待办、现在该管什么 |
| 你每发一条消息 | 提醒 AI「这轮有新内容就记下来」 |
| 上下文快满了 | 要求 AI 先把没记的抢救下来再压缩 |
| AI 答完 | 检查有没有漏记 + 自动提交推送到 GitHub |

---

## 命令

| 命令 | 作用 |
|---|---|
| `context` | 开会话时加载规则 + 概览 |
| `build` | 重新生成总页 |
| `search <词>` | 搜全部历史讨论 |
| `status` | 各项目统计 |
| **`doctor`** | **体检**：15 项健康检查（换机器后先跑这个） |
| **`audit`** | **盘点**：确认「所有内容都在」 |
| `sync` | 提交推送到 GitHub |
| `init` | 初始化目录 |
| `clean-stale` | 清失效路径映射（有预览保护） |
| `export` | 导出成单个 markdown |

**知识库结构**：每个项目一个目录，含`README.md` / `todo.md` / `questions.md` /
`log.md` / `glossary.md` / `discussions/`（讨论纪要）/ `decisions/`（决议）/ `artifacts/`（产物原件）。

---

## 三层安全设计

|保险 | 作用 |
|---|---|
| **只推私有仓库** | 检测到远程是 PUBLIC 就拒绝推送 |
| **密钥扫描** | 提交前扫一遍，发现真 key 就整批拦住 |
| **不许删文件** | 10 个命令**没有一个能删文件**；规则里写死「删之前必须问用户」 |

---

## 兼容性

| 能力 | Claude Code | WorkBuddy / CodeBuddy | 其他 agent |
|---|---|---|---|
| 会话开始自动加载 | ✅ hook | ✅ hook | ⚠️ 靠指令 |
| 每轮提醒 | ✅ hook | ✅ hook | ❌ |
| 压缩前保护 | ✅ hook | ✅ hook | ⚠️ 靠指令 |
| 回合结束自动提交 | ✅ hook | ✅ hook | ❌ 靠指令 |

Claude Code 与 WorkBuddy / CodeBuddy 都实测通过；Codex / Gemini CLI / Cursor / Windsurf 未实测。

**多agent 共用同一知识库**：一台机器上装了多个 agent（既开WorkBuddy 又用 Claude Code）时，
安装脚本会**给每个都配好 hook**，它们共用同一个知识库目录 —— 谁都能读写同一批记录。
已实测：双 agent 场景下两个平台的 hook 都正确写入，互不干扰。

**没有 hook 的 agent 也能用**，只是自动化程度低一档。

---

## 换机器 / 恢复

```bash
git clone <你的私有知识库> ~/ai-knowledge-base
cd <本仓库路径> && ./universal/install.sh
```

两条命令即可恢复（知识库 + 工具 + hook 配置）。

---

## 工具包内容

```
universal/          纯工具（install.sh / kb.py / rules.md / selftest.sh）
claude-code/        Claude Code 插件版
AGENT-SETUP.md      给 AI agent 看的安装手册
extract_sessions.py 从 WorkBuddy/Claude Code 会话记录提炼纪要
distill_sessions.py 从会话中提取结论 / 待办 / 决议
LICENSE             MIT
```

---

# 以下为完整文档

# ai-kb 使用手册（v2.0.0）

把你和 AI 的**所有讨论**自动沉淀成一个**个人知识库**：待办、待讨论问题、决议、讨论纪要、生成的文件，全部可追溯、可全文搜索，**脱离会话也能完整理解**；并同步到你自己的**私有** GitHub 仓库，持续更新。

> **让另一个 AI agent 自己安装：** 对它说一句“阅读并执行 `AGENT-SETUP.md`（本包根目录，或知识库里的 `_tool/AGENT-SETUP.md`）”。它会自己做前置检查、隔离自测（`universal/selftest.sh`，20 项）、安装、申请权限并向你汇报，**不需要你再提供额外信息**。

## 1. 你得到什么

每个项目一个档案目录，所有项目有一个自动生成的总页：

```
ai-knowledge-base/                  ← 你的私有仓库
├── README.md                       总页（自动生成）：所有项目汇总、全部待办/问题、最近更新，可点击进入各项目
├── projects/<项目>/
│   ├── README.md                   项目首页：简介、背景、当前状态、关键决议 + 自动生成的全部档案导航
│   ├── todo.md                     待办与优化清单（未完成/已完成，带优先级、文件:行号、来源）
│   ├── questions.md                待讨论问题（未决/已决议）——之前该聊的不会丢
│   ├── log.md                      只追加的时间线日志，用于追溯
│   ├── discussions/                讨论纪要：自包含，写明背景、过程、被否决的方案、结论依据
│   ├── decisions/                  重要决议记录
│   ├── artifacts/                  讨论中生成的文件原件（文档/SQL/脚本/配置…）+ INDEX.md
│   └── glossary.md                 术语、缩写、系统/表名含义
├── _meta/                          路径映射、配置、同步状态
└── _tool/                          本工具源码（在新机器上克隆后可一键安装）
```

- **自动**：讨论出要点/结论/待办/问题/产物，AI 当轮写入，不用你提醒；回复末尾标注“已记录 N 条”。
- **忠实**：用户明确说的照实记；AI 自己补充的分析标注“（AI 补充）”，不确定的标“（待核实）”。
- **新会话开场**：自动加载当前项目要点，并提示“还有哪些问题没聊完”。
- **查细节**：问“上次为什么没选 X”，AI 会先搜知识库、读原文再回答，而不是凭记忆。
- **安全**：只允许推送到**私有**仓库（公开仓库一律拒绝）；提交前自动扫描密钥/token/密码，命中则拦截。

## 2. 包里有什么

```
ai-kb-pack/
├── README.md                       本手册（给人看）
├── AGENT-SETUP.md                  安装手册（给 AI agent 看，它自己执行）
├── claude-code/ai-kb/              Claude Code 插件（hook 全自动，推荐）
└── universal/                      通用层（任何能执行 shell 的 agent）
    ├── kb.py  rules.md             核心脚本与规则（仅 python3 标准库）
    ├── AGENT-INSTRUCTIONS.md       贴进 agent 全局指令的片段
    ├── install.sh                  一键安装（在知识库 _tool/ 里运行时自动识别知识库目录）
    └── selftest.sh                 隔离自测（临时知识库，不碰真实数据，20 项）
```

## 3. 兼容性（如实）

| 能力 | Claude Code | WorkBuddy / CodeBuddy | 其他 agent（通用层） |
|---|---|---|---|
| 档案结构、总页、搜索、日志、git 追溯 | ✅ | ✅ | ✅ |
| 会话开始自动加载规则 | ✅ hook | ✅ hook | ⚠️ 靠指令先跑 `kb.py context` |
| 每轮提醒记录 | ✅ hook | ✅ hook | ❌ |
| 压缩前保护 | ✅ hook | ✅ hook | ⚠️ 仅靠指令 |
| 回合结束检查 + 自动提交推送 | ✅ hook | ✅ hook | ❌ 靠指令跑 `kb.py sync` |

**安装脚本会自动探测你的 agent 并配好 hook**（Claude Code / WorkBuddy / CodeBuddy 三个都支持，配置格式与 Claude Code 同构）。

实测：
- ✅ **Claude Code** —— 全新环境端到端验证
- ✅ **WorkBuddy** —— 2026-10-11 在真实会话中实测四事件全部触发（`SessionStart` 注入 3690 字上下文、`UserPromptSubmit` 每轮提醒、`PreCompact` 抢救指令、`Stop` 自动提交）
- ⚠️ **Codex / Gemini CLI / Cursor / Windsurf** —— **未实测**，装完请按第 6 节自测

> **没有 hook 的 agent 也能用**，只是自动化程度低一档：靠指令让 agent 记得跑命令，漏记概率明显更高。

多个 agent 可共用同一个知识库目录。

## 4. 准备 GitHub 私有仓库（必须先做）

1. 在 GitHub 新建一个**私有（Private）**空仓库，例如 `ai-knowledge-base`。**已有仓库请确认可见性是 Private**（Settings → General → Danger Zone → Change visibility）。
2. 本机登录对应账号并有**写权限**：`gh auth login`（或配置好 git 凭据）。用 `gh auth status` 确认账号是仓库所有者。
3. **同时用多个 GitHub 账号时（常见：公司账号 + 个人账号）**：gh 同一时间只有一个"活动账号"，后台自动推送会因此失败。办法：把知识库的远程地址写成**带用户名**的形式，工具就会固定用该账号检查和推送，不受活动账号影响：

```bash
git -C ~/ai-knowledge-base remote set-url origin https://<你的用户名>@github.com/<你的用户名>/<仓库>.git
gh auth login      # 登录该账号；两个账号可以同时登录，互不影响（凭据各自存在系统钥匙串）
gh auth status     # 确认两个账号都在
```

   原理：工具用 `gh auth token --user <用户名>` 取该账号的 token，只通过环境变量传给 git 作为临时凭据，不写入命令行、配置或磁盘（需要 gh 2.40 以上）。
4. 工具推送前会用 `gh repo view` 检查可见性；**不是 PRIVATE/INTERNAL 就拒绝推送**，并在下次会话开场提醒你。装有 gh 才能完成这个检查；没有 gh 时默认拒绝推送（可在 `_meta/config.json` 里设 `"allow_unverified_push": true` 自行承担风险）。

## 5. 安装

要求：`python3`（必需）、`git`（强烈建议）、`gh`（用于私有检查与登录）。

### A. Claude Code（推荐）

**① 创建知识库目录并关联远程**（必须在启动会话前存在）：

```bash
git clone https://github.com/<你>/<仓库>.git ~/ai-knowledge-base     # 空仓库也可以
```

**② 授权 Claude 写入该目录**（在项目目录之外，不授权会被拒绝，实测）。在 `~/.claude/settings.json` 加入（换成绝对路径）：

```json
{
  "permissions": { "additionalDirectories": ["/Users/你的用户名/ai-knowledge-base"] },
  "env": { "AI_KB_DIR": "/Users/你的用户名/ai-knowledge-base" }
}
```

想免确认，再在 `permissions.allow` 里为该目录加 `Edit` / `Write` 规则（权限更宽，自行决定）。

**③ 加载插件**：

```bash
claude --plugin-dir /path/to/ai-kb-pack/claude-code/ai-kb
```

长期使用可放进团队插件市场用 `/plugin` 安装。**不需要**改 CLAUDE.md：规则由 hook 在会话开始时注入。

### B. 其他 agent（通用层）

```bash
cd ai-kb-pack/universal
./install.sh --remote https://github.com/<你>/<仓库>.git --target <该 agent 的全局指令文件>
```

脚本会：安装 `kb.py`/`rules.md` 到 `~/.ai-kb/`；克隆/初始化知识库；把指令片段追加到你指定的文件（带标记，幂等）。

全局指令文件位置（**参考，以官方文档为准**）：Codex CLI `~/.codex/AGENTS.md`；Gemini CLI `~/.gemini/GEMINI.md`；Claude Code（不装插件）`~/.claude/CLAUDE.md`；Cursor：Settings → Rules → User Rules；Windsurf：全局规则。

> ⚠️ 不要把片段放进项目仓库里的指令文件（会让它进入项目仓库），一定用**用户级/全局**指令。
> 同样要给该 agent 授权写入知识库目录，并确保它能执行 `python3 ~/.ai-kb/kb.py ...`。Windows 没有 `install.sh`：手动复制到 `%USERPROFILE%\.ai-kb\`，并设置 `AI_KB_DIR`。

### 5.3 手动配置 hook（可选）

如果安装脚本没识别出你的 agent，或你想自己配，把下面这段合并到你的 agent 配置文件里
（Claude Code → `~/.claude/settings.json`；WorkBuddy → `~/.workbuddy/settings.json`；CodeBuddy → `~/.codebuddy/settings.json`）。

**注意**：把 `__KB__` 换成你的知识库绝对路径。

```json
{
  "hooks": {
    "SessionStart": [
      { "matcher": "startup", "hooks": [{ "type": "command", "timeout": 45,
        "command": "AI_KB_DIR=\"__KB__\" python3 ~/.ai-kb/kb.py sessionstart" }] }
    ],
    "UserPromptSubmit": [
      { "matcher": "*", "hooks": [{ "type": "command", "timeout": 10,
        "command": "AI_KB_DIR=\"__KB__\" python3 ~/.ai-kb/kb.py prompt" }] }
    ],
    "PreCompact": [
      { "matcher": "*", "hooks": [{ "type": "command", "timeout": 15,
        "command": "AI_KB_DIR=\"__KB__\" python3 ~/.ai-kb/kb.py precompact" }] }
    ],
    "Stop": [
      { "matcher": "*", "hooks": [{ "type": "command", "timeout": 30,
        "command": "AI_KB_DIR=\"__KB__\" python3 ~/.ai-kb/kb.py stop" }] }
    ]
  }
}
```

四个事件各干什么：

| 事件 | 时机 | 作用 |
|---|---|---|
| `SessionStart` | 会话开始 | 把完整规则 + 全项目概览 + 🔴当前该管什么 注入给 agent |
| `UserPromptSubmit` | 你每发一条消息 | 提醒 agent 当轮记录什么 |
| `PreCompact` | 上下文压缩前 | 要求 agent 先抢救未落盘内容 |
| `Stop` | agent 回答完| 检查漏记 + 提交推送 |

**改完必须完全重启 agent 才生效**（WorkBuddy 用 Cmd+Q 彻底退出，不是关窗口）。

## 6. 安装后自测（3 分钟）

1. 新建一个空 git 项目目录，用你的 agent 打开。
2. 说一段带结论的话：“我们讨论缓存：决定用 Redis，因为 3 个实例要共享；Memcached 团队没人熟所以否决；handler.py 第 42 行每次请求重建连接，需要优化（高优先级）；过期策略用 TTL 还是主动失效我还没想好，下次再聊。再帮我写个 SQL 查最近 7 天每天订单数，保存起来。”
3. 检查知识库：应出现 `projects/<项目>/` 下的讨论纪要、`decisions/D-1-…`、`todo.md` 的 T-1、`questions.md` 的 Q-1、`artifacts/` 里的 SQL 和 INDEX、`log.md` 新增行，根目录 `README.md` 总页更新；回复末尾有“已记录 N 条”。
4. **新开会话**问：“上次为什么没选 Memcached？SQL 放哪了？”应基于知识库答对，并主动提示未决的 Q-1。
5. 没通过：先查授权写入，再查 `python3` 是否可用，再运行 `python3 kb.py status`。

## 7. 日常使用

正常工作即可。想主动操作时直接说：

- “看下总页 / 所有项目还有什么没做” / “这个项目还有哪些待讨论问题”
- “之前为什么决定 X？” / “搜一下知识库里关于 Y 的内容”
- “整理一下这个项目的档案”（补摘要、更新项目首页与当前状态）
- “审计一下最近有没有漏记”
- “同步到 GitHub”（也可手动：`python3 kb.py sync`）

命令行工具（`kb.py`，设好 `AI_KB_DIR`）：

| 命令 | 作用 |
|---|---|
| `context` | 输出规则 + 全项目概览 + **🔴 现在最该看的** + 当前项目要点（会话开始用） |
| `build` | 重建各项目 README 自动区块与根总页 |
| `search <词> ...` | 全文搜索，返回 `文件:行号:内容` |
| `status` | 各项目统计与同步状态 |
| `sync` | 提交 + 拉取 + 推送（含私有校验与密钥扫描） |
| `init` | 初始化骨架（幂等） |
| **`doctor`** | **体检**：依赖 / 结构 / 仓库可见性 / 同步状态 / 路径映射 / 项目识别，一次查完并给人话结论 |
| **`clean-stale`** | 清理指向已不存在目录的路径映射（默认预览，`KB_CONFIRM=1` 才真删） |
| **`export [路径]`** | 导出整个知识库为单个 markdown，便于离线阅读或分享 |

> **新机器装完后第一件事：跑 `kb.py doctor`**，它会告诉你缺什么、哪里不对。

**换电脑 / 恢复**：`git clone <私有仓库>` 到本机，装好插件并设置 `AI_KB_DIR`，新会话开始时自动加载并拉取。知识库里的 `_tool/` 就是本工具，克隆后可直接安装。

## 8. 同步机制

- 会话开始：先本地提交，再 `pull --rebase --autostash`（冲突则放弃合并并告警，不会弄坏你的内容）。
- 每轮结束：重建总页 → 密钥扫描 → 提交 → **后台推送**（不拖慢对话）。
- 推送前：检查仓库私有；失败或被拒时写入 `_meta/.sync-status.json`，下次会话开场告警。
- 密钥拦截：命中的变更**整批不提交**，写 `_meta/SYNC_BLOCKED.md` 列出文件和类型；把凭证改成占位符（如 `<TOKEN>`）即可恢复；确属误报的行内加 `kb-allow` 放行。
- 多机器使用：推送前先拉取；两台机器同时改同一文件可能冲突，工具会告警而不自动覆盖。

## 9. 可选：每周漏记审计

自动记录依赖模型遵守规则，不是 100% 强制。Claude Code 里说“每周五帮我审计知识库”即可建定时任务；其他 agent 可定期发送：

```
知识库目录是 ~/ai-knowledge-base。读取根目录 README.md 和各项目的 README/todo/questions/discussions，
对照最近 7 天我在这些项目目录下的会话，找出“讨论过但知识库里没有”的要点、结论、待办、优化点、待讨论问题、生成的产物。
只读审计，不改正文；结果写到 _audit/<今天日期>.md（按项目分节：会话日期+摘要+建议归入哪个文件），没有就写“本周未发现漏记”。
```

## 10. 配置

- `AI_KB_DIR`：知识库目录（兼容旧名 `CLAUDE_TRACKER_DIR`），默认 `~/ai-knowledge-base`。
- `_meta/config.json`：`allow_unverified_push`（无法验证可见性时仍推送，不建议）、`allow_non_github_remote`（远程不是 GitHub 时允许推送，如自建 git 服务）。
- 项目识别：git 根目录名；同名不同路径自动加哈希；临时目录和家目录归 `_general`；映射在 `_meta/map.json`。
- 改规则：编辑 `rules.md`。Stop 检查阈值（约 500 字或改过文件）在 `kb.py` 的 `stop` 分支。

## 11. 已知局限

**平台**：仅支持 macOS / Linux（需要 bash + python3 + git）。
**Windows 原生不支持** —— 请用 WSL 2（推荐）或 Git Bash。安装脚本会检测并给出提示。

- 自动记录依赖模型遵守规则；hook 与审计是兜底，不是绝对保证。
- 只存精炼档案和产物，**不存完整原始对话**：完整性取决于 AI 整理时不遗漏，无法回看对话原文。
- 只有 Claude Code 插件有“每轮提醒”和“回合结束检查”；其他 agent 漏记概率更高。
- Stop 检查是启发式的：很短但含结论的回复可能漏检。
- 超长对话、多次压缩后的表现尚未长期验证。
- 密钥扫描基于规则，不保证发现所有敏感信息；**不要把敏感内容讲给 AI 后指望工具兜底**。

## 12. 隐私与安全

- 知识库可能含公司相关信息：只放你**自己的私有仓库**，不要放公开仓库或公开同步目录。
- 脚本不联网（除 `git` 与 `gh` 命令），只读写知识库目录，并读取当前项目的 git 根路径。
- 分享本工具包前，确认没有带入你自己的知识库内容（本包只含脚本与空模板）。

## v2.1.0 新增（2026-10-11，WorkBuddy 实测后补充）

在 WorkBuddy 上完成落地并实测 hook 后，补了三个命令（原 v2.0.0 的实际痛点）：

| 命令 | 为什么加 |
|---|---|
| `doctor` | **新机器装完不知道正不正常** —— 一次查完依赖、结构、仓库可见性、同步状态、路径映射、项目识别，输出人话结论。实测当场抓出 3 条旧机器失效路径 |
| `clean-stale` | 换机器后 `map.json` 残留旧路径永远命不中，还要手动翻 json。默认**预览**，需 `KB_CONFIRM=1` 才真删 |
| `export` | 整个知识库导出成一个 markdown（实测 286 章节 / 152KB），便于离线阅读、分享、喂给别的工具 |

另外修了两个实战暴露的缺陷：
- `project()` 排除 WorkBuddy 会话目录（`~/WorkBuddy/<时间戳>/`）—— 否则**每开一次会话就多一个垃圾项目**
- `build_context()` 增加「🔴 现在最该看的」段，按优先级排序并**自动降级用户已说「挂起 / 后续再说」的问题** —— 新会话开场不必面对几十条平铺清单

`selftest.sh` 已修 bash 3.2 全角括号问题并推回本仓库，macOS 自带 bash 可直接跑。

---

## 13. 卸载

- Claude Code：去掉 `--plugin-dir`（或在 `/plugin` 禁用），删除 settings 里的 `AI_KB_DIR`。
- 通用层：删除 `~/.ai-kb/`，并从全局指令文件中删除 `<!-- ai-kb:begin -->` 到 `<!-- ai-kb:end -->` 之间的内容。
- 知识库目录和 GitHub 仓库是你的数据，想保留就保留。
