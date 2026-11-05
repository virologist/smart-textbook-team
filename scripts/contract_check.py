#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""contract_check.py — 成员产物契约校验（M2「部分落盘」判据执行体，2026-11-04 P1）

问题背景
========
诊断报告 M2：「成员部分落盘无判据」——harness §6.4 只有预防性条款，
全包 grep「部分落盘」0 命中。具体病灶：

  · 编排者收产出时，只看「成员说完成了」，不核对**该产出的文件到底在不在**
  · harness §2 防投毒对账第 4 条只管「越界写」（写了不该写的），
    不管「该写的没写」（产物缺失）——**缺项被判合格**
  · 结果：成员只落了一半（3 节写了 2 节），编排者照样推进到下一相位，
    缺的那节在后续审查里才暴露，白跑一轮

本脚本做什么
============
读 `references/member-contracts.json`（契约 SSOT），对指定成员的
`must_produce` 清单做**逐项落盘核对**：

  · 全部命中 → PASS（可推进）
  · 部分命中 → PARTIAL（缺项清单 + 处置建议 `on_partial`）
  · 全部落空 → MISSING（= 成员未交付，按 E2 处置）

同时做**越界写扫描**（`must_not_write`）：成员写了不该写的路径 →
报 OUT_OF_SCOPE_WRITE（与 harness §2 对账第 4 条同源，此处提供机械判据）。

「产物契约」与「路径归属」是两份表，职责不同：
  · `references/path-ownership.md`  = **谁能写哪个路径**（一路径一写者）
  · `references/member-contracts.json` = **该成员这一轮必须产出什么**（本脚本）

退出码
======
  0  PASS      —— must_produce 全部落盘
  1  PARTIAL   —— 部分落盘（缺项）
  2  MISSING   —— 应产出物一个都没有
  3  OUT_OF_SCOPE_WRITE —— 越界写（且产物齐备）→ 拒收
  4  输入缺失 / 契约文件损坏

用法
====
  python3 scripts/contract_check.py --work-root "$WORK_ROOT" \\
      --member subject-writer --chapter ch03

  # 节级模式（>8000 字，产物为 sections/{节号}.md）
  python3 scripts/contract_check.py --work-root "$WORK_ROOT" \\
      --member subject-writer --chapter ch03 --mode sections

  # 只看某几个具体产物
  python3 scripts/contract_check.py --work-root "$WORK_ROOT" \\
      --member quality-examiner --chapter ch03 \\
      --produce "章节/ch03/review/round1_report.md" --produce "章节/ch03/review/proofread.md"

  # 机器可读
  python3 scripts/contract_check.py --work-root "$WORK_ROOT" \\
      --member subject-writer --chapter ch03 --json
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

CONTRACT_REL = ('references', 'member-contracts.json')

# 判定结果 → 退出码
EXIT_PASS = 0
EXIT_PARTIAL = 1
EXIT_MISSING = 2
EXIT_OUT_OF_SCOPE = 3
EXIT_INPUT_ERROR = 4

# ═══════════════════════════════════════════════════════════════════════
# R2：波次状态回写与主理人裁决消费端（schema = stt.wave_state/1）
# ═══════════════════════════════════════════════════════════════════════
#
# 病灶（复诊 R2）：B4 的节级波次只 print 到 stdout，调度器算出的波次结构
# 没有持久化锚点 ⇒ ① 契约回写无从核对「本波该交付什么」
# ② 效率指标（波次耗时 / 并行收益）没有数据源 ③ 中断续跑不知上次跑到哪个波次。
#
# R2 落地：`scheduler.py plan --mode sections --write-wave-state` 把波次计划落盘为
# `运行态/wave_{ch##}_w{n}.json`（唯一消费端锚点）。本模块负责**增量回写**：
#   · `contract[节号].produced` —— 该节实际是否交付
#   · `net_words[节号]`        —— 该节实际净字数（SSOT 口径：count_net_words.py）
#   · `reason`                 —— 本次回写的判据说明
#
# 【计划与授权分离】本脚本**只报不裁决**：
#   · `contract` / `net_words` / `reason` = 机械核对结果（脚本可自证）
#   · `wave_verdict`（READY|BLOCKED|BUDGET_DEGRADED）= **主理人裁决位**，
#     本脚本**不写**它——脚本写它等于「计划存在」被误读成「已获执行授权」。
#     主理人裁决由 `wave_verdict` 子命令落定。

WAVE_STATE_SCHEMA = 'stt.wave_state/1'
WAVE_STATE_RE = re.compile(r'^wave_(ch\d{2})_w(\d+)\.json$')
WAVE_VERDICTS = ('READY', 'BLOCKED', 'BUDGET_DEGRADED')
WAVE_VERDICT_PENDING = 'PENDING'


def wave_state_path(work_root: Path, chapter: str, wave_id: int) -> Path:
    """波次状态文件路径（运行态/wave_{ch##}_w{n}.json）。"""
    return work_root / '运行态' / f'wave_{chapter}_w{wave_id}.json'


def list_wave_states(work_root: Path, chapter: str) -> list[Path]:
    """列出某章的全部波次状态文件（按 wave_id 升序）。"""
    d = work_root / '运行态'
    if not d.is_dir():
        return []
    out: list[tuple[int, Path]] = []
    for p in d.iterdir():
        m = WAVE_STATE_RE.match(p.name)
        if m and m.group(1) == chapter:
            out.append((int(m.group(2)), p))
    return [p for _, p in sorted(out)]


def load_wave_state(path: Path) -> dict:
    """读波次状态。文件缺失/损坏 → 抛异常（调用方 exit 4）。

    schema 不匹配 → 抛异常：跨 schema 的增量回写会把不相干字段写进状态文件，
    宁可报错也不静默污染锚点。
    """
    if not path.is_file():
        raise FileNotFoundError(f'波次状态文件不存在: {path}')
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError(f'波次状态文件格式错误（顶层不是对象）: {path}')
    schema = data.get('schema')
    if schema != WAVE_STATE_SCHEMA:
        raise ValueError(f'波次状态 schema 不匹配（期望 {WAVE_STATE_SCHEMA}，'
                         f'实为 {schema!r}）: {path}')
    return data


def write_wave_state(path: Path, state: dict) -> None:
    """写回波次状态（原子替换，避免半截文件）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n',
                   encoding='utf-8')
    tmp.replace(path)


def _net_words_of(work_root: Path, rel_path: str) -> int | None:
    """按 SSOT 口径（count_net_words.py）算某产物文件的净字数。

    口径必须与 `assemble_sections.py` / `check_manuscript.py` 同源——否则
    回写的净字数与章节门禁量的是不同的东西（C-05 病灶：同一规则两份口径）。
    """
    p = work_root / rel_path
    if not p.is_file():
        return None
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from count_net_words import count_net_words
    except ImportError:
        return None
    try:
        return count_net_words(p.read_text(encoding='utf-8'))['net_final']
    except (OSError, ValueError):
        return None


def patch_wave_state(work_root: Path, chapter: str, wave_id: int,
                     patched_by: str = 'contract_check.py') -> dict:
    """增量回写某波次的契约快照（contract / net_words / reason）。

    回写内容 = **机械核对结果**：
      · `contract[节号].produced` = 该节产物文件是否存在且非空
      · `net_words[节号]`        = 该节实际净字数（SSOT 口径）
      · `reason`                 = 本次回写的判据说明（含缺失节清单）

    **不写 `wave_verdict`** —— 那是主理人裁决位，脚本无权代填。
    返回回写后的状态摘要（供 JSON 输出与断言）。
    """
    path = wave_state_path(work_root, chapter, wave_id)
    state = load_wave_state(path)

    contract = dict(state.get('contract') or {})
    net_words = dict(state.get('net_words') or {})
    missing: list[str] = []
    checked: list[str] = []

    for sec, entry in contract.items():
        entry = dict(entry or {})
        rel = (entry.get('must_produce')
               or f'章节/{chapter}/sections/{sec}.md')
        p = work_root / rel
        produced = p.is_file() and p.stat().st_size > 0
        entry['produced'] = produced
        entry['must_produce'] = rel
        contract[sec] = entry
        if produced:
            nw = _net_words_of(work_root, rel)
            net_words[sec] = nw
            checked.append(sec)
        else:
            net_words[sec] = None
            missing.append(sec)

    state['contract'] = contract
    state['net_words'] = net_words
    state['reason'] = (
        f'契约回写：已交付 {len(checked)}/{len(contract)} 节'
        + (f'；缺失 {", ".join(missing)}' if missing else '；无缺失')
    )
    state['patched_at'] = datetime.now(timezone.utc).isoformat(timespec='milliseconds')
    state['patched_by'] = patched_by

    write_wave_state(path, state)
    return {
        'wave_id': wave_id,
        'chapter': chapter,
        'path': str(path),
        'delivered': checked,
        'missing': missing,
        'net_words': {k: v for k, v in net_words.items()},
        'wave_verdict': state.get('wave_verdict'),
        'proposed_verdict': state.get('proposed_verdict'),
        'verdict_untouched': True,
    }


def set_wave_verdict(work_root: Path, chapter: str, wave_id: int,
                     verdict: str, reason: str = '',
                     verdict_by: str = 'smart-textbook-team-team-lead'
                     ) -> dict:
    """落定主理人裁决（wave_verdict）。

    这是**消费端**：脚本只提供机械核对结果，`READY|BLOCKED|BUDGET_DEGRADED`
    的授权判断由主理人做。本函数只负责**忠实记录**裁决，不自行产生裁决——
    裁决值必须由调用方显式给出。
    """
    v = (verdict or '').strip().upper()
    if v not in WAVE_VERDICTS:
        raise ValueError(f'非法裁决值 {verdict!r}；合法值：'
                         f'{"|".join(WAVE_VERDICTS)}')
    path = wave_state_path(work_root, chapter, wave_id)
    state = load_wave_state(path)
    state['wave_verdict'] = v
    state['verdict_by'] = verdict_by
    state['verdict_at'] = datetime.now(timezone.utc).isoformat(timespec='milliseconds')
    state['verdict_reason'] = reason or None
    write_wave_state(path, state)
    return {
        'wave_id': wave_id,
        'chapter': chapter,
        'path': str(path),
        'wave_verdict': v,
        'verdict_by': verdict_by,
        'verdict_at': state['verdict_at'],
        'verdict_reason': state['verdict_reason'],
    }


def load_contracts(pkg_root: Path) -> dict:
    """读契约 SSOT。文件缺失/损坏 → 抛异常（调用方 exit 4）。"""
    p = pkg_root.joinpath(*CONTRACT_REL)
    if not p.is_file():
        raise FileNotFoundError(f'契约 SSOT 不存在: {p}')
    data = json.loads(p.read_text(encoding='utf-8'))
    if 'members' not in data:
        raise ValueError(f'契约文件格式错误（缺 members 段）: {p}')
    return data


def expand(pattern: str, chapter: str, slug: str = '') -> str:
    """把契约里的占位符展开成实际相对路径。

    {ch} → 章节号；{slug} → slug（未给则保留占位 → 该模式视为不可判定）；
    {图号}/{节号} 含具体数字的由调用方用 --produce 显式给出。
    """
    out = pattern.replace('{ch}', chapter)
    if slug:
        out = out.replace('{slug}', slug)
    return out


def _match_glob(path: str, pattern: str) -> bool:
    """glob 匹配（支持 ** 跨层与 * 单层）。"""
    return fnmatch.fnmatch(path, pattern)


def _resolve_artifact(work_root: Path, rel: str) -> Path:
    return work_root / rel


# ═══════════════════════════════════════════════════════════════════════
# 写者身份证据（2026-11-04 真实运行样本实测后重建）
# ═══════════════════════════════════════════════════════════════════════
#
# 【为什么需要这一层】前两版越界判据都被真实样本证伪：
#   v1「文件存在即越界」→ 误杀：writer 被判写了 examiner 的 review/ 产物
#   v2「归属者==本成员即越界」→ 漏判：architect 实际写了归属 writer 的
#      sections/3.1.md，判 PASS
# 根因（认知纠正）：**「文件存在」不能证明「是谁写的」**。
# 归属表回答「谁拥有该路径」，回答不了「这次是谁写的」。
#
# 【真实样本揭示的三个陷阱】trace.jsonl 15 条实测（教材编写真实在跑任务）：
#   ① trace.from 是**实例 ID**（subject-writer-1 / -2 / didactic-architect-3），
#      不是规范角色 ID → 按精确名比对会漏掉全部实例
#   ② artifacts 有 7/15 为空数组 → 不可假设「必有自报」
#   ③ artifacts 混有中文描述文本（「情境策略」「项目地图」「DESIGN-SPEC」）→
#      不是路径，参与路径匹配会假阳性
#
# 【本实现的证据分级】
#   L1 静态：契约 must_not_write × 路径归属表 → 检出「契约自相矛盾」
#   L2 自报：trace.jsonl 里该成员自报的**路径型** artifacts（实例 ID 已归一）
#   L3 内嵌：产物文件头部自述的写者（如「撰写：subject-writer」）
# L2/L3 都必须**路径命中 must_not_write** 才成立；两者皆无证据 → 只记
# `suspected`（提示，不阻断）——遵循「UNKNOWN 优先于误杀」纪律。

# 实例 ID 尾部后缀（subject-writer-1 → subject-writer）
_INSTANCE_SUFFIX = re.compile(r'-\d+$')

# 路径型 artifact 的扩展名白名单（用于把中文描述文本排除在外）
_PATHLIKE_EXT = ('.md', '.docx', '.csv', '.tsv', '.json', '.yaml', '.yml',
                 '.ipynb', '.svg', '.mmd', '.png', '.pdf', '.txt', '.py',
                 '.jpg', '.jpeg', '.xlsx', '.doc')


def normalize_member(name: str) -> str:
    """实例 ID → 规范角色 ID（剥离尾部 `-N` 实例后缀）。

    真实样本：`subject-writer-1` / `subject-writer-2` / `didactic-architect-3`
    并存于同一 trace；契约里只登记规范角色名 → 必须归一后才可比对。
    """
    n = (name or '').strip()
    return _INSTANCE_SUFFIX.sub('', n) if n else ''


def _norm_pattern(pattern: str, chapter: str | None = None) -> str:
    """归一路径模式（匹配用）。

    · chapter 给定 → 展开 `{ch}` / `{ch##}` 为该章
    · chapter 为 None → `{ch}` / `{ch##}` 归一为 `*`（章节无关族匹配）
    · 其余占位符（`{节号}` / `{图号}`）→ `*`
    · `**` → `*`（fnmatch 的 `*` 天然跨层，无需双星）
    """
    p = (pattern or '').replace('\\', '/')
    if chapter:
        p = p.replace('{ch##}', chapter).replace('{ch}', chapter)
    else:
        p = p.replace('{ch##}', '*').replace('{ch}', '*')
    p = re.sub(r'\{[^}]*\}', '*', p)
    p = p.replace('**', '*')
    return p.strip('/')


def _rel_to_root(work_root: Path, art: str) -> str:
    """把 artifact 路径归一为相对 work_root 的路径。

    真实样本里 artifacts 有**绝对路径**（team-lead 记的 task_package.md）
    与**相对路径**（subject-writer 记的 `.textbook-review/...`）两种，
    统一转相对才能与契约路径模式比较。
    """
    a = (art or '').strip().replace('\\', '/')
    if not a:
        return ''
    if a.startswith('/'):
        try:
            return str(Path(a).resolve().relative_to(work_root.resolve()))
        except (ValueError, OSError):
            return a.lstrip('/')
    # 注意：不能用 lstrip('./')——那会把 '.textbook-review' 砍成
    # 'textbook-review'（lstrip 按字符集剥前缀，坑）
    return re.sub(r'^\./', '', a)


def _is_pathlike(s: str) -> bool:
    """判断 artifact 是否为**路径形态**。

    真实样本的 artifacts 混有中文描述文本（「情境策略」「难度标尺+CSV」
    「DESIGN-SPEC」）——它们不是路径，参与路径匹配必假阳性。
    """
    if not s:
        return False
    if '/' in s:
        return True
    return s.lower().endswith(_PATHLIKE_EXT)


def _trace_records(work_root: Path) -> list[dict]:
    """读 运行态/trace.jsonl（真实运行的权威执行记录）。"""
    p = work_root / '运行态' / 'trace.jsonl'
    if not p.is_file():
        return []
    recs: list[dict] = []
    for line in p.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(d, dict):
            recs.append(d)
    return recs


def _reported_artifacts(work_root: Path, member: str) -> list[dict]:
    """收集本成员在 trace 里**自报的路径型产物**（写者身份证据 · L2）。

    实例 ID 已归一；非路径型 artifact（中文描述）已剔除。
    每条附来源记录（from / task_id / correlation_id）供审计。
    """
    want = normalize_member(member)
    out: list[dict] = []
    for d in _trace_records(work_root):
        if normalize_member(str(d.get('from') or '')) != want:
            continue
        for art in (d.get('artifacts') or []):
            s = str(art).strip()
            if not _is_pathlike(s):
                continue
            rel = _rel_to_root(work_root, s)
            if not rel:
                continue
            out.append({'path': rel, 'raw': s,
                        'from': d.get('from'),
                        'task_id': d.get('task_id'),
                        'correlation_id': d.get('correlation_id')})
    return out


# 产物文件头部的写者自述（真实样本实证）：
#   `> 撰写：subject-writer（祝书白）｜ 日期：2026-11-04`
#   `> 任务：REDESIGN-PHASE1-DESIGN ｜ 设计：didactic-architect ｜ 日期：...`
#   `> 诊断：didactic-architect ｜ 日期：2026-11-04`
_WRITER_DECL = re.compile(
    r'(?:撰写|设计|诊断|编制|产出|作者|执笔|主笔|起草|检索|复核)'
    r'\s*[:：]\s*([A-Za-z][A-Za-z0-9_-]*)')

# 只扫文件头若干行：真实样本的写者声明都在前 5 行；正文深处常出现
# 「撰写：某某」这类**引用他人**的表述，深扫会误判为越界。
_DECL_SCAN_LINES = 10


def _embedded_writers(path: Path) -> list[str]:
    """读产物文件头部自述的写者（归一后的成员 ID 列表）。"""
    try:
        head = path.read_text(encoding='utf-8', errors='ignore').splitlines()
    except OSError:
        return []
    out: list[str] = []
    for line in head[:_DECL_SCAN_LINES]:
        for m in _WRITER_DECL.finditer(line):
            n = normalize_member(m.group(1))
            if n and n not in out:
                out.append(n)
    return out


def _path_matches(path: str, pattern: str) -> bool:
    """单路径 × glob 模式匹配（两侧先归一）。

    fnmatch 的 `*` 天然跨层，故 `章节/ch03/review/*` 能命中
    `章节/ch03/review/round1_report.md`；`*` 亦可匹配字面量 `*`
    （fnmatch 不做正则转义）——这正是变量段 `{N}` 归一为 `*` 后的预期行为。
    """
    if not path or not pattern:
        return False
    p = _norm_pattern(path, None)
    q = _norm_pattern(pattern, None)
    if fnmatch.fnmatch(p, q):
        return True
    return fnmatch.fnmatch(p, q.rstrip('*') + '*')


def _owners_under(pkg_root: Path, pattern: str, chapter: str) -> set[str]:
    """查出「在该路径族下拥有路径」的全部归属者（供 L1 检测）。

    对通配模式（如 `章节/ch03/review/*`）必须同时看**归属表里落在该族下**
    的条目——只做精确相等会漏（`round{N}_report.md` 是变量段）。
    """
    out: set[str] = set()
    for pat, owner in _load_path_owners(pkg_root):
        p = _norm_pattern(pat, chapter)
        if fnmatch.fnmatch(pattern, p) or fnmatch.fnmatch(p, pattern):
            out.add(owner)
    return out


def _conflict_analysis(pkg_root: Path, member: str, mc: dict,
                        chapter: str) -> tuple[list[dict], list[dict]]:
    """L1 契约矛盾检测 → (硬矛盾, 软重叠)。

    **硬矛盾（CONTRACT_CONFLICT，须修契约）**
      成员自己的 `must_produce` 路径被列进 `must_not_write` —— 自相矛盾，
      成员无论如何写都会被判违规。

    **软重叠（overlap，仅提示）**
      成员在该 `must_not_write` 族内**只拥有部分路径**，例如
      team-lead 拥有 `章节/{ch}/review/interventions.md`（append），
      但 `must_not_write` 写的是 `章节/{ch}/review/**`（整族）。
      这不是矛盾——整族禁写里留一个自有例外口，是正常设计。
      把它当硬矛盾会导致编排者每次核对 team-lead 都被拦，属误杀。

    （2026-11-04 实测：首版把二者混为一谈，导致 team-lead 在
      `review/**` 与 `figures/**` 上被误报矛盾。）
    """
    conflicts: list[dict] = []
    overlaps: list[dict] = []
    produces = [_norm_pattern(p, chapter) for p in (mc.get('must_produce') or [])]
    for pat in mc.get('must_not_write') or []:
        pn = _norm_pattern(pat, chapter)
        owners = _owners_under(pkg_root, pn, chapter)
        if member not in owners:
            continue
        # 硬矛盾：自有 must_produce 落在该禁写族内
        hit = [p for p in produces if fnmatch.fnmatch(p, pn)
               or fnmatch.fnmatch(pn, p)]
        if hit:
            conflicts.append({
                'path': pat,
                'detail': f'该路径归属本成员（{member}），却列入 must_not_write'
                          f'——契约配置矛盾，须修契约而非判违规',
                'evidence': 'L1_STATIC',
            })
        else:
            overlaps.append({
                'path': pat,
                'detail': f'本成员在该族内拥有部分路径（如 interventions.md）'
                          f'，整族禁写留了自有例外口——非矛盾，仅提示',
                'evidence': 'L1_OVERLAP',
            })
    return conflicts, overlaps


def _files_under(work_root: Path, pattern: str) -> list[str]:
    """列出 work_root 下匹配给定（已归一）路径模式的实际文件。"""
    pat = _norm_pattern(pattern, None)
    if not pat:
        return []
    if '*' not in pat:
        return [pat] if (work_root / pat).is_file() else []
    prefix = pat.split('*')[0].rstrip('/')
    base = work_root / prefix if prefix else work_root
    if not base.is_dir():
        return []
    tail = pat[len(prefix):].lstrip('/')
    out: list[str] = []
    for f in base.rglob('*'):
        if not f.is_file():
            continue
        try:
            rel = str(f.relative_to(work_root)).replace('\\', '/')
        except ValueError:
            continue
        if fnmatch.fnmatch(rel, pat) or (tail and fnmatch.fnmatch(rel, tail)):
            out.append(rel)
    return sorted(set(out))


def check_contract(work_root: Path, pkg_root: Path, member: str,
                   chapter: str, produce: list[str] | None = None,
                   mode: str = 'default', slug: str = '',
                   task_type: str = '', section_no: str = '') -> dict:
    """核对成员的 must_produce 落盘情况 + must_not_write 越界扫描。

    ★H2（v2.10.1）：条件产物（task_type_required）
    -----------------------------------------------
    契约 JSON 新增可选键 `task_type_required: {task_type: [产物...]}`——
    仅在对应 task_type 派工时才必查的产物（如 r5_score.json 只在
    review-proofread-score / review-score 轮产出；{节号}.verdict.md 只在
    review-section 轮产出）。

    规则（临时目录实证驱动，消 2 个假阳性）：
    · 无 --task-type（常规核对）→ 跳过全部条件产物，不算缺项；
      响应附 `conditional_skipped` 信息行（审计可见，非静默）；
    · 有 --task-type → 用对应清单**替换**默认 must_produce（显式覆盖，
      与 --produce 同语义）；清单里的 {节号} 占位符由 --section 展开，
      未展开的占位符仍按 PATTERN_UNRESOLVED 报（不静默）。
    """
    contracts = load_contracts(pkg_root)
    members = contracts['members']
    if member not in members:
        return {'ok': False, 'verdict': 'UNKNOWN_MEMBER',
                'detail': f'契约中无成员 {member}；已登记成员: {sorted(members)}',
                'missing': [], 'present': [], 'out_of_scope': []}

    mc = members[member]
    tt_required = mc.get('task_type_required') or {}
    conditional_skipped: list[str] = []

    # ── 待核对产物清单 ────────────────────────────────────────────────
    if produce:
        targets = list(produce)
    elif task_type:
        if task_type not in tt_required:
            return {'ok': False, 'verdict': 'UNKNOWN_TASK_TYPE',
                    'detail': (f'成员 {member} 的契约无 task_type={task_type} '
                               f'的条件产物；已登记: {sorted(tt_required)}'),
                    'missing': [], 'present': [], 'out_of_scope': []}
        targets = list(tt_required[task_type])
    elif mode == 'sections' and member == 'subject-writer':
        # 节级模式：产物落在 sections/ 下，节号由设计文件给出（此处宽松判定）
        targets = [f'章节/{chapter}/sections/{s}.md'
                   for s in _section_numbers(work_root, chapter)]
    else:
        targets = list(mc.get('must_produce') or [])
        # 常规核对：条件产物不进核对（附信息行，不静默）
        # 注意 targets 存的是未展开的 {ch} 模式，比对须用同口径
        targets_expanded = {expand(t, chapter, slug) for t in targets}
        for tlist in tt_required.values():
            for pat in tlist:
                rel = expand(pat, chapter, slug)
                if rel not in targets_expanded and rel not in conditional_skipped:
                    conditional_skipped.append(rel)

    # review-section 条件产物的 {节号} 占位符由 --section 展开
    if task_type and section_no:
        targets = [t.replace('{节号}', section_no) for t in targets]

    # ── 落盘核对 ──────────────────────────────────────────────────────
    present, missing = [], []
    for pat in targets:
        rel = expand(pat, chapter, slug)
        if '{' in rel:
            # 占位符未被消解（如 {图号}）→ 无法机械判定，
            # 记为 missing 并标注原因（不静默当通过）
            missing.append({'path': rel, 'reason': 'PATTERN_UNRESOLVED',
                            'note': '占位符未消解，无法机械核对——'
                                    '请用 --produce 给出具体产物路径'
                                    + ('（review-section 须配合 --section <节号>）'
                                       if task_type == 'review-section' else '')})
            continue
        p = _resolve_artifact(work_root, rel)
        if p.is_file() and p.stat().st_size > 0:
            present.append(rel)
        else:
            missing.append({'path': rel,
                            'reason': 'NOT_FOUND' if not p.exists() else 'EMPTY_FILE'})

    # ── 越界写检测（must_not_write）· 三级证据分级 ──────────────────────
    # **核心认知（2026-11-04 真实样本实测纠正）**：「文件存在」**不能**证明
    # 「是谁写的」。归属表回答「谁拥有该路径」，回答不了「这次是谁写的」。
    # 前两版判据均被真实样本证伪：
    #   v1「文件存在即越界」→ 误杀（examiner 的 review/ 产物被判成 writer 越界）
    #   v2「归属者==本成员即越界」→ 漏判（architect 实写了归属 writer 的
    #      sections/3.1.md，判 PASS）
    #
    # 可判定的写者身份证据有两类（trace 自报 + 产物内嵌声明）：
    #   L2 自报：trace.jsonl 里该成员自报的**路径型** artifacts
    #      （真实样本 7/15 为空、6/15 是中文描述 → 必须过滤，否则假阳性）
    #   L3 内嵌：产物文件头部自述的写者（真实样本实证格式）
    # 二者都必须**路径命中 must_not_write** 才成立；都无证据 → 只记
    # `suspected`（提示，不阻断）——「UNKNOWN 优先于误杀」。
    reported = _reported_artifacts(work_root, member)
    out_of_scope: list[dict] = []
    suspected: list[dict] = []
    conflicts, overlaps = _conflict_analysis(pkg_root, member, mc, chapter)
    for pat in mc.get('must_not_write') or []:
        rel = expand(pat, chapter, slug)
        # 模式归一（章节无关族 → {ch} 归一为 *）
        pat_norm = _norm_pattern(pat, chapter)

        # ── L1 静态：契约自相矛盾已在上方统一检测 ────────────────
        # 硬矛盾（自有 must_produce 被禁写）→ 跳过该条的越界扫描
        if any(c['path'] == pat for c in conflicts):
            continue
        # 软重叠（族内部分自有）→ 仍需扫描，但本成员自有路径不算越界
        own_exceptions = [p for p in (mc.get('must_produce') or [])
                          if fnmatch.fnmatch(_norm_pattern(p, chapter), pat_norm)]

        # ── L2 自报证据（trace）────────────────────────────────────
        l2_hits = []
        for r in reported:
            if _path_matches(r['path'], pat_norm):
                if own_exceptions and any(
                        fnmatch.fnmatch(r['path'], _norm_pattern(e, chapter))
                        for e in own_exceptions):
                    continue    # 自有例外口 → 不算越界
                l2_hits.append(r['path'])
                out_of_scope.append({
                    'path': r['path'],
                    'reason': 'SELF_REPORTED_IN_MUST_NOT_WRITE',
                    'evidence': 'L2_TRACE_SELF_REPORT',
                    'detail': f"trace 自报（from={r['from']} "
                              f"task={r.get('task_id')}）",
                })

        # ── L3 内嵌证据（产物头部自述写者）─────────────────────────
        # 只在「本成员是 must_not_write 命中路径的候选写者」时才判定，
        # 否则任何文件头写「设计：didactic-architect」都会误伤。
        for frel in _files_under(work_root, pat_norm):
            if frel in l2_hits:
                continue
            if own_exceptions and any(
                    fnmatch.fnmatch(frel, _norm_pattern(e, chapter))
                    for e in own_exceptions):
                continue    # 自有例外口 → 不算越界
            writers = _embedded_writers(work_root / frel)
            if normalize_member(member) in writers:
                out_of_scope.append({
                    'path': frel,
                    'reason': 'EMBEDDED_DECLARATION_IN_MUST_NOT_WRITE',
                    'evidence': 'L3_EMBEDDED_WRITER_DECL',
                    'detail': f'产物头部自述写者含 {member}',
                })

        # ── 仅文件存在、无任何身份证据 → 疑似（不阻断）─────────────
        for frel in _files_under(work_root, pat_norm):
            if any(o['path'] == frel for o in out_of_scope):
                continue
            if own_exceptions and any(
                    fnmatch.fnmatch(frel, _norm_pattern(e, chapter))
                    for e in own_exceptions):
                continue
            suspected.append({
                'path': frel,
                'reason': 'FILE_EXISTS_NO_WRITER_EVIDENCE',
                'note': '文件存在但无写者身份证据 → 不判越界（UNKNOWN 优先于误杀）',
            })

    # ── 判定 ──────────────────────────────────────────────────────────
    if conflicts:
        verdict = 'CONTRACT_CONFLICT'
    elif out_of_scope:
        # 契约三原则②：越界产出视同未产出 → 越界优先于「产物齐备」，
        # 且被越界写入的那份产物不算已交付（present 中移除）。
        for o in out_of_scope:
            if o['path'] in present:
                present.remove(o['path'])
                missing.append({'path': o['path'],
                                'reason': 'OUT_OF_SCOPE_NOT_COUNTED',
                                'note': '越界产出视同未产出（契约三原则②）'})
        verdict = 'OUT_OF_SCOPE_WRITE'
    elif missing and not present:
        verdict = 'MISSING'
    elif missing:
        verdict = 'PARTIAL'
    else:
        verdict = 'PASS'

    action = mc.get('on_partial', 'BLOCK')
    return {
        'ok': verdict == 'PASS',
        'verdict': verdict,
        'member': member,
        'chapter': chapter,
        'mode': mode,
        'task_type': task_type or None,
        'targets': targets,
        'present': present,
        'missing': missing,
        'conditional_skipped': conditional_skipped,
        'out_of_scope': out_of_scope,
        'suspected': suspected,
        'conflicts': conflicts,
        'overlaps': overlaps,
        'on_partial': action,
        'on_timeout': mc.get('on_timeout', 'TIMEOUT'),
        'timeout_budget_s': mc.get('timeout_budget_s'),
        'max_retry': mc.get('max_retry'),
        'detail': {
            'PASS': 'must_produce 全部落盘，可推进',
            'PARTIAL': f'缺 {len(missing)} 项产物 → 按契约处置 {action}'
                       f'（不得静默当合格）',
            'MISSING': '应产出物一个都没有 → 本轮未交付，按 E2 处置',
            'OUT_OF_SCOPE_WRITE': '存在越界写（trace 自报证据）→ 该产出拒收（契约三原则②）',
            'CONTRACT_CONFLICT': '契约配置矛盾（路径归属本成员却在 must_not_write）→ 修契约',
        }.get(verdict, ''),
    }


def _section_numbers(work_root: Path, chapter: str) -> list[str]:
    """从 chapter_design §C 解析节序（复用 assemble_sections.parse_design_order）。"""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from assemble_sections import parse_design_order  # type: ignore
        design = work_root / '章节' / chapter / 'chapter_design.md'
        if design.is_file():
            return parse_design_order(design)
    except Exception:
        pass
    return []


# 已知成员 ID（用于从归属表「归属者」列里精确取出成员名，
# 不能用宽松正则——那会把 smart-textbook-team-team-lead 截成 team-lead）
KNOWN_MEMBERS = (
    'smart-textbook-team-team-lead',
    'didactic-architect',
    'literature-scout',
    'subject-writer',
    'quality-examiner',
    'visual-instructional-designer',
)


def path_owner(pkg_root: Path, rel_path: str, chapter: str) -> str | None:
    """查某路径的归属者（读 references/path-ownership.md）。

    返回归属者 member id；未登记返回 None（→ 判据不误杀）。

    匹配用 **glob 而非精确相等**：归属表里存在**变量段**，
    如 `章节/{ch##}/review/round{N}_report.md`（N = 轮次）——
    精确相等匹配不上实际的 `round1_report.md`（2026-11-04 实测漏判）。
    """
    owner_map = _load_path_owners(pkg_root)
    if not owner_map:
        return None
    norm = _norm_path(rel_path, chapter)
    for pat, owner in owner_map:
        p = _norm_path(pat, chapter)
        if fnmatch.fnmatch(norm, p):
            return owner
        # 目录型条目（如 `交付/`）→ 追加 /* 再试
        if not p.endswith('*') and fnmatch.fnmatch(norm, p + '/*'):
            return owner
    return None


_OWNER_CACHE: dict[str, list[tuple[str, str]]] = {}


def _load_path_owners(pkg_root: Path) -> list[tuple[str, str]]:
    """解析 path-ownership.md 的归属表 → [(路径模式, 归属者)]。"""
    key = str(pkg_root)
    if key in _OWNER_CACHE:
        return _OWNER_CACHE[key]
    f = pkg_root / 'references' / 'path-ownership.md'
    rows: list[tuple[str, str]] = []
    if f.is_file():
        for line in f.read_text(encoding='utf-8').splitlines():
            if not line.strip().startswith('|'):
                continue
            if '---' in line:
                continue
            cells = [c.strip() for c in line.strip('|').split('|')]
            if len(cells) < 2:
                continue
            path_cell = cells[0].strip('`')
            owner_cell = cells[1]
            if not path_cell or path_cell.startswith('路径'):
                continue
            # 从归属者列里取出 member id（可能是 **bold** 或带说明）
            # 用已知成员 ID 列表做**最长优先**匹配，避免把
            # smart-textbook-team-team-lead 截成 team-lead
            hits = [m for m in KNOWN_MEMBERS if m in owner_cell]
            if not hits:
                continue
            rows.append((path_cell, max(hits, key=len)))
    _OWNER_CACHE[key] = rows
    return rows


def _norm_path(p: str, chapter: str) -> str:
    """归一化路径用于归属表匹配：展开 {ch##}/{ch}，把 {图号}/{节号} 归一为 *。"""
    p = p.replace('{ch##}', chapter).replace('{ch}', chapter)
    p = re.sub(r'\{[^}]*\}', '*', p)
    p = p.replace('**', '*')
    return p.strip('/')


def _scan_glob(work_root: Path, pattern: str) -> list[dict]:
    """按 glob 模式扫描 work_root 下的实际文件（用于 must_not_write 的通配模式）。"""
    hits: list[dict] = []
    if '**' not in pattern and '*' not in pattern:
        return hits
    # 目录级通配：从 pattern 推断根目录
    root_rel = pattern.split('*')[0].rstrip('/')
    base = work_root / root_rel if root_rel else work_root
    if not base.is_dir():
        return hits
    tail = pattern[len(root_rel):].lstrip('/')
    for f in base.rglob('*'):
        if not f.is_file():
            continue
        try:
            rel = str(f.relative_to(work_root))
        except ValueError:
            continue
        if _match_glob(rel, pattern) or fnmatch.fnmatch(rel, tail):
            hits.append({'path': rel, 'reason': 'FILE_EXISTS'})
    return hits


def render(r: dict) -> str:
    lines = []
    v = r.get('verdict')
    lines.append(f"契约核对：{r.get('member')} / {r.get('chapter')} "
                 f"（模式 {r.get('mode')}）→ **{v}**")
    if r.get('detail'):
        lines.append(f'  {r["detail"]}')
    if r.get('present'):
        lines.append('  已落盘：')
        for x in r['present']:
            lines.append(f'    ✓ {x}')
    if r.get('missing'):
        lines.append('  缺失：')
        for m in r['missing']:
            extra = f'（{m.get("note")}）' if m.get('note') else ''
            lines.append(f'    ✗ {m["path"]}  [{m["reason"]}]{extra}')
    if r.get('out_of_scope'):
        lines.append('  越界写（拒收）：')
        for m in r['out_of_scope']:
            extra = f'（{m["detail"]}）' if m.get('detail') else ''
            lines.append(f'    ! {m["path"]}  [{m["reason"]}]{extra}')
    if r.get('conflicts'):
        lines.append('  契约矛盾（须修契约）：')
        for m in r['conflicts']:
            lines.append(f'    ✗ {m["path"]}  [{m.get("evidence", "")}]')
            lines.append(f'      {m["detail"]}')
    if r.get('overlaps'):
        lines.append(f'  提示（族内自有例外口，非矛盾，共 {len(r["overlaps"])} 项）：')
        for m in r['overlaps']:
            lines.append(f'    · {m["path"]}  [{m.get("evidence", "")}]')
    if r.get('suspected'):
        lines.append(f'  疑似（无写者证据，不阻断，共 {len(r["suspected"])} 项）：')
        for m in r['suspected'][:10]:
            lines.append(f'    ? {m["path"]}  [{m["reason"]}]')
        if len(r['suspected']) > 10:
            lines.append(f'    … 另有 {len(r["suspected"]) - 10} 项')
    return '\n'.join(lines)


_EXIT = {
    'PASS': EXIT_PASS,
    'PARTIAL': EXIT_PARTIAL,
    'MISSING': EXIT_MISSING,
    'OUT_OF_SCOPE_WRITE': EXIT_OUT_OF_SCOPE,
    'CONTRACT_CONFLICT': EXIT_INPUT_ERROR,
    'UNKNOWN_MEMBER': EXIT_INPUT_ERROR,
}


def main() -> int:
    ap = argparse.ArgumentParser(description='contract_check — 成员产物契约校验（部分落盘判据）')
    ap.add_argument('--work-root', required=True)
    ap.add_argument('--member', default='', help='成员 ID，如 subject-writer')
    ap.add_argument('--chapter', required=True, help='章号，如 ch03')
    ap.add_argument('--produce', action='append', default=None,
                    help='显式指定本轮应产出的具体路径（可多次；覆盖契约默认清单）')
    ap.add_argument('--mode', default='default', choices=['default', 'sections'],
                    help='sections = 节级模式（产物落在 sections/）')
    # ── ★H2（v2.10.1）：条件产物（task_type_required）──
    ap.add_argument('--task-type', default='',
                    help='★H2：按任务类型激活条件产物必查清单'
                         '（review-proofread-score / review-style / review-score / review-section）；'
                         '不给则常规核对 must_produce 并跳过条件产物（附 conditional_skipped 信息行）')
    ap.add_argument('--section', default='',
                    help='★H2：配合 --task-type review-section，展开 {节号} 占位符'
                         '（如 --section 3 → sections/3.verdict.md）')
    ap.add_argument('--slug', default='', help='slug（展开 {slug} 占位符）')
    ap.add_argument('--pkg-root', default=None,
                    help='专家包根（默认取本脚本所在包的上一级）')
    # ── R2：波次状态回写 / 主理人裁决 ────────────────────────────────
    ap.add_argument('--wave', type=int, default=None,
                    help='R2：回写该波次的契约快照（contract/net_words/reason）；'
                         '不给则走常规成员契约核对')
    ap.add_argument('--verdict', default='',
                    help=f'R2：主理人裁决 wave_verdict，合法值 '
                         f'{" | ".join(WAVE_VERDICTS)}（须配合 --wave）')
    ap.add_argument('--verdict-by', default='smart-textbook-team-team-lead',
                    help='R2：裁决落定者（默认主理人）')
    ap.add_argument('--verdict-reason', default='',
                    help='R2：裁决理由（写入 verdict_reason）')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()

    wr = Path(args.work_root).expanduser().resolve()
    if not wr.is_dir():
        print(f'ERROR  WORK_ROOT 不存在: {wr}', file=sys.stderr)
        return EXIT_INPUT_ERROR
    pkg_root = (Path(args.pkg_root).expanduser().resolve() if args.pkg_root
                else Path(__file__).resolve().parent.parent)

    # ── R2 分支：波次状态回写 / 主理人裁决 ──────────────────────────
    if args.wave is not None or args.verdict:
        if args.wave is None:
            print('ERROR  --verdict 必须配合 --wave（不知道改哪个波次）',
                  file=sys.stderr)
            return EXIT_INPUT_ERROR
        try:
            if args.verdict:
                r = set_wave_verdict(wr, args.chapter, args.wave,
                                     args.verdict, reason=args.verdict_reason,
                                     verdict_by=args.verdict_by)
            else:
                r = patch_wave_state(wr, args.chapter, args.wave)
        except (FileNotFoundError, ValueError, json.JSONDecodeError, OSError) as e:
            print(f'ERROR  {e}', file=sys.stderr)
            return EXIT_INPUT_ERROR
        if args.json:
            print(json.dumps(r, ensure_ascii=False, indent=2))
        else:
            if args.verdict:
                print(f'波次裁决落定：{args.chapter} w{args.wave} → '
                      f'**{r["wave_verdict"]}**（by {r["verdict_by"]}）')
                if r.get('verdict_reason'):
                    print(f'  理由：{r["verdict_reason"]}')
                print(f'  {r["path"]}')
            else:
                print(f'波次契约回写：{args.chapter} w{args.wave} → '
                      f'已交付 {len(r["delivered"])} 节，'
                      f'缺失 {len(r["missing"])} 节')
                for sec in r['delivered']:
                    print(f'  ✓ {sec}  净字数={r["net_words"].get(sec)}')
                for sec in r['missing']:
                    print(f'  ✗ {sec}  未交付')
                print(f'  {r["path"]}')
                print(f'  wave_verdict={r["wave_verdict"]}（脚本未改；'
                      f'由主理人落定）')
        return EXIT_PASS

    if not args.member:
        print('ERROR  常规契约核对须给 --member', file=sys.stderr)
        return EXIT_INPUT_ERROR

    try:
        r = check_contract(wr, pkg_root, args.member, args.chapter,
                           produce=args.produce, mode=args.mode, slug=args.slug,
                           task_type=args.task_type, section_no=args.section)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as e:
        print(f'ERROR  {e}', file=sys.stderr)
        return EXIT_INPUT_ERROR

    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print(render(r))
        if r.get('conditional_skipped'):
            print(f'\nℹ 条件产物 {len(r["conditional_skipped"])} 项本轮未核对'
                  f'（仅对应 task_type 派工时必查，用 --task-type 激活）：')
            for pth in r['conditional_skipped']:
                print(f'  - {pth}')
    return _EXIT.get(r.get('verdict'), EXIT_INPUT_ERROR)


if __name__ == '__main__':
    sys.exit(main())
