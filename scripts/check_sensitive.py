#!/usr/bin/env python3
"""敏感信息扫描：提交前自查与 CI 双用的守门工具。

用法：
    python scripts/check_sensitive.py              # 扫描 git 已跟踪文件（或整个目录）
    python scripts/check_sensitive.py --staged     # 只扫描已暂存文件（pre-commit 用）
    python scripts/check_sensitive.py <路径>...    # 扫描指定文件/目录

命中任何模式退出码为 1。占位符（文档示例 IP 段、示例 MAC）在白名单内放行。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _doc_range_ips(prefix: str) -> set[str]:
    """文档示例段全部地址（含 .0/.255 网络与广播地址写法）。"""
    return {f"{prefix}.{i}" for i in range(0, 256)}

# (模式名, 正则, 白名单——命中白名单的匹配不算问题)
PATTERNS = [
    ("设备序列号", re.compile(r"P100H\d{6,}"), set()),
    ("蓝牙/网络 MAC", re.compile(
        r"(?i)\b([0-9a-f]{2}:){5}[0-9a-f]{2}\b"),
     {"AA:BB:CC:DD:EE:FF", "00:11:22:33:44:55"}),
    ("内网 IP", re.compile(
        r"\b(?:10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d{1,3}\.\d{1,3}\b"),
     # 192.168.0.x / 192.168.1.x 为文档示例段（含 .0/.255 网络与广播地址写法）
     _doc_range_ips("192.168.0") | _doc_range_ips("192.168.1")),
    ("个人用户名/邮箱", re.compile(r"(?i)orangray"), set()),
    ("个人绝对路径", re.compile(
        r"(?i)\b[a-z]:[\\/](?:users|git)[\\/]"), set()),
    ("本地逆向素材引用", re.compile(r"\.refs\b"), set()),
]

SKIP_DIRS = {".git", ".venv", ".refs", "vendor", "__pycache__", "bin", "obj",
             ".zcode", ".pytest_cache", "node_modules", ".githooks"}

# 本身就需要出现这些关键词的治理文件（排除规则文本、合规说明）
FILE_SKIP = {".gitignore", "docs/OPEN-SOURCE-CHECKLIST.md"}

# 版权署名是有意公开的作者身份，扫描前先替换掉
AUTHOR_MARK = re.compile(r"(?i)orangray-mdjx")


def iter_files(paths: list[str] | None, staged: bool):
    if staged:
        out = subprocess.run(["git", "diff", "--cached", "--name-only"],
                             cwd=REPO, capture_output=True, text=True, check=True).stdout
        for line in out.splitlines():
            p = REPO / line
            if p.is_file():
                yield p
        return
    if paths:
        for arg in paths:
            p = Path(arg)
            if p.is_file():
                yield p.resolve()
            elif p.is_dir():
                yield from walk(p.resolve())
        return
    # 默认：git 已跟踪文件；不在 git 仓库时退回目录遍历
    try:
        out = subprocess.run(["git", "ls-files"], cwd=REPO,
                             capture_output=True, text=True, check=True).stdout
        for line in out.splitlines():
            p = REPO / line
            if p.is_file():
                yield p
    except subprocess.CalledProcessError:
        yield from walk(REPO)


def walk(root: Path):
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        yield p


def scan_file(path: Path) -> list[str]:
    if path.name == "check_sensitive.py":
        return []  # 模式定义自身含关键字，跳过本文件
    try:
        rel = path.relative_to(REPO).as_posix()
    except ValueError:
        rel = path.as_posix()
    if rel in FILE_SKIP:
        return []
    try:
        data = path.read_bytes()
    except OSError:
        return []
    if b"\x00" in data[:8192]:  # 二进制文件跳过
        return []
    text = AUTHOR_MARK.sub("<author>", data.decode("utf-8", errors="ignore"))
    findings = []
    for name, pattern, allow in PATTERNS:
        for m in pattern.finditer(text):
            if m.group(0) not in allow:
                line = text.count("\n", 0, m.start()) + 1
                findings.append(f"{path.relative_to(REPO)}:{line} [{name}] {m.group(0)}")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="要扫描的文件/目录（默认已跟踪文件）")
    parser.add_argument("--staged", action="store_true", help="只扫描 git 暂存文件")
    args = parser.parse_args()

    all_findings: list[str] = []
    for f in iter_files(args.paths or None, args.staged):
        all_findings.extend(scan_file(f))

    if all_findings:
        print("发现疑似敏感信息，禁止提交/发布：", file=sys.stderr)
        for f in all_findings:
            print(f"  {f}", file=sys.stderr)
        print("处理方式：真实地址/标识改为占位符（文档示例段 192.168.1.x、"
              "MAC AA:BB:CC:DD:EE:FF），或把文件加入 .gitignore 后 git rm --cached。",
              file=sys.stderr)
        return 1
    print("敏感信息扫描通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
