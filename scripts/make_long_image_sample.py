"""Generate a numbered 384x2400 original image; never submit a print."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageDraw
from paperang_p1.render import find_font
image=Image.new('L',(384,2400),255);draw=ImageDraw.Draw(image)
font=find_font(None,24)
draw.text((8,10),'START / 长图原图验证',font=font,fill=0)
draw.line((0,52,383,52),fill=0,width=3)
for n in range(1,13):
    y=90+(n-1)*185
    draw.text((8,y),f'{n:02d} / 共12段 / 1234567890',font=font,fill=0)
    draw.line((0,y+45,383,y+45),fill=0,width=2)
    for x in range(0,384,48):draw.rectangle((x,y+65,x+15,y+90),fill=0)
draw.text((8,2330),'END / 末尾应完整出现一次',font=font,fill=0)
draw.line((0,2380,383,2380),fill=0,width=3)
output=Path(__file__).resolve().parents[1]/'paperang_p1/static/long-image-sample.png'
image.save(output);print(output)
