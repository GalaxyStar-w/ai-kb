#!/bin/bash
# 通用安装：脚本装到 ~/.ai-kb/，初始化知识库目录，并把指令片段追加到你指定的 agent 全局指令文件。
# 用法:
#   ./install.sh [--remote <你的私有仓库地址>] [--target <全局指令文件>]...
# 环境变量 AI_KB_DIR 指定知识库目录（默认 ~/ai-knowledge-base）。重复运行安全（幂等）。
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/.ai-kb"
# 知识库目录：AI_KB_DIR > 本脚本位于 <KB>/_tool/universal 时自动取 <KB> > 默认 ~/ai-knowledge-base
KB="${AI_KB_DIR:-}"
if [ -z "$KB" ]; then
  CAND="$(cd "$HERE/../.." && pwd)"
  if [ -d "$CAND/projects" ] && [ -d "$CAND/_meta" ]; then KB="$CAND"; echo "• 自动识别知识库目录：$KB"; else KB="$HOME/ai-knowledge-base"; fi
fi
MARK="<!-- ai-kb:begin -->"; END="<!-- ai-kb:end -->"
command -v python3 >/dev/null || { echo "需要 python3"; exit 1; }
remote=""; targets=(); AGENT=""; NO_HOOK=0; DRY_RUN=0
while [ $# -gt 0 ]; do case "$1" in
  --remote) remote="$2"; shift 2;;
  --target) targets+=("$2"); shift 2;;
  --agent) AGENT="$2"; shift 2;;
  --no-hook) NO_HOOK=1; shift;;
  --dry-run) DRY_RUN=1; shift;;
  *) echo "未知参数: $1"; exit 1;; esac; done

# ---- 探测 agent 平台（决定 hook 写到哪里）----
detect_agent() {
  if [ -n "$AGENT" ]; then echo "$AGENT"; return; fi
  # WorkBuddy 桌面版：配置目录 ~/.workbuddy（内部注入 CODEBUDDY_CONFIG_DIR 指向这里）
  if [ -f "$HOME/.workbuddy/settings.json" ]; then echo workbuddy; return; fi
  # CodeBuddy CLI：配置目录 ~/.codebuddy
  if [ -f "$HOME/.codebuddy/settings.json" ]; then echo codebuddy; return; fi
  # Claude Code
  if [ -f "$HOME/.claude/settings.json" ]; then echo claude-code; return; fi
  echo none
}
AGENT="$(detect_agent)"
AGENT_EXPLICIT=0; [ $# -gt 0 ] && case " $* " in *" --agent "*) AGENT_EXPLICIT=1;; esac
if [ "$DRY_RUN" != "1" ]; then
  mkdir -p "$DEST"; cp "$HERE/kb.py" "$HERE/rules.md" "$HERE/rules-lite.md" "$DEST/"; echo "✔ 脚本已安装到 $DEST"
  if [ -n "$remote" ] && [ ! -d "$KB/.git" ]; then git clone "$remote" "$KB" 2>/dev/null || { mkdir -p "$KB"; git -C "$KB" init -q; git -C "$KB" remote add origin "$remote"; }; fi
  AI_KB_DIR="$KB" python3 "$DEST/kb.py" init
else
  echo "• [dry-run] 不安装脚本、不初始化知识库，只预览 hook 配置会怎么改"
fi
SNIP="$(sed "s#__KB__#$KB#g" "$HERE/AGENT-INSTRUCTIONS.md")"   # 片段里写入真实知识库路径，避免 agent 误建默认目录
if [ -n "$remote" ] && [ -d "$KB/.git" ] && ! git -C "$KB" remote | grep -q origin; then git -C "$KB" remote add origin "$remote"; fi
[ "$DRY_RUN" = "1" ] || echo "✔ 知识库目录就绪：$KB"

# ---- 配置 hook（这是自动记录的关键）----
# 背景：hook 才能做到「会话开始自动注入规则 / 每轮提醒 / 压缩前保护 / 回合结束自动提交」，
# 没有 hook 只能靠指令让 agent 自己记得跑，漏记概率明显更高。
install_hooks() {
  local cfg="$1" plat="$2"
  [ "$NO_HOOK" = "1" ] && { echo "• 已跳过 hook 配置（--no-hook）"; return 1; }
  mkdir -p "$(dirname "$cfg")"
  # 安全原则（对应 AI-START-HERE 规则二：改用户已有文件前要备份）：
  #   1) 只在能严格解析 JSON 时才改；解析失败 → 跳过并保持原文件不变（旧版会用 {} 覆盖，导致原配置丢失）
  #   2) 改动前先备份为 <文件>.bak-ai-kb-<时间戳>（只新增，不删旧备份）
  #   3) 原子写入（先写临时文件再替换），中途失败不会留下半截文件
  #   4) 只增删「本工具写入的」hook 条目，用户自己的 hook、permissions 等全部原样保留
  python3 - "$cfg" "$KB" "$DEST" "$DRY_RUN" "$plat" <<'PYEOF2'
import json, sys, os, re, shutil, time, tempfile
cfg, kb, dest, dry, plat = sys.argv[1:6]
dry = (dry == "1")

def skip(why):
    print(f"  ✘ {plat}：{cfg} {why}")
    print("    为避免丢失你的原有配置，已跳过，未做任何修改。可先修好该文件后重跑，或手动按 README 配置 hook。")
    sys.exit(3)

d = {}
if os.path.exists(cfg):
    raw = open(cfg, encoding="utf-8").read()
    if raw.strip():
        try:
            d = json.loads(raw)
        except Exception as e:
            skip("不是严格 JSON（%s）" % e)
        if not isinstance(d, dict):
            skip("顶层不是 JSON 对象")
hooks = d.get("hooks", {})
if not isinstance(hooks, dict):
    skip("的 hooks 字段不是对象")

def cmd(mode, timeout):
    return {"type": "command", "command": f'AI_KB_DIR="{kb}" python3 "{dest}/kb.py" {mode}', "timeout": timeout}

OURS = re.compile(r'kb\.py"?\s+(sessionstart|prompt|precompact|stop)\b')
def is_ours(grp):
    return isinstance(grp, dict) and any(OURS.search(str(h.get("command", ""))) for h in grp.get("hooks", []) if isinstance(h, dict))

# SessionStart 不设限制（"*" = startup/resume/clear/compact 全部触发）：
# 旧版只写 startup，会话恢复/清屏/上下文压缩之后规则就不再重新注入。
SPEC = (("SessionStart", "sessionstart", 45), ("UserPromptSubmit", "prompt", 10),
        ("PreCompact", "precompact", 15), ("Stop", "stop", 30))
before = json.dumps(d, sort_keys=True)
changes = []
for ev, mode, t in SPEC:
    groups = hooks.get(ev, [])
    if not isinstance(groups, list):
        skip("的 hooks.%s 不是数组" % ev)
    kept = [g for g in groups if not is_ours(g)]
    replaced = len(groups) - len(kept)
    kept.append({"matcher": "*", "hooks": [cmd(mode, t)]})
    hooks[ev] = kept
    changes.append(f"{ev}{'（替换旧条目）' if replaced else '（新增）'}")
d["hooks"] = hooks
after = json.dumps(d, sort_keys=True)
if before == after:
    print(f"  · {plat}：{cfg} 已是最新，无需改动")
    sys.exit(0)
if dry:
    print(f"  · {plat}：[dry-run] 将写入 {cfg}：" + "、".join(changes))
    sys.exit(0)
if os.path.exists(cfg):
    bak = f"{cfg}.bak-ai-kb-{time.strftime('%Y%m%d%H%M%S')}"
    shutil.copy2(cfg, bak)
    print(f"  · 已备份原配置：{bak}")
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(cfg) or ".", prefix=".kb-settings-")
with os.fdopen(fd, "w", encoding="utf-8") as f:
    json.dump(d, f, ensure_ascii=False, indent=2); f.write("\n")
if os.path.exists(cfg):
    shutil.copymode(cfg, tmp)
os.replace(tmp, cfg)
print(f"  · {plat}：已写入 {cfg}：" + "、".join(changes))
PYEOF2
  local rc=$?
  [ $rc -eq 0 ] || return 1
  [ "$DRY_RUN" = "1" ] || echo "⚠ hook 需**完全重启 agent**（Claude Code: 重新启动；WorkBuddy: Cmd+Q 彻底退出而非关窗口）才会生效"
  return 0
}

# 给**所有已安装的平台**都配hook —— 一台机器可能同时用多个 agent
# （例如既开WorkBuddy 又用 Claude Code），它们应共用同一个知识库。
HOOKED=""
if [ "$NO_HOOK" != "1" ]; then
  for plat in claude-code workbuddy codebuddy; do
    case "$plat" in
      claude-code) cfg="$HOME/.claude/settings.json";;
      workbuddy)    cfg="$HOME/.workbuddy/settings.json";;
      codebuddy)    cfg="$HOME/.codebuddy/settings.json";;
    esac
    # 平台目录存在才配（说明该 agent 在用）；--agent 可强制指定单个平台
    # 自动探测时：给所有已安装平台都配（多agent 共用同一知识库）
    # --agent 显式指定时：只配那一个
    if [ -f "$cfg" ] && { [ "$AGENT_EXPLICIT" != "1" ] || [ "$AGENT" = "$plat" ]; }; then
      if install_hooks "$cfg" "$plat"; then HOOKED="$HOOKED $plat"; fi
    fi
  done
fi

if [ -z "$HOOKED" ]; then
  echo "• 没有成功配置任何 hook（未识别到 agent 平台，或其配置文件无法安全修改——见上方提示）。"
  echo "  若你的 agent 支持 hooks（Claude Code / WorkBuddy / CodeBuddy 均支持），"
  echo "  可手动执行：--agent workbuddy（或 claude-code / codebuddy）重跑本脚本。"
  echo "  完整 hook JSON 见 README 第 5.3 节。"
fi
for f in "${targets[@]+"${targets[@]}"}"; do
  [ "$DRY_RUN" = "1" ] && { echo "• [dry-run] 不写入 $f"; continue; }
  f="${f/#\~/$HOME}"; mkdir -p "$(dirname "$f")"; touch "$f"
  if grep -qF "$MARK" "$f"; then echo "• $f 已包含片段，跳过"
  else { echo; echo "$MARK"; echo "$SNIP"; echo "$END"; } >> "$f"; echo "✔ 已追加到 $f"; fi
done
if [ ${#targets[@]} -eq 0 ]; then echo; echo "—— 请把下面内容粘贴到你的 agent 的「全局/用户级指令」里 ——"; echo; echo "$SNIP"; fi
echo
echo "── 下一步 ──"
echo "1) 授权 agent 可写入 $KB（在项目目录之外）"
echo "2) 确认远程仓库是【私有】的（工具会自动拒绝推送向公开仓库）"
[ "$NO_HOOK" = "1" ] && echo "3) 你跳过了 hook 配置，自动记录能力会降级——需要时按 README 第 5.3 节手动加"
echo
echo "验证：AI_KB_DIR=\"$KB\" python3 \"$DEST/kb.py\" doctor"
