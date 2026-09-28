"""真机浓度档位阶梯验证：各档一张标签图，检查设备 ACK 与任务记录。

每张图含档位文字 + 全宽黑条，便于纸面黑度对比。用法：
    python scripts/density_ladder.py [levels...]
"""
import argparse
import base64
import io
import sys
import time
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paperang_p1.render import find_font

API = 'http://127.0.0.1:8765/api'


def ladder_png(level: int) -> bytes:
    image = Image.new('L', (384, 110), 255)
    draw = ImageDraw.Draw(image)
    font = find_font(None, 26)
    draw.text((8, 8), f'浓度档 {level}/100', font=font, fill=0)
    draw.rectangle((0, 70, 383, 100), fill=0)
    buf = io.BytesIO(); image.save(buf, 'PNG')
    return buf.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('levels', type=int, nargs='+', default=[0, 25, 50, 75, 100])
    args = parser.parse_args()
    results = []
    with httpx.Client(base_url=API, trust_env=False, timeout=60) as client:
        status = client.get('/status').json()
        if not status.get('connected'):
            print(f'设备未连接: {status}'); return 2
        for level in args.levels:
            r = client.post('/print/image', json={
                'b64': base64.b64encode(ladder_png(level)).decode('ascii'),
                'dither': 'threshold', 'density': level})
            r.raise_for_status()
            jid = r.json()['job_id']
            state = None
            for _ in range(240):
                job = client.get(f'/jobs/{jid}').json()
                state = job['state']
                if state in ('completed', 'failed', 'unknown', 'held', 'cancelled'):
                    break
                time.sleep(.5)
            results.append((level, jid, state, job.get('error')))
            print(f'density={level:>3} job={jid} state={state} error={job.get("error")}')
    bad = [r for r in results if r[2] != 'completed']
    print('RESULT:', 'ALL-ACKED' if not bad else f'{len(bad)} NOT-COMPLETED')
    return 0 if not bad else 1


if __name__ == '__main__':
    raise SystemExit(main())
