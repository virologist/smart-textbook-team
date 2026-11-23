#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_md_links.py — 包内 Markdown 链接与路径引用核验（v2.18.1 新增门禁）
======================================
存在理由（2026-11-17 链接核验实证）：包内 376 条链接/路径引用靠人眼维护，
曾出现 docs/evals/router_baseline.md、scripts/build_chapter.py 等虚构引用
（各轮审计已修，但无门禁防回潮）。本脚本把「链接有效性」做成确定性检查。

检查范围（两条通道）：
  ① Markdown 链接 [text](target) —— 跳过 http/https/锚点/mailto
  ② 反引号内的包内路径引用 `skills/…` / `references/…` / `agents/…` /
     `scripts/…` / `docs/…` / `vendor/…`（限 .md/.py/.sh/.ps1/.json/.yml/.yaml）

已知合法模式（不视为断链）：
  A. 模板占位符：`references/profiles/{discipline}.md` —— {…} 是变量说明；
     展开时按「是否有该目录 + 目录内 ≥1 个同扩展名文件」判定
  B. 标签语法误配：`[实](PMID: …)` / `[引](…)——测试夹具与正文的引用标签，
     (…) 内非路径（含空格或 PMID:/DOI: 前缀）一律跳过
  C. 历史留档文件：CHANGELOG.md、docs/ 下审计报告（日期开头）、
     skills/SKILL_CHANGELOG.md、docs/00_archive/ —— 历史流水照抄旧引用属
     免疫内容（与 doc_consistency D1 免疫口径一致）

退出码：0 = 全部通过 | 1 = 存在真实断链

用法：python3 scripts/check_md_links.py [--json]
"""
import argparse
import json
import re
import sys
from pathlib import Path

# 历史留档（免疫）：这些文件里的旧引用不核验
IMMUNE_FILES = {"CHANGELOG.md", "SKILL_CHANGELOG.md"}
# 审计报告（docs 日期留档 + harness 流程的 04-test/ 成员报告）+ 测试夹具。
# 04-test/ 报告会引用 agent-harness-expert 专家包的路径（如 agents/_harness_kb_init.py），
# 跨包引用按本包根解析必然断——报告是流程留档非包文档，豁免（2026-11-23 复测）
IMMUNE_DIR_PREFIXES = ("docs/2026-", "tests/fixtures/", "04-test/")
# 运行态目录（agent-harness-expert SOP 项目级状态机/wiki 底座）不属包文档，不参与核验
# （2026-11-20 复测：.harness-kb/learnings.md 跨包引用 agents/_harness_kb_init.py 造成假断链）
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules", "docs/00_archive",
             ".harness-kb", ".wiki-creator"}
PATH_PREFIXES = ("skills/", "references/", "agents/", "scripts/", "docs/", "vendor/")
EXTS = (".md", ".py", ".sh", ".ps1", ".json", ".yml", ".yaml")

MD_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
BACKTICK_PATH = re.compile(
    r"`((?:skills|references|agents|scripts|docs|vendor)/[A-Za-z0-9_\-./{}【】\[\]]+\.(?:md|py|sh|ps1|json|yml|yaml))`")
PLACEHOLDER = re.compile(r"\{[^}]*\}")
NON_PATH_TARGET = re.compile(r"(?:^|\s)(?:PMID|DOI|doi)\s*:")   # 标签语法：[实](PMID: …)
# 勘误性提及：行内明确说明该路径不存在（引用它正是为了声明其虚构）
ERRATUM_CONTEXT = re.compile(r"不存在|虚构|从未存在|勘误|已迁移|已移除|已删除")


def _placeholder_resolvable(pkg_root: Path, rel: str) -> bool:
    """{…} 占位符路径：目录存在且目录内有 ≥1 个同扩展名文件即算可解析。"""
    m = PLACEHOLDER.search(rel)
    if not m:
        return False
    concrete = PLACEHOLDER.sub("x", rel)          # profiles/x.md
    directory = pkg_root / concrete.rsplit("/", 1)[0]
    ext = concrete.rsplit(".", 1)[-1] if "." in concrete else ""
    return directory.is_dir() and any(directory.glob(f"*.{ext}"))


def _is_immune(rel_md: str) -> bool:
    if rel_md in IMMUNE_FILES or Path(rel_md).name == "SKILL_CHANGELOG.md":
        return True
    return rel_md.startswith(IMMUNE_DIR_PREFIXES)


def check_links(pkg_root: Path) -> dict:
    broken, checked = [], 0
    md_files = [p for p in sorted(pkg_root.rglob("*.md"))
                if not any(d in p.parts for d in SKIP_DIRS)]
    for md in md_files:
        rel_md = md.relative_to(pkg_root).as_posix()
        immune = _is_immune(rel_md)
        text = md.read_text(encoding="utf-8")

        # ① markdown 链接
        for m in MD_LINK.finditer(text):
            target = m.group(1).strip()
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            if NON_PATH_TARGET.search(target) or " " in target:
                continue                            # 标签语法 / 非路径
            target = target.split("#")[0]
            if not target:
                continue
            checked += 1
            if immune:
                continue
            resolved = (md.parent / target).resolve()
            if not resolved.exists():
                broken.append({"file": rel_md, "kind": "md-link", "target": target})

        # ② 反引号包内路径引用（逐行扫，便于勘误上下文豁免）
        for line_no, line in enumerate(text.splitlines(), 1):
            for m in BACKTICK_PATH.finditer(line):
                raw = m.group(1)
                checked += 1
                if immune:
                    continue
                if ERRATUM_CONTEXT.search(line):
                    continue        # 勘误性提及：声明其不存在，非功能性引用
                if PLACEHOLDER.search(raw):
                    if _placeholder_resolvable(pkg_root, raw):
                        continue
                    broken.append({"file": rel_md, "kind": "backtick-path",
                                   "target": raw, "note": "占位符路径无可解析目录"})
                    continue
                resolved = (pkg_root / raw).resolve()
                if not resolved.exists():
                    broken.append({"file": f"{rel_md}:{line_no}",
                                   "kind": "backtick-path", "target": raw})

    return {"total": checked, "broken": broken, "files": len(md_files)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pkg-root", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    result = check_links(Path(args.pkg_root).resolve())
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("=" * 62)
        print("Markdown 链接与路径引用核验")
        print("=" * 62)
        print(f"  扫描 {result['files']} 个 .md | 核验 {result['total']} 条 | 断链 {len(result['broken'])}")
        for b in result["broken"]:
            print(f"  ✗ {b['file']} → {b['target']}"
                  + (f"（{b['note']}）" if b.get("note") else ""))
        print("=" * 62)
    return 1 if result["broken"] else 0


if __name__ == "__main__":
    sys.exit(main())
