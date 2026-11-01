#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_domain_neutral.py — 通用层「学科中立性」门禁（ADR-02，2026-11-01 批次 B3）

==============================================================================
为什么需要：盲诊五病灶之一「泛化只换名词不换判据」——`scripts/*.py` 全量 grep
`discipline` 仅 1 处，校验器层零学科概念；兽医判据（术语表禁用 AI / 11 个兽医
指标触发词 / 跨章「发病率」正则）写死在通用层，换专业（计算机/法学）时整体失效。
本门禁禁止学科常量词**回潮进通用层**：只许存在于 `references/profiles/*.md`
（学科化数据源），通用层只能「引用 profile」。

两条规则：
  ① 学科常量词表：扫描 agents/ skills/ scripts/ references/
     （排除 references/profiles/ 与 *.example.md）。词分两级——
     HARD「判据执行体词」（指标/触发词/禁用词）命中 = FAIL；
     SOFT「机构/法规/学科名」（作为核验源示例/白名单/默认学科说明）命中 = WARN（不阻塞）。
  ② 路径中立性：全包不得硬编码绝对路径（~/.workbuddy、/Users/、C:\\ 等），
     必须用 $EXPERT_DIR / $WORK_ROOT 等环境变量（N-2 路径中立性）。

用法
------------------------------------------------------------------------------
  python3 scripts/check_domain_neutral.py --root .
  python3 scripts/check_domain_neutral.py --root . --json

退出码：0 中立 | 1 命中学科常量或硬编码路径（--strict 时）| 2 用法错误
==============================================================================
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

# ── 规则①：学科常量词表（分级，ADR-02 首版词表的执行细化）─────────────
# HARD「判据执行体词」：触发词/指标/禁用词——写死在通用层 = 换学科即失效 = FAIL。
# SOFT「机构/法规/学科名」：作为核验源示例/白名单/默认学科说明出现在通用层是合理的
#   （权威源由 profile §2/§3 承载），仅 WARN 提示「建议下沉」，不阻塞。
# 分级理由：HARD 词直接决定判据行为（跨学科失效），SOFT 词是「以默认学科举例」的说明文字。
DOMAIN_TERMS_HARD = [
    "禽流感", "新城疫", "法氏囊", "大肠杆菌",
    "发病率", "病死率", "死亡率", "免疫程序", "效价",
    "阳性率", "感染率", "保护率", "剂量", "浓度", "日龄",
]
DOMAIN_TERMS_SOFT = [
    "兽医", "禽病", "兽药典", "ICTV", "WOAH", "Merck", "动物防疫法",
]
DOMAIN_TERMS = DOMAIN_TERMS_HARD + DOMAIN_TERMS_SOFT

# ── 规则①b：学段常量词表（ADR-02 同构扩展，#71 批次 2，2026-11-01）─────
# 病灶同构：学段判据写死在通用层（writer/designer/role-assembly 的「高职学生=…」），
# 换学段（学术本科/研究生教材）时整体失效。学段判据的唯一 SSOT =
# references/audience-profiles.md（四档判据表），通用层只能「引用该表」。
# HARD「判据执行体词」：学段画像/档位判据词——命中 = FAIL（与学科 HARD 同级）。
AUDIENCE_TERMS_HARD = [
    "高职学生", "高职生", "高职专科", "职业本科", "学术本科", "研究生",
    "大专生", "本科生",
]
# SOFT「举例措辞词」：说明性举例（如「如高职」）常见于历史注记——WARN 不阻塞。
AUDIENCE_TERMS_SOFT = [
    "高职", "专科", "学段画像", "受众画像",
]
AUDIENCE_TERMS = AUDIENCE_TERMS_HARD + AUDIENCE_TERMS_SOFT

# 学段词扫描范围与豁免（与学科词同目录集；豁免 = 学段判据的合法载体）
AUDIENCE_SCAN_DIRS = ["agents", "skills", "scripts", "references"]
AUDIENCE_SKIP_DIRS = {
    "references/profiles",          # 学科化数据源（学段裁剪注记的合法承载位）
    "references/audience-profiles.md",  # 学段判据表 SSOT（词表定义的对象本身）
}
# 门禁脚本自身是词表定义者，须排除（否则词表命中自身，永远红）
AUDIENCE_SELF = "scripts/check_domain_neutral.py"

# 扫描范围（相对包根）；references/ 需排除 profiles/ 与 *.example.md
SCAN_DIRS = ["agents", "skills", "scripts", "references"]
SKIP_DIRS = {"references/profiles"}
SKIP_SUFFIX = ".example.md"
# 门禁脚本自身是「词表定义者」，不是被审对象，须排除（否则词表命中自身，永远红）
SELF = "scripts/check_domain_neutral.py"

# ── 规则②：路径中立性 ──────────────────────────────────────────────────
# 硬编码绝对路径（宿主用户名不可写死；须用环境变量）
PATH_PATTERNS = [
    re.compile(r"~/\.[A-Za-z]+"),           # ~/.workbuddy 等宿主点目录
    re.compile(r"/Users/[A-Za-z0-9_.-]+/"),
    re.compile(r"C:\\Users\\"),
]
# install.sh 的「旧安装位置检测」（[[ -d "$WB_OLD" ]]）是兼容逻辑，非写死路径
PATH_SKIP_FILES = {"install.sh"}


def _iter_target_files(root: Path):
    """产出 (相对路径, Path) 的待扫文件（.md/.py/.sh/.yml/.yaml）。"""
    for d in SCAN_DIRS:
        base = root / d
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file():
                continue
            if p.suffix not in (".md", ".py", ".sh", ".yml", ".yaml"):
                continue
            rel = p.relative_to(root).as_posix()
            if rel == SELF:
                continue
            if any(rel == s or rel.startswith(s + "/") for s in SKIP_DIRS):
                continue
            if rel.endswith(SKIP_SUFFIX):
                continue
            yield rel, p


def _docstring_ranges(text: str) -> set[int]:
    """返回 docstring（module/class/function 首条 Expr 字符串）覆盖的行号集合。

    用 ast 而非行级三引号开关：行级开关遇「单行 docstring」或
    「fixture = 三引号字符串字面量」会错位（见 count_net_words.py self_test 实测——
    旧开关把 docstring 正文当代码扫出假阳性）。ast 只认「语句首位的常量字符串」为
    docstring，普通字符串字面量（正则/触发词表/测试夹具）不属于 docstring，仍会被扫描。
    """
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return set()
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if not body:
                continue
            first = body[0]
            if (isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                end = getattr(first, "end_lineno", first.lineno)
                lines.update(range(first.lineno, end + 1))
    return lines


def _iter_code_lines(path: Path):
    """产出 (行号, 行内容) 的「代码/正文」行。.py 跳过 # 注释与 docstring
    （docstring 用 ast 识别，避免单行 docstring / 字符串字面量错位），
    .md 只扫 ``` 代码块内（正文的学科词是「示例/说明」，非判据写死）。"""
    text = path.read_text(encoding="utf-8", errors="ignore")
    if path.suffix == ".py":
        ds = _docstring_ranges(text)
        for lineno, line in enumerate(text.splitlines(), 1):
            if lineno in ds:
                continue
            if line.strip().startswith("#"):
                continue
            yield lineno, line
    elif path.suffix == ".md":
        in_code = False
        for lineno, line in enumerate(text.splitlines(), 1):
            if line.strip().startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                yield lineno, line
    else:
        for lineno, line in enumerate(text.splitlines(), 1):
            yield lineno, line


def check_domain_terms(root: Path) -> tuple[list[dict], list[dict]]:
    """规则①：HARD 词命中 → FAIL 列表；SOFT 词命中 → WARN 列表。"""
    hard_hits, soft_hits = [], []
    for rel, p in _iter_target_files(root):
        for lineno, line in _iter_code_lines(p):
            for term in DOMAIN_TERMS_HARD:
                if term in line:
                    hard_hits.append({"file": rel, "line": lineno, "term": term})
            for term in DOMAIN_TERMS_SOFT:
                if term in line:
                    soft_hits.append({"file": rel, "line": lineno, "term": term})
    return hard_hits, soft_hits


def _iter_audience_lines(path: Path):
    """学段词扫描的行产出器：.md 扫**正文**（学段画像写死在通用行文里，
    与学科词只扫代码块不同——学段常量的病灶恰是正文散文）+ 代码块；
    .py 跳过注释与 docstring（同学科词口径）；.yml/.sh 全行。"""
    text = path.read_text(encoding="utf-8", errors="ignore")
    if path.suffix == ".py":
        ds = _docstring_ranges(text)
        for lineno, line in enumerate(text.splitlines(), 1):
            if lineno in ds:
                continue
            if line.strip().startswith("#"):
                continue
            yield lineno, line
    else:
        # .md 正文与代码块都扫（正文是主战场）；.yml/.sh 全行
        for lineno, line in enumerate(text.splitlines(), 1):
            yield lineno, line


def check_audience_terms(root: Path) -> tuple[list[dict], list[dict]]:
    """规则①b（#71 批次 2）：学段常量词 HARD → FAIL；SOFT → WARN。

    豁免：references/audience-profiles.md（SSOT 本体）与 references/profiles/
    （学段裁剪注记的学科化承载位）；门禁自身文件排除。
    """
    hard_hits, soft_hits = [], []
    for d in AUDIENCE_SCAN_DIRS:
        base = root / d
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or p.suffix not in (".md", ".py", ".sh", ".yml", ".yaml"):
                continue
            rel = p.relative_to(root).as_posix()
            if rel == AUDIENCE_SELF:
                continue
            if any(rel == s or rel.startswith(s if s.endswith("/") else s)
                   for s in AUDIENCE_SKIP_DIRS):
                continue
            for lineno, line in _iter_audience_lines(p):
                for term in AUDIENCE_TERMS_HARD:
                    if term in line:
                        hard_hits.append({"file": rel, "line": lineno, "term": term})
                for term in AUDIENCE_TERMS_SOFT:
                    if term in line:
                        soft_hits.append({"file": rel, "line": lineno, "term": term})
    return hard_hits, soft_hits


def check_paths(root: Path) -> list[dict]:
    """规则②：硬编码绝对路径 → 文件:行号:路径。"""
    hits = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix not in (".md", ".py", ".sh", ".yml", ".yaml", ".json"):
            continue
        # 跳过 vendor 兜底副本（外部依赖，非本包编写）与 .git 与门禁自身
        rel = p.relative_to(root).as_posix()
        if rel.startswith(("vendor/", ".git/", "node_modules/")) or rel == SELF:
            continue
        if p.name in PATH_SKIP_FILES:
            continue
        for lineno, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            for pat in PATH_PATTERNS:
                m = pat.search(line)
                if m:
                    hits.append({"file": rel, "line": lineno, "path": m.group(0)})
                    break
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description="通用层学科中立性 + 路径中立性门禁")
    ap.add_argument("--root", default=".", help="专家包根目录")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = Path(args.root).expanduser()
    hard_hits, soft_hits = check_domain_terms(root)
    aud_hard, aud_soft = check_audience_terms(root)
    path_hits = check_paths(root)

    if args.json:
        print(json.dumps({"hard_hits": hard_hits, "soft_hits": soft_hits,
                          "audience_hard_hits": aud_hard, "audience_soft_hits": aud_soft,
                          "path_hits": path_hits}, ensure_ascii=False, indent=2))
    else:
        print("=" * 62)
        print("通用层学科中立性门禁")
        print("=" * 62)
        if hard_hits:
            print(f"✗ 判据执行体词命中 {len(hard_hits)} 处（应下沉到 profiles/）:")
            for h in hard_hits:
                print(f"    {h['file']}:{h['line']}  词「{h['term']}」")
        else:
            print("✓ 判据执行体词 0 命中")
        if soft_hits:
            print(f"⚠ 机构/法规/学科名示例 {len(soft_hits)} 处（建议下沉，不阻塞）:")
            for h in soft_hits[:20]:
                print(f"    {h['file']}:{h['line']}  词「{h['term']}」")
            if len(soft_hits) > 20:
                print(f"    … 共 {len(soft_hits)} 处")
        if aud_hard:
            print(f"✗ 学段常量词命中 {len(aud_hard)} 处（判据基准 = audience-profiles，通用层禁写死）:")
            for h in aud_hard:
                print(f"    {h['file']}:{h['line']}  词「{h['term']}」")
        else:
            print("✓ 学段常量词（HARD）0 命中")
        if aud_soft:
            print(f"⚠ 学段举例措辞 {len(aud_soft)} 处（建议改引用 audience-profiles，不阻塞）:")
            for h in aud_soft[:20]:
                print(f"    {h['file']}:{h['line']}  词「{h['term']}」")
            if len(aud_soft) > 20:
                print(f"    … 共 {len(aud_soft)} 处")
        if path_hits:
            print(f"✗ 硬编码绝对路径 {len(path_hits)} 处（应用 $EXPERT_DIR 等变量）:")
            for h in path_hits:
                print(f"    {h['file']}:{h['line']}  {h['path']}")
        else:
            print("✓ 硬编码绝对路径 0 命中")
        print("-" * 62)
        n = len(hard_hits) + len(path_hits) + len(aud_hard)
        print(f"FAIL {n} | WARN {len(soft_hits) + len(aud_soft)}")
        print("=" * 62)

    return 1 if (hard_hits or path_hits or aud_hard) else 0


if __name__ == "__main__":
    sys.exit(main())
