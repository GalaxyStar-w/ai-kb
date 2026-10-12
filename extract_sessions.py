#!/usr/bin/env python3
"""从 AI 会话记录（.jsonl）提炼可读纪要，供导入知识库。支持 WorkBuddy 与 Claude Code。

只提取：用户提问 + 助手的文字回答（跳过工具调用、工具输出、思考过程、文件快照）。
纯只读，不修改任何原始文件。
**自动脱敏**：疑似密钥/token/密码/私钥/连接串账号密码在写出前替换为 <REDACTED>（会话原文含敏感信息的风险比精炼档案高得多）。

用法：
  python3 extract_sessions.py --all [输出目录] [--source auto|workbuddy|claude]
  python3 extract_sessions.py <工作区目录名> [--source ...]        # 输出到屏幕
默认 --source auto：存在哪个就提取哪个（~/.workbuddy/projects、~/.claude/projects）。
"""
import sys, os, json, re, glob, datetime

SOURCES = {
    "workbuddy": os.path.expanduser("~/.workbuddy/projects"),
    "claude": os.path.expanduser("~/.claude/projects"),
}

# 与 kb.py 的密钥扫描规则保持一致（提取出的纪要入库前也会被 kb.py 扫描，这里先脱敏，避免整批被拦）
SECRET_PATTERNS = [
    r"AKIA[0-9A-Z]{16}", r"gh[pousr]_[A-Za-z0-9]{30,}", r"sk-[A-Za-z0-9_\-]{20,}", r"xox[baprs]-[A-Za-z0-9-]{10,}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)", r"Bearer\s+[A-Za-z0-9._\-]{24,}",
    r"(?<=://)[^\s:@/]+:[^\s@/]{3,}(?=@)",
    r"(?i)\b(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?key|token)\b\s*[:=]\s*['\"]?[^\s'\"<>{}$]{8,}",
]
_SECRET_RE = [re.compile(x) for x in SECRET_PATTERNS]
REDACTIONS = 0


def redact(text):
    """把疑似凭证替换为 <REDACTED>，返回脱敏后的文本。"""
    global REDACTIONS
    for rx in _SECRET_RE:
        text, n = rx.subn("<REDACTED>", text)
        REDACTIONS += n
    return text


def norm_ts(t):
    """timestamp 可能是 ISO 字符串或毫秒/秒时间戳，统一成 ISO 字符串。"""
    if isinstance(t, str):
        return t
    if isinstance(t, (int, float)):
        v = t / 1000 if t > 1e11 else t
        try:
            return datetime.datetime.fromtimestamp(v).isoformat()
        except Exception:
            return ""
    return ""


def text_of(content):
    """把 message.content 里的文字部分抽出来。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if not isinstance(b, dict):
                continue
            # 实测：用户块是 input_text，助手块是 output_text
            if b.get("type") in ("text", "input_text", "output_text"):
                parts.append(b.get("text", ""))
        return "\n".join(parts)
    return ""


NOISE = re.compile(
    r"<(system-reminder|command-name|command-message|local-command-stdout|"
    r"user-prompt-submit-hook|hook|attachment|ide_selection|environment_details)")


def clean(s):
    """去掉注入的系统上下文，只保留用户真实说的话。

    会话里每条消息都带<system-reminder>（user_info / identity_context / memory 注入），
    以及 hook 提醒、文件快照引用——这些是机器注入的噪音，必须清掉，
    否则提取出来全是模板文字，没有实际内容。
    """
    if not s:
        return ""
    # 反复剥离（注入块可能嵌套多段）
    for _ in range(6):
        before = s
        s = re.sub(r"<system-reminder\b[^>]*>.*?</system-reminder>", "", s, flags=re.S)
        s = re.sub(r"<system-reminder\b[^>]*/>", "", s)
        s = re.sub(r"<(?:command-name|command-message|command-args|"
                   r"local-command-stdout|attachment|ide_selection|"
                   r"environment_details|workspace_context|user-info)\b[^>]*>"
                   r".*?</[a-z_-]+>", "", s, flags=re.S)
        if s == before:
            break
    # 去掉注入文件清单（"Path: ..." 这类）
    s = re.sub(r"^#+\s*(SOUL|IDENTITY|USER|BOOTSTRAP)\.md$", "", s, flags=re.M)
    s = re.sub(r"^Path: .*$", "", s, flags=re.M)
    s = re.sub(r"^Injected workspace identity files:.*$", "", s, flags=re.M)
    return s.strip()


def extract_one(path):
    """返回 dict：{会话id, 标题, 工作目录, 时间, 轮次[(role, text)]}"""
    turns, title, cwd, sid, ts = [], None, None, None, None
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                t = d.get("type")
                if t == "session-meta":
                    sid = d.get("sessionId") or d.get("id")
                    ts = norm_ts(d.get("timestamp"))
                    cwd = (d.get("meta") or {}).get("cwd") or d.get("cwd")
                elif t == "ai-title":
                    title = d.get("aiTitle")
                elif t == "message":
                    role = d.get("role")
                    body = clean(text_of(d.get("content")))
                    if body and len(body) > 1:
                        cwd = cwd or d.get("cwd")
                        raw = d.get("timestamp")
                        if not ts:
                            ts = norm_ts(raw)
                        turns.append((role, body))
    except Exception as e:
        return None
    if not turns:
        return None
    return dict(sid=sid or os.path.basename(path)[:8], title=title, cwd=cwd,
                ts=ts, turns=turns)


def extract_one_claude(path):
    """解析 Claude Code 会话（~/.claude/projects/<编码路径>/<会话id>.jsonl）。
    行类型：user / assistant（message.content 为字符串或块列表，取其中 type=text 的块），
    custom-title / ai-title 给出标题；其余（工具调用、思考、附件、快照）一律跳过。"""
    turns, title, cwd, sid, ts = [], None, None, None, None
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                t = d.get("type")
                if t in ("custom-title", "ai-title"):
                    title = d.get("customTitle") or d.get("aiTitle") or title
                elif t in ("user", "assistant"):
                    sid = sid or d.get("sessionId")
                    cwd = cwd or d.get("cwd")
                    ts = ts or norm_ts(d.get("timestamp"))
                    msg = d.get("message") or {}
                    body = clean(text_of(msg.get("content")))
                    if body and len(body) > 1:
                        turns.append((t, body))
    except Exception:
        return None
    if not turns:
        return None
    return dict(sid=sid or os.path.basename(path)[:8], title=title, cwd=cwd, ts=ts, turns=turns)


EXTRACTORS = {"workbuddy": extract_one, "claude": extract_one_claude}


def active_sources(choice):
    names = [choice] if choice in SOURCES else list(SOURCES)
    return [(n, SOURCES[n]) for n in names if os.path.isdir(SOURCES[n])]


def fmt_session(s):
    L = []
    title = s["title"] or "（无标题）"
    day = (s["ts"] or "")[:10] or "未知日期"
    L.append(f"## 会话 · {title}")
    L.append(f"- 时间：{day}")
    if s["cwd"]:
        L.append(f"- 工作目录：`{s['cwd']}`")
    L.append(f"- 有效轮次：{len(s['turns'])}\n")
    for role, body in s["turns"]:
        who = "👤 用户" if role == "user" else "🤖 助手"
        # 长回答截断，避免把知识库塞满噪音
        b = body if len(body) <= 1500 else body[:1500] + "\n…（已截断，完整内容见原始会话）"
        L.append(f"### {who}\n\n{redact(b)}\n")
    return "\n".join(L)


def workspace_name(d):
    """会话目录名把 cwd 编码了（/Users/<用户名>/<路径> → Users-<用户名>-<路径> 或 -Users-...）。
    通用做法：去掉前缀，不针对特定用户名。"""
    return re.sub(r"^-?Users-[^\/]+-", "", d)


def main():
    args = sys.argv[1:]
    source = "auto"
    if "--source" in args:
        i = args.index("--source")
        source = args[i + 1] if i + 1 < len(args) else "auto"
        del args[i:i + 2]
    if not args:
        print(__doc__)
        return 1
    srcs = active_sources(source)
    if not srcs:
        print("✘ 没有找到会话目录（~/.workbuddy/projects 或 ~/.claude/projects）")
        return 1
    if args[0] == "--all":
        outdir = os.path.expanduser(args[1]) if len(args) > 1 else os.path.join(os.path.expanduser("~"), "kb-extract")
        os.makedirs(outdir, exist_ok=True)
        total_dirs = total_sess = 0
        for label, base in srcs:
            for d in sorted(os.listdir(base)):
                if not os.path.isdir(os.path.join(base, d)):
                    continue
                ws = workspace_name(d)
                safe = re.sub(r"[^\w一-鿿-]", "_", ws)
                chunks = []
                for f in sorted(glob.glob(os.path.join(base, d, "*.jsonl"))):
                    s = EXTRACTORS[label](f)
                    if s:
                        chunks.append(fmt_session(s))
                if not chunks:
                    continue
                total_dirs += 1
                total_sess += len(chunks)
                out = os.path.join(outdir, f"{label}-{safe}.md")      # 文件名带来源，两种来源同名工作区不会互相覆盖
                with open(out, "w", encoding="utf-8") as fh:
                    fh.write(f"# 工作区：{ws}\n\n来源：{label}　源目录：`{base}/{d}`\n"
                             f"会话数：{len(chunks)}\n\n---\n\n" + "\n\n---\n\n".join(chunks))
        print(f"✅ 提取完成：{total_dirs} 个工作区，{total_sess} 个会话 → {outdir}")
        print(f"🔒 自动脱敏：{REDACTIONS} 处疑似凭证已替换为 <REDACTED>（仍建议入库前人工浏览一遍）")
        return 0
    d = args[0]
    for label, base in srcs:
        for f in sorted(glob.glob(os.path.join(base, d, "*.jsonl"))):
            s = EXTRACTORS[label](f)
            if s:
                print(fmt_session(s))
    return 0


if __name__ == "__main__":
    sys.exit(main())