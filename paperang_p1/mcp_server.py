# -*- coding: utf-8 -*-
"""MCP 服务（stdio）：让 AI 客户端（ZCode/Claude 等）以工具方式调用打印。

依赖常驻服务的 HTTP API（默认 http://127.0.0.1:8765）。
在 MCP 客户端配置中注册::

    {
      "mcpServers": {
        "paperang": {
          "command": "<venv>\\\\Scripts\\\\python.exe",
          "args": ["-m", "paperang_p1.mcp_server"],
          "env": {"PAPERANG_API": "http://127.0.0.1:8765"}
        }
      }
    }
"""

from __future__ import annotations

import base64
import json
import os

import httpx
from fastmcp import FastMCP
from .config import Config

API = os.environ.get("PAPERANG_API", f"http://127.0.0.1:{Config.load().api_port}")

mcp = FastMCP("paperang")


def _get(path: str, **params):
    r = httpx.get(f"{API}{path}", params=params, timeout=60, trust_env=False)
    r.raise_for_status()
    return r.json()


def _post(path: str, payload: dict | None = None):
    r = httpx.post(f"{API}{path}", json=payload or {}, timeout=120, trust_env=False)
    r.raise_for_status()
    return r.json()


@mcp.tool
def paperang_status() -> str:
    """查询喵喵机打印机状态（连接通道/电量/队列）。"""
    return json.dumps(_get("/api/status"), ensure_ascii=False)


@mcp.tool
def paperang_scan(timeout: float = 6.0) -> str:
    """扫描附近的 Paperang 蓝牙设备。"""
    return json.dumps(_get("/api/scan", timeout=timeout), ensure_ascii=False)


@mcp.tool
def paperang_connect(transport: str = "auto") -> str:
    """连接打印机。transport: auto | vendor | spp | usb | ble。"""
    return json.dumps(_post("/api/connect", {"transport": transport}),
                      ensure_ascii=False)


@mcp.tool
def paperang_print_text(text: str, font_size: int | None = None,
                        density: int | None = None) -> str:
    """打印文本（支持中文多行，\\n 换行）。"""
    return json.dumps(_post("/api/print/text", {
        "text": text, "font_size": font_size, "density": density}),
        ensure_ascii=False)


@mcp.tool
def paperang_print_image(path: str | None = None, b64: str | None = None,
                         density: int | None = None,
                         dither: str | None = None,
                         invert: bool = False) -> str:
    """打印图片：给本地路径 path 或 base64 内容 b64。"""
    if not path and not b64:
        return "错误: 需要 path 或 b64 参数"
    return json.dumps(_post("/api/print/image", {
        "path": path, "b64": b64, "density": density,
        "dither": dither, "invert": invert}), ensure_ascii=False)


@mcp.tool
def paperang_print_file(path: str, density: int | None = None) -> str:
    """打印本地文件（PDF/PS/PNG/JPG）。"""
    return json.dumps(_post("/api/print/file", {
        "path": path, "density": density}), ensure_ascii=False)


@mcp.tool
def paperang_selftest() -> str:
    """打印自检页（渐变/棋盘/黑块，用于检验打印质量）。"""
    return json.dumps(_post("/api/selftest"), ensure_ascii=False)


@mcp.tool
def paperang_config_get() -> str:
    """读取服务配置。"""
    return json.dumps(_get("/api/config"), ensure_ascii=False)


@mcp.tool
def paperang_config_set(items: dict) -> str:
    """修改服务配置，如 {"density": 80, "dither": "threshold"}。"""
    r = httpx.put(f"{API}/api/config", json=items, timeout=30, trust_env=False)
    r.raise_for_status()
    return json.dumps(r.json(), ensure_ascii=False)


@mcp.tool
def paperang_jobs() -> str:
    """列出持久化任务及其状态（unknown 不会自动重打）。"""
    return json.dumps(_get('/api/jobs'), ensure_ascii=False)


@mcp.tool
def paperang_job_status(job_id: int) -> str:
    """查询指定任务的状态与页数。"""
    return json.dumps(_get(f'/api/jobs/{job_id}'), ensure_ascii=False)


@mcp.tool
def paperang_cancel_job(job_id: int) -> str:
    """取消尚未开始的任务，正在打印的任务在页边界停止。"""
    return json.dumps(_post(f'/api/jobs/{job_id}/cancel'), ensure_ascii=False)


@mcp.tool
def paperang_resume_job(job_id: int) -> str:
    """设备唤醒后恢复 held 任务；禁止恢复 unknown 任务。"""
    return json.dumps(_post(f'/api/jobs/{job_id}/resume'), ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
