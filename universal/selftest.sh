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

echo "[5] 一致性"
python3 "$KBPY" status >/dev/null 2>&1; ok $? "status 可运行"
echo; echo "自测结果：通过 ${pass}，失败 ${fail}"
[ "${fail}" = 0 ] && echo "✅ ai-kb 机制正常（临时数据已清理）" || echo "❌ 有失败项，请把上面的 ✘ 项告诉用户，不要继续安装"
[ "${fail}" = 0 ]
