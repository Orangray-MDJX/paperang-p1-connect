"""Regenerate the Windows icon from the geometry in static/logo.svg."""
from pathlib import Path

from PIL import Image, ImageDraw


def build():
    scale = 4
    image = Image.new('RGBA', (64 * scale, 64 * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    s = lambda points: [(round(x * scale), round(y * scale)) for x, y in points]
    ink, accent = '#252a33', '#df805f'
    draw.polygon(s([(15, 15), (18, 4), (28, 12), (36, 12), (46, 4),
                    (49, 15), (55, 23), (55, 42), (51, 51), (44, 53),
                    (20, 53), (11, 50), (7, 40), (7, 24)]), fill=ink)
    draw.rounded_rectangle((7*scale, 12*scale, 55*scale, 53*scale),
                           radius=11*scale, fill=ink)
    for x in (24.5, 39.5):
        draw.ellipse(((x-2.5)*scale, 23*scale, (x+2.5)*scale, 28*scale), fill='white')
    draw.arc((26*scale, 28*scale, 38*scale, 38*scale), 8, 172,
             fill='white', width=2*scale)
    draw.rounded_rectangle((14*scale, 45*scale, 50*scale, 57*scale),
                           radius=3*scale, fill='white', outline=ink, width=2*scale)
    draw.line((20*scale, 51*scale, 44*scale, 51*scale), fill=accent, width=2*scale)
    target = Path(__file__).resolve().parents[1] / 'paperang_p1' / 'static' / 'app.ico'
    image.save(target, format='ICO', sizes=[(16,16),(24,24),(32,32),(48,48),
                                           (64,64),(128,128),(256,256)])


if __name__ == '__main__':
    build()
