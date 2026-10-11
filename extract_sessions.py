#!/usr/bin/env python3
"""从WorkBuddy 会话记录（.jsonl）提炼可读纪要，供导入知识库。

只提取：用户提问 + 助手的文字回答（跳过工具调用、工具输出、思考过程、文件快照）。
纯只读，不修改任何原始文件。

用法：
  python3 extract_sessions.py <工作区目录名> [输出文件]
  python3 extract_sessions.py --all<输出目录>
"""
import sys, os, json, re, glob, datetime

BASE = os.path.expanduser("~/.workbuddy/projects")


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
        L.append(f"### {who}\n\n{b}\n")
    return "\n".join(L)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    if sys.argv[1] == "--all":
        outdir = sys.argv[2] if len(sys.argv) > 2 else "/tmp/kb-extract"
        os.makedirs(outdir, exist_ok=True)
        dirs = [d for d in sorted(os.listdir(BASE))
                if os.path.isdir(os.path.join(BASE, d))]
        total_sess = 0
        for d in dirs:
            # WorkBuddy 把cwd 编码成目录名：/Users/<用户名>/<路径> → Users-<用户名>-<路径>
            # 通用做法：去掉前缀 "Users-<用户名>-"，不针对特定用户名
            ws = re.sub(r"^Users-[^\/]+-", "", d)
            safe = re.sub(r"[^\w一-鿿-]", "_", ws)
            chunks = []
            for f in sorted(glob.glob(os.path.join(BASE, d, "*.jsonl"))):
                s = extract_one(f)
                if s:
                    chunks.append(fmt_session(s))
            if not chunks:
                continue
            total_sess += len(chunks)
            out = os.path.join(outdir, f"{safe}.md")
            with open(out, "w", encoding="utf-8") as fh:
                fh.write(f"# 工作区：{ws}\n\n源目录：`~/.workbuddy/projects/{d}`\n"
                         f"会话数：{len(chunks)}\n\n---\n\n" + "\n\n---\n\n".join(chunks))
        print(f"✅ 提取完成：{len(dirs)} 个工作区，{total_sess} 个会话 → {outdir}")
        return 0
    d = sys.argv[1]
    for f in sorted(glob.glob(os.path.join(BASE, d, "*.jsonl"))):
        s = extract_one(f)
        if s:
            print(fmt_session(s))
    return 0


if __name__ == "__main__":
    sys.exit(main())