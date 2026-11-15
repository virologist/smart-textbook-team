#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_common.py — scripts/ 公共工具 SSOT（B4/B5，2026-11-16）

统一此前三份逐字相同的 `log()`（build_manuscript / assemble_sections /
merge_sections）——它们是同一个「统一日志通道」的三次手写副本，输出格式
完全一致 `[LEVEL] msg → stderr`。抽取为共享模块后，三处改为 import，
避免将来改格式时三处漂移。

注意：本模块刻意保持零依赖（仅 stdlib）、零学科常量词，以通过
check_domain_neutral 的通用层扫描。
"""
from __future__ import annotations

import sys


def log(msg: str, level: str = "INFO") -> None:
    """统一日志输出：所有诊断/进度信息走 stderr，格式 `[LEVEL] msg`。

    B5（2026-11-16）：此前 stderr/stdout 混用（部分错误打到 stdout），
    CI/运维无法按级别过滤。公共通道统一为 stderr。
    """
    print(f"[{level}] {msg}", file=sys.stderr)


__all__ = ["log"]
