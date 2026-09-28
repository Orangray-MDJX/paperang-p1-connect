"""Bounded Apple Raster (UNIRAST) W8 decoder, per libcups raster-stream.c."""
import io
import struct
from PIL import Image
from .pwg_raster import MAX_PIXELS


def decode(data):
    stream = io.BytesIO(data)
    def read(n):
        value = stream.read(n)
        if len(value) != n: raise ValueError('URF data truncated')
        return value
    if read(8) != b'UNIRAST\0': raise ValueError('Invalid Apple Raster signature')
    count = struct.unpack('>I',read(4))[0]
    pages = []; pixels = 0
    while stream.tell() < len(data):
        header = read(32)
        width,height,dpi = struct.unpack_from('>III',header,12)
        pixels += width * height
        if header[0] != 8 or header[1] not in (0,4):
            raise ValueError('Only W8 grayscale Apple Raster is supported')
        if not width or not height or width > 10000 or pixels > MAX_PIXELS or not dpi:
            raise ValueError('Invalid or oversized Apple Raster dimensions')
        raw = bytearray(); row = 0
        while row < height:
            repeat = read(1)[0]+1
            line = bytearray()
            while len(line) < width:
                control = read(1)[0]
                if control == 128:
                    line.extend(b'\xff'*(width-len(line))); break
                if control < 128: line.extend(read(1)*(control+1))
                else: line.extend(read(257-control))
                if len(line)>width: raise ValueError('URF run exceeds row')
            if row+repeat>height: raise ValueError('URF row repeat exceeds page')
            raw.extend(line*repeat); row += repeat
        pages.append(Image.frombytes('L',(width,height),bytes(raw)))
    if not pages or count not in (0,0xffffffff,len(pages)):
        raise ValueError('URF page count mismatch')
    return pages
