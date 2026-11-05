#!/usr/bin/env python3
"""record_trace.py — 智能体团队 trace 写入器

每个成员完成 dispatch 后调用,append 一行 JSON 到 {WORK_ROOT}/运行态/trace.jsonl
schema 与 harness §6 对齐。

用法:
  python3 scripts/record_trace.py \\
    --work-root /path/to/work \\
    --task-id ch06-PRODUCE-R2 \\
    --from subject-writer \\
    --to smart-textbook-team-team-lead \\
    --type RESULT \\
    --outcome OK \\
    --duration-ms 128000 \\
    --tokens-in 8000 --tokens-out 12000 \\
    --artifacts "章节/ch06/draft.md"
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# ── B2（2026-11-04）：时延字段契约的 SSOT ─────────────────────────────────
# 只借用 trace_schema 的 REQUIRED_TIMING_FIELDS / validate_timing /
# TIMING_DEGRADED_FLAG；outcome 归一化仍走本文件既有实现（不重复搬移）。
sys.path.insert(0, str(Path(__file__).resolve().parent))
import trace_schema as tsc  # noqa: E402

# ── ADR-05（批次 B4）：信封全字段解析 ─────────────────────────────────────
# harness §1 消息信封模板的完整字段集（唯一 SSOT）。--from-envelope 此前只
# 解析 from/to/task_id/type/correlation_id 5 字段，其余字段「trace 与信封两张皮」
# （A-09/A-26）；现全字段解析并落入 trace 记录 envelope 子对象 + 核心字段平铺。
# ★G4（v2.10）：19 → 21 字段——新增 reasoning_chain（决策推理链）与
# divergence（分歧记录）；三类关键决策（门禁裁决/blocking/介入根因）必附
# reasoning_chain，缺失由 CLI WARN（渐进接入），非法 JSON 拒收。
ENVELOPE_FIELDS = (
    'agent_id', 'task_id', 'phase', 'status', 'confidence', 'deliverable_summary',
    'evidence', 'issues', 'next_agent_hint', 'metrics', 'msg_id', 'correlation_id',
    'type', 'from', 'to', 'context_refs', 'state_patch', 'ts', 'payload',
    'reasoning_chain', 'divergence',
)
# 信封 status（小写）→ trace outcome 映射（harness §1「status 取值」）
ENVELOPE_STATUS_MAP = {
    'success': 'OK', 'partial': 'PARTIAL', 'failed': 'ERROR', 'blocked': 'BLOCKED',
}

# ── outcome 归一化（2026-11-04 诊断 P0-1）───────────────────────────────
# 病史（真实运行样本实证）：主理人按直觉写 `--outcome SUCCESS`，而
# compute_metrics.py 严格比较 `outcome == 'OK'` → 真实运行的 4 个任务
# 全部被判为「未成功」，分派命中率算成 0/4 = 0.000，而实际全部成功。
# 根因：outcome 是自由文本（argparse 无 choices），但下游按枚举硬比较。
# 修法：写入端做归一化（SUCCESS→OK 等价映射），并对未知值告警。
# SSOT = scripts/trace_schema.py（写端与读端共同引用，避免双写漂移）。
from trace_schema import (  # noqa: E402
    OUTCOME_ALIASES as _ALIASES,
    OUTCOME_VALUES as _KNOWN_OUTCOMES,
    normalize_outcome as _normalize,
)

OUTCOME_ALIASES = _ALIASES
KNOWN_OUTCOMES = set(_KNOWN_OUTCOMES)


def normalize_outcome(raw: str) -> tuple[str, str | None]:
    """归一 outcome 取值。返回 (归一后值, 告警信息或 None)。

    大小写不敏感；未知值原样保留（不丢信息），但返回告警文本。
    """
    if not raw:
        return '', None
    norm = _normalize(raw)
    key = str(raw).strip().upper()
    if key in OUTCOME_ALIASES:
        if norm != raw:
            return norm, f"outcome 归一化: {raw!r} → {norm!r}"
        return norm, None
    return raw, (f"未知 outcome 取值 {raw!r}（已知: "
                 f"{'/'.join(sorted(KNOWN_OUTCOMES))}）——已原样保留，"
                 f"但下游按枚举比较，可能不被计入")


def _is_known_phase(phase: str) -> bool:
    """校验相位名是否落在 progress.py 的 PHASE_ORDER（含粗粒度别名）。

    相位 SSOT 唯一权威源 = scripts/progress.py 的 PHASE_ORDER；
    此处动态读取，避免在 record_trace.py 里复述一份（防双写漂移）。
    读取失败时保守返回 True（不误伤正常写入）。
    """
    try:
        import progress as _progress  # 同目录
        known = set(_progress.PHASE_ORDER)
        known |= set(getattr(_progress, 'PHASE_ALIAS', {}) or {})
        known |= set(getattr(_progress, 'LEGACY_PHASE', {}) or {})
        known |= set(getattr(_progress, 'LEGACY_PHASE', {}) or {})
        return phase in known
    except Exception:
        return True
# 介入协议触发阈值（ADR-05 §5.2：同问题打回 ≥2 次；SSOT = pipeline §介入协议）
REJECT_INTERVENTION_THRESHOLD = 2


def main() -> int:
    ap = argparse.ArgumentParser(description='trace.jsonl 写入器 + tokens 对账器')
    sub = ap.add_subparsers(dest='cmd')

    # G6: tokens 对账子命令（确定性累加，替代手工 patch）
    p_tok = sub.add_parser('tokens', help='从 trace.jsonl 累加 tokens（编排者每 gate 后执行，patch 黑板 budget.tokens_used）')
    p_tok.add_argument('--work-root', required=True)

    ap.add_argument('--work-root', required=False, help='WORK_ROOT 根目录')
    ap.add_argument('--task-id', required=False)
    ap.add_argument('--correlation-id', default='', help='缺省取 task_id 前缀(ch##)')
    ap.add_argument('--from', dest='src', required=False, help='from 成员 ID')
    ap.add_argument('--to', dest='dst', required=False, help='to 成员/编排 ID')
    ap.add_argument('--type', required=False, choices=['RESULT', 'BLOCK', 'ERROR', 'STATUS', 'NEED_INPUT'])
    ap.add_argument('--msg-id', default='', help='缺省自动生成')
    ap.add_argument('--outcome', default='',
                    help='OK / ERROR / BLOCKED / TIMEOUT / PARTIAL（写入端自动归一：'
                         'SUCCESS→OK 等；未知值保留但告警）')
    ap.add_argument('--duration-ms', type=int, default=0)
    ap.add_argument('--phase', default='',
                    help='相位名（13 态业务态或 23 相位物理名，如 PRODUCE-R2）——'
                         '写入顶层字段，使相位级时延可计算（2026-11-04 诊断 C2）')
    ap.add_argument('--start', default='',
                    help='任务开始时刻 ISO8601（带时区）——与 ts 配对算单任务时延；'
                         'B2 起为必填（缺省回落 ts 会让 duration=0、真实并发度恒 1），'
                         '仅 --allow-degraded 时才允许回落')
    ap.add_argument('--allow-degraded', action='store_true',
                    help='显式允许「缺 phase/start」的退化记录（写入 timing_degraded=true 标记）。'
                         '默认严格拒绝；仅用于兼容历史调用方/排障，禁止常态使用')
    ap.add_argument('--tokens-in', type=int, default=0)
    ap.add_argument('--tokens-out', type=int, default=0)
    ap.add_argument('--turns', type=int, default=0)
    ap.add_argument('--artifacts', default='', help='逗号分隔的产物路径')
    ap.add_argument('--blocking-open', default='', help='逗号分隔的 blocking 列表')
    ap.add_argument('--task-type', default='', help='router 标注的 task_type')
    ap.add_argument('--routing-conf', type=float, default=None, help='routing_confidence')
    ap.add_argument('--notes', default='', help='自由备注')
    ap.add_argument('--estimated', action='store_true',
                    help='tokens 为估算值(字符数÷3 口径)——平台未暴露真实用量时必须打此标,'
                         'compute_metrics 报告将标注「不可审计」(P2-6/LE-20261015-04)')
    ap.add_argument('--from-envelope', default=None,
                    help='成员回传信封 JSON 文件路径——传入后 from/to/task_id/type 以信封为准'
                         '(C14, 2026-10-30): CLI 自填值与信封不一致时以信封为准并 WARN,'
                         '消除「trace 与信封两张皮」;信封缺 from/to 时拒收(exit 2)。'
                         'ADR-05 + ★G4: 21 字段全解析,输出 ENVELOPE_FIELDS_PARSED=n/21')
    # ── ADR-05（批次 B4）：硬门槛落盘的 4 个新 trace 字段 + 打回计数 ──
    ap.add_argument('--confidence', type=float, default=None,
                    help='置信度 0-100（信封 confidence 同源;两处不一致以信封为准）')
    ap.add_argument('--gate-verdict', default='',
                    help='JSON 化 pass-fail 清单,如 \'{"gate1":"pass","gate2":"fail"}\'')
    ap.add_argument('--issues', default='', help='自评问题清单（逗号分隔）')
    ap.add_argument('--root-cause', default='', choices=['', 'A', 'B', 'C', 'D'],
                    help='介入协议根因（A 补证据/B 改指令/C 拆步骤/D 停机报用户）')
    ap.add_argument('--reject-key', default='',
                    help='打回计数键 "<correlation_id>|<问题指纹>"——写入时累加 '
                         '运行态/reject-counts.json;计数 ≥2 自动触发介入协议'
                         '（ADR-05 §5.2,禁止手工计数）。`appeal|` 前缀键 = 申诉计数'
                         '（#70 判据 A2:同一指纹申诉 ≤1 次）,不触发介入协议'
                         '（progress.py rejects 对其显示「申诉已用」）')
    # ── ★G4（v2.10）：决策推理链 + 分歧记录（信封 19→21 字段扩展）──
    ap.add_argument('--reasoning-chain', default='',
                    help='JSON 化决策推理链（★G4）: {"decision","criteria_refs",'
                         '"evidence_refs","computation","alternatives_considered"}——'
                         '四道门禁裁决 / examiner blocking / 介入根因三类关键决策必附;'
                         '判据引用须指向 SSOT 文件 §节。缺失仅 WARN（渐进接入,不拒收）')
    ap.add_argument('--divergence', default='',
                    help='JSON 化分歧记录（★G4）: {"parties","issue","resolution",'
                         '"rule_ref"}——审查与写作有分歧时必附;无分歧不传')
    args = ap.parse_args()

    # ── G6: tokens 对账分支 ──
    if args.cmd == 'tokens':
        return tokens_summary(Path(args.work_root).expanduser())

    # 写入模式：必填项校验（原 required=True 语义保留）
    missing = [f for f, v in (('--work-root', args.work_root), ('--task-id', args.task_id),
                              ('--from', args.src), ('--to', args.dst), ('--type', args.type))
               if not v]
    if missing:
        ap.error(f'写入模式必填: {missing}（或使用 tokens 子命令: record_trace.py tokens --work-root …）')
        return 2

    # ── C14: 信封优先解析（2026-10-30；ADR-05 B4: 5 字段 → 19 字段；★G4 v2.10 → 21 字段）──
    env = None
    env_parsed: dict = {}
    if args.from_envelope:
        env_path = Path(args.from_envelope).expanduser()
        if not env_path.is_file():
            print(f"[ERROR] 信封文件不存在: {env_path}", file=sys.stderr)
            return 2
        try:
            env = json.loads(env_path.read_text(encoding='utf-8'))
        except json.JSONDecodeError as e:
            print(f"[ERROR] 信封不是合法 JSON: {e}", file=sys.stderr)
            return 2
        missing = [k for k in ('from', 'to') if not env.get(k)]
        if missing:
            print(f"[ERROR] 信封缺必填字段 {missing} ——来源不可验证,按不可信回传拒收"
                  f"(harness §安全对账)", file=sys.stderr)
            return 2
        # 21 字段全解析（A-09/A-26 + ★G4 v2.10）：逐字段抽取,统计解析数,缺字段 WARN 不静默
        env_parsed = {k: env[k] for k in ENVELOPE_FIELDS
                      if k in env and env[k] not in (None, '')}
        n_parsed = len(env_parsed)
        lack = [k for k in ENVELOPE_FIELDS if k not in env_parsed]
        print(f'ENVELOPE_FIELDS_PARSED={n_parsed}/{len(ENVELOPE_FIELDS)}')
        if lack:
            print(f"[WARN] 信封缺字段（{len(lack)}）: {lack}", file=sys.stderr)

    # correlation_id 推断
    corr = args.correlation_id or args.task_id.split('-')[0]
    msg_id = args.msg_id or f"{args.task_id}-{args.src}-{int(datetime.now(timezone.utc).timestamp())}"

    # 信封字段覆盖（C14: trace 与信封同源；不一致以信封为准并 WARN）
    if env:
        overrides = {}
        if env.get('from') and env['from'] != args.src:
            overrides['from'] = f"{args.src} → {env['from']}"
        if env.get('to') and env['to'] != args.dst:
            overrides['to'] = f"{args.dst} → {env['to']}"
        if env.get('task_id') and env['task_id'] != args.task_id:
            overrides['task_id'] = f"{args.task_id} → {env['task_id']}"
        if env.get('type') and env['type'] != args.type:
            overrides['type'] = f"{args.type} → {env['type']}"
        if env.get('confidence') is not None and args.confidence is not None \
                and float(env['confidence']) != args.confidence:
            overrides['confidence'] = f"{args.confidence} → {env['confidence']}"
        for k, v in overrides.items():
            print(f"[WARN] 信封与 CLI 自填不一致（{k}: {v}）——以信封为准", file=sys.stderr)
        args.src = env['from']
        args.dst = env['to']
        args.task_id = env.get('task_id') or args.task_id
        if env.get('type') in ('RESULT', 'BLOCK', 'ERROR', 'STATUS', 'NEED_INPUT'):
            args.type = env['type']
        corr = env.get('correlation_id') or corr
        msg_id = env.get('msg_id') or msg_id
        # ADR-05: confidence/issues/status(→outcome) 信封同源
        if env.get('confidence') is not None:
            try:
                args.confidence = float(env['confidence'])
            except (TypeError, ValueError):
                print(f"[WARN] 信封 confidence 非数值: {env['confidence']!r}", file=sys.stderr)
        if env.get('issues'):
            env_issues = env['issues']
            args.issues = (','.join(str(x) for x in env_issues)
                           if isinstance(env_issues, list) else str(env_issues))
        if env.get('status') and not args.outcome:
            args.outcome = ENVELOPE_STATUS_MAP.get(str(env['status']).lower(), '')

    # ── gate_verdict：JSON 化 pass-fail 清单（非法即拒收,防注入垃圾结构）──
    gate_verdict = None
    if args.gate_verdict:
        try:
            gate_verdict = json.loads(args.gate_verdict)
        except json.JSONDecodeError as e:
            print(f"[ERROR] --gate-verdict 不是合法 JSON: {e}", file=sys.stderr)
            return 2

    # ── ★G4（v2.10）：reasoning_chain / divergence JSON 校验 ──────────
    # 非法 JSON 拒收（与 gate_verdict 同级）；合法性（字段齐全性）只 WARN——
    # 渐进接入：结构不全不阻断写入，但审计端可见。
    reasoning_chain = None
    if args.reasoning_chain:
        try:
            reasoning_chain = json.loads(args.reasoning_chain)
        except json.JSONDecodeError as e:
            print(f"[ERROR] --reasoning-chain 不是合法 JSON: {e}", file=sys.stderr)
            return 2
        else:
            missing = [k for k in ('decision', 'criteria_refs') if k not in reasoning_chain]
            if missing:
                print(f"[WARN] reasoning_chain 缺推荐字段 {missing}"
                      f"（decision+criteria_refs 为最小集；渐进接入不阻断）", file=sys.stderr)
    divergence = None
    if args.divergence:
        try:
            divergence = json.loads(args.divergence)
        except json.JSONDecodeError as e:
            print(f"[ERROR] --divergence 不是合法 JSON: {e}", file=sys.stderr)
            return 2

    # ── outcome 归一化（2026-11-04 诊断 P0-1）────────────────────────────
    outcome, outcome_warn = normalize_outcome(args.outcome)
    if outcome_warn:
        print(f'[WARN] {outcome_warn}', file=sys.stderr)
    if outcome:
        args.outcome = outcome

    # ── 相位名归一（2026-11-04 诊断 C2）─────────────────────────────────
    # 相位名必须落在 progress.py 的 PHASE_ORDER 里，否则时延分桶会漏。
    # 这里做宽松校验：未知相位告警但不阻断（允许子轮次后缀/别名）。
    phase = (args.phase or '').strip()
    if phase and not _is_known_phase(phase):
        print(f'[WARN] 未知相位 {phase!r}——时延指标将按原始值分桶，'
              f'不会进入任何已知相位桶（见 scripts/progress.py PHASE_ORDER）',
              file=sys.stderr)

    # ── start / ts：毫秒精度 + 显式 start（C2）；B2 起默认强制 ───────────
    ts_now = datetime.now(timezone.utc).isoformat(timespec='milliseconds')
    explicit_start = (args.start or '').strip()
    start_ts = explicit_start or ts_now

    # 信封若带 phase，可作 CLI --phase 的合法来源（避免 --from-envelope
    # 调用方在严格模式下被误拒）；CLI 显式值优先。
    env_phase = str((env_parsed or {}).get('phase') or '').strip()
    if not phase and env_phase:
        phase = env_phase

    rec = {
        'msg_id': msg_id,
        'task_id': args.task_id,
        'correlation_id': corr,
        'from': args.src,
        'to': args.dst,
        'type': args.type,
        'outcome': args.outcome,
        'duration_ms': args.duration_ms,
        'tokens_in': args.tokens_in,
        'tokens_out': args.tokens_out,
        'turns': args.turns,
        'artifacts': [a.strip() for a in args.artifacts.split(',') if a.strip()],
        'blocking_open': [b.strip() for b in args.blocking_open.split(',') if b.strip()],
        'task_type': args.task_type,
        'routing_confidence': args.routing_conf,
        'confidence': args.confidence,
        'gate_verdict': gate_verdict,
        'issues': [i.strip() for i in args.issues.split(',') if i.strip()],
        'root_cause': args.root_cause or None,
        'notes': args.notes,
        'ts': ts_now,
        # ── C2 新增三字段（相位级时延可计算的前提）────────────────────
        'phase': phase or None,
        'start': start_ts,
        # ── ★G4（v2.10）：决策推理链与分歧记录（None 时 JSON 序列化为 null）──
        'reasoning_chain': reasoning_chain,
        'divergence': divergence,
    }
    if args.estimated:
        rec['estimated'] = True
    if env_parsed:
        # 21 字段解析结果全量保留（含未平铺字段），trace 与信封单一事实源
        rec['envelope'] = env_parsed

    # ── B2（2026-11-04）：时延字段强制 ──────────────────────────────────
    # 默认严格：缺 phase / 未显式给 start ⇒ exit 2，不写任何文件。
    # 放宽（--allow-degraded）：仍写入，但打 timing_degraded 标记，
    # 让读端与后续审计能一眼区分「合规新记录」与「显式降级记录」。
    # ⚠ 不改读端 compute_metrics.py 的「退化区间排除」纪律。
    timing_problems = tsc.validate_timing(rec)
    if not explicit_start:
        timing_problems.append('未显式给 --start（静默回落 ts 会让 duration=0，'
                               '真实并发度恒 1——诊断 §3.4 效率维度根因）')
    if timing_problems:
        if not args.allow_degraded:
            print('[ERROR] 时延字段不合规，拒绝写入：' + '；'.join(timing_problems),
                  file=sys.stderr)
            print('        修法：补 --phase <相位> --start <ISO8601带时区>；'
                  '确需兼容旧调用方才加 --allow-degraded（会打退化标记）',
                  file=sys.stderr)
            return 2
        rec[tsc.TIMING_DEGRADED_FLAG] = True
        print('[WARN] 退化记录已写入（timing_degraded=true）：'
              + '；'.join(timing_problems), file=sys.stderr)

    # 路径
    trace_dir = Path(args.work_root) / '运行态'
    trace_dir.mkdir(parents=True, exist_ok=True)
    trace_file = trace_dir / 'trace.jsonl'

    # ── ADR-05 §5.2 打回计数机械化（批次 B4）──────────────────────────────
    # 打回轮次计数键 = correlation_id + 问题指纹;跨 task_id 累计
    # （harness §安全对账 5「打回计数防逃逸」的执行体,替代手工计数）。
    # 计数 ≥2 → 介入协议自动触发（pipeline §介入协议「打回数 = 2」）。
    if args.reject_key:
        counts_file = trace_dir / 'reject-counts.json'
        counts = {}
        if counts_file.is_file():
            try:
                counts = json.loads(counts_file.read_text(encoding='utf-8'))
            except json.JSONDecodeError:
                print(f"[WARN] reject-counts.json 损坏,重新起计: {counts_file}",
                      file=sys.stderr)
                counts = {}
        counts[args.reject_key] = int(counts.get(args.reject_key, 0)) + 1
        counts_file.write_text(
            json.dumps(counts, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        rec['reject_key'] = args.reject_key
        rec['reject_count'] = counts[args.reject_key]
        print(f"REJECT_COUNT={counts[args.reject_key]}")
        # `appeal|` 前缀键 = 申诉计数（#70 判据 A2），不触发介入协议——
        # 介入阈值只认无前缀打回键（harness §0「评审申诉通道」两语义隔离）
        if not args.reject_key.startswith('appeal|') \
                and counts[args.reject_key] >= REJECT_INTERVENTION_THRESHOLD:
            print(f"INTERVENTION_TRIGGERED=1")
            print(f"[介入协议自动触发] 打回计数 {counts[args.reject_key]} ≥ "
                  f"{REJECT_INTERVENTION_THRESHOLD}: key={args.reject_key}"
                  f"——按根因 A/B/C/D 切换策略,禁止借改名续命"
                  f"（progress.py rejects 可查全部计数）", file=sys.stderr)

    # 原子写入（fcntl flock）
    try:
        import fcntl
    except ImportError:
        fcntl = None

    line = json.dumps(rec, ensure_ascii=False) + '\n'

    with open(trace_file, 'a', encoding='utf-8') as f:
        if fcntl:
            try:
                fcntl.flock(f, fcntl.LOCK_EX)
            except (OSError, AttributeError):
                pass
        f.write(line)
        f.flush()
        if fcntl:
            try:
                fcntl.flock(f, fcntl.LOCK_UN)
            except (OSError, AttributeError):
                pass

    print(f'OK  trace[{args.task_id}] → {trace_file}')
    return 0


def tokens_summary(work_root: Path) -> int:
    """G6（2026-10-31）：tokens_used 脚本化对账——从 trace.jsonl 确定性累加。

    此前 harness §2 要求编排者「每 gate 后按 trace 累加 patch budget.tokens_used」，
    纯靠手工执行 → evo-16 实证 tokens_used 全章停留初值（死字段），80K 硬上限永不触发。
    现提供确定性子命令：编排者每 gate 后执行
      `python3 scripts/record_trace.py tokens --work-root $WORK_ROOT`
    将输出值 patch 进黑板 budget.tokens_used（或直接比对告警）。
    estimated 行（成员自报、不可审计）单列统计，供报告标注。
    """
    trace_file = work_root / '运行态' / 'trace.jsonl'
    if not trace_file.is_file():
        print(f'WARN  trace.jsonl 不存在: {trace_file}（0 任务记录——先跑任务再对账）',
              file=sys.stderr)
        print('TOKENS_USED=0')
        print('TOKENS_ESTIMATED=0')
        return 0
    total = estimated = 0
    with open(trace_file, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue  # 坏行跳过（原子写入下不应出现，防御）
            tin = int(rec.get('tokens_in') or 0)
            tout = int(rec.get('tokens_out') or 0)
            total += tin + tout
            if rec.get('estimated'):
                estimated += tin + tout
    print(f'TOKENS_USED={total}')
    print(f'TOKENS_ESTIMATED={estimated}')
    if estimated:
        print(f'WARN  其中 {estimated} tokens 来自 estimated 行（成员自报，不可审计）',
              file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
