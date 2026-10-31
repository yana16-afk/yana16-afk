"""A photograph sampled as a looping rose/lilac point-data portrait.

Source pixels provide every point's location, tone and contour. The source is
read-only. This is a shallow luminance-based parallax treatment, never a turn
of the face or an inferred reconstruction of unseen anatomy.

Public API: render_portrait(t, size=(560,310)) -> transparent RGBA Image.
Phase t is in radians; zero and 2*pi match. No assets are written on import.
"""
from functools import lru_cache
from pathlib import Path
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

SOURCE = Path('/Applications/personal/Job Search/hero photo Background Removed.png')
ROOT = Path(__file__).resolve().parent.parent
SUPERSAMPLE = 2


@lru_cache(maxsize=1)
def _source():
    # Preserve the entire supplied canvas. Never crop any source pixels.
    return Image.open(SOURCE).convert('RGBA')


@lru_cache(maxsize=8)
def _layout(size):
    width,height=size
    if min(size)<40:
        raise ValueError('Portrait tiles must be at least 40px in both dimensions.')
    source=_source()
    bounds=source.getchannel('A').getbbox()
    x0,y0,x1,y1=bounds
    padding=13
    # Fit all visible source content in BOTH dimensions. The full source is
    # resized intact; translation only removes unused transparent margins
    # from the returned tile, with no hair, body or clothing content lost.
    scale=min((width-2*padding)/(x1-x0),(height-2*padding)/(y1-y0))
    photo=source.resize((max(2,round(source.width*scale)),
                         max(2,round(source.height*scale))),Image.Resampling.LANCZOS)
    sx,sy=photo.width/source.width,photo.height/source.height
    visible_w,visible_h=(x1-x0)*sx,(y1-y0)*sy
    left=(width-visible_w)/2-x0*sx
    top=(height-visible_h)/2-y0*sy
    fit_bounds=((width-visible_w)/2,(height-visible_h)/2,
                (width+visible_w)/2,(height+visible_h)/2)
    return photo,(left,top),fit_bounds,bounds


def portrait_metadata(size=(560,310)):
    """Report full-source geometry for integration and no-crop verification."""
    photo,offset,fit_bounds,bounds=_layout(tuple(map(int,size)))
    return {'source_canvas':_source().size,'source_alpha_bounds':bounds,
            'source_crop':None,'resized_canvas':photo.size,'canvas_translation':offset,
            'tile_size':tuple(size),'visible_subject_bounds':fit_bounds,'padding':13}


@lru_cache(maxsize=8)
def _model(size):
    width,height = size
    photo,offset,fit_bounds,bounds=_layout(size)
    portrait_w,portrait_h=photo.size
    pix = np.asarray(photo).astype(np.float32)/255
    rgb,alpha = pix[...,:3],pix[...,3]
    lum = rgb@np.array([.2126,.7152,.0722])
    gy,gx = np.gradient(lum)
    edge = np.sqrt(gx*gx+gy*gy)
    # Constant grid coverage keeps cheeks and forehead visible, rather than
    # reducing the face to a few disembodied feature outlines.
    step = 2.55 if height>=300 else 2.45
    ys,xs = np.mgrid[1:portrait_h-1:step,1:portrait_w-1:step]
    xs,ys=xs.ravel(),ys.ravel()
    # Fixed subpixel jitter breaks the coherent lattice before the portrait
    # is reduced for GitHub. It prevents broad moire/checkerboard bands while
    # keeping density and source sampling deterministic across every frame.
    rng=np.random.default_rng(160716)
    xs=np.clip(xs+rng.uniform(-.67,.67,xs.shape),0,portrait_w-1)
    ys=np.clip(ys+rng.uniform(-.67,.67,ys.shape),0,portrait_h-1)
    xi,yi=np.rint(xs).astype(int),np.rint(ys).astype(int)
    keep=alpha[yi,xi]>.9
    xs,ys,xi,yi=xs[keep],ys[keep],xi[keep],yi[keep]
    # A second sparse layer adds detail at brows, eyes, lips and face contours.
    yy,xx=np.mgrid[step/2:portrait_h-1:step,step/2:portrait_w-1:step]
    xx,yy=xx.ravel(),yy.ravel()
    xx=np.clip(xx+rng.uniform(-.67,.67,xx.shape),0,portrait_w-1)
    yy=np.clip(yy+rng.uniform(-.67,.67,yy.shape),0,portrait_h-1)
    ax,ay=np.rint(xx).astype(int),np.rint(yy).astype(int)
    skin=(rgb[ay,ax,0]>rgb[ay,ax,2]*1.12)&(lum[ay,ax]>.24)
    # The photographed face is in the upper third of the full-body canvas.
    # Preserve extra sampling there without enlarging or cropping its shape.
    center=(xx>portrait_w*.3)&(xx<portrait_w*.78)&(yy<portrait_h*.52)&(yy>portrait_h*.14)
    feature=(edge[ay,ax]>.038)&center
    # Include skin detail as well as edges. Hair remains a lighter data field.
    dense=(alpha[ay,ax]>.9)&center&(feature|skin)
    xs=np.concatenate([xs,xx[dense]])
    ys=np.concatenate([ys,yy[dense]])
    xi=np.rint(xs).astype(int);yi=np.rint(ys).astype(int)
    value=np.clip((lum[yi,xi]-.025)/.87,0,1)**.85
    # Cream highlights and rose/lilac shadows encode the source luminance.
    low=np.array([116,79,111.])
    high=np.array([255,231,223.])
    colors=low[None,:]+value[:,None]*(high-low)[None,:]
    opacities=190+value*65
    positions=np.column_stack([xs+offset[0],ys+offset[1]])
    # A shallow depth field from existing image brightness, with subtle sway.
    visible_center=(fit_bounds[0]+fit_bounds[2])/2
    normalized_x=(positions[:,0]-visible_center)/((fit_bounds[2]-fit_bounds[0])/2)
    depth=np.maximum(0,1-normalized_x**2)*(.35+.65*value)
    y_norm=np.clip((positions[:,1]-fit_bounds[1])/(fit_bounds[3]-fit_bounds[1]),0,1)
    return positions,colors,opacities,depth,y_norm,value


def render_portrait(t,size=(560,310)):
    size=tuple(map(int,size))
    positions,colors,opacities,depth,y_norm,value=_model(size)
    t=float(t)
    # Periodic Gaussian scan: motion loops smoothly without hiding identity.
    cycle=t/math.tau
    distance=(y_norm-cycle+.5)%1-.5
    scan=np.exp(-.5*(distance/.065)**2)
    breathe=.97+.03*math.cos(t)
    brightness=breathe+scan*.16
    shaded=np.clip(colors*brightness[:,None],0,255).astype(np.uint8)
    alpha=np.clip(opacities*(.97+.03*math.cos(t)+scan*.045),0,255).astype(np.uint8)
    xs=positions[:,0]+math.sin(t)*depth*5.5
    ys=positions[:,1]+math.sin(t+.35)*depth*.85
    # Points move by less than one pixel within the scanning band; the facial
    # landmarks remain in their photographed relative positions at all times.
    xs+=np.sin(y_norm*31+t)*scan*.22
    canvas=Image.new('RGBA',(size[0]*SUPERSAMPLE,size[1]*SUPERSAMPLE))
    draw=ImageDraw.Draw(canvas)
    for x,y,color,a,v in zip(xs,ys,shaded,alpha,value):
        radius=(.59+.10*v)*SUPERSAMPLE
        x,y=x*SUPERSAMPLE,y*SUPERSAMPLE
        draw.ellipse((x-radius,y-radius,x+radius,y+radius),
                     fill=(int(color[0]),int(color[1]),int(color[2]),int(a)))
    # A rose scanner makes the data-map motion visible after GitHub scales
    # the header down. It remains translucent over the complete point face.
    # Its opacity eases to zero at both ends before returning to the top.
    progress=cycle%1
    scan_fade=math.sin(math.pi*progress)**2
    if scan_fade>1e-8:
        _,_,fit_bounds,_=_layout(size)
        left,top,right,bottom=fit_bounds
        line_y=top+progress*(bottom-top)
        s=SUPERSAMPLE
        glow=Image.new('RGBA',canvas.size)
        gd=ImageDraw.Draw(glow)
        gd.line(((left+3)*s,line_y*s,(right-3)*s,line_y*s),
                fill=(249,139,190,round(66*scan_fade)),width=5*s)
        canvas.alpha_composite(glow.filter(ImageFilter.GaussianBlur(3*s)))
        accent=Image.new('RGBA',canvas.size)
        ad=ImageDraw.Draw(accent)
        ad.line(((left+3)*s,line_y*s,(right-3)*s,line_y*s),
                fill=(255,169,207,round(112*scan_fade)),width=s)
        # Small outward corner brackets suggest a moving acquisition window.
        for x,direction in [(left-4,1),(right+4,-1)]:
            ad.line(((x+direction*6)*s,(line_y-7)*s,x*s,(line_y-7)*s,
                     x*s,(line_y+7)*s,(x+direction*6)*s,(line_y+7)*s),
                    fill=(255,180,214,round(194*scan_fade)),width=3)
        canvas.alpha_composite(accent)
    return canvas.resize(size,Image.Resampling.LANCZOS)


class PortraitMap:
    def __init__(self,size=(560,310)):
        self.size=tuple(size)

    def render(self,t):
        return render_portrait(t,self.size)

    __call__=render


if __name__=='__main__':
    build=ROOT/'.profile-build'
    for name,size in [('desktop',(560,310)),('mobile',(313,289))]:
        image=Image.new('RGBA',size,'#302133')
        image.alpha_composite(render_portrait(0,size))
        image.convert('RGB').save(build/('portrait-map-'+name+'.png'))
    sheet=Image.new('RGB',(1120,620),'#302133')
    for n,t in enumerate([0,math.pi/2,math.pi,math.pi*1.5]):
        tile=Image.new('RGBA',(560,310),'#302133')
        tile.alpha_composite(render_portrait(t))
        sheet.paste(tile.convert('RGB'),((n%2)*560,(n//2)*310))
    sheet.save(build/'portrait-map-phases.png')
    print('Portrait map module ready; desktop/mobile/phase QA saved.',flush=True)
