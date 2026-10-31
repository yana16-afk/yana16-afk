"""Approximate the actual README offline, including badges and disclosures.

This preview is a local rendering aid. GitHub remains the final rendering
reference; remote widgets are shown only from an explicit local preview map.
"""
from pathlib import Path
from html.parser import HTMLParser
import json
import re
import xml.etree.ElementTree as ET
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / '.profile-build'
FONTS = BUILD / 'fonts'
CACHE = BUILD / 'widget-cache'


def clean(parts):
    return '\n'.join(' '.join(part.split()) for part in ''.join(parts).split('\u2028')).strip()


class Blocks(HTMLParser):
    def __init__(self, mobile=False, expand_details=False):
        super().__init__(convert_charrefs=True)
        self.blocks = []
        self.kind = None
        self.parts = []
        self.source = None
        self.mobile = mobile
        self.expand_details = expand_details
        self.details = []
        self.cell = None
        self.row = []

    def visible(self):
        if not self.details:
            return True
        frame = self.details[-1]
        return frame['parent_visible'] and (frame['summary'] or frame['open'])

    def flush(self):
        if not self.kind:
            return
        kind, parts = self.kind, self.parts
        self.kind, self.parts = None, []
        if kind == 'summary':
            value = clean([p for p in parts if isinstance(p, str)])
            images = [p for p in parts if isinstance(p, dict)]
            if value or images:
                self.blocks.append(('summary', {
                    'text': value, 'images': images,
                    'expanded': self.details[-1]['open'] if self.details else self.expand_details,
                }))
            return
        # Images in a paragraph remain a consecutive inline group. This lets
        # badges wrap at their native SVG sizes and card pairs respect widths.
        run = []
        run_is_image = None
        for part in parts:
            is_image = isinstance(part, dict)
            if run and is_image != run_is_image:
                self.emit_run(kind, run, run_is_image)
                run = []
            run.append(part)
            run_is_image = is_image
        self.emit_run(kind, run, run_is_image)

    def emit_run(self, kind, run, is_image):
        if not run:
            return
        if is_image:
            self.blocks.append(('images', run))
        else:
            value = clean(run)
            if value:
                self.blocks.append((kind, value))

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'details':
            self.flush()
            self.details.append({'parent_visible': self.visible(), 'summary': False, 'open': self.expand_details or 'open' in attrs})
            return
        if tag == 'summary':
            if self.details:
                self.details[-1]['summary'] = True
            if self.visible():
                self.flush()
                self.kind, self.parts = 'summary', []
            return
        if not self.visible():
            return
        if tag in ['p', 'h2', 'h3', 'li']:
            self.flush()
            self.kind, self.parts = tag, []
        elif tag == 'picture':
            self.source = None
        elif tag == 'source':
            media = attrs.get('media', '')
            if self.mobile and ('max-width' in media or not media):
                self.source = attrs.get('srcset', '').split(',')[0].strip().split(' ')[0]
        elif tag == 'img':
            item = {
                'src': self.source or attrs.get('src', ''),
                'alt': attrs.get('alt', ''),
                'width': attrs.get('width'),
                'height': attrs.get('height'),
            }
            if self.kind:
                # Pure formatting whitespace between images should not break
                # a badge flow into separate full-width rows.
                if self.parts and isinstance(self.parts[-1], str) and not self.parts[-1].strip():
                    self.parts.pop()
                self.parts.append(item)
            else:
                self.blocks.append(('images', [item]))
        elif tag == 'br':
            if self.cell is not None:
                self.cell.append('\u2028')
            elif self.kind:
                self.parts.append('\u2028')
            else:
                self.blocks.append(('space', 12))
        elif tag == 'tr':
            self.row = []
        elif tag in ['td', 'th']:
            self.cell = []

    def handle_endtag(self, tag):
        if tag == 'details':
            if self.visible():
                self.flush()
            if self.details:
                self.details.pop()
            return
        if tag == 'summary':
            if self.kind == 'summary':
                self.flush()
            if self.details:
                self.details[-1]['summary'] = False
            return
        if not self.visible():
            return
        if tag in ['p', 'h2', 'h3', 'li']:
            self.flush()
        elif tag == 'picture':
            self.source = None
        elif tag in ['td', 'th']:
            self.row.append(clean(self.cell or []))
            self.cell = None
        elif tag == 'tr' and self.row:
            self.blocks.append(('row', self.row))

    def handle_data(self, data):
        if not self.visible():
            return
        if self.cell is not None:
            self.cell.append(data)
        elif self.kind:
            # Ignore only formatting whitespace directly after an image.
            if data.strip() or not self.parts or not isinstance(self.parts[-1], dict):
                self.parts.append(data)

    def finish(self):
        self.close()
        self.flush()


def face(size, bold=False):
    name = 'DM-Sans-normal-700-2.ttf' if bold else 'DM-Sans-normal-400-0.ttf'
    return ImageFont.truetype(str(FONTS / name), size)


def rich_text(canvas, xy, value, font, fill):
    """Keep native Unicode emoji colorful in the offline PNG preview."""
    draw = ImageDraw.Draw(canvas)
    x, y = xy
    for part in re.split(r'([\U0001F300-\U0001FAFF\u2661\u2727])', value):
        if not part:
            continue
        if part in ('♡', '✧'):
            symbol_font = ImageFont.truetype('/System/Library/Fonts/Apple Symbols.ttf', font.size + 3)
            draw.text((x, y), part, font=symbol_font, fill=fill, anchor='lt')
            x += draw.textlength(part, font=symbol_font)
        elif len(part) == 1 and ord(part) >= 0x1F300:
            emoji_font = ImageFont.truetype('/System/Library/Fonts/Apple Color Emoji.ttc', 32)
            tile = Image.new('RGBA', (64, 64))
            ImageDraw.Draw(tile).text((0, 0), part, font=emoji_font, embedded_color=True, anchor='lt')
            bounds = tile.getbbox()
            if bounds:
                tile = tile.crop(bounds)
                height = font.size + 2
                tile = tile.resize((round(tile.width * height / tile.height), height), Image.Resampling.LANCZOS)
                canvas.alpha_composite(tile, (round(x), round(y)))
                x += tile.width
        else:
            draw.text((x, y), part, font=font, fill=fill, anchor='lt')
            x += draw.textlength(part, font=font)


def lines_for(value, font, width, draw):
    lines = []
    for paragraph in value.split('\n'):
        line = ''
        for word in paragraph.split():
            trial = (line + ' ' + word).strip()
            if line and draw.textlength(trial, font=font) > width:
                lines.append(line)
                line = word
            else:
                line = trial
        if line:
            lines.append(line)
    return lines


def numeric(value):
    if value is None:
        return None
    match = re.match(r'^\s*(\d+(?:\.\d+)?)\s*(?:px)?\s*$', str(value))
    return float(match.group(1)) if match else None


def requested_width(value, available):
    if value and str(value).strip().endswith('%'):
        try:
            return available * float(str(value).strip()[:-1]) / 100
        except ValueError:
            return None
    return numeric(value)


def svg_size(path):
    root = ET.parse(path).getroot()
    width, height = numeric(root.attrib.get('width')), numeric(root.attrib.get('height'))
    if not width or not height:
        viewbox = re.split(r'[\s,]+', root.attrib.get('viewBox', '').strip())
        if len(viewbox) == 4:
            width, height = float(viewbox[2]), float(viewbox[3])
    return (width, height) if width and height else None


def preview_map():
    path = CACHE / 'preview-map.json'
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def widget_path(value):
    path = Path(value)
    if path.is_absolute():
        return path
    candidates = [ROOT / path, CACHE / path, BUILD / path]
    return next((p for p in candidates if p.exists()), candidates[0])


def placeholder(item, available, mobile):
    size = 13 if mobile else 16
    font = face(size)
    measure = ImageDraw.Draw(Image.new('RGB', (1,1)))
    prefix = 'Live widget: ' if item['src'].startswith(('https://', 'http://')) else 'Image: '
    label = prefix + (item['alt'] or 'preview unavailable')
    width = min(available, max(110, round(measure.textlength(label, font=font))+24))
    lines = lines_for(label, font, width-24, measure)
    tile = Image.new('RGBA', (width, max(34,len(lines)*(size+7)+16)), '#f6f8fa')
    draw = ImageDraw.Draw(tile)
    draw.rounded_rectangle((0,0,width-1,tile.height-1), radius=5, outline='#d1d9e0')
    for i,line in enumerate(lines):
        draw.text((12,8+i*(size+7)),line,font=font,fill='#57606a',anchor='lt')
    return tile


def load_image(item, available, mobile, mapping):
    src = item['src']
    badge = src.startswith(('./assets/badges/', 'assets/badges/'))
    native = None
    if src.startswith(('https://', 'http://')):
        path = widget_path(mapping[src]) if src in mapping else None
    elif badge:
        svg = ROOT / src
        if svg.exists():
            native = svg_size(svg)
        path = BUILD / 'badge-preview' / (Path(src).stem+'.png')
    else:
        path = ROOT / src
    if path is None or not path.exists():
        return placeholder(item, available, mobile)
    img = Image.open(path).convert('RGBA')
    if badge:
        # Raster badge previews are rendered at density 144; HTML uses the
        # SVG root's native dimensions, not those larger raster dimensions.
        width, height = native or (img.width/2, img.height/2)
    else:
        width = requested_width(item.get('width'), available) or min(available,img.width)
        width = min(width,available)
        height = img.height*width/img.width
    scale = min(1, available/width)
    target = (max(1,round(width*scale)),max(1,round(height*scale)))
    return img.resize(target,Image.Resampling.LANCZOS)


def image_flow(items, available, mobile, mapping):
    gap = 8 if mobile else 10
    row, row_width, row_height = [], 0, 0
    rows = []
    for item in items:
        img = load_image(item,available,mobile,mapping)
        if row and row_width+gap+img.width > available:
            rows.append((row,row_height))
            row,row_width,row_height = [],0,0
        x = row_width+(gap if row else 0)
        row.append((x,img))
        row_width = x+img.width
        row_height = max(row_height,img.height)
    if row:
        rows.append((row,row_height))
    total = sum(height for _,height in rows)+gap*max(0,len(rows)-1)+15
    tile = Image.new('RGBA',(available,max(1,total)),'#ffffff')
    y = 0
    for row,height in rows:
        for x,img in row:
            tile.alpha_composite(img,(x,y))
        y += height+gap
    return tile


def render(mobile=False, expand_details=False):
    if mobile and expand_details:
        raise ValueError('The expanded preview is desktop only.')
    width,pad = (430,20) if mobile else (1060,40)
    available = width-2*pad
    parser = Blocks(mobile,expand_details=expand_details)
    parser.feed((ROOT/'README.md').read_text())
    parser.finish()
    mapping = preview_map()
    tiles = []
    measure = ImageDraw.Draw(Image.new('RGB',(1,1)))
    for kind,value in parser.blocks:
        if kind == 'images':
            tiles.append(image_flow(value,available,mobile,mapping))
        elif kind == 'space':
            tiles.append(Image.new('RGBA',(available,value),'#ffffff'))
        elif kind == 'summary':
            size = 16 if mobile else 20
            f = face(size,True)
            images = value.get('images', [])
            if images:
                # Keep the native disclosure triangle outside the image. Width
                # attributes are percentages of the README, with enough room
                # reserved for that marker rather than flattening it into art.
                inset = 22 if mobile else 26
                sized = []
                for item in images:
                    desired = requested_width(item.get('width'),available) or available
                    sized.append({**item,'width':str(min(desired,available-inset))})
                flow = image_flow(sized,available-inset,mobile,mapping)
                text_lines = lines_for(value['text'],f,available-inset,measure)
                step = round(size*1.5)
                label_height = len(text_lines)*step+(6 if text_lines else 0)
                tile = Image.new('RGBA',(available,label_height+flow.height+3),'#ffffff')
                tile.alpha_composite(flow,(inset,label_height))
                draw = ImageDraw.Draw(tile)
                marker_y = label_height+max(15,(flow.height-15)//2)
                if value['expanded']:
                    draw.polygon([(2,marker_y-4),(14,marker_y-4),(8,marker_y+4)],fill='#57606a')
                else:
                    draw.polygon([(4,marker_y-6),(4,marker_y+6),(12,marker_y)],fill='#57606a')
                for i,line in enumerate(text_lines):
                    rich_text(tile,(inset,i*step),line,f,'#1f2328')
                if value['expanded']:
                    draw.line((inset,tile.height-2,available,tile.height-2),fill='#e8dce2')
            else:
                lines = lines_for(value['text'],f,available-30,measure)
                step = round(size*1.5)
                tile = Image.new('RGBA',(available,len(lines)*step+19),'#ffffff')
                draw = ImageDraw.Draw(tile)
                if value['expanded']:
                    draw.polygon([(2,12),(14,12),(8,20)],fill='#57606a')
                else:
                    draw.polygon([(4,9),(4,21),(12,15)],fill='#57606a')
                for i,line in enumerate(lines):
                    rich_text(tile,(25,5+i*step),line,f,'#1f2328')
            tiles.append(tile)
        elif kind == 'row':
            first_width = 96 if mobile else 190
            size,step = (15,25) if mobile else (20,32)
            f = face(size)
            body = ' | '.join(value[1:])
            first_lines = lines_for(value[0],face(size,True),first_width-20,measure)
            body_lines = lines_for(body,f,available-first_width-22,measure)
            height = max(len(first_lines),len(body_lines))*step+23
            tile = Image.new('RGBA',(available,height),'#f6f8fa' if value[0] == 'Area' else '#ffffff')
            draw = ImageDraw.Draw(tile)
            draw.rectangle((0,0,available-1,height-1),outline='#d1d9e0',width=1)
            draw.line((first_width,0,first_width,height),fill='#d1d9e0')
            for i,line in enumerate(first_lines):
                draw.text((10,10+i*step),line,font=face(size,True),fill='#1f2328',anchor='lt')
            for i,line in enumerate(body_lines):
                draw.text((first_width+10,10+i*step),line,font=f,fill='#1f2328',anchor='lt')
            tiles.append(tile)
        else:
            size = (23 if mobile else 30) if kind == 'h2' else (16 if mobile else 20)
            f = face(size,kind in ['h2','h3'])
            indent = 24 if kind == 'li' else 0
            lines = lines_for(value,f,available-indent,measure)
            step = round(size*1.6)
            top = 12 if kind == 'h2' else 3
            bottom = 8 if kind == 'li' else 22
            tile = Image.new('RGBA',(available,top+len(lines)*step+bottom),'#ffffff')
            draw = ImageDraw.Draw(tile)
            color = '#0969da' if 'LinkedIn' in value else '#1f2328'
            if kind == 'li':
                draw.ellipse((3,top+8,8,top+13),fill='#1f2328')
            for i,line in enumerate(lines):
                rich_text(tile,(indent,top+i*step),line,f,color)
            if kind == 'h2':
                draw.line((0,tile.height-10,available,tile.height-10),fill='#d1d9e0')
            tiles.append(tile)
    head = 74
    height = head+pad+sum(t.height for t in tiles)+12
    image = Image.new('RGBA',(width,height),'#ffffff')
    draw = ImageDraw.Draw(image)
    draw.rectangle((0,0,width,head),fill='#f6f8fa')
    draw.line((0,head,width,head),fill='#d1d9e0')
    title = 'yana16-afk / README.md'+(' · expanded' if expand_details else '')
    draw.text((pad,26),title,font=face(15 if mobile else 19,True),fill='#1f2328',anchor='lt')
    y = head+pad
    for tile in tiles:
        image.alpha_composite(tile,(pad,y))
        y += tile.height
    name = 'profile-preview-expanded.png' if expand_details else ('profile-preview-mobile.png' if mobile else 'profile-preview.png')
    destination = ROOT/name
    image.convert('RGB').save(destination,optimize=True)
    print(('Expanded desktop' if expand_details else ('Phone' if mobile else 'Desktop'))+f' static preview: {width} × {height}')
    return destination


if __name__ == '__main__':
    render()
    render(True)
    render(expand_details=True)
