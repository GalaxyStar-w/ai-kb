#!/usr/bin/env bash
# deploy_dashboard.sh —— 构建「加密」看板并部署到 Cloudflare Pages
#
# 用法：
#   bash deploy_dashboard.sh                    构建 + 部署到 ~/.ai-kb/kb_project 指定的项目
#   bash deploy_dashboard.sh --rotate           新建一个随机名的新项目、部署加密站并切换过去（不删旧项目）
#   bash deploy_dashboard.sh --status           只读：显示当前/旧项目名与部署数量
#   KB_CONFIRM=1 bash deploy_dashboard.sh --purge-old       删除 --rotate 留下的旧项目（含其全部历史部署）
#   KB_CONFIRM=1 bash deploy_dashboard.sh --purge-history   只保留当前项目的最新一次部署，删除更早的历史部署
#
# 为什么需要 --rotate / --purge：Cloudflare Pages 会保留【所有历史部署】，每个都有独立网址。
# 如果以前部署过明文版本，光部署新版并不会让旧版消失。迁移到加密版后应轮换网址并清掉旧项目。
#
# 凭证：环境变量 CLOUDFLARE_API_TOKEN，或文件 ~/.ai-kb/cf_token（权限 600，不进仓库）。
# 绝不在脚本里写死 token，也不打印 token。
# 安全闸：只部署通过校验的加密产物（有 vault/params.json，且不含明文 search-index.json / content/ / 明文标记）。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AIKB="$HOME/.ai-kb"
OUT="$AIKB/dashboard_out"
BRANCH="main"
MODE="deploy"
case "${1:-}" in
  "") ;;
  --rotate) MODE="rotate";;
  --status) MODE="status";;
  --purge-old) MODE="purge-old";;
  --purge-history) MODE="purge-history";;
  -h|--help) sed -n '2,17p' "$0"; exit 0;;
  *) echo "未知参数：$1（用 --help 看用法）"; exit 1;;
esac

die() { echo "❌ $1" >&2; exit 1; }

# ---------- 凭证 ----------
if [[ -z "${CLOUDFLARE_API_TOKEN:-}" ]]; then
  TOKFILE="$AIKB/cf_token"
  [[ -f "$TOKFILE" ]] || die "未找到 Cloudflare API Token：请设置环境变量 CLOUDFLARE_API_TOKEN，或把它写入 $TOKFILE（chmod 600）"
  perm="$(stat -f '%Lp' "$TOKFILE" 2>/dev/null || stat -c '%a' "$TOKFILE" 2>/dev/null || echo 600)"
  [[ "$perm" == "600" || "$perm" == "400" ]] || echo "⚠ $TOKFILE 权限为 $perm，建议 chmod 600"
  CLOUDFLARE_API_TOKEN="$(tr -d '[:space:]' < "$TOKFILE")"
fi
export CLOUDFLARE_API_TOKEN

api() {  # api METHOD PATH  → 输出 JSON（token 只经 header 传，不落盘不打印）
  curl -s --max-time 30 -X "$1" "https://api.cloudflare.com/client/v4$2" -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN"
}
jget() { python3 -c 'import json,sys; d=json.load(sys.stdin); print(eval(sys.argv[1], {"d": d}))' "$1" 2>/dev/null || true; }

ACCOUNT="$(api GET /accounts | jget 'd["result"][0]["id"] if d.get("success") else ""')"
[[ -n "$ACCOUNT" ]] || die "无法获取 Cloudflare Account ID，请检查 token 是否有效、是否有 Account Settings:Read 权限"
export CLOUDFLARE_ACCOUNT_ID="$ACCOUNT"

CUR="$(cat "$AIKB/kb_project" 2>/dev/null || true)"
OLD_FILE="$AIKB/kb_project.old"

# ---------- wrangler ----------
find_wrangler() {
  if command -v wrangler >/dev/null 2>&1; then echo "wrangler"; return; fi
  local w="$HOME/.workbuddy/binaries/node/workspace/node_modules/.bin/wrangler"
  if [[ -x "$w" ]]; then echo "$w"; return; fi
  if command -v npx >/dev/null 2>&1; then echo "npx --yes wrangler"; return; fi
  echo ""
}

list_deploys() {  # list_deploys 项目名 → 每行一个 部署ID（按 API 返回顺序，最新在前）
  api GET "/accounts/$ACCOUNT/pages/projects/$1/deployments?per_page=50" | jget '"\n".join(x["id"] for x in d.get("result", []))'
}

# ---------- 只读状态 ----------
if [[ "$MODE" == "status" ]]; then
  echo "当前项目：${CUR:-（未设置）}"
  if [[ -f "$OLD_FILE" ]]; then echo "待清理的旧项目："; sed 's/^/  - /' "$OLD_FILE"; else echo "待清理的旧项目：无"; fi
  if [[ -n "$CUR" ]]; then n="$(list_deploys "$CUR" | grep -c . || true)"; echo "当前项目历史部署数：$n（每个都有独立网址；若含明文旧版，请 --purge-history 或 --rotate）"; fi
  exit 0
fi

# ---------- 清理（破坏性，必须明确确认） ----------
if [[ "$MODE" == "purge-old" || "$MODE" == "purge-history" ]]; then
  [[ "${KB_CONFIRM:-}" == "1" ]] || die "这是删除操作（删除的是 Cloudflare 上的旧站点/历史部署，不是知识库内容）。确认要执行请加 KB_CONFIRM=1"
  if [[ "$MODE" == "purge-history" ]]; then
    [[ -n "$CUR" ]] || die "未设置当前项目（~/.ai-kb/kb_project）"
    echo "将保留 $CUR 的最新部署，删除更早的历史部署…"
    first=1; deleted=0
    while read -r id; do
      [[ -n "$id" ]] || continue
      if [[ $first -eq 1 ]]; then first=0; echo "  保留最新：$id"; continue; fi
      res="$(api DELETE "/accounts/$ACCOUNT/pages/projects/$CUR/deployments/$id?force=true" | jget '"ok" if d.get("success") else "失败:"+str(d.get("errors"))')"
      echo "  删除 $id → $res"; deleted=$((deleted+1))
    done < <(list_deploys "$CUR")
    echo "✅ 完成，删除 $deleted 个历史部署"
  else
    [[ -f "$OLD_FILE" ]] || die "没有待清理的旧项目（$OLD_FILE 不存在）。先用 --rotate 切换到新项目。"
    [[ -n "$CUR" ]] || die "未设置当前项目，拒绝清理（避免误删唯一站点）"
    purged=0
    while read -r name; do
      [[ -n "$name" ]] || continue
      [[ "$name" != "$CUR" ]] || { echo "⚠ 跳过 $name：它就是当前项目"; continue; }
      purged=$((purged+1))
      echo "清理旧项目：$name"
      while read -r id; do
        [[ -n "$id" ]] || continue
        api DELETE "/accounts/$ACCOUNT/pages/projects/$name/deployments/$id?force=true" >/dev/null
      done < <(list_deploys "$name")
      res="$(api DELETE "/accounts/$ACCOUNT/pages/projects/$name" | jget '"ok" if d.get("success") else "失败:"+str(d.get("errors"))')"
      echo "  删除项目 → $res"
    done < "$OLD_FILE"
    mv "$OLD_FILE" "$OLD_FILE.done.$(date +%Y%m%d%H%M%S)"
    if [[ $purged -gt 0 ]]; then echo "✅ 已清理 $purged 个旧项目（旧网址已失效）"; else echo "ℹ 没有需要清理的旧项目"; fi
  fi
  exit 0
fi

# ---------- 构建加密产物 + 安全闸 ----------
[[ "$MODE" == "rotate" || -n "$CUR" ]] || die "未设置项目名（~/.ai-kb/kb_project）。首次请用 --rotate 创建随机名项目。"
echo "📦 构建加密看板..."
python3 "$HERE/build_dashboard.py"
[[ -f "$OUT/vault/params.json" ]] || die "产物里没有 vault/params.json，拒绝部署"
for leak in search-index.json nav.json content PLAINTEXT-DO-NOT-DEPLOY; do
  [[ ! -e "$OUT/$leak" ]] || die "产物里出现明文文件 $leak，拒绝部署"
done

WRANGLER="$(find_wrangler)"
[[ -n "$WRANGLER" ]] || die "未找到 wrangler 或 npx。请安装 Node.js 后执行：npm install -g wrangler"

# ---------- 轮换：新建随机名项目 ----------
if [[ "$MODE" == "rotate" ]]; then
  NEW="kb$(python3 -c 'import secrets,string;print("".join(secrets.choice(string.ascii_lowercase+string.digits) for _ in range(8)))')"
  echo "🔄 新建项目 $NEW …"
  $WRANGLER pages project create "$NEW" --production-branch="$BRANCH" 2>&1 | tail -3
  echo "🚀 部署加密站到 $NEW …"
  $WRANGLER pages deploy "$OUT" --project-name="$NEW" --branch="$BRANCH" --commit-dirty=true 2>&1 | tail -4
  mkdir -p "$AIKB"
  [[ -z "$CUR" ]] || echo "$CUR" >> "$OLD_FILE"
  printf '%s\n' "$NEW" > "$AIKB/kb_project"
  echo "✅ 已切换：https://$NEW.pages.dev"
  [[ -z "$CUR" ]] || echo "⚠ 旧项目 $CUR 仍在线（可能是明文旧版）。确认新站可用后执行：KB_CONFIRM=1 bash deploy_dashboard.sh --purge-old"
  exit 0
fi

# ---------- 普通部署 ----------
[[ -n "$CUR" ]] || die "未设置项目名（~/.ai-kb/kb_project）。首次请用 --rotate 创建随机名项目。"
echo "🚀 部署加密站到 $CUR …"
$WRANGLER pages deploy "$OUT" --project-name="$CUR" --branch="$BRANCH" --commit-dirty=true 2>&1 | tail -5
echo "✅ 完成：https://$CUR.pages.dev"
echo "ℹ 若该项目以前部署过明文版本，历史部署仍可通过各自网址访问：建议 --rotate，或 KB_CONFIRM=1 ... --purge-history"
