"""Rose workspace cycling through a full portrait and abstract point studies."""
from pathlib import Path
import math
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from portrait_map import render_portrait
from shape_maps import render_shape

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / 'assets'
FONTS = ROOT / '.profile-build/fonts'
CREAM = '#fff7f2'
PLUM = '#342031'
ROSE = '#b7668a'
FRAMES = 184
SCENES=[(0,40,'portrait'),(40,72,'trefoil'),(72,100,'orbit'),(100,128,'wave'),(128,156,'heart'),(156,184,'code')]


def font(size, kind='sans'):
    files = {'sans':'DM-Sans-normal-400-0.ttf', 'medium':'DM-Sans-normal-500-1.ttf',
             'bold':'DM-Sans-normal-700-2.ttf', 'serif':'Fraunces-normal-500-4.ttf',
             'italic':'Fraunces-italic-500-3.ttf'}
    if kind == 'mono':
        return ImageFont.truetype('/System/Library/Fonts/Menlo.ttc', size)
    return ImageFont.truetype(str(FONTS/files[kind]), size)


def label(im, xy, text, size=22, kind='sans', fill=CREAM):
    ImageDraw.Draw(im).text(xy, text, font=font(size,kind), fill=fill, anchor='lt')


def rule(im, xy, fill='#674258'):
    ImageDraw.Draw(im).line(xy, fill=fill, width=1)


def panel(im, box, fill, outline):
    ImageDraw.Draw(im).rounded_rectangle(box, radius=17, fill=fill, outline=outline, width=2)


def prepare(mobile=False):
    size = (760,880) if mobile else (1600,600)
    w,h = size
    im = Image.new('RGBA',size,'#251723')
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((12,12,w-13,h-13),radius=27,fill='#2d1b2a',outline='#865c77',width=2)
    d.rounded_rectangle((16,16,w-17,h-17),radius=24,outline='#3d2738',width=1)
    bar = 83 if mobile else 78
    rule(im,(14,bar,w-15,bar),'#674258')
    for x,color in [(46,'#e594b1'),(72,'#f4d4b0'),(98,'#b9abc8')]:
        d.ellipse((x-7,44-7,x+7,44+7), fill=color)
    label(im,(139,35) if mobile else (146,33),'~/yana/creative-workspace',17 if mobile else 20,'mono','#d5b8ca')
    if not mobile:
        label(im,(1330,35),'PH / UTC+08',17,'mono','#af8fa7')

    if mobile:
        panel(im,(38,108,722,330),CREAM,'#edc5d6')
        label(im,(64,134),'DESIGN / DEVELOPMENT / CURIOSITY',17,'mono',ROSE)
        label(im,(61,177),'Juliana Caedo.',75,'serif',PLUM)
        label(im,(66,281),'@yana16-afk',22,'mono','#88617b')
        panel(im,(38,352,399,768),'#302033','#66485e')
        panel(im,(418,352,722,768),'#382535','#66485e')
        label(im,(60,374),'creative.map',17,'mono','#e9bfd5')
        label(im,(442,374),'profile.info',17,'mono','#e9bfd5')
        for y,key,value in [(447,'based in','Manila, PH'),
                            (559,'focus','UI/UX + full stack'),(671,'background','Computer Science')]:
            label(im,(443,y),key,15,'mono','#b391ab')
            label(im,(443,y+27),value,21,'medium',CREAM)
        label(im,(60,731),'VISUAL MAP / CYCLE',12,'mono','#a68aa7')
        rule(im,(41,798,719,798))
        label(im,(64,823),'design with curiosity. build with care.',24,'italic','#ecc7dc')
    else:
        panel(im,(42,104,655,553),'#302033','#66485e')
        panel(im,(677,104,1558,553),CREAM,'#edc5d6')
        label(im,(66,127),'creative.map',18,'mono','#e9bfd5')
        label(im,(456,129),'VISUAL / CYCLE',13,'mono','#a68aa7')
        label(im,(712,128),'DESIGN / DEVELOPMENT / CURIOSITY',18,'mono',ROSE)
        label(im,(707,171),'Juliana Caedo.',83,'serif',PLUM)
        label(im,(713,270),'@yana16-afk',21,'mono','#88617b')
        rule(im,(713,311,1520,311),'#e6cbd7')
        rows=[('based in','Manila, Philippines'),
              ('focus','UI/UX · Frontend · Full stack'),('background','B.S. Computer Science')]
        for i,(key,value) in enumerate(rows):
            y=345+i*48
            label(im,(714,y),key,19,'mono','#a0738e')
            label(im,(929,y),value,22,'medium',PLUM)
        rule(im,(713,493,1520,493),'#e6cbd7')
        label(im,(715,514),'design with curiosity. build with care.',23,'italic','#976081')
        label(im,(66,518),'form + identity',16,'mono','#c09bb7')
        label(im,(441,519),'CODE / POINT MAP',13,'mono','#a68aa7')
    return im


def frame(base,t,mobile=False):
    im=base.copy()
    # The same visual-map window holds the complete portrait and varied shapes.
    # GitHub plays this as a looping GIF; no page JavaScript is required.
    box=(68,424,369,704) if mobile else (76,181,619,491)
    x0,y0,x1,y1=box
    size=(x1-x0,y1-y0)
    position=(t%math.tau)/math.tau*FRAMES
    index=next((i for i,(start,end,kind) in enumerate(SCENES) if start<=position<end),0)
    start,end,kind=SCENES[index]
    progress=(position-start)/(end-start)
    def visual(mode,phase):
        return render_portrait(phase,size=size) if mode=='portrait' else render_shape(phase,size=size,kind=mode)
    tile=visual(kind,progress*math.tau)
    # A short dissolve makes every mode transition, including the loop, smooth.
    fade_start=end-6
    if position>=fade_start:
        alpha=min(1.,max(0.,(position-fade_start)/5))
        alpha=alpha*alpha*(3-2*alpha)
        next_kind=SCENES[(index+1)%len(SCENES)][2]
        tile=Image.blend(tile,visual(next_kind,0),alpha)
    im.alpha_composite(tile,(x0,y0))
    d=ImageDraw.Draw(im)
    if mobile:
        corners=[(62,419,1,1),(375,419,-1,1),(62,708,1,-1),(375,708,-1,-1)]
    else:
        corners=[(67,176,1,1),(628,176,-1,1),(67,491,1,-1),(628,491,-1,-1)]
    for x,y,sx,sy in corners:
        d.line((x+sx*15,y,x,y,x,y+sy*15),fill='#87536f',width=1)
    return im.convert('RGB')


def render(mobile=False):
    stem='workspace-header-mobile' if mobile else 'workspace-header'
    base=prepare(mobile);still=frame(base,0,mobile)
    still.save(ASSETS/(stem+'.png'),optimize=True)
    size=(608,704) if mobile else (1200,450)
    # Include portrait and shape colors in one stable palette.
    samples=Image.new('RGB',(size[0]*4,size[1]))
    for j,phase in enumerate((0,44,78,108)):
        sample=frame(base,phase*math.tau/FRAMES,mobile).resize(size,Image.Resampling.LANCZOS)
        samples.paste(sample,(j*size[0],0))
    palette=samples.quantize(colors=256,method=Image.Quantize.MAXCOVERAGE,dither=Image.Dither.NONE)
    frames=[]
    for n in range(FRAMES):
        rgb=frame(base,n*math.tau/FRAMES,mobile).resize(size,Image.Resampling.LANCZOS)
        frames.append(rgb.quantize(palette=palette,dither=Image.Dither.NONE))
    frames[0].save(ASSETS/(stem+'.gif'),save_all=True,append_images=frames[1:],
                   duration=[120,130]*(FRAMES//2),loop=0,optimize=True,disposal=1)
    print(stem,still.size,(ASSETS/(stem+'.gif')).stat().st_size,flush=True)


if __name__=='__main__':
    render(False)
    render(True)
