#!/usr/bin/env python3
"""ai-kb：个人 AI 讨论知识库工具（单文件，仅依赖 python3 标准库；git/gh 可选）。

hook 模式（stdin 传 JSON）: sessionstart | precompact | prompt | stop
通用/手动模式:
  context            输出规则 + 总览 + 当前项目要点（给没有 hook 的 agent 在会话开始时运行）
  build              重新生成各项目 README 的自动区块和根目录总页
  search <词> [...]   在整个知识库里搜索（多个词为"或"，支持正则），返回 文件:行号: 内容
  status             打印各项目统计与同步状态
  init               创建知识库目录骨架（git init、.gitignore）
  sync               手动：提交 + 拉取 + 推送（带私有仓库与密钥检查）
  audit              盘点：列出所有项目/文件数/体积/提交数，纯只读，用于确认「内容都在」（v2 新增）
  doctor             体检：依赖/结构/远程可见性/同步状态/路径映射/项目识别 一次查完（v2 新增）
  coverage           盘点本机所有 AI 会话与知识库的对应关系，生成会话台账 _meta/session-ledger.md（只读会话）
  clean-stale        清理指向已不存在目录的路径映射（预览；KB_CONFIRM=1 才真删）（v2 新增）
  export [路径]      把整个知识库导出成单个 markdown，便于离线阅读/分享（v2 新增）
知识库目录：环境变量 AI_KB_DIR（兼容 CLAUDE_TRACKER_DIR），默认 ~/ai-knowledge-base。

🔒 删除保护（2026-10-11 用户要求）：本工具**不提供任何删除命令**。
   删文件只能手工操作，且**必须先问用户**——理由见 rules.md 的「删除红线」。
   历史案例：一份实战纪要曾被当「测试残留」删除，事后才从 git 历史恢复。
任何异常在 hook 模式下静默退出，绝不影响正常对话。
"""
import sys, os, re, json, subprocess, hashlib, datetime, shutil, time, collections

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
KB = os.path.expanduser(os.environ.get("AI_KB_DIR") or os.environ.get("CLAUDE_TRACKER_DIR") or "~/ai-knowledge-base")
KBNAME = os.path.basename(os.path.normpath(KB))
PROJ = os.path.join(KB, "projects")
META = os.path.join(KB, "_meta")
MAPF = os.path.join(META, "map.json")
CFGF = os.path.join(META, "config.json")
STATUSF = os.path.join(META, ".sync-status.json")
BLOCKF = os.path.join(META, "SYNC_BLOCKED.md")
HAS_GIT = shutil.which("git") is not None
mode = sys.argv[1] if len(sys.argv) > 1 else ""
VERSION = "2.3.1"
ROOT_CAP_TODO = 15      # 总页每个项目最多列出的未完成待办条数
ROOT_CAP_Q = 10         # 总页每个项目最多列出的未决问题条数
CTX_CAP = 9000          # 会话开场注入：待办/问题清单各自的字符上限
HOOK_MODES = ("sessionstart", "precompact", "prompt", "stop")
today = datetime.date.today().isoformat()
NON_PROJECT_PREFIXES = ("/tmp/", "/private/tmp/", "/private/var/", "/var/folders/")
# WorkBuddy/CodeBuddy 的会话工作区：形如 ~/WorkBuddy/2026-10-11-13-24-31，每开一个会话新建一个。
# 它们不是真实项目，若按 basename 建档会每次会话都多出一个垃圾项目。
NON_PROJECT_PARENTS = ("/WorkBuddy/", "/.workbuddy/workspace/")
SESSION_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[-_]\d{2}[-_]\d{2}(?:[-_]\d{2})?$")


# ---------- 基础工具 ----------
def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def write(p, s, m="w"):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, m, encoding="utf-8") as f:
        f.write(s)


def load_json(p, default):
    try:
        return json.loads(read(p))
    except Exception:
        return default


def git(*a, timeout=30):
    # -c core.quotepath=false：中文路径不再被转义成八进制（否则 scan_staged 判断命中文件时会解析错）
    return subprocess.run(["git", "-C", KB, "-c", "core.quotepath=false", *a],
                          capture_output=True, text=True, timeout=timeout)


def remote_url():
    return git("remote", "get-url", "origin").stdout.strip()


def gh_account():
    """远程地址写成 https://用户名@github.com/... 时，固定使用该 gh 账号（不依赖当前活动账号）。"""
    m = re.match(r"https://([^/@:]+)@github\.com/", remote_url())
    return m.group(1) if m else None


def gh_token(user):
    if not shutil.which("gh"):
        return None
    try:
        r = subprocess.run(["gh", "auth", "token", "--hostname", "github.com", "--user", user],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None
    except Exception:
        return None


def net_env():
    """联网 git 命令用的环境：剥掉代理环境变量。

    为什么必须剥：WorkBuddy/部分终端会注入 HTTP_PROXY=http://127.0.0.1:xxxxx，
    而 git 读代理的优先级是「环境变量 > git config」，仓库级
    `git config http.proxy ""` 压不住环境变量 —— 实测 push 报
    「Failed to connect to github.com port 443」（2026-10-14，T-43）。
    临时解法是每次手工 `env -u HTTP_PROXY ... git push`，这里写进工具根治。
    只影响 kb.py 自己 spawn 的 git 子进程，不动用户 shell 环境。
    """
    env = dict(os.environ)
    for k in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy",
              "ALL_PROXY", "all_proxy", "FTP_PROXY", "ftp_proxy"):
        env.pop(k, None)
    return env


def authed_git(*a, timeout=60):
    """需要联网认证的 git 命令（fetch/pull/push）。地址里带用户名且 gh 已登录该账号时，用该账号的 token 作为临时凭据；
    token 只经环境变量传给子进程，不写入命令行、配置或磁盘。"""
    user = gh_account()
    tok = gh_token(user) if user else None
    if tok:
        env = net_env()
        env["KB_GH_USER"] = user
        env["KB_GH_TOKEN"] = tok
        helper = '!f() { echo "username=$KB_GH_USER"; echo "password=$KB_GH_TOKEN"; }; f'
        return subprocess.run(["git", "-C", KB, "-c", "credential.helper=", "-c", "credential.helper=" + helper, *a],
                              capture_output=True, text=True, timeout=timeout, env=env)
    # 无 token 走普通 git（SSH 等），同样剥代理
    return subprocess.run(["git", "-C", KB, "-c", "core.quotepath=false", *a],
                          capture_output=True, text=True, timeout=timeout, env=net_env())


def has_remote():
    return HAS_GIT and os.path.isdir(os.path.join(KB, ".git")) and bool(git("remote").stdout.strip())


# ---------- 模板 ----------
def tpl_readme(name, root):
    return (f"# {name}\n\n- 对应目录：{root or '无（不在具体项目目录下的讨论）'}\n- 创建：{today}\n\n"
            "## 项目简介\n（AI 维护。写到“从没听说过这个项目的人也能看懂”：是什么、目标、背景、涉及的系统/表/服务、相关人员与外部依赖。）\n\n"
            "## 当前状态\n（一两段：现在进展到哪、下一步是什么。）\n\n"
            "## 关键决议\n（每条一行：`D-xxx 标题 —— 一句话结论`，链接到 decisions/。）\n\n"
            "<!-- AUTO:BEGIN -->\n<!-- AUTO:END -->\n")


def tpl_todo(name):
    return (f"# {name} 待办与优化清单\n\n"
            "> 格式：`- [ ] T-<n> [类型|优先级] 内容（文件:行号）— 来源 · 提出日期`。类型：待办/优化/缺陷/调研；优先级：高/中/低。\n"
            "> 编号全项目唯一、递增。完成后移到“已完成”并写完成日期，不删除。来源指向 discussions/ 或 decisions/ 下的文件。\n\n"
            "## 未完成\n\n## 已完成\n")


def tpl_questions(name):
    return (f"# {name} 待讨论问题\n\n"
            "> 格式：`- Q-<n> [待讨论|讨论中] 问题 — 提出 日期 · 最近触及 日期 · 来源/关联`。已决议的移到“已决议”并写 `→ D-xxx` 或结论，不删除。\n\n"
            "## 未决\n\n## 已决议\n")


def tpl_log(name):
    return (f"# {name} 日志（只追加，按时间）\n\n> 每行：`- 日期 | 动作 | 条目ID | 说明`\n\n- {today} | 创建 | - | 创建项目档案\n")


def tpl_glossary(name):
    return f"# {name} 术语与背景\n\n> 记录项目里的专有名词、缩写、系统/表名含义、人名角色，让脱离会话的人也能看懂。\n\n"


def tpl_artifacts_index(name):
    return (f"# {name} 产物索引\n\n> AI 在讨论中生成的文档/脚本/SQL/配置/报告等，原文件放在本目录。每个文件一行：\n"
            "> `- [文件名](文件名) — 说明 · 生成于 日期 · 来源 discussions/xxx.md`\n\n")


GITIGNORE = ".DS_Store\n_meta/.sync-status.json\n_meta/SYNC_BLOCKED.md\n"


def ensure_kb():
    os.makedirs(PROJ, exist_ok=True)
    os.makedirs(META, exist_ok=True)
    gi = os.path.join(KB, ".gitignore")
    if not os.path.exists(gi):
        write(gi, GITIGNORE)
    if HAS_GIT and not os.path.isdir(os.path.join(KB, ".git")):
        git("init", "-q")
        git("config", "user.name", os.environ.get("GIT_AUTHOR_NAME") or "ai-kb")
        git("config", "user.email", os.environ.get("GIT_AUTHOR_EMAIL") or "ai-kb@local")


def ensure_project(name, root):
    d = os.path.join(PROJ, name)
    files = {"README.md": tpl_readme(name, root), "todo.md": tpl_todo(name), "questions.md": tpl_questions(name),
             "log.md": tpl_log(name), "glossary.md": tpl_glossary(name),
             os.path.join("artifacts", "INDEX.md"): tpl_artifacts_index(name)}
    for rel, content in files.items():
        p = os.path.join(d, rel)
        if not os.path.exists(p):
            write(p, content)
    for sub in ("discussions", "decisions"):
        os.makedirs(os.path.join(d, sub), exist_ok=True)
        k = os.path.join(d, sub, ".gitkeep")
        if not os.listdir(os.path.join(d, sub)):
            write(k, "")
    return d


# ---------- 项目识别 ----------
def is_temp_dir(path):
    """判断是否临时目录。原前缀表带尾部斜杠，直接 startswith 会漏掉 /private/tmp 这种无尾斜杠的精确匹配。"""
    for pre in NON_PROJECT_PREFIXES:
        if path == pre.rstrip("/") or path.startswith(pre):
            return True
    return False


def project(cwd, persist=True):
    root = cwd
    if HAS_GIT:
        try:
            r = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=5).stdout.strip()
            root = r or cwd
        except Exception:
            pass
    home = os.path.expanduser("~")
    norm = root.replace("\\", "/")
    # 符号链接归一化：macOS 上 /tmp 实际是 /private/tmp 的链接，不归一化会导致前缀判断失效
    real = os.path.realpath(root).replace("\\", "/")
    base = os.path.basename(os.path.normpath(real))
    is_session = (SESSION_DIR_RE.match(base)
                  or any(pp in real for pp in NON_PROJECT_PARENTS))
    kbnorm = os.path.normpath(KB)
    is_under_kb = os.path.normpath(root) == kbnorm or os.path.normpath(root).startswith(kbnorm + os.sep)
    # 知识库自身的根目录归 _general；知识库下的 projects/<名字>/ 仍按项目名识别
    under_projects = os.path.normpath(root).startswith(os.path.join(kbnorm, "projects") + os.sep)
    if (not root or os.path.normpath(root) == os.path.normpath(home) or "/Claude/scratch-workspaces/" in norm
            or is_temp_dir(real)
            or is_session
            or (is_under_kb and not under_projects)):
        return "_general", ""
    m = load_json(MAPF, {})
    if root not in m:
        name = os.path.basename(os.path.normpath(root)) or "project"
        if name in m.values():
            name += "-" + hashlib.md5(root.encode()).hexdigest()[:4]
        m[root] = name
        if not persist:            # 只读场景（如 doctor）不落盘，避免写入幽灵映射
            return name, root
        write(MAPF, json.dumps(m, indent=2, ensure_ascii=False))
    return m[root], root


# ---------- 解析与生成 ----------
def title_of(p):
    try:
        for line in read(p).splitlines():
            if line.startswith("# "):
                return line[2:].strip()
    except Exception:
        pass
    return os.path.basename(p)


def open_part(text, heading):
    i = text.find("\n" + heading)
    return text if i < 0 else text[:i]


def stats(name):
    d = os.path.join(PROJ, name)
    def rd(f):
        try: return read(os.path.join(d, f))
        except Exception: return ""
    todo, ques, log = rd("todo.md"), rd("questions.md"), rd("log.md")
    t_open = len(re.findall(r"^- \[ \]", open_part(todo, "## 已完成"), re.M))
    t_done = len(re.findall(r"^- \[[xX]\]", todo, re.M))
    q_open = len(re.findall(r"^- Q-\d+", open_part(ques, "## 已决议"), re.M))
    def files(sub, skip=("INDEX.md", ".gitkeep")):
        p = os.path.join(d, sub)
        return sorted([f for f in os.listdir(p) if f not in skip and not f.startswith(".")]) if os.path.isdir(p) else []
    dates = re.findall(r"^- (\d{4}-\d{2}-\d{2})", log, re.M)
    return dict(name=name, t_open=t_open, t_done=t_done, q_open=q_open, disc=files("discussions"), dec=files("decisions"),
                art=files("artifacts"), last=dates[-1] if dates else "", log_tail=[l for l in log.splitlines() if l.startswith("- 2")][-5:])


def all_projects():
    if not os.path.isdir(PROJ):
        return []
    return sorted(n for n in os.listdir(PROJ) if os.path.isdir(os.path.join(PROJ, n)) and not n.startswith("."))


def auto_block(s, name):
    d = os.path.join(PROJ, name)
    L = ["<!-- AUTO:BEGIN 由脚本生成，请勿手改 -->", "### 导航",
         f"- 待办与优化：[todo.md](todo.md) — 未完成 **{s['t_open']}** / 已完成 {s['t_done']}",
         f"- 待讨论问题：[questions.md](questions.md) — 未决 **{s['q_open']}**",
         "- 日志：[log.md](log.md)　·　术语：[glossary.md](glossary.md)　·　产物索引：[artifacts/INDEX.md](artifacts/INDEX.md)", "",
         f"### 讨论纪要（{len(s['disc'])}）"]
    DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
    L += [f"- {f[:10] if DATE_RE.match(f) else ''} [{title_of(os.path.join(d, 'discussions', f))}](discussions/{f})"
          for f in reversed(s["disc"])] or ["- （暂无）"]
    L += ["", f"### 决议记录（{len(s['dec'])}）"]
    L += [f"- [{title_of(os.path.join(d,'decisions',f))}](decisions/{f})" for f in s["dec"]] or ["- （暂无）"]
    L += ["", f"### 产物（{len(s['art'])}）"]
    L += [f"- [{f}](artifacts/{f})" for f in s["art"]] or ["- （暂无）"]
    L += ["", "### 最近日志"] + (s["log_tail"] or ["- （暂无）"]) + ["<!-- AUTO:END -->"]
    return "\n".join(L)


def build():
    ensure_kb()
    rows, open_todos, open_qs, recent = [], [], [], []
    for n in all_projects():
        # 补全缺失的结构（只新增、绝不覆盖）：git 不跟踪空目录，克隆到新机器后 discussions/ decisions/ 等会丢失；
        # 外部创建的项目也可能缺文件。ensure_project 是幂等的，已有文件一律不动。
        ensure_project(n, "")
        s = stats(n)
        p = os.path.join(PROJ, n, "README.md")
        text = read(p) if os.path.exists(p) else tpl_readme(n, "")
        blk = auto_block(s, n)
        if "<!-- AUTO:BEGIN" in text and "<!-- AUTO:END -->" in text:
            text = re.sub(r"<!-- AUTO:BEGIN.*?<!-- AUTO:END -->", lambda m: blk, text, flags=re.S)
        else:
            text = text.rstrip() + "\n\n" + blk + "\n"
        if text != (read(p) if os.path.exists(p) else None):
            write(p, text)
        rows.append(f"| [{n}](projects/{n}/README.md) | {s['t_open']} | {s['q_open']} | {len(s['disc'])} | {len(s['dec'])} | {len(s['art'])} | {s['last']} |")
        d = os.path.join(PROJ, n)
        # 总页每个项目最多列出若干条，其余只提示数量（完整清单在各项目 todo.md / questions.md）：
        # 补录大量历史会话后，未完成项可能上百条，全列出来会让总页无法阅读。
        shown_t = shown_q = more_t = more_q = 0
        for l in open_part(read(os.path.join(d, "todo.md")), "## 已完成").splitlines():
            if l.startswith("- [ ]"):
                if shown_t >= ROOT_CAP_TODO:
                    more_t += 1
                    continue
                shown_t += 1
                # T-21：若该行在源文件里带 kb-allow，复制到总页时必须保留，
                # 否则源文件已放行、总页却重新触发密钥扫描拦截（整批不提交）。
                body = l[6:]
                if "kb-allow" not in body and hits_secret(body):
                    body = body.rstrip() + "（kb-allow：由源文件推断为误报）"
                open_todos.append(f"- **{n}** {body}")
        if more_t:
            open_todos.append(f"- **{n}** …另有 {more_t} 条未完成待办未在此列出，见 [projects/{n}/todo.md](projects/{n}/todo.md)")
        for l in open_part(read(os.path.join(d, "questions.md")), "## 已决议").splitlines():
            if l.startswith("- Q-"):
                if shown_q >= ROOT_CAP_Q:
                    more_q += 1
                    continue
                shown_q += 1
                body = l[2:]
                if "kb-allow" not in body and hits_secret(body):
                    body = body.rstrip() + "（kb-allow：由源文件推断为误报）"
                open_qs.append(f"- **{n}** {body}")
        if more_q:
            open_qs.append(f"- **{n}** …另有 {more_q} 个未决问题未在此列出，见 [projects/{n}/questions.md](projects/{n}/questions.md)")
        for l in s["log_tail"]: recent.append((l[2:12], f"- **{n}** {l[2:]}"))
    recent.sort(key=lambda x: x[0], reverse=True)
    root = ["# AI 知识库总页", "",
            "> 由脚本自动生成（请勿手改）。这是我与 AI 讨论过的所有项目的汇总：每个项目有独立档案，点击项目名进入。", "",
            "## 如何脱离会话使用这个知识库",
            "- **项目首页** `projects/<项目>/README.md`：项目是什么、当前状态、关键决议，以及自动生成的全部档案导航。",
            "- **todo.md / questions.md**：所有待办优化项、待讨论问题（含已完成/已决议，不删除）。",
            "- **discussions/**：每次讨论的纪要，自包含，写明背景、过程、被否决的方案和结论依据。",
            "- **decisions/**：重要决议的完整记录（背景、选项、结论、原因）。",
            "- **artifacts/**：讨论中生成的文档、脚本、SQL、配置等原文件，`INDEX.md` 说明每个文件的用途。",
            "- **log.md**：只追加的时间线，用于追溯。想找某个细节：在仓库里全文搜索关键词，或让 AI 运行 `kb.py search`。", "",
            "## 让新的 AI agent 接入这个知识库",
            "对它说一句：“阅读并执行本仓库 `_tool/AGENT-SETUP.md`”。它会自己完成前置检查、隔离自测、安装、权限申请和验收汇报，不需要你再提供额外信息。", "",
            "## 项目总览", "", "| 项目 | 未完成待办 | 未决问题 | 讨论纪要 | 决议 | 产物 | 最近更新 |", "|---|---|---|---|---|---|---|"] + rows
    total_t = sum(int(r.split("|")[2]) for r in rows)
    total_q = sum(int(r.split("|")[3]) for r in rows)
    root += ["", f"## 全部未完成待办（共 {total_t}；每个项目最多列出 {ROOT_CAP_TODO} 条）"] + (open_todos or ["- （暂无）"])
    root += ["", f"## 全部未决问题（共 {total_q}；每个项目最多列出 {ROOT_CAP_Q} 条）"] + (open_qs or ["- （暂无）"])
    root += ["", "## 最近更新（全部项目）"] + ([r[1] for r in recent[:15]] or ["- （暂无）"]) + [""]
    new = "\n".join(root)
    rp = os.path.join(KB, "README.md")
    if not os.path.exists(rp) or read(rp) != new:
        write(rp, new)


# ---------- 同步（密钥扫描 / 私有仓库检查 / 提交 / 推送） ----------
SECRET_PATTERNS = [
    ("AWS Access Key", r"AKIA[0-9A-Z]{16}"), ("GitHub token", r"gh[pousr]_[A-Za-z0-9]{30,}"),
    ("API key (sk-)", r"sk-[A-Za-z0-9_\-]{20,}"), ("Slack token", r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    ("私钥", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), ("Bearer token", r"Bearer\s+[A-Za-z0-9._\-]{24,}"),
    ("URL 内嵌账号密码", r"[a-zA-Z][a-zA-Z0-9+.\-]*://[^\s:@/]+:[^\s@/]{3,}@"),
    ("password/secret/token 赋值", r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|access[_-]?key|token)\b\s*[:=]\s*['\"]?[^\s'\"<>{}$]{8,}"),
]


def hits_secret(line):
    """判断一行文本是否命中密钥扫描规则（用于 build 时自动补 kb-allow）。"""
    if "kb-allow" in line:
        return False
    return any(re.search(pat, line) for _, pat in SECRET_PATTERNS)


def scan_staged():
    diff = git("diff", "--cached", "-U0", "--no-color").stdout
    hits, cur = [], ""
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            cur = line[6:]
        elif line.startswith("+") and not line.startswith("+++"):
            if "kb-allow" in line:
                continue
            for nm, pat in SECRET_PATTERNS:
                if re.search(pat, line):
                    hits.append((cur, nm))
    return hits


def commit(msg):
    if not (HAS_GIT and os.path.isdir(os.path.join(KB, ".git"))):
        return True
    git("add", "-A")
    if not git("status", "--porcelain").stdout.strip():
        return True
    hits = scan_staged()
    if hits:
        git("reset", "-q")
        write(BLOCKF, "# ⚠ 同步被拦截：检测到疑似密钥/凭证\n\n以下文件的新增内容命中敏感信息规则，**本次变更未提交、未推送**。请把凭证替换为占位符（如 `<TOKEN>`）后再继续；确属误报的行可在行内加 `kb-allow` 标记放行。\n\n"
              + "\n".join(f"- `{f}`：{n}" for f, n in sorted(set(hits))) + "\n")
        return False
    if os.path.exists(BLOCKF):
        os.remove(BLOCKF)
    git("commit", "-q", "-m", msg)
    return True


def remote_is_private():
    """推送前检查：只有确认仓库是 PRIVATE/INTERNAL 才允许推送。"""
    cfg = load_json(CFGF, {})
    if cfg.get("allow_unverified_push"):
        return True, "allow_unverified_push"
    url = remote_url()
    m = re.search(r"github\.com[:/]+(?:[^/@]+@)?([^/]+)/([^/.]+)", url)
    if not m:  # 非 GitHub 远程（如自建 git 服务/本地裸仓库）：无法检查可见性，按配置决定
        return bool(cfg.get("allow_non_github_remote", False)), "non-github-remote"
    if not shutil.which("gh"):
        return False, "gh 不可用，无法确认仓库是否私有"
    env, user = dict(os.environ), gh_account()
    if user:
        tok = gh_token(user)
        if not tok:
            return False, f"gh 没有登录账号 {user}（请 gh auth login 登录该账号）"
        env["GH_TOKEN"] = tok  # 用该账号检查，不依赖当前活动账号
    r = subprocess.run(["gh", "repo", "view", f"{m.group(1)}/{m.group(2)}", "--json", "visibility", "--jq", ".visibility"],
                       capture_output=True, text=True, timeout=20, env=env)
    vis = r.stdout.strip().upper()
    return vis in ("PRIVATE", "INTERNAL"), vis or (r.stderr.strip()[:120] or "未知")


def set_status(ok, msg):
    write(STATUSF, json.dumps({"ok": ok, "msg": msg, "time": datetime.datetime.now().isoformat(timespec="seconds")}, ensure_ascii=False))


def do_push():
    """前台执行：检查私有 -> push。结果写入状态文件。"""
    try:
        ok, why = remote_is_private()
        if not ok:
            set_status(False, "已拒绝推送：远程仓库是公开的，请先在 GitHub 改为私有。" if why == "PUBLIC"
                       else f"已拒绝推送：无法确认仓库是私有的（{why}）。")
            return False
        r = authed_git("push", "-u", "origin", "HEAD", timeout=90)
        set_status(r.returncode == 0, "推送成功" if r.returncode == 0 else ("推送失败：" + (r.stderr.strip()[-200:])))
        return r.returncode == 0
    except Exception as e:
        set_status(False, f"推送异常：{e}")
        return False


def push_bg():
    if not has_remote():
        return
    kw = {"start_new_session": True} if os.name != "nt" else {"creationflags": 0x00000008}
    subprocess.Popen([sys.executable, os.path.abspath(__file__), "_push"], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=os.environ.copy(), **kw)


def pull():
    if not has_remote():
        return
    try:
        authed_git("fetch", "-q", timeout=30)
        up = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
        if up.returncode != 0:
            return
        r = authed_git("pull", "--rebase", "--autostash", "-q", timeout=45)
        if r.returncode != 0:
            git("rebase", "--abort")
            set_status(False, "拉取合并冲突，已放弃本次合并；请手动处理")
    except Exception as e:
        set_status(False, f"拉取失败：{e}")


# ---------- 上下文 ----------
def rules_text():
    return read(os.path.join(HERE, "rules.md")).replace("{KB}", KB)


def cap_section(text, path, limit=None):
    """会话开场注入的清单过长时，在行边界截断并提示剩余数量（完整内容仍在文件里）。
    补录大量历史会话后未完成项可能上百条，全部注入会淹没真正要紧的内容。"""
    limit = limit or CTX_CAP
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit("\n", 1)[0]
    rest = text[len(cut):]
    n = len(re.findall(r"^- (?:\[ \]|Q-)", rest, re.M))
    return cut + f"\n…（已截断：还有 {n} 条未显示；完整清单见 {path}。注入里优先放在前面的是较新/较要紧的条目）"


def build_context(name, root):
    d = os.path.join(PROJ, name)
    script = os.path.abspath(__file__)
    parts = [rules_text(), f"\n## 当前位置\n- 知识库：{KB}\n- 当前项目：**{name}**（{d}）\n"
             f"- 搜索命令：`AI_KB_DIR=\"{KB}\" python3 \"{script}\" search <关键词>`（多个词为“或”，支持正则）\n"
             f"- 手动同步：`AI_KB_DIR=\"{KB}\" python3 \"{script}\" sync`"]
    warn = []
    if os.path.exists(BLOCKF):
        warn.append("⚠ 同步被拦截（疑似密钥）：" + read(BLOCKF).split("\n\n", 1)[-1].strip()[:400])
    st = load_json(STATUSF, {})
    if st and not st.get("ok"):
        warn.append("⚠ 上次同步异常：" + str(st.get("msg")))
    if warn:
        parts.append("\n## 同步警告（请先告知用户）\n" + "\n".join(warn))
    rows = [stats(n) for n in all_projects()]
    parts.append("\n## 全部项目概览\n" + "\n".join(
        f"- {r['name']}：未完成待办 {r['t_open']}，未决问题 {r['q_open']}，讨论纪要 {len(r['disc'])}，决议 {len(r['dec'])}，产物 {len(r['art'])}，最近 {r['last']}" for r in rows))
    rd = os.path.join(d, "README.md")
    readme = re.sub(r"<!-- AUTO:BEGIN.*?<!-- AUTO:END -->", "", read(rd), flags=re.S).strip()
    s = stats(name)
    parts.append(f"\n## 当前项目首页（README.md）\n{readme}")
    parts.append(f"\n### 详细档案（按需读取，不在此展开）\n讨论纪要 {len(s['disc'])} 篇（最近：{', '.join(s['disc'][-3:]) or '无'}），决议 {len(s['dec'])} 条，产物 {len(s['art'])} 个。位于 {d}/discussions|decisions|artifacts。")
    parts.append("\n## 未完成待办（todo.md）\n" + cap_section(open_part(read(os.path.join(d, "todo.md")), "## 已完成").strip(), os.path.join(d, "todo.md")))
    parts.append("\n## 未决问题（questions.md）\n" + cap_section(open_part(read(os.path.join(d, "questions.md")), "## 已决议").strip(), os.path.join(d, "questions.md")))
    # T-36：新会话开场最需要的是「现在该管什么」，而不是面对几十条平铺的清单。
    urgent = urgent_items()
    if urgent:
        parts.append("\n## 🔴 现在最该看的（按优先级+ 是否挂起过滤）\n"
                     + "\n".join(urgent)
                     + "\n\n> 上面是本知识库当前最值得动手的几条；完整清单见根目录 README.md。")
    parts.append("\n## 最近日志\n" + ("\n".join(s["log_tail"]) or "（暂无）"))
    return "\n".join(parts)


PRIO_ORDER = {"高": 0, "中": 1, "低": 2}


def urgent_items(limit=8):
    """挑出当前最该看的条目：高优先级在前，排除用户已明确「挂起/后续再说」的。"""
    todo_rows, q_rows = [], []
    for name in all_projects():
        d = os.path.join(PROJ, name)
        try:
            todo = read(os.path.join(d, "todo.md"))
            ques = read(os.path.join(d, "questions.md"))
        except Exception:
            continue
        for l in open_part(todo, "## 已完成").splitlines():
            m = re.match(r"- \[ \] (T-\d+) \[([^|]+)\|([^\]]+)\] (.*)", l)
            if m:
                todo_rows.append((PRIO_ORDER.get(m.group(3).strip(), 3), m.group(1),
                                  name, m.group(3).strip(), m.group(2).strip(), m.group(4)))
        for l in open_part(ques, "## 已决议").splitlines():
            m = re.match(r"- (Q-\d+) \[(待讨论|讨论中)\] (.*)", l)
            if m:
                # 用户说了「挂起 / 后续再说 / 后续再看」的直接降级，避免反复催
                suspended = any(k in m.group(3) for k in ("挂起", "后续再说", "后续再看", "暂不催"))
                q_rows.append((PRIO_ORDER["中"] if suspended else 0, m.group(1),
                               name, "挂起" if suspended else "待讨论", "问题", m.group(3)))
    rows = sorted(todo_rows + q_rows, key=lambda r: r[0])[:limit]
    out = []
    for _, tid, name, prio, kind, text in rows:
        flag = "⏸ 挂起" if prio == "挂起" else f"[{prio}]"
        out.append(f"- **{name}** {tid} {flag} {text.strip()[:150]}")
    return out


def search(terms):
    if not terms:
        print("用法: kb.py search <关键词> [更多关键词...]")
        return
    pats = [re.compile(t, re.I) for t in terms]
    n = 0
    for dp, dn, fn in os.walk(KB):
        dn[:] = [x for x in dn if x != ".git"]
        for f in sorted(fn):
            if not f.endswith((".md", ".txt", ".sql", ".py", ".json", ".yaml", ".yml", ".csv", ".sh")):
                continue
            p = os.path.join(dp, f)
            try:
                for i, line in enumerate(read(p).splitlines(), 1):
                    if any(x.search(line) for x in pats):
                        print(f"{os.path.relpath(p, KB)}:{i}: {line.strip()[:200]}")
                        n += 1
                        if n >= 60:
                            print("…（结果过多，请加更具体的关键词）")
                            return
            except Exception:
                pass
    if n == 0:
        print("没有匹配")



# ---------- 新增命令（v2 补充） ----------
def cmd_doctor():
    """体检：一次跑完所有关键检查，输出人话结论。给新机器安装后、或怀疑出问题��用。"""
    out = []
    ok = lambda c, m: out.append(("✅" if c else "❌", m))
    out.append(("ℹ️", f"ai-kb v{VERSION}"))

    # 1. 依赖
    ok(shutil.which("python3") is not None, "python3 可用")
    ok(shutil.which("git") is not None, "git 可用")
    gh = shutil.which("gh")
    ok(gh is not None, "gh 可用" + ("" if gh else "（私有仓库校验与多账号推送会退化为手动）"))

    # 2. 知识库结构
    ok(os.path.isdir(PROJ), f"projects/ 存在（{PROJ}）")
    ok(os.path.isdir(META), f"_meta/ 存在")
    ok(os.path.isfile(os.path.join(KB, "README.md")), "根总页 README.md 已生成")
    n = len(all_projects())
    ok(n > 0, f"项目数：{n}")

    # 3. 结构完整性（每个项目 8 类文件）
    missing = []
    for name in all_projects():
        d = os.path.join(PROJ, name)
        for rel in ("README.md", "todo.md", "questions.md", "log.md", "glossary.md"):
            if not os.path.isfile(os.path.join(d, rel)):
                missing.append(f"{name}/{rel}")
        for sub in ("artifacts", "discussions", "decisions"):
            if not os.path.isdir(os.path.join(d, sub)):
                missing.append(f"{name}/{sub}/")
    ok(not missing, "各项目结构完整（8 类文件）" if not missing else f"缺失：{', '.join(missing[:6])}")

    # 4. 远程与私有性
    url = remote_url()
    ok(bool(url), f"远程已配置：{url or '无（无法推送）'}")
    if url:
        acct = gh_account()
        ok(acct is not None, f"远程带用户名（固定推送账号）：{acct or '未带，依赖 gh 活动账号'}")
        if gh:
            m = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$", url)
            if m:
                tok = gh_token(acct) if acct else None
                vis = None
                if tok:
                    r = subprocess.run(["gh", "repo", "view", f"{m.group(1)}/{m.group(2)}",
                                        "--json", "visibility"], capture_output=True, text=True,
                                       env=dict(os.environ, GH_TOKEN=tok), timeout=20)
                    if r.returncode == 0:
                        vis = json.loads(r.stdout).get("visibility")
                ok(vis in ("PRIVATE", "INTERNAL"),
                   f"仓库可见性：{vis}" + ("" if vis in ("PRIVATE", "INTERNAL") else "（公开！工具会拒绝推送）"))

    # 5. 同步状态
    st = load_json(STATUSF, {})
    if st:
        ok(st.get("ok") is True, f"上次同步：{st.get('msg')}（{st.get('time','')[:16]}）")
    else:
        out.append(("ℹ️", "尚未同步过"))
    if os.path.exists(BLOCKF):
        ok(False, "⚠️ 存在 SYNC_BLOCKED.md（有变更被密钥扫描拦截）")
    else:
        out.append(("✅", "无密钥拦截残留"))

    # 6. 路径映射健康度
    m = load_json(MAPF, {})
    stale = [k for k in m if not os.path.isdir(k)]
    if m:
        ok(not stale, f"路径映射 {len(m)} 条全部有效" if not stale
           else f"路径映射 {len(m)} 条，其中 {len(stale)} 条指向已不存在的目录（旧机器残留，可清理）")

    # 8. 看板安全（看板把整个知识库发布成网页，必须加密后再部署）
    aikb = os.path.expanduser("~/.ai-kb")
    if os.path.isdir(os.path.join(KB, "_dashboard")):
        ok(False, "发现旧版明文看板产物 _dashboard/：若曾部署到公开托管，请迁移到加密版（build_dashboard.py）并轮换网址（deploy_dashboard.sh --rotate）")
    dout = os.path.join(aikb, "dashboard_out")
    if os.path.isdir(dout):
        enc = os.path.isfile(os.path.join(dout, "vault", "params.json"))
        leak = [n for n in ("search-index.json", "nav.json", "content") if os.path.exists(os.path.join(dout, n))]
        ok(enc and not leak, "看板待部署产物是加密的" if enc and not leak else "看板待部署产物含明文或不完整，不要部署")
    if os.path.isfile(os.path.join(aikb, "dashboard_pass")):
        mode = os.stat(os.path.join(aikb, "dashboard_pass")).st_mode & 0o077
        ok(mode == 0, "看板口令文件权限 600" if mode == 0 else "看板口令文件权限过宽，请 chmod 600 ~/.ai-kb/dashboard_pass")
    if os.path.isfile(os.path.join(aikb, "kb_project.old")):
        out.append(("⚠️", "有待清理的旧看板项目（~/.ai-kb/kb_project.old）：确认新站可用后执行 KB_CONFIRM=1 bash deploy_dashboard.sh --purge-old"))

    # 7. 项目识别自测
    cases = [("/tmp", "_general"), (KB, "_general")]      # 用实际知识库路径（旧版硬编码 ~/ai-knowledge-base，知识库在别处会误报并写入幽灵映射）
    bad = []
    for cwd, want in cases:
        got = project(cwd, persist=False)[0]
        if got != want:
            bad.append(f"{cwd}→{got}(应为 {want})")
    ok(not bad, "项目识别：临时目录/知识库根 均正确归 _general" if not bad else f"识别异常：{'; '.join(bad)}")

    print("\n".join(f"{a} {m_}" for a, m_ in out))
    fail = sum(1 for a, _ in out if a == "❌")
    warn = sum(1 for a, _ in out if a == "ℹ️")
    print(f"\n体检结果：{len(out) - fail - warn} 通过，{fail} 失败，{warn} 条提示")
    if fail:
        print("⚠️ 有失败项，按上面提示处理；若涉及凭证/可见性，需用户本人处理")
    return 1 if fail else 0



# ---------- 会话覆盖度（coverage）：「有没有遗漏」随时可验证 ----------
SESSION_SOURCES = (("claude-code", "~/.claude/projects"), ("workbuddy", "~/.workbuddy/projects"), ("codebuddy", "~/.codebuddy/projects"))
_PATH_RE = re.compile(r"[\w][\w./-]{2,}\.(?:py|md|sql|ya?ml|json|tsx?|jsx?|html|sh|toml|csv)\b")
_SNAKE_RE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+){2,}\b")
_PR_RE = re.compile(r"\bPR-\d+\b")
_COMMON_TERMS = {"__init__", "__main__", "package.json", "readme.md", "claude.md", "todo.md", "log.md", "questions.md",
                 "glossary.md", "settings.json", "tool_use_id", "tool_result"}


def _parse_ts(t):
    if isinstance(t, (int, float)):
        return datetime.datetime.fromtimestamp(t / 1000 if t > 1e11 else t).astimezone()
    if not t:
        return None
    t = str(t).replace("Z", "+00:00")
    try:
        d = datetime.datetime.fromisoformat(t)
    except ValueError:
        try:
            d = datetime.datetime.fromisoformat(re.sub(r"\.\d+", "", t))
        except ValueError:
            return None
    return d if d.tzinfo else d.astimezone()


def _msg_text(c):
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") in ("text", "input_text", "output_text"))
    return ""


def _real_user(s):
    s = re.sub(r"<system-reminder.*?</system-reminder>", "", s, flags=re.S)
    s = re.sub(r"<(?:command-name|command-message|command-args|local-command-stdout|task-notification)\b.*?</[a-z-]+>", "", s, flags=re.S)
    s = re.sub(r"(?m)^(UserPromptSubmit|SessionStart|Stop|PreCompact) hook.*$", "", s)
    s = re.sub(r"(?m)^\[(知识库|清单)提醒\].*$", "", s)
    return s.strip()


def _top_terms(text, n=40):
    c = collections.Counter()
    for rx in (_PATH_RE, _SNAKE_RE, _PR_RE):
        for m in rx.finditer(text):
            c[m.group(0).lower()] += 1
    terms = [(t, k) for t, k in c.items() if k >= 2 and t not in _COMMON_TERMS and len(t) >= 5]
    terms.sort(key=lambda x: -x[1])
    return [t for t, _ in terms[:n]]


def scan_sessions():
    """遍历本机各 agent 的会话文件，只读，返回元数据与抽取出的标识符（不保留原文）。"""
    out = []
    for label, base in SESSION_SOURCES:
        base = os.path.expanduser(base)
        if not os.path.isdir(base):
            continue
        for d in sorted(os.listdir(base)):
            dp = os.path.join(base, d)
            if not os.path.isdir(dp):
                continue
            for f in sorted(os.listdir(dp)):
                if not f.endswith(".jsonl"):
                    continue
                path = os.path.join(dp, f)
                uturns, achars, first, last, title, cwd, sid, buf = 0, 0, None, None, "", "", None, []
                try:
                    with open(path, encoding="utf-8", errors="replace") as fh:
                        for line in fh:
                            try:
                                x = json.loads(line)
                            except Exception:
                                continue
                            t = x.get("type")
                            if t in ("custom-title", "ai-title"):
                                title = x.get("customTitle") or x.get("aiTitle") or title
                            elif t in ("user", "assistant") and not x.get("isSidechain"):
                                sid = sid or x.get("sessionId")
                                cwd = cwd or x.get("cwd") or ""
                                ts = _parse_ts(x.get("timestamp"))
                                if ts:
                                    first = first or ts
                                    last = ts
                                body = _msg_text((x.get("message") or {}).get("content"))
                                if t == "user":
                                    body = _real_user(body)
                                    if len(body) > 1:
                                        uturns += 1
                                else:
                                    achars += len(body)
                                buf.append(body)
                except Exception:
                    continue
                if not first:
                    continue
                out.append(dict(src=label, sid=sid or f[:8], cwd=cwd, title=title, first=first, last=last,
                                user_turns=uturns, asst_chars=achars, terms=_top_terms("\n".join(buf))))
    return out


def _kb_corpus():
    parts = []
    for dp, dn, fn in os.walk(PROJ):
        dn[:] = [x for x in dn if not x.startswith(".")]
        for f in fn:
            if f.endswith((".md", ".html", ".txt", ".sql", ".py", ".json", ".yaml", ".yml", ".csv")):
                try:
                    parts.append(read(os.path.join(dp, f)).lower())
                except Exception:
                    pass
    return "\n".join(parts)


def _kb_commits():
    if not (HAS_GIT and os.path.isdir(os.path.join(KB, ".git"))):
        return []
    out = git("log", "--name-only", "--format=@@%cI").stdout
    res, cur = [], None
    for line in out.splitlines():
        if line.startswith("@@"):
            cur = [_parse_ts(line[2:]), set()]
            res.append(cur)
        elif cur is not None and line.startswith("projects/"):
            cur[1].add(line.split("/")[1])
    return [(t, p) for t, p in res if t and p]


def cmd_coverage(write=True):
    """盘点本机 AI 会话 ↔ 知识库：每个会话是否被整理，并生成 _meta/session-ledger.md。
    判断依据（启发式，按强弱）：①知识库里出现该会话号前 8 位（补录/自动记录会写入）→ 已整理；
    ②从会话抽取最常出现的独特标识符（文件名/表名/函数名/PR 号，≤40 个），在知识库里出现的比例：≥80% 已覆盖，50–80% 部分覆盖，<50% 未整理；
    ③会话期间知识库有提交 → 有写入痕迹。<3 条用户发言的视为轻量会话，不判断。"""
    sess = scan_sessions()
    if not sess:
        print("没有找到本机的会话目录（~/.claude/projects、~/.workbuddy/projects、~/.codebuddy/projects）")
        return 0
    corpus = _kb_corpus()
    commits = _kb_commits()
    first_kb = min((t for t, _ in commits), default=None)
    rows = []
    for s in sess:
        name = project(s["cwd"], persist=False)[0] if s["cwd"] else "_general"
        lo, hi = s["first"] - datetime.timedelta(minutes=2), s["last"] + datetime.timedelta(minutes=30)
        wrote = any(lo <= t <= hi for t, _ in commits)
        id_hit = bool(s["sid"]) and s["sid"][:8] in corpus
        pct = (sum(1 for t in s["terms"] if t in corpus) / len(s["terms"])) if len(s["terms"]) >= 5 else None
        if id_hit:      # 知识库里有会话号 = 已整理（不论会话长短；轻量会话补录后也应显示为已整理）
            st, basis = "已整理", "知识库含会话号"
        elif s["user_turns"] < 3:
            st, basis = "轻量·未判断", "发言<3"
        elif pct is not None:
            st = "已覆盖" if pct >= 0.8 else ("部分覆盖" if pct >= 0.5 else "未整理")
            basis = f"标识符命中 {pct*100:.0f}%" + ("；会话期间有写入" if wrote else "")
        elif wrote:
            st, basis = "有写入痕迹", "会话期间知识库有提交（无法量化）"
        else:
            st, basis = "无法判断", "讨论类，标识符不足"
        pre = first_kb is not None and s["last"] < first_kb
        rows.append(dict(s, project=name, status=st, basis=basis, pre=pre))
    rows.sort(key=lambda r: r["first"])
    cnt = collections.Counter(r["status"] for r in rows)
    heavy = [r for r in rows if r["user_turns"] >= 3]
    hc = collections.Counter(r["status"] for r in heavy)
    print(f"本机会话 {len(rows)} 个（来源：{', '.join(sorted(set(r['src'] for r in rows)))}）；其中实质性（≥3 条发言）{len(heavy)} 个")
    print("状态分布（全部）：", dict(cnt))
    print("状态分布（实质性）：", dict(hc))
    gaps = [r for r in heavy if r["status"] in ("未整理", "部分覆盖")]
    if gaps:
        print(f"\n需要关注（未整理/部分覆盖，共 {len(gaps)} 个）：")
        for r in sorted(gaps, key=lambda r: -r["user_turns"])[:15]:
            print(f"  {r['first'].strftime('%m-%d')} {r['project'][:18]:18} {r['user_turns']:>3}发言 {r['status']}  {(r['title'] or '(无标题)')[:36]}")
    if write:
        lines = ["# 会话台账（由 `kb.py coverage` 自动生成，请勿手改）", "",
                 f"> 生成于 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}。盘点本机各 AI agent 的会话与知识库的对应关系，用来回答「有没有遗漏」。",
                 "> 判断是启发式的：知识库含会话号=已整理；否则看会话里的文件名/表名/函数名在知识库里出现的比例。", "",
                 "| 状态 | 数量 |", "|---|---|"] + [f"| {k} | {v} |" for k, v in cnt.most_common()] + ["",
                 "| 会话 | 来源 | 日期 | 项目 | 发言 | 状态 | 依据 | 标题 |", "|---|---|---|---|---|---|---|---|"]
        for r in rows:
            lines.append(f"| {r['sid'][:8]} | {r['src']} | {r['first'].strftime('%Y-%m-%d')} | {r['project']} | {r['user_turns']} | {r['status']} | {r['basis']} | {(r['title'] or '').replace('|', '/')[:40]} |")
        write_p = os.path.join(META, "session-ledger.md")
        os.makedirs(META, exist_ok=True)
        with open(write_p, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        print(f"\n台账已写入 {write_p}")
    return 0


def cmd_clean_stale():
    """清理 _meta/map.json 里指向已不存在目录的路径映射（不动任何项目内容）。"""
    m = load_json(MAPF, {})
    stale = [k for k in m if not os.path.isdir(k)]
    if not stale:
        print("没有失效的路径映射")
        return 0
    print("将移除以下失效映射（只删映射，不删项目内容）：")
    for k in stale:
        print(f"  - {k} → {m[k]}")
    if os.environ.get("KB_CONFIRM") != "1":
        print("\n这是预览。确认要删就加环境变量重跑：KB_CONFIRM=1 kb.py clean-stale")
        return 0
    for k in stale:
        m.pop(k)
    write(MAPF, json.dumps(m, indent=2, ensure_ascii=False))
    print(f"\n✅ 已清理 {len(stale)} 条失效映射")
    return 0


def cmd_export(path):
    """把整个知识库导出成一个可直接阅读的单个 markdown 文件。"""
    path = os.path.expanduser(path)
    parts = [f"# 知识库导出（{today}）\n",
             f"- 源目录：{KB}", f"- 项目数：{len(all_projects())}\n",
             "\n---\n"]
    for name in all_projects():
        d = os.path.join(PROJ, name)
        parts.append(f"\n# 项目：{name}\n")
        for f in ("README.md", "todo.md", "questions.md", "glossary.md", "log.md"):
            fp = os.path.join(d, f)
            if os.path.isfile(fp):
                body = re.sub(r"<!-- AUTO:BEGIN.*?<!-- AUTO:END -->", "", read(fp), flags=re.S).strip()
                parts.append(f"\n## {f}\n\n{body}\n")
        for sub in ("discussions", "decisions"):
            p = os.path.join(d, sub)
            fs = sorted(x for x in os.listdir(p) if x.endswith(".md")) if os.path.isdir(p) else []
            if fs:
                parts.append(f"\n## {sub}/\n")
                for x in fs:
                    parts.append(f"\n### {x}\n\n{read(os.path.join(p, x))}\n")
    write(path, "\n".join(parts))
    print(f"✅ 已导出到 {path}（{os.path.getsize(path)} 字节）")
    return 0



def cmd_audit():
    """盘点：把知识库现状完整列出来，用于确认「所有内容都在」。
    不修改任何东西，纯只读。"""
    print(f"\n📊 知识库盘点 · {today}")
    print(f"目录：{KB}\n")
    rows, total_files, total_bytes = [], 0, 0
    for name in all_projects():
        d = os.path.join(PROJ, name)
        s = stats(name)
        files = 0
        size = 0
        for dp, dn, fn in os.walk(d):
            for f in fn:
                fp = os.path.join(dp, f)
                if not os.path.isfile(fp):
                    continue
                files += 1
                try:
                    size += os.path.getsize(fp)
                except OSError:
                    pass
        total_files += files
        total_bytes += size
        rows.append((name, s['t_open'], s['q_open'], len(s['disc']), len(s['dec']), len(s['art']), files, size, s['last']))
    w = [max(18, max(len(str(r[i])) for r in rows)) for i in range(9)]
    hdr = ("项目", "待办", "问题", "纪要", "决议", "产物", "文件", "体积", "最近")
    print("  ".join(h.ljust(w[i]) for i, h in enumerate(hdr)))
    print("  ".join("-" * w[i] for i in range(9)))
    for r in rows:
        cells = [r[0], str(r[1]), str(r[2]), str(r[3]), str(r[4]), str(r[5]), str(r[6]),
                 f"{r[7]/1024:.0f}K", r[8] or "-"]
        print("  ".join(c.ljust(w[i]) for i, c in enumerate(cells)))
    print(f"\n合计：{len(rows)} 个项目，{total_files} 个文件，{total_bytes/1024/1024:.1f} MB")

    st = load_json(STATUSF, {})
    if st:
        print(f"同步：{st.get('msg')}（{st.get('time','')[:16]}）")
    url = remote_url()
    print(f"远程：{url or '未配置'}")
    if url:
        commits = git("rev-list", "--count", "HEAD").stdout.strip()
        print(f"提交数：{commits or '?'}（历史都在，可随时回溯）")
    print("\n🔒 提醒：本工具不提供删除命令。历史只在 git 里，删了要从提交历史恢复。")
    return 0


# ---------- 主流程 ----------
def main():
    if mode == "_push":
        do_push()
        return
    if mode == "search":
        search(sys.argv[2:])
        return
    if mode == "audit":
        sys.exit(cmd_audit())
    if mode == "coverage":
        sys.exit(cmd_coverage(write="--no-write" not in sys.argv))
    if mode == "doctor":
        sys.exit(cmd_doctor())
    if mode == "clean-stale":
        sys.exit(cmd_clean_stale())
    if mode == "export":
        sys.exit(cmd_export(sys.argv[2] if len(sys.argv) > 2 else "~/ai-knowledge-base-export.md"))
    try:
        data = json.load(sys.stdin) if mode in HOOK_MODES else {}
    except Exception:
        data = {}
    cwd = data.get("cwd") or os.getcwd()
    ensure_kb()
    # 只有「agent 在某个项目里工作」的模式才把当前目录登记成项目。
    # build / status / sync / init 是维护命令，在哪个目录运行都不该顺手创建项目
    # （旧版会：在工具仓库里跑一次 build 就在知识库里多出一个空项目并写入 map.json）。
    if mode in ("sessionstart", "context", "prompt", "precompact", "stop"):
        name, root = project(cwd)
        ensure_project(name, root)
    else:
        name, root = "_general", ""

    if mode == "init":
        build()
        print(f"知识库已就绪：{KB}")
    elif mode == "build":
        build()
        print("已重新生成各项目 README 自动区块和根目录总页")
    elif mode == "status":
        for n in all_projects():
            s = stats(n)
            print(f"{n}: 未完成待办 {s['t_open']} / 未决问题 {s['q_open']} / 讨论 {len(s['disc'])} / 决议 {len(s['dec'])} / 产物 {len(s['art'])} / 最近 {s['last']}")
        print("同步状态:", load_json(STATUSF, {}) or "无记录", "| 远程:", "已配置" if has_remote() else "未配置")
    elif mode == "sync":
        build()
        ok = commit(f"manual sync {today}")
        pull()
        if ok:
            print("推送结果:", "成功" if do_push() else load_json(STATUSF, {}).get("msg"))
        else:
            print("提交被密钥扫描拦截，见", BLOCKF)
    elif mode in ("sessionstart", "context"):
        build()
        commit(f"snapshot {today}")
        pull()
        ctx = build_context(name, root)
        if mode == "context":
            print(ctx)
        else:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": ctx}}, ensure_ascii=False))
    elif mode == "precompact":
        print(f"压缩摘要必须保留：本次对话中所有尚未写入知识库 {os.path.join(PROJ, name)} 的内容——讨论要点与结论（discussions/）、决议（decisions/）、待办与优化项（todo.md）、"
              f"待讨论问题（questions.md）、生成的产物（artifacts/）——逐条列出，并注明路径；压缩后第一件事是把它们补写进知识库。")
    elif mode == "prompt":
        print(f"[知识库提醒] 当前项目 {name}，目录 {os.path.join(PROJ, name)}。本轮若有新的讨论要点/结论/决议/待办/优化项/待讨论问题/生成的产物，当轮写入对应文件（讨论纪要需自包含，产物要存原文件并登记 artifacts/INDEX.md），并在 log.md 追加一行；"
              f"回复末尾标注“已记录 N 条”；无则无需提及。归属拿不准先问用户。")
    elif mode == "stop":
        build()
        commit(f"auto {today}")
        push_bg()
        if data.get("stop_hook_active"):
            return
        tp = data.get("transcript_path")
        if not tp or not os.path.exists(tp):
            return
        msgs = []
        for line in open(tp, encoding="utf-8", errors="ignore"):
            try:
                msgs.append(json.loads(line))
            except Exception:
                pass

        def real_user(m):
            if m.get("type") != "user":
                return False
            c = m.get("message", {}).get("content")
            return bool(c.strip()) if isinstance(c, str) else any(b.get("type") == "text" for b in c or [])

        last = max((i for i, m in enumerate(msgs) if real_user(m)), default=-1)
        text_len, wrote, edited_other = 0, False, False
        for m in msgs[last + 1:]:
            if m.get("type") != "assistant":
                continue
            for b in m.get("message", {}).get("content") or []:
                if b.get("type") == "text":
                    text_len += len(b.get("text", ""))
                elif b.get("type") == "tool_use":
                    s = json.dumps(b.get("input", {}), ensure_ascii=False)
                    if KBNAME in s:
                        wrote = True
                    elif b.get("name") in ("Edit", "Write", "NotebookEdit"):
                        edited_other = True
        if not wrote and (text_len > 500 or edited_other):
            print(json.dumps({"decision": "block", "reason":
                  f"知识库检查：本轮内容较多但没有写入知识库（{os.path.join(PROJ, name)}）。若有讨论要点/结论/决议/待办/优化项/待讨论问题/生成的产物未记录，现在写入并在 log.md 追加；"
                  f"若确实没有，回复“本轮无需记录”即可。"}, ensure_ascii=False))
    else:
        print(__doc__)


if __name__ == "__main__":
    if mode in HOOK_MODES:
        try:
            main()
        except Exception:
            sys.exit(0)
    else:
        main()
