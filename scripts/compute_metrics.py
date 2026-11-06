#!/usr/bin/env python3
"""compute_metrics.py — 过程指标(1-5) + 整章产物质量(6) 计算器

读取 {WORK_ROOT}/运行态/trace.jsonl + 工作区产物,计算:
  1. 分派命中率  (末态 outcome=OK 的任务数 / 派发任务总数——按 task_id 去重取末态,
                  E1 重试的 ERROR 被后续 RESULT 覆盖时不双扣; P2-6 口径修复)
  2. 返工率      (同 task_id 出现 ≥2 次 RESULT OK——同一任务重复成功交付才算返工;
                  ERROR→OK 的重试不算返工,单列 retry_rate; P2-6 口径修复:
                  旧口径按「R2 出现在任务名」计数,把流水线既定的第二轮审查
                  误判为返工,真实运行 2/2=1.000 恒 FAIL)
  2b. retry_rate (含 ERROR/BLOCK 行的任务占比——E1 重试强度,参考项不设门槛)
  3. blocking 占比 (blocking_open 非空任务 / 总任务)
  4. 平均轮次    (同 task_id 的 trace 行数中位数; 自报 turns 仅作参考列 — evo-16 口径修复)
  5. per-task token (in+out 累加,按 task_type; 行内 estimated:true 时报告标注)
  6. 整章产物质量 (C9, 2026-10-30 批次5)——过程指标只答「流程顺不顺」,
     本指标答「产物好不好」: ① 结构完整率(5 类必备段) ② 数据标签完整率
     (数值陈述带 [实]/[估]/[引]/[待核实]) ③ 引用核验通过率(R3 报告汇总)。
     数据源缺失 → 整体 N/A,不阻塞

输出: 文本报告 + 可选 JSON

用法:
  python3 scripts/compute_metrics.py --work-root /path/to/work [--json out.json]
"""
from __future__ import annotations
import argparse
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from _profile_loader import read_discipline, load_section7
# ── 2026-11-04 诊断 P0-1/C2/H1/H2/H3：口径统一到 trace_schema SSOT ──
from trace_schema import normalize_outcome, is_success, REVIEW_TASK_TYPES


def load_traces(work_root: Path) -> tuple[list[dict], int]:
    """读取 trace.jsonl。返回 (有效记录列表, 坏行数)。

    2026-11-04 H3：坏行原先被静默 `continue` 丢弃——指标分母被动变小，
    且无法区分「任务少」与「日志坏了」。现返回坏行计数供报告标注。
    """
    trace_file = work_root / '运行态' / 'trace.jsonl'
    if not trace_file.exists():
        return [], 0
    out = []
    bad = 0
    with open(trace_file, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                bad += 1
                continue
    return out, bad


def compute(traces: list[dict], work_root: Path | None = None,
            bad_lines: int = 0) -> dict:
    base = {
        'total_traces': 0,
        'total_tasks': 0,
        'has_estimated_tokens': False,
        'spawn_total': 0,
        'spawn_ok': 0,
        'dispatch_hit_rate': None,
        'retry_tasks': 0,
        'retry_rate': None,
        'review_total': 0,
        'review_rework': 0,
        'rework_rate': None,
        'rework_warn': None,
        'blocking_total': 0,
        'blocking_pct': None,
        'blocking_row_total': 0,
        'blocking_row_pct': None,
        'avg_turns': None,
        'self_reported_turns_median': None,
        'tokens_per_task': {},
        'by_task_type': {},
        'bad_lines': bad_lines,
        'latency_by_phase': {},
        'latency_tasks': {},
        'product_quality': _product_quality(work_root) if work_root else None,
        # ── R2：波次级效率指标（wave_time / parallel_gain）──────────
        'wave_time_ms': None,
        'parallel_gain': None,
        'wave_metrics': None,
    }
    if not traces:
        # 无 trace 不代表无产物：产物质量（[6]）仍应计算（C9）
        if work_root:
            wm = _compute_wave_metrics(work_root, traces)
            base['wave_metrics'] = wm
            base['wave_time_ms'] = (wm or {}).get('wave_time_ms')
            base['parallel_gain'] = (wm or {}).get('parallel_gain')
        return base

    # ── P2-6 口径修复(2026-10-15) ──────────────────────────────────
    # 按 task_id 去重取【末态】: E1 重试(ERROR→RESULT OK)不双扣分派命中率;
    # 返工改按「同 task_id ≥2 次 RESULT OK」判定(与文件名里的 R2 彻底解耦);
    # 重试强度单列 retry_rate(参考项,不设门槛)。
    by_task: dict[str, list[dict]] = defaultdict(list)
    for t in traces:
        tid = t.get('task_id') or ''
        by_task[tid].append(t)

    def _terminal(rows: list[dict]) -> dict:
        """末态行: 取该 task_id 最后一行(trace 为 append-only,文件序即时间序)。"""
        return rows[-1]

    dispatched = {tid: rows for tid, rows in by_task.items()
                  if any(r.get('type') in ('RESULT', 'BLOCK', 'ERROR') for r in rows)}
    spawn_total = len(dispatched)
    # ── P0-1（2026-11-04）：成功判据走 SSOT 归一，不再硬比较 'OK' ──
    # 病史：真实运行写 outcome=SUCCESS → 硬比较判负 → 分派命中率 0/4。
    spawn_ok = sum(1 for rows in dispatched.values()
                   if _terminal(rows).get('type') == 'RESULT'
                   and is_success(_terminal(rows).get('outcome')))
    dispatch_hit_rate = spawn_ok / spawn_total if spawn_total else None

    retry_tasks = {tid for tid, rows in by_task.items()
                   if any(r.get('type') in ('ERROR', 'BLOCK') for r in rows)}
    retry_rate = (len(retry_tasks) / spawn_total) if spawn_total else None

    # 返工: 同 task_id 出现 ≥2 次「RESULT outcome=OK」= 同一任务重复成功交付
    review_task_ids = {tid for tid, rows in by_task.items()
                       if any((r.get('task_type') or '').startswith('review-') for r in rows)}
    rework_task_ids = {tid for tid, rows in by_task.items()
                       if sum(1 for r in rows
                              if r.get('type') == 'RESULT'
                              and is_success(r.get('outcome'))) >= 2}
    review_total = len(review_task_ids)
    review_rework = len(review_task_ids & rework_task_ids)
    rework_rate = review_rework / review_total if review_total else None

    # ── H1（2026-11-04）：返工率不可计算时必须告警，禁止静默消失 ──
    # 病史：task_type 漏标 → review_total=0 → rework_rate=None →
    # 报告里该行整行消失、进程 exit 0，无任何告警 → 指标长期「没有数据」而不被发现。
    rework_warn = None
    if rework_rate is None:
        # 统计有多少任务缺 task_type 标注（漏标是返工率失效的根因）
        _unlabeled = sum(1 for rows in by_task.values()
                         for r in rows
                         if r.get('type') == 'RESULT' and not (r.get('task_type') or '').strip())
        rework_warn = (
            f"返工率不可计算：未识别到任何 review-* 类任务"
            f"（共 {spawn_total} 个任务，其中 {_unlabeled} 条 RESULT 行缺 task_type 标注）。"
            f"请在派工时补 --task-type review-*；否则该指标长期缺失且不报错。"
        )

    # ── H2（2026-11-04）：blocking 占比口径统一为「任务」 ──
    # 病史：实现用 trace 行数作分母，harness §6.2 文档写「总任务」→ 同数据两个数。
    # 裁决（用户 Q4 确认按建议）：以文档口径「任务」为准，
    # 同时保留行口径作为参考列，避免历史基线不可比。
    blocking_task_ids = {tid for tid, rows in by_task.items()
                         if any(r.get('blocking_open') for r in rows)}
    blocking_total = len(blocking_task_ids)
    blocking_pct = blocking_total / spawn_total if spawn_total else None
    blocking_row_total = sum(1 for t in traces if t.get('blocking_open'))
    blocking_row_pct = blocking_row_total / len(traces) if traces else None
    # 注：blocking_row_total 计的是「行」数（同一任务的 STATUS/RESULT 两行都算）

    # 平均轮次（evo-16 口径修复）: 按文档语义 = 同 task_id 的 trace 行数中位数（接力轮次,可审计）;
    # 成员自报 turns 取中位数仅作参考列（自报值不可审计,与 §2 预算对账"防谎报"原则一致）
    lines_per_task = Counter(t.get('task_id') for t in traces)
    avg_turns = statistics.median(list(lines_per_task.values())) if lines_per_task else None

    self_reported = defaultdict(int)
    for t in traces:
        tid = t.get('task_id')
        if t.get('turns'):
            self_reported[tid] = max(self_reported[tid], t.get('turns', 0))
    self_reported_turns = statistics.median(list(self_reported.values())) if self_reported else None

    tokens_per_task: dict[str, int] = defaultdict(int)
    for t in traces:
        tid = t.get('task_id')
        tokens_per_task[tid] += (t.get('tokens_in', 0) + t.get('tokens_out', 0))

    by_task_type: dict[str, dict] = defaultdict(lambda: {'count': 0, 'tokens': 0})
    for t in traces:
        tt = t.get('task_type') or 'unknown'
        by_task_type[tt]['count'] += 1
        by_task_type[tt]['tokens'] += (t.get('tokens_in', 0) + t.get('tokens_out', 0))

    # ── C2（2026-11-04）：相位级时延 —— 依赖 trace 新增的 phase/start 字段 ──
    # 优先用 duration_ms（成员自报，但可审计）；缺失时用 ts - start 兜底。
    # 无 phase 字段的历史 trace 不计入（避免把「无数据'误算成 0ms）。
    latency_by_phase: dict[str, list[int]] = defaultdict(list)
    latency_tasks: dict[str, int] = {}
    for t in traces:
        dur = int(t.get('duration_ms') or 0)
        if dur <= 0:
            dur = _delta_ms(t.get('start'), t.get('ts'))
        if dur <= 0:
            continue
        ph = (t.get('phase') or '').strip()
        if ph:
            latency_by_phase[ph].append(dur)
        tid = t.get('task_id') or ''
        if tid:
            latency_tasks[tid] = max(latency_tasks.get(tid, 0), dur)

    # ── [7] 平均并发度（P1-4，2026-11-04）────────────────────────────
    # Q2 授权：「受限于 API 速率还是 token 预算」→ 并行度**动态决定**，
    # 因此本指标**不设门槛**（设门槛等于把动态策略写死），
    # 只做观测：算出来看实际并发落在什么区间，用于定位瓶颈。
    #
    # 口径：**时间加权平均并发度**
    #   把每个任务视为区间 [start, start+duration]，
    #   对所有时间点求「同时在跑的任务数」的时间平均值。
    #   这是并发度的标准定义（area-under-concurrency-curve / 总时长）。
    #   若改用「峰值并发」会高估（只看最忙那一瞬）。
    #
    # 数据源：trace 的 start/ts/duration_ms（C2 已落地）。
    # 缺失 start 的记录**不计入**（不猜、不用 ts 硬凑，避免虚构区间）。
    concurrency = _compute_concurrency(traces)

    # ── [6] 整章产物质量（C9，2026-10-30 批次 5）─────────────────────────
    # 过程指标（[1]-[5]）只回答「流程跑得顺不顺」，不回答「产物好不好」。
    # 本指标从工作区产物直接计算三个结构化维度；数据源缺失时整体 N/A（不阻塞）。
    product = _product_quality(work_root)

    # ── R2：波次级效率指标（wave_time / parallel_gain）──────────────────
    # 数据源 = 波次状态锚点（运行态/wave_{ch##}_w{n}.json）+ trace 的
    # start/duration_ms。缺任一 → None + 说明，**不静默当 0**。
    wave_metrics = _compute_wave_metrics(work_root, traces)

    # ── R1：协议评测分数（protocol_eval_score）──────────────────────────
    # 数据源 = 协议评测结果落盘（运行态/protocol_eval.json）。
    # 无落盘 ⇒ None + 说明，**不静默当 0**（0 分会被误读成「协议全挂」）。
    protocol_eval = _read_protocol_eval(work_root)

    # ── ★I-2（v2.10.2）：决策推理链覆盖率（reasoning_chain_coverage）────
    # G4 声明的可审计性指标：三类关键决策（门禁裁决/blocking/介入根因）
    # 应附 reasoning_chain。判据 = 带 gate_verdict 或 root_cause 的 trace 行中
    # reasoning_chain 非空的比例。数据不足 → None + 说明，不静默当 0。
    key_rows = [t for t in traces
                if t.get('gate_verdict') or t.get('root_cause')]
    rc_rows = [t for t in key_rows if t.get('reasoning_chain')]
    if key_rows:
        rc_cov = len(rc_rows) / len(key_rows)
        rc_note = f'{len(rc_rows)}/{len(key_rows)} 关键决策附推理链'
    else:
        rc_cov = None
        rc_note = '无关键决策 trace 行（无 gate_verdict/root_cause）——不可计算'

    # ── ★I-3（v2.10.3）：条件产物核对覆盖率（conditional_artifacts_coverage）──
    # 数据源 = contract_check 落 trace 的观测行（notes 含 conditional-skip /
    # conditional-checked，task_type 标记激活态）。口径 = 条件产物核对中
    # 「--task-type 激活」的占比——衡量条件产物机制的真实使用率。
    cond_rows = [t for t in traces
                 if isinstance(t.get('notes'), str)
                 and t['notes'].startswith('conditional-')]
    cond_checked = [t for t in cond_rows
                    if t['notes'].startswith('conditional-checked')]
    if cond_rows:
        cond_cov = len(cond_checked) / len(cond_rows)
        cond_note = (f'{len(cond_checked)}/{len(cond_rows)} 条件产物核对被 '
                     f'--task-type 激活（其余为常规核对跳过）')
    else:
        cond_cov = None
        cond_note = '无 conditional-* 观测行——contract_check 尚未在工作区运行'

    return {
        'total_traces': len(traces),
        'total_tasks': len(by_task),
        'has_estimated_tokens': any(t.get('estimated') for t in traces),
        'spawn_total': spawn_total,
        'spawn_ok': spawn_ok,
        'dispatch_hit_rate': dispatch_hit_rate,
        'retry_tasks': len(retry_tasks),
        'retry_rate': retry_rate,
        'review_total': review_total,
        'review_rework': review_rework,
        'rework_rate': rework_rate,
        'blocking_total': blocking_total,
        'blocking_pct': blocking_pct,
        'blocking_row_total': blocking_row_total,
        'blocking_row_pct': blocking_row_pct,
        'avg_turns': avg_turns,
        'self_reported_turns_median': self_reported_turns,
        'tokens_per_task': dict(tokens_per_task),
        'by_task_type': dict(by_task_type),
        'bad_lines': bad_lines,
        'rework_warn': rework_warn,
        'latency_by_phase': {k: list(v) for k, v in latency_by_phase.items()},
        'latency_tasks': dict(latency_tasks),
        'avg_concurrency': concurrency.get('avg_concurrency'),
        'peak_concurrency': concurrency.get('peak_concurrency'),
        'concurrency_span_ms': concurrency.get('span_ms'),
        'concurrency_tasks': concurrency.get('task_count'),
        'concurrency_note': concurrency.get('note'),
        'reasoning_chain_coverage': rc_cov,
        'reasoning_chain_note': rc_note,
        'conditional_artifacts_coverage': cond_cov,
        'conditional_artifacts_note': cond_note,
        'product_quality': product,
        'wave_time_ms': (wave_metrics or {}).get('wave_time_ms'),
        'parallel_gain': (wave_metrics or {}).get('parallel_gain'),
        'wave_metrics': wave_metrics,
        'protocol_eval_score': (protocol_eval or {}).get('score'),
        'protocol_eval': protocol_eval,
    }


def _read_protocol_eval(work_root: Path | None) -> dict | None:
    """R1：协议评测分数（protocol_eval_score）。

    数据源：`运行态/protocol_eval.json`——由 `scripts/protocol_eval.py --json`
    的输出落盘（合入前的评测闸门会写这份文件）。

    口径（复诊 §3.4 指标表）：
      · **协议质量**：协议组件离线评测分数
      · **计算式**：各组件 eval 通过项 / 总项（跨组件合并）
      · **门槛**：≥0.80 方可合入；改前后对照

    数据不足（未落盘 / 文件损坏）→ 返回 None + 说明，
    **不静默当 0**——0 分会被误读成「协议全挂」，而真相是「没跑过」。
    """
    if not work_root:
        return None
    p = work_root / '运行态' / 'protocol_eval.json'
    if not p.is_file():
        return {'score': None, 'note': '未落盘协议评测结果（运行态/protocol_eval.json 不存在）'}
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError) as e:
        return {'score': None, 'note': f'协议评测结果文件损坏: {e}'}
    if not isinstance(data, dict) or 'score' not in data:
        return {'score': None, 'note': '协议评测结果结构非法（缺 score 字段）'}
    out = {
        'score': data.get('score'),
        'passed': data.get('passed'),
        'total': data.get('total'),
        'failed': data.get('failed'),
        'threshold': data.get('threshold'),
        'per_component': data.get('per_component'),
    }
    failures = data.get('failures')
    if isinstance(failures, list):
        out['failure_count'] = len(failures)
        out['failures'] = failures[:10]
    return out


def _product_quality(work_root: Path) -> dict | None:
    """整章产物质量三维度（C9）。数据不全 → 返回 None（N/A，不阻塞）。"""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from count_net_words import count_net_words
    except ImportError:
        return None

    chapters = sorted((work_root / '章节').glob('ch*')) if (work_root / '章节').is_dir() else []
    if not chapters:
        return None

    # B3（ADR-02）：数值触发词从写死兽医指标改为读 profile §7 number_triggers +
    # 通用单位模式（C-05 病灶「同规则两份口径」——与 assemble_sections 共源）。
    _discipline = read_discipline(work_root)
    _domain_terms = load_section7(work_root, _discipline, 'number_triggers')
    _domain_alt = '|'.join(re.escape(t) for t in _domain_terms)

    chapters_out = []
    n_struct_total = n_struct_ok = 0
    n_label_total = n_label_ok = 0

    for ch in chapters:
        draft = ch / 'draft.md'
        if not draft.is_file():
            continue
        text = draft.read_text(encoding='utf-8')
        entry: dict = {'chapter': ch.name}

        # ① 结构完整率：5 类必备段各自存在即 +1
        #    （章标题 / ≥1 节标题 / 图表位或图表 / 习题位 / 参考文献）
        #    习题位（v2.9.0 口径统一，2026-11-05 R3-遗留 L1a）：canonical 形式
        #    `[习题 {章}-{序}]` 与 legacy 形式 `[习题位 {节号}：…]` **都算存在**。
        #    理由：结构完整率只答「有没有习题位」，不答「格式对不对」——
        #    格式由判据 4.8b 单独判 FAIL（check_manuscript）。若此处只认 canonical，
        #    同一处缺陷会被**重复计一次**（结构扣分 + 格式 FAIL）⇒ 指标失真。
        required = {
            '章标题': re.search(r'^#\s+', text, re.M),
            '节标题': re.search(r'^##\s+', text, re.M),
            '图表': re.search(r'\[图\s*\d+-\d+|^\s*图\s*\d+-\d+', text, re.M),
            '习题位': re.search(r'\[习题\s*\d+-\d+|\[习题位\s*\d', text),
            '参考文献': re.search(r'^##\s*参考文献', text, re.M),
        }
        ok = sum(1 for v in required.values() if v)
        n_struct_total += len(required)
        n_struct_ok += ok
        entry['structure'] = f'{ok}/{len(required)}'

        # ② 数据标签完整率：数值触发词陈述句带 [实]/[估]/[引]/[待核实] 的比例
        #    触发词 = profile §7 学科指标（动态）+ 通用单位模式（兜底）
        _alt_parts = ([_domain_alt] if _domain_alt else [])
        _alt_parts.append(r'[%％]|\d+(\.\d+)?\s*(?:%|％|倍|次|天|日|周|年|mg|ml|ug)')
        trigger = re.compile(
            rf'[^。！？\n]*(?:{"|".join(_alt_parts)})[^。！？\n]*[。！？]', re.I)
        label = re.compile(r'\[(?:实|估|引|待核实)[^\]]*\]')
        # 口径修正（R3 真实跑批暴露，2026-11-05）：标签写在**句末标点之后**
        # （教材通用写法「……产蛋率93%。[实](PMID: 12345678)」）时，
        # 句级正则只截到句号 ⇒ 标签落在匹配范围外 ⇒ 误判「未标注」。
        # 实测同一份稿：行级口径 107/107 = 100%，句级口径仅 20/105 = 19%。
        # 修法：命中句后再看**紧邻其后**的标签，若贴在该句之后则计入。
        # 不放宽触发条件，只修标签归属判定——否则该指标长期误报 FAIL。
        label_tail = re.compile(r'^[。！？\s]*\[(?:实|估|引|待核实)[^\]]*\]')
        # ★ v2.9.0（2026-11-05 R3-遗留 L2）：分母必须是「**带具体数值**」的陈述句。
        #   病灶（真实章 ch_01 实测）：触发词命中 188 句，其中 **155 句只有触发词
        #   而无数值**（如「本病多见于日龄较大鸡群」「免疫程序规范与否影响保护率」）
        #   ⇒ 原口径把这类**无数值**定性描述计入分母 ⇒ 覆盖率被系统性稀释
        #   （真值约 0.21，口径读数 0.17）。
        #   协议原文是「每条**学科数据**必须带标签」⇒ 分母只该算「数据句」。
        #   ⇒ 增「具体数值」判据：数字 + 单位/百分号（纯数量词如「3号舍」不算数据）。
        _has_value = re.compile(
            r'\d+(?:\.\d+)?\s*(?:%|％|倍|次|天|日|周|月|年|小时|分钟|'
            r'mg|kg|ml|L|羽|只|例|个|项|种|元|万元|亿|万|℃|度|克|吨)')
        n_trig = 0
        n_lab = 0
        n_trig_nodata = 0
        for mt in trigger.finditer(text):
            seg = mt.group(0)
            if not _has_value.search(seg):
                # 触发词命中但**无数值** ⇒ 不是数据句，不计入分母（单列计数）
                n_trig_nodata += 1
                continue
            n_trig += 1
            if label.search(seg):
                n_lab += 1
                continue
            tail = text[mt.end():mt.end() + 120].lstrip('。！？\n \t')
            if label_tail.match(tail) or label.match(tail):
                n_lab += 1
        n_label_total += n_trig
        n_label_ok += n_lab
        entry['labels'] = f'{n_lab}/{n_trig}' if n_trig else 'N/A(无数值陈述)'
        if n_trig_nodata:
            entry['labels_no_value'] = f'触发词命中但无数值 {n_trig_nodata} 句（不计入分母）'

        # ③ 引用核验通过率：从 R3 审查报告抓核验汇总（无报告 → N/A）
        pass_rate = None
        for rep in sorted((ch / 'review').glob('round*_report.md')) if (ch / 'review').is_dir() else []:
            rt = rep.read_text(encoding='utf-8')
            m = re.search(r'核验\s*(\d+)\s*条\s*\|?\s*通过\s*(\d+)', rt)
            if m and int(m.group(1)) > 0:
                pass_rate = int(m.group(2)) / int(m.group(1))
        if pass_rate is not None:
            entry['citation_pass'] = f'{pass_rate:.2f}'
        else:
            entry['citation_pass'] = 'N/A(无审查报告)'
        chapters_out.append(entry)

    if not chapters_out:
        return None
    struct_rate = n_struct_ok / n_struct_total if n_struct_total else None
    label_rate = n_label_ok / n_label_total if n_label_total else None
    rates = [float(c['citation_pass']) for c in chapters_out
             if not str(c['citation_pass']).startswith('N/A')]
    citation = sum(rates) / len(rates) if rates else None
    return {
        'chapters': chapters_out,
        'structure_rate': struct_rate,
        'label_rate': label_rate,
        'citation_pass_rate': citation,
        'thresholds': {'structure_rate': 1.00, 'label_rate': 0.95, 'citation_pass_rate': 0.95},
    }


def render(m: dict) -> str:
    lines = ['=' * 60, '智能体团队 5 项关键指标', '=' * 60]
    lines.append(f'总 trace 数: {m["total_traces"]}  |  任务数(按 task_id 去重): {m["total_tasks"]}')
    lines.append('')
    lines.append('[1] 分派命中率 (末态 OK 任务 / 派发任务——按 task_id 去重,重试不双扣)')
    if m['dispatch_hit_rate'] is not None:
        lines.append(f'    {m["spawn_ok"]}/{m["spawn_total"]} = {m["dispatch_hit_rate"]:.3f}')
        rr = m.get('retry_rate')
        if rr is not None:
            lines.append(f'    (参考) retry_rate = {m["retry_tasks"]}/{m["spawn_total"]} = {rr:.2f}'
                         '  (E1 重试强度,不设门槛)')
        lines.append(f'    门槛 ≥ 0.80  {"✓ PASS" if m["dispatch_hit_rate"] >= 0.80 else "✗ FAIL"}')
    else:
        lines.append('    暂无数据')

    lines.append('')
    lines.append('[2] 返工率 (同 task_id ≥2 次成功交付的 review 任务 / review 任务数)')
    if m['rework_rate'] is not None:
        lines.append(f'    {m["review_rework"]}/{m["review_total"]} = {m["rework_rate"]:.3f}')
        lines.append(f'    门槛 ≤ 0.30  {"✓ PASS" if m["rework_rate"] <= 0.30 else "✗ FAIL"}')
    else:
        lines.append('    ⚠ 不可计算（不是「无返工」，是数据不足）')
        if m.get('rework_warn'):
            lines.append(f'      原因: {m["rework_warn"]}')

    lines.append('')
    lines.append('[3] blocking 占比 (blocking_open 非空【任务】/ 总任务)')
    if m['blocking_pct'] is not None:
        lines.append(f'    {m["blocking_total"]}/{m["spawn_total"]} = {m["blocking_pct"]:.3f}')
        lines.append(f'    门槛 ≤ 0.10  {"✓ PASS" if m["blocking_pct"] <= 0.10 else "✗ FAIL"}')
        row_pct = m.get('blocking_row_pct')
        if row_pct is not None:
            lines.append(f'    (参考) 行口径 = {m.get("blocking_row_total")}/{m["total_traces"]} = {row_pct:.3f}')
    else:
        lines.append('    暂无数据')

    lines.append('')
    lines.append('[4] 平均轮次 (同 task_id 的 trace 行数中位数 — 接力轮次,可审计)')
    if m['avg_turns'] is not None:
        lines.append(f'    median = {m["avg_turns"]}')
        sr = m.get('self_reported_turns_median')
        if sr is not None:
            lines.append(f'    (参考) 成员自报 turns 中位数 = {sr} (不可审计,不进门禁)')
        lines.append(f'    门槛 ≤ 6  {"✓ PASS" if m["avg_turns"] <= 6 else "✗ FAIL"}')
    else:
        lines.append('    暂无数据')

    lines.append('')
    lines.append('[5] per-task token (按 task_type 累加)')
    if m['by_task_type']:
        for tt, info in sorted(m['by_task_type'].items(), key=lambda x: -x[1]['tokens']):
            lines.append(f'    {tt:24s}  {info["count"]:3d} spawn  {info["tokens"]:>8d} tokens')
        if m.get('has_estimated_tokens'):
            lines.append('    ⚠ 含估算值(estimated:true)——平台未暴露真实用量,按字符数÷3 估,不可审计')
    else:
        lines.append('    暂无数据')

    lines.append('')
    lines.append('[6] 相位级时延 (C2: 需 trace 携带 phase/start 字段)')
    lat = m.get('latency_by_phase') or {}
    if lat:
        for ph in sorted(lat, key=lambda k: -max(lat[k])):
            vals = sorted(lat[ph])
            p50 = vals[len(vals) // 2]
            lines.append(f'    {ph:18s} n={len(vals):2d}  P50={p50/1000:.1f}s  max={max(vals)/1000:.1f}s')
        lt = m.get('latency_tasks') or {}
        if lt:
            lines.append(f'    任务级: n={len(lt)}  最慢={max(lt.values())/1000:.1f}s')
    else:
        lines.append('    ⚠ 无相位时延数据（trace 缺 phase/start 字段——新写入的记录才有）')

    lines.append('')
    pq = m.get('product_quality')
    lines.append('[7] 整章产物质量 (C9: 结构完整率 / 数据标签完整率 / 引用核验通过率)')
    if pq:
        sr, lr, cr = pq['structure_rate'], pq['label_rate'], pq['citation_pass_rate']
        th = pq['thresholds']
        lines.append(f'    ① 结构完整率   : '
                     + (f'{sr:.3f}  门槛 ≥{th["structure_rate"]:.2f}  '
                        f'{"✓ PASS" if sr >= th["structure_rate"] else "✗ FAIL"}' if sr is not None else 'N/A'))
        lines.append(f'    ② 标签完整率   : '
                     + (f'{lr:.3f}  门槛 ≥{th["label_rate"]:.2f}  '
                        f'{"✓ PASS" if lr >= th["label_rate"] else "✗ FAIL"}' if lr is not None else 'N/A(无数值陈述)'))
        lines.append(f'    ③ 引用核验通过 : '
                     + (f'{cr:.3f}  门槛 ≥{th["citation_pass_rate"]:.2f}  '
                        f'{"✓ PASS" if cr >= th["citation_pass_rate"] else "✗ FAIL"}' if cr is not None else 'N/A(无审查报告)'))
        for c in pq['chapters']:
            lines.append(f'      - {c["chapter"]}: 结构 {c["structure"]} | 标签 {c["labels"]} | 核验 {c["citation_pass"]}')
    else:
        lines.append('    N/A（工作区无 章节/ 产物，不阻塞）')

    lines.append('')
    lines.append('[8] 平均并发度 (P1-4 · 时间加权 · 观测项·不设门槛)')
    ac = m.get('avg_concurrency')
    if ac is not None:
        lines.append(f'    平均并发 = {ac}   峰值并发 = {m.get("peak_concurrency")}   '
                     f'时间跨度 = {(m.get("concurrency_span_ms") or 0) / 1000:.1f}s   '
                     f'可判定任务 = {m.get("concurrency_tasks")}')
        lines.append('    无门槛（Q2：并行度由 API 速率 / token 预算动态决定，'
                     '固定阈值等于把动态策略写死）——本项仅作瓶颈定位')
        if m.get('concurrency_note'):
            lines.append(f'    ({m["concurrency_note"]})')
    else:
        lines.append('    ⚠ 不可计算（不是「并发为 0」，是数据不足）')
        if m.get('concurrency_note'):
            lines.append(f'      原因: {m["concurrency_note"]}')

    # ── R2：波次级效率指标 ─────────────────────────────────────────
    lines.append('')
    lines.append('[9] 波次级效率 (R2 · wave_time / parallel_gain · 观测项·不设门槛)')
    wm = m.get('wave_metrics')
    if wm and wm.get('waves'):
        lines.append(f'    波次墙钟合计 = {(wm.get("wave_time_ms") or 0) / 1000:.1f}s   '
                     f'串行基准 = {(wm.get("serial_baseline_ms") or 0) / 1000:.1f}s   '
                     f'并行收益 = {wm.get("parallel_gain")}×   '
                     f'波次数 = {wm.get("wave_count")}')
        lines.append('    口径：parallel_gain = 串行基准耗时 ÷ 波次墙钟耗时；'
                     '1.0 = 无并行收益（退化为串行）')
        for w in wm['waves']:
            lines.append(f'      w{w.get("wave_id")} {w.get("chapter")} '
                         f'节={w.get("sections")} 墙钟={w.get("wave_time_ms")}ms '
                         f'串行基准={w.get("serial_baseline_ms")}ms '
                         f'gain={w.get("parallel_gain")}×')
        if wm.get('note'):
            lines.append(f'    ({wm["note"]})')
    else:
        lines.append('    ⚠ 不可计算（不是「耗时为 0」，是数据不足）')
        if wm and wm.get('note'):
            lines.append(f'      原因: {wm["note"]}')
        else:
            lines.append('      原因: 无 波次状态锚点（运行态/wave_{ch##}_w{n}.json）'
                         '——须先跑 scheduler.py --mode sections --write-wave-state')

    # ── R1：协议评测分数 ────────────────────────────────────────────
    lines.append('')
    lines.append('[10] 协议评测分数 (R1 · protocol_eval_score · 门槛项·≥0.80 方可合入)')
    pe = m.get('protocol_eval')
    if pe and pe.get('score') is not None:
        passed = pe.get('passed')
        total = pe.get('total')
        lines.append(f'    协议评测总分 = {pe.get("score")}   '
                     f'通过 {passed}/{total}   门槛 = {pe.get("threshold")}')
        lines.append('    口径：各组件 eval 通过项 ÷ 总项（跨组件合并）；'
                     '合入前必须 ≥0.80，否则回滚该条改动')
        for pc in (pe.get('per_component') or []):
            lines.append(f'      {pc.get("component"):26s} {pc.get("passed")}/'
                         f'{pc.get("total")} ({pc.get("score")})')
        for f in (pe.get('failures') or [])[:5]:
            lines.append(f'      ✗ [{f.get("id")}] {f.get("component")} / '
                         f'{f.get("name")}: {f.get("detail")}')
    else:
        lines.append('    ⚠ 不可计算（不是「分数为 0」，是数据不足）')
        if pe and pe.get('note'):
            lines.append(f'      原因: {pe["note"]}')
        else:
            lines.append('      原因: 无协议评测落盘（运行态/protocol_eval.json）'
                         '——须先跑 protocol_eval.py --json 并落盘')

    # ── [11] ★I-2（v2.10.2）：决策推理链覆盖率（可审计性）──
    lines.append('[11] 决策推理链覆盖率 (★G4/I-2 · reasoning_chain_coverage · 观测项·渐进爬坡目标 100%)')
    rc = m.get('reasoning_chain_coverage')
    if rc is not None:
        lines.append(f'    {m.get("reasoning_chain_note")} = {rc:.2f}')
        lines.append('    口径：带 gate_verdict/root_cause 的关键决策行中 reasoning_chain '
                     '非空占比；「不支持（主题错配）」类语义判定不在本指标内')
    else:
        lines.append(f'    ⚠ 不可计算（{m.get("reasoning_chain_note")}）')

    # ── [12] ★I-3（v2.10.3）：条件产物核对覆盖率（机制使用率）──
    lines.append('[12] 条件产物核对覆盖率 (★H2/I-3 · conditional_artifacts_coverage · 观测项)')
    cc = m.get('conditional_artifacts_coverage')
    if cc is not None:
        lines.append(f'    {m.get("conditional_artifacts_note")} = {cc:.2f}')
        lines.append('    口径：conditional-* 观测行中 --task-type 激活占比；'
                     '0.00 = 机制从未被激活（常规核对全部跳过条件产物）')
    else:
        lines.append(f'    ⚠ 不可计算（{m.get("conditional_artifacts_note")}）')

    lines.append('=' * 60)
    return '\n'.join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--work-root', required=True)
    ap.add_argument('--json', help='输出 JSON 路径')
    ap.add_argument('--report-only', action='store_true',
                    help='只出报告不因指标 fail 而非零退出（默认：产物质量三维度的 FAIL 会影响退出码）')
    args = ap.parse_args()

    traces, bad_lines = load_traces(Path(args.work_root))
    m = compute(traces, work_root=Path(args.work_root), bad_lines=bad_lines)
    if bad_lines:
        # H3：坏行不可静默——必须在报告里显式标注「数据不完整」
        print(f'[WARN] trace.jsonl 有 {bad_lines} 条坏行已被跳过——'
              f'指标分母偏小，数据不完整（2026-11-04 H3）', file=sys.stderr)
    print(render(m))

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'JSON: {args.json}')

    # 退出码:任一指标 fail 则 1
    bad = []
    if m['dispatch_hit_rate'] is not None and m['dispatch_hit_rate'] < 0.80:
        bad.append('dispatch_hit_rate')
    if m['rework_rate'] is not None and m['rework_rate'] > 0.30:
        bad.append('rework_rate')
    if m['blocking_pct'] is not None and m['blocking_pct'] > 0.10:
        bad.append('blocking_pct')
    if m['avg_turns'] is not None and m['avg_turns'] > 6:
        bad.append('avg_turns')

    # ── D-10 修复（2026-10-30 批次 B）───────────────────────────────────
    # 旧实现：指标 [6] 产物质量三维度（结构/标签/核验）会渲染「✗ FAIL」，
    # 但**不参与退出码判定** → 红灯不阻塞任何流程（实测结构完整率 0.200
    # 渲染 FAIL，exit 仍为 0）。现默认即参与判定；另提供 --report-only
    # 供「只想看报告不想被退出码卡住」的场景（默认 stricter 是正确方向：
    # 渲染出 FAIL 却不反映在退出码上 = 自相矛盾）。
    pq = m.get('product_quality')
    if pq and not args.report_only:
        th = pq.get('thresholds', {})
        for key, label in (('structure_rate', '产物结构完整率'),
                           ('label_rate', '数据标签完整率'),
                           ('citation_pass_rate', '引用核验通过率')):
            v = pq.get(key)
            limit = th.get(key)
            if v is not None and limit is not None and v < limit:
                bad.append(f'{label}({v:.3f}<{limit:.2f})')

    return 1 if bad else 0



def _compute_concurrency(traces: list[dict]) -> dict:
    """时间加权平均并发度（P1-4）。

    口径：把每个可判定区间的任务视为 [t0, t1]，
    全部区间的「同时在跑任务数」对时间求加权平均。

    算法（扫描线）：
      1. 收集所有区间端点，排序去重
      2. 对每个相邻端点区间 [e_i, e_{i+1})，数一下有多少任务区间覆盖它
      3. 加权平均 = Σ(并发数 × 区间长度) / 总时间跨度

    **不设门槛**（Q2）：并行度由 API 速率 / token 预算动态决定，
    设一个固定阈值等于把动态策略写死。本指标只作观测与瓶颈定位。

    数据不足（无任何可判定区间）→ 返回 None + 说明，**不静默当 0**。
    """
    intervals: list[tuple[int, int]] = []
    missing = 0
    degenerate = 0
    for t in traces:
        start = _parse_ts(t.get('start'))
        if start is None:
            missing += 1
            continue
        dur = int(t.get('duration_ms') or 0)
        if dur <= 0:
            dur = _delta_ms(t.get('start'), t.get('ts'))
        if dur <= 0:
            # **退化区间**（2026-11-04 真实样本）：真实运行写 trace 时
            # start 与 ts 是**同一时刻**（记录于任务结束），且 duration_ms=0
            # → 该记录不构成任何时间区间，**不可判定**。
            # 若给它一个「极小窗口」（dur=1），会凭空造出 9 个 1ms 的
            # 伪区间，把平均并发算成 ≈0.0 —— 那是虚构，不是观测。
            # 正确处置：排除，并在 note 里说明。
            degenerate += 1
            continue
        intervals.append((start, start + dur))

    if not intervals:
        parts = []
        if missing:
            parts.append(f'{missing} 条缺 start')
        if degenerate:
            parts.append(f'{degenerate} 条 start==ts 且 duration_ms=0（退化区间）')
        return {'avg_concurrency': None, 'peak_concurrency': None,
                'span_ms': 0, 'task_count': 0,
                'note': ('不可计算：' + '、'.join(parts) if parts else '无 trace 记录')
                        + '——不是「并发为 0」，是数据不足'
                        + ('；真实运行需在任务**开始时**记录 start、在**结束时**'
                           '记录 duration_ms' if degenerate else '')}

    events: list[tuple[int, int]] = []
    for s, e in intervals:
        events.append((s, 1))
        events.append((e, -1))
    events.sort()

    # 扫描线：逐端点推进，累计「并发数 × 时长」
    total_weighted = 0
    span_start = intervals[0][0]
    span_end = max(e for _, e in intervals)
    cur = 0
    prev = events[0][0]
    peak = 0
    for point, delta in events:
        if point > prev:
            total_weighted += cur * (point - prev)
        cur += delta
        peak = max(peak, cur)
        prev = point

    span = span_end - span_start
    avg = (total_weighted / span) if span > 0 else None
    return {
        'avg_concurrency': round(avg, 3) if avg is not None else None,
        'peak_concurrency': peak,
        'span_ms': span,
        'task_count': len(intervals),
        'note': (f'{missing} 条缺 start 已排除' if missing else ''),
    }


def _compute_wave_metrics(work_root: Path | None,
                           traces: list[dict]) -> dict | None:
    """波次级效率指标（R2）：`wave_time` 与 `parallel_gain`。

    数据源：`运行态/wave_{ch##}_w{n}.json`（R2 波次状态锚点）+ `trace.jsonl`。

    【join 键】波次状态里的 `contract[节号].task_id` 与 trace 的 `task_id`
    格式完全一致（`ch01-PRODUCE-R1-节1.10`，由 `scheduler.py` 生成）⇒ 不需要
    引入第二套 ID 体系。

    ── `wave_time`（毫秒）──────────────────────────────────────────
    单个波次的**墙钟耗时** = 波内最早 start → 最晚结束。
    波内并行 ⇒ 墙钟远小于各节耗时之和；这是「并行到底省了多少」的分子。

    ── `parallel_gain`（倍数）──────────────────────────────────────
    **串行基准耗时 ÷ 实际波次墙钟耗时**：
        serial_baseline = Σ(波内各节的可判定耗时)
        parallel_gain    = serial_baseline / wave_time
    语义 = 「同样这些节，串行跑要花 wave_time×gain 的时间；波内并行实际只花
    wave_time」⇒ gain=1.0 表示**完全没有并行收益**（退化为串行），
    gain=3.0 表示 3 倍加速。

    为什么不用 `Σduration / wave_time`：那个值等于「波内平均并发度」，
    与既有的 `avg_concurrency` 指标重复；`parallel_gain` 用**串行基准**
    做分母，度量的是**本波次**的并行收益，可与 avg_concurrency 互为佐证。

    数据不足（无波次状态 / 无可判定 trace 区间）→ 返回 None + 说明，
    **不静默当 0**（与 `_compute_concurrency` 同一纪律）。
    """
    if not work_root:
        return None
    wave_dir = work_root / '运行态'
    if not wave_dir.is_dir():
        return None
    state_files = sorted(p for p in wave_dir.iterdir()
                         if p.name.startswith('wave_ch') and p.name.endswith('.json'))
    if not state_files:
        return None

    # trace 索引：task_id → (start_ms, duration_ms)
    tindex: dict[str, tuple[int, int]] = {}
    for t in traces:
        tid = str(t.get('task_id') or '')
        if not tid:
            continue
        start = _parse_ts(t.get('start'))
        if start is None:
            continue
        dur = int(t.get('duration_ms') or 0)
        if dur <= 0:
            dur = _delta_ms(t.get('start'), t.get('ts'))
        if dur <= 0:
            continue
        prev = tindex.get(tid)
        if prev is None or dur > prev[1]:
            tindex[tid] = (start, dur)

    waves: list[dict] = []
    total_wall = 0
    total_serial = 0
    n_gain = 0
    skipped = 0
    for p in state_files:
        try:
            st = json.loads(p.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            skipped += 1
            continue
        if not isinstance(st, dict) or not st.get('schema', '').startswith('stt.wave_state'):
            skipped += 1
            continue
        contract = st.get('contract') or {}
        # 收集本波次内可判定的 trace 区间
        ivs: list[tuple[int, int]] = []
        for sec, entry in contract.items():
            tid = (entry or {}).get('task_id')
            hit = tindex.get(str(tid)) if tid else None
            if hit:
                ivs.append(hit)
        if not ivs:
            skipped += 1
            continue
        wave_start = min(s for s, _ in ivs)
        wave_end = max(s + d for s, d in ivs)
        wall = wave_end - wave_start
        serial = sum(d for _, d in ivs)
        gain = round(serial / wall, 3) if wall > 0 else None
        waves.append({
            'wave_id': st.get('wave_id'),
            'chapter': st.get('chapter'),
            'sections': st.get('sections'),
            'wave_time_ms': wall,
            'serial_baseline_ms': serial,
            'parallel_gain': gain,
            'sections_measured': len(ivs),
        })
        total_wall += wall
        total_serial += serial
        if gain is not None:
            n_gain += 1

    if not waves:
        return {'waves': [], 'wave_time_ms': None, 'parallel_gain': None,
                'note': f'有 {len(state_files)} 个波次状态文件，但无一匹配到'
                        f'可判定的 trace 区间（需 trace 带 start 与 duration_ms）'
                        f'——不是「耗时为 0」，是数据不足'}

    overall_gain = (round(total_serial / total_wall, 3)
                    if total_wall > 0 and n_gain else None)
    return {
        'waves': waves,
        'wave_time_ms': total_wall,
        'wave_count': len(waves),
        'parallel_gain': overall_gain,
        'serial_baseline_ms': total_serial,
        'note': (f'{skipped} 个波次状态未匹配到可判定 trace 区间'
                 if skipped else ''),
    }


def _parse_ts(raw) -> int | None:
    """ISO8601 → epoch 毫秒。解析失败返回 None（不猜）。"""
    if not raw:
        return None
    s = str(raw).strip().replace('Z', '+00:00')
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _delta_ms(start: str | None, end: str | None) -> int:
    """计算两个 ISO8601 时刻的毫秒差；无法解析返回 0。

    兼容带/不带时区的 ISO8601（naive 视为 UTC），解析失败一律返回 0
    （不抛异常——指标计算绝不能因单条脏数据中断）。
    """
    if not start or not end:
        return 0
    try:
        from datetime import datetime as _dt
        f = '%Y-%m-%dT%H:%M:%S'
        s_txt, e_txt = str(start), str(end)
        # 截掉小数秒与时区后缀，按秒精度解析
        def _parse(t: str):
            t = t.split('+')[0].split('Z')[0]
            if '.' in t:
                t = t.split('.')[0]
            return _dt.strptime(t, f)
        delta = (_parse(e_txt) - _parse(s_txt)).total_seconds()
        return int(delta * 1000)
    except Exception:
        return 0


if __name__ == '__main__':
    sys.exit(main())
