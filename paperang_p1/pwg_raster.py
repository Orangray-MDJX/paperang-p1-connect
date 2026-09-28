"""PWG Raster v2 decoder (RaS2, big endian, chunked 1/8-bit monochrome)."""
import io
import struct
from PIL import Image, ImageOps

MAX_PIXELS = 20_000_000


def decode(data: bytes) -> list[Image.Image]:
    src = io.BytesIO(data)
    if src.read(4) != b'RaS2': raise ValueError('需要 PWG Raster v2 (RaS2)')

    def read(n):
        b = src.read(n)
        if len(b) != n: raise ValueError('PWG Raster 数据截断')
        return b

    pages = []; pixels = 0
    while src.tell() < len(data):
        h = read(1796)
        field = lambda off: struct.unpack_from('>I', h, off)[0]
        width, height = field(372), field(376)
        bpc, bpp, stride = field(384), field(388), field(392)
        order, space, colors = field(396), field(400), field(420)
        pixels += width * height
        if not width or not height or width > 10000 or pixels > MAX_PIXELS:
            raise ValueError('PWG Raster 尺寸过大或无效')
        if order != 0 or colors != 1 or space not in (0, 3, 18) or bpc not in (1, 8) or bpp != bpc:
            raise ValueError('仅支持 black/sgray 单色 1 或 8 位 PWG Raster')
        minimum = (width * bpp + 7) // 8
        if not minimum <= stride <= minimum + 64:
            raise ValueError('PWG Raster 行长无效')
        raw = bytearray(); row = 0
        # For 1/8-bit single-channel pixels the compression unit is one byte.
        while row < height:
            repeat = read(1)[0] + 1
            line = bytearray()
            while len(line) < stride:
                control = read(1)[0]
                if control == 128:
                    # CUPS/PWG end-of-line fills with the colorspace's white.
                    white = 0 if space == 3 else 255
                    line.extend(bytes([white]) * (stride - len(line)))
                    break
                if control < 128:
                    line.extend(read(1) * (control + 1))
                else:
                    line.extend(read(257 - control))
                if len(line) > stride: raise ValueError('PWG Raster 游程越过行尾')
            if row + repeat > height: raise ValueError('PWG Raster 重复行越过页尾')
            raw.extend(line * repeat); row += repeat
        mode = '1' if bpp == 1 else 'L'
        image = Image.frombytes(mode, (width, height), bytes(raw), 'raw', mode, stride).convert('L')
        if space == 3: image = ImageOps.invert(image)  # K: 0=white; W/SW: 0=black
        pages.append(image)
    if not pages: raise ValueError('PWG Raster 没有页面')
    return pages
