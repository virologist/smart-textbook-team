#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""merge_sections.py — 超上下文拆分-合并链路（Q3 落地，2026-11-04 P1）

==============================================================================
为什么有这个脚本（Q3 授权原文）
------------------------------------------------------------------------------
  「单章 token 不受限；如果超过单次 AI 的上下文限度，则拆分分别执行完成后再合并
    检查和校队/润色修改，确保上下文连贯和衔接。」

拆开看是三个动作：
  ① 拆分：单章超出单次上下文 → 按节拆成多次执行
  ② 合并：多次执行的产出 → 合并为整章
  ③ **合并后必须走检查/校对/润色**（不得直接进装配）

关键约束（易错点）：**③ 是硬性的**。
`assemble_sections.py` 只做「节级自查 + 拼接 + 拼接清单」，它保证的是
「节内部合规」；**节与节之间的衔接**（术语一致、图表位连续、数据口径不冲突、
段落过渡不突兀）只有整章视角才能看出来。
故本脚本在拼接后**强制**生成一份「合并后必检清单」，并把它转成
**可机械核对的整章门禁项**——不通过就不许进 ASSEMBLE。

与既有脚本的分工
------------------------------------------------------------------------------
  assemble_sections.py  → 节级自查 + 拼接 + 拼接清单（节内视角）
  merge_sections.py（本）→ 合并后衔接检查 + 整章必检清单 + 合并溯源（章间视角）

退出码
------------------------------------------------------------------------------
  0  合并完成且合并后必检清单已生成（可进 VERIFY-R3）
  1  合并后必检未过（衔接问题 / 缺节 / 重复节）——不得进 VERIFY-R3
  2  输入缺失（sections/ 不存在 / 为空）
  3  前置未满足（已有未处理的合并冲突标记）

用法
------------------------------------------------------------------------------
  # 合并 + 生成必检清单
  python3 scripts/merge_sections.py --work-root "$WORK_ROOT" --chapter ch01

  # 只检查已有 draft.md 的衔接（不重新合并）
  python3 scripts/merge_sections.py --work-root "$WORK_ROOT" --chapter ch01 --check-only

  # 指定合并后的下游相位（默认 VERIFY-R3）
  python3 scripts/merge_sections.py --work-root "$WORK_ROOT" --chapter ch01 \\
      --downstream VERIFY-R3
==============================================================================
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

RE_SECTION_FILE = re.compile(r"^(\d+(?:\.\d+)?)\.md$")

# 合并后衔接检查项（全部为整章视角，节级自查管不到）
# 每项 = (编号, 检查名, 判定说明)
CHECK_ITEMS = (
    ('C1', '节序连续性',
     '章内节号须连续递增（如 1.1→1.2→1.3），无跳号/无倒序'),
    ('C2', '节号唯一性',
     '同节号不得出现两份（重复节 → 合并会产生重复内容）'),
    ('C3', '术语一致性',
     '同一术语在章内不得出现两种写法（跨节术语漂移是拆分写作的头号副作用）'),
    ('C4', '图表位连续性',
     '图位编号须为 {章号}-{序号} 形态，序号不重复'),
    ('C5', '数据标签完整性',
     '数值陈述须带 [实]/[估]/[引]/[待核实] 标签（合并后整章视角复核）'),
    ('C6', '章节过渡',
     '相邻节之间须有过渡（承接句/小结），避免拼接感'),
)


def log(msg: str, level: str = 'INFO') -> None:
    print(f'[{level}] {msg}', file=sys.stderr)


def _read_section_order(design_path: Path) -> list[str]:
    """从 chapter_design §C 解析节序（与 assemble_sections 同源正则）。"""
    if not design_path.is_file():
        return []
    text = design_path.read_text(encoding='utf-8')
    m = re.search(r'##\s*C[\.、．]?\s*[^\n]*\n(?:(?!^## ).)*', text, re.S | re.M)
    seg = m.group(0) if m else text
    order: list[str] = []
    for line in seg.splitlines():
        if '|' not in line:
            continue
        cells = [c.strip() for c in line.strip('|').split('|')]
        if cells and re.fullmatch(r'\d+(?:\.\d+)+', cells[0]):
            order.append(cells[0])
    return order


def _sec_key(sec_no: str) -> tuple:
    """节号 → 可比较的元组（1.10 > 1.9，按数值而非字典序）。"""
    try:
        return tuple(int(x) for x in sec_no.split('.'))
    except ValueError:
        return (0,)


def check_continuity(order: list[str]) -> list[str]:
    """C1 节序连续性：不得跳号、不得倒序。"""
    problems: list[str] = []
    for a, b in zip(order, order[1:]):
        ka, kb = _sec_key(a), _sec_key(b)
        if kb <= ka:
            problems.append(f'C1 节序倒序/重复: {a} → {b}')
            continue
        # 同级递增应 +1；允许子节层级变化（如 1.2 → 1.2.1）
        if len(ka) == len(kb) and kb[0] == ka[0] and kb[-1] != ka[-1] + 1:
            problems.append(f'C1 节号跳号: {a} → {b}（同级应连续）')
    return problems


def check_uniqueness(order: list[str]) -> list[str]:
    """C2 节号唯一性。"""
    seen, dup = set(), []
    for s in order:
        if s in seen:
            dup.append(s)
        seen.add(s)
    return [f'C2 节号重复: {s}' for s in dup]


def _extract_terms(body: str, min_len: int = 4, max_len: int = 8) -> set[str]:
    """抽取术语候选（滑窗 n-gram）。

    **为什么用滑窗而不是 `[一-龥]{2,6}` 贪婪匹配**（2026-11-04 实测踩坑）：
    贪婪匹配会把「本节讲禽病防冶的要点，禽病防治体系需完善」切成
    `['冶的要点', '本节讲禽病防', '禽病防治体系', '需完善']`——
    「禽病防冶」这个**真正的漂移写法根本没被抽出来**，
    导致近形异写比对永远查不出问题。
    滑窗保证每个长度为 min_len..max_len 的汉字连续子串都会被抽出，
    近形异写必然成对出现。

    候选集可能偏大（中文 n-gram 组合爆炸）→ 用**出现频次**过滤：
    只在「跨节出现」且「在同节内重复」的术语里找近形异写，
    这正是术语表里「核心术语」的特征。
    """
    # 按标点/空白切句，避免跨句粘连
    chunks = re.split(r'[，。；：、！？\s（）()\[\]【】"\'|—\-]+', body)
    out: set[str] = set()
    for chunk in chunks:
        n = len(chunk)
        for size in range(min_len, max_len + 1):
            if size > n:
                break
            for i in range(n - size + 1):
                out.add(chunk[i:i + size])
    return out


def check_terms(sections: list[tuple[str, str]],
                term_rows: list[tuple] | None = None
                ) -> tuple[list[str], list[str]]:
    """C3 术语一致性 → (阻断项, 提示项)。

    **两级判据（2026-11-04 实测后重构）**

    L1 权威源（首选）：术语表 SSOT 三级查找
        ① {WORK_ROOT}/学科标准/术语表.md
        ② references/profiles/{discipline}.md §5.1
        ③ references/terminology-table.example.md（示例，WARN）
      按「禁用写法」列 + 「允许别名」列核验合并后正文。
      这是**权威判据**——与 check_manuscript.py 门禁 4.11c 同源，
      不另造口径。命中 → **阻断**（术语表说禁用就是禁用）。

    L2 启发式（仅术语表完全缺失时启用）：近形异写检测。
      实测教训：纯 n-gram 启发式误报率高（滑窗必然产生「病发生的」
      vs「疾病发生的」这类切片噪声）→ 只能作**提示级**，
      且必须显著标注「启发式，非权威」。

    返回值分流：
      · 术语表禁用写法命中 / 别名并存 → 阻断项（进 blocking_problems）
      · 启发式近形异写 → 提示项（进 advisory_hints）
    """
    blocking: list[str] = []
    hints: list[str] = []
    body_all = '\n'.join(b for _, b in sections)

    # ── L1 权威源：术语表核验 ──────────────────────────────────
    if term_rows:
        l1_hits = 0
        for std, alias, banned, _first in term_rows:
            for b in banned:
                if not b:
                    continue
                cnt = body_all.count(b)
                if cnt:
                    l1_hits += 1
                    blocking.append(
                        f'C3 术语表禁用写法命中: 「{b}」(×{cnt}) —— '
                        f'标准写法应为「{std}」[术语表权威源]')
            # 别名与标准写法并存（同一页内不并存 → 合并后整章视角）
            if alias and alias != '—':
                if body_all.count(std) and body_all.count(alias):
                    l1_hits += 1
                    blocking.append(
                        f'C3 标准写法与别名并存: 「{std}」与别名「{alias}」'
                        f'同时出现 —— 同一页内不得并存 [术语表权威源]')
        if l1_hits:
            return blocking, hints      # 权威源已判定 → 不叠加启发式
        hints.append(
            f'C3 术语表权威核验：{len(term_rows)} 条术语、禁用写法 0 命中'
            f'（未覆盖术语表外的自由表述漂移）')
        return blocking, hints

    # ── L2 启发式（仅术语表完全缺失时的降级路径）──────────────
    total_cnt: dict[str, int] = {}
    sec_freq: dict[str, set[str]] = {}
    for sec_no, body in sections:
        for t in _extract_terms(body):
            c = body.count(t)
            if c <= 0:
                continue
            total_cnt[t] = total_cnt.get(t, 0) + c
            sec_freq.setdefault(t, set()).add(sec_no)

    main_terms = {t for t, n in total_cnt.items()
                   if n >= 2 and len(sec_freq.get(t, ())) >= 2}
    if not main_terms:
        return blocking, hints

    minimal = _minimal_candidates(body_all, set(total_cnt))
    main_terms = {t for t in main_terms if t in minimal}
    if not main_terms:
        return blocking, hints

    seen_pairs = set()
    for t1 in sorted(main_terms):
        for t2 in sorted(minimal):
            if t1 == t2 or abs(len(t1) - len(t2)) > 1:
                continue
            if len(t1) < 4 or len(t2) < 4:
                continue
            if _edit_distance(t1, t2) != 1:
                continue
            f1, f2 = total_cnt.get(t1, 0), total_cnt.get(t2, 0)
            if f2 >= f1:
                continue
            # 覆盖度：主项须比配项覆盖更多节
            cov1 = len(sec_freq.get(t1, ()))
            cov2 = len(sec_freq.get(t2, ()))
            if cov1 <= cov2:
                continue
            key = tuple(sorted((t1, t2)))
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            hints.append(
                f'C3 术语疑似漂移（启发式·非权威，术语表缺失时降级启用）: '
                f'「{t1}」(×{f1}, 覆盖{cov1}节) vs 「{t2}」(×{f2}, 覆盖{cov2}节)')
            if len(hints) >= 20:
                return blocking, hints
    return blocking, hints


def _is_standalone(body: str, term: str) -> bool:
    """判定 term 是否在正文中**以标点/空白为界**出现（不跨词边界）。

    中文无词边界，故不能用「前后不接汉字」判定术语独立——那会把
    「本节讲禽病防治要点」里的「禽病防治」误判为非独立（实测）。
    此处只用于**降噪**：排除那些明显是长片段切片的候选
    （其左右紧邻汉字且不是标点/空白）。

    判定口径：存在一处出现，其左右至少一侧是**非汉字**（标点/空白/换行）
    或处于文首/文末 → 视为独立出现。
    """
    if not term:
        return False
    idx = body.find(term)
    while idx != -1:
        before = body[idx - 1] if idx > 0 else ''
        after = body[idx + len(term)] if idx + len(term) < len(body) else ''
        if not _is_hanzi(before) or not _is_hanzi(after):
            return True
        idx = body.find(term, idx + 1)
    return False


def _is_hanzi(ch: str) -> bool:
    return bool(ch) and '一' <= ch <= '龥'


def _minimal_candidates(body: str, terms: set[str]) -> set[str]:
    """从 n-gram 候选里挑出「最小独立单元」——降噪核心。

    n-gram 会产出「禽病防治体系」「禽病防治中」「禽病防治」等一串长度
    递减的同源片段。真正的术语漂移发生在**最短的那一层**：
    正确的最短层（禽病防治）vs 错写的最短层（禽病防冶）。
    长片段只是上下文噪声。

    口径：对每个候选 t，若存在**更短的候选 s**（s 是 t 的真子串）
    且 s 在正文中独立出现 → t 是长片段，剔除。
    剩下的就是最小独立单元集合。
    """
    out: set[str] = set()
    for t in terms:
        dominated = False
        for s in terms:
            if s == t or len(s) >= len(t):
                continue
            if t in s:      # s 比 t 长 → 不是我们要的
                continue
            if s in t and _is_standalone(body, s):
                dominated = True
                break
        if not dominated:
            out.add(t)
    return out


def _edit_distance(a: str, b: str) -> int:
    """Levenshtein 距离（编辑距离 1 的判定用）。"""
    if abs(len(a) - len(b)) > 1:
        return 2
    if len(a) == len(b):
        return sum(1 for x, y in zip(a, b) if x != y)
    # 长度差 1：尝试插入一个字符
    if len(a) > len(b):
        a, b = b, a
    for i in range(len(b)):
        if b[:i] + b[i + 1:] == a:
            return 1
    return 2


def check_figures(sections: list[tuple[str, str]], chapter: str) -> list[str]:
    """C4 图表位连续性：图位编号形态 + 序号不重复。"""
    problems: list[str] = []
    seen: dict[str, str] = {}
    for sec_no, body in sections:
        for m in re.finditer(r'\[图\s*([^\]：:]{1,10})[：:]', body):
            raw = m.group(1).strip()
            if not re.fullmatch(r'\d+-\d+', raw):
                problems.append(f'C4 图位编号格式非法（{sec_no}）: [{raw}]')
                continue
            if raw in seen:
                problems.append(f'C4 图位重复: [{raw}] 出现于 {seen[raw]} 与 {sec_no}')
            else:
                seen[raw] = sec_no
    return problems


RE_DATA_TAG = re.compile(r'\[(?:实|估|引|待核实)')
RE_PERCENT = re.compile(r'\d+(?:\.\d+)?\s*[%％]')


def check_data_tags(sections: list[tuple[str, str]]) -> list[str]:
    """C5 数据标签完整性：数值陈述须带标签。"""
    problems: list[str] = []
    for sec_no, body in sections:
        for i, line in enumerate(body.splitlines(), 1):
            if RE_PERCENT.search(line) and not RE_DATA_TAG.search(line):
                problems.append(f'C5 {sec_no} 行{i}: 数值陈述缺 [实]/[估]/[引]/[待核实] 标签')
                if len(problems) >= 30:
                    return problems
    return problems


RE_TRANSITION = re.compile(
    r'(承接|上一节|前一节|上节|接下来|下面(?:将|我们)|由此|综上|小节|过渡)')


def check_transitions(sections: list[tuple[str, str]]) -> list[str]:
    """C6 章节过渡：相邻节之间须有过渡线索，避免拼接感。

    口径：后一节的前 3 行内须出现过渡词，或出现指向上一节的引用。
    这是**提示级**启发式——无过渡词不必然是问题（客观陈述节可无过渡），
    故记为提示项，不单独阻断；阻断由 C1-C5 决定。
    """
    hints: list[str] = []
    for (a, _), (b, body_b) in zip(sections, sections[1:]):
        head = '\n'.join(body_b.splitlines()[:3])
        if not RE_TRANSITION.search(head):
            hints.append(f'C6 {a} → {b} 交界处未见过渡线索（检查衔接是否突兀）')
    return hints


def build_checklist(chapter: str, order: list[str], sections: list[tuple[str, str]],
                    problems: list[str], hints: list[str],
                    downstream: str, term_source: str = '') -> dict:
    """构造合并后必检清单（落盘为 章域/合并检查清单.json）。"""
    return {
        'chapter': chapter,
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'downstream_phase': downstream,
        'sections_merged': order,
        'section_count': len(order),
        'terminology_source': term_source,
        'check_items': [
            {'id': cid, 'name': name, 'rule': rule}
            for cid, name, rule in CHECK_ITEMS
        ],
        'blocking_problems': problems,
        'advisory_hints': hints,
        'verdict': 'PASS' if not problems else 'FAIL',
        'note': ('合并后必检清单。blocking_problems 非空 → 不得进 '
                 f'{downstream}，须回 writer 修节重合并。'
                 '本清单是**整章衔接**视角，与 assemble_sections.py 的节级自查互补。'),
    }


def load_term_rows(work_root: Path, chapter: str) -> tuple[list[tuple], str]:
    """加载术语表行（复用 check_manuscript.py 的权威实现，不另造口径）。

    返回 (rows, 来源描述)。rows 元素 = (标准写法, 别名, [禁用写法...], 首次出现)。
    加载失败 → ([], 原因)，调用方据此决定是否降级到启发式。
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from check_manuscript import (  # type: ignore
            _extract_term_table, _parse_term_rows, _resolve_term_table,
        )
    except Exception as e:                       # pragma: no cover
        return [], f'术语表模块不可用（{e}）'
    pkg_root = Path(__file__).resolve().parent.parent
    try:
        from _profile_loader import read_discipline  # type: ignore
        discipline = read_discipline(work_root, chapter)
    except Exception:
        discipline = 'veterinary'
    try:
        table_text, source, _warn = _resolve_term_table(
            work_root, discipline, pkg_root)
    except Exception as e:
        return [], f'术语表解析失败（{e}）'
    if not table_text:
        return [], '三级术语表均缺失'
    rows, _ = _parse_term_rows(table_text)
    return rows, source


def main() -> int:
    ap = argparse.ArgumentParser(description='超上下文拆分-合并链路（合并后衔接检查）')
    ap.add_argument('--work-root', required=True)
    ap.add_argument('--chapter', required=True, help='如 ch01')
    ap.add_argument('--downstream', default='VERIFY-R3',
                    help='合并后的下游相位（默认 VERIFY-R3 = 检查）')
    ap.add_argument('--check-only', action='store_true',
                    help='只对已有 draft.md 做衔接检查，不重新合并')
    args = ap.parse_args()

    work_root = Path(args.work_root).expanduser().resolve()
    ch_dir = work_root / '章节' / args.chapter
    sec_dir = ch_dir / 'sections'
    draft = ch_dir / 'draft.md'

    if not ch_dir.is_dir():
        log(f'章目录不存在: {ch_dir}', 'ERROR')
        return 2

    # ── 合并阶段（check-only 跳过）─────────────────────────────────
    if not args.check_only:
        if not sec_dir.is_dir():
            log(f'sections/ 不存在: {sec_dir}（整章推进模式无需合并）', 'ERROR')
            return 2
        sec_files = sorted(sec_dir.glob('*.md'))
        if not sec_files:
            log(f'sections/ 为空: {sec_dir}', 'ERROR')
            return 2

        design_order = _read_section_order(ch_dir / 'chapter_design.md')
        file_map = {}
        for f in sec_files:
            m = RE_SECTION_FILE.match(f.name)
            if m:
                file_map[m.group(1)] = f
        if design_order:
            missing = [s for s in design_order if s not in file_map]
            if missing:
                log(f'设计节序缺 {len(missing)} 节文件: {missing}——禁止合并', 'ERROR')
                return 2
            order = design_order
        else:
            order = sorted(file_map, key=_sec_key)
            log('未能从 chapter_design §C 解析节序 → 按节号数值序合并', 'WARN')

        parts: list[str] = []
        sections: list[tuple[str, str]] = []
        for s in order:
            body = file_map[s].read_text(encoding='utf-8').strip()
            fm = re.match(r'^---\s*\n(.*?)\n---\s*\n', body, re.S)
            if fm:
                body = body[fm.end():]
            parts.append(body)
            sections.append((s, body))

        head = ''
        if draft.is_file():
            old = draft.read_text(encoding='utf-8')
            m = re.match(r'^---\s*\n(.*?)\n---\s*\n', old, re.S)
            if m:
                head = f'---\n{m.group(1)}\n---\n\n'
        draft.write_text(head + '\n\n'.join(parts) + '\n', encoding='utf-8')
        log(f'合并完成: {draft}（{len(order)} 节）')
    else:
        if not draft.is_file():
            log(f'draft.md 不存在: {draft}', 'ERROR')
            return 2
        # check-only：从 draft 反推节边界（以节标题/节号标记切）
        text = draft.read_text(encoding='utf-8')
        chunks = re.split(r'\n(?=#{1,4}\s*\d+(?:\.\d+)*\s)', text)
        sections = []
        order = []
        for c in chunks:
            m = re.match(r'^#{1,4}\s*(\d+(?:\.\d+)*)', c.strip())
            sec_no = m.group(1) if m else (str(len(order) + 1) if order else '1')
            order.append(sec_no)
            sections.append((sec_no, c))
        if not sections:
            log('draft.md 无法切分出节 → 请用 --order 或检查节标题格式', 'ERROR')
            return 2

    # ── 合并后必检（整章衔接视角）─────────────────────────────────
    term_rows, term_source = load_term_rows(work_root, args.chapter)
    problems: list[str] = []
    problems += check_continuity(order)
    problems += check_uniqueness(order)
    problems += check_figures(sections, args.chapter)
    problems += check_data_tags(sections)
    hints = check_transitions(sections)
    term_blocking, term_hints = check_terms(sections, term_rows)
    problems += term_blocking
    hints += term_hints
    if not term_rows:
        hints.append(
            f'C3 术语核验降级：术语表未加载（{term_source}）——'
            f'本项仅启用启发式近形异写检测，非权威判据；'
            f'补 学科标准/术语表.md 或 profile §5.1 可得权威核验')

    checklist = build_checklist(args.chapter, order, sections, problems, hints,
                                args.downstream, term_source)
    out = ch_dir / '合并检查清单.json'
    out.write_text(json.dumps(checklist, ensure_ascii=False, indent=2),
                   encoding='utf-8')

    if problems:
        log(f'合并后必检未过（{len(problems)} 项阻断）——不得进 '
            f'{args.downstream}，回 writer 修节重合并:', 'ERROR')
        for p in problems[:20]:
            log(f'  ✗ {p}', 'ERROR')
        log(f'清单落盘: {out}', 'ERROR')
        return 1

    log(f'合并后必检通过（{len(hints)} 项提示）→ 可进 {args.downstream}')
    log(f'清单落盘: {out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
