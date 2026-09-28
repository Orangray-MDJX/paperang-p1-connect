"""A 384-dot physical ruler test; --submit is an explicit real print."""
import argparse
import base64
import io
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from PIL import Image, ImageDraw
from paperang_p1.render import find_font


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--submit', action='store_true')
    args = parser.parse_args()
    image = Image.new('L', (384, 610), 255)
    draw = ImageDraw.Draw(image)
    font = find_font(None, 20)
    draw.text((8, 8), 'P1 打印区域校准', font=font, fill=0)
    draw.text((8, 32), '顶部黑条：384 dots', font=font, fill=0)
    draw.rectangle((0, 62, 383, 66), fill=0)
    draw.line((42, 125, 342, 125), fill=0, width=1)
    for x in (42, 342): draw.line((x, 115, x, 135), fill=0, width=1)
    draw.text((76, 88), '横向两刻线：300 dots', font=font, fill=0)
    draw.line((42, 160, 42, 560), fill=0, width=1)
    for y in (160, 260, 360, 460, 560):
        draw.line((32, y, 52, y), fill=0, width=1)
    draw.text((70, 173), '左侧上下：400 dots', font=font, fill=0)
    draw.text((70, 205), '小格：50 x 50 dots', font=font, fill=0)
    for offset in range(0, 201, 50):
        draw.line((100+offset, 260, 100+offset, 460), fill=0)
        draw.line((100, 260+offset, 300, 260+offset), fill=0)
    draw.text((70, 495), '请测刻线中心距离', font=font, fill=0)
    draw.text((8, 575), '纸宽57mm / 有效点宽384', font=font, fill=0)
    output = Path(__file__).resolve().parents[1] / 'calibration.png'
    image.save(output)
    print(output)
    if args.submit:
        buf = io.BytesIO(); image.save(buf, format='PNG')
        with httpx.Client(base_url='http://127.0.0.1:8765',trust_env=False,timeout=30) as client:
            response = client.post('/api/print/image',json={'b64':base64.b64encode(buf.getvalue()).decode('ascii'),'dither':'threshold'})
            print(response.raise_for_status().json())


if __name__ == '__main__': main()
