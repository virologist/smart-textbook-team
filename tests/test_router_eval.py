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
        改为 信号命中(40)+样例精确匹配(30)+成员空闲假设(20)+边界清晰(10) 合成
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

# skill §4 已知样例(精确匹配 → 置信度加成; G3 同步 skill §4 的 11 条)
KNOWN_SAMPLES = {
    '设计第 6 章禽流感鉴别诊断': 'design-bloom',
    '查一下 GB 19438 的现行版次': 'retrieval-standard',
    '检索 H5N1 致病性最新文献': 'retrieval-pmid',
    '写禽流感章节的骨架': 'write-skeleton',
    '把 draft 充实一下，加证据标签': 'write-revise',
    '审查 ch06 的结构': 'review-structure',
    '核验所有 [实] 标签的 PMID/DOI': 'review-citation',
    '校对这章，出校对后稿和修订记录': 'review-style',
    '给这章打个五维质量分': 'review-score',
    '校对并给这章打五维质量分': 'review-proofread-score',
    '审一下第 3 节的深度够不够': 'review-section',
    '单独核查第 5 节是否达标': 'review-section',
    '画一张疫区封锁的决策树': 'visual-spec',
    '按 gaps.md 把缺口逐条补证据': 'gap-retrieval',
}


def route(query: str) -> tuple[str | None, float, list[str]]:
    """返回 (task_type, confidence, routing_signals)

    置信度合成(FIX-4, 对应 skill §2; G3 量纲统一 0-100): 40 信号命中 + 30 样例精确 + 20 成员空闲(评测假设) + 10 边界清晰
    """
    q = query
    signals: list[str] = []

    def conf(sample_match: bool, boundary_clear: bool = True) -> float:
        c = 40 + 20  # 信号命中 + 成员空闲(评测假设空闲)
        if sample_match:
            c += 30
        if boundary_clear:
            c += 10
        return round(min(c, 100), 0)

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

    # ── 检索-标准(v1.3 中文法规链联动: 兽药典/动物防疫法/公告 等中文权威源入路由) ──
    if any(kw in q for kw in ('GB ', 'GB/', 'WOAH', 'OIE', '标准', '法规', '条例', '手册', '版次',
                              '兽药典', '动物防疫法', '畜牧法', '公告')):
        signals.append('standard')
        return 'retrieval-standard', conf(KNOWN_SAMPLES.get(q.strip()) == 'retrieval-standard'), signals

    # ── 检索-缺口清单(G3 新增: gaps.md 消费意图——置于 PMID 分支之前，防"补检索"被文献意图截胡) ──
    if 'gaps' in q.lower() or '缺口清单' in q or '缺口' in q:
        signals.append('gap')
        return 'gap-retrieval', conf(KNOWN_SAMPLES.get(q.strip()) == 'gap-retrieval'), signals

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

    # ── 审查-R4+R5 合并(B1-3 新增: 合并意图必须早于 R5/风格两个单轮分支,
    #    否则「校对并打分」会被「打分」截胡退化成 review-score) ──
    if (('校对' in q or '校稿' in q) and
            any(kw in q for kw in ('五维', '质量分', '打分', '评分', '打个分'))):
        signals.append('proofread-score')
        return ('review-proofread-score',
                conf(KNOWN_SAMPLES.get(q.strip()) == 'review-proofread-score'),
                signals)

    # ── 审查-R5 评分(G3 新增: 分数/五维/质量分意图) ──
    if any(kw in q for kw in ('五维', '质量分', '打个', '评分')):
        signals.append('score')
        return 'review-score', conf(KNOWN_SAMPLES.get(q.strip()) == 'review-score'), signals

    # ── 审查-结构/深度/风格 ──
    # ── 审查-节级(★G3 v2.10: review-section —— 「节」意图优先于整章审查词,
    #    否则「审一下第 3 节」会被「结构/深度」截胡) ──
    if '节' in q and any(kw in q for kw in ('审', '查', '核')):
        signals.append('review-section')
        return 'review-section', conf(KNOWN_SAMPLES.get(q.strip()) == 'review-section'), signals
    if ('结构' in q or '框架' in q) and '审' in q:
        signals.append('structure')
        return 'review-structure', conf(KNOWN_SAMPLES.get(q.strip()) == 'review-structure'), signals
    if any(kw in q for kw in ('深度', '内容够不够', '够不够深')):
        signals.append('depth')
        return 'review-depth', conf(False), signals
    if any(kw in q for kw in ('风格', 'AI 腔', 'AI腔', '可读', '校对', '校对后稿')):
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
    return None, 0, []


# 40 用例(2026-10-15 P2-3 扩容): 原 26 + 新增 14。
# 覆盖目标: 13 类 task_type 每类 ≥2(目标 3) + 模糊升级用例。
# 类型分布(40): design-bloom 3 | design-review 2 | retrieval-standard 4 |
#   retrieval-pmid 3 | retrieval-wiki 3 | write-skeleton 3 | write-revise 2 |
#   review-structure 2 | review-depth 3 | review-citation 3 | review-style 3 |
#   visual-spec 3 | visual-review 3 | 升级 3
EVAL_CASES = [
    ("设计第 6 章禽流感鉴别诊断", "design-bloom", 80),
    ("给我这一章的 Bloom 分层大纲", "design-bloom", 70),
    ("把教学设计复审一遍", "design-review", 70),
    ("复审一下这章的教学设计", "design-review", 60),
    ("查一下 GB 19438 的现行版次", "retrieval-standard", 80),
    ("WOAH《陆生动物卫生手册》最新版的禽流感章节", "retrieval-standard", 70),
    ("检索 H5N1 致病性最新文献", "retrieval-pmid", 80),
    ("找一下 PMID 关于 H7N9 免疫逃逸的", "retrieval-pmid", 70),
    ("把这条事实沉淀到知识库", "retrieval-wiki", 70),
    ("写禽流感章节的骨架", "write-skeleton", 70),
    ("起草 R1 章节框架", "write-skeleton", 60),
    ("把 draft 充实一下,加证据标签", "write-revise", 70),
    ("润色一下这段文字", "write-revise", 70),
    ("审查 ch06 的结构", "review-structure", 80),
    ("看这章深度够不够", "review-depth", 60),
    ("核验所有 [实] 标签的 PMID/DOI", "review-citation", 80),   # 回归钉: 曾被误路由为 retrieval-pmid
    ("检查引用是不是真实", "review-citation", 70),
    ("逐条核验正文里的 DOI", "review-citation", 70),             # 新增: 核验意图(含 DOI)
    ("这章风格怎么样,有 AI 腔吗", "review-style", 70),
    ("画一张疫区封锁的决策树", "visual-spec", 80),
    ("做个 Mermaid 流程图", "visual-spec", 70),
    ("图与正文数据一致吗", "visual-review", 60),                 # 回归钉: 曾被误路由为 visual-spec
    ("图表数值和 draft 对得上吗", "visual-review", 60),          # 新增: 一致性意图

    # ── P2-3 扩容(2026-10-15): 14 条,补齐 1-覆盖类至 3 ──
    ("按 Bloom 认知层级排布这章的知识块", "design-bloom", 70),
    ("先写一版 ch09 的 R1 框架", "write-skeleton", 70),
    ("查兽药典 2020 版对碘伏的浓度规定", "retrieval-standard", 70),   # 中文法规源入路由(联动 citation-verify v130)
    ("查动物防疫法第 X 条的现行表述", "retrieval-standard", 70),      # 中文法规源(新关键词)
    ("找 H5 亚型分子流行病学方面的文献", "retrieval-pmid", 70),
    ("把这条结论入库", "retrieval-wiki", 70),
    ("把这个知识点沉淀一下", "retrieval-wiki", 70),
    ("审一下这章的结构安排", "review-structure", 70),
    ("看看 §2 机制讲得深不深,内容够不够", "review-depth", 70),
    ("这章因果链深度不够,做一次深度复核", "review-depth", 70),
    ("查一下有没有套话和 AI 腔", "review-style", 70),
    ("统一一下各节的术语和文风可读性", "review-style", 70),
    ("给 §4 画一张免疫程序时序图", "visual-spec", 70),
    ("插图编号和正文引用对得上吗", "visual-review", 70),

    # ── G3 扩容(2026-10-31): 新枚举 3 类 ──
    ('给这章打个五维质量分', 'review-score', 70),
    ('按五维给 ch03 评分', 'review-score', 70),
    ('按 gaps.md 把缺口逐条补证据', 'gap-retrieval', 70),
    ('缺口清单里的条目逐条补检索', 'gap-retrieval', 70),
    ('校对这章，出校对后稿和修订记录', 'review-style', 70),

    # ── B1-3 新增(2026-11-04): R4+R5 合并派工路由 ──
    ('校对并给这章打五维质量分', 'review-proofread-score', 100),
    ('校稿并打分，一次做完', 'review-proofread-score', 70),

    # 边界用例: 模糊问法, 应触发升级
    ("帮我搞一下这章", None, 0),
    ("看看这章", None, 0),
    ("这章写得怎么样", None, 0),                                # 新增: 无路由信号, 期望升级
]


def main() -> int:
    verbose = '--verbose' in sys.argv
    passed, failed, fail_details = 0, 0, []

    for query, expected_type, min_conf in EVAL_CASES:
        actual_type, actual_conf, signals = route(query)
        if expected_type is None:
            ok = actual_type is None or actual_conf < 70
        else:
            ok = (actual_type == expected_type) and (actual_conf >= min_conf)
        if ok:
            passed += 1
            if verbose:
                print(f"  PASS  '{query}' → {actual_type} ({actual_conf:.0f}) {signals}")
        else:
            failed += 1
            fail_details.append((query, expected_type, actual_type, actual_conf))
            print(f"  FAIL  '{query}' → expected={expected_type} >= {min_conf}, "
                  f"got={actual_type} ({actual_conf:.0f})")

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
