"""渲染层单测：位图打包约定、抖动、文本、GS 光栅化。"""

import io
from pathlib import Path

import pytest
from PIL import Image

from paperang_p1 import LINE_BYTES, LINE_DOTS
from paperang_p1.render import (
    load_image, prepare, rows_from_image, selftest_image, text_image,
)


def test_rows_packing_convention():
    """1=黑、MSB 在前：全黑图打包后每字节 0xFF。"""
    img = Image.new("L", (LINE_DOTS, 4), 0)  # 全黑
    rows = rows_from_image(prepare(img, dither="threshold"))
    assert len(rows) == LINE_BYTES * 4
    assert rows == b"\xff" * len(rows)

    img_white = Image.new("L", (LINE_DOTS, 4), 255)
    rows_w = rows_from_image(prepare(img_white, dither="threshold"))
    assert rows_w == b"\x00" * len(rows_w)


def test_load_image_accepts_encoded_bytes():
    image = Image.new('L', (384, 8), 0)
    data = io.BytesIO()
    image.save(data, 'PNG')
    loaded = load_image(data.getvalue())
    assert loaded.size == image.size and loaded.getpixel((0, 0)) == 0


def test_half_black_column():
    """左半黑右半白：每行前 24 字节 FF、后 24 字节 00。"""
    img = Image.new("L", (LINE_DOTS, 2), 255)
    for y in range(2):
        for x in range(LINE_DOTS // 2):
            img.putpixel((x, y), 0)
    rows = rows_from_image(prepare(img, dither="threshold"))
    assert rows[:24] == b"\xff" * 24
    assert rows[24:48] == b"\x00" * 24


def test_resize_to_384():
    img = Image.new("L", (768, 100), 128)
    p = prepare(img, dither="threshold")
    assert p.width == LINE_DOTS
    assert p.height == 50


def test_invert():
    img = Image.new("L", (LINE_DOTS, 2), 0)
    rows = rows_from_image(prepare(img, dither="threshold", invert=True))
    assert rows == b"\x00" * len(rows)


def test_text_image_cjk():
    img = text_image("你好喵喵机\nPaperang P1 测试", font_size=24)
    assert img.width == LINE_DOTS
    assert img.height > 50
    # 黑字白底：应有黑像素
    hist = img.histogram()
    assert hist[0] > 0 and hist[255] > 0


def test_selftest_image():
    img = selftest_image()
    assert img.width == LINE_DOTS
    hist = img.histogram()
    assert hist[0] > 0 and hist[255] > 0


def test_dither_floyd_steinberg_produces_both():
    img = Image.new("L", (LINE_DOTS, 40), 128)  # 纯灰：抖动应产生黑白混合
    p = prepare(img, dither="floyd-steinberg")
    hist = p.convert("L").histogram()
    assert hist[0] > 0 and hist[255] > 0


_GS = None
try:
    from paperang_p1.config import Config, find_ghostscript
    _GS = find_ghostscript(Config())
except Exception:
    pass


@pytest.mark.skipif(not _GS, reason="Ghostscript 未安装")
def test_rasterize_ps():
    from paperang_p1.render import rasterize_document
    ps = b"%!PS\n72 72 moveto /Helvetica findfont 24 scalefont setfont (Hello P1) show showpage\n"
    pages = rasterize_document(ps, _GS)
    assert len(pages) == 1
    assert pages[0].width > 0
