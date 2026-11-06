#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_doc_consistency.py — 文档计数/量纲/编号/归属一致性门禁（P2 批次，2026-11-04）

==============================================================================
背景（2026-11-04 系统性诊断的 P2 批次）
------------------------------------------------------------------------------
包内存在一类**低烈度但会持续累积**的漂移：文档里复述了 SSOT 的**数字**
（枚举几类、评分阈值多少、用例多少条），SSOT 改了而复述处没改 → 两边对不上。
这类漂移不会让流水线报错，但会让审计者按旧数字做决策（如「12 类 task_type」
让人以为 router 只覆盖 12 类），且**永远无人报警**——CI 里没有任何一条断言
守着它们。

与既有 `check_phase_consistency.py` 的分工：
  · check_phase_consistency 守「相位字面量」这一类（枚举值本身）
  · 本脚本守「**引用计数与量纲**」这一类（枚举的个数、阈值的数值、编号序列）

六条判据
------------------------------------------------------------------------------
  D1  task_type 计数一致：文档声明的「N 类 task_type」必须等于
      `skills/task-router/SKILL.md` §1 表实际行数（SSOT 解析，非硬编码）。
  D2  置信度量纲一致：全包不得出现 0-1 量纲的置信度阈值写法
      （`confidence < 0.7` / `routing_confidence ≥ 0.7`）——当前量纲是 0-100
      （与 harness §1 信封 `confidence: 0-100` 同源），旧写法是量纲撕裂。
  D3  编号序列连续：markdown 有序列表 `1. 2. 3.` 不得出现**同级重复编号**
      （两个「6.」）——重复编号会让渲染器静默重排，读者以为漏了一条。
  D4  列表标记格式：不得出现 `.- ` 这类残缺标记（应为 `- `）。
  D5  路径归属唯一：同一文件扩展名不得在 path-ownership 表中出现**两次**
      （两个归属者 = 并行安全条款「路径表唯一归属」直接失效）。
      唯一例外是显式标注「双写者」并给出仲裁规则的路径（当前：`{图号}.png`）。
  D6  路径无主：path-ownership 表中出现的**扩展名**必须在表内有归属行，
      不允许「表里提到但无归属」（如 `.pdf` 被删归属后成为无主路径）。

免检通道
------------------------------------------------------------------------------
  · 文件级：`CHANGELOG.md` / `skills/SKILL_CHANGELOG.md`（追加式历史流水，
    照抄旧数字是证据要求，改它等于篡改历史）
  · 行级：含 `doc-consistency:ignore` 的行

用法
------------------------------------------------------------------------------
  python3 scripts/check_doc_consistency.py --root . [--verbose] [--json]

退出码
------------------------------------------------------------------------------
  0 一致 | 1 发现不一致 | 2 权威源不可用或判据自身失效
==============================================================================
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# 扫描范围：包内全部 markdown（不含 vendor/ 与 .git/）
SCAN_DIRS = ("agents", "skills", "references", "scripts")
SCAN_FILES = ("README.md", "CONTRIBUTING.md", "AGENTS.md")
# 历史流水文件：照抄旧数字是证据要求，不参与判据
IMMUNE_FILES = ("CHANGELOG.md", "SKILL_CHANGELOG.md")
IGNORE_MARK = "doc-consistency:ignore"

# ── D1：task_type 计数 ────────────────────────────────────────────────────
# 形态有多种：「13 类 task_type」「task_type（15 类）」「…等 15 类」「15-type routing」。
# 共同点：**所在行提到 task_type（或 task-router N-type）** + 该行出现一个「N 类 / N-type」数字。
# 故判据改为「行内触发词 + 行内计数」的组合，而非固定词序。
RE_TT_TRIGGER = re.compile(r"\btask_type\b|task-router\b|task router\b", re.I)
RE_TT_COUNT = re.compile(r"(\d+)\s*(?:类|种|-type\b)")
RE_TT_COUNT_ALT = re.compile(r"(\d+)\s*类\s*task_type")

# ── D2：置信度 0-1 量纲残留 ───────────────────────────────────────────────
# 只匹配「阈值比较 + 0-1 小数」这一形态，避免误伤正文里普通的 0.7
RE_CONF_01 = re.compile(
    r"(?:confidence|置信度|routing_confidence|路由置信度)\s*"
    r"(?:≥|>=|<|<=|>|<|=|为|：|:)\s*0\.[0-9]+"
)

# 语义组合式：路由/评分上下文词 + 0-1 小数阈值（不含显式 confidence 字样）
RE_CONF_CTX = re.compile(
    r"(?:走升级|升级规则|总分|评分)"
    r"[^\n]{0,12}?(?:≥|>=|<|<=|>|=|为)\s*0\.[0-9]+"
)

# ── D3：有序列表同级重复编号 ──────────────────────────────────────────────
RE_OL_ITEM = re.compile(r"^(\s*)(\d+)\.\s+\S")

# ── D5/D6：path-ownership 归属表解析 ─────────────────────────────────────
RE_OWN_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|")


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


def _iter_md(root: Path):
    """产出 (相对路径, 全文) —— 跳过免疫文件与 vendor/.git。"""
    for d in SCAN_DIRS:
        base = root / d
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.md")):
            if p.name in IMMUNE_FILES or "vendor" in p.parts:
                continue
            yield str(p.relative_to(root)), _read(p)
    for f in SCAN_FILES:
        p = root / f
        if p.is_file():
            yield f, _read(p)


def _lines_with_no_ignore(text: str):
    """产出 (行号(1-based), 行文本)，跳过免疫标记行与代码块内的行。"""
    in_fence = False
    for i, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if IGNORE_MARK in line:
            continue
        yield i, line


# ── SSOT 解析：task-router §1 表的 task_type 个数 ─────────────────────────
def parse_task_type_count(root: Path):
    """从 skills/task-router/SKILL.md §1 表解析 task_type 数量。

    返回 (count, table_rows) —— 解析失败返回 (None, [])。
    刻意**不复述**枚举值：只数 §1 表里 `` `task_type` `` 形态的行。
    """
    p = root / "skills" / "task-router" / "SKILL.md"
    if not p.is_file():
        return None, []
    text = _read(p)
    if "## 1. task_type" not in text:
        return None, []
    sec = text.split("## 1. task_type", 1)[1]
    # 到下一个二级标题为止
    m = re.search(r"\n## ", sec)
    if m:
        sec = sec[:m.start()]
    types = re.findall(r"^\|\s*`([a-z][a-z0-9\-]*)`\s*\|", sec, re.M)
    return len(types), types


def check(root: Path, verbose: bool = False):
    items = []          # (id, desc, ok, detail)
    notes = []

    def add(cid, desc, ok, detail=""):
        items.append((cid, desc, bool(ok), detail if not ok else ""))

    # ── D1：task_type 计数 ────────────────────────────────────────────────
    tt_count, tt_types = parse_task_type_count(root)
    if not tt_count:
        add("D1", "task_type 计数一致（文档声明 == router §1 表实际行数）", False,
            "无法解析 skills/task-router/SKILL.md §1 表——权威源不可用，判据失效")
    else:
        bad = []
        for rel, text in _iter_md(root):
            for ln, line in _lines_with_no_ignore(text):
                if not RE_TT_TRIGGER.search(line):
                    continue
                # 该行所有「N 类 / N-type」计数都应是 task_type 计数
                for m in list(RE_TT_COUNT.finditer(line)) + list(RE_TT_COUNT_ALT.finditer(line)):
                    claimed = int(m.group(1))
                    if claimed != tt_count:
                        bad.append(f"{rel}:{ln} 声明 {claimed} 类，实际 {tt_count} 类")
        add("D1", f"task_type 计数一致（文档声明 == router §1 表实际 {tt_count} 类）",
            not bad, "; ".join(bad[:8]))
        notes.append(f"router §1 解析出 {tt_count} 类：{', '.join(tt_types)}")

    # ── D2：置信度量纲 ────────────────────────────────────────────────────
    bad = []
    for rel, text in _iter_md(root):
        for ln, line in _lines_with_no_ignore(text):
            if RE_CONF_01.search(line) or RE_CONF_CTX.search(line):
                bad.append(f"{rel}:{ln} 仍用 0-1 量纲：{line.strip()[:60]}")
    add("D2", "置信度量纲一致（0-100，不得残留 0-1 阈值写法）",
        not bad, "; ".join(bad[:8]))

    # ── D3：有序列表同级重复编号 ──────────────────────────────────────────
    bad = []
    for rel, text in _iter_md(root):
        prev_num = None
        prev_indent = None
        for ln, line in _lines_with_no_ignore(text):
            m = RE_OL_ITEM.match(line)
            if not m:
                # 非列表项 → 断开序列
                if line.strip() and not line.startswith(" ") and not line.strip().startswith(">"):
                    prev_num, prev_indent = None, None
                continue
            indent, num = len(m.group(1)), int(m.group(2))
            if prev_num is not None and num == prev_num and indent == prev_indent:
                bad.append(f"{rel}:{ln} 编号 {num}. 与同级上一项重复")
            prev_num, prev_indent = num, indent
    add("D3", "有序列表编号连续（同级不得重复编号）",
        not bad, "; ".join(bad[:8]))

    # ── D4：残缺列表标记 ──────────────────────────────────────────────────
    bad = []
    for rel, text in _iter_md(root):
        for ln, line in _lines_with_no_ignore(text):
            if re.match(r"^\s*\.\-\s+", line):
                bad.append(f"{rel}:{ln} 残缺列表标记 `.-`")
    add("D4", "列表标记格式正确（不得出现 `.- `）",
        not bad, "; ".join(bad[:8]))

    # ── D5/D6：path-ownership 归属唯一性与无主路径 ────────────────────────
    po = root / "references" / "path-ownership.md"
    if not po.is_file():
        add("D5", "path-ownership 表扩展名归属唯一", False,
            "references/path-ownership.md 不存在——无法校验")
        add("D6", "path-ownership 表内扩展名均有归属行", False,
            "references/path-ownership.md 不存在——无法校验")
    else:
        text = _read(po)
        rows = []
        for ln, line in enumerate(text.splitlines(), 1):
            m = RE_OWN_ROW.match(line.strip())
            if not m:
                continue
            path_cell, owner, action, others = m.group(1), m.group(2), m.group(3), m.group(4)
            rows.append((ln, path_cell, owner, action, others))

        # 提取每行声明的扩展名
        ext_owner = {}      # ext -> [(line, owner)]
        for ln, path_cell, owner, action, others in rows:
            exts = set(re.findall(r"\.([A-Za-z0-9]+)", path_cell))
            for e in exts:
                ext_owner.setdefault(e, []).append((ln, owner, path_cell))

        # D5：同一**路径模式**被多个**不同归属者**声明 → 冲突。
        #     注意：判据按路径模式（归一化掉 {ch##} / {图号} / {节号} 等占位符）
        #     而非按扩展名——`章节/{ch##}/draft.md` 与 `章节/{ch##}/gaps.md`
        #     扩展名都是 .md 但归属不同（writer / architect），不是冲突。
        #     真冲突的形态是：同一路径模式（如 `figures/assets/{图号}.svg`）
        #     同时被两个归属者声明。
        def _pattern(path_cell: str) -> str:
            """把路径归一化成可比形态：占位符统一 + 扩展名保留。"""
            p = path_cell.strip().strip("`")
            p = re.sub(r"\{[^}]*\}", "{*}", p)
            return p

        pat_owner = {}
        for ln, path_cell, owner, action, others in rows:
            pat_owner.setdefault(_pattern(path_cell), []).append((ln, owner, path_cell))

        conflicts = []
        for pat, lst in sorted(pat_owner.items()):
            owners = {o for _, o, _ in lst}
            if len(owners) > 1:
                # 例外：显式标注「双写者」且给出仲裁规则的路径
                if all("双写者" in o for _, o, _ in lst):
                    continue
                conflicts.append(
                    f"路径模式 `{pat}` 有 {len(owners)} 个归属者：" +
                    "; ".join(f"L{ln} {o[:40]}" for ln, o, _ in lst))

        # D5b：**同一目录 + 同一文件名主干 + 同一扩展名**被两个归属者声明 → 冲突。
        #     这正是修复前的历史病灶形态：`figures/assets/{图号}.mmd/.svg`
        #     （designer）与 `figures/assets/{图号}.png/.svg`（team-lead）
        #     —— 路径模式不同（一个 .mmd 一个 .png），但**都在 assets/ 目录下
        #     都声明了 .svg** → 同一个 `{图号}.svg` 两个写者。
        #
        #     关键约束：**必须落到同一个具体文件名**才算冲突。
        #     同目录下不同文件名的两个扩展名（`章节/{ch##}/draft.md` 归 writer
        #     vs `章节/{ch##}/chapter_design.md` 归 architect）是合法的。
        #
        #     实现要点（实测踩坑两次）：
        #       ① 多扩展名连写 `{图号}.mmd/.svg` 必须**先剥扩展名再切目录**，
        #          否则末段会被斜杠切成 `.svg`，目录也错位；
        #       ② 目录与主干必须**共用同一个归一化路径**，
        #          否则 dir 取自原串、stem 取自剥过的串，两边对不上。
        def _split_path(path_cell: str):
            """归一化路径 → (目录, 文件名主干)。

            实现要点（实测踩坑三次，全部在「多扩展名连写」这一形态上）：
              ① `{图号}.mmd/.svg` 里含斜杠，**先按 `/` 切末段会切错**——
                 末段变成 `.svg`，主干丢失 `{图号}`；
              ② 正确顺序：先把路径里**所有** `.ext` 片段（连同其前的斜杠）剥掉，
                 得到「纯路径 + 纯文件名」；
              ③ 再切目录。目录与主干必须共用同一份归一化结果，
                 否则两边对不上（聚合键错位 → 冲突检测形同虚设）。

            例：`章节/{ch##}/figures/assets/{图号}.mmd/.svg`
              → 剥扩展名片段 → `章节/{ch##}/figures/assets/{图号}`
              → dir=`章节/{*}/figures/assets`，stem=`{*}`

            ★H3 修正（v2.10.1，真实误伤驱动）：**复合双扩展名是不同文件名**。
              `sections/{节号}.md`（writer 节稿）与 `sections/{节号}.verdict.md`
              （examiner 节审 verdict）是**两个不同文件**——归一化后若都剥成
              `sections/{*}` + ext=md，会把合法的双归属误判为冲突。
              修正：剥扩展名前**先保留首个扩展名到主干**——即把
              `.verdict.md` 视为「主干 `{节号}.verdict` + 扩展名 md」，
              而非「主干 `{节号}` + 扩展名 verdict+md 连写」。
              判别规则（正则见下，名字段为实义词）→ 主干含该复合后缀；
              裸连写（`.mmd/.svg` 斜杠分隔）仍按多扩展名剥。
            """
            p = path_cell.strip().strip("`")
            p = re.sub(r"\{[^}]*\}", "{*}", p)          # ★先归一占位符，正则才匹配到 {N}/{节号}
            # ★H3：复合双扩展名（`{N}.verdict.md` 形态）→ 主干保留 `.verdict`
            m = re.search(r"/([^/]+)\.(verdict|report|revisions|score|log)\.(md|json)$", p)
            if m:
                stem_full = m.group(1) + "." + m.group(2)
                d = p[: m.start()]
            else:
                # 剥掉所有扩展名片段：`.ext` 或 `/.ext`（连写形式）
                p2 = re.sub(r"(?:/)?\.[A-Za-z0-9]+", "", p)
                if "/" in p2:
                    d, stem_full = p2.rsplit("/", 1)
                else:
                    d, stem_full = "", p2
            return d, stem_full

        dir_ext_owner = {}
        for ln, path_cell, owner, action, others in rows:
            d, stem = _split_path(path_cell)
            for e in set(re.findall(r"\.([A-Za-z0-9]+)", path_cell)):
                dir_ext_owner.setdefault((d, stem, e), []).append((ln, owner, path_cell))

        for (d, stem, e), lst in sorted(dir_ext_owner.items()):
            owners = {o for _, o, _ in lst}
            if len(owners) > 1:
                if all("双写者" in o for _, o, _ in lst):
                    continue
                conflicts.append(
                    f"文件 `{d}/{stem}.{e}` 有 {len(owners)} 个归属者：" +
                    "; ".join(f"L{ln} {o[:36]}" for ln, o, _ in lst))

        add("D5", "path-ownership 表归属唯一（同路径模式 / 同文件不得有两个归属者）",
            not conflicts, "; ".join(conflicts[:8]))

        # D6：表内被提及但无归属行的**资产扩展名**
        #     判据：正文（§1-§2 表格区）提到的扩展名必须能在归属行里找到；
        #     变更记录是历史叙述，按定义可提旧名 → 排除。
        notes_po = []
        body = text.split("## 3. 资源冲突仲裁")[0]
        body = re.sub(r"```.*?```", "", body, flags=re.S)      # 去掉代码块
        body = re.sub(r"^>.*$", "", body, flags=re.M)            # 去掉引用块
        # 归属行覆盖到的扩展名
        owned_exts = set(ext_owner.keys())
        mentioned = set(re.findall(r"\.([A-Za-z0-9]+)", body))
        # 非资产类扩展名（文档/配置/代码类，本就不在图表资产归属范围内）
        NON_ASSET = {
            "md", "yaml", "yml", "json", "py", "sh", "ps1", "txt", "csv",
            "ipynb_placeholder",
        }
        for e in sorted(mentioned - owned_exts - NON_ASSET):
            # 排除版本号/小数误匹配（如 §4.1 里的 ".1"）
            if e.isdigit() or len(e) < 2:
                continue
            notes_po.append(f".{e} 在表中被提及但无归属行")
        add("D6", "path-ownership 表内提及的资产扩展名均有归属行（无无主路径）",
            not notes_po, "; ".join(notes_po[:8]))

    # ── D7：task_type_required 键 ⊆ router §1 枚举 + 工具总表锚计分（★I-2 v2.10.2）──
    # 缺口（第四轮扫描实证）：H2 增的条件产物映射键若与 task-router §1 枚举漂移，
    # contract_check --task-type 会静默判 UNKNOWN_TASK_TYPE（或漏判）⇒ 机械拦截。
    # 另：G5 声明的「总表 vs 成员 MD 一致性计分」此前只在文档，本判据落地。
    try:
        bad_d7 = []
        router_count, router_types = parse_task_type_count(root)
        contracts_p = root / "references" / "member-contracts.json"
        if not contracts_p.is_file():
            bad_d7.append("references/member-contracts.json 不存在——判据失效")
        else:
            try:
                cdata = json.loads(contracts_p.read_text(encoding="utf-8"))
                for mname, mc in (cdata.get("members") or {}).items():
                    for tt in (mc.get("task_type_required") or {}):
                        if router_types and tt not in router_types:
                            bad_d7.append(
                                f"member {mname} 的 task_type_required 键 {tt!r} "
                                f"不在 router §1 枚举内（{len(router_types)} 类）")
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                bad_d7.append(f"契约 JSON 解析失败: {e}")
        # C-TOOL：工具编排总表锚——scout/examiner MD 必须含引用行
        to = root / "references" / "tool-orchestration.md"
        if not to.is_file():
            bad_d7.append("references/tool-orchestration.md 缺失（G5 SSOT）")
        else:
            for member_rel, need in (
                    ("agents/literature-scout.md", "L1"),
                    ("agents/quality-examiner.md", "L3"),
            ):
                mp = root / member_rel
                if mp.is_file():
                    mt = mp.read_text(encoding="utf-8")
                    if "tool-orchestration.md" not in mt:
                        bad_d7.append(f"{member_rel} 缺工具编排总表锚引用行")
                    elif need not in mt:
                        bad_d7.append(f"{member_rel} 总表锚未含 {need} 行引用")
        add("D7", "task_type_required ⊆ router 枚举 + 工具总表锚齐备（★I-2）",
            not bad_d7, "; ".join(bad_d7[:8]))
    except Exception as e:  # 判据自身崩 → 显式失败，不静默
        add("D7", "task_type_required ⊆ router 枚举 + 工具总表锚齐备（★I-2）",
            False, f"判据执行异常: {e}")

    failed = [i for i in items if not i[2]]
    return items, failed, notes


def emit(items, failed, notes, as_json, verbose):
    if as_json:
        print(json.dumps({
            "total": len(items),
            "failed": len(failed),
            "items": [{"id": i[0], "desc": i[1], "pass": i[2], "detail": i[3]}
                      for i in items],
            "notes": notes,
        }, ensure_ascii=False, indent=2))
    else:
        print("=" * 64)
        print("文档一致性门禁（计数 / 量纲 / 编号 / 归属）")
        print("=" * 64)
        for cid, desc, ok, detail in items:
            print(f"  {'✓' if ok else '✗'} [{cid}] {desc}")
            if detail:
                for part in detail.split("; "):
                    print(f"          → {part}")
        if verbose:
            for n in notes:
                print(f"  · {n}")
        print("-" * 64)
        print(f"检查项 {len(items)} | 通过 {len(items) - len(failed)} | 失败 {len(failed)}")
        print("=" * 64)
    return 0 if not failed else 1


def main():
    ap = argparse.ArgumentParser(description="文档计数/量纲/编号/归属一致性门禁")
    ap.add_argument("--root", default=".")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"根目录不存在: {root}", file=sys.stderr)
        return 2
    items, failed, notes = check(root, verbose=args.verbose)
    return emit(items, failed, notes, args.json, args.verbose)


if __name__ == "__main__":
    sys.exit(main())
