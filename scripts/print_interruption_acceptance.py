"""Submit a numbered strip only after the operator is ready to interrupt it."""
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
    parser.add_argument('--transport', choices=('usb', 'spp'), default='usb')
    args = parser.parse_args()
    if not args.submit:
        parser.error('Operator must be ready; explicitly pass --submit.')
    with httpx.Client(base_url='http://127.0.0.1:8765', trust_env=False, timeout=30) as client:
        status = client.get('/api/status').raise_for_status().json()
        if not status['connected'] or status['transport'] != args.transport or status['queue']['printing'] or status['queue']['pending']:
            raise RuntimeError('Require the selected transport ready and an idle queue.')
        image = Image.new('L', (384, 2400), 255)
        draw = ImageDraw.Draw(image)
        font = find_font(None, 24)
        for index, y in enumerate(range(8, 2350, 100), 1):
            draw.text((8, y), f'中断测试 {index:02d} - 不自动重打', font=font, fill=0)
            draw.rectangle((8, y + 38, 375, y + 43), fill=0)
        encoded = io.BytesIO()
        image.save(encoded, format='PNG')
        response = client.post('/api/print/image', json={'b64': base64.b64encode(encoded.getvalue()).decode('ascii'), 'dither': 'threshold'})
        print(response.raise_for_status().json())


if __name__ == '__main__':
    main()
