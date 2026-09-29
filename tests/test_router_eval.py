#!/usr/bin/env python3
"""test_router_eval.py — task-router 离线评估

evo-16 修订（2026-09-30 九维诊断后重构）:
  FIX-1 优先级 bug: review-citation(核验/真实/引用) 判定提到 retrieval-pmid 之前——
        否则「核验所有 [实] 标签的 PMID/DOI」被 PMID 关键词截胡误路由为检索(实战级误路由)
  FIX-2 优先级 bug: visual-review(图文一致) 判定提到 visual-spec 之前——
        否则「图与正文数据一致吗」被「图」截胡误路由为出图
  FIX-3 运算符优先级 bug: 原 L90 `any(...) and '写' in query or '起草' in query`
        因 and/or 优先级, 任何含「起草」的问法都直落 write-skeleton——加括号修正
  FIX-4 置信度失真: 原实现每分支硬编码 0.85/0.90, 不反映 skill §2 四步评分——
        改为 信号命中(0.4)+样例精确匹配(0.3)+成员空闲假设(0.2)+边界清晰(0.1) 合成
  FIX-5 双 SSOT 漂移: TASK_TYPES 不再手抄, 改为解析 skills/task-router/SKILL.md §1 表格——
        skill 改枚举本文件自动跟随, 漂移在源头消灭
  NOTE  本文件是 skill §2 决策算法的 Python 影子实现, 用于离线回归; 真实路由由
        team-lead LLM 执行。skill 与本实现必须同步演进(见 skill §6 义务声明)。

用法: python3 tests/test_router_eval.py [--verbose]
门槛: 命中率 >= 0.80
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SKILL_PATH = Path(__file__).resolve().parent.parent / 'skills' / 'task-router' / 'SKILL.md'


def load_task_types() -> dict[str, str]:
    """FIX-5: 从 skill §1 markdown 表解析 task_type → 责任成员(SSOT 派生)"""
    if not SKILL_PATH.exists():
        raise FileNotFoundError(f'task-router skill 不存在: {SKILL_PATH}')
    types: dict[str, str] = {}
    for line in SKILL_PATH.read_text(encoding='utf-8').splitlines():
        m = re.match(
            r'^\|\s*`?([a-z][a-z-]+)`?\s*\|[^|]+\|\s*'
            r'(didactic-architect|literature-scout|subject-writer|quality-examiner|visual-instructional-designer)\s*\|',
            line,
        )
        if m:
            types[m.group(1)] = m.group(2)
    if len(types) < 12:
        raise ValueError(f'skill §1 枚举解析不完整: 仅 {len(types)} 项, 应 >=12 (表格格式变更?)')
    return types


TASK_TYPES = load_task_types()

# skill §4 已知样例(精确匹配 → 置信度加成)
KNOWN_SAMPLES = {
    '设计第 6 章禽流感鉴别诊断': 'design-bloom',
    '查一下 GB 19438 的现行版次': 'retrieval-standard',
    '检索 H5N1 致病性最新文献': 'retrieval-pmid',
    '写禽流感章节的骨架': 'write-skeleton',
    '把 draft 充实一下，加证据标签': 'write-revise',
    '审查 ch06 的结构': 'review-structure',
    '核验所有 [实] 标签的 PMID/DOI': 'review-citation',
    '画一张疫区封锁的决策树': 'visual-spec',
}


def route(query: str) -> tuple[str | None, float, list[str]]:
    """返回 (task_type, confidence, routing_signals)

    置信度合成(FIX-4, 对应 skill §2): 0.4 信号命中 + 0.3 样例精确 + 0.2 成员空闲(评测假设) + 0.1 边界清晰
    """
    q = query
    signals: list[str] = []

    def conf(sample_match: bool, boundary_clear: bool = True) -> float:
        c = 0.4 + 0.2  # 信号命中 + 成员空闲(评测假设空闲)
        if sample_match:
            c += 0.3
        if boundary_clear:
            c += 0.1
        return round(min(c, 1.0), 2)

    # ── 审查-引用(核验意图优先于检索意图, FIX-1) ──
    if any(kw in q for kw in ('核验', '查无此文', '引用是不是真实', '引用真实', '逐条核验')) or \
            ('引用' in q and '真实' in q) or ('[实]' in q and ('核' in q or '查' in q)):
        signals.append('citation')
        sample = KNOWN_SAMPLES.get(q.strip()) == 'review-citation'
        return 'review-citation', conf(sample), signals

    # ── 视觉-审查(一致性意图优先于出图意图, FIX-2) ──
    if '图' in q and any(kw in q for kw in ('一致', '相符', '对得上', '对齐')):
        signals.append('visual-review')
        return 'visual-review', conf(False), signals

    # ── 设计 ──
    if any(kw in q for kw in ('设计', 'Bloom', '大纲', '教学设计')):
        signals.append('design')
        if '复审' in q or ('审' in q and '设计' in q):
            return 'design-review', conf(False), signals
        return 'design-bloom', conf(KNOWN_SAMPLES.get(q.strip()) == 'design-bloom'), signals

    # ── 检索-标准 ──
    if any(kw in q for kw in ('GB ', 'GB/', 'WOAH', 'OIE', '标准', '法规', '条例', '手册', '版次')):
        signals.append('standard')
        return 'retrieval-standard', conf(KNOWN_SAMPLES.get(q.strip()) == 'retrieval-standard'), signals

    # ── 检索-PMID ──
    if any(kw in q for kw in ('PMID', 'DOI', '文献', '检索', '找一下', '查文献')):
        signals.append('pmid')
        return 'retrieval-pmid', conf(KNOWN_SAMPLES.get(q.strip()) == 'retrieval-pmid'), signals

    # ── 检索-沉淀 ──
    if any(kw in q for kw in ('沉淀', '知识库', '入库')):
        signals.append('wiki')
        return 'retrieval-wiki', conf(False), signals

    # ── 撰写-骨架(FIX-3: 括号显式化, 消除 and/or 优先级陷阱) ──
    if ('写' in q and any(kw in q for kw in ('骨架', 'R1', '框架'))) or '起草' in q:
        signals.append('skeleton')
        return 'write-skeleton', conf(KNOWN_SAMPLES.get(q.strip()) == 'write-skeleton'), signals

    # ── 撰写-充实(evo-16 边界加固: 单字「写」过宽——「这章写得怎么样」会被误捕获,
    #    要求与写作对象上下文共现; 润色/充实/改写/续写 仍可单独立路由) ──
    if any(kw in q for kw in ('充实', '润色', '改写', '续写')) or \
            ('写' in q and any(ctx in q for ctx in ('正文', '章节内容', '这段', '一下', 'draft', '稿子'))):
        signals.append('revise')
        return 'write-revise', conf(KNOWN_SAMPLES.get(q.strip()) == 'write-revise'), signals

    # ── 审查-结构/深度/风格 ──
    if ('结构' in q or '框架' in q) and '审' in q:
        signals.append('structure')
        return 'review-structure', conf(KNOWN_SAMPLES.get(q.strip()) == 'review-structure'), signals
    if any(kw in q for kw in ('深度', '内容够不够', '够不够深')):
        signals.append('depth')
        return 'review-depth', conf(False), signals
    if any(kw in q for kw in ('风格', 'AI 腔', 'AI腔', '可读')):
        signals.append('style')
        return 'review-style', conf(False), signals

    # ── 视觉-规格 ──
    if any(kw in q for kw in ('图', 'Mermaid', 'SVG', 'chart', '决策树', '流程图')):
        signals.append('visual-spec')
        return 'visual-spec', conf(KNOWN_SAMPLES.get(q.strip()) == 'visual-spec'), signals

    # ── 设计-复审(「复审」独立兜底) ──
    if '复审' in q and '设计' in q:
        signals.append('design-review')
        return 'design-review', conf(False), signals

    # 默认: 升级
    return None, 0.0, []


# 26 用例: 原 22 + 新增 4(含两个曾被误路由的回归钉)
EVAL_CASES = [
    ("设计第 6 章禽流感鉴别诊断", "design-bloom", 0.8),
    ("给我这一章的 Bloom 分层大纲", "design-bloom", 0.7),
    ("把教学设计复审一遍", "design-review", 0.7),
    ("复审一下这章的教学设计", "design-review", 0.6),
    ("查一下 GB 19438 的现行版次", "retrieval-standard", 0.8),
    ("WOAH《陆生动物卫生手册》最新版的禽流感章节", "retrieval-standard", 0.7),
    ("检索 H5N1 致病性最新文献", "retrieval-pmid", 0.8),
    ("找一下 PMID 关于 H7N9 免疫逃逸的", "retrieval-pmid", 0.7),
    ("把这条事实沉淀到知识库", "retrieval-wiki", 0.7),
    ("写禽流感章节的骨架", "write-skeleton", 0.7),
    ("起草 R1 章节框架", "write-skeleton", 0.6),
    ("把 draft 充实一下,加证据标签", "write-revise", 0.7),
    ("润色一下这段文字", "write-revise", 0.7),
    ("审查 ch06 的结构", "review-structure", 0.8),
    ("看这章深度够不够", "review-depth", 0.6),
    ("核验所有 [实] 标签的 PMID/DOI", "review-citation", 0.8),   # 回归钉: 曾被误路由为 retrieval-pmid
    ("检查引用是不是真实", "review-citation", 0.7),
    ("逐条核验正文里的 DOI", "review-citation", 0.7),             # 新增: 核验意图(含 DOI)
    ("这章风格怎么样,有 AI 腔吗", "review-style", 0.7),
    ("画一张疫区封锁的决策树", "visual-spec", 0.8),
    ("做个 Mermaid 流程图", "visual-spec", 0.7),
    ("图与正文数据一致吗", "visual-review", 0.6),                 # 回归钉: 曾被误路由为 visual-spec
    ("图表数值和 draft 对得上吗", "visual-review", 0.6),          # 新增: 一致性意图
    # 边界用例: 模糊问法, 应触发升级
    ("帮我搞一下这章", None, 0.0),
    ("看看这章", None, 0.0),
    ("这章写得怎么样", None, 0.0),                                # 新增: 无路由信号, 期望升级
]


def main() -> int:
    verbose = '--verbose' in sys.argv
    passed, failed, fail_details = 0, 0, []

    for query, expected_type, min_conf in EVAL_CASES:
        actual_type, actual_conf, signals = route(query)
        if expected_type is None:
            ok = actual_type is None or actual_conf < 0.7
        else:
            ok = (actual_type == expected_type) and (actual_conf >= min_conf)
        if ok:
            passed += 1
            if verbose:
                print(f"  PASS  '{query}' → {actual_type} ({actual_conf:.2f}) {signals}")
        else:
            failed += 1
            fail_details.append((query, expected_type, actual_type, actual_conf))
            print(f"  FAIL  '{query}' → expected={expected_type} >= {min_conf}, "
                  f"got={actual_type} ({actual_conf:.2f})")

    total = passed + failed
    score = passed / total if total else 0.0
    print(f"\n{'=' * 60}")
    print(f"Router Eval 总分: {passed}/{total} ({score:.3f})")
    print(f"枚举来源: skill §1 SSOT 解析 ({len(TASK_TYPES)} 类) | 用例: {total}")
    print(f"门槛: >= 0.80")
    print(f"{'=' * 60}")
    if failed:
        print(f"\n失败用例 ({failed}):")
        for q, exp, act, c in fail_details:
            print(f"  - '{q}' → 期望 {exp}, 实际 {act} ({c:.2f})")
    if score >= 0.80:
        print("\n✓ PASS — router 达标")
        return 0
    print(f"\n✗ FAIL — router 命中率 {score:.3f} < 0.80, 需扩展样本或调整权重")
    return 1


if __name__ == '__main__':
    sys.exit(main())
