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

# ── CLI 兜底（R-B4 2026-11-23 复测）──────────────────────────────────────
# 只读目录 / 依赖缺失是长期运行态最高频故障；此前这些场景抛裸 Python 栈，
# 违反「失败也要留痕 + 可读诊断」。装饰器统一兜底：OSError → 中文诊断 + 退出 2，
# ModuleNotFoundError → 提示重装 + 退出 3。按需包在 CLI 入口函数上，不全局 try。
def guard_cli(fn):
    """CLI 入口兜底装饰器：环境类异常转可读诊断，业务异常照常透出。"""
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ModuleNotFoundError as e:
            print(f"[ERROR] 包内模块缺失: {e.name}——安装态不完整，"
                  f"请重新安装或校验安装态（install_state_check.py）", file=sys.stderr)
            return 3
        except PermissionError as e:
            print(f"[ERROR] 无写权限（目录只读或属主不符）: {e.filename or e}——"
                  f"请检查 WORK_ROOT 权限后重试", file=sys.stderr)
            return 2
        except OSError as e:
            print(f"[ERROR] 系统级 I/O 错误: {e}——请检查磁盘/路径后重试",
                  file=sys.stderr)
            return 2
    return wrapper


__all__ = ["log", "guard_cli"]

