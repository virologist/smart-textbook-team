#!/usr/bin/env bash
# package_release.sh — 专家包导出打包 + 版本一致性校验（2026-10-15）
#
# 存在理由（真实教训）：smart-textbook-team.zip 曾停留在 2026-08-29 的 2.0.0/21 文件，
# 而真源已到 2.2.1/70 文件——**手工打包没有任何门禁，一个多月没人发现**。
# 本脚本把「打包」变成有校验的确定性动作：版本不一致直接拒绝打包。
#
# 用法:
#   bash scripts/package_release.sh [输出路径]
#   bash scripts/package_release.sh --check     # 只校验包内版本 vs 源仓，不打包
#
# 退出码: 0 = 一致并打包成功 | 1 = 版本漂移(拒绝打包) | 2 = 用法错误

set -euo pipefail

PKG_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_OUT="$HOME/Library/CloudStorage/OneDrive-Personal/GPT/Claude/tb-writer/smart-textbook-team.zip"
OUT="${1:-$DEFAULT_OUT}"
MODE="build"

if [[ "${1:-}" == "--check" ]]; then
    MODE="check"; OUT="$DEFAULT_OUT"
fi

log()  { printf '\033[1;34m[package]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[ok]\033[0m %s\n' "$*"; }
err()  { printf '\033[1;31m[err]\033[0m %s\n' "$*" >&2; }

# ── 1. 读源仓版本（三处 manifest 必须自洽）───────────────────────────
SRC_VER=$(python3 -c "
import json,sys
cb = json.load(open('$PKG_ROOT/.codebuddy-plugin/plugin.json'))['version']
cc = json.load(open('$PKG_ROOT/.claude-plugin/plugin.json'))['version']
mk = json.load(open('$PKG_ROOT/.claude-plugin/marketplace.json'))
mkv = mk['metadata']['version']; mkp = mk['plugins'][0]['version']
sh = [l.split('=')[1].strip().strip('\"') for l in open('$PKG_ROOT/install.sh')
      if l.startswith('VERSION=')][0]
vs = [cb, cc, mkv, mkp, sh]
if len(set(vs)) != 1:
    print('DRIFT:' + '|'.join(vs)); sys.exit(9)
print(cb)
" 2>/dev/null) || {
    err "源仓版本漂移（.codebuddy-plugin / .claude-plugin / marketplace.json / install.sh 四处不一致）"
    err "请先跑 tests/test_manifest_sync.py 定位，修完再打包"
    exit 1
}

log "源仓版本: $SRC_VER"
log "打包根:   $PKG_ROOT"

# ── 2. check 模式：只比对已有 zip ─────────────────────────────────────
# 变量必须在 if 外先赋默认值：set -u 下 if 分支内赋值、后续引用会报 unbound
# （与 install.sh 2026-10-15 踩过的坑同类，此处显式规避）
if [[ "$MODE" == "check" ]]; then
    if [[ ! -f "$OUT" ]]; then
        err "导出包不存在: $OUT"
        exit 2
    fi
    ZIP_VER=$(unzip -p "$OUT" "smart-textbook-team/.codebuddy-plugin/plugin.json" 2>/dev/null \
        | python3 -c "import json,sys; print(json.load(sys.stdin)['version'])" 2>/dev/null || echo "读取失败")
    ZIP_N=$(unzip -l "$OUT" | tail -1 | awk '{print $2}')
    if [[ "${ZIP_VER:-}" != "$SRC_VER" ]]; then
        err "导出包版本落后: zip=${ZIP_VER:-} vs 源仓=$SRC_VER"
        err "修复: bash scripts/package_release.sh"
        exit 1
    fi
    ok "导出包版本一致: ${ZIP_VER:-?}（${ZIP_N:-?} 文件）"
    exit 0
fi

# ── 3. 打包（排除 .git 与 macOS 元数据）───────────────────────────────
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp -R "$PKG_ROOT" "$STAGE/smart-textbook-team"
rm -rf "$STAGE/smart-textbook-team/.git" "$STAGE/smart-textbook-team/.DS_Store"
find "$STAGE" -name '.DS_Store' -delete 2>/dev/null || true
# 运行态缓存属派生产物，不进分发包（审计实测曾带入 28 项 / 556 KiB）
find "$STAGE/smart-textbook-team" -type d \( -name '__pycache__' -o -name '.pytest_cache' \) \
    -prune -exec rm -rf {} + 2>/dev/null || true
find "$STAGE/smart-textbook-team" -name '*.pyc' -delete 2>/dev/null || true

rm -f "$OUT"
(cd "$STAGE" && zip -r -q "$OUT" smart-textbook-team)

# ── 4. 打包后自检：回读 zip 内版本 ───────────────────────────────────
ZIP_VER=$(unzip -p "$OUT" "smart-textbook-team/.codebuddy-plugin/plugin.json" \
    | python3 -c "import json,sys; print(json.load(sys.stdin)['version'])")
if [[ "$ZIP_VER" != "$SRC_VER" ]]; then
    err "打包后回读版本不一致: zip=$ZIP_VER vs 源仓=$SRC_VER（打包异常）"
    exit 1
fi

FILE_N=$(unzip -l "$OUT" | tail -1 | awk '{print $2}')
ok "打包完成: $OUT"
ok "  版本 $ZIP_VER ｜ $FILE_N 文件 ｜ $(du -h "$OUT" | cut -f1)"
log "下一步（如需对外分发）: gh release create v$SRC_VER \"$OUT\""