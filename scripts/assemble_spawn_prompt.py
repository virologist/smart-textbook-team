#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
兼容 shim（v3.4.2 P0-1 分发修复，2026-10-15；原 v3.4.1 R9 shared-core 下沉）
==============================================================================
本包的实现已下沉至联邦共享件：my-experts/plugins/shared-core/assemble_spawn_prompt.py
（4 个无差异包共用同一份真源，消除 378 行 x 4 的拷贝漂移）。
本文件保留入口兼容——sop-stages.md / 各成员 MD 均引用 scripts/assemble_spawn_prompt.py。

解析顺序（两级，先联邦后兜底）：
  1. 联邦真源：从「专家包根的父目录」起逐级向上找 shared-core/assemble_spawn_prompt.py
     （最多 4 层）。安装态路径 .../marketplaces/my-experts/plugins/<pkg> 的父目录即为
     plugins/，命中联邦 core —— 真源优先，运行时不产生漂移。
  2. vendor 兜底：<pkg>/vendor/shared-core/assemble_spawn_prompt.py。
     仅在联邦 core 缺失时启用（git clone 后直跑 / CI / 离线开发态），
     保证 `git clone → python3 scripts/assemble_spawn_prompt.py --list-members` 开箱可用。
  3. 两者皆无 → exit 3（保留原诊断信息）。

防漂移：
  tests/test_vendor_core.py 在安装态（联邦 core 存在）比对 vendor 副本 sha256，
  不一致即 FAIL 并提示 sync 命令；联邦缺失时自动 SKIP（git/CI 场景不误报）。

调试：
  SHIM_DEBUG=1 python3 scripts/assemble_spawn_prompt.py --list-members
  → stderr 打印解析到的 core 路径与来源（federal / vendor）。

环境变量：
  EXPERT_DIR  显式指定专家包根（core 内优先级：--expert-dir > EXPERT_DIR > 位置反推）
  SHIM_DEBUG  打印 core 解析来源
"""

import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(_HERE)                                  # 调用方专家包根
_CORE_NAME = "assemble_spawn_prompt.py"
_MAX_UP = 4                                                    # 向上查找最大层数

# 联邦 core 相对「某目录」的路径；vendor 兜底路径
_FEDERAL_REL = os.path.join("shared-core", _CORE_NAME)
_VENDOR_REL = os.path.join("vendor", "shared-core", _CORE_NAME)


def _find_federal() -> str | None:
    """联邦真源：从专家包根的【父目录】起逐级向上找（不含包内自身）。

    不写死层数——安装态路径随 marketplace 嵌套深度变化
    （.../marketplaces/my-experts/plugins/<pkg>）。
    从父目录起步是关键：若包含 _PKG 自身，安装态会把包内任何 shared-core/
    误判为真源，反而制造第二份副本。
    """
    d = os.path.dirname(_PKG)
    for _ in range(_MAX_UP):
        cand = os.path.join(d, _FEDERAL_REL)
        if os.path.isfile(cand):
            return cand
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None


def _find_vendor() -> str | None:
    """vendor 兜底副本：包内 vendor/shared-core/。"""
    cand = os.path.join(_PKG, _VENDOR_REL)
    return cand if os.path.isfile(cand) else None


_FEDERAL = _find_federal()
_VENDOR = _find_vendor()
_CORE = _FEDERAL or _VENDOR
_SOURCE = "federal" if _FEDERAL else ("vendor" if _VENDOR else None)


def _debug(msg: str) -> None:
    if os.environ.get("SHIM_DEBUG"):
        sys.stderr.write(f"[assemble_spawn_prompt shim] {msg}\n")


if _CORE is None:
    sys.stderr.write(
        "[assemble_spawn_prompt shim] shared-core 缺失（自 %s 向上 %d 层未找到联邦件，"
        "且包内无 vendor 兜底）\n"
        "  本包实现已下沉至联邦共享件。请确认安装态 .../plugins/shared-core/ 存在；\n"
        "  若在 git 仓库结构中运行，请确认 vendor/shared-core/ 已随仓库分发，\n"
        "  或从 vet-med-ppt-team 仓库的 shared-core/ 取回。\n" % (_PKG, _MAX_UP))
    sys.exit(3)

_debug(f"core = {_CORE}（来源: {_SOURCE}）")

# 专家包根显式传给 core（core 内优先级：--expert-dir > EXPERT_DIR > 位置反推）
os.environ.setdefault("EXPERT_DIR", _PKG)

_spec = importlib.util.spec_from_file_location("_shared_core_assemble_spawn_prompt", _CORE)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

# ── 包私有增量：--skip-skill-preload 降级档（ADR-05 / harness §3.1，B6 M3）────
# 联邦 core 保持无差异（维护纪律：包私有需求走各包增量，不回染 core）。
# 预算 ≥80% tokens_limit 时编排者加此 flag：spawn 文案注入降级指令，
# 成员仅强制加载安全底线 skill（agent-harness-protocol / citation-verify），
# 其余预加载按需、失败不阻塞——「降至线内」的可执行削减动作。
# 削减须由编排者写入黑板 budget.cuts（M3 反查锚：本段即 flag 的实现行）。
_SKIP_PRELOAD_NOTE = (
    "\n## 预算降级档：--skip-skill-preload（ADR-05 / harness §3.1）\n"
    "预算已达 tokens_limit 的 80%，本次 spawn **跳过非关键 skill 预加载**：\n"
    "仅强制加载 `agent-harness-protocol` 与 `citation-verify`（安全底线），\n"
    "「额外预加载 skills」其余项按需加载、失败不阻塞主路径。\n"
    "编排者已将本削减记入黑板 budget.cuts 并须在交付质量报告声明。\n"
)


def _main_with_skip_preload() -> int:
    """捕获 core 输出并在头部注入降级指令（flag 的行为实现体）。"""
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = _mod.main()
    sys.stdout.write(_SKIP_PRELOAD_NOTE + buf.getvalue())
    return rc


if __name__ == "__main__":
    if "--skip-skill-preload" in sys.argv:
        sys.argv.remove("--skip-skill-preload")
        sys.exit(_main_with_skip_preload())
    sys.exit(_mod.main())
