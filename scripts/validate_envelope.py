#!/usr/bin/env python3
"""validate_envelope.py — 消息信封完整校验（2026-11-04 诊断 M3/M4 执行体）

问题背景
========
harness §1 定义消息信封为**唯一 SSOT**，21 字段（★G4 v2.10：6 必填 + 扩展 + payload + reasoning_chain/divergence）。
但在此版本之前：

  · record_trace.py --from-envelope 只对 `from` / `to` 两个字段做**拒收级**校验
    （缺失 → exit 2），其余 17 字段缺失仅打印 WARN 后照常写入 trace
  · harness §1 声明的「6 必填」在**代码层没有任何一处执行**
  · 后果：信封可以「半残」通过并写入 trace，写入后无法与完整信封区分；
    下游按字段判定（如 status→outcome 映射）会静默取到空值

本脚本做什么
============
把信封校验从「文档声明」变成「可执行判据」，分三级：

  ERROR（必填缺失）  → 拒收，exit 2
  WARN （扩展缺失）  → 放行 + 告警（不阻断——扩展字段本就是可选的）
  INFO （payload 缺失）→ 放行 + 提示

退出码
======
  exit 0  通过（可能有 WARN）
  exit 2  必填字段缺失 → 拒收
  exit 3  文件/JSON 错误

用法
====
  python3 scripts/validate_envelope.py --envelope path/to/envelope.json
  python3 scripts/validate_envelope.py --envelope env.json --json
  python3 scripts/validate_envelope.py --stdin < env.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# ── 必填 6 字段（harness §1）──────────────────────────────────────────
# 选取依据：缺任一字段都会让「来源可验证 / 归属可判定 / 结果可路由」失效。
REQUIRED_FIELDS = (
    'from',        # 来源成员 ID —— 反投毒对账锚
    'to',          # 目标成员/编排 ID
    'task_id',     # 任务标识 —— 指标按此去重取末态
    'type',        # RESULT / BLOCK / ERROR / STATUS / NEED_INPUT
    'correlation_id',  # 跨阶段聚合 —— 并行分支归并依据
    'status',      # success / partial / failed / blocked —— 决定 outcome
)

# ── 扩展 8 字段（缺失仅告警）──────────────────────────────────────────
EXTENDED_FIELDS = (
    'agent_id', 'confidence', 'deliverable_summary', 'evidence', 'issues',
    'next_agent_hint', 'metrics', 'msg_id',
)

# ── 合法取值域 ────────────────────────────────────────────────────────
TYPE_VALUES = ('RESULT', 'BLOCK', 'ERROR', 'STATUS', 'NEED_INPUT')
STATUS_VALUES = ('success', 'partial', 'failed', 'blocked')
# status → outcome 映射（与 record_trace.py ENVELOPE_STATUS_MAP 同源，
# 但这里定义在「校验」侧，两边必须一致 —— 故从 record_trace 导入以免双写）
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from record_trace import ENVELOPE_STATUS_MAP
except Exception:  # pragma: no cover - 导入失败时用内置兜底
    ENVELOPE_STATUS_MAP = {
        'success': 'OK', 'partial': 'PARTIAL',
        'failed': 'ERROR', 'blocked': 'BLOCKED',
    }


def validate(env: dict) -> dict:
    """校验信封。返回 {ok, errors, warns, infos, parsed, missing}"""
    errors: list[str] = []
    warns: list[str] = []
    infos: list[str] = []

    if not isinstance(env, dict):
        return {'ok': False, 'errors': ['信封不是 JSON 对象'],
                'warns': [], 'infos': [], 'parsed': 0, 'missing': list(REQUIRED_FIELDS)}

    # 必填
    missing = []
    for k in REQUIRED_FIELDS:
        v = env.get(k)
        if v is None or (isinstance(v, str) and not v.strip()):
            missing.append(k)
    if missing:
        errors.append(f'缺必填字段 {missing} —— 来源不可验证/归属不可判定，按不可信回传拒收')

    # 扩展
    lack_ext = [k for k in EXTENDED_FIELDS
                if env.get(k) is None or (isinstance(env.get(k), str) and not str(env.get(k)).strip())]
    if lack_ext:
        warns.append(f'缺扩展字段（{len(lack_ext)}）: {lack_ext} —— 可放行，但信息不完整')

    # payload
    if not env.get('payload'):
        infos.append('无 payload 字段 —— 若本条无附加产物/度量则正常')

    # 取值域
    t = env.get('type')
    if t and str(t).upper() not in TYPE_VALUES:
        errors.append(f'type 取值非法: {t!r}（合法: {"/".join(TYPE_VALUES)}）')
    s = env.get('status')
    if s and str(s).lower() not in STATUS_VALUES:
        errors.append(f'status 取值非法: {s!r}（合法: {"/".join(STATUS_VALUES)}）')
    c = env.get('confidence')
    if c is not None:
        try:
            cv = float(c)
            if not (0 <= cv <= 100):
                errors.append(f'confidence 越界: {cv}（合法 0-100）')
        except (TypeError, ValueError):
            errors.append(f'confidence 非数值: {c!r}')

    parsed = sum(1 for k in set(REQUIRED_FIELDS) | set(EXTENDED_FIELDS)
                 if env.get(k) not in (None, ''))

    return {
        'ok': not errors,
        'errors': errors,
        'warns': warns,
        'infos': infos,
        'parsed': parsed,
        'missing': missing,
        'outcome': ENVELOPE_STATUS_MAP.get(str(s).lower()) if s else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description='validate_envelope — 消息信封完整校验')
    ap.add_argument('--envelope', help='信封 JSON 文件路径')
    ap.add_argument('--stdin', action='store_true', help='从标准输入读取信封')
    ap.add_argument('--json', action='store_true', help='以 JSON 输出结果')
    ap.add_argument('--strict', action='store_true',
                    help='严格模式：扩展字段缺失也判失败（默认仅告警）')
    args = ap.parse_args()

    if args.stdin:
        raw = sys.stdin.read()
    elif args.envelope:
        p = Path(args.envelope).expanduser()
        if not p.is_file():
            print(f'[ERROR] 信封文件不存在: {p}', file=sys.stderr)
            return 3
        raw = p.read_text(encoding='utf-8')
    else:
        print('必须给 --envelope 或 --stdin', file=sys.stderr)
        return 3

    try:
        env = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f'[ERROR] 信封不是合法 JSON: {e}', file=sys.stderr)
        return 3

    r = validate(env)

    if args.strict and r['warns']:
        r['ok'] = False
        r['errors'].append('严格模式：扩展字段缺失判失败')

    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print(f"必填字段: {len(REQUIRED_FIELDS) - len(r['missing'])}/{len(REQUIRED_FIELDS)}  "
              f"扩展字段已填: {r['parsed']}")
        if r['outcome']:
            print(f'OUTCOME={r["outcome"]}')
        for e in r['errors']:
            print(f'[ERROR] {e}', file=sys.stderr)
        for w in r['warns']:
            print(f'[WARN] {w}', file=sys.stderr)
        for i in r['infos']:
            print(f'[INFO] {i}', file=sys.stderr)
        if r['ok']:
            print('ENVELOPE_VALID=1')
        else:
            print('ENVELOPE_VALID=0')

    return 0 if r['ok'] else 2


if __name__ == '__main__':
    sys.exit(main())
