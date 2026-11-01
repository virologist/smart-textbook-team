#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_declaration.py — M3 声明与行为解耦校验（GATE2 §6）

==============================================================================
凡是文档里写「由 X 拦截 / 由 Y 生成」的句子，必须能被反查到 X/Y 的实现行。
查不到 → WARN 并列入技术债清单——防 B-12 类虚构职责（如「PDF 导出由
build_manuscript.py 处理」而脚本里没有任何 PDF 代码，声明写了、行为没有）。

反查口径
------------------------------------------------------------------------------
  模式 A（判据拦截声明）：句中含判据号（4.x/5.x）且含「拦截/拦住/必须拦」
    → 4.x 在 scripts/check_manuscript.py 必须有 r.add("4.x…" 实现行
      （族前缀匹配：声明 4.2 可由 4.2a-图 实现覆盖）
    → 5.x 在 scripts/check_book.py 同理
  模式 B（工具能力声明）：句中含包内脚本名（xxx.py 或 scripts/xxx.py）
    且含能力动词（拦截|拦住|生成|产出|输出|导出|写入|重排|合并|重编号|计数|落盘|执行|校验）
    → 脚本文件必须存在且含 ≥1 个 def（非空实现）
    → 句中拉丁技术词（≥2 字符，如 PDF/docx/PAGE/TOC，过滤常见停用词）
      必须能在脚本文本中反查到（大小写不敏感）——能力词查无 = 虚构职责
  模式 C（flag 声明）：句中含 `--flag` 且含（生成|开启|触发|启用|执行）
    → 包内某脚本 argparse 必须注册过该 flag
  外部路径（含 `/` 且非 scripts/ 前缀）与纯示例代码块内声明：跳过（INFO）

用法
------------------------------------------------------------------------------
  python3 scripts/check_declaration.py [--root <包根>] [--strict] [--out <技术债清单.md>]

退出码
------------------------------------------------------------------------------
  0 全部声明可反查（或仅 INFO 跳过项）；TECH_DEBT=0
  1 --strict 下存在 WARN（技术债 >0）
  2 输入错误（根目录不存在）
==============================================================================
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SCAN_GLOBS = ("skills/**/*.md", "agents/*.md", "references/**/*.md",
              "README.md", "CONTRIBUTING.md", "CHANGELOG.md", "AGENTS.md")
# 扫描但不判警告的（历史叙述性文本，声明密度低价值）——仍扫描模式 A（判据反查最重要）
SOFT_FILES = ("CHANGELOG.md",)

CAP_VERBS = ("拦截", "拦住", "必须拦", "生成", "产出", "输出", "导出", "写入",
             "重排", "合并", "重编号", "计数", "落盘", "执行", "校验")
FLAG_VERBS = ("生成", "开启", "触发", "启用", "执行", "调用")
# 能力词口径（B6 装机实证收紧）：只有**工件词表内**或**含大写字母**的拉丁词
# 才参与能力反查——否则英文散文词（arguments/cwd/evo/advisory/agent ID 子词
# 如 smart-textbook-team）全被误当能力词，首跑 16/18 是这类噪声。
ARTIFACT_VOCAB = {"pdf", "docx", "xlsx", "pptx", "png", "svg", "ipynb", "zip",
                  "pandoc", "nbconvert", "word", "excel", "matlab", "fasta",
                  "toc", "page", "footnote", "fingerprint", "hash", "badzipfile"}
# 判据号前缀：§5.2 是小节引用不是判据 5.2——负向后视排除（首跑误报实证）
RE_CRIT = re.compile(r"(?<!§)\b([45]\.\d+[a-z]?)\b")
RE_BLOCK = re.compile(r"拦截|拦住|必须拦")
RE_SENTENCE = re.compile(r"[^。！？\n]+")
RE_SCRIPT = re.compile(r"(?:scripts/)?([A-Za-z_][\w-]*\.py)")
RE_FLAG = re.compile(r"(--[a-z][a-z0-9-]{2,})")
RE_LATIN = re.compile(r"[A-Za-z]{2,}")
RE_IMPL = re.compile(r"^\s*def\s+\w+", re.M)


def strip_code_blocks(text: str) -> str:
    """去掉 ``` 围栏代码块——代码示例里的「由 X 生成」不算文档声明。"""
    return re.sub(r"```.*?```", "", text, flags=re.S)


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def check_criterion(cid: str, scripts_dir: Path) -> str | None:
    """模式 A：判据号 → r.add 实现行反查（族前缀匹配）。返回缺失原因或 None。"""
    target = scripts_dir / ("check_book.py" if cid.startswith("5.") else "check_manuscript.py")
    if not target.is_file():
        return f"{target.name} 不存在"
    src = read(target)
    # r.add("4.12d" / r.add(f"4.2a-{kind}" —— 前缀命中即族已落地
    if re.search(rf'r\.add\(\s*f?"{re.escape(cid)}', src):
        return None
    return f"{target.name} 无 r.add(\"{cid}…\" 实现行"


def check_tool(script: str, sentence: str, scripts_dir: Path) -> str | None:
    """模式 B：脚本存在 + 非空实现 + 句中拉丁技术词可反查。"""
    p = scripts_dir / script
    if not p.is_file():
        return f"scripts/{script} 不存在（包内脚本名声明无法反查）"
    src = read(p)
    if not RE_IMPL.search(src):
        return f"scripts/{script} 无任何 def（空壳/纯文案）"
    # 能力词反查：只认工件词表内的词（大小写不敏感）——散文英文/缩写（SSOT/CI/evo…）
    # 一律不参与（B6 装机实证：宽口径首跑 16/18 噪声，收紧后只留真债）
    tokens = {t.lower() for t in RE_LATIN.findall(sentence)
              if t.lower() in ARTIFACT_VOCAB and t.lower() != script[:-3].lower()}
    missing = sorted(t for t in tokens if t not in src.lower())
    if missing:
        return (f"scripts/{script} 内查无能力词 {missing}"
                f"（声明了职责但实现里没有对应代码——B-12 类虚构职责）")
    return None


def check_flag(flag: str, scripts_dir: Path) -> str | None:
    """模式 C：--flag 须在某脚本 argparse 注册。"""
    for p in sorted(scripts_dir.glob("*.py")):
        if flag in read(p):
            return None
    return f"包内无脚本注册 {flag}（flag 声明无法反查）"


def main() -> int:
    ap = argparse.ArgumentParser(description="M3 声明与行为解耦校验")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent),
                    help="包根目录（缺省 = 脚本所在包）")
    ap.add_argument("--strict", action="store_true",
                    help="存在 WARN（技术债）即 exit 1")
    ap.add_argument("--out", default=None, help="技术债清单输出路径（markdown）")
    args = ap.parse_args()

    root = Path(args.root).expanduser()
    if not root.is_dir():
        print(f"[ERROR] 包根不存在: {root}", file=sys.stderr)
        return 2
    scripts_dir = root / "scripts"

    hits: list[tuple[str, int, str, str]] = []   # (file, line, 声明, 缺失原因)
    checked = 0

    for pattern in SCAN_GLOBS:
        for p in sorted(root.glob(pattern)):
            if not p.is_file():
                continue
            rel = p.relative_to(root).as_posix()
            soft = rel in SOFT_FILES
            text = strip_code_blocks(read(p))
            for line_no, line in enumerate(text.splitlines(), 1):
                for sent in RE_SENTENCE.findall(line):
                    # ── 模式 A：判据拦截声明 ──
                    if RE_BLOCK.search(sent):
                        for cid in RE_CRIT.findall(sent):
                            checked += 1
                            reason = check_criterion(cid, scripts_dir)
                            if reason:
                                hits.append((rel, line_no, sent.strip()[:80], reason))
                    # ── 模式 B：工具能力声明 ──
                    if any(v in sent for v in CAP_VERBS):
                        for script in RE_SCRIPT.findall(sent):
                            # 外部路径（CONTRIBUTING 的 tb-writer/... 等）跳过
                            if "/" in sent and f"scripts/{script}" not in sent \
                                    and f"`{script}" not in sent and not (scripts_dir / script).is_file():
                                continue
                            checked += 1
                            reason = check_tool(script, sent, scripts_dir)
                            if reason and not soft:
                                hits.append((rel, line_no, sent.strip()[:80], reason))
                    # ── 模式 C：flag 声明 ──
                    if any(v in sent for v in FLAG_VERBS):
                        for flag in RE_FLAG.findall(sent):
                            if " " in flag:
                                continue
                            checked += 1
                            reason = check_flag(flag, scripts_dir)
                            if reason and not soft:
                                hits.append((rel, line_no, sent.strip()[:80], reason))

    print("=" * 62)
    print(f"M3 声明↔实现反查 | 扫描声明 {checked} 条")
    print("=" * 62)
    for rel, ln, sent, reason in hits:
        print(f"  ⚠ {rel}:{ln}")
        print(f"      声明: {sent}")
        print(f"      → {reason}")
    print("-" * 62)
    print(f"TECH_DEBT={len(hits)}")
    print("=" * 62)

    if args.out and hits:
        out = Path(args.out).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        lines = ["# M3 技术债清单（声明无法反查实现）", ""]
        for rel, ln, sent, reason in hits:
            lines += [f"## {rel}:{ln}", f"- 声明：{sent}", f"- 缺失：{reason}", ""]
        out.write_text("\n".join(lines), encoding="utf-8")
        print(f"技术债清单 → {out}")

    return 1 if (args.strict and hits) else 0


if __name__ == "__main__":
    sys.exit(main())
