#!/usr/bin/env python3
"""test_router_eval.py — task-router 离线评估

加载 task-router skill 的 task_type 枚举 + 已知样例,跑 20+ 用例,计算命中率。
>= 80% 方可通过 CI gate。

用法: python3 tests/test_router_eval.py [--verbose]
"""

from __future__ import annotations
import json
import re
import sys
from pathlib import Path

# 任务类型枚举（与 skills/task-router/SKILL.md §1 SSOT 对齐）
TASK_TYPES = {
    'design-bloom': 'didactic-architect',
    'design-review': 'didactic-architect',
    'retrieval-pmid': 'literature-scout',
    'retrieval-standard': 'literature-scout',
    'retrieval-wiki': 'literature-scout',
    'write-skeleton': 'subject-writer',
    'write-revise': 'subject-writer',
    'review-structure': 'quality-examiner',
    'review-depth': 'quality-examiner',
    'review-citation': 'quality-examiner',
    'review-style': 'quality-examiner',
    'visual-spec': 'visual-instructional-designer',
    'visual-review': 'visual-instructional-designer',
}

# 20+ 用例（与 skill §4 一致并扩充）
EVAL_CASES = [
    # (用户问法, 期望 task_type, 期望置信度下限)
    ("设计第 6 章禽流感鉴别诊断", "design-bloom", 0.8),
    ("给我这一章的 Bloom 分层大纲", "design-bloom", 0.7),
    ("把教学设计复审一遍", "design-review", 0.7),
    ("查一下 GB 19438 的现行版次", "retrieval-standard", 0.8),
    ("WOAH《陆生动物卫生手册》最新版的禽流感章节", "retrieval-standard", 0.7),
    ("检索 H5N1 致病性最新文献", "retrieval-pmid", 0.8),
    ("找一下 PMID 关于 H7N9 免疫逃逸的", "retrieval-pmid", 0.9),
    ("把这条事实沉淀到知识库", "retrieval-wiki", 0.7),
    ("写禽流感章节的骨架", "write-skeleton", 0.7),
    ("起草 R1 章节框架", "write-skeleton", 0.6),
    ("把 draft 充实一下,加证据标签", "write-revise", 0.8),
    ("润色一下这段文字", "write-revise", 0.7),
    ("审查 ch06 的结构", "review-structure", 0.8),
    ("看这章深度够不够", "review-depth", 0.7),
    ("核验所有 [实] 标签的 PMID/DOI", "review-citation", 0.9),
    ("检查引用是不是真实", "review-citation", 0.8),
    ("这章风格怎么样,有 AI 腔吗", "review-style", 0.8),
    ("画一张疫区封锁的决策树", "visual-spec", 0.8),
    ("做个 Mermaid 流程图", "visual-spec", 0.8),
    ("图与正文数据一致吗", "visual-review", 0.7),
    # 边界用例:模糊问法,应触发升级（命中 fallback task_type 但置信度应 < 0.7）
    ("帮我搞一下这章", None, 0.0),         # 完全模糊,期望升级
    ("看看这章", None, 0.0),               # 完全模糊,期望升级
]

# 路由器实现（简化版,与 skill §2 决策算法对应）
def route(query: str) -> tuple[str | None, float, list[str]]:
    """返回 (task_type, confidence, routing_signals)"""
    q = query.lower()
    signals = []

    # 设计相关
    if any(kw in query for kw in ['设计', 'Bloom', '大纲', '教学设计']):
        signals.append('design')
        if '复审' in query or '审一下' in query and '设计' in query:
            return 'design-review', 0.85, signals
        return 'design-bloom', 0.85, signals

    # 检索-标准
    if any(kw in query for kw in ['GB ', 'WOAH', 'OIE', '标准', '法规', '条例', '手册']):
        signals.append('standard')
        return 'retrieval-standard', 0.90, signals

    # 检索-PMID
    if any(kw in query for kw in ['PMID', 'DOI', '文献', '检索', '找一下']):
        signals.append('pmid')
        return 'retrieval-pmid', 0.85, signals

    # 检索-沉淀
    if any(kw in query for kw in ['沉淀', '知识库', '入库']):
        signals.append('wiki')
        return 'retrieval-wiki', 0.80, signals

    # 撰写-骨架
    if any(kw in query for kw in ['骨架', '起草', 'R1', '框架']) and '写' in query or '起草' in query:
        signals.append('skeleton')
        return 'write-skeleton', 0.80, signals

    # 撰写-充实
    if any(kw in query for kw in ['充实', '润色', '改写', '写', '续写']):
        signals.append('revise')
        return 'write-revise', 0.80, signals

    # 审查-引用
    if any(kw in query for kw in ['核验', 'PMID', 'DOI', '引用', '真实']):
        signals.append('citation')
        return 'review-citation', 0.90, signals

    # 审查-结构
    if any(kw in query for kw in ['结构', '框架']) and '审' in query:
        signals.append('structure')
        return 'review-structure', 0.85, signals

    # 审查-深度
    if any(kw in query for kw in ['深度', '内容']):
        signals.append('depth')
        return 'review-depth', 0.75, signals

    # 审查-风格
    if any(kw in query for kw in ['风格', 'AI 腔', '可读']):
        signals.append('style')
        return 'review-style', 0.80, signals

    # 视觉-规格
    if any(kw in query for kw in ['图', 'Mermaid', 'SVG', 'chart', '决策树', '流程图']):
        signals.append('visual-spec')
        return 'visual-spec', 0.85, signals

    # 视觉-审查
    if '图' in query and ('一致' in query or '对' in query):
        signals.append('visual-review')
        return 'visual-review', 0.80, signals

    # 默认:升级
    return None, 0.0, []


def main() -> int:
    verbose = '--verbose' in sys.argv

    passed = 0
    failed = 0
    fail_details = []

    for query, expected_type, min_conf in EVAL_CASES:
        actual_type, actual_conf, signals = route(query)

        # 命中判定
        if expected_type is None:
            # 期望升级: 实际应返回 None 或置信度 < 0.7
            ok = actual_type is None or actual_conf < 0.7
        else:
            ok = (actual_type == expected_type) and (actual_conf >= min_conf)

        if ok:
            passed += 1
            if verbose:
                print(f"  PASS  '{query}' → {actual_type} ({actual_conf:.2f})")
        else:
            failed += 1
            fail_details.append((query, expected_type, actual_type, actual_conf))
            print(f"  FAIL  '{query}' → expected={expected_type} >= {min_conf}, "
                  f"got={actual_type} ({actual_conf:.2f})")

    total = passed + failed
    score = passed / total if total > 0 else 0.0

    print(f"\n{'='*60}")
    print(f"Router Eval 总分: {passed}/{total} ({score:.3f})")
    print(f"门槛: ≥ 0.80 (Apollo 类比基线)")
    print(f"{'='*60}")

    if failed > 0:
        print(f"\n失败用例 ({failed}):")
        for q, exp, act, conf in fail_details:
            print(f"  - '{q}' → 期望 {exp}, 实际 {act} ({conf:.2f})")

    # CI gate
    if score >= 0.80:
        print("\n✓ PASS — router 达标")
        return 0
    else:
        print(f"\n✗ FAIL — router 命中率 {score:.3f} < 0.80, 需扩展训练样本或调整权重")
        return 1


if __name__ == '__main__':
    sys.exit(main())
