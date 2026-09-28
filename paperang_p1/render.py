"""渲染：图像/文本 → P1 可打印的 1-bit 行字节流（384 点/48 字节每行，1=黑）。"""

from __future__ import annotations

import io
import logging
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from . import DPI, LINE_DOTS

log = logging.getLogger(__name__)

_DITHERS = ("floyd-steinberg", "atkinson", "threshold")

_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyh.ttc",      # 微软雅黑
    r"C:\Windows\Fonts\simhei.ttf",    # 黑体
    r"C:\Windows\Fonts\simsun.ttc",    # 宋体
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def find_font(cfg_path: str | None = None, size: int = 24) -> ImageFont.FreeTypeFont:
    for p in (cfg_path, *_FONT_CANDIDATES):
        if p and Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def load_image(src: str | Path | bytes) -> Image.Image:
    img = Image.open(io.BytesIO(src) if isinstance(src, bytes) else src)
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass
    return img


def prepare(img: Image.Image, width: int = LINE_DOTS, dither: str = "floyd-steinberg",
            threshold: int = 128, invert: bool = False) -> Image.Image:
    """缩放到指定宽度、灰度化、抖动成 1-bit（黑=0 白=255 的 PIL 约定）。

    invert=True 用于暗底截图等场景（白字打黑底），在灰度阶段就翻转。
    """
    if img.mode in ("RGBA", "LA", "PA"):
        # 透明像素按白纸处理
        base = Image.new("L", img.size, 255)
        base.paste(img.convert("L"), mask=img.convert("LA").split()[-1])
        img = base
    else:
        img = img.convert("L")
    if invert:
        from PIL import ImageChops
        img = ImageChops.invert(img)
    if img.width != width:
        h = max(1, round(img.height * width / img.width))
        img = img.resize((width, h), Image.LANCZOS)

    if dither == "threshold":
        out = img.point(lambda p: 255 if p >= threshold else 0).convert("1")
    elif dither == "atkinson":
        out = _atkinson(img).convert("1")
    else:
        out = img.convert("1", dither=Image.Dither.FLOYDSTEINBERG)
    return out


def rows_from_image(img1: Image.Image) -> bytes:
    """1-bit 图 → 行字节流。PIL '1' 模式 1=白、MSB 在前；协议要求 1=黑，故取反。"""
    if img1.width != LINE_DOTS:
        raise ValueError(f"图像宽度应为 {LINE_DOTS}，实际 {img1.width}")
    from PIL import ImageChops
    inverted = ImageChops.invert(img1.convert("L")).convert("1")
    return inverted.tobytes()


def _atkinson(img: Image.Image) -> Image.Image:
    """Atkinson 抖动（纯 Python，较慢；追求速度用 floyd-steinberg）。"""
    w, h = img.size
    px = img.load()
    for y in range(h):
        for x in range(w):
            old = px[x, y]
            new = 255 if old >= 128 else 0
            err = old - new
            px[x, y] = new
            for dx, dy in ((1, 0), (2, 0), (-1, 1), (0, 1), (1, 1), (0, 2)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h:
                    px[nx, ny] = max(0, min(255, px[nx, ny] + err // 8))
    return img


def text_image(text: str, font_path: str | None = None, font_size: int = 24,
               padding: int = 8) -> Image.Image:
    """多行文本 → 灰度图（自动换行到 384px 宽）。"""
    font = find_font(font_path, font_size)
    width = LINE_DOTS
    dummy = Image.new("L", (10, 10))
    draw = ImageDraw.Draw(dummy)

    def line_width(s: str) -> int:
        b = draw.textbbox((0, 0), s, font=font)
        return b[2] - b[0]

    # 逐字贪心换行（CJK 无空格）
    lines: list[str] = []
    for raw in text.splitlines() or [""]:
        cur = ""
        for ch in raw:
            if line_width(cur + ch) > width - 2 * padding and cur:
                lines.append(cur)
                cur = ch
            else:
                cur += ch
        lines.append(cur)

    asc, desc = font.getmetrics()
    line_h = asc + desc + 2
    height = 2 * padding + line_h * len(lines)
    img = Image.new("L", (width, max(height, 1)), 255)
    d = ImageDraw.Draw(img)
    y = padding
    for ln in lines:
        d.text((padding, y), ln, font=font, fill=0)
        y += line_h
    return img


def selftest_image() -> Image.Image:
    """自检图：标题 + 渐变 + 网格 + 纯黑块，用于验证浓度与限速参数。"""
    w = LINE_DOTS
    img = Image.new("L", (w, 560), 255)
    d = ImageDraw.Draw(img)
    font = find_font(size=28)
    d.text((8, 6), "Paperang P1 Selftest", font=font, fill=0)
    d.text((8, 40), "1234567890 ABCabc 喵喵机", font=find_font(size=22), fill=0)
    for x in range(w):                     # 渐变条
        g = round(x * 255 / (w - 1))
        d.point((x, 84), fill=g)
        d.point((x, 85), fill=g)
    for blk in range(8):                   # 8 级灰阶
        g0 = round(255 * blk / 7)
        d.rectangle((blk * w // 8, 96, (blk + 1) * w // 8 - 1, 140), fill=g0)
    step = 16                              # 棋盘格
    for y in range(156, 284, step):
        for x in range(0, w, step):
            if ((x // step) + (y // step)) % 2 == 0:
                d.rectangle((x, y, min(x + step, w) - 1, y + step - 1), fill=0)
    d.rectangle((0, 300, w - 1, 400), fill=0)   # 纯黑块：验证缓冲/限速
    d.rectangle((0, 416, w // 2 - 1, 476), fill=0)  # 半宽黑块
    d.text((8, 500), "If all blocks print fine, pacing is OK.", font=find_font(size=18), fill=0)
    return img


def rasterize_document(src: bytes | Path, gs_path: str, dpi: int = DPI,
                       quiet: bool = True) -> list[Image.Image]:
    """PostScript/PDF → 每页一张灰度图（Ghostscript pnggray）。"""
    with tempfile.TemporaryDirectory(prefix="paperang-gs-") as td:
        tdir = Path(td)
        ext = ".ps"
        if isinstance(src, (str, Path)):
            ext = Path(src).suffix.lower() or ".ps"
            data = Path(src).read_bytes()
        else:
            # PS 流以 %! 开头，PDF 以 %PDF 开头
            ext = ".pdf" if src[:5] == b"%PDF-" else ".ps"
            data = bytes(src)
        infile = tdir / f"in{ext}"
        infile.write_bytes(data)
        outpat = str(tdir / "page-%d.png")
        cmd = [
            gs_path, "-dSAFER", "-dBATCH", "-dNOPAUSE",
            *(["-dQUIET"] if quiet else []),
            "-sDEVICE=pnggray", f"-r{dpi}", f"-sOutputFile={outpat}", str(infile),
        ]
        proc = subprocess.run(cmd, capture_output=True, timeout=180)
        if proc.returncode != 0:
            raise RuntimeError(
                f"Ghostscript 失败({proc.returncode}): {proc.stderr.decode('utf-8', 'replace')[-800:]}")
        pages = sorted(tdir.glob("page-*.png"))
        if not pages:
            raise RuntimeError("Ghostscript 未产出任何页面")
        return [Image.open(p).convert("L") for p in pages]
