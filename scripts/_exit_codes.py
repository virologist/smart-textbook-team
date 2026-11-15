#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_exit_codes.py — 退出码语义 SSOT（B2，2026-11-16）

背景（11-15b B2）：退出码 2 在不同脚本承担两种语义——
  · 「输入错误/用法错误」：build_manuscript.py、metrics_baseline.py(EXIT_INPUT_ERROR)
  · 「检查失败」：check_test_prompts.py
而 1 又表「发现问题」；3 在 assemble_spawn_prompt.py 表「缺失 core」、
在 metrics_baseline.py 表「基线损坏」。

实证更正（2026-11-16）：报告称「stt.py 以 return 2 判定子命令失败，若子脚本
用 1 表失败会误判为成功」——**不成立**。stt.py 的 `_run()` 原样透传子进程
returncode，`_run_consistency` 用 `rc = rc or c` 对任何非零都判失败，
cmd_gate 的 `return 2` 仅用于「本 CLI 自身的参数错误」，不参与子命令判定。
故不存在「误判成功」的实际 bug。

本模块因此定位为**约定 SSOT + 自文档**：新脚本应 import 这些常量，
已有脚本保持现状（强行全仓替换会改变各脚本既有契约，属高风险行为变更）。
统一为单一命名常量是渐进收敛方向，不强制回溯。
"""
from __future__ import annotations

EXIT_OK = 0            # 成功（含带降级告警的成功）
EXIT_CHECK_FAIL = 1    # 检查/门禁发现问题（含严格模式下的 WARN）
EXIT_INPUT_ERROR = 2   # 输入/用法/参数错误
EXIT_PREREQUISITE = 3  # 前置条件不满足（缺失 core / 基线损坏 / 需恢复）

__all__ = ["EXIT_OK", "EXIT_CHECK_FAIL", "EXIT_INPUT_ERROR", "EXIT_PREREQUISITE"]
