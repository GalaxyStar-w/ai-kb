# ai-kb 安装手册（写给 AI agent）

> 你是被用户要求安装并启用 ai-kb 的 AI 编程助手。**请完整阅读本文件并按步骤自己执行，不要向用户索取本文件里已经写明的信息。** 只有"需要用户批准的权限提示""本文明确写了要问用户的事"才去找用户。

## 0. 这个工具是什么、你要达成什么

ai-kb 把用户和 AI 的所有讨论沉淀成**个人知识库**（用户自己的私有 Git 仓库，与任何项目代码仓库无关）：每个项目一个档案目录，含 `README.md`、`todo.md`、`questions.md`、`log.md`、`discussions/`、`decisions/`、`artifacts/`、`glossary.md`；根目录 `README.md` 是自动生成的总页。

你装完之后要达成：**每个会话开始自动加载知识库规则和当前项目要点；讨论中当轮自动记录；回答历史问题时先查知识库；变更自动同步到私有远程。**

## 1. 不可违反的原则

- 不修改 Git 远程仓库的可见性；不登录/切换/删除任何 GitHub 账号；不推送到公开仓库（工具自己会拒绝，不要绕过）。
- 不把密码、token、密钥、连接串写进知识库；不删除知识库已有内容；不改写 Git 历史。
- 不修改 `kb.py`、`rules.md`（除非用户明确要求）。
- 不把任何指令片段写进**项目仓库内**的文件（如仓库里的 `AGENTS.md`、`.cursor/rules`、`.github/copilot-instructions.md`）。只写**用户级/全局**指令。
- 自测只能用 `selftest.sh`（它用临时知识库），**不要往真实知识库写测试内容**——真实知识库的变更会被自动提交并推送到远程。
- 不扩大权限范围：只申请"写知识库目录"和"执行 kb.py"所需的最小权限。

## 1.5 先探测你的平台（决定 hook 写哪里）

**这一步很关键 —— 有 hook 和没 hook，自动化程度差一档。**

按顺序检查，用第一个命中的：

| 检查 | 命中则| hook 配置文件 |
|---|---|---|
| `~/.workbuddy/settings.json` 存在 | **WorkBuddy 桌面版** | `~/.workbuddy/settings.json` |
| `~/.codebuddy/settings.json` 存在 | **CodeBuddy CLI** | `~/.codebuddy/settings.json` |
| `~/.claude/settings.json` 存在 | **Claude Code** | `~/.claude/settings.json` |
| 都不存在 | 无 hook 支持的 agent | 只能靠全局指令，自动化程度较低 |

**三个平台都支持 hooks，配置格式与 Claude Code 同构**（写 `hooks` 字段，四事件：
`SessionStart` / `UserPromptSubmit` / `PreCompact` / `Stop`）。

**装之前先备份**：`install.sh` 改配置前会**自动备份**为 `<配置文件>.bak-ai-kb-<时间戳>`，并且只在能严格解析 JSON 时才修改（解析失败会跳过、保持原文件不变）。你也可以手动再备一份：`cp <配置文件> <配置文件>.backup-before-aikb`。

**装完必须提示用户**：完全重启 agent 才生效
（Claude Code 重新启动；WorkBuddy **Cmd+Q 彻底退出**，关窗口不算 —— 它有常驻进程）。

> 完整的 hook JSON 见 `universal/README.md` 第 5.3 节，或直接跑
> `./universal/install.sh --agent workbuddy`（自动写好，幂等；只增删本工具写入的 hook 条目，用户自己的 hook 与 permissions 等原样保留）。


## 2. 步骤

### 步骤 1：定位（不需要问用户）
- 本文件所在目录记为 `PACK`。
- 知识库目录 `KB` 的确定顺序：
  1. 若 `PACK` 的上一级目录下同时有 `projects/` 和 `_meta/`（即 `PACK` 位于 `<KB>/_tool/`），则 `KB` = 该上一级目录；
  2. 否则用环境变量 `AI_KB_DIR`；
  3. 都没有 → **这是唯一允许问用户的信息**：问"知识库目录在哪（或远程仓库地址）"。

### 步骤 2：前置检查（只读，不改任何东西）
依次检查，任何一项不满足就**停止并告诉用户缺什么**，不要自行修复账号或仓库可见性：
1. `python3 --version`、`git --version` 可用。
2. `KB` 是 Git 仓库，且 `git -C "$KB" remote -v` 有 `origin`。
3. 若 `gh` 可用：远程地址若形如 `https://<用户名>@github.com/...`，用 `gh auth token --hostname github.com --user <用户名>` 能取到 token（说明该账号已登录）；并确认仓库可见性是 PRIVATE（`GH_TOKEN=<该token> gh repo view <owner>/<repo> --json visibility`）。
4. 若远程地址里**没有**用户名而本机有多个 gh 账号：提醒用户把远程改成带用户名的形式（给出命令 `git -C "$KB" remote set-url origin https://<用户名>@github.com/<owner>/<repo>.git`），但**由用户决定**是否执行。

### 步骤 2.5：检查是否已经装过（只读）
检查你自己的**用户级全局指令**和**钩子/事件配置**里是否已有 ai-kb 配置（搜索 `ai-kb:begin`、`kb.py`、`AI_KB_DIR`）：
- 已有，且指向的知识库就是 `KB` → 说明已安装：**不要重复写入**，只做步骤 3 自测和验收汇报。
- 已有，但指向**另一个**知识库 → **停止**，告诉用户两套配置会冲突，由用户决定保留哪个；不要擅自删除或合并。
- 你与用户已有的另一个 agent 是同一个产品且共用配置（例如两者都是 Claude Code）→ 同理，已装就不要再装。

### 步骤 3：隔离自测（先于安装）
```bash
bash "$PACK/universal/selftest.sh"
```
必须输出 `✅ ai-kb 机制正常`（全部通过，当前共 58 项）。有 ✘：把失败项原样告诉用户，**停止安装**。

### 步骤 4：安装
**先预览再写入（会修改用户的配置文件，必须先告诉用户并得到同意）**：
```bash
AI_KB_DIR="$KB" bash "$PACK/universal/install.sh" --dry-run     # 只预览将改哪些配置文件，不写任何东西
```
把预览结果告诉用户，同意后再正式安装：
```bash
AI_KB_DIR="$KB" bash "$PACK/universal/install.sh" --target <你自己的用户级全局指令文件>
```
- `<你自己的用户级全局指令文件>`：你应当知道自己启动时会读取哪个**用户级/全局**指令文件（例如：Codex `~/.codex/AGENTS.md`；Gemini CLI `~/.gemini/GEMINI.md`；Claude Code `~/.claude/CLAUDE.md`；Cursor 的 User Rules；Windsurf 的全局规则）。这些位置仅为参考，以你自己所在工具的实际机制为准。
- 如果你的工具只能在 UI 里配置全局规则（无法写文件）：运行不带 `--target` 的 install.sh，它会**打印**指令片段，你把片段原样交给用户并说明要粘贴到哪里。
- 没有 bash（如纯 Windows）：把 `universal/kb.py`、`universal/rules.md` 复制到 `%USERPROFILE%\.ai-kb\`，把 `universal/AGENT-INSTRUCTIONS.md` 里的 `__KB__` 全部替换成 `KB` 的真实路径后写入全局指令。
- 如果你的工具支持"会话开始 / 每轮 / 回合结束 / 压缩前"这类事件钩子：可参照 `claude-code/ai-kb/hooks/hooks.json`，把 `kb.py sessionstart|prompt|precompact|stop` 接上（stdin 为 JSON，含 `cwd`、`transcript_path`；输出格式因工具而异，需要你自己适配）。**接钩子是可选增强**，不做也能用，只是少了自动提醒和自动推送。

### 步骤 5：权限
你需要能：① 读写 `KB` 目录；② 执行 `python3 ~/.ai-kb/kb.py ...`。`KB` 在项目目录之外，多数工具默认不允许写。按你所在工具的机制申请：把 `KB` 加入"额外可写目录/工作区"，并允许上述命令。需要修改你自己的权限配置文件时，**先告诉用户要改什么并得到同意**，只放开 `KB` 目录。

### 步骤 6：验收汇报（必须）
向用户汇报，格式：
- ✅/✘ 前置检查各项结果
- ✅/✘ 自测结果（通过项数）
- 你**修改了哪些文件**（完整路径）和**没改什么**
- 还需要用户做的事（例如批准权限）
- **未验证的部分**：真实会话里的自动记录效果只能在用户日常使用后评估，请如实说明，不要说"完美"

然后告诉用户一句验收方法："请在一个真实项目目录里正常讨论，结束后看知识库里是否出现该项目的讨论纪要、待办、日志；再新开一个会话问'上次聊了什么'。"

## 3. 安装后你的日常行为

指令片段会要求你：每个会话开始运行 `AI_KB_DIR="<KB>" python3 ~/.ai-kb/kb.py context` 并遵守输出的规则（完整规则见 `universal/rules.md`）；讨论中当轮记录；用户问历史细节时先 `kb.py search`；每轮有变更就 `kb.py sync`。**没有 hook 的 agent 不会自动推送，只有你运行 `sync` 时才推。**

## 4. 常见失败与处理

| 现象 | 处理 |
|---|---|
| 写 `KB` 被拒绝 | 步骤 5：授权写入目录，目录必须在会话启动前已存在 |
| `kb.py context` 在别处新建了空知识库 | 命令里漏了 `AI_KB_DIR="<KB>"`；删除误建的空目录前先告诉用户 |
| 推送被拒（"远程仓库是公开的"） | 停止，告诉用户去 GitHub 改成私有；**不要自己改** |
| 推送被拒（"gh 没有登录账号 X"） | 告诉用户执行 `gh auth login` 登录该账号；不要自己登录 |
| `SYNC_BLOCKED.md` 出现 | 里面列出疑似含密钥的文件；把凭证改成占位符 `<TOKEN>`；确属误报的行加 `kb-allow` |
| 拉取冲突告警 | 不要强推；告诉用户，由用户决定如何合并 |
