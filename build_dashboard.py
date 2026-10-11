#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_dashboard.py —— 把知识库烘焙成静态网页看板（AI 知识总控台）。

设计目标：
1. **不读 GitHub、不发网络请求**：构建时把 `projects/` 全部转成静态 HTML + 预建搜索索引，
   线上访问直接读文件 → 秒开。
2. **不内嵌超大内容**：`search`（kb.py）会 os.walk 整个仓库，所以看板只放"索引 + 摘要"，
   正文按需从 `content/` 单独文件取；>200KB 的文件只存摘要，标记懒加载。
3. **纯标准库**，和 kb.py 保持一致，可直接在 GitHub Actions 里跑。

用法：
    python3 _tool/build_dashboard.py            # 输出到仓库根 _dashboard/
    python3 _tool/build_dashboard.py --out DIR  # 指定输出目录
"""

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
KB = os.path.dirname(HERE)              # 仓库根
PROJ = os.path.join(KB, "projects")
TPL = os.path.join(HERE, "_dashboard_template")   # 静态页模板目录

# 超过这个大小的 md，正文不入库，只保留摘要 + 懒加载标记
BIG_FILE = 200 * 1024                   # 200KB
# 搜索索引里每个文件保留的正文长度上限
INDEX_BODY_LIMIT = 4000


# ---------- 基础工具 ----------

def read(p):
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return ""


def write(p, s):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)


def all_projects():
    if not os.path.isdir(PROJ):
        return []
    return sorted(
        n for n in os.listdir(PROJ)
        if os.path.isdir(os.path.join(PROJ, n)) and not n.startswith(".")
    )


def md_files(project):
    """收集项目下所有 md（跳过自动区块以外的大产物也保留，用于索引）。"""
    root = os.path.join(PROJ, project)
    out = []
    for dp, dn, fn in os.walk(root):
        for f in fn:
            if f.endswith(".md"):
                full = os.path.join(dp, f)
                rel = os.path.relpath(full, root)
                out.append((rel, full))
    return sorted(out)


def stat_kind(rel):
    """按文件所在位置归类，用于看板分组展示。"""
    rel = rel.replace(os.sep, "/")
    if rel == "README.md":
        return "首页"
    if rel == "todo.md":
        return "待办"
    if rel == "questions.md":
        return "待讨论"
    if rel == "log.md":
        return "日志"
    if rel == "glossary.md":
        return "术语"
    if rel.startswith("discussions/"):
        return "讨论纪要"
    if rel.startswith("decisions/"):
        return "决议"
    if rel.startswith("artifacts/"):
        return "产物"
    return "其他"


# ---------- 轻量 Markdown → HTML ----------

def md_to_html(md):
    """够用的 markdown 渲染：标题/粗体/代码/列表/表格/段落/链接。"""
    lines = md.split("\n")
    out = []
    in_code = False
    in_table = False
    list_stack = []

    def close_list():
        while list_stack:
            out.append("</%s>" % list_stack.pop())

    def inline(t):
        t = (t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
        t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
        t = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", t)
        t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', t)
        return t

    for raw in lines:
        line = raw.rstrip()

        if line.strip().startswith("```"):
            out.append("</code></pre>" if in_code else "<pre><code>")
            in_code = not in_code
            continue
        if in_code:
            out.append(inline(line))
            continue

        # 表格
        if line.strip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            # 跳过 markdown 表格分隔行 |---|---| | :--- | ---: |
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                continue
            if not in_table:
                out.append("<table><thead><tr>")
                for c in cells:
                    out.append("<th>%s</th>" % inline(c))
                out.append("</tr></thead><tbody>")
                in_table = True
            else:
                out.append("<tr>")
                for c in cells:
                    out.append("<td>%s</td>" % inline(c))
                out.append("</tr>")
            continue
        if in_table:
            out.append("</tbody></table>")
            in_table = False

        h = re.match(r"^(#{1,6})\s+(.*)$", line)
        if h:
            close_list()
            lv = len(h.group(1))
            out.append("<h%d>%s</h%d>" % (lv, inline(h.group(2)), lv))
            continue

        li = re.match(r"^(\s*)([-*+]|\d+\.)\s+(.*)$", line)
        if li:
            depth = len(li.group(1)) // 2
            tag = "ul" if depth == 0 and not re.match(r"\d", li.group(2)) else "ol"
            while len(list_stack) <= depth:
                list_stack.append(tag)
                out.append("<%s>" % tag)
            out.append("<li>%s</li>" % inline(li.group(3)))
            continue

        if not line.strip():
            close_list()
            continue

        close_list()
        out.append("<p>%s</p>" % inline(line))

    if in_code:
        out.append("</code></pre>")
    if in_table:
        out.append("</tbody></table>")
    close_list()
    return "\n".join(out)


def extract_text(md):
    """从 markdown 抽纯文本，用于搜索索引和摘要。"""
    t = re.sub(r"```.*?```", " ", md, flags=re.S)
    t = re.sub(r"<!--.*?-->", " ", t, flags=re.S)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"^[#>\-*\+|]+\s*", "", t, flags=re.M)
    t = re.sub(r"[`*_~]", "", t)
    return re.sub(r"\s+", " ", t).strip()


# ---------- 主构建 ----------

def build(outdir):
    if os.path.isdir(outdir):
        shutil.rmtree(outdir)
    os.makedirs(outdir)

    # 复制静态页模板（index.html 由本脚本生成，project/view 是固定模板）
    if os.path.isdir(TPL):
        for f in os.listdir(TPL):
            if f.endswith(".html"):
                shutil.copy2(os.path.join(TPL, f), os.path.join(outdir, f))

    projects = all_projects()
    index_rows = []      # 搜索索引
    nav = []             # 项目导航
    built_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    for name in projects:
        files = md_files(name)
        pdocs = []

        def cnt(kind, _docs=None):
            return sum(1 for d in (_docs if _docs is not None else pdocs)
                       if d["kind"] == kind)

        for rel, full in files:
            size = os.path.getsize(full)
            md = read(full)
            text = extract_text(md)
            is_big = size > BIG_FILE

            pdocs.append({
                "rel": rel,
                "kind": stat_kind(rel),
                "size": size,
                "big": is_big,
                "text": text[:600],                 # 列表摘要
            })

            if is_big:
                # 超大文件：只进索引（截断），正文不生成独立页
                index_rows.append({
                    "p": name, "rel": rel, "k": stat_kind(rel),
                    "t": text[:INDEX_BODY_LIMIT], "big": True, "size": size,
                })
            else:
                write(os.path.join(outdir, "content", name, rel + ".html"),
                      md_to_html(md))
                index_rows.append({
                    "p": name, "rel": rel, "k": stat_kind(rel),
                    "t": text[:INDEX_BODY_LIMIT], "big": False, "size": size,
                })

        # 项目统计（口径与 kb.py stats() 完全一致：数条目而非文件数）
        pdir = os.path.join(PROJ, name)

        def rd(f):
            return read(os.path.join(pdir, f))

        def open_part(text, heading):
            i = text.find("\n" + heading)
            return text if i < 0 else text[:i]

        todo_txt, ques_txt, log_txt = rd("todo.md"), rd("questions.md"), rd("log.md")
        t_open = len(re.findall(r"^- \[ \]", open_part(todo_txt, "## 已完成"), re.M))
        t_done = len(re.findall(r"^- \[[xX]\]", todo_txt, re.M))
        q_open = len(re.findall(r"^- Q-\d+", open_part(ques_txt, "## 已决议"), re.M))
        dates = re.findall(r"^- (\d{4}-\d{2}-\d{2})", log_txt, re.M)

        nav.append({
            "name": name,
            "files": len(pdocs),
            "todo": t_open,
            "todo_done": t_done,
            "question": q_open,
            "disc": cnt("讨论纪要"),
            "dec": cnt("决议"),
            "art": cnt("产物"),
            "last": dates[-1] if dates else "",
        })

    write(os.path.join(outdir, "search-index.json"),
          json.dumps({"built": built_at, "rows": index_rows}, ensure_ascii=False))
    write(os.path.join(outdir, "nav.json"),
          json.dumps({"built": built_at, "projects": nav}, ensure_ascii=False))
    write(os.path.join(outdir, "index.html"), render_index(nav, built_at))
    print("构建完成：%d 个项目，%d 个文件，输出到 %s" % (len(nav), len(index_rows), outdir))


def render_index(nav, built_at):
    cards = []
    for p in nav:
        cards.append("""<div class="card" onclick="location.href='project.html?p=%s'">
      <h3>%s</h3>
      <div class="nums">
        <span><b>%d</b> 待办</span><span><b>%d</b> 待讨论</span>
        <span><b>%d</b> 纪要</span><span><b>%d</b> 决议</span>
        <span><b>%d</b> 产物</span>
      </div>
      <div class="nums" style="margin-top:6px"><span>最近 %s</span><span>%d 个文件</span></div>
    </div>""" % (p["name"], p["name"], p["todo"], p["question"],
                 p["disc"], p["dec"], p["art"], p.get("last", "-"), p["files"]))

    return """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI 知识总控台</title>
<style>
:root{--bg:#FBF6EE;--panel:#FFFDF8;--ink:#4A4039;--muted:#9C8E7E;--line:#EADFCB;
--primary:#C08357;--primary-d:#A86B43;--radius:14px;--shadow:0 6px 20px rgba(120,90,60,.08)}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;line-height:1.6}
.wrap{max-width:960px;margin:0 auto;padding:28px 20px}
h1{margin:0 0 4px;font-size:22px}
.sub{color:var(--muted);font-size:13px;margin-bottom:20px}
input{width:100%;padding:11px 14px;border:1px solid var(--line);border-radius:10px;font-size:15px;background:#fff;font-family:inherit}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px;margin-top:20px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);padding:16px;box-shadow:var(--shadow);cursor:pointer;transition:.15s}
.card:hover{border-color:var(--primary)}
.card h3{margin:0 0 8px;font-size:16px;color:var(--primary-d)}
.nums{display:flex;flex-wrap:wrap;gap:10px;font-size:12px;color:var(--muted)}
.nums b{color:var(--primary-d)}
#res{margin-top:18px}
.hit{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:11px 13px;margin-bottom:8px;cursor:pointer;font-size:14px}
.hit:hover{border-color:var(--primary)}
.hit .meta{color:var(--muted);font-size:12px}
</style></head><body><div class="wrap">
<h1>AI 知识总控台</h1>
<div class="sub">共 __NPROJ__ 个项目 · 构建于 __BUILT__ · 内容已预建索引，搜索秒开</div>
<input id="q" placeholder="🔍 搜索全部知识库内容…（输入即搜）" oninput="doSearch(this.value)">
<div class="grid">__CARDS__</div>
<div id="res"></div>
</div>
<script>
let IDX=null,NAV=null;
async function boot(){
  IDX=(await (await fetch('search-index.json')).json());
  NAV=(await (await fetch('nav.json')).json());
}
const norm=s=>s.toLowerCase();
function doSearch(q){
  q=norm(q.trim());const box=document.getElementById('res');
  if(!IDX){boot().then(()=>doSearch(document.getElementById('q').value));return;}
  if(!q){box.innerHTML='';return;}
  const hits=IDX.rows.filter(r=>norm(r.t).includes(q)||norm(r.p).includes(q)||norm(r.rel).includes(q)).slice(0,60);
  box.innerHTML=hits.length?hits.map((h,i)=>'<div class="hit" onclick="openHit('+i+')">'+
    '<div>'+h.p+' · '+h.rel+' '+(h.big?'<span class="meta">(大文件-仅索引摘要)</span>':'')+'</div>'+
    '<div class="meta">'+h.t.slice(0,120)+'…</div></div>').join(''):'<div class="sub">没找到匹配内容</div>';
  window._hits=hits;
}
function openHit(i){const h=window._hits[i];
  location.href='view.html?p='+encodeURIComponent(h.p)+'&r='+encodeURIComponent(h.rel);}
boot();
</script></body></html>""".replace("__NPROJ__", str(len(nav))).replace("__BUILT__", built_at).replace("__CARDS__", "".join(cards))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(KB, "_dashboard"))
    a = ap.parse_args()
    build(a.out)