"""Original abstract point studies for the mixed portrait/shape visual map."""
from functools import lru_cache
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFilter


@lru_cache(maxsize=5)
def points(kind):
    if kind=='heart':
        a,b=np.meshgrid(np.linspace(0,math.tau,180,endpoint=False),np.linspace(0,math.pi,32))
        x=16*np.sin(a)**3*np.sin(b)
        y=-(13*np.cos(a)-5*np.cos(2*a)-2*np.cos(3*a)-np.cos(4*a))*np.sin(b)
        z=5*np.cos(b)
        return np.stack([x.ravel(),y.ravel(),z.ravel()],axis=1)/18
    if kind=='code':
        segments=[((-1,-.65),(-1.65,0)),((-1.65,0),(-1,.65)),((1,-.65),(1.65,0)),((1.65,0),(1,.65)),((.35,-.9),(-.35,.9))]
        clouds=[]
        for start,end in segments:
            a=np.array(start); b=np.array(end); v=b-a; normal=np.array([-v[1],v[0]])/np.linalg.norm(v)
            for u in np.linspace(0,1,95):
                for angle in np.linspace(0,math.tau,14,endpoint=False):
                    xy=a+u*v+.065*math.cos(angle)*normal
                    clouds.append([*xy,.065*math.sin(angle)])
        return np.array(clouds)
    u,v=np.meshgrid(np.linspace(0,math.tau,230,endpoint=False),
                    np.linspace(0,math.tau,24,endpoint=False))
    if kind=='trefoil':
        # Restore the original knot's exact mathematical surface.
        radius=2+np.cos(3*u)+.27*np.cos(v)
        x=radius*np.cos(2*u);y=radius*np.sin(2*u);z=np.sin(3*u)+.27*np.sin(v)
        return np.stack([x.ravel(),y.ravel(),z.ravel()],axis=1)/3.2
    if kind=='orbit':
        radius=1+.34*np.cos(v)
        x=radius*np.cos(u);y=radius*np.sin(u);z=.34*np.sin(v)
    elif kind=='wave':
        radius=1+.22*np.cos(5*u)+.13*np.cos(v)
        x=radius*np.cos(u);y=radius*np.sin(u)
        z=.35*np.sin(5*u)+.20*np.sin(v)
    else:
        raise ValueError(kind)
    return np.stack([x.ravel(),y.ravel(),z.ravel()],axis=1)/1.4


def render_shape(t,size=(543,310),kind='trefoil'):
    width,height=map(int,size)
    ay=float(t);az=.31;ax=.54
    if kind in ('heart','code'):
        ay=.48*math.sin(t);az=.06*math.sin(t);ax=.12*math.cos(t)
    ry=np.array([[math.cos(ay),0,math.sin(ay)],[0,1,0],[-math.sin(ay),0,math.cos(ay)]])
    rz=np.array([[math.cos(az),-math.sin(az),0],[math.sin(az),math.cos(az),0],[0,0,1]])
    rx=np.array([[1,0,0],[0,math.cos(ax),-math.sin(ax)],[0,math.sin(ax),math.cos(ax)]])
    p=points(kind)@rz.T@rx.T@ry.T
    perspective=3.8/(3.8-p[:,2]);xy=p[:,:2]*perspective[:,None]
    # Keep every rotating form comfortably inside the existing map window.
    extent=np.max(np.abs(xy),axis=0)
    scale=min((width-30)/(2*extent[0]),(height-28)/(2*extent[1]))*.94
    xy=xy*scale+np.array([width/2,height/2])
    im=Image.new('RGBA',(width,height))
    glow=Image.new('RGBA',im.size);d=ImageDraw.Draw(glow)
    r=min(width,height)*.33
    d.ellipse((width/2-r,height/2-r,width/2+r,height/2+r),fill=(177,98,148,23))
    im.alpha_composite(glow.filter(ImageFilter.GaussianBlur(20)))
    d=ImageDraw.Draw(im)
    for n in np.argsort(p[:,2]):
        x,y=xy[n];depth=float(np.clip((p[n,2]+1.1)/2.2,0,1))
        c=(int(139+116*depth),int(91+121*depth),int(134+99*depth),int(95+160*depth))
        r=.66+depth*.62
        d.ellipse((x-r,y-r,x+r,y+r),fill=c)
    return im
