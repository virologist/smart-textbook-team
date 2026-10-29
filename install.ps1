# install.ps1 — Smart Textbook Team cross-platform installer (Windows PowerShell)
# Supports: WorkBuddy / Claude Code / Claude Desktop / Cursor
# 用法:
#   .\install.ps1 -Target workbuddy          # 仅 WorkBuddy
#   .\install.ps1 -Target all -DryRun       # 全平台干跑
#   .\install.ps1 -Help                     # 帮助
#
# Author: TZUVet (MIT)

[CmdletBinding()]
param(
    [ValidateSet('workbuddy','claude-code','claude-desktop','cursor','all')]
    [string]$Target = 'all',
    [switch]$DryRun,
    [switch]$Help
)

$VERSION = '2.2.2'
# 仓库根 = 本脚本所在目录（install.ps1 就在仓库根，不要再取父目录）。
# 2026-10-30 修复：原实现多取一次 -Parent 指向了仓库的**父目录**，
# 导致所有 Test-Path 判假 → 逐个静默跳过，WorkBuddy 安装态实际什么都不装且不报错。
$REPO_DIR = $PSScriptRoot
if (-not $REPO_DIR) { $REPO_DIR = (Get-Location).Path }
$HOME_DIR = $HOME

function Write-Log  { param([string]$m) Write-Host "[install] $m" -ForegroundColor Cyan }
function Write-Warn { param([string]$m) Write-Host "[warn] $m" -ForegroundColor Yellow }
function Write-Err  { param([string]$m) Write-Host "[err] $m" -ForegroundColor Red }
function Write-Ok   { param([string]$m) Write-Host "[ok] $m" -ForegroundColor Green }

function Run {
    param([string]$cmd)
    if ($DryRun) {
        Write-Host "  DRY-RUN: $cmd"
    } else {
        Invoke-Expression $cmd
    }
}

function Install-WorkBuddy {
    Write-Log '→ WorkBuddy (专家团)'
    # v5 新路径优先,回退 v4 旧路径
    $WB_NEW = Join-Path $HOME_DIR '.codebuddy\plugins\marketplaces'
    $WB_OLD = Join-Path $HOME_DIR '.workbuddy\plugins\marketplaces'
    if (Test-Path $WB_OLD) {
        $WB = $WB_OLD
    } else {
        $WB = $WB_NEW
    }
    $DEST = Join-Path $WB 'my-experts\plugins\smart-textbook-team'
    Write-Log "  安装到: $DEST"
    Run "New-Item -ItemType Directory -Force -Path '$DEST'"
    # 复制核心目录与文件
    # v2.2.2 同步（与 install.sh 同纪律，2026-10-30）：
    #   + references  —— role-assembly.md（角色团 SSOT）与 path-ownership.md（路径归属表）
    #                    已迁入该目录，由装配器 resolve_shared_refs() 注入；漏复制 = 安装态死链
    #   + scripts/tests/vendor/.claude-plugin —— 与 install.sh 对齐（此前 PowerShell 路径
    #                    长期落后，安装态连 assemble_spawn_prompt.py / progress.py 都缺失）
    #   - role-assembly.md —— 已迁走，Test-Path 判假会静默跳过，属死条目，移除
    $items = @('agents','skills','scripts','tests','vendor','references','.codebuddy-plugin','.claude-plugin','README.md','LICENSE','CHANGELOG.md','CONTRIBUTING.md','.gitignore')
    foreach ($item in $items) {
        $src = Join-Path $REPO_DIR $item
        if (Test-Path $src) {
            $dst = Join-Path $DEST $item
            Run "Remove-Item -Recurse -Force '$dst' -ErrorAction SilentlyContinue"
            Run "Copy-Item -Recurse -Path '$src' -Destination '$dst'"
            Write-Ok "  copied: $item"
        }
    }
    Write-Warn '  启用方式: 打开 WorkBuddy → 插件管理 → 启用 smart-textbook-team'
}

function Install-ClaudeCode {
    Write-Log '→ Claude Code (subagent)'
    # 一律用户级 ~/.claude/agents/——subagent 是用户级共享资源
    # 项目级 .claude/agents/ 应仅在用户显式 -Scope project 时启用
    $TARGET_DIR = Join-Path $HOME_DIR '.claude\agents'
    Write-Log '  使用用户级 ~/.claude/agents/ (subagent 用户级共享)'
    Run "New-Item -ItemType Directory -Force -Path '$TARGET_DIR'"
    foreach ($a in @('smart-textbook-team-team-lead','didactic-architect','literature-scout','subject-writer','quality-examiner','visual-instructional-designer')) {
        $src = Join-Path $REPO_DIR (Join-Path 'agents' "$a.md")
        if (Test-Path $src) {
            Run "Copy-Item -Path '$src' -Destination '$TARGET_DIR\$a.md'"
            Write-Ok "  agent: $a.md"
        }
    }
    $SKILL_DIR = Join-Path $HOME_DIR '.claude\skills'
    Run "New-Item -ItemType Directory -Force -Path '$SKILL_DIR'"
    foreach ($s in @('agent-harness-protocol','citation-verify','learn-protocol','manuscript-delivery','multi-agent-patterns','task-router','textbook-pipeline-workflow')) {
        $src = Join-Path $REPO_DIR (Join-Path 'skills' $s)
        if (Test-Path $src) {
            $dst = Join-Path $SKILL_DIR $s
            Run "Remove-Item -Recurse -Force '$dst' -ErrorAction SilentlyContinue"
            Run "Copy-Item -Recurse -Path '$src' -Destination '$dst'"
            Write-Ok "  skill: $s"
        }
    }
    Write-Warn '  Claude Code v2.1.32+ 已支持 subagent skills; 用 Task tool dispatch 即可'
}

function Install-ClaudeDesktop {
    Write-Log '→ Claude Desktop (Windows)'
    # 仅 Windows 测试过
    $AGENTS_DIR = Join-Path $HOME_DIR '.claude\agents'
    Run "New-Item -ItemType Directory -Force -Path '$AGENTS_DIR'"
    foreach ($a in @('smart-textbook-team-team-lead','didactic-architect','literature-scout','subject-writer','quality-examiner','visual-instructional-designer')) {
        $src = Join-Path $REPO_DIR (Join-Path 'agents' "$a.md")
        if (Test-Path $src) {
            Run "Copy-Item -Path '$src' -Destination '$AGENTS_DIR\$a.md'"
            Write-Ok "  agent: $a.md"
        }
    }
    $SKILL_DIR = Join-Path $HOME_DIR '.claude\skills'
    Run "New-Item -ItemType Directory -Force -Path '$SKILL_DIR'"
    foreach ($s in @('agent-harness-protocol','citation-verify','learn-protocol','manuscript-delivery','multi-agent-patterns','task-router','textbook-pipeline-workflow')) {
        $src = Join-Path $REPO_DIR (Join-Path 'skills' $s)
        if (Test-Path $src) {
            $dst = Join-Path $SKILL_DIR $s
            Run "Remove-Item -Recurse -Force '$dst' -ErrorAction SilentlyContinue"
            Run "Copy-Item -Recurse -Path '$src' -Destination '$dst'"
            Write-Ok "  skill: $s"
        }
    }
    Write-Warn '  Claude Desktop 通过 ~/.claude/agents/ 自动识别 subagent'
    Write-Warn '  MCP 服务器请编辑 %APPDATA%\Claude\claude_desktop_config.json'
}

function Install-Cursor {
    Write-Log '→ Cursor (Agent Skills)'
    $TARGET_DIR = Join-Path $REPO_DIR '.cursor'
    Run "New-Item -ItemType Directory -Force -Path '$TARGET_DIR\agents'"
    Run "New-Item -ItemType Directory -Force -Path '$TARGET_DIR\skills'"
    foreach ($a in @('smart-textbook-team-team-lead','didactic-architect','literature-scout','subject-writer','quality-examiner','visual-instructional-designer')) {
        $src = Join-Path $REPO_DIR (Join-Path 'agents' "$a.md")
        if (Test-Path $src) {
            Run "Copy-Item -Path '$src' -Destination '$TARGET_DIR\agents\$a.md'"
            Write-Ok "  .cursor/agents/$a.md"
        }
    }
    foreach ($s in @('agent-harness-protocol','citation-verify','learn-protocol','manuscript-delivery','multi-agent-patterns','task-router','textbook-pipeline-workflow')) {
        $src = Join-Path $REPO_DIR (Join-Path 'skills' $s)
        if (Test-Path $src) {
            $dst = Join-Path $TARGET_DIR (Join-Path 'skills' $s)
            Run "Remove-Item -Recurse -Force '$dst' -ErrorAction SilentlyContinue"
            Run "Copy-Item -Recurse -Path '$src' -Destination '$dst'"
            Write-Ok "  .cursor/skills/$s"
        }
    }
    $AGENTS_MD = Join-Path $REPO_DIR 'AGENTS.md'
    if (-not (Test-Path $AGENTS_MD)) {
        if ($DryRun) {
            Write-Host '  DRY-RUN: would write AGENTS.md'
        } else {
            @'
# AGENTS.md — Smart Textbook Team (Cursor)

This project uses the Smart Textbook Team (6 agents + 7 skills) from `smart-textbook-team-team-lead`. Subagent definitions are in `.cursor/agents/`, skills in `.cursor/skills/`.

## Quick start

Dispatch the team lead (`smart-textbook-team-team-lead`) with your textbook title, target audience, and chapter topic — it will route through the 13-state pipeline.

## Update

Re-run `.\install.ps1 -Target cursor` from the upstream repo to refresh local copies.
'@ | Set-Content -Path $AGENTS_MD -Encoding UTF8
            Write-Ok '  created AGENTS.md'
        }
    } else {
        Write-Ok '  AGENTS.md 已存在,跳过'
    }
}

if ($Help) {
    Get-Help $MyInvocation.MyCommand.Path -Detailed | Out-String | Write-Host
    exit 0
}

Write-Host '===================================================='
Write-Host "Smart Textbook Team v${VERSION} 安装器"
Write-Host "源目录: $REPO_DIR"
Write-Host "目标平台: $Target"
Write-Host "模式: $(if ($DryRun) { 'DRY-RUN' } else { 'ACTUAL' })"
Write-Host '===================================================='

switch ($Target) {
    'workbuddy'      { Install-WorkBuddy }
    'claude-code'    { Install-ClaudeCode }
    'claude-desktop' { Install-ClaudeDesktop }
    'cursor'         { Install-Cursor }
    'all' {
        Install-WorkBuddy
        Install-ClaudeCode
        Install-ClaudeDesktop
        Install-Cursor
    }
    default { Write-Err "Unknown target: $Target"; exit 2 }
}

Write-Host ''
Write-Ok "完成 ✓  Smart Textbook Team v${VERSION}"
Write-Host ''
Write-Host '后续:'
Write-Host '  - WorkBuddy: 打开后应在专家列表看到『智能教材编写天团』'
Write-Host '  - Claude Code/Desktop: 用 Task tool dispatch 或 @ 提及 team-lead'
Write-Host '  - Cursor: 重启 Cursor, Agent 面板可见团队'
