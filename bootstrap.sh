#!/usr/bin/env bash
# 一键安装 ai-kb：工具 + 知识库骨架 + hook 配置 + 自测
#
# 用法:
#   ./bootstrap.sh                       # 安装（知识库默认 ~/ai-knowledge-base）
#   ./bootstrap.sh --kb <路径># 指定知识库放哪
#   ./bootstrap.sh --remote <git 地址>   # 用已有的远程仓库（可跳过建库）
#   ./bootstrap.sh --check               # 只体检，什么都不改
#   ./bootstrap.sh --no-hook             # 不配置 hook（无hook 的 agent 用）
#   ./bootstrap.sh --help
#
# 幂等：重复跑安全，不覆盖已有配置。
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
KB="${AI_KB_DIR:-$HOME/ai-knowledge-base}"
TOOL_URL="https://github.com/GalaxyStar-w/ai-kb.git"
REMOTE=""
CHECK_ONLY=0
NO_HOOK=0

while [ $# -gt 0 ]; do case "$1" in
  --kb)      KB="$2"; shift 2;;
  --remote)  REMOTE="$2"; shift 2;;
  --check)   CHECK_ONLY=1; shift;;
  --no-hook) NO_HOOK=1; shift;;
  -h|--help) sed -n '2,12p' "$0"; exit 0;;
  *) printf "未知参数: %s（用 --help 看用法）\n" "$1"; exit 1;;
esac; done

ok()   { printf "  \033[32m✔\033[0m %s\n" "$1"; }
warn() { printf "  \033[33m!\033[0m %s\n" "$1"; }
bad()  { printf "  \033[31m✘\033[0m %s\n" "$1"; }
info() { printf "  \033[36m·\033[0m %s\n" "$1"; }
step() { printf "\n\033[1m▸ %s\033[0m\n" "$1"; }
die()  { bad "$1"; exit 1; }

printf "\n\033[1m ai-kb 安装程序\033[0m\n知识库位置: %s\n" "$KB"

# ═══════════════ 0. 依赖体检 ═══════════════
step "检查依赖"
command -v python3 >/dev/null || die "缺 python3（macOS 自带，Linux 请装 python3）"
ok "python3 $(python3 --version 2>&1 | cut -d' ' -f2)"
command -v git >/dev/null || die "缺 git"
ok "git $(git --version | cut -d' ' -f3)"
if command -v gh >/dev/null && gh auth status >/dev/null 2>&1; then
  ok "gh CLI 已登录"
elif command -v gh >/dev/null; then
  info "gh 已安装但未登录 —— 若用私有远程仓库，需先 gh auth login"
fi

# ═══════════════ --check 模式 ═══════════════
if [ "$CHECK_ONLY" = "1" ]; then
  step "当前状态"
  [ -d "$KB/projects" ] && ok "知识库已就位（$(ls "$KB/projects" 2>/dev/null | wc -l | tr -d ' ') 个项目）" || info "知识库未就位"
  [ -f "$HOME/.ai-kb/kb.py" ] && ok "工具已安装（~/.ai-kb）" || info "工具未安装"
  for cfg in "$HOME/.workbuddy/settings.json" "$HOME/.codebuddy/settings.json" "$HOME/.claude/settings.json"; do
    [ -f "$cfg" ] || continue
    python3 - "$cfg" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
    ev = list((d.get("hooks") or {}).keys())
    ours = any("kb.py" in str(h)
               for g in (d.get("hooks") or {}).values()
               for grp in g for h in grp.get("hooks", []))
    print(f"  {'✔' if ours else '·'} {sys.argv[1].split('/')[-2]}: hook {ev or '未配置'}"
          f"{'' if ours else '（缺ai-kb hook）'}")
except Exception:
    pass
PY
  done
  if [ -f "$HOME/.ai-kb/kb.py" ] && [ -d "$KB/projects" ]; then
    echo
    AI_KB_DIR="$KB" python3 "$HOME/.ai-kb/kb.py" doctor 2>/dev/null | tail -3 | sed 's/^/  /'
  fi
  printf "\n（--check 未做任何改动）\n"
  exit 0
fi

# ═══════════════ 1. 知识库 ═══════════════
step "1/3 准备知识库"
if [ -d "$KB/projects" ]; then
  ok "已存在，跳过创建"
  if [ -n "$REMOTE" ] && [ -d "$KB/.git" ]; then
    git -C "$KB" remote get-url origin >/dev/null 2>&1 \
      || git -C "$KB" remote add origin "$REMOTE"
  fi
elif [ -n "$REMOTE" ]; then
  info "从远程 clone…"
  if git clone "$REMOTE" "$KB" 2>/dev/null; then
    ok "clone 成功"
  else
    bad "clone 失败 —— 私有仓库请先登录：gh auth login"
    exit 1
  fi
else
  mkdir -p "$KB"
  AI_KB_DIR="$KB" python3 "$HERE/universal/kb.py" init >/dev/null 2>&1
  ok "已创建空知识库骨架"
  info "下一步请创建一个【私有】仓库并关联："
  printf "\n     cd %s\n     git init && git remote add origin <你的私有仓库地址>\n     git add -A && git commit -m init && git push\n\n" "$KB"
fi

# ═══════════════ 2. 安装工具 ═══════════════
step "2/3 安装工具"
if [ -f "$HERE/universal/kb.py" ]; then
  mkdir -p "$HOME/.ai-kb"
  cp "$HERE/universal/kb.py" "$HERE/universal/rules.md" "$HOME/.ai-kb/" 2>/dev/null
  [ -f "$HERE/universal/selftest.sh" ] && cp "$HERE/universal/selftest.sh" "$HOME/.ai-kb/"
  ok "已安装到 ~/.ai-kb"
else
  die "找不到 universal/kb.py —— 确认你在 ai-kb 仓库根目录下跑的"
fi

# ═══════════════ 3. 配置 hook ═══════════════
step "3/3 配置 hook"
if [ "$NO_HOOK" = "1" ]; then
  info "已跳过（--no-hook）。自动记录会降级，靠全局指令驱动。"
  info "之后想补：./universal/install.sh"
else
  AI_KB_DIR="$KB" bash "$HERE/universal/install.sh" 2>&1 | grep -E "已写入|跳过|未识别|重启|下一步|⚠" | sed 's/^/  /'
  # install.sh 只装脚本不写 hook 时（未识别平台），提示手动方式
  if ! grep -q "已写入" /dev/null 2>&1; then :; fi
fi

# ═══════════════ 验证 ═══════════════
step "验证"
AI_KB_DIR="$KB" python3 "$HOME/.ai-kb/kb.py" doctor 2>&1 | tail -4 | sed 's/^/  /'
echo
AI_KB_DIR="$KB" python3 "$HOME/.ai-kb/kb.py" audit 2>&1 | head -8 | sed 's/^/  /'

cat <<EOF

────────────────────────────────────────────────
✅ 安装完成

接下来两件事：

1️⃣  重启 agent 让 hook 生效
    WorkBuddy → Cmd+Q 彻底退出（关窗口不算，它有常驻进程）
    Claude Code → 直接重新启动
    CodeBuddy  → 重新启动终端会话

2️⃣  让 agent 知道怎么用 —— 只要说一句话：

    「按 $KB/AI-START-HERE.md 走」

    它就会知道：你是谁、知识库怎么用、有哪些硬性规则、现在该管什么。

📖 详细文档：README.md
🔧 有问题先跑：AI_KB_DIR="$KB" python3 ~/.ai-kb/kb.py doctor
────────────────────────────────────────────────
EOF