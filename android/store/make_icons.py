# Draws the app icon (turf green, three rising bars, gold trend line) and Play store art.
import os, sys
from PIL import Image, ImageDraw, ImageFont
R = sys.argv[1]
GREEN, DARK, WHITE, GOLD = (31,107,58), (15,21,17), (255,255,255), (227,172,74)
def icon(n=1024):
    S = 4*n; im = Image.new('RGB', (S,S), GREEN); d = ImageDraw.Draw(im)
    # subtle yard lines
    for i in range(1,5):
        y = int(S*i/5); d.line([(0,y),(S,y)], fill=(38,120,67), width=S//160)
    # content kept inside the central 60% so Android's round/squircle masks never clip it
    x0, base, bw, gap = S*0.25, S*0.73, S*0.13, S*0.055
    hs = [0.18, 0.30, 0.44]
    tops = []
    for i,h in enumerate(hs):
        x = x0 + i*(bw+gap); top = base - S*h
        d.rounded_rectangle([x, top, x+bw, base], radius=S*0.025, fill=WHITE)
        tops.append((x+bw/2, top - S*0.07))
    d.line(tops, fill=GOLD, width=int(S*0.035), joint='curve')
    for (cx,cy) in tops:
        r = S*0.035; d.ellipse([cx-r,cy-r,cx+r,cy+r], fill=GOLD)
    return im.resize((n,n), Image.LANCZOS)
big = icon(1024)
os.makedirs(f'{R}/board/site/icons', exist_ok=True); os.makedirs(f'{R}/android/store', exist_ok=True)
for n, name in [(192,'icon-192.png'),(512,'icon-512.png'),(180,'apple-touch-icon.png'),(32,'favicon-32.png')]:
    big.resize((n,n), Image.LANCZOS).save(f'{R}/board/site/icons/{name}', optimize=True)
big.resize((512,512), Image.LANCZOS).save(f'{R}/android/store/play-icon-512.png', optimize=True)
# Play feature graphic 1024x500
fg = Image.new('RGB', (1024,500), DARK); m = Image.new('L',(300,300),0); ImageDraw.Draw(m).rounded_rectangle([0,0,299,299], radius=60, fill=255); fg.paste(big.resize((300,300), Image.LANCZOS), (80,100), m)
d = ImageDraw.Draw(fg)
def font(sz):
    for p in ['/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf','/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf']:
        if os.path.exists(p): return ImageFont.truetype(p, sz)
    return ImageFont.load_default()
d.text((430,170), 'Props Board', font=font(76), fill=WHITE)
d.text((432,275), 'NFL  ·  NBA  ·  NHL  ·  Bank Builder', font=font(25), fill=GOLD)
fg.save(f'{R}/android/store/feature-graphic-1024x500.png', optimize=True)
print('ok')
