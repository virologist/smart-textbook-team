#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stt.py spawn 端到端测试（真实任务包 → 委托 assemble_spawn_prompt.py → 落盘）

注：本环境 pytest 自带 tmp_path 被沙箱 broker 拦截，故自建临时目录（os.makedirs 可用）。
本测试依赖 vendor/shared-core/assemble_spawn_prompt.py（spawn 真源）。若该核心缺失，
spawn 会 exit 3，测试将失败——这是真实回归信号，不应静默跳过。
"""
from __future__ import annotations
import os
import subprocess
import sys
import shutil
from pathlib import Path

STT = Path(__file__).resolve().parent.parent / "scripts" / "stt.py"
# 放 /tmp 而非 repo 内 .pytest-tmp：repo 扫描类门禁（学科中立/静态契约）会扫到
# 测试产物里的绝对路径而误报；同时避免污染仓库。
_BASE = Path("/tmp/stt_test_stt_spawn_e2e")

_TASK_PKG = """\
---
name: subject-writer
maxTurns: 20
skills: [agent-harness-protocol, citation-verify]
---

```json
{
  "objective": "撰写 ch01 禽流感概述章节正文",
  "output_format": "Markdown，含标题层级与图表占位",
  "constraints": ["字数 1500-2000", "须引用近 5 年文献"],
  "task_boundary": "仅撰写正文，不改版式；不处理跨章引用",
  "acceptance_criteria": [
    {"check": "净字数落在 1500-2000 区间", "judge_mode": "机", "threshold": ">= 1500 且 <= 2000，源 config/chapter-rules.yaml#word_range"},
    {"check": "近 5 年文献占比 >= 60%", "judge_mode": "机+人", "threshold": ">= 0.6，源 config/citation-policy.yaml#recent_ratio"}
  ]
}
```
"""


def _setup() -> Path:
    d = _BASE / f"run_{os.getpid()}_{len(os.listdir(_BASE)) if _BASE.exists() else 0}"
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)
    (d / "task_pkg.md").write_text(_TASK_PKG, encoding="utf-8")
    return d


def test_stt_spawn_e2e_writes_prompt():
    b = _setup()
    run_dir = b / "run"
    out = run_dir / "spawn__subject-writer.md"
    r = subprocess.run([
        sys.executable, str(STT), "spawn",
        "--member", "subject-writer",
        "--task-id", "ch01-PRODUCE-R1",
        "--task-file", str(b / "task_pkg.md"),
        "--run-dir", str(run_dir),
        "--check-task-package",
        "--out", str(out),
    ], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert out.is_file(), "spawn 未落盘产出文件"
    text = out.read_text(encoding="utf-8")
    assert len(text) > 1000, "落盘内容异常短"
    assert "subject-writer" in text, "产出未含成员标识"
    assert "ch01-PRODUCE-R1" in text, "产出未含 task-id"
