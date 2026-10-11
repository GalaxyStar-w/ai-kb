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
remote=""; targets=(); AGENT=""; NO_HOOK=0
while [ $# -gt 0 ]; do case "$1" in
  --remote) remote="$2"; shift 2;;
  --target) targets+=("$2"); shift 2;;
  --agent) AGENT="$2"; shift 2;;
  --no-hook) NO_HOOK=1; shift;;
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
mkdir -p "$DEST"; cp "$HERE/kb.py" "$HERE/rules.md" "$DEST/"; echo "✔ 脚本已安装到 $DEST"
if [ -n "$remote" ] && [ ! -d "$KB/.git" ]; then git clone "$remote" "$KB" 2>/dev/null || { mkdir -p "$KB"; git -C "$KB" init -q; git -C "$KB" remote add origin "$remote"; }; fi
AI_KB_DIR="$KB" python3 "$DEST/kb.py" init
SNIP="$(sed "s#__KB__#$KB#g" "$HERE/AGENT-INSTRUCTIONS.md")"   # 片段里写入真实知识库路径，避免 agent 误建默认目录
if [ -n "$remote" ] && [ -d "$KB/.git" ] && ! git -C "$KB" remote | grep -q origin; then git -C "$KB" remote add origin "$remote"; fi
echo "✔ 知识库目录就绪：$KB"

# ---- 配置 hook（这是自动记录的关键）----
# 背景：hook 才能做到「会话开始自动注入规则 / 每轮提醒 / 压缩前保护 / 回合结束自动提交」，
# 没有 hook 只能靠指令让 agent 自己记得跑，漏记概率明显更高。
install_hooks() {
  local cfg="$1" plat="$2"
  [ "$NO_HOOK" = "1" ] && { echo "• 已跳过 hook 配置（--no-hook）"; return; }

  mkdir -p "$(dirname "$cfg")"
  [ -f "$cfg" ] || printf '%s\n' '{}' > "$cfg"

  python3 - "$cfg" "$KB" "$DEST" <<'PYEOF2'
import json, sys, os
cfg, kb, dest = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    d = json.load(open(cfg, encoding="utf-8"))
    if not isinstance(d, dict): d = {}
except Exception:
    d = {}
hooks = d.get("hooks") or {}
def cmd(mode, timeout):
    return {
        "type": "command",
        "command": f'AI_KB_DIR="{kb}" python3 "{dest}/kb.py" {mode}',
        "timeout": timeout,
    }
# 先清掉本工具此前写入的条目（识别标志是命令里含 "kb.py <mode>"），
# 再按当前 KB/DEST 路径重建。这样重复安装不会叠加，且换路径后不会留旧指向。
def is_ours(grp):
    return any("kb.py" in str(h) for h in (grp or {}).get("hooks", []))

SPEC = (("SessionStart", "sessionstart", 45, "startup"),
        ("UserPromptSubmit", "prompt", 10, "*"),
        ("PreCompact", "precompact", 15, "*"),
        ("Stop", "stop", 30, "*"))
for ev, mode, t, matcher in SPEC:
    kept = [g for g in (hooks.get(ev) or []) if not is_ours(g)]
    kept.append({"matcher": matcher, "hooks": [cmd(mode, t)]})
    hooks[ev] = kept
d["hooks"] = hooks
json.dump(d, open(cfg, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"  · SessionStart / UserPromptSubmit / PreCompact / Stop 已写入 {cfg}")
PYEOF2
  echo "⚠ hook 需**完全重启 agent**（Claude Code: 重新启动；WorkBuddy: Cmd+Q 彻底退出而非关窗口）才会生效"
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
      install_hooks "$cfg" "$plat"
      HOOKED="$HOOKED $plat"
    fi
  done
fi

if [ -z "$HOOKED" ]; then
  echo "• 未识别 agent 平台，跳过 hook 配置。"
  echo "  若你的 agent 支持 hooks（Claude Code / WorkBuddy / CodeBuddy 均支持），"
  echo "  可手动执行：--agent workbuddy（或 claude-code / codebuddy）重跑本脚本。"
  echo "  完整 hook JSON 见 README 第 5.3 节。"
fi
for f in "${targets[@]}"; do
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
