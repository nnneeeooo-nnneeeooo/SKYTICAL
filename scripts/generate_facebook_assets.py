"""Rebuild the navy Facebook PNGs from original assets (requires Pillow and NumPy)."""
from pathlib import Path
from PIL import Image, ImageDraw
import numpy as np

ASSETS = Path(__file__).resolve().parents[1] / 'static'
OUT = ASSETS
SOURCE = ASSETS
OUT.mkdir(parents=True, exist_ok=True)

def background(w, h, cover=False):
    y, x = np.mgrid[0:h, 0:w]
    t = y / h
    # Restrained ink blue; a broad, faint warm band replaces photographic light.
    top = np.array([9., 22., 39.])
    bottom = np.array([27., 48., 65.])
    rgb = top + (bottom-top)*t[..., None]
    warmth = np.exp(-((t-.91)/.17)**2) * 0.10
    rgb = rgb*(1-warmth[..., None])+np.array([138., 103., 70.])*warmth[..., None]
    im = Image.fromarray(np.uint8(np.clip(rgb, 0, 255)), 'RGB').convert('RGBA')
    if cover:
        scale = 3
        layer = Image.new('RGBA', (w*scale,h*scale))
        d = ImageDraw.Draw(layer)
        # Quiet off-canvas navigation arcs, leaving the brand area clear.
        for r in (300, 400, 500, 600):
            cx, cy = w+70, h+160
            d.ellipse(((cx-r)*scale,(cy-r)*scale,(cx+r)*scale,(cy+r)*scale), outline=(139,165,187,22), width=2)
        # A single gently rising route, offset from the lettering.
        points=[]
        for px in range(1080,w+1):
            py=562-0.00030*(px-1080)**2
            points.append((px*scale,py*scale))
        d.line(points, fill=(181,159,121,58), width=3)
        for px in (1190,1490):
            py=562-0.00030*(px-1080)**2
            d.ellipse(((px-3)*scale,(py-3)*scale,(px+3)*scale,(py+3)*scale),fill=(192,167,123,115))
        im = Image.alpha_composite(im, layer.resize((w,h), Image.Resampling.LANCZOS))
    return im

def original_foreground(im, cover):
    a=np.asarray(im.convert('RGB')).astype(float)
    h,w=a.shape[:2]
    chroma=a.max(axis=2)-a.min(axis=2)
    yy,xx=np.mgrid[0:h,0:w]
    logo=(chroma>8)
    if cover:
        logo &= (xx<570)&(yy>100)&(yy<350)
    # Recover colored foreground edges against the original light gray matte.
    matte=np.array([243.,242.,242.])
    solid=logo & (chroma>145)
    nearest=a.copy()
    known=solid.copy()
    for _ in range(8):
        for axis,step in ((0,1),(0,-1),(1,1),(1,-1)):
            adjacent=np.roll(known,step,axis=axis)
            take=(~known)&adjacent
            nearest[take]=np.roll(nearest,step,axis=axis)[take]
            known |= take
    delta=matte-nearest
    alpha=np.clip(np.sum((matte-a)*delta,axis=2)/np.maximum(np.sum(delta*delta,axis=2),1),0,1)*logo
    color=np.clip((a-matte*(1-alpha[...,None]))/np.maximum(alpha[...,None],.001),0,255)
    if cover:
        yy,xx=np.mgrid[0:h,0:w]
        text_region=((xx>570)&(yy<350))|((yy>460)&(yy<520))
        fg=np.where((yy<280)[...,None], np.array([72.,81.,92.]),np.array([117.,128.,140.]))
        ta=np.clip(np.mean((matte-a)/(matte-fg),axis=2),0,1)*text_region*(~logo)
        replacement=np.where((yy<280)[...,None],np.array([239.,242.,245.]),np.array([165.,181.,195.]))
        color=np.where((ta>0)[...,None],replacement,color)
        alpha=np.maximum(alpha,ta)
    return Image.fromarray(np.uint8(np.dstack([color,alpha*255])), 'RGBA')

for kind,name,cover in [('avatar','SKYTICAL-Facebook-avatar-1024.png',False),('cover','SKYTICAL-Facebook-cover-1640x624.png',True)]:
    src=Image.open(SOURCE/name)
    final=Image.alpha_composite(background(*src.size,cover),original_foreground(src,cover)).convert('RGB')
    dest=OUT/f'SKYTICAL-Facebook-{kind}-navy.png'
    final.save(dest)
    print(f'{dest}: {final.size}')
