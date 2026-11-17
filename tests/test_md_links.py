#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_md_links.py — check_md_links.py 链接有效性门禁的正反例（v2.18.1）

核心功能：真实链接通过、假链接被抓
免疫豁免：CHANGELOG/SKILL_CHANGELOG/日期报告/fixtures 占位符/勘误行
边界：占位符目录可解析、非路径目标（PMID 标签）跳过、行号定位

用法：python3 -m pytest tests/test_md_links.py -q --basetemp=/private/tmp/...
"""
import shutil
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PKG_ROOT / "scripts"))
from check_md_links import check_links, _placeholder_resolvable  # noqa: E402


@pytest.fixture()
def sandbox_pkg(tmp_path):
    """最小假包根：agents/ + skills/ + scripts/ 三目录骨架。"""
    for d in ("agents", "skills/real-skill", "scripts", "docs/2026-01-01"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    (tmp_path / "skills/real-skill/SKILL.md").write_text("# real\n", encoding="utf-8")
    (tmp_path / "scripts/_common.py").write_text("# c\n", encoding="utf-8")
    return tmp_path


# ── 核心功能 ──────────────────────────────────────────────

def test_real_link_passes(sandbox_pkg):
    (sandbox_pkg / "agents/a.md").write_text(
        "见 [skill](../skills/real-skill/SKILL.md) 和 `scripts/_common.py`。\n",
        encoding="utf-8")
    r = check_links(sandbox_pkg)
    assert r["broken"] == []


def test_broken_md_link_caught(sandbox_pkg):
    (sandbox_pkg / "agents/a.md").write_text(
        "见 [skill](../skills/real-skill/MISSING.md)。\n", encoding="utf-8")
    r = check_links(sandbox_pkg)
    assert len(r["broken"]) == 1 and r["broken"][0]["kind"] == "md-link"


def test_broken_backtick_path_caught_with_lineno(sandbox_pkg):
    (sandbox_pkg / "agents/a.md").write_text(
        "首行真引用 `scripts/_common.py`。\n第二行假引用 `skills/nope/SKILL.md`。\n",
        encoding="utf-8")
    r = check_links(sandbox_pkg)
    assert len(r["broken"]) == 1
    assert r["broken"][0]["target"] == "skills/nope/SKILL.md"
    assert r["broken"][0]["file"].endswith(":2")          # 行号定位


# ── 免疫豁免 ──────────────────────────────────────────────

def test_changelog_immune(sandbox_pkg):
    (sandbox_pkg / "CHANGELOG.md").write_text(
        "曾引用 `scripts/ghost.py`（历史留档）。\n", encoding="utf-8")
    assert check_links(sandbox_pkg)["broken"] == []


def test_skill_changelog_immune(sandbox_pkg):
    (sandbox_pkg / "skills/SKILL_CHANGELOG.md").write_text(
        "`scripts/ghost.py` 历史条目。\n", encoding="utf-8")
    assert check_links(sandbox_pkg)["broken"] == []


def test_dated_report_immune(sandbox_pkg):
    (sandbox_pkg / "docs/2026-01-01/audit.md").write_text(
        "`scripts/ghost.py` 审计记录。\n", encoding="utf-8")
    assert check_links(sandbox_pkg)["broken"] == []


def test_erratum_line_exempt(sandbox_pkg):
    (sandbox_pkg / "agents/a.md").write_text(
        "勘误：此前引用了不存在的 `scripts/build_chapter.py`。\n", encoding="utf-8")
    assert check_links(sandbox_pkg)["broken"] == []


def test_placeholder_resolvable(sandbox_pkg):
    (sandbox_pkg / "references/profiles").mkdir(parents=True)
    (sandbox_pkg / "references/profiles/veterinary.md").write_text("# p\n", encoding="utf-8")
    assert _placeholder_resolvable(sandbox_pkg, "references/profiles/{discipline}.md")
    assert not _placeholder_resolvable(sandbox_pkg, "references/profiles/{ghost}.py")


def test_placeholder_unresolvable_dir_caught(sandbox_pkg):
    (sandbox_pkg / "agents/a.md").write_text(
        "配置 `references/profiles/{discipline}.md`。\n", encoding="utf-8")
    r = check_links(sandbox_pkg)
    assert len(r["broken"]) == 1 and "占位符" in r["broken"][0].get("note", "")


# ── 边界 ──────────────────────────────────────────────────

def test_citation_label_not_a_link(sandbox_pkg):
    """[实](PMID: …) 是引用标签语法，不是 md 链接——不得误报。"""
    (sandbox_pkg / "agents/a.md").write_text(
        "数据支持[实](PMID: 33148165)；结论[引](DOI: 10.1000/xyz)。\n", encoding="utf-8")
    r = check_links(sandbox_pkg)
    assert r["broken"] == []
    # 计数不应把标签当链接核验数（两条标签均被过滤）
    assert r["total"] == 0


def test_external_links_skipped(sandbox_pkg):
    (sandbox_pkg / "agents/a.md").write_text(
        "[pubmed](https://pubmed.ncbi.nlm.nih.gov/1/) 与 [节](#anchor)。\n",
        encoding="utf-8")
    r = check_links(sandbox_pkg)
    assert r["broken"] == [] and r["total"] == 0


def test_real_package_zero_broken():
    """真包当前态必须零断链（防回潮主断言）。"""
    r = check_links(PKG_ROOT)
    assert r["broken"] == [], f"真包断链: {r['broken']}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
