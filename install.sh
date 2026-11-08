#!/usr/bin/env bash
# install.sh — Smart Textbook Team cross-platform installer
# 支持平台：WorkBuddy / Claude Code / Claude Desktop / Cursor
# 用法: ./install.sh [--target TARGET] [--dry-run] [--help]
#   TARGET: workbuddy | claude-code | claude-desktop | cursor | all（默认）
#
# Author: TZUVet (MIT)

set -euo pipefail

# ── 运行时依赖（★E4 v2.11.1 显式声明；完整附表见 references/skill-mounting.md §7）──
# 硬依赖：python3 >= 3.10（全部 scripts/*.py 与 CI）
# 测试依赖：pytest（tests/ 全量；python3 -m pip install pytest）
# 打包依赖：zip / unzip（package_release.sh）
# 环境隐性依赖（成员协议引用，缺失按行内降级链）：WebFetch / ToolSearch+DeferExecuteTool /
#   ima 知识库 / Obsidian $TB_VAULT_PATH / markitdown——均为可选增强，缺失不阻塞安装
VERSION="2.11.1"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="all"
DRY_RUN=0

usage() {
    sed -n '3,11p' "$0" | sed 's/^# \{0,1\}//'
    echo "  --lint-ps1   对 install.ps1 做静态语法自检（无 pwsh 环境的替代验证）"
    exit "${1:-0}"
}

# ---------- install.ps1 静态语法自检（残留1：无 pwsh 环境的替代验证）----------
# 背景：开发/CI 均无 PowerShell → ps1 此前零验证。真机实跑仍不可替代，
# 但本自检能拦住「括号不配平 / here-string 未闭合 / 引号计数错乱 / 关键结构缺失」
# 这类会在 PowerShell 解析期直接炸掉的错误（历史上 M 系列门禁抓过此类）。
lint_ps1() {
    local PS1_FILE="$REPO_DIR/install.ps1"
    if [[ ! -f "$PS1_FILE" ]]; then err "install.ps1 不存在"; return 1; fi
    python3 - "$PS1_FILE" <<'PYEOF'
import re, sys
from pathlib import Path

t = Path(sys.argv[1]).read_text(encoding="utf-8")
lines = t.splitlines()
errors = []

# 1) 花括号配平（剔除 here-string 与注释与字符串字面量后计数）
def strip_noise(text: str) -> str:
    # 去 here-string @'...'@（其内容为字面量）
    text = re.sub(r"@'\r?\n.*?\r?\n'@", "", text, flags=re.S)
    # 去行注释与块注释
    text = re.sub(r"<#.*?#>", "", text, flags=re.S)
    text = "\n".join(re.sub(r"#.*$", "", ln) for ln in text.splitlines())
    # 去双引号字符串（简化：不含嵌套 " 的行内串）
    text = re.sub(r'"(?:[^"`]|`.)"', '""', text)
    # 去单引号字符串（'' 转义）
    text = re.sub(r"'(?:[^']|'')*'", "''", text)
    return text

cleaned = strip_noise(t)
ob, cb = cleaned.count("{"), cleaned.count("}")
if ob != cb:
    errors.append(f"花括号不配平: {{ ×{ob} vs }} ×{cb}")

# 2) 单引号字符串逐行闭合检查（跳过 here-string 区间与注释行）
in_heredoc = False
for i, ln in enumerate(lines, 1):
    s = ln.strip()
    if s.endswith("@'") and not s.startswith("'@"):
        # here-string 开始行（$x = @' 或裸 @'）：@' 起字面量区，前缀仍须引号配平
        body = s[: s.rfind("@'")]
        if body.count("'") % 2 != 0:
            errors.append(f"行 {i}: here-string 前缀行单引号未闭合: {s[:70]}")
        in_heredoc = True; continue
    if s == "'@":
        in_heredoc = False; continue
    if in_heredoc or s.startswith("#"):
        continue
    cnt = ln.count("'")
    # 偶数个单引号才闭合（数组/参数串都是成对的）；含 '' 转义也保持偶性
    if cnt % 2 != 0:
        errors.append(f"行 {i}: 单引号数为奇数（字符串可能未闭合）: {ln.strip()[:70]}")

# 3) 关键结构存在性
must_have = [
    ("function Install-WorkBuddy", "WorkBuddy 安装函数"),
    ("function Install-ClaudeCode", "Claude Code 安装函数"),
    ("$REPO_DIR -eq $DEST", "自毁保护"),
    ("avatars", "avatars 清单项"),
    ("marketplace.json", "marketplace 注册"),
]
for needle, label in must_have:
    if needle not in t:
        errors.append(f"缺少关键结构: {label}（'{needle}'）")

# 4) 技能循环 ×3 应含 9 技能（匹配 foreach ($s in @(...)) 实际格式）
declared = {"agent-harness-protocol","book-orchestration","citation-verify","learn-protocol","manuscript-delivery",
            "multi-agent-patterns","scientific-figure","task-router","team-generation","textbook-pipeline-workflow"}
n_loops = 0
for m in re.finditer(r"foreach\s*\(\$s\s+in\s+@\(([^)]*)\)\)", t):
    names = set(re.findall(r"'([^']+)'", m.group(1)))
    if declared <= names:
        n_loops += 1
if n_loops < 3:
    errors.append(f"技能循环含全 9 技能的只有 {n_loops} 处（应 ≥3）")

if errors:
    print(f"[lint-ps1] FAIL — {len(errors)} 项：")
    for e in errors:
        print("   ✗", e)
    sys.exit(1)
print(f"[lint-ps1] PASS — 括号配平 / 引号闭合 / {len(must_have)} 关键结构 / 技能循环×3(9技能)")
PYEOF
}

# ---------- arg parsing ----------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --target) TARGET="$2"; shift 2 ;;
        --target=*) TARGET="${1#*=}"; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        --lint-ps1) lint_ps1; exit $? ;;
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
    # v2.2.3: 补 avatars/ —— plugin.json 引用 avatars/*.png（专家卡片图标），
    # 漏复制 = 安装态头像全空。
    # v2.5.1: **移除 settings.json** —— 宿主 ExpertPluginService 会把「恰有 1 个键且为
    #   非空 agent」的 settings.json 判定为「宿主自己生成的 agent override 缓存」，
    #   在激活专家时与宿主启动时各 unlink 一次（removeGeneratedAgentOverrideFile /
    #   removePersistedGeneratedAgentOverrides）。包内放该文件 = 与宿主抢同一个文件，
    #   必然被删（实测已丢失 4 次）。
    #   agent 名解析走 plugin.json 的 agentName / agents[] + markdown frontmatter，
    #   **从不读 settings.json** → 该文件对本包功能上冗余，移除无功能损失。
    for item in agents skills scripts tests vendor references avatars .codebuddy-plugin .claude-plugin \
                README.md LICENSE CHANGELOG.md CONTRIBUTING.md .gitignore; do
        if [[ -e "$REPO_DIR/$item" ]]; then
            # ── D-1 自毁保护（2026-10-30 修复）─────────────────────────────
            # 旧实现先 `rm -rf $DEST/$item` 再 `cp -R $REPO_DIR/$item`——当源目录
            # 就是目标目录（即用户在安装态目录里执行 install.sh）时，rm 已把源删掉，
            # cp 复制的是空目录 → **整包被清空且不报错**（实测 exit 13、agents/ 消失）。
            # 现改为：源==目标时不删不拷（幂等重装语义本就等价）。
            if [[ "$REPO_DIR" == "$DEST" ]]; then
                ok "  skipped (源=目标,幂等): $item"
                continue
            fi
            run "rm -rf '$DEST/$item'"
            run "cp -R '$REPO_DIR/$item' '$DEST/$item'"
            ok "  copied: $item"
        fi
    done
    # 注入 marketplace 注册（2026-10-15 P1-2 修复；2026-10-30 D-3 补实写条目）
    # v3 host 真实注册位置 = $WB/my-experts/.codebuddy-plugin/marketplace.json
    # （老路径 $WB/my-experts/marketplace.json 是 dead 位置，register_expert 走的是新位置）
    # 先建父目录再判 -d: 旧版只在 $WB/my-experts 已存在时建 marketplace.json,
    # 但 v3 首次安装 my-experts/ 根目录尚未建,导致 marketplace.json 永不创建
    #
    # ── D-3 修复（2026-10-30）────────────────────────────────────────────
    # 旧实现写入 `"plugins": []`（空数组）且**从不追加本插件条目**——
    # 注释声称「注入 marketplace 注册」，实际什么都没注册；
    # 且「已存在」分支只打印一行、**完全不更新**该文件 → 二次安装也不会注册。
    # 现改为：用 python3 就地 upsert 本插件条目（幂等：已存在则更新，不重复追加），
    # 并保留宿主 marketplace.json 里的其它插件条目。
    if [[ $DRY_RUN -eq 1 ]]; then
        ok "  DRY-RUN: would upsert marketplace 注册条目 → ${mkt_file:-}"
    else
        run "mkdir -p '${mkt_dir:-}'"
        # 用宿主真实结构补齐（name/source/description/version），
        # source 指向安装后的 DEST，与 register_expert 写入的结构一致。
        MKT_FILE="${mkt_file:-}" MKT_DEST="$DEST" MKT_NAME="smart-textbook-team" \
        MKT_VERSION="$VERSION" MKT_DESC="智能教材编写天团——十三态流水线编排的教材编写团队" \
        python3 - <<'PYEOF'
import json, os
from pathlib import Path

p = Path(os.environ["MKT_FILE"])
dest = os.environ["MKT_DEST"]
name = os.environ["MKT_NAME"]
ver = os.environ["MKT_VERSION"]
desc = os.environ["MKT_DESC"]

data = {"name": "my-experts", "owner": "TZUVet", "plugins": []}
if p.is_file():
    try:
        loaded = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data = loaded
            data.setdefault("name", "my-experts")
            data.setdefault("owner", "TZUVet")
            data.setdefault("plugins", [])
    except (OSError, json.JSONDecodeError):
        print("  [warn] marketplace.json 解析失败，将以新结构覆盖", flush=True)

entry = {"name": name, "source": dest, "description": desc, "version": ver}
plugins = [x for x in data.get("plugins", []) if x.get("name") != name]
plugins.append(entry)
data["plugins"] = plugins

p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"  [ok] marketplace 注册已 upsert: {name}@{ver} → {p}")
PYEOF
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
    for s in agent-harness-protocol book-orchestration citation-verify learn-protocol manuscript-delivery multi-agent-patterns scientific-figure task-router team-generation textbook-pipeline-workflow; do
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
    for s in agent-harness-protocol book-orchestration citation-verify learn-protocol manuscript-delivery multi-agent-patterns scientific-figure task-router team-generation textbook-pipeline-workflow; do
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
    for s in agent-harness-protocol book-orchestration citation-verify learn-protocol manuscript-delivery multi-agent-patterns scientific-figure task-router team-generation textbook-pipeline-workflow; do
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

This project uses the Smart Textbook Team (6 agents + 9 skills) from `smart-textbook-team-team-lead`. Subagent definitions are in `.cursor/agents/`, skills in `.cursor/skills/`.

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