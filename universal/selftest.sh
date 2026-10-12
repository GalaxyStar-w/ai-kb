#!/bin/bash
# ai-kb 隔离自测：在临时知识库里跑完整机制检查，**不触碰真实知识库、不联网写入**。
# 用法: ./selftest.sh        （任何能执行 bash 的环境；需要 python3 和 git）
# 结果: 每项 ✔/✘，最后输出汇总；有失败时退出码非 0。
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"; KBPY="$HERE/kb.py"
command -v python3 >/dev/null || { echo "✘ 缺少 python3"; exit 2; }
command -v git >/dev/null || { echo "✘ 缺少 git"; exit 2; }
T="$(mktemp -d "$HOME/.ai-kb-selftest.XXXXXX")"; trap 'rm -rf "$T"' EXIT
export AI_KB_DIR="$T/kb"; unset CLAUDE_TRACKER_DIR
P="$T/proj"; mkdir -p "$P"; git -C "$P" init -q
pass=0; fail=0
ok(){ if [ "$1" = 0 ]; then echo "  ✔ $2"; pass=$((pass+1)); else echo "  ✘ $2"; fail=$((fail+1)); fi; }
hook(){ echo "{\"cwd\":\"$P\"}" | python3 "$KBPY" "$@"; }

echo "[1] 初始化与项目识别"
CTX="$(cd "$P" && python3 "$KBPY" context 2>&1)"
echo "$CTX" | grep -q "AI 知识库规则"; ok $? "context 输出包含规则"
PN="$(echo "$CTX" | sed -n 's/.*当前项目：\*\*\(.*\)\*\*（.*/\1/p' | head -1)"
[ -n "${PN}" ]; ok $? "识别出当前项目名（${PN}）"
[ "${PN}" = "_general" ] && echo "    （提示：HOME 位于系统临时目录下，项目被归入 _general，属正常，后续检查按 _general 进行）"
KP="$AI_KB_DIR/projects/${PN}"
for f in README.md todo.md questions.md log.md glossary.md artifacts/INDEX.md; do [ -f "$KP/${f}" ]; ok $? "生成 projects/${PN}/${f}"; done
hook sessionstart | python3 -c 'import sys,json;json.load(sys.stdin)["hookSpecificOutput"]["additionalContext"]' 2>/dev/null; ok $? "hook 模式 sessionstart 输出合法 JSON"

echo "[2] 写入、总页与搜索"
python3 - "$KP" <<'EOF'
import sys,os
d=sys.argv[1]
def rep(f,a,b):
    p=os.path.join(d,f); s=open(p,encoding="utf-8").read(); open(p,"w",encoding="utf-8").write(s.replace(a,b,1))
rep("todo.md","## 未完成\n","## 未完成\n- [ ] T-1 [优化|高] 自测待办 selftest-marker-todo — 来源 discussions/2026-01-01-自测.md · 2026-01-01\n")
rep("questions.md","## 未决\n","## 未决\n- Q-1 [待讨论] 自测问题 selftest-marker-q — 提出 2026-01-01 · 最近触及 2026-01-01\n")
open(os.path.join(d,"discussions","2026-01-01-自测.md"),"w",encoding="utf-8").write("# 自测讨论\n背景 selftest-marker-disc\n")
EOF
python3 "$KBPY" build >/dev/null
grep -q "| \[${PN}\]" "$AI_KB_DIR/README.md"; ok $? "根目录总页出现该项目"
grep -q "selftest-marker-todo" "$AI_KB_DIR/README.md"; ok $? "总页汇总了未完成待办"
grep -q "discussions/2026-01-01-自测.md" "$KP/README.md"; ok $? "项目首页自动区块列出了讨论纪要"
python3 "$KBPY" search selftest-marker-disc | grep -q "2026-01-01-自测.md"; ok $? "search 能搜到讨论纪要内容"

echo "[3] 密钥拦截"
# 假密钥在运行时拼出，文件里不出现字面量（否则本脚本存进知识库时会被密钥扫描误拦）
FAKE="hunter2""hunter2"; KW="pass""word"
echo "$KW = $FAKE" >> "$KP/glossary.md"
hook stop >/dev/null
[ -f "$AI_KB_DIR/_meta/SYNC_BLOCKED.md" ]; ok $? "含疑似密码的变更被拦截并写出 SYNC_BLOCKED.md"
git -C "$AI_KB_DIR" log --all -p 2>/dev/null | grep -q "$FAKE"; [ $? -ne 0 ]; ok $? "密钥没有进入 git 历史"
sed -i.bak "/$FAKE/d" "$KP/glossary.md"; rm -f "$KP/glossary.md.bak"
hook stop >/dev/null
[ ! -f "$AI_KB_DIR/_meta/SYNC_BLOCKED.md" ]; ok $? "去掉密钥后恢复提交、拦截标记消失"

echo "[4] 推送保险（不会真的推到任何地方）"
git -C "$AI_KB_DIR" remote add origin "https://github.com/ai-kb-selftest-nonexistent/none.git" 2>/dev/null
python3 "$KBPY" _push
grep -q '"ok": false' "$AI_KB_DIR/_meta/.sync-status.json"; ok $? "无法确认仓库私有时拒绝推送"
git init -q --bare "$T/remote.git"; git -C "$AI_KB_DIR" remote set-url origin "$T/remote.git"
echo '{"allow_non_github_remote": true}' > "$AI_KB_DIR/_meta/config.json"
python3 "$KBPY" _push
grep -q '"ok": true' "$AI_KB_DIR/_meta/.sync-status.json"; ok $? "允许的远程（本地裸仓库）可以推送"
git --git-dir="$T/remote.git" log --oneline 2>/dev/null | grep -q .; ok $? "远程收到了提交"

REPO="$(cd "${HERE}/.." && pwd)"

echo "[5] 安装器改 settings.json 的安全性"
H1="${T}/h1"; mkdir -p "${H1}/.claude"
printf '{\n  // 带注释的配置\n  "theme": "dark",\n}\n' > "${H1}/.claude/settings.json"; cp "${H1}/.claude/settings.json" "${T}/h1.orig"
HOME="${H1}" AI_KB_DIR="${T}/kb-h1" bash "${HERE}/install.sh" >/dev/null 2>&1
cmp -s "${T}/h1.orig" "${H1}/.claude/settings.json"; ok $? "非严格 JSON 的 settings.json 原样保留（旧版会用 {} 覆盖，导致原配置丢失）"
H2="${T}/h2"; mkdir -p "${H2}/.claude"
echo '{"theme":"dark","permissions":{"allow":["Bash(ls)"]},"hooks":{"Stop":[{"hooks":[{"type":"command","command":"echo user-hook"}]}]}}' > "${H2}/.claude/settings.json"
HOME="${H2}" AI_KB_DIR="${T}/kb-h2" bash "${HERE}/install.sh" >/dev/null 2>&1
python3 - "${H2}/.claude/settings.json" <<'EOF'
import json, sys
d = json.load(open(sys.argv[1])); h = d["hooks"]
assert d["theme"] == "dark" and d["permissions"]["allow"] == ["Bash(ls)"]
assert any("user-hook" in str(g) for g in h["Stop"]) and len(h["Stop"]) == 2
assert all(g.get("matcher") == "*" for g in h["SessionStart"])
EOF
ok $? "合法 settings.json：保留 theme/permissions/用户自己的 hook；SessionStart 不再只限 startup"
ls "${H2}/.claude" | grep -q "bak-ai-kb"; ok $? "改动前已备份原配置"
n1="$(ls "${H2}/.claude" | grep -c "bak-ai-kb")"; HOME="${H2}" AI_KB_DIR="${T}/kb-h2" bash "${HERE}/install.sh" >/dev/null 2>&1; n2="$(ls "${H2}/.claude" | grep -c "bak-ai-kb")"
[ "${n1}" = "${n2}" ]; ok $? "重复安装幂等（不叠加 hook、不新增备份）"

echo "[6] bootstrap 与 _tool 完整性"
if [ -f "${REPO}/bootstrap.sh" ]; then
  H3="${T}/h3"; mkdir -p "${H3}/.claude"; echo '{}' > "${H3}/.claude/settings.json"
  HOME="${H3}" bash "${REPO}/bootstrap.sh" --kb "${T}/kb-h3" >/dev/null 2>&1
  for f in AGENT-SETUP.md build_dashboard.py vault_encrypt.mjs deploy_dashboard.sh universal/kb.py universal/selftest.sh claude-code/ai-kb/hooks/hooks.json _dashboard_template/shell.html; do
    [ -e "${T}/kb-h3/_tool/${f}" ]; ok $? "_tool/${f} 已放入知识库"
  done
  H4="${T}/h4"; mkdir -p "${H4}/.claude"; echo '{}' > "${H4}/.claude/settings.json"
  HOME="${H4}" bash "${REPO}/bootstrap.sh" --kb "${T}/kb-h4" --dry-run >/dev/null 2>&1
  [ ! -e "${H4}/.ai-kb" ] && [ ! -e "${T}/kb-h4" ]; ok $? "bootstrap --dry-run 不写任何文件"
  bash -n "${REPO}/bootstrap.sh" && bash -n "${HERE}/install.sh"; ok $? "bootstrap.sh / install.sh 语法正确"
else echo "  - 跳过（找不到 bootstrap.sh：不在完整工具目录中运行）"; fi

echo "[6.5] 克隆后丢失的空目录会被补全"
rmdir "${KP}/decisions" 2>/dev/null || rm -rf "${KP}/decisions"; rm -f "${KP}/discussions/.gitkeep" 2>/dev/null
[ ! -d "${KP}/decisions" ]; ok $? "（准备）模拟 git 克隆后空目录丢失"
python3 "${KBPY}" build >/dev/null 2>&1
[ -d "${KP}/decisions" ] && [ -d "${KP}/discussions" ]; ok $? "build 补全了缺失的 decisions/ discussions/（只新增，不覆盖已有文件）"
grep -q "selftest-marker-todo" "${KP}/todo.md"; ok $? "补全时没有覆盖已有内容（todo.md 原有条目仍在）"

echo "[6.6] 维护命令不会把所在目录登记成项目"
O="${T}/otherproj"; mkdir -p "${O}"; git -C "${O}" init -q
( cd "${O}" && python3 "${KBPY}" build >/dev/null 2>&1; python3 "${KBPY}" status >/dev/null 2>&1; python3 "${KBPY}" init >/dev/null 2>&1 )
[ ! -d "${AI_KB_DIR}/projects/otherproj" ]; ok $? "build/status/init 不会在知识库里创建该目录对应的项目（旧版会）"
! grep -q "otherproj" "${AI_KB_DIR}/_meta/map.json" 2>/dev/null; ok $? "map.json 里没有被误登记的目录"
( cd "${O}" && echo "{\"cwd\":\"${O}\"}" | python3 "${KBPY}" prompt >/dev/null 2>&1 )
[ -d "${AI_KB_DIR}/projects/otherproj" ]; ok $? "而 hook 模式（agent 真在该目录工作）仍会正常登记"

echo "[7] doctor / audit / export / clean-stale"
[ -f "${AI_KB_DIR}/_meta/map.json" ] && cp "${AI_KB_DIR}/_meta/map.json" "${T}/map.before" || echo '{}' > "${T}/map.before"
python3 "${KBPY}" doctor 2>&1 | grep -q "ai-kb v"; ok $? "doctor 可运行并显示版本"
if [ -f "${AI_KB_DIR}/_meta/map.json" ]; then cmp -s "${T}/map.before" "${AI_KB_DIR}/_meta/map.json"; else [ "$(cat "${T}/map.before")" = "{}" ]; fi
ok $? "doctor 是只读的（旧版会往 map.json 写入幽灵映射）"
python3 "${KBPY}" audit >/dev/null 2>&1; ok $? "audit 可运行"
python3 "${KBPY}" export "${T}/export.md" >/dev/null 2>&1; [ -s "${T}/export.md" ]; ok $? "export 生成了非空文件"
echo '{"/nonexistent/selftest-dir": "ghost"}' > "${AI_KB_DIR}/_meta/map.json"
python3 "${KBPY}" clean-stale >/dev/null 2>&1; grep -q "ghost" "${AI_KB_DIR}/_meta/map.json"; ok $? "clean-stale 默认只预览，不删除"
KB_CONFIRM=1 python3 "${KBPY}" clean-stale >/dev/null 2>&1; ! grep -q "ghost" "${AI_KB_DIR}/_meta/map.json"; ok $? "clean-stale 带 KB_CONFIRM=1 才真正清理"

echo "[8] 看板加密（需要 node）"
if command -v node >/dev/null 2>&1 && [ -f "${REPO}/build_dashboard.py" ] && [ -f "${REPO}/vault_encrypt.mjs" ]; then
  H5="${T}/h5"; mkdir -p "${H5}"; DK="${T}/kb-dash"; mkdir -p "${DK}/_meta" "${DK}/projects/dashproj/discussions"
  printf '# dashproj\nDASH-SECRET-MARKER-1 客户机密\n' > "${DK}/projects/dashproj/README.md"
  printf '# t\n## 未完成\n- [ ] T-1 [优化|高] DASH-SECRET-MARKER-2\n## 已完成\n' > "${DK}/projects/dashproj/todo.md"
  DPASS="selftest-passphrase-123456"; DO="${H5}/.ai-kb/dashboard_out"
  HOME="${H5}" AI_KB_DIR="${DK}" KB_DASH_PASS="${DPASS}" python3 "${REPO}/build_dashboard.py" >/dev/null 2>&1; ok $? "构建加密看板成功"
  [ -f "${DO}/vault/params.json" ]; ok $? "产物含 vault/params.json"
  ! grep -rqaF "DASH-SECRET-MARKER" "${DO}"; ok $? "密文站里搜不到任何明文内容"
  ! grep -rqaF "dashproj" "${DO}"; ok $? "密文站里看不出项目名"
  [ ! -e "${DO}/search-index.json" ] && [ ! -e "${DO}/nav.json" ] && [ ! -d "${DO}/content" ]; ok $? "不含明文索引/导航/内容目录"
  KB_DASH_PASS="${DPASS}" node "${REPO}/vault_encrypt.mjs" verify --out "${DO}" >/dev/null 2>&1; ok $? "正确口令可解开全部文件"
  KB_DASH_PASS="wrong-passphrase-123456" node "${REPO}/vault_encrypt.mjs" verify --out "${DO}" >/dev/null 2>&1; [ $? -ne 0 ]; ok $? "错误口令解不开"
  cp -R "${DO}/vault" "${T}/vault1"
  HOME="${H5}" AI_KB_DIR="${DK}" KB_DASH_PASS="${DPASS}" python3 "${REPO}/build_dashboard.py" >/dev/null 2>&1
  nd="$(diff -rq "${T}/vault1" "${DO}/vault" | grep -v manifest | wc -l | tr -d ' ')"; [ "${nd}" = "0" ]; ok $? "重复构建密文逐字节相同（增量部署只传改动）"
  mkdir -p "${T}/notmine"; echo x > "${T}/notmine/keep.txt"
  HOME="${H5}" AI_KB_DIR="${DK}" KB_DASH_PASS="${DPASS}" python3 "${REPO}/build_dashboard.py" --out "${T}/notmine" >/dev/null 2>&1; rc=$?
  [ "${rc}" -ne 0 ] && [ -f "${T}/notmine/keep.txt" ]; ok $? "拒绝改动非本工具的目录（不会误删别的文件）"
  HOME="${H5}" AI_KB_DIR="${DK}" python3 "${REPO}/build_dashboard.py" --out "${T}/nopass" >/dev/null 2>&1; [ $? -ne 0 ]
  ok $? "没有口令时拒绝构建（不会悄悄产出明文站）"
  bash -n "${REPO}/deploy_dashboard.sh"; ok $? "deploy_dashboard.sh 语法正确"
else echo "  - 跳过（需要 node 与 build_dashboard.py / vault_encrypt.mjs）"; fi

echo "[9] 会话提取脱敏"
if [ -f "${REPO}/extract_sessions.py" ]; then
  EX="${REPO}/extract_sessions.py" python3 - <<'EOF'
import importlib.util, os, sys
sys.argv = ["x"]
sp = importlib.util.spec_from_file_location("ex", os.environ["EX"]); m = importlib.util.module_from_spec(sp); sp.loader.exec_module(m)
fake_tok = "gh" + "p_" + "A" * 36          # 运行时拼接，避免本脚本里出现字面量被密钥扫描误拦
out = m.redact("请用 token " + fake_tok + " 并且 pass" + "word: " + "x" * 10 + " 访问")
assert fake_tok not in out and "<REDACTED>" in out, out
assert m.redact("普通的一句话，没有任何密钥") == "普通的一句话，没有任何密钥"
EOF
  ok $? "会话原文里的疑似凭证被替换为 <REDACTED>，普通文本不受影响"
else echo "  - 跳过（找不到 extract_sessions.py）"; fi

echo "[10] 一致性"
python3 "$KBPY" status >/dev/null 2>&1; ok $? "status 可运行"
echo; echo "自测结果：通过 ${pass}，失败 ${fail}"
[ "${fail}" = 0 ] && echo "✅ ai-kb 机制正常（临时数据已清理）" || echo "❌ 有失败项，请把上面的 ✘ 项告诉用户，不要继续安装"
[ "${fail}" = 0 ]
