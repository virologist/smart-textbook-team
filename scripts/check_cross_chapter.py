#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_cross_chapter.py — 跨章一致性校验器（C10，批次 5）

==============================================================================
为什么需要：单章流程内的校验（审查 R1-R4 / 门禁 3 / 门禁 4）都只看【本章】，
多章成书时三类跨章矛盾无人看守：
  ① 同一术语多种写法（「禽流感」vs「禽流行性感冒」混用）
  ② 数据矛盾（ch01 说发病率 12.5%，ch07 说 21%——同源数据必有一错）
  ③ 内容重复（两章大段复述同一背景，成书后读者跳戏）

用法
------------------------------------------------------------------------------
  python3 scripts/check_cross_chapter.py --work-root "$WORK_ROOT" [--strict] [--json]
  python3 scripts/check_cross_chapter.py --work-root "$WORK_ROOT" \
      --affected-from ch02 --json     # 只重跑 ch02 修订的下游受影响章

  七项跨章检查（B5 六项 + Batch 4 升级 F 第 7 项）：
    ① 术语一致性（改读 profile §5.1 五列表）  ② 数据矛盾（profile §7）
    ③ 内容重复  ④ 难度递进（Bloom 单调不减）  ⑤ 字数分配（±10%）  ⑥ 图号/表号连续
    ⑦ 术语依赖图（exports/imports：下游 imports 必须仍在上游 exports 里）

第 7 项 frontmatter 契约（每章 draft.md）：
  ---
  exports: [T3, T4]                 # 本章新定义、可供下游使用的术语
  imports:
    - term: T1                     # 本章用到、由外章定义的术语
      from: ch02                   # 来源章号（必填）
  ---
  未声明 exports/imports 的章记 WARN（渐进接入，不阻塞）；声明了但缺 from、
  来源章不存在、或上游当前版本已不含该术语 ⇒ FAIL。
  `--affected-from ch##` 按静态 imports 反向边做 BFS 闭包，只校验受影响下游章：
  任何章 PROOFREAD pass 后的联动重跑可直接用这个开关，无需全量重扫。

退出码：0 一致 | 1 存在 FAIL（--strict 时）| 2 输入缺失
==============================================================================
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict, deque
from pathlib import Path

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - 缺依赖时第 7 项报 FAIL，不静默跳过
    yaml = None

from _profile_loader import read_discipline, load_section7, load_term_table


def load_chapters(work_root: Path) -> dict[str, str]:
    """读各章 draft（无 draft 的章跳过）。返回 {ch##: text}。"""
    out: dict[str, str] = {}
    ch_dir = work_root / "章节"
    if not ch_dir.is_dir():
        return out
    for ch in sorted(ch_dir.glob("ch*")):
        d = ch / "draft.md"
        if d.is_file():
            out[ch.name] = d.read_text(encoding="utf-8")
    return out


def strip_code(text: str) -> str:
    """剔除代码块与 frontmatter——那些区域出现「不一致」是正常的（示例/元数据）。"""
    text = re.sub(r"^---\s*\n.*?\n---\s*\n", "", text, flags=re.S)
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    return text


# ── ① 术语一致性 ─────────────────────────────────────────────────────────
def check_terms(chapters: dict[str, str], term_table: list[dict]) -> list[dict]:
    """跨章术语口径（B3/B5 改读 profile §5.1 五列表）。

    旧实现只认 --terms 用户表或括注多写法；现按 profile §5.1 的「标准写法/允许别名/
    禁用写法」三列跨章比对：别名或禁用写法出现在任一章 → 报（应统一为标准写法）。
    term_table 为空 → 退回括注多写法兜底（不改行为，仅少一层学科化）。
    """
    issues = []
    if term_table:
        for row in term_table:
            std = row["std"]
            for alias in row["aliases"] + row["forbidden"]:
                found_in = {ch: alias for ch, text in chapters.items()
                            if alias and alias in strip_code(text)}
                if found_in:
                    issues.append({
                        "type": "术语别名", "term": std,
                        "detail": f"「{alias}」出现在 {sorted(found_in)}，应统一为「{std}」",
                        "severity": "FAIL",
                    })
    else:
        # 无术语表：抓「同一概念多种括注写法」（如 X（Y）与 Y（X）并存）
        paren = re.compile(r"([\u4e00-\u9fff]{2,12})（([A-Za-z][A-Za-z0-9\- ]{1,20})）")
        abbr2std: dict[str, set] = defaultdict(set)
        for text in chapters.values():
            body = strip_code(text)
            for cn, en in paren.findall(body):
                abbr2std[en].add(cn)
        for en, cns in abbr2std.items():
            if len(cns) > 1:
                issues.append({
                    "type": "术语多写法", "term": en,
                    "detail": f"同一英文缩写被标注为多个中文名 {sorted(cns)}——必有一处不规范",
                    "severity": "WARN",
                })
    return issues


# ── ② 数据矛盾 ───────────────────────────────────────────────────────────
def check_data_conflicts(chapters: dict[str, str],
                         metrics: list[str] | None = None) -> list[dict]:
    """同一「指标+对象」在不同章给出不同数值。

    口径：只比对带 [实] 标签的数值陈述（有标签才算断言；未标数据由单章流程管）。
    B3（ADR-02）：指标正则从写死的兽医词表改为读 profile §7 conflict_metrics，
    非兽医学科（计算机/法学）的跨章数值矛盾不再漏检；metrics 为空 → 返回空（N/A）。
    """
    if not metrics:
        return []
    issues = []
    # 「{对象} 的 {指标} 为/约/达 {数值}{单位}」
    # P3-7 实战修正（2026-11-01）：对象名此前限定为纯汉字 `[\u4e00-\u9fff]{2,10}`，
    # 而教材里的指标几乎都挂在**病原/毒株名**上（H9N2、H5N1、E. coli、PRRSV），
    # 全是 ASCII → 真实稿件里最该被抓的一类矛盾**永远不命中**（实测 ch01 1% vs ch02 25%
    # 双章 [实] 断言，检测器 FAIL 0 静默放过）。现对象允许字母数字与连字符。
    metric_alt = "|".join(re.escape(m) for m in metrics)
    pat = re.compile(
        rf"([A-Za-z0-9\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff\- .]{{1,14}}?)"
        rf"的(?:{metric_alt})"
        r"[约为达高达]*\s*(\d+(?:\.\d+)?)\s*[%％][^\n]*?\[实\]")
    claims: dict[tuple, list] = defaultdict(list)
    for ch, text in chapters.items():
        body = strip_code(text)
        for obj, num in pat.findall(body):
            claims[(obj.strip(),)].append((ch, num))
    for (obj,), lst in claims.items():
        nums = {n for _, n in lst}
        if len(nums) > 1:
            issues.append({
                "type": "数据矛盾", "term": obj,
                "detail": f"「{obj}」同指标多章数值不一: {lst}（同源数据必有一错，须回溯检索摘要定对错）",
                "severity": "FAIL",
            })
    return issues


# ── ③ 内容重复 ───────────────────────────────────────────────────────────
def check_duplication(chapters: dict[str, str], min_len: int = 60) -> list[dict]:
    """跨章 ≥N 字的相同句串（按句切，两句连续相同即报）。"""
    issues = []
    sents: dict[str, list[str]] = {}
    for ch, text in chapters.items():
        body = strip_code(text)
        body = re.sub(r"\[(?:实|估|引|待核实)[^\]]*\]", "", body)
        sents[ch] = [s.strip() for s in re.split(r"[。！？\n]", body)
                     if len(s.strip()) >= min_len]
    chs = sorted(sents)
    for i, a in enumerate(chs):
        for b in chs[i + 1:]:
            common = set(sents[a]) & set(sents[b])
            if common:
                sample = sorted(common)[0][:40]
                issues.append({
                    "type": "内容重复",
                    "term": f"{a} ↔ {b}",
                    "detail": f"{len(common)} 个长句完全相同（如「{sample}…」）——成书后读者跳戏，建议改写其一",
                    "severity": "WARN",
                })
    return issues


def load_book_spec(work_root: Path) -> list[dict]:
    """读 book-spec.md 的 chapters 列表 → [{id, word_budget, difficulty, domain}]。"""
    spec = work_root / "运行态" / "book-spec.md"
    if not spec.is_file():
        return []
    txt = spec.read_text(encoding="utf-8")
    rows = []
    for m in re.finditer(
            r'^\s*- id: (\S+)\n\s*word_budget: (\d+)\n\s*difficulty: (\S*)\n\s*domain: (.*)$',
            txt, re.M):
        rows.append({"id": m.group(1), "word_budget": int(m.group(2)),
                     "difficulty": m.group(3).strip(), "domain": m.group(4).strip()})
    return rows


# ── ④ 难度递进 ───────────────────────────────────────────────────────────
def check_difficulty_progression(spec: list[dict]) -> list[dict]:
    """各章难度梯度单调不减（L1 ≤ L2 ≤ L3）；缺难度的章跳过（N/A，不阻塞）。"""
    if len(spec) < 2:
        return []
    order = {"L1": 1, "L2": 2, "L3": 3}
    issues = []
    prev_lv, prev_ch, prev_d = 0, None, None
    for row in spec:
        d = (row["difficulty"] or "").upper()
        if d not in order:
            continue
        lv = order[d]
        if prev_ch is not None and lv < prev_lv:
            issues.append({
                "type": "难度递进", "term": f"{prev_ch} → {row['id']}",
                "detail": f"难度回落（{prev_ch}={prev_d} → {row['id']}={d}），Bloom 层级应单调不减",
                "severity": "WARN",
            })
        prev_lv, prev_ch, prev_d = lv, row["id"], d
    return issues


# ── ⑤ 字数分配 ───────────────────────────────────────────────────────────
def check_word_budget(work_root: Path, spec: list[dict],
                      chapters: dict[str, str]) -> list[dict]:
    """各章实际净字数 vs 预算 ±10%（B5 新增）。预算 0 / 章无 draft → 跳过。"""
    if not spec:
        return []
    issues = []
    for row in spec:
        budget = row["word_budget"]
        if not budget:
            continue
        ch = row["id"]
        text = chapters.get(ch)
        if text is None:
            continue
        try:
            import count_net_words
            actual = count_net_words.count_net_words(text)["net_final"]
        except Exception:
            actual = 0
        if not actual:
            continue
        dev = abs(actual - budget) / budget
        if dev > 0.10:
            issues.append({
                "type": "字数分配", "term": ch,
                "detail": f"实际 {actual} 字 vs 预算 {budget} 字（偏差 {dev:.1%} > 10%）",
                "severity": "WARN",
            })
    return issues


# ── ⑥ 图号/表号全书连续性 ────────────────────────────────────────────────
def check_figure_continuity(chapters: dict[str, str]) -> list[dict]:
    """各章图号 / 表号（「图 X-Y」/「表 X-Y」）的 Y 序应连续无跳号。"""
    issues = []
    for ch, text in chapters.items():
        body = strip_code(text)
        for kind in ("图", "表"):
            nums = sorted({int(m.group(1)) for m in re.finditer(
                rf"{kind}\s*\d+-\s*(\d+)", body)})
            if not nums:
                continue
            expect = list(range(1, nums[-1] + 1))
            missing = [n for n in expect if n not in nums]
            if missing:
                issues.append({
                    "type": "图号连续性" if kind == "图" else "表号连续性",
                    "term": ch,
                    "detail": f"{ch} {kind}号跳号：缺 {missing}（全书 {kind}号应连续）",
                    "severity": "WARN",
                })
    return issues


# ── ⑦ 术语依赖图（Batch 4 升级 F / Q6）────────────────────────────────────
RE_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


def parse_dependency_frontmatter(text: str) -> dict:
    """解析单章 draft frontmatter 的 exports / imports。

    不静默：YAML 不可用或结构非法都写进 parse_error，由检查函数升级为 FAIL。
    """
    m = RE_FRONTMATTER.match(text)
    if not m:
        return {'declared': False, 'exports': [], 'imports': [],
                'parse_error': None, 'reason': '无 frontmatter'}
    if yaml is None:
        return {'declared': False, 'exports': [], 'imports': [],
                'parse_error': 'PyYAML 不可用，无法解析 exports/imports（不静默跳过）',
                'reason': ''}
    try:
        data = yaml.safe_load(m.group(1)) or {}
    except Exception as e:  # yaml.YAMLError 及其子类
        return {'declared': False, 'exports': [], 'imports': [],
                'parse_error': f'frontmatter YAML 非法: {e}', 'reason': ''}
    if not isinstance(data, dict):
        return {'declared': False, 'exports': [], 'imports': [],
                'parse_error': 'frontmatter 不是映射结构', 'reason': ''}
    exports = [str(x).strip() for x in (data.get('exports') or [])
               if str(x).strip()]
    imports: list[dict] = []
    for it in (data.get('imports') or []):
        if isinstance(it, dict):
            imports.append({'term': str(it.get('term') or '').strip(),
                            'from': str(it.get('from') or '').strip()})
        else:
            # 简写（只有术语名、无来源章）不允许：来源章是依赖图的边，缺失即无法算闭包
            imports.append({'term': str(it).strip(), 'from': ''})
    return {
        'declared': ('exports' in data) or ('imports' in data),
        'exports': exports, 'imports': imports,
        'parse_error': None, 'reason': '',
    }


def dependency_closure(deps: dict[str, dict], source: str) -> list[str]:
    """由 imports 反向边做 BFS：返回 source 修订后受影响的下游章（不含 source）。"""
    reverse: dict[str, list[str]] = defaultdict(list)
    for ch, d in deps.items():
        for item in d['imports']:
            if item['from']:
                reverse[item['from']].append(ch)
    affected: list[str] = []
    seen = {source}
    q = deque([source])
    while q:
        cur = q.popleft()
        for nxt in reverse.get(cur, []):
            if nxt not in seen:
                seen.add(nxt)
                affected.append(nxt)
                q.append(nxt)
    return sorted(affected)


def check_term_dependency_graph(chapters: dict[str, str],
                                affected_from: str | None = None
                                ) -> tuple[list[dict], dict]:
    """第 7 项：imports ⊆ 上游 exports；可只校验指定章修订的下游闭包。

    返回 (issues, meta)；meta 供 JSON 输出披露受影响章与依赖图摘要。
    """
    issues: list[dict] = []
    deps = {ch: parse_dependency_frontmatter(t) for ch, t in chapters.items()}

    for ch, d in deps.items():
        if d['parse_error']:
            issues.append({
                'type': '术语依赖图', 'term': ch,
                'detail': f'{ch}: {d["parse_error"]}', 'severity': 'FAIL',
            })
        elif not d['declared']:
            issues.append({
                'type': '术语依赖图', 'term': ch,
                'detail': (f'{ch} 未声明 exports/imports——渐进接入期记 WARN；'
                           f'声明后即可获得上游修订联动校验'),
                'severity': 'WARN',
            })

    affected = None
    if affected_from:
        affected = dependency_closure(deps, affected_from)
        if affected_from not in chapters and not affected:
            issues.append({
                'type': '术语依赖图', 'term': affected_from,
                'detail': f'--affected-from {affected_from} 既非现存章、也无下游依赖'
                          f'（无可校验目标，不得报「全通过」）',
                'severity': 'FAIL',
            })

    for ch, d in deps.items():
        if affected is not None and ch not in affected:
            continue
        for item in d['imports']:
            term, src = item['term'], item['from']
            if not term or not src:
                issues.append({
                    'type': '术语依赖图', 'term': ch,
                    'detail': f'{ch} imports 项缺 term/from: {item}'
                              f'（来源章号是依赖图的边，必填）',
                    'severity': 'FAIL',
                })
            elif src not in deps:
                issues.append({
                    'type': '术语依赖图', 'term': ch,
                    'detail': f'{ch} imports 的 {term} 标注来源 {src}，'
                              f'但 {src} 无 draft.md（来源章不存在或尚未产出）',
                    'severity': 'FAIL',
                })
            elif term not in deps[src]['exports']:
                issues.append({
                    'type': '术语依赖图', 'term': ch,
                    'detail': f'{ch} imports 的 {term} 已不在 {src} 的 exports 里'
                              f'（上游删除/改名 ⇒ 下游术语失配）',
                    'severity': 'FAIL',
                })

    meta = {
        'check': 7,
        'affected_from': affected_from,
        'affected_chapters': affected,
        'declared_chapters': sorted(ch for ch, d in deps.items() if d['declared']),
        'undeclared_chapters': sorted(ch for ch, d in deps.items() if not d['declared']),
        'exports': {ch: d['exports'] for ch, d in deps.items()},
        'imports': {ch: d['imports'] for ch, d in deps.items()},
    }
    return issues, meta


def main() -> int:
    ap = argparse.ArgumentParser(description="跨章一致性校验器（术语/数据/重复/难度/字数/图号/术语依赖图）")
    ap.add_argument("--work-root", required=True)
    ap.add_argument("--strict", action="store_true", help="存在 FAIL 即 exit 1")
    ap.add_argument("--affected-from", default='',
                    help="只重跑该章修订的下游受影响章（第 7 项静态依赖闭包，如 ch02）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    work_root = Path(args.work_root).expanduser()
    chapters = load_chapters(work_root)
    if len(chapters) < 2:
        print(f"[WARN] 有效章节 {len(chapters)} 章（<2）——跨章校验需要 ≥2 章 draft，跳过",
              file=sys.stderr)
        return 0

    _discipline = read_discipline(work_root)
    _metrics = load_section7(work_root, _discipline, "conflict_metrics")
    _terms = load_term_table(work_root, _discipline)
    _spec = load_book_spec(work_root)
    dep_issues, dep_meta = check_term_dependency_graph(
        chapters, args.affected_from or None)
    issues = (check_terms(chapters, _terms)
              + check_data_conflicts(chapters, _metrics)
              + check_duplication(chapters)
              + check_difficulty_progression(_spec)
              + check_word_budget(work_root, _spec, chapters)
              + check_figure_continuity(chapters)
              + dep_issues)

    if args.json:
        print(json.dumps({"chapters": sorted(chapters), "issues": issues,
                          "term_dependency": dep_meta},
                         ensure_ascii=False, indent=2))
    else:
        print("=" * 62)
        print(f"跨章一致性校验 | 章节: {', '.join(sorted(chapters))}")
        print("=" * 62)
        if not issues:
            print("  ✓ 未发现跨章矛盾")
        for i in issues:
            mark = "✗" if i["severity"] == "FAIL" else "⚠"
            print(f"  {mark} [{i['type']}] {i['term']}")
            print(f"      → {i['detail']}")
        n_fail = sum(1 for i in issues if i["severity"] == "FAIL")
        print("-" * 62)
        print(f"FAIL {n_fail} | WARN {len(issues) - n_fail}")
        print("=" * 62)

    if args.strict and any(i["severity"] == "FAIL" for i in issues):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
