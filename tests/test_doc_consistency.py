#!/usr/bin/env python3
"""test_doc_consistency.py — 文档一致性门禁的回归测试（2026-11-04 P2 批次）

背景
----
`scripts/check_doc_consistency.py` 是本轮 P2 批次新建的文档漂移门禁
（计数 / 量纲 / 编号 / 归属 6 条判据）。门禁自身也要被守——
否则它可能「判据写坏了 → 永远绿灯」，比没有门禁更糟。

本文件做两件事：
  ① 正向：真实包跑门禁必须 exit 0（不得误杀合法内容）；
  ② 负向：每条判据各注入一个**真实历史病灶形态**的破坏样本，
     门禁必须拦下（拦不下 = 该判据是假门禁）。

负向样本用的是**修复前的真实文本**，不是臆造形态：
  D1 「等 12 类」——修复前 team-lead.md 的原话（router §1 实为 16 类）
  D2 「总分 <0.7」——修复前的 0-1 量纲写法（当前量纲 0-100）
  D3 两个「6.」——修复前 subject-writer.md 的原话
  D4 「.- R1 结构审查」——修复前 quality-examiner.md 的原话
  D5 `.mmd/.svg` + `.png/.svg` 两行都声明 .svg——修复前 path-ownership 的原状
  D6 删掉 `.pdf` 归属行——修复前 path-ownership 曾误删归属导致的无主路径

运行：python3 -m pytest tests/test_doc_consistency.py -v
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PKG_ROOT / "scripts"

# ── 工具 ────────────────────────────────────────────────────────────────


@pytest.fixture()
def sandbox_pkg():
    """把包内相关目录复制到临时区，供破坏性实验使用。

    不用 pytest 内置 tmp_path —— 本包运行在 OneDrive 沙箱环境下，
    pytest 的 basetemp 创建会被宿主拦截（FileExistsError），
    而 tempfile.mkdtemp 走同一挂载点却正常。已实测。
    """
    d = tempfile.mkdtemp(prefix="stt_doc_")
    try:
        for sub in ("agents", "skills", "references", "scripts"):
            src = PKG_ROOT / sub
            if src.is_dir():
                shutil.copytree(src, Path(d) / sub)
        for f in ("README.md", "CONTRIBUTING.md", "AGENTS.md"):
            src = PKG_ROOT / f
            if src.is_file():
                shutil.copy2(src, Path(d) / f)
        yield Path(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _load_gate(root: Path):
    """加载被测门禁模块（从沙箱副本加载，确保测的是副本里的版本）。"""
    spec = importlib.util.spec_from_file_location(
        "check_doc_consistency", root / "scripts" / "check_doc_consistency.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_gate(root: Path):
    """跑门禁 → 返回 (failed_ids, items)。"""
    mod = _load_gate(root)
    items, failed, _notes = mod.check(root)
    return {i[0] for i in failed}, items


def _detail(items, cid):
    for cid_, desc, ok, detail in items:
        if cid_ == cid:
            return detail
    return ""


# ── 正向：真实包必须全绿 ─────────────────────────────────────────────────

def test_real_package_is_clean():
    """真实包跑门禁必须 exit 0（不得误杀合法内容）。"""
    failed, _ = _run_gate(PKG_ROOT)
    assert not failed, f"真实包被误判，失败判据：{sorted(failed)}"


def test_gate_has_six_criteria():
    """门禁必须恰好有 6 条判据（少一条 = 有判据失效且无人知道）。"""
    _failed, items = _run_gate(PKG_ROOT)
    ids = {i[0] for i in items}
    assert ids == {"D1", "D2", "D3", "D4", "D5", "D6"}, ids


def test_task_type_count_parsed_from_ssot():
    """D1 的 task_type 数必须来自 router §1 实解析，不得硬编码。"""
    mod = _load_gate(PKG_ROOT)
    count, types = mod.parse_task_type_count(PKG_ROOT)
    assert count == 16, f"router §1 实解析 {count} 类：{types}"
    assert "review-score" in types and "gap-retrieval" in types
    # B1-3（2026-11-04）：R4+R5 合并派工类型必须在内
    assert "review-proofread-score" in types


# ── 负向：每条判据各一个破坏样本 ─────────────────────────────────────────

def test_d1_catches_wrong_task_type_count(sandbox_pkg):
    """D1：把「16 类」改回「12 类」必须被拦。"""
    p = sandbox_pkg / "agents" / "smart-textbook-team-team-lead.md"
    t = p.read_text(encoding="utf-8")
    assert "等 16 类" in t, "前置条件：当前包应写 16 类"
    p.write_text(t.replace("等 16 类", "等 12 类"), encoding="utf-8")

    failed, items = _run_gate(sandbox_pkg)
    assert "D1" in failed, "D1 未拦住 task_type 计数漂移"
    assert "12 类" in _detail(items, "D1")


def test_d2_catches_legacy_0_1_confidence_scale(sandbox_pkg):
    """D2：把量纲改回 0-1（<0.7）必须被拦。"""
    p = sandbox_pkg / "agents" / "smart-textbook-team-team-lead.md"
    t = p.read_text(encoding="utf-8")
    assert "<70 走升级" in t, "前置条件：当前包应写 <70"
    p.write_text(t.replace("<70 走升级", "<0.7 走升级"), encoding="utf-8")

    failed, items = _run_gate(sandbox_pkg)
    assert "D2" in failed, "D2 未拦住 0-1 量纲残留"
    assert "0-1 量纲" in _detail(items, "D2")


def test_d3_catches_duplicate_ordered_list_number(sandbox_pkg):
    """D3：两个「6.」必须被拦。"""
    p = sandbox_pkg / "agents" / "subject-writer.md"
    t = p.read_text(encoding="utf-8")
    assert "7. **学段适配表达**" in t, "前置条件：当前包编号应为 7."
    p.write_text(t.replace("7. **学段适配表达**", "6. **学段适配表达**"),
                 encoding="utf-8")

    failed, items = _run_gate(sandbox_pkg)
    assert "D3" in failed, "D3 未拦住同级重复编号"
    assert "重复" in _detail(items, "D3")


def test_d4_catches_broken_list_marker(sandbox_pkg):
    """D4：`.- ` 残缺标记必须被拦。"""
    p = sandbox_pkg / "agents" / "quality-examiner.md"
    t = p.read_text(encoding="utf-8")
    assert "   - R1 结构审查：" in t, "前置条件：当前包标记应为 `- `"
    p.write_text(t.replace("   - R1 结构审查：", "   .- R1 结构审查："),
                 encoding="utf-8")

    failed, items = _run_gate(sandbox_pkg)
    assert "D4" in failed, "D4 未拦住残缺列表标记"


def test_d5_catches_duplicate_owner_for_same_file(sandbox_pkg):
    """D5：`.svg` 被 designer 与 team-lead 同时声明必须被拦。

    用修复前的**真实历史形态**：`{图号}.mmd/.svg` 与 `{图号}.png/.svg`
    两行都在 assets/ 目录下声明了 .svg。
    """
    p = sandbox_pkg / "references" / "path-ownership.md"
    t = p.read_text(encoding="utf-8")
    # 还原历史形态：designer 拿 .mmd/.svg，team-lead 拿 .png/.svg
    t = t.replace(
        "| `章节/{ch##}/figures/assets/{图号}.mmd` | visual-instructional-designer | 写（图表源码：Mermaid） | 只读 |",
        "| `章节/{ch##}/figures/assets/{图号}.mmd/.svg` | visual-instructional-designer | 写（图表源码） | 只读 |")
    t = t.replace(
        "| `章节/{ch##}/figures/assets/{图号}.svg` | **smart-textbook-team-team-lead**（由 `build_manuscript.py` 从 md ```svg 代码块落盘，见 `write_source_assets()`） | 写（SVG 矢量直嵌 docx，不经 mmdc） | 只读 |",
        "| `章节/{ch##}/figures/assets/{图号}.png/.svg` | **smart-textbook-team-team-lead**（由 `build_manuscript.py` 栅格化/导出） | 写 | 只读 |")
    p.write_text(t, encoding="utf-8")

    failed, items = _run_gate(sandbox_pkg)
    assert "D5" in failed, "D5 未拦住同文件双归属"
    d5 = _detail(items, "D5")
    assert ".svg" in d5, f"D5 详情应点名 .svg：{d5}"


def test_d5_allows_declared_dual_writer(sandbox_pkg):
    """D5 反向自检：显式标注「双写者」且给仲裁规则的 .png 必须放行。

    没有这条，D5 会逼着人删掉双写者声明——那才是真破坏。
    """
    failed, _ = _run_gate(sandbox_pkg)
    assert "D5" not in failed, "D5 误伤了显式声明的 .png 双写者"


def test_d6_catches_ownerless_asset_path(sandbox_pkg):
    """D6：删掉 `.pdf` 归属行造成无主路径必须被拦。"""
    p = sandbox_pkg / "references" / "path-ownership.md"
    lines = p.read_text(encoding="utf-8").splitlines()
    kept = [l for l in lines
            if not l.startswith("| `章节/{ch##}/figures/assets/{图号}.pdf`")]
    assert len(kept) < len(lines), "前置条件：.pdf 归属行应存在"
    p.write_text("\n".join(kept) + "\n", encoding="utf-8")

    failed, items = _run_gate(sandbox_pkg)
    assert "D6" in failed, "D6 未拦住无主路径"
    assert ".pdf" in _detail(items, "D6")


def test_immune_files_are_skipped(sandbox_pkg):
    """CHANGELOG 是历史流水，照抄旧数字必须免检。"""
    p = sandbox_pkg / "README.md"
    t = p.read_text(encoding="utf-8")
    # README 不是免疫文件 → 改它应被 D1 拦
    assert "16 类 task_type" in t, "前置条件：README 应写 16 类 task_type"
    p.write_text(t.replace("16 类 task_type", "12 类 task_type"), encoding="utf-8")
    failed, _ = _run_gate(sandbox_pkg)
    assert "D1" in failed, "README 的计数漂移应被拦"

    ch = sandbox_pkg / "skills" / "task-router" / "SKILL.md"
    ct = ch.read_text(encoding="utf-8")
    # task-router/SKILL.md 是 SSOT 本体，不在免疫名单内；
    # 真正的免疫名单是 CHANGELOG.md / SKILL_CHANGELOG.md
    assert "CHANGELOG.md" in (PKG_ROOT / "scripts" / "check_doc_consistency.py").read_text(
        encoding="utf-8")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
