# 更新记录

## v2.4.0 · 2026-10-16
- **多机编号防撞**：新编号带本机前缀，形如 `T-xing-70` / `Q-xing-6` / `D-xing-2`。序号仍取全库同类最大号 +1（新旧格式一起算）；两台机器即使同时新增，前缀不同也不会重复。已有的 `T-12` 等旧编号不变、照常可用。前缀存在本机 `~/.ai-kb/machine`（不进知识库），首次使用时按主机名自动生成，可用 `kb.py machine <前缀>` 修改，或用环境变量 `AI_KB_MACHINE` 覆盖。
- **新增 `kb.py record <项目>`**：从 stdin 一次写入多条记录（`@@discussion` / `@@decision` / `@@todo` / `@@q` / `@@done` / `@@resolve` / `@@artifact` / `@@log`），先整体校验（字段、编号是否存在、密钥扫描），有任何错误则一条都不写。把每轮平均 3–4 次知识库工具调用合并成 1 次，省 token。
- 会话开场改为注入精简规则 `rules-lite.md`（完整规则仍在 `rules.md`，按需读取）；缺少 `rules-lite.md` 时自动退回完整规则，不会中断。`install.sh` / `bootstrap.sh` 现在会一并安装它。
- 拉取改为 merge（不再 rebase），README 自动区块冲突自动消解；配合知识库的 `.gitattributes` union 合并，解决两台机器同写时反复冲突的问题。
- 包含 v2.3.1 之后的 T-43 修复：联网 git 剥掉 `HTTP_PROXY` 等代理环境变量。
- 自测新增 record、多机编号、精简规则兜底、剥代理等 18 项。

## v2.3.1 · 2026-10-12
- `coverage`：知识库里含会话号的会话一律标「已整理」（此前发言少于 3 条的轻量会话即使已补录，也会被先标成「轻量·未判断」而少报）；自测 72 → 74 项。

## v2.3.0 · 2026-10-12
- 新增 **`kb.py coverage`**：盘点本机各 agent（Claude Code / WorkBuddy / CodeBuddy）的会话与知识库的对应关系，生成会话台账 `_meta/session-ledger.md`，回答「有没有遗漏」。判断依据：知识库含会话号前 8 位=已整理；否则看会话里最常出现的独特标识符（文件名/表名/函数名/PR 号）在知识库里的命中率（≥80% 已覆盖、50–80% 部分覆盖、<50% 未整理）；<3 条用户发言视为轻量会话。用真实数据校准：有自动记录的会话命中率平均 92%。
- 补录建库前会话的规范写入 `AI-START-HERE.md`（脱敏、提炼、写明会话号、标注待核实、验收）。
- 自测 62 → 74 项（coverage 的 5 类状态与台账）。

## v2.2.1 · 2026-10-12
- 看板口令：新增 `--show-pass`（在构建机上随时再看一次口令）；`--gen-pass` / `--show-pass` **只在真实终端里显示口令**——由 AI 或脚本调用（stdout 非终端）时只写文件、不打印，避免口令进入会话记录/日志；自测 58 → 74 项。
- README 说明口令存放位置、找回方式，以及用浏览器/密码管理器保存并在手机自动填充。

## v2.2.0 · 2026-10-12

基于对 v2.1.0 的逐项审查（只读检查 + 临时环境实测复现）修复缺陷，并补上看板的隐私保护。

### 新增：加密看板
- `build_dashboard.py` 默认构建**加密站**：全部内容（页面、导航、搜索索引、每篇文档、文件名）用口令端到端加密，部署到公开托管后服务器上只有密文；浏览器里输入口令后本地解密。不依赖自有域名、Worker 或服务端配置。
- `vault_encrypt.mjs`：PBKDF2-HMAC-SHA256（60 万次）+ AES-256-GCM；文件名为 HMAC 哈希；密文确定性（增量部署）；构建后自动 `verify`。
- `_dashboard_template/shell.html`：登录外壳（错误口令拒绝、会话内保持解锁、可选「记住此设备」、🔒 锁定）。
- `--gen-pass` / `--set-pass`：口令由用户在自己的终端生成/输入，存 `~/.ai-kb/dashboard_pass`（600），不进知识库与命令行。
- `deploy_dashboard.sh`：安全闸（只部署通过校验的加密产物）、`--rotate`（新建随机名项目）、`--purge-old` / `--purge-history`（删除旧站/历史部署，必须 `KB_CONFIRM=1`，不会误删当前项目）、`--status`（只读）。
- 为什么要轮换：Cloudflare Pages 保留全部历史部署，旧的明文版本仍可通过各自网址访问。

### 修复（高）
- **`install.sh` 会清空用户的 `settings.json`**：遇到带注释/尾逗号的非严格 JSON 时，旧版用 `{}` 覆盖整份配置（`permissions`、`theme` 等全部丢失且无备份）。现在：严格解析，失败即跳过并保持原文件不变；改前自动备份为 `*.bak-ai-kb-<时间戳>`；原子写入；只增删本工具写入的 hook；新增 `--dry-run`。
- **`SessionStart` 的 matcher 只设 `startup`**：会话恢复/清屏/上下文压缩之后规则不再重新注入。改为全部来源触发（与插件 `hooks.json` 一致）。

### 修复（中）
- `kb.py` 的维护命令（`build` / `status` / `sync` / `init`）不再把「所在目录」顺手登记成项目：旧版在工具仓库里跑一次 `build`，就会在知识库里多出一个空项目并写入 `map.json`。只有 agent 真正工作的模式（`sessionstart` / `context` / `prompt` / `precompact` / `stop`）才登记。
- `kb.py build` 自动补全缺失的项目结构（只新增、不覆盖）：git 不跟踪空目录，克隆到新机器后 `discussions/` `decisions/` 等会丢失，`doctor` 会误报缺失。
- `kb.py doctor` 不再写入幽灵映射：识别自测改用实际知识库路径并且不落盘（旧版硬编码 `~/ai-knowledge-base`，知识库在别处时误报并写入 `map.json`）。
- `bootstrap.sh`：`_tool/` 现在放入**完整工具**（含 `AGENT-SETUP.md`、`claude-code/`、看板脚本与模板），换机器恢复与看板构建在新装环境可用；新增 `--sync-tool`（覆盖前备份）。
- `bootstrap.sh --remote` 克隆遵循「地址里的账号」规则（多 GitHub 账号下不再依赖活动账号）。
- `bootstrap.sh` 支持单文件 `curl | bash` 自举（缺少仓库文件时先克隆工具仓库再执行）；`AI_KB_TOOL_URL` 可覆盖工具仓库地址。
- `extract_sessions.py` 支持 **Claude Code** 会话目录（旧版只读 WorkBuddy，文档却写两者都支持），并在写出前**自动脱敏**疑似凭证。
- `build_dashboard.py` 不再假定自己位于 `<KB>/_tool/`（按 `AI_KB_DIR` / 位置 / 默认路径查找知识库）。
- README 合并为一份与实际行为一致的文档；去掉未实现的「`ai-kb` 一行命令」，改为真正可用的 `curl | bash`。

### 其他
- `.gitignore` 增加杂散临时文件模式与看板口令/令牌/盐/产物。
- `selftest.sh` 从 20 项扩展到 **74 项**，新增：安装器改配置的安全性、bootstrap 与 `_tool/` 完整性、`doctor`/`audit`/`export`/`clean-stale`、看板加密（含错误口令、明文泄露检查、确定性、拒绝改动非本工具目录、无口令拒绝构建）、会话脱敏；macOS 自带 bash 3.2 通过。
- `AGENT-SETUP.md`：安装前先 `--dry-run` 预览并征得用户同意；`AI-START-HERE.md` / `skill/SKILL.md` 增加看板规则。

## v2.1.0 · 2026-10-11
`doctor` / `audit` / `clean-stale` / `export`、`bootstrap.sh` 一键安装、`skill/SKILL.md`、`AI-START-HERE.md`、多 agent 同时配 hook、WorkBuddy 会话目录识别、「🔴 现在最该看的」、删除红线。

## v2.0.0
档案结构（README/todo/questions/log/glossary/discussions/decisions/artifacts）、总页、搜索、私有仓库保险、多账号推送、密钥扫描、通用层与 Claude Code 插件。
