#!/usr/bin/env python3
"""trace_schema.py — trace 记录字段 SSOT + outcome 归一化（2026-11-04 诊断引入）

存在理由：trace.jsonl 的字段语义此前散落在 record_trace.py（写）与
compute_metrics.py（读）两处，且 outcome 取值无枚举约束——真实运行样本
实测出 `SUCCESS` 与 `OK` 并存，导致分派命中率被算成 0.000（真实全部成功）。
本模块把「字段名 + 取值枚举 + 归一化」收敛为唯一事实源，两侧共同引用。

SSOT 原则：
  · 字段名定义只在此处一份
  · 写端（record_trace.py）与读端（compute_metrics.py）都 import 本模块
  · 新增字段必须同时更新本文件与 harness §6 文档
"""
from __future__ import annotations

# ── trace 顶层字段（写入顺序即此顺序）──────────────────────────────────
TRACE_FIELDS = (
    'msg_id', 'task_id', 'correlation_id', 'from', 'to', 'type', 'outcome',
    'duration_ms', 'tokens_in', 'tokens_out', 'turns', 'artifacts',
    'blocking_open', 'task_type', 'routing_confidence', 'confidence',
    'gate_verdict', 'issues', 'root_cause', 'notes',
    # ── 2026-11-04 C2 新增：相位级时延可计算的三件套 ──
    'phase', 'start', 'ts',
)

# ── 时延字段契约（2026-11-04 B2：start/phase 强制）───────────────────────
# 根因：avg/peak_concurrency 与 latency_by_phase 都依赖 (start, ts, phase)
# 三元组；此前 start 缺省时静默回落到 ts ⇒ 所有任务「时长为 0」，真实并发度
# 恒为 1，指标形同虚设（诊断 §3.4 效率维度）。
# ⇒ 写端默认强制：缺任一字段即拒绝写入；只有显式 --allow-degraded 才放行，
#   且必须打 timing_degraded 标记，让读端能区分「真退化」与「合规新记录」。
# ⚠ 读端 compute_metrics.py 的「退化区间排除」纪律**不变**：历史遗留的
#   无 start 记录仍按原逻辑排除，本契约只约束新写入的记录。
REQUIRED_TIMING_FIELDS = ('phase', 'start')
TIMING_DEGRADED_FLAG = 'timing_degraded'


def validate_timing(rec: dict) -> list[str]:
    """校验新 trace 记录的时延三元组，返回问题列表（空 = 合规）。

    只做「存在性 + 类型」检查，不校验相位名合法性（那是 record_trace 的
    _is_known_phase 职责，未知相位按既有契约告警但不阻断）。
    """
    problems = []
    for f in REQUIRED_TIMING_FIELDS:
        v = rec.get(f)
        if v is None or (isinstance(v, str) and not v.strip()):
            problems.append(f'缺 {f}')
    if not problems:
        v = rec.get('ts')
        if v is None or (isinstance(v, str) and not v.strip()):
            problems.append('缺 ts')
    return problems


# ── outcome 枚举（唯一权威）──────────────────────────────────────────────
# 归一化后的合法值。写入端强制归一，读端按归一后值比较。
OUTCOME_VALUES = ('OK', 'PARTIAL', 'ERROR', 'BLOCKED', 'TIMEOUT',
                  'SILENT_FAILURE')

# 别名表：主理人按直觉写的各种同义值 → 规范值
OUTCOME_ALIASES = {
    'OK': 'OK', 'SUCCESS': 'OK', 'SUCCEED': 'OK', 'PASS': 'OK', 'DONE': 'OK',
    'ERROR': 'ERROR', 'FAILED': 'ERROR', 'FAIL': 'ERROR',
    'PARTIAL': 'PARTIAL', 'BLOCKED': 'BLOCKED', 'BLOCK': 'BLOCKED',
    'TIMEOUT': 'TIMEOUT', 'SILENT_FAILURE': 'SILENT_FAILURE',
}

# 读端兼容：历史 trace 里可能残留未归一的取值，读时同样归一
_READ_ALIASES = dict(OUTCOME_ALIASES)


def normalize_outcome(raw) -> str:
    """归一 outcome 取值（大小写不敏感）。未知值原样返回。"""
    if raw in (None, ''):
        return ''
    key = str(raw).strip().upper()
    return _READ_ALIASES.get(key, str(raw).strip())


def is_success(raw) -> bool:
    """判定一次交付是否成功（归一后 == OK）。

    这是读端的唯一成功判据——所有脚本必须走这里，否则会出现
    「写端写 SUCCESS / 读端认 OK」这类口径撕裂。
    """
    return normalize_outcome(raw) == 'OK'


def is_review_task_type(task_type) -> bool:
    """判定是否「审查类任务」——返工率的分母口径。

    判据（2026-11-04 H1 修复）：审查类 task_type 以 `review-` 开头，
    但历史上真实运行存在 task_type 漏标（空串）的情况；
    漏标会导致返工率整行消失且 exit 0（静默失效）。
    故此处只做「已知审查类」识别，不做「非审查类」排除——
    是否漏标由调用方用 warn_unclassifiable 单独告警。
    """
    return str(task_type or '').strip().startswith('review-')


# ── 审查类 task_type 白名单（SSOT，与 skills/task-router §1 对齐）────────
REVIEW_TASK_TYPES = (
    'review-structure', 'review-depth', 'review-citation',
    'review-style', 'review-score', 'review-design', 'review-visual',
    # B1-3（2026-11-04）：R4+R5 合并单次派工
    'review-proofread-score',
)
