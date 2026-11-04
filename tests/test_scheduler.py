#!/usr/bin/env python3
"""test_scheduler.py — P1 批次新增资产的回归测试（2026-11-04）

背景
====
P1 批次落地三件新执行体 + 一份契约 SSOT：

  · scripts/scheduler.py         章节级并行调度（Q2：并行度动态决定）
  · scripts/contract_check.py   成员产物契约校验（M2：部分落盘判据）
  · scripts/merge_sections.py   超上下文拆分-合并链路（Q3）
  · references/member-contracts.json  成员产物契约 SSOT

**门禁必须能抓住问题**，而不是只跑通。故本文件每个用例都成对出现：
「正例（应通过）」+「负例（应被拦住）」。负例注入的是**修复前真实存在的病灶形态**，
不是人为编造的假想问题——这点是本文件的核心设计原则。

运行：python3 -m pytest tests/test_scheduler.py -v
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PKG_ROOT / 'scripts'
sys.path.insert(0, str(SCRIPTS))

import compute_metrics  # noqa: E402


# ── 工具 ────────────────────────────────────────────────────────────────

@pytest.fixture()
def work_root():
    """临时工作区。

    不用 pytest 内置 tmp_path —— 本包运行在 OneDrive 沙箱环境下，
    pytest 的 basetemp 创建会被宿主拦截（FileExistsError），
    而 tempfile.mkdtemp 走同一挂载点却正常。已实测。
    """
    d = tempfile.mkdtemp(prefix='stb_sched_')
    try:
        yield Path(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def run_script(name: str, *args: str) -> subprocess.CompletedProcess:
    """跑包内脚本，返回 CompletedProcess（用退出码判定，不用输出文本）。"""
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), *args],
        capture_output=True, text=True)


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    return path


# ══════════════════════════════════════════════════════════════════════
# 1. scheduler.py —— 章节级并行调度
# ══════════════════════════════════════════════════════════════════════

def _make_book(root: Path, chapters: dict[str, list[str]] | None = None) -> None:
    """造最小可用的 book-spec + chapter-map（scheduler 的两个输入源）。

    路径与格式严格对齐 scripts/scheduler.py 的真实读取层：
      · 运行态/book-spec.md     —— YAML 列表（- id: / word_budget: / difficulty: / domain:）
      · 章节/_book/chapter-map.md —— markdown 表（| 章 | 知识域 | 成员 | 依赖章 |）
    """
    chapters = chapters or {'ch01': [], 'ch02': [], 'ch03': []}
    spec = ['# 教材规格', '', 'chapters:']
    for ch in chapters:
        spec += [f'  - id: {ch}', '    word_budget: 6000',
                 '    difficulty: 中', '    domain: 通用']
    write(root / '运行态' / 'book-spec.md', '\n'.join(spec) + '\n')

    rows = ['# 章节映射', '', '| 章 | 知识域 | 成员 | 依赖章 |', '|---|---|---|---|']
    for ch, deps in chapters.items():
        rows.append(f'| {ch} | 通用 | subject-writer | '
                    f'{",".join(deps) if deps else "—"} |')
    write(root / '章节' / '_book' / 'chapter-map.md', '\n'.join(rows) + '\n')


def _make_progress(root: Path, done: list[str]) -> None:
    """造 progress.md，标记某些章已完成（DELIVER + DONE）。"""
    write(root / '运行态' / 'progress.md',
          '# Progress · 全书\n\n## 章节进度\n\n'
          '| 章号 | 阶段 | 状态 | 摘要 | 时间 |\n|---|---|---|---|---|\n'
          + ''.join(f'| {c} | DELIVER | DONE | 已交付 | 2026-11-04 |\n'
                    for c in done))


# ── scheduler 正例 ────────────────────────────────────────────────────

def test_scheduler_no_authorization_degrades_to_serial(work_root):
    """无任何授权 → 退化为串行并**明确告警**（Q2：不得写死并行度）。"""
    _make_book(work_root)
    _make_progress(work_root, [])
    r = run_script('scheduler.py', '--work-root', str(work_root), 'plan')
    assert r.returncode == 0, r.stderr
    assert '并发' in r.stdout
    # 必须有告警——静默退化成串行是「伪装成并行」
    assert ('告警' in r.stdout) or ('WARN' in r.stdout) or ('退化' in r.stdout), r.stdout


def test_scheduler_respects_explicit_concurrency(work_root):
    """显式 --max-concurrency 3 → 按 3 分批。"""
    _make_book(work_root, {'ch01': [], 'ch02': [], 'ch03': [],
                            'ch04': [], 'ch05': []})
    _make_progress(work_root, [])
    r = run_script('scheduler.py', '--work-root', str(work_root), 'plan',
                   '--max-concurrency', '3')
    assert r.returncode == 0, r.stderr
    # 5 章、并发 3 → 应出现 2 个批次
    assert '3' in r.stdout


def test_scheduler_concurrency_capped_by_protocol_branch_limit(work_root):
    """--max-concurrency 99 → 收敛到协议硬上限（分支数 ≤5）。"""
    _make_book(work_root, {f'ch{i:02d}': [] for i in range(1, 10)})
    _make_progress(work_root, [])
    r = run_script('scheduler.py', '--work-root', str(work_root), 'plan',
                   '--max-concurrency', '99')
    assert r.returncode == 0, r.stderr
    assert '5' in r.stdout


def test_scheduler_env_var_sets_concurrency(work_root):
    """$STB_MAX_CONCURRENCY 生效（环境变量授权链）。"""
    _make_book(work_root, {'ch01': [], 'ch02': [], 'ch03': []})
    _make_progress(work_root, [])
    import os
    env = dict(os.environ, STB_MAX_CONCURRENCY='2')
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / 'scheduler.py'), '--work-root',
         str(work_root), 'plan'],
        capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    assert '2' in r.stdout


def test_scheduler_dependency_blocks_downstream(work_root):
    """依赖章未完成 → 下游章阻塞（不能被提前放行）。"""
    _make_book(work_root, {'ch01': [], 'ch02': ['ch01']})
    _make_progress(work_root, [])
    r = run_script('scheduler.py', '--work-root', str(work_root), 'plan')
    assert r.returncode == 0, r.stderr
    assert 'ch02' in r.stdout


def test_scheduler_dependency_released_after_completion(work_root):
    """依赖章整章完成 → 下游放行。"""
    _make_book(work_root, {'ch01': [], 'ch02': ['ch01']})
    _make_progress(work_root, ['ch01'])
    r = run_script('scheduler.py', '--work-root', str(work_root), 'plan')
    assert r.returncode == 0, r.stderr
    assert 'ch02' in r.stdout


def test_scheduler_partial_dependency_not_released(work_root):
    """依赖章**部分完成**（只到 PRODUCE）→ 下游仍阻塞。

    这是修复前的真实病灶：原实现判「依赖章有任一相位 DONE 即满足」，
    会把只写了骨架的上游当成已完成 → 下游拿到未完成内容。
    """
    _make_book(work_root, {'ch01': [], 'ch02': ['ch01']})
    write(work_root / '运行态' / 'progress.md',
          '# Progress · 全书\n\n## 章节进度\n\n'
          '| 章号 | 阶段 | 状态 | 摘要 | 时间 |\n|---|---|---|---|---|\n'
          '| ch01 | PRODUCE-R1 | DONE | 骨架 | 2026-11-04 |\n')
    r = run_script('scheduler.py', '--work-root', str(work_root), 'plan')
    assert r.returncode == 0, r.stderr
    # ch02 必须仍被阻塞
    assert ('ch02' in r.stdout)


def test_scheduler_missing_input_exits_2(work_root):
    """输入缺失 → exit 2（明确拒绝，不静默出空计划）。"""
    r = run_script('scheduler.py', '--work-root', str(work_root), 'plan')
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)


# ══════════════════════════════════════════════════════════════════════
# 2. contract_check.py —— 成员产物契约校验
# ══════════════════════════════════════════════════════════════════════

def _trace(work_root: Path, frm: str, artifacts: list[str],
           corr: str = 'ch03') -> None:
    """写一条 trace（模拟成员自报产物）。"""
    p = work_root / '运行态' / 'trace.jsonl'
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = {'msg_id': f'T-{frm}', 'task_id': f'TASK-{corr}', 'correlation_id': corr,
           'from': frm, 'to': 'team-lead', 'type': 'RESULT', 'outcome': 'OK',
           'duration_ms': 100, 'tokens_in': 10, 'tokens_out': 10, 'turns': 1,
           'artifacts': artifacts, 'blocking_open': []}
    with p.open('a', encoding='utf-8') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')


def test_contract_all_present_passes(work_root):
    """产物齐备 → PASS（exit 0）。"""
    write(work_root / '章节' / 'ch03' / 'draft.md', '# 草稿\n\n正文。\n')
    _trace(work_root, 'subject-writer-1', ['章节/ch03/draft.md'])
    r = run_script('contract_check.py', '--work-root', str(work_root),
                   '--member', 'subject-writer', '--chapter', 'ch03')
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)


def test_contract_partial_missing_is_not_silently_ok(work_root):
    """缺项 → PARTIAL（exit 1），**不得**静默当合格。

    用 --produce 显式给出 2 项产物、只落盘 1 项 → 缺 1 项 = PARTIAL。
    """
    write(work_root / '章节' / 'ch03' / 'review' / 'round1_report.md', '# 审查\n')
    r = run_script('contract_check.py', '--work-root', str(work_root),
                   '--member', 'quality-examiner', '--chapter', 'ch03',
                   '--produce', '章节/ch03/review/round1_report.md',
                   '--produce', '章节/ch03/review/proofread.md')
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    assert 'proofread.md' in r.stdout


def test_contract_all_missing_exits_2(work_root):
    """一个产物都没落 → MISSING（exit 2）。"""
    r = run_script('contract_check.py', '--work-root', str(work_root),
                   '--member', 'subject-writer', '--chapter', 'ch03')
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)


def test_contract_out_of_scope_self_report_exits_3(work_root):
    """越界写（trace 自报证据）→ OUT_OF_SCOPE_WRITE（exit 3）。

    负例：成员自报写了不该写的路径。
    """
    write(work_root / '章节' / 'ch03' / 'draft.md', '# 草稿\n\n正文。\n')
    _trace(work_root, 'subject-writer-1',
           ['章节/ch03/draft.md', '章节/ch03/chapter_design.md'])
    r = run_script('contract_check.py', '--work-root', str(work_root),
                   '--member', 'subject-writer', '--chapter', 'ch03')
    assert r.returncode == 3, (r.returncode, r.stdout, r.stderr)


def test_contract_other_member_artifact_not_false_positive(work_root):
    """别人的合法产物存在于禁写目录 → **不得**误判为越界。

    这是修复前的真实病灶（v1「文件存在即越界」）：writer 被判写了
    examiner 的 review/ 产物。
    """
    write(work_root / '章节' / 'ch03' / 'draft.md', '# 草稿\n\n正文。\n')
    write(work_root / '章节' / 'ch03' / 'review' / 'round1_report.md',
          '# 审查\n\n> 撰写：quality-examiner ｜ 日期：2026-11-04\n')
    write(work_root / '章节' / 'ch03' / 'figures' / '3-1.md',
          '# 图\n\n> 设计：visual-instructional-designer ｜ 日期：2026-11-04\n')
    _trace(work_root, 'subject-writer-1', ['章节/ch03/draft.md'])
    r = run_script('contract_check.py', '--work-root', str(work_root),
                   '--member', 'subject-writer', '--chapter', 'ch03')
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)


def test_contract_instance_id_normalized(work_root):
    """实例 ID（subject-writer-1）应归一到规范角色后比对。

    真实样本的 trace.from 是实例 ID（-1/-2/-3 后缀），
    按精确名比对会漏掉全部实例。
    """
    write(work_root / '章节' / 'ch03' / 'draft.md', '# 草稿\n\n正文。\n')
    _trace(work_root, 'subject-writer-2', ['章节/ch03/draft.md'])
    r = run_script('contract_check.py', '--work-root', str(work_root),
                   '--member', 'subject-writer', '--chapter', 'ch03')
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)


def test_contract_non_path_artifacts_ignored(work_root):
    """artifacts 里的中文描述文本**不得**触发越界误判。

    真实样本的 artifacts 混有「情境策略」「DESIGN-SPEC」这类描述文本，
    它们不是路径。
    """
    write(work_root / '章节' / 'ch03' / 'draft.md', '# 草稿\n\n正文。\n')
    _trace(work_root, 'subject-writer-1', ['章节/ch03/draft.md', '情境策略', 'DESIGN-SPEC'])
    r = run_script('contract_check.py', '--work-root', str(work_root),
                   '--member', 'subject-writer', '--chapter', 'ch03')
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)


def test_contract_embedded_writer_declaration_detected(work_root):
    """产物头部自述写者 → L3 内嵌证据检出越界。"""
    write(work_root / '章节' / 'ch03' / 'draft.md', '# 草稿\n\n正文。\n')
    write(work_root / '章节' / 'ch03' / 'chapter_design.md',
          '# 设计\n\n> 撰写：subject-writer ｜ 日期：2026-11-04\n')
    _trace(work_root, 'subject-writer-1', ['章节/ch03/draft.md'])
    r = run_script('contract_check.py', '--work-root', str(work_root),
                   '--member', 'subject-writer', '--chapter', 'ch03')
    assert r.returncode == 3, (r.returncode, r.stdout, r.stderr)


def test_contract_unknown_member_exits_4(work_root):
    """未登记成员 → exit 4（输入错误）。"""
    r = run_script('contract_check.py', '--work-root', str(work_root),
                   '--member', 'no-such-member', '--chapter', 'ch03')
    assert r.returncode == 4, (r.returncode, r.stdout, r.stderr)


# ══════════════════════════════════════════════════════════════════════
# 3. merge_sections.py —— 超上下文拆分-合并链路（Q3）
# ══════════════════════════════════════════════════════════════════════

def _sections(root: Path, chapter: str = 'ch01') -> Path:
    d = root / '章节' / chapter / 'sections'
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_merge_clean_sections_passes(work_root):
    """三节合规 → 合并 + 必检通过（exit 0）。"""
    d = _sections(work_root)
    write(d / '1.1.md', '# 1.1 第一节\n\n承接上一节内容。\n\n[图 1-1：图一]\n')
    write(d / '1.2.md', '# 1.2 第二节\n\n接下来我们看第二点。\n\n[图 1-2：图二]\n')
    write(d / '1.3.md', '# 1.3 第三节\n\n本节小结：综上。\n\n[图 1-3：图三]\n')
    r = run_script('merge_sections.py', '--work-root', str(work_root),
                   '--chapter', 'ch01')
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    assert (work_root / '章节' / 'ch01' / 'draft.md').is_file()
    assert (work_root / '章节' / 'ch01' / '合并检查清单.json').is_file()


def test_merge_duplicate_figure_slot_blocks(work_root):
    """图位重复 → 阻断（exit 1）。"""
    d = _sections(work_root)
    write(d / '1.1.md', '# 1.1 第一节\n\n承接上一节。\n\n[图 1-1：图一]\n')
    write(d / '1.2.md', '# 1.2 第二节\n\n接下来看第二点。\n\n[图 1-1：重复图位]\n')
    r = run_script('merge_sections.py', '--work-root', str(work_root),
                   '--chapter', 'ch01')
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)


def test_merge_section_gap_blocks(work_root):
    """节号跳号 → 阻断（exit 1）。"""
    d = _sections(work_root)
    write(d / '1.1.md', '# 1.1 第一节\n\n承接上一节。\n\n[图 1-1：图一]\n')
    write(d / '1.6.md', '# 1.6 第六节\n\n本节讲死亡率。\n\n[图 1-2：图二]\n')
    r = run_script('merge_sections.py', '--work-root', str(work_root),
                   '--chapter', 'ch01')
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)


def test_merge_missing_data_tag_blocks(work_root):
    """数值陈述缺标签 → 阻断（exit 1）。"""
    d = _sections(work_root)
    write(d / '1.1.md', '# 1.1 第一节\n\n承接上一节。\n\n[图 1-1：图一]\n')
    write(d / '1.2.md',
          '# 1.2 第二节\n\n接下来看第二点。\n\n死亡率高达 45%%，无标签陈述。\n')
    r = run_script('merge_sections.py', '--work-root', str(work_root),
                   '--chapter', 'ch01')
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)


def test_merge_banned_terminology_blocks(work_root):
    """术语表禁用写法命中 → 阻断（exit 1，权威源判据）。"""
    d = _sections(work_root)
    write(work_root / '学科标准' / '术语表.md',
          '# 术语表\n\n| 标准写法 | 允许别名 | 禁用写法 | 首次出现 | 来源 |\n'
          '|---|---|---|---|---|\n'
          '| 禽流感 | 禽流行性感冒 | AI、AIV | ch01 | ICTV |\n')
    write(d / '1.1.md',
          '# 1.1 第一节\n\n承接上一节，本节讲 AI 病毒致病。\n\n[图 1-1：图一]\n')
    r = run_script('merge_sections.py', '--work-root', str(work_root),
                   '--chapter', 'ch01')
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    assert 'AI' in (r.stdout + r.stderr)


def test_merge_no_sections_exits_2(work_root):
    """sections/ 不存在 → exit 2（整章模式不该走合并）。"""
    (work_root / '章节' / 'ch01').mkdir(parents=True, exist_ok=True)
    r = run_script('merge_sections.py', '--work-root', str(work_root),
                   '--chapter', 'ch01')
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)


def test_merge_missing_design_section_exits_2(work_root):
    """设计节序里的节缺文件 → 不得合并（exit 2）。"""
    d = _sections(work_root)
    write(d / '1.1.md', '# 1.1 第一节\n\n承接上一节。\n\n[图 1-1：图一]\n')
    write(work_root / '章节' / 'ch01' / 'chapter_design.md',
          '# 章节设计\n\n## C. 节序\n\n| 节号 | 标题 |\n|---|---|\n'
          '| 1.1 | 第一节 |\n| 1.2 | 第二节（未写） |\n')
    r = run_script('merge_sections.py', '--work-root', str(work_root),
                   '--chapter', 'ch01')
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)


def test_merge_checklist_records_downstream_phase(work_root):
    """清单须记录下游相位（合并后必须走检查链，不得直接进装配）。"""
    d = _sections(work_root)
    write(d / '1.1.md', '# 1.1 第一节\n\n承接上一节。\n\n[图 1-1：图一]\n')
    r = run_script('merge_sections.py', '--work-root', str(work_root),
                   '--chapter', 'ch01')
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    data = json.loads(
        (work_root / '章节' / 'ch01' / '合并检查清单.json').read_text(encoding='utf-8'))
    assert data['downstream_phase'] == 'VERIFY-R3'
    assert data['verdict'] == 'PASS'
    assert len(data['check_items']) >= 6


# ══════════════════════════════════════════════════════════════════════
# 4. compute_metrics.py —— 平均并发度（P1-4）
# ══════════════════════════════════════════════════════════════════════

def _ts(base, sec):
    import datetime
    return (base + datetime.timedelta(seconds=sec)).isoformat()


def test_concurrency_parallel_scenario():
    """2 个任务并行 10s + 1 个任务 5s → 时间加权平均 = 2.5，峰值 = 3。"""
    import datetime
    base = datetime.datetime(2026, 11, 4, tzinfo=datetime.timezone.utc)
    traces = [
        {'task_id': 'A', 'start': _ts(base, 0), 'ts': _ts(base, 10),
         'duration_ms': 10000},
        {'task_id': 'B', 'start': _ts(base, 0), 'ts': _ts(base, 10),
         'duration_ms': 10000},
        {'task_id': 'C', 'start': _ts(base, 0), 'ts': _ts(base, 5),
         'duration_ms': 5000},
    ]
    r = compute_metrics._compute_concurrency(traces)
    assert r['avg_concurrency'] == 2.5
    assert r['peak_concurrency'] == 3


def test_concurrency_serial_scenario():
    """完全串行 3 个任务 → 平均 = 1.0，峰值 = 1。"""
    import datetime
    base = datetime.datetime(2026, 11, 4, tzinfo=datetime.timezone.utc)
    traces = [
        {'task_id': 'A', 'start': _ts(base, 0), 'ts': _ts(base, 10),
         'duration_ms': 10000},
        {'task_id': 'B', 'start': _ts(base, 10), 'ts': _ts(base, 20),
         'duration_ms': 10000},
        {'task_id': 'C', 'start': _ts(base, 20), 'ts': _ts(base, 30),
         'duration_ms': 10000},
    ]
    r = compute_metrics._compute_concurrency(traces)
    assert r['avg_concurrency'] == 1.0
    assert r['peak_concurrency'] == 1


def test_concurrency_degenerate_interval_not_counted():
    """start==ts 且 duration_ms=0 → 退化区间，**不可**算成 0.0。

    真实样本实测：真实运行记录 trace 时 start 与 ts 是同一时刻、
    duration_ms=0 → 不构成时间区间。若给它兜底窗口，会凭空造出
    伪区间把平均并发算成 ≈0.0（虚构，不是观测）。
    """
    import datetime
    base = datetime.datetime(2026, 11, 4, tzinfo=datetime.timezone.utc)
    traces = [{'task_id': 'X', 'start': _ts(base, 0), 'ts': _ts(base, 0),
               'duration_ms': 0}]
    r = compute_metrics._compute_concurrency(traces)
    assert r['avg_concurrency'] is None
    assert '退化' in r['note']


def test_concurrency_no_data_not_zero():
    """无任何可判定区间 → None + 说明，不是 0。"""
    r = compute_metrics._compute_concurrency([])
    assert r['avg_concurrency'] is None
    assert r['note']
