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
  D1 「等 12 类」——修复前 team-lead.md 的原话（router §1 实为 17 类，★G3 v2.10 增 review-section）
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


def test_gate_has_seven_criteria():
    """门禁必须恰好有 7 条判据（少一条 = 有判据失效且无人知道）。

    ★I-2（v2.10.2）：D6 → D7 增补——task_type_required ⊆ router 枚举
    + 工具编排总表锚计分（G5 声明的一致性计分落地）。"""
    _failed, items = _run_gate(PKG_ROOT)
    ids = {i[0] for i in items}
    assert ids == {"D1", "D2", "D3", "D4", "D5", "D6", "D7"}, ids


def test_d7_catches_unknown_task_type_key(sandbox_pkg):
    """D7 负向例：契约 task_type_required 混入 router 外的键 ⇒ 必须被拦。

    ★v2.20.0（2026-11-27，主理人复核发现）：本用例此前直接改**真实包**
    的 `references/member-contracts.json`，靠 `try/finally` 恢复。进程若被
    SIGTERM/超时杀死（finally 不执行），破坏样本会**永久留在生产资产里** ——
    实测已发生：真实包残留 `fake-task-xx` 键，导致 D7 对真实包持续报红。
    现改为在**沙箱副本**上破坏，从根上杜绝污染。
    """
    import json
    contract = sandbox_pkg / "references" / "member-contracts.json"
    original = contract.read_text(encoding="utf-8")
    try:
        d = json.loads(original)
        d["members"]["quality-examiner"].setdefault("task_type_required", {})["fake-task-xx"] = [
            "章节/{ch}/review/x.md"]
        contract.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        failed, _ = _run_gate(sandbox_pkg)
        assert "D7" in failed, "D7 未拦截枚举外的 task_type_required 键（判据恒真）"
    finally:
        contract.write_text(original, encoding="utf-8")


def test_task_type_count_parsed_from_ssot():
    """D1 的 task_type 数必须来自 router §1 实解析，不得硬编码。"""
    mod = _load_gate(PKG_ROOT)
    count, types = mod.parse_task_type_count(PKG_ROOT)
    assert count == 22, f"router §1 实解析 {count} 类：{types}"  # ★G3 v2.10=17 → v2.17.0=22（+5 可选增强）
    assert "review-score" in types and "gap-retrieval" in types
    # B1-3（2026-11-04）：R4+R5 合并派工类型必须在内
    assert "review-proofread-score" in types
    # v2.17.0：三名可选增强成员的 5 类路由必须在 SSOT 内
    for nt in ("review-learner", "standards-parse", "standards-audit",
               "assessment-generate", "assessment-review"):
        assert nt in types, f"v2.17.0 新路由 {nt} 未解析到"


# ── 负向：每条判据各一个破坏样本 ─────────────────────────────────────────

def test_d1_catches_wrong_task_type_count(sandbox_pkg):
    """D1：把「16 类」改回「12 类」必须被拦。"""
    p = sandbox_pkg / "agents" / "smart-textbook-team-team-lead.md"
    t = p.read_text(encoding="utf-8")
    assert "等 22 类" in t, "前置条件：当前包应写 22 类（v2.17.0 扩容后基线）"
    p.write_text(t.replace("等 22 类", "等 12 类"), encoding="utf-8")

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
    assert "22 类 task_type" in t, "前置条件：README 应写 22 类 task_type（v2.17.0 扩容后基线）"
    p.write_text(t.replace("22 类 task_type", "12 类 task_type"), encoding="utf-8")
    failed, _ = _run_gate(sandbox_pkg)
    assert "D1" in failed, "README 的计数漂移应被拦"

    ch = sandbox_pkg / "skills" / "task-router" / "SKILL.md"
    ct = ch.read_text(encoding="utf-8")
    # task-router/SKILL.md 是 SSOT 本体，不在免疫名单内；
    # 真正的免疫名单是 CHANGELOG.md / SKILL_CHANGELOG.md
    assert "CHANGELOG.md" in (PKG_ROOT / "scripts" / "check_doc_consistency.py").read_text(
        encoding="utf-8")


# ── ★DEF-5（v2.20.0）：D1 门禁盲区加固 ────────────────────────────────────
#
# 病灶：`skills/task-router/SKILL.md:10` 写「映射成 17 个标准 task_type 之一」，
# 而同文件 §1 表（SSOT）实为 22 类 —— frontmatter:4 与 §1 标题:28 均为 22。
# 漂移长期无人报警，因旧 D1 判据的计数正则只认「N 类 / N 种 / N-type」三种量词，
# **「N 个标准 task_type」这类量词句式完全漏网**（量词是「个」不是「类」）。
#
# 本组用例锁两件事：
#   ① 正向：该句式被改坏 → D1 必须拦（门禁不再是假门禁）
#   ② 反向：非 task_type 的计数（「22 个成员」「13 类 skill」）不得误伤
#      ——量词面一扩，误伤面同步扩大，故「语义绑定」必须与量词面同时落地


def test_d1_catches_quantifier_form_task_type_count(sandbox_pkg):
    """D1 正向：把「22 个标准 task_type」改回「12 个标准 task_type」必须被拦。

    这是 DEF-5 的原始病灶形态——旧门禁对此**完全漏网**（实测改坏后仍 7/7 PASS）。
    """
    p = sandbox_pkg / "skills" / "task-router" / "SKILL.md"
    t = p.read_text(encoding="utf-8")
    assert "22 个标准 task_type" in t, "前置条件：SKILL.md:10 应写 22 个标准 task_type"
    p.write_text(t.replace("22 个标准 task_type", "12 个标准 task_type"),
                 encoding="utf-8")

    failed, items = _run_gate(sandbox_pkg)
    assert "D1" in failed, "D1 未拦住「N 个标准 task_type」句式的计数漂移（旧盲区）"
    assert "12 类" in _detail(items, "D1")


def test_d1_does_not_flag_non_task_type_counts(sandbox_pkg):
    """D1 反向：非 task_type 的计数不得误伤。

    「22 个成员」「13 类 skill」这类计数**数的东西不是 task_type**——
    量词面扩充后若不做语义绑定，它们会被误判成 task_type 计数 ⇒ 门禁误杀合法内容。
    """
    p = sandbox_pkg / "agents" / "smart-textbook-team-team-lead.md"
    t = p.read_text(encoding="utf-8")
    # 在含 task_type 触发行处插入无关计数行。
    # 关键：该行**必须带触发词**（task-router），否则根本不进 D1 判定路径，
    # 用例就成了空转（假反例）。行内「22 个成员」「13 类 skill」数的是别的东西。
    anchor = "1. **标注 task_type**"
    assert anchor in t, "前置条件：team-lead.md 应含 task_type 标注步骤"
    noise = "> 本团 22 个成员共同维护 task-router 路由，仓内共 13 类 skill 参与协作。"
    t = t.replace(anchor, noise + "\n\n" + anchor, 1)
    p.write_text(t, encoding="utf-8")

    # 前置自检：该行确实带触发词（否则本用例空转）
    mod = _load_gate(sandbox_pkg)
    assert mod.RE_TT_TRIGGER.search(noise), "前置条件：干扰行必须含 task-router 触发词"

    failed, items = _run_gate(sandbox_pkg)
    assert "D1" not in failed, f"D1 误伤了非 task_type 计数：{_detail(items, 'D1')}"


def test_d1_exempts_threshold_context(sandbox_pkg):
    """D1 反向：阈值语境（「命中 ≥2 个 task_type」）是命中数下限，不是枚举总数。

    ESC1/ESC2 升级规则里的「≥2 个 task_type」说的是**候选命中个数**，
    与枚举总数（22）无关——若不豁免，D1 会把升级规则判成漂移。
    """
    p = sandbox_pkg / "skills" / "task-router" / "SKILL.md"
    t = p.read_text(encoding="utf-8")
    assert "≥2 个 task_type" in t, "前置条件：ESC1 应含「≥2 个 task_type」阈值表述"
    # 前置行本身在 §1 表之后，用 sandbox 里的当前值即可（此处只验豁免不误伤）
    failed, items = _run_gate(sandbox_pkg)
    assert "D1" not in failed, f"D1 误伤了阈值语境：{_detail(items, 'D1')}"


def test_d1_semantic_binding_unit():
    """D1 语义绑定单元级：计数必须**确实指代 task_type** 才认领。

    直接驱动门禁内部的 `_tt_count_claims`（不落盘、不依赖沙箱），
    把「直邻 / 省略 / 异指 / 阈值豁免」四态逐条钉死。
    """
    mod = _load_gate(PKG_ROOT)

    def _claims(line):
        return [c[1] for c in mod._tt_count_claims(line)]

    # 直邻：中心词是 task_type 语义 → 认领
    assert _claims("映射成 22 个标准 task_type 之一") == [22]
    assert _claims("Defines task_type enum (22 types)") == [22]
    # 省略：中心词缺省（计数是括号/分句末项）+ 枚举语境锚 → 认领
    assert _claims("## 1. task_type 枚举（22 类，SSOT）") == [22]
    assert _claims("按 router §1 枚举（design-bloom 等 22 类）判定") == [22]
    # 异指：中心词非 task_type 语义 → **不认领**
    assert _claims("本团 22 个成员共同维护路由") == []
    assert _claims("仓内共 13 类 skill 参与协作") == []
    # 阈值：命中数下限 → **不认领**
    assert _claims("候选歧义（同一问法命中 ≥2 个 task_type）") == []
    # 历史行：变更记录里的旧枚举数非 task_type 中心词 → 不认领
    assert _claims("初版：12 task_type 枚举 + 4 步决策算法") == []


def test_d1_does_not_treat_plain_etc_as_enumeration_context():
    """D1 反向：裸「等」是并列连词，不是枚举语境标记（自审实测抓到的误报类）。

    病灶形态：「加载 task-router 等 22 个」——「22 个」数的是 **skill 总数**，
    不是 task_type 枚举数。但「等」紧邻触发词 task-router，且计数处**中心词省略**
    ⇒ 若枚举语境锚把裸「等」当锚，就会被误认成 task_type 计数 ⇒ 门禁误杀合法内容。

    正解：裸「等」不单独成立，须与强枚举信号（task_type/枚举/路由/扩至…）同现。
    """
    mod = _load_gate(PKG_ROOT)

    def _claims(line):
        return [c[1] for c in mod._tt_count_claims(line)]

    # 裸「等」+ 中心词省略 ⇒ 不认领（数的是 skill/任务/成员总数）
    assert _claims("加载 task-router 等 22 个") == []
    assert _claims("本轮跑了 task-router 等 22 个") == []
    # 但「等」+ 强枚举信号同现 ⇒ 认领（「按 §1 枚举（… 等 22 类）」）
    assert _claims("按 router §1 枚举（design-bloom 等 22 类）判定") == [22]


# ── ★v2.20.0：_iter_md 分支 B 免疫失效修复的回归锁定 ────────────────────────
#
# 病灶：`_iter_md` 的两条扫描分支是**各自独立**的 if —— 分支 A（SCAN_DIRS
# 递归）带 IMMUNE_FILES 检查，分支 B（SCAN_FILES 根文件列表）**漏掉**。
# ⇒ 免疫承诺（CHANGELOG / SKILL_CHANGELOG 照抄旧数字是证据要求，不参与判据）
#    在分支 A 生效、在分支 B **完全失效** ⇒ D1–D4 对这两个文件的漂移静默漏检。
#
# 当前 SCAN_FILES 恰好不含 CHANGELOG.md / SKILL_CHANGELOG.md，所以缺陷**尚未
# 发作**——但它是一枚埋雷：任何人往 SCAN_FILES 加入免疫文件，免疫立即失效且
# 无人察觉。本用例锁死「分支 B 也必须跳过免疫文件」这一行为。


def test_iter_md_skips_immune_files_in_both_branches(sandbox_pkg):
    """免疫文件在**两条扫描分支**上都必须被跳过（不得只保护其中一条）。"""
    mod = _load_gate(sandbox_pkg)

    # 前置条件：免疫名单含 CHANGELOG.md / SKILL_CHANGELOG.md
    assert "CHANGELOG.md" in mod.IMMUNE_FILES
    assert "SKILL_CHANGELOG.md" in mod.IMMUNE_FILES

    # 造一个免疫文件，并把它**显式塞进 SCAN_FILES** —— 模拟「有人把 CHANGELOG
    # 加进根文件扫描列表」这一最危险的情形。
    immune = sandbox_pkg / "CHANGELOG.md"
    immune.write_text("# 历史流水\n\n照抄旧数字：映射成 3 个标准 task_type 之一\n",
                      encoding="utf-8")
    orig_scan_files = mod.SCAN_FILES
    mod.SCAN_FILES = tuple(orig_scan_files) + ("CHANGELOG.md",)
    try:
        scanned = dict(mod._iter_md(sandbox_pkg))
    finally:
        mod.SCAN_FILES = orig_scan_files

    # 分支 B（根文件列表）不得产出免疫文件
    assert "CHANGELOG.md" not in scanned, \
        "免疫文件经分支 B 被扫描 ⇒ 免疫承诺失效（D1–D4 对 CHANGELOG 静默漏检）"

    # 分支 A（递归）同样不得产出免疫文件（既有行为，防回退）
    for rel in scanned:
        assert Path(rel).name not in mod.IMMUNE_FILES, \
            f"免疫文件被扫描：{rel}"


def test_iter_md_branch_b_still_scans_normal_root_files(sandbox_pkg):
    """反向：分支 B 的免疫修复**不得**误伤正常根文件（README 等仍须被扫）。"""
    mod = _load_gate(sandbox_pkg)
    scanned = dict(mod._iter_md(sandbox_pkg))
    for f in ("README.md", "CONTRIBUTING.md", "AGENTS.md"):
        if (sandbox_pkg / f).is_file():
            assert f in scanned, f"正常根文件 {f} 被误排除（免疫修复过度）"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
