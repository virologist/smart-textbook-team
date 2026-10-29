#!/usr/bin/env bash
# install.sh — Smart Textbook Team cross-platform installer
# 支持平台：WorkBuddy / Claude Code / Claude Desktop / Cursor
# 用法: ./install.sh [--target TARGET] [--dry-run] [--help]
#   TARGET: workbuddy | claude-code | claude-desktop | cursor | all（默认）
#
# Author: TZUVet (MIT)

set -euo pipefail

VERSION="2.2.2"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="all"
DRY_RUN=0

usage() {
    sed -n '3,11p' "$0" | sed 's/^# \{0,1\}//'
    exit "${1:-0}"
}

# ---------- arg parsing ----------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --target) TARGET="$2"; shift 2 ;;
        --target=*) TARGET="${1#*=}"; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help) usage 0 ;;
        *) echo "Unknown arg: $1"; usage 1 ;;
    esac
done

# ---------- helpers ----------
log()  { printf '\033[1;34m[install]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[1;31m[err]\033[0m %s\n'  "$*" >&2; }
ok()   { printf '\033[1;32m[ok]\033[0m %s\n'   "$*"; }

# run-or-print command based on DRY_RUN
# 注意：所有调用应传单个字符串参数（"$*" 合并）,因为 "$@" 在函数内不接收数组
run() {
    if [[ $DRY_RUN -eq 1 ]]; then
        printf '  DRY-RUN: %s\n' "$*"
    else
        eval "$*"
    fi
}

# Detect user home (works on macOS/Linux; works in sudo if $HOME not set)
HOME_DIR="${HOME:-$(eval echo ~$(id -un))}"
UNAME_S="$(uname -s 2>/dev/null || echo unknown)"

# ---------- WorkBuddy ----------
install_workbuddy() {
    log "→ WorkBuddy（专家团）"
    # v5 新路径优先，回退到 v4 老路径
    local WB_NEW="$HOME_DIR/.codebuddy/plugins/marketplaces"
    local WB_OLD="$HOME_DIR/.workbuddy/plugins/marketplaces"
    local WB=""
    # 默认装到当前已存在的路径，没有则选新路径
    if [[ -d "$WB_OLD" ]]; then WB="$WB_OLD"; else WB="$WB_NEW"; fi
    # 注入 marketplace 注册路径（v3 新路径，2026-10-15 P1-2 修复）—— 在函数顶层声明
    # 供全函数体访问,规避 set -u 在 elif 内的作用域边界
    local mkt_dir="$WB/my-experts/.codebuddy-plugin"
    local mkt_file="${mkt_dir:-}/marketplace.json"
    local DEST="$WB/my-experts/plugins/smart-textbook-team"
    log "  安装到: $DEST"
    run "mkdir -p '$DEST'"
    # 复制核心目录与文件
    # v2.1: 补 scripts/tests/vendor/.claude-plugin —— 缺 scripts 会导致
    # trace/progress/assemble_spawn_prompt 全部不可用（P0-1 连带修复）
    # v2.2.2: 补 references/ —— role-assembly.md（角色团 SSOT）与 path-ownership.md
    # （路径归属表）均迁移至此，由装配器 resolve_shared_refs() 自动注入成员 spawn 文案。
    # 漏掉本目录 = 安装态下资源清单全是死链（源仓态一切正常，安装态静默失效，最难排查）。
    # 同时移除已迁走的包根 role-assembly.md 条目（[[ -e ]] 判假会静默跳过，属死条目）。
    for item in agents skills scripts tests vendor references .codebuddy-plugin .claude-plugin \
                README.md LICENSE CHANGELOG.md CONTRIBUTING.md .gitignore; do
        if [[ -e "$REPO_DIR/$item" ]]; then
            run "rm -rf '$DEST/$item'"
            run "cp -R '$REPO_DIR/$item' '$DEST/$item'"
            ok "  copied: $item"
        fi
    done
    # 注入 marketplace 注册（2026-10-15 P1-2 修复）
    # v3 host 真实注册位置 = $WB/my-experts/.codebuddy-plugin/marketplace.json
    # （老路径 $WB/my-experts/marketplace.json 是 dead 位置，register_expert 走的是新位置）
    # 先建父目录再判 -d: 旧版只在 $WB/my-experts 已存在时建 marketplace.json,
    # 但 v3 首次安装 my-experts/ 根目录尚未建,导致 marketplace.json 永不创建
    if [[ ! -f "${mkt_file:-}" && $DRY_RUN -eq 0 ]]; then
        run "mkdir -p '${mkt_dir:-}'"
        cat > "${mkt_file:-}" <<'EOF'
{
  "name": "my-experts",
  "owner": "TZUVet",
  "plugins": []
}
EOF
        ok "  created marketplace.json（v3 新路径 ${mkt_file:-}）"
    elif [[ -f "${mkt_file:-}" ]]; then
        ok "  marketplace.json 已存在（位置 ${mkt_file:-}）"
    fi
    warn "  启用方式：打开 WorkBuddy → 插件管理 → 启用 smart-textbook-team（如已自动发现可忽略）"
}

# ---------- Claude Code ----------
install_claude_code() {
    log "→ Claude Code（subagent）"
    # 一律用户级 ~/.claude/agents/——subagent 是用户级共享资源
    # 项目级 .claude/agents/ 应仅在用户显式 --scope=project 时启用
    local TARGET_DIR="$HOME_DIR/.claude/agents"
    log "  使用用户级 ~/.claude/agents/（subagent 用户级共享）"
    run "mkdir -p '$TARGET_DIR'"
    # 复制 6 个 agent MD
    for a in smart-textbook-team-team-lead didactic-architect literature-scout subject-writer quality-examiner visual-instructional-designer; do
        if [[ -f "$REPO_DIR/agents/$a.md" ]]; then
            run "cp '$REPO_DIR/agents/$a.md' '$TARGET_DIR/$a.md'"
            ok "  agent: $a.md"
        fi
    done
    # skills 复制到 ~/.claude/skills/（Claude Code 自 v2.1.32+ 支持 skills frontmatter 字段）
    local SKILL_DIR="$HOME_DIR/.claude/skills"
    run "mkdir -p '$SKILL_DIR'"
    for s in agent-harness-protocol citation-verify learn-protocol multi-agent-patterns task-router textbook-pipeline-workflow; do
        if [[ -d "$REPO_DIR/skills/$s" ]]; then
            run "rm -rf '$SKILL_DIR/$s'"
            run "cp -R '$REPO_DIR/skills/$s' '$SKILL_DIR/$s'"
            ok "  skill: $s"
        fi
    done
    warn "  Claude Code v2.1.32+ 已支持 subagent skills；如用 Task tool dispatch,按 description 路由即可"
}

# ---------- Claude Desktop ----------
install_claude_desktop() {
    log "→ Claude Desktop（macOS）"
    # 仅 macOS 路径(其他平台跳过)
    if [[ "$UNAME_S" != "Darwin" ]]; then
        warn "  Claude Desktop 安装仅在 macOS 测试过,当前 $UNAME_S 跳过"
        return 0
    fi
    local AGENTS_DIR="$HOME_DIR/.claude/agents"
    run "mkdir -p '$AGENTS_DIR'"
    for a in smart-textbook-team-team-lead didactic-architect literature-scout subject-writer quality-examiner visual-instructional-designer; do
        if [[ -f "$REPO_DIR/agents/$a.md" ]]; then
            run "cp '$REPO_DIR/agents/$a.md' '$AGENTS_DIR/$a.md'"
            ok "  agent: $a.md"
        fi
    done
    local SKILL_DIR="$HOME_DIR/.claude/skills"
    run "mkdir -p '$SKILL_DIR'"
    for s in agent-harness-protocol citation-verify learn-protocol multi-agent-patterns task-router textbook-pipeline-workflow; do
        if [[ -d "$REPO_DIR/skills/$s" ]]; then
            run "rm -rf '$SKILL_DIR/$s'"
            run "cp -R '$REPO_DIR/skills/$s' '$SKILL_DIR/$s'"
            ok "  skill: $s"
        fi
    done
    warn "  Claude Desktop 通过 ~/.claude/agents/*.md 自动识别 subagent,无需额外配置"
    warn "  MCP 服务器(若需要)请手动编辑 ~/Library/Application Support/Claude/claude_desktop_config.json"
}

# ---------- Cursor ----------
install_cursor() {
    log "→ Cursor (Agent Skills)"
    local TARGET_DIR="$REPO_DIR/.cursor"
    run "mkdir -p '$TARGET_DIR/agents' '$TARGET_DIR/skills'"
    for a in smart-textbook-team-team-lead didactic-architect literature-scout subject-writer quality-examiner visual-instructional-designer; do
        if [[ -f "$REPO_DIR/agents/$a.md" ]]; then
            run "cp '$REPO_DIR/agents/$a.md' '$TARGET_DIR/agents/$a.md'"
            ok "  .cursor/agents/$a.md"
        fi
    done
    for s in agent-harness-protocol citation-verify learn-protocol multi-agent-patterns task-router textbook-pipeline-workflow; do
        if [[ -d "$REPO_DIR/skills/$s" ]]; then
            run "rm -rf '$TARGET_DIR/skills/$s'"
            run "cp -R '$REPO_DIR/skills/$s' '$TARGET_DIR/skills/$s'"
            ok "  .cursor/skills/$s"
        fi
    done
    # AGENTS.md 总入口（如不存在则创建）
    if [[ ! -f "$REPO_DIR/AGENTS.md" ]]; then
        if [[ $DRY_RUN -eq 1 ]]; then
            printf '  DRY-RUN: would write AGENTS.md\n'
        else
            cat > "$REPO_DIR/AGENTS.md" <<'EOF'
# AGENTS.md — Smart Textbook Team (Cursor)

This project uses the Smart Textbook Team (6 agents + 6 skills) from `smart-textbook-team-team-lead`. Subagent definitions are in `.cursor/agents/`, skills in `.cursor/skills/`.

## Quick start

Dispatch the team lead (`smart-textbook-team-team-lead`) with your textbook title, target audience, and chapter topic — it will route through the 13-state pipeline.

## Update

Re-run `bash install.sh --target cursor` from the upstream repo to refresh local copies.
EOF
            ok "  created AGENTS.md"
        fi
    else
        ok "  AGENTS.md 已存在,跳过"
    fi
}

# ---------- main ----------
echo "===================================================="
echo "Smart Textbook Team v${VERSION} 安装器"
echo "源目录: ${REPO_DIR}"
echo "目标平台: ${TARGET}"
echo "模式: $([ $DRY_RUN -eq 1 ] && echo DRY-RUN || echo ACTUAL)"
echo "===================================================="

case "$TARGET" in
    workbuddy)      install_workbuddy ;;
    claude-code)    install_claude_code ;;
    claude-desktop) install_claude_desktop ;;
    cursor)         install_cursor ;;
    all)
        install_workbuddy
        install_claude_code
        install_claude_desktop
        install_cursor
        ;;
    *)
        err "Unknown target: $TARGET"
        usage 1
        ;;
esac

echo
ok "完成 ✓  Smart Textbook Team v${VERSION}"
echo
echo "后续:"
echo "  - WorkBuddy: 打开后应能在专家列表看到『智能教材编写天团』"
echo "  - Claude Code/Desktop: 用 Task tool dispatch 或 @ 提及 team-lead"
echo "  - Cursor: 重启 Cursor,Agent 面板可见团队"
