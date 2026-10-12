#!/usr/bin/env bash
# 一键安装 ai-kb：工具 + 知识库骨架 + hook 配置 + 自测
#
# 用法:
#   ./bootstrap.sh                       # 安装（知识库默认 ~/ai-knowledge-base）
#   ./bootstrap.sh --kb <路径># 指定知识库放哪
#   ./bootstrap.sh --remote <git 地址>   # 用已有的远程仓库（可跳过建库）
#   ./bootstrap.sh --check               # 只体检，什么都不改
#   ./bootstrap.sh --no-hook             # 不配置 hook（无hook 的 agent 用）
#   ./bootstrap.sh --sync-tool           # 已有知识库时，把最新工具文件同步进 <KB>/_tool/（被覆盖的旧文件先备份）
#   ./bootstrap.sh --dry-run             # 演练：显示会改哪些配置，不写任何文件
#   一行安装： curl -fsSL https://raw.githubusercontent.com/GalaxyStar-w/ai-kb/main/bootstrap.sh | bash
#   ./bootstrap.sh --help
#
# 幂等：重复跑安全，不覆盖已有配置。
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
KB="${AI_KB_DIR:-$HOME/ai-knowledge-base}"
TOOL_URL="${AI_KB_TOOL_URL:-https://github.com/GalaxyStar-w/ai-kb.git}"
REMOTE=""
CHECK_ONLY=0
NO_HOOK=0
SYNC_TOOL=0
DRY_RUN=0
ORIG_ARGS=("$@")

while [ $# -gt 0 ]; do case "$1" in
  --kb)      KB="$2"; shift 2;;
  --remote)  REMOTE="$2"; shift 2;;
  --check)   CHECK_ONLY=1; shift;;
  --no-hook) NO_HOOK=1; shift;;
  --sync-tool) SYNC_TOOL=1; shift;;
  --dry-run) DRY_RUN=1; shift;;
  -h|--help) sed -n '2,16p' "$0"; exit 0;;
  *) printf "未知参数: %s（用 --help 看用法）\n" "$1"; exit 1;;
esac; done

ok()   { printf "  \033[32m✔\033[0m %s\n" "$1"; }
warn() { printf "  \033[33m!\033[0m %s\n" "$1"; }
bad()  { printf "  \033[31m✘\033[0m %s\n" "$1"; }
info() { printf "  \033[36m·\033[0m %s\n" "$1"; }
step() { printf "\n\033[1m▸ %s\033[0m\n" "$1"; }
die()  { bad "$1"; exit 1; }

# 单文件运行（如 curl | bash）：仓库文件不在身边时，先克隆工具仓库，再从那里重新执行
if [ ! -f "$HERE/universal/kb.py" ]; then
  command -v git >/dev/null 2>&1 || die "缺 git"
  REPO="$HOME/.ai-kb/repo"
  mkdir -p "$HOME/.ai-kb"
  if [ -d "$REPO/.git" ]; then git -C "$REPO" pull -q --ff-only 2>/dev/null || true
  else git clone -q "$TOOL_URL" "$REPO" || die "克隆工具仓库失败：$TOOL_URL"; fi
  exec bash "$REPO/bootstrap.sh" ${ORIG_ARGS[@]+"${ORIG_ARGS[@]}"}
fi

printf "\n\033[1m ai-kb 安装程序\033[0m\n知识库位置: %s\n" "$KB"

# Windows 原生环境不支持（需要 WSL / Git Bash + POSIX 工具链）
case "$(uname -s 2>/dev/null || echo unknown)" in
  MINGW*|MSYS*|CYGWIN*)
    printf "\n\033[31m✘ 检测到 Windows 环境\033[0m\n"
    printf "  本工具需要 POSIX 环境（bash + python3 + git）。Windows 上请用：\n"
    printf "    · WSL 2（推荐）：wsl --install -d Ubuntu，然后在里面跑本脚本\n"
    printf "    · Git Bash：安装后从 Git Bash 里运行 bash ./bootstrap.sh\n"
    printf "  在原生 cmd / PowerShell 里无法运行。\n"
    exit 1;;
esac


# 克隆远程：地址写成 https://用户名@github.com/... 且 gh 已登录该账号时，固定用该账号（不受 gh 活动账号影响）
clone_remote() {
  local url="$1" dest="$2" user tok
  user="$(printf '%s' "$url" | sed -n 's#^https://\([^/@:]*\)@github\.com/.*#\1#p')"
  if [ -n "$user" ] && command -v gh >/dev/null 2>&1; then
    tok="$(gh auth token --hostname github.com --user "$user" 2>/dev/null || true)"
    if [ -n "$tok" ]; then
      KB_GH_USER="$user" KB_GH_TOKEN="$tok" git -c credential.helper= \
        -c 'credential.helper=!f() { echo "username=$KB_GH_USER"; echo "password=$KB_GH_TOKEN"; }; f' clone "$url" "$dest"
      return $?
    fi
  fi
  git clone "$url" "$dest"
}

# 把工具文件完整放进 <KB>/_tool/（换机器时从这里恢复；看板构建脚本也假定在这里）
# 已存在且内容不同的文件，先备份到 <KB>/_meta/tool-backup/<时间戳>/ 再覆盖（知识库本身也是 git 仓库，另有历史）
TOOL_ITEMS="universal claude-code skill _dashboard_template AGENT-SETUP.md AI-START-HERE.md bootstrap.sh build_dashboard.py vault_encrypt.mjs deploy_dashboard.sh extract_sessions.py distill_sessions.py LICENSE README.md CHANGELOG.md"
sync_tool() {
  local dest="$KB/_tool" ts bak n=0 item src f rel
  ts="$(date +%Y%m%d%H%M%S)"; bak="$KB/_meta/tool-backup/$ts"
  mkdir -p "$dest"
  for item in $TOOL_ITEMS; do
    src="$HERE/$item"
    [ -e "$src" ] || continue
    if [ -d "$src" ]; then
      while IFS= read -r f; do
        rel="${f#"$HERE"/}"
        if [ -f "$KB/_tool/$rel" ] && ! cmp -s "$f" "$KB/_tool/$rel"; then
          mkdir -p "$bak/$(dirname "$rel")"; cp "$KB/_tool/$rel" "$bak/$rel"; n=$((n+1))
        fi
        mkdir -p "$dest/$(dirname "$rel")"; cp "$f" "$dest/$rel"
      done < <(find "$src" -type f ! -name '.DS_Store')
    else
      if [ -f "$dest/$item" ] && ! cmp -s "$src" "$dest/$item"; then
        mkdir -p "$bak"; cp "$dest/$item" "$bak/$item"; n=$((n+1))
      fi
      cp "$src" "$dest/$item"
    fi
  done
  ok "工具已完整放入 _tool/（含看板构建/部署脚本，换机器时从这里恢复）"
  [ "$n" -gt 0 ] && info "有 $n 个已存在且不同的文件被更新，旧版已备份到 $bak"
  return 0
}

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

# ═══════════════ --dry-run 模式：只预览，不写任何文件 ═══════════════
if [ "$DRY_RUN" = "1" ]; then
  step "演练（--dry-run）：以下是将要做的 hook 配置改动，不会写任何文件"
  AI_KB_DIR="$KB" bash "$HERE/universal/install.sh" --dry-run 2>&1 | grep -E "dry-run|✘|已是最新|没有成功|未识别" | sed 's/^/  /'
  printf "\n（--dry-run 未做任何改动）\n"
  exit 0
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
step "1/4 准备知识库"
if [ -d "$KB/projects" ]; then
  ok "已存在，跳过创建"
  if [ -n "$REMOTE" ] && [ -d "$KB/.git" ]; then
    git -C "$KB" remote get-url origin >/dev/null 2>&1 \
      || git -C "$KB" remote add origin "$REMOTE"
  fi
elif [ -n "$REMOTE" ]; then
  info "从远程 clone…"
  if clone_remote "$REMOTE" "$KB" 2>/dev/null; then
    ok "clone 成功"
  else
    bad "clone 失败 —— 私有仓库请先登录：gh auth login"
    exit 1
  fi
else
  mkdir -p "$KB"
  AI_KB_DIR="$KB" python3 "$HERE/universal/kb.py" init >/dev/null 2>&1
  ok "已创建空知识库骨架"

  # 关键：把「AI 怎么用」的两份文件放进知识库，
  # 否则用户那句「按 AI-START-HERE.md 走」指不到文件，AI 就无从读起。
  [ -f "$HERE/AI-START-HERE.md" ] && cp "$HERE/AI-START-HERE.md" "$KB/" && ok "已放入 AI-START-HERE.md（agent 的使用入口）"
  sync_tool

  info "下一步：创建【私有】远程仓库并关联"
  printf "\n     cd %s\n     git init\n     git remote add origin <你的私有仓库地址>\n     git add -A && git commit -m init && git push\n\n" "$KB"
  warn "注意：必须用【私有】仓库，工具会拒绝向公开仓库推送"
fi

# 已有知识库：按需把最新工具同步进 _tool/（默认不动，避免覆盖你在 _tool 里的本地修改）
if [ "$SYNC_TOOL" = "1" ] && [ -d "$KB/projects" ]; then sync_tool; fi
# 已有知识库时也确保 AI-START-HERE.md 在（补装场景）
if [ -d "$KB" ]; then
  [ -f "$HERE/AI-START-HERE.md" ] && [ ! -f "$KB/AI-START-HERE.md" ] && \
    cp "$HERE/AI-START-HERE.md" "$KB/" && ok "补装 AI-START-HERE.md"
fi

# ═══════════════ 2. 安装工具 ═══════════════
step "2/4 安装工具"
if [ -f "$HERE/universal/kb.py" ]; then
  mkdir -p "$HOME/.ai-kb"
  cp "$HERE/universal/kb.py" "$HERE/universal/rules.md" "$HOME/.ai-kb/" 2>/dev/null
  [ -f "$HERE/universal/selftest.sh" ] && cp "$HERE/universal/selftest.sh" "$HOME/.ai-kb/"
  ok "已安装到 ~/.ai-kb"
else
  die "找不到 universal/kb.py —— 确认你在 ai-kb 仓库根目录下跑的"
fi

# ═══════════════ 3. 配置 hook ═══════════════
step "3/4 安装 skill（让 agent 自动发现）"
if [ -f "$HERE/skill/SKILL.md" ]; then
  INSTALLED_SKILLS=""
  for agent in workbuddy claude codebuddy; do
    base="$HOME/.${agent}/skills"
    # 只装到已存在的 agent 技能目录（说明该 agent 在用）
    if [ -d "$base" ]; then
      mkdir -p "$base/ai-kb"
      if cp "$HERE/skill/SKILL.md" "$base/ai-kb/SKILL.md" 2>/dev/null; then
        INSTALLED_SKILLS="$INSTALLED_SKILLS $agent"
      fi
    fi
  done
  if [ -n "$INSTALLED_SKILLS" ]; then
    ok "已安装 skill 到：$INSTALLED_SKILLS"
    info "→ agent 会自动读到它，之后你只说「装一下 ai-kb」它就知道怎么做"
  else
    info "未检测到 agent 技能目录（~/.workbuddy/skills 等），跳过 skill 安装"
    info "  想手动装：把 skill/SKILL.md 放到 ~/.workbuddy/skills/ai-kb/ 即可"
  fi
else
  info "仓库里没有 skill/SKILL.md，跳过"
fi

step "4/4 配置 hook"
if [ "$NO_HOOK" = "1" ]; then
  info "已跳过（--no-hook）。自动记录会降级，靠全局指令驱动。"
  info "之后想补：./universal/install.sh"
else
  AI_KB_DIR="$KB" bash "$HERE/universal/install.sh" $([ "$DRY_RUN" = "1" ] && echo --dry-run) 2>&1 | grep -E "已写入|已备份|已是最新|dry-run|✘|跳过|未识别|没有成功|重启|下一步|⚠" | sed 's/^/  /'
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