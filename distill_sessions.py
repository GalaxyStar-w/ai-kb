#!/usr/bin/env python3
"""从历史会话归档中提炼「结论 / 待办 / 决议」，产出结构化档案。

只读输入，输出到 stdout 或指定文件。不修改任何归档原文。
"""
import re, sys, os, json


def load_blocks(path):
    s = open(path, encoding="utf-8").read()
    return re.split(r"\n(?=## 会话 · )", s)


def turns(block):
    """返回 [(role, text)]，跳过会话压缩摘要这类机器噪音。"""
    out = []
    for m in re.finditer(r"### (👤 用户|🤖 助手)\n\n(.*?)(?=\n\n### |\n\n---|\n\n<!--|\Z)",
                         block, re.S):
        who, body = m.group(1), m.group(2)
        body = re.sub(r"<user_query>|</user_query>", "", body).strip()
        # 机器噪音：压缩摘要 / 续跑指令
        if body.startswith("<conversation_history_summary>") or \
           body.startswith("Please continue with the conversation") or \
           "请继续完成未完成的任务" in body[:30] or \
           body.startswith("<system-reminder"):
            continue
        if len(body) < 3:
            continue
        out.append(("user" if "用户" in who else "assistant", body))
    return out


# 决策/结论信号
SIGNALS = {
    "决定": r"(决定|就这么定|定下来|敲定|采用|选了|选择|不做|放弃)",
    "待办": r"(需要做|待办|下一步|接下来要|回头要|得去|要去)",
    "风险": r"(风险|问题在于|隐患|坑|注意|小心)",
    "偏好": r"(我不喜欢|我更|我倾向|我不想要|太麻烦)",
}

TOPIC_KEYS = {
    "小红书": ["小红书", "爆款", "种草"],
    "dify": ["dify", "Dify"],
    "taptap": ["taptap", "TapTap", "小游戏", "steam"],
    "游戏": ["游戏", "game", "玩法", "关卡", "剧情"],
    "副业": ["副业", "变现", "接单", "赚钱", "商业化"],
    "工作台": ["工作台", "同步", "索引"],
}


def tag_topic(title, body):
    blob = (title + " " + body[:400]).lower()
    hits = [k for k, v in TOPIC_KEYS.items() if any(x.lower() in blob for x in v)]
    return hits or ["其他"]


def extract(path, max_items=40):
    blocks = load_blocks(path)
    sessions = []
    for b in blocks:
        head = b.split("\n")[0]
        if not head.startswith("## 会话"):
            continue
        title = head.replace("## 会话 · ", "").strip()
        ts = (re.search(r"- 时间：(\S+)", b) or [None, ""])[1]
        cwd = (re.search(r"- 工作目录：`([^`]+)`", b) or [None, ""])[1]
        tv = turns(b)
        if not tv:
            continue
        blob = " ".join(t for _, t in tv)
        sessions.append(dict(title=title, ts=ts, cwd=cwd, turns=tv,
                             topics=tag_topic(title, blob)))
    return sessions


def main():
    path = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else "list"
    sess = extract(path)
    if mode == "list":
        for i, s in enumerate(sess, 1):
            print(f"{i:>3}. [{s['ts']}] {s['title']}")
            print(f"     轮次{len(s['turns'])} | 主题 {','.join(s['topics'])} | {s['cwd'] or '-'}")
    elif mode == "dump":
        idx = int(sys.argv[3]) - 1
        s = sess[idx]
        print(f"# {s['title']}\n时间 {s['ts']} | 目录 {s['cwd']}\n")
        for r, t in s["turns"]:
            who = "👤 用户" if r == "user" else "🤖 助手"
            print(f"### {who}\n\n{t[:2000]}\n")
    elif mode == "stats":
        from collections import Counter
        c = Counter(t for s in sess for t in s["topics"])
        print(f"共 {len(sess)} 个有效会话\n主题分布：")
        for k, v in c.most_common():
            print(f"  {k}: {v} 会话")


if __name__ == "__main__":
    main()