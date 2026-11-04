#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""parallel_gate.py — Batch 3 流程结构变更的机械裁决门（诊断 §3.2 升级 A / 升级 C）

为什么需要脚本而不是只改文档
------------------------------
升级 A「SPECIFY-RETRIEVE 搭接并行」与升级 C「VISUALIZE 半相位前移」各带一条
风险控制条款。若只写成散文，前面批次建立的「规范可执行化」纪律就断了：

  A: refine 只增不改知识块 ID——ID 是 architect 与 scout 的共享锚，
     门禁 2 永远以 v1 知识块为覆盖判据（并行撕裂的防线）
  C: R2/R3 返修导致 >50% 图表位变更 ⇒ 判定并行失败，回退旧串行序并写 trace

本脚本把两条变成可计算、可回归、可审计的判据。**脚本只报决策、不 spawn 成员**
（与 Batch 4 升级 E 同一纪律）：它无权调度 agent，裁决权归主理人；
主理人可 override，但 override 必须记 trace（见 SKILL.md §搭接并行协议）。

子命令
------
  anchor        比对 chapter_design v1 快照与 refine 版的知识块锚
  visual-drift  比对 R1 结构冻结稿与 R2/R3 后稿的图表位，输出继续/回退决策

知识块锚格式（唯一权威 = skills/textbook-pipeline-workflow/SKILL.md §搭接并行协议）
--------------------------------------------------------------------------------
chapter_design.md 内必须含一个机器可读区块，表格首列固定为 block_id：

  <!-- KNOWLEDGE_BLOCKS_BEGIN -->
  | block_id | 知识域 | Bloom 层级 | 字数目标 | 依赖块 | 可并行标记 |
  | --- | --- | --- | --- | --- | --- |
  | KB-01 | 病原学 | 理解 | 800 | — | yes |
  <!-- KNOWLEDGE_BLOCKS_END -->

除 block_id 外的各列构成「字段签名」：refine 版中 v1 已有块的签名必须逐字不变
（首尾空白归一），允许新增块，禁止删块 / 改块 / 重复 ID。

图表位口径
----------
复用 `check_manuscript.py` 的 `RE_FIGURE_SLOT`（门禁 4 的唯一正则 SSOT），
不在本文件复制第二份正则。图号 = `{章}-{序}`，冒号后的描述文本 = 图的
「教学目的/数据来源」声明；图号消失或描述变化 = 该图规格卡作废。
新增图位只意味着「另画一张」，不使既有规格卡作废，故不计入分子。

退出码（两个子命令统一）
------------------------
  0 判定通过（ANCHOR_OK / CONTINUE_PARALLEL）
  1 判定不通过（ANCHOR_VIOLATION / FALLBACK_SERIAL）——**是决策码，不是脚本故障**
  2 输入错误（缺文件 / 格式非法 / 基准为空 / 同一文件自比对）——不得静默判 PASS
  3 写 trace 失败（record_trace.py 不可用或返回非 0）

用法
----
  python3 scripts/parallel_gate.py anchor \
      --v1 章节/ch01/chapter_design_v1.md \
      --refined 章节/ch01/chapter_design.md \
      --out 运行态/knowledge_anchor_ch01.json

  python3 scripts/parallel_gate.py visual-drift \
      --frozen 章节/ch01/draft_r1_frozen.md \
      --current 章节/ch01/draft.md \
      --chapter ch01 --threshold 0.5 \
      --out 运行态/visual_drift_ch01.json \
      [--work-root "$WORK_ROOT" --write-trace]

依赖：仅标准库 + 同目录 check_manuscript.py / record_trace.py；无需安装包。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# 同目录模块优先：成员/编排者从任意 cwd 调用都能解析（不写死绝对路径）
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

try:
    # 图表位正则的唯一 SSOT；导入期无副作用（已实测）。
    from check_manuscript import RE_FIGURE_SLOT  # noqa: E402
except ImportError as exc:  # pragma: no cover - 缺依赖必须响，不静默降级
    print(f'[ERROR] 无法导入图表位正则 SSOT: {exc}', file=sys.stderr)
    sys.exit(2)

# ── 常量 ────────────────────────────────────────────────────────────────
EXIT_OK = 0
EXIT_DECISION = 1
EXIT_INPUT_ERROR = 2
EXIT_TRACE_ERROR = 3

ANCHOR_BEGIN = '<!-- KNOWLEDGE_BLOCKS_BEGIN -->'
ANCHOR_END = '<!-- KNOWLEDGE_BLOCKS_END -->'
ANCHOR_RE = re.compile(re.escape(ANCHOR_BEGIN) + r'(.*?)' + re.escape(ANCHOR_END),
                       re.S)
BLOCK_ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.\-]*$')
CHAPTER_RE = re.compile(r'^ch\d{2}$')
SEP_CELL_RE = re.compile(r'^:?-{3,}:?$')

DECISION_ANCHOR_OK = 'ANCHOR_OK'
DECISION_ANCHOR_VIOLATION = 'ANCHOR_VIOLATION'
DECISION_CONTINUE = 'CONTINUE_PARALLEL'
DECISION_FALLBACK = 'FALLBACK_SERIAL'

DEFAULT_THRESHOLD = 0.5
TRACE_TIMEOUT_S = 30


# ── 通用小工具 ──────────────────────────────────────────────────────────
def read_text(path: Path, label: str) -> tuple[str | None, str | None]:
    """读文件；不存在/不可读一律返回错误原因（绝不静默当空串判 PASS）。"""
    if not path.is_file():
        return None, f'{label} 文件不存在: {path}'
    try:
        return path.read_text(encoding='utf-8'), None
    except (OSError, UnicodeError) as exc:
        return None, f'{label} 无法读取: {path}（{exc}）'


def write_report(out: str | None, report: dict) -> str | None:
    """报告落盘；父目录自动建。返回错误原因或 None。"""
    if not out:
        return None
    path = Path(out).expanduser()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n',
                        encoding='utf-8')
    except OSError as exc:
        return f'报告写入失败: {path}（{exc}）'
    return None


def input_error(msg: str, report: dict | None = None) -> int:
    print(f'[ERROR] {msg}', file=sys.stderr)
    if report is not None:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return EXIT_INPUT_ERROR


# ── 升级 A：知识块共享锚 ────────────────────────────────────────────────
def _cells(line: str) -> list[str]:
    """拆一行 Markdown 表格为单元格（首尾空白归一，不做语义解释）。"""
    return [c.strip() for c in line.strip().strip('|').split('|')]


def parse_anchor_table(text: str, label: str) -> tuple[dict | None, str | None]:
    """解析锚区块。返回 (结构, 错误原因)；结构含 header/blocks/order/duplicates。

    列数与表头不一致、block_id 非法、区块缺失、空表 —— 一律 INPUT_ERROR，
    因为「解析不出锚」若判 PASS，等于共享锚形同虚设（恒真放行）。
    """
    m = ANCHOR_RE.search(text)
    if not m:
        return None, (f'{label} 未找到知识块锚区块'
                      f'（须含 {ANCHOR_BEGIN} … {ANCHOR_END}）')
    lines = [ln.strip() for ln in m.group(1).splitlines()
             if ln.strip().startswith('|')]
    if len(lines) < 2:
        return None, f'{label} 锚区块表格不足 2 行（表头 + 至少 1 个数据行）'

    header = _cells(lines[0])
    if header[0].lower() != 'block_id':
        return None, f'{label} 锚表首列必须是 block_id，实为 {header[0]!r}'
    ncols = len(header)
    if ncols < 2:
        return None, f'{label} 锚表只有 block_id 一列，无字段签名可比（无法判「改块」）'

    body = lines[1:]
    # 分隔行可缺省（Markdown 允许无对齐标记），命中则跳过；不把它当数据。
    if body and all(SEP_CELL_RE.fullmatch(c or '') for c in _cells(body[0])):
        body = body[1:]
    if not body:
        return None, f'{label} 锚区块无数据行（空锚不得判 PASS）'

    blocks: dict[str, tuple[str, ...]] = {}
    order: list[str] = []
    duplicates: list[str] = []
    for lineno, line in enumerate(body, 1):
        cells = _cells(line)
        if len(cells) != ncols:
            return None, (f'{label} 锚表第 {lineno} 行有 {len(cells)} 列，'
                          f'表头 {ncols} 列——列错位禁止静默放行')
        bid = cells[0]
        if not BLOCK_ID_RE.fullmatch(bid):
            return None, f'{label} 锚表第 {lineno} 行 block_id 非法: {bid!r}'
        if bid in blocks:
            duplicates.append(bid)
            continue
        blocks[bid] = tuple(cells[1:])
        order.append(bid)
    return {'header': header, 'blocks': blocks, 'order': order,
            'duplicates': duplicates}, None


def cmd_anchor(args: argparse.Namespace) -> int:
    v1_path = Path(args.v1).expanduser().resolve()
    refined_path = Path(args.refined).expanduser().resolve()
    # 防「同一文件自比对恒真」：这是完整性校验纪律，不是多余检查。
    if v1_path == refined_path:
        return input_error('v1 与 refined 指向同一文件——共享锚必须来自独立的 v1 快照'
                           '（主理人过门禁 1 后先 cp 一份 chapter_design_v1.md）')

    v1_text, err = read_text(v1_path, 'v1')
    if err:
        return input_error(err)
    refined_text, err = read_text(refined_path, 'refined')
    if err:
        return input_error(err)

    v1, err = parse_anchor_table(v1_text, 'v1')
    if err:
        return input_error(err)
    refined, err = parse_anchor_table(refined_text, 'refined')
    if err:
        return input_error(err)

    base_ids = v1['order']
    removed = [b for b in base_ids if b not in refined['blocks']]
    modified = [b for b in base_ids
                if b in refined['blocks'] and refined['blocks'][b] != v1['blocks'][b]]
    added = [b for b in refined['order'] if b not in v1['blocks']]
    duplicates = sorted(set(v1['duplicates'] + refined['duplicates']))
    violations = removed + modified + duplicates

    report = {
        'gate': 'anchor',
        'decision': DECISION_ANCHOR_VIOLATION if violations else DECISION_ANCHOR_OK,
        'v1': str(v1_path),
        'refined': str(refined_path),
        'baseline_ids': base_ids,          # 门禁 2 覆盖判据的唯一输入
        'baseline_count': len(base_ids),
        'refined_count': len(refined['order']),
        'added_ids': added,
        'removed_ids': removed,
        'modified_ids': modified,
        'duplicate_ids': duplicates,
        'violations': violations,
        # 供 learn_v2 / 门禁 2 复用的口径说明，不参与判定
        'rule': 'refine 只增不改知识块 ID 与字段签名；基线以 v1 为准',
    }
    err = write_report(args.out, report)
    if err:
        return input_error(err)

    print(f"DECISION={report['decision']}  "
          f"基线 {report['baseline_count']} 块 / refine 后 {report['refined_count']} 块"
          f" | 新增 {len(added)} 删除 {len(removed)} 改块 {len(modified)}"
          f" 重复 {len(duplicates)}")
    if violations:
        print('[判定] 共享锚被撕裂：refine 违反「只增不改」⇒ 本轮退回串行'
              '（scout 检索依据已变，门禁 2 覆盖判据失效）', file=sys.stderr)
        for b in removed:
            print(f'  · 删块 {b}', file=sys.stderr)
        for b in modified:
            print(f'  · 改块 {b}: {v1["blocks"][b]} → {refined["blocks"].get(b)}',
                  file=sys.stderr)
        for b in duplicates:
            print(f'  · 重复 ID {b}', file=sys.stderr)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return EXIT_DECISION
    print('[判定] 基线 ID 全保留且字段签名未变 ⇒ 允许 RETRIEVE 与 SPECIFY-refine 并行')
    return EXIT_OK


# ── 升级 C：图表位漂移与回退 ────────────────────────────────────────────
def figure_slots(text: str, label: str) -> tuple[dict[str, str] | None, str | None]:
    """提取 {图号: 描述}；同号重复且描述不一致属输入歧义，拒绝判定。"""
    slots: dict[str, str] = {}
    for m in RE_FIGURE_SLOT.finditer(text):
        stem = f'{m.group(1)}-{m.group(2)}'
        desc = m.group(3).strip()
        if stem in slots and slots[stem] != desc:
            return None, (f'{label} 图号 {stem} 重复且描述不一致'
                          f'（{slots[stem]!r} vs {desc!r}）——先修编号再裁决')
        slots.setdefault(stem, desc)
    return slots, None


def write_fallback_trace(work_root: Path, chapter: str, report: dict,
                         started_at: str) -> tuple[bool, str]:
    """回退决策落 trace：只写合规记录，绕过 record_trace.py = 破坏 B2 强制契约。

    用 STATUS 而非 RESULT，避免污染 compute_metrics.py 的 dispatch_hit_rate
    （该指标只统计 RESULT/BLOCK/ERROR 的 task_id 末态）。
    """
    notes = (f'VISUALIZE_PARALLEL_FALLBACK; chapter={chapter}; '
             f'changed={len(report["changed_slots"])}/{report["frozen_slots"]}'
             f'={report["changed_ratio"]:.3f}; threshold={report["threshold"]}; '
             f'slots={",".join(report["changed_slots"])}')
    cmd = [
        sys.executable, str(SCRIPT_DIR / 'record_trace.py'),
        '--work-root', str(work_root),
        '--task-id', f'{chapter}-VISUALIZE-gate',
        '--from', 'smart-textbook-team-team-lead',
        '--to', 'smart-textbook-team-team-lead',
        '--type', 'STATUS',
        '--outcome', 'OK',
        '--phase', 'VISUALIZE',
        '--start', started_at,
        '--notes', notes,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=TRACE_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f'调用 record_trace.py 失败: {exc}'
    if r.returncode != 0:
        return False, (f'record_trace.py exit {r.returncode}: '
                       f'{r.stderr.strip() or r.stdout.strip()}')
    return True, r.stdout.strip()


def cmd_visual_drift(args: argparse.Namespace) -> int:
    if not CHAPTER_RE.fullmatch(args.chapter or ''):
        return input_error(f'--chapter 非法: {args.chapter!r}（须 ch##，如 ch01）')
    if not 0.0 <= args.threshold <= 1.0:
        return input_error(f'--threshold 须在 [0,1]，实为 {args.threshold}')

    frozen_path = Path(args.frozen).expanduser().resolve()
    current_path = Path(args.current).expanduser().resolve()
    if frozen_path == current_path:
        return input_error('frozen 与 current 指向同一文件——结构冻结稿必须是'
                           ' VERIFY-R1 pass 当时的独立快照')
    frozen_text, err = read_text(frozen_path, 'frozen')
    if err:
        return input_error(err)
    current_text, err = read_text(current_path, 'current')
    if err:
        return input_error(err)

    frozen, err = figure_slots(frozen_text, 'frozen')
    if err:
        return input_error(err)
    current, err = figure_slots(current_text, 'current')
    if err:
        return input_error(err)
    if not frozen:
        # 基准为空时 ratio 无定义；若默认 0 会恒真放行——必须拒绝判定。
        return input_error(f'frozen 稿无图表位（{frozen_path}）——'
                           '无基准不得判「继续并行」；本章应走旧串行序或 W4 补图')

    changed = [s for s in frozen
               if s not in current or current[s] != frozen[s]]
    removed = [s for s in frozen if s not in current]
    added = [s for s in current if s not in frozen]
    unchanged = [s for s in frozen if s not in changed]
    ratio = len(changed) / len(frozen)
    # 严格大于：=50% 不回退（与 architect「密度 <0.3 严格小于」同一纪律）
    fallback = ratio > args.threshold

    report = {
        'gate': 'visual-drift',
        'decision': DECISION_FALLBACK if fallback else DECISION_CONTINUE,
        'chapter': args.chapter,
        'frozen': str(frozen_path),
        'current': str(current_path),
        'frozen_slots': len(frozen),
        'current_slots': len(current),
        'changed_slots': changed,
        'removed_slots': removed,
        'added_slots': added,
        'unchanged_slots': unchanged,
        'changed_ratio': round(ratio, 6),
        'threshold': args.threshold,
        'strictly_greater': fallback,
        'rule': '变更率 > 阈值（严格大于）⇒ 回退旧串行序；新增图位不计入分子',
        'trace_written': False,
        'learn_signal': None,
    }

    trace_error = None
    if fallback and args.write_trace:
        if not args.work_root:
            trace_error = '--write-trace 需同时给 --work-root'
        else:
            ok, detail = write_fallback_trace(
                Path(args.work_root).expanduser(), args.chapter, report,
                datetime.now(timezone.utc).isoformat(timespec='milliseconds'))
            if ok:
                report['trace_written'] = True
            else:
                trace_error = detail
    if fallback:
        report['learn_signal'] = {
            'signal_type': 'parallel_fallback',
            'chapter': args.chapter,
            'metric_evidence': {
                'metric': 'visual_slot_change_ratio',
                'baseline': args.threshold,
                'current': report['changed_ratio'],
                'delta': round(ratio - args.threshold, 6),
                'red_line': True,
                'delta_report': args.out or '(未落盘)',
            },
        }
        if trace_error:
            report['trace_error'] = trace_error

    err = write_report(args.out, report)
    if err:
        return input_error(err)

    print(f"DECISION={report['decision']}  变更 {len(changed)}/{len(frozen)}"
          f" = {ratio:.3f} {'>' if fallback else '<='} {args.threshold}"
          f" | 新增 {len(added)} 未变 {len(unchanged)}")
    if trace_error:
        print(f'[ERROR] 回退 trace 写入失败: {trace_error}', file=sys.stderr)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return EXIT_TRACE_ERROR
    if fallback:
        print('[判定] 并行失败 ⇒ 回退旧串行序（CONSOLIDATION 之后再 VISUALIZE）；'
              '脚本只报决策，实际改序由主理人执行', file=sys.stderr)
        print('[learn_v2] 已生成 signal_type=parallel_fallback 的候补信号，'
              '主理人须写入 学习/候补/ 供指标评审门裁决', file=sys.stderr)
        print(f"[trace] {'已写' if report['trace_written'] else '未写（未加 --write-trace）'}")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return EXIT_DECISION
    print('[判定] 图表位稳定 ⇒ VISUALIZE-spec 可继续与 VERIFY-R2/R3 并行')
    return EXIT_OK


# ── CLI ─────────────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description='Batch 3 并行裁决门：升级 A 共享锚 + 升级 C 图表位漂移回退')
    sub = ap.add_subparsers(dest='cmd', required=True)

    p_anchor = sub.add_parser('anchor', help='知识块共享锚「只增不改」校验')
    p_anchor.add_argument('--v1', required=True, help='门禁 1 通过时的 v1 快照路径')
    p_anchor.add_argument('--refined', required=True, help='refine 后 chapter_design 路径')
    p_anchor.add_argument('--out', default='', help='JSON 报告落盘路径（含 baseline_ids）')
    p_anchor.set_defaults(func=cmd_anchor)

    p_drift = sub.add_parser('visual-drift', help='图表位变更率与并行/串行决策')
    p_drift.add_argument('--frozen', required=True, help='VERIFY-R1 pass 时的结构冻结稿')
    p_drift.add_argument('--current', required=True, help='VERIFY-R2/R3 返修后稿')
    p_drift.add_argument('--chapter', required=True, help='章节号 ch##')
    p_drift.add_argument('--threshold', type=float, default=DEFAULT_THRESHOLD,
                         help='回退阈值（默认 0.5，严格大于才回退）')
    p_drift.add_argument('--out', default='', help='JSON 决策报告落盘路径')
    p_drift.add_argument('--work-root', default='', help='WORK_ROOT（--write-trace 时必填）')
    p_drift.add_argument('--write-trace', action='store_true',
                         help='回退时经 record_trace.py 写 STATUS 行（正常路径不写，不污染指标）')
    p_drift.set_defaults(func=cmd_visual_drift)
    return ap


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
