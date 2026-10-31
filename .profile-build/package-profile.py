"""Validate and package the current GitHub profile without copying stale assets.

Default invocation updates only preview.html's readme article, github-profile.zip
and .profile-build/validation.json. --check-only is read-only. --stage optionally
creates a fresh, uniquely named staging directory; existing files are never
removed. No network calls are made and publishing is not performed.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
from html import unescape
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / '.profile-build'
ASSETS = ROOT / 'assets'
VALIDATION = BUILD / 'validation.json'


class ValidationError(Exception):
    pass


def srcset_urls(value):
    """Return URL tokens from normal HTML srcsets, retaining query commas.

    URL tokens end at whitespace; optional descriptors end at the next comma.
    Data URLs are rejected by asset_path rather than read or decoded.
    """
    urls = []
    position = 0
    length = len(value)
    while position < length:
        while position < length and (value[position].isspace() or value[position] == ','):
            position += 1
        start = position
        while position < length and not value[position].isspace():
            position += 1
        token = value[start:position]
        if not token:
            continue
        if token.endswith(','):
            urls.append(token.rstrip(','))
            continue
        urls.append(token)
        while position < length and value[position] != ',':
            position += 1
    return urls


class Readme(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.references = []
        self.images = []
        self.sources = []
        self.links = []
        self.headings = []
        self.details = []
        self.details_stack = []
        self.heading_parts = None
        self.heading_is_visible = True
        self.about_visible_immediately = False
        self.in_summary = False
        self.summary_parts = []
        self.errors = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        line = self.getpos()[0]
        if tag in {'script', 'style', 'iframe', 'canvas', 'form', 'input', 'button', 'object', 'embed'}:
            self.errors.append(f'Unsupported README element <{tag}> on line {line}.')
        for key in a:
            if key.startswith('on') or key in {'style', 'class', 'id'}:
                self.errors.append(f'GitHub removes attribute {key!r} on line {line}; use native formatting.')
        if tag == 'img':
            alt = a.get('alt', '')
            self.images.append({'alt': alt, 'line': line, 'src': a.get('src', '')})
            if not alt.strip():
                self.errors.append(f'Image on line {line} needs meaningful alt text.')
            if not a.get('src') and not a.get('srcset'):
                self.errors.append(f'Image on line {line} has no src or srcset.')
            if a.get('src'):
                self.references.append((a['src'], line))
            if self.in_summary and self.details_stack:
                self.details_stack[-1]['summary_images'] += 1
            if self.in_summary and alt:
                self.summary_parts.append(alt)
        if tag in {'img', 'source'} and a.get('srcset'):
            self.references.extend((url, line) for url in srcset_urls(a['srcset']))
        if tag == 'source':
            self.sources.append(a)
        if tag == 'a' and a.get('href'):
            self.links.append(a['href'])
        if re.fullmatch(r'h[1-6]', tag):
            self.heading_parts = []
            self.heading_is_visible = all(item['open'] for item in self.details_stack)
        if tag == 'details':
            detail = {'open': 'open' in a, 'depth': len(self.details_stack), 'summary': '', 'summary_images': 0}
            self.details.append(detail)
            self.details_stack.append(detail)
        if tag == 'summary':
            self.in_summary = True
            self.summary_parts = []

    def handle_endtag(self, tag):
        if re.fullmatch(r'h[1-6]', tag) and self.heading_parts is not None:
            heading = ' '.join(''.join(self.heading_parts).split())
            self.headings.append(heading)
            if self.heading_is_visible and re.search(r'\babout\b', heading, re.I):
                self.about_visible_immediately = True
            self.heading_parts = None
        if tag == 'summary':
            if self.details_stack:
                self.details_stack[-1]['summary'] = ' '.join(' '.join(self.summary_parts).split())
            self.in_summary = False
            self.summary_parts = []
        if tag == 'details':
            if not self.details_stack:
                self.errors.append('Closing </details> has no matching opening tag.')
            else:
                self.details_stack.pop()

    def handle_data(self, value):
        if self.heading_parts is not None:
            self.heading_parts.append(value)
        if self.in_summary:
            self.summary_parts.append(value)


class ArticleLocator(HTMLParser):
    """Locate the exact inner byte-equivalent text span of one readme article."""
    def __init__(self, source):
        super().__init__(convert_charrefs=False)
        self.source = source
        self.offsets = [0]
        for line in source.splitlines(keepends=True):
            self.offsets.append(self.offsets[-1] + len(line))
        self.depth = 0
        self.matches = []
        self.start = None

    def position(self):
        line, column = self.getpos()
        return self.offsets[line-1] + column

    def handle_starttag(self, tag, attrs):
        if tag != 'article':
            return
        if self.depth:
            self.depth += 1
        elif 'readme' in dict(attrs).get('class', '').split():
            self.depth = 1
            self.start = self.position() + len(self.get_starttag_text())

    def handle_endtag(self, tag):
        if tag == 'article' and self.depth:
            self.depth -= 1
            if self.depth == 0:
                self.matches.append((self.start, self.position()))


def article_span(source):
    parser = ArticleLocator(source)
    parser.feed(source)
    parser.close()
    if parser.depth or len(parser.matches) != 1:
        raise ValidationError('preview.html must contain exactly one complete <article class="readme">.')
    return parser.matches[0]


def asset_path(url):
    url = unescape(url).strip()
    parts = urlsplit(url)
    if parts.scheme in {'http', 'https'} and parts.netloc:
        return None
    if parts.scheme or parts.netloc:
        raise ValidationError(f'Unsupported image URL scheme: {url!r}')
    decoded = unquote(parts.path)
    if not decoded or decoded.startswith('/') or '\\' in decoded or '\x00' in decoded:
        raise ValidationError(f'Unsafe local image path: {url!r}')
    pure = PurePosixPath(decoded)
    if not pure.parts or '..' in pure.parts or pure.parts[0] != 'assets':
        raise ValidationError(f'Local image must be inside assets/: {url!r}')
    name = pure.as_posix()
    path = ROOT / name
    if not path.resolve().is_relative_to(ASSETS.resolve()):
        raise ValidationError(f'Local image escapes assets/ through a symbolic link: {url!r}')
    if not path.is_file():
        raise ValidationError(f'Missing local image: {name}')
    return name


def image_metadata(name, data):
    suffix = Path(name).suffix.lower()
    metadata = {'bytes': len(data)}
    if not data:
        raise ValidationError(f'Empty image: {name}')
    if suffix == '.svg':
        try:
            root = ET.fromstring(data)
        except ET.ParseError as exc:
            raise ValidationError(f'Invalid SVG {name}: {exc}') from exc
        if root.tag.split('}')[-1] != 'svg':
            raise ValidationError(f'Expected SVG document root: {name}')
        for node in root.iter():
            if node.tag.split('}')[-1] in {'script', 'foreignObject'}:
                raise ValidationError(f'Active or unsupported SVG content in {name}')
            for key, value in node.attrib.items():
                if key.startswith('on'):
                    raise ValidationError(f'Active SVG event handler in {name}')
                if key.split('}')[-1] == 'href' and value.startswith(('http:', 'https:', '//')):
                    raise ValidationError(f'External SVG image dependency in {name}')
        metadata.update({'format': 'SVG', 'width': root.get('width'), 'height': root.get('height')})
    else:
        try:
            from PIL import Image
        except ImportError as exc:
            raise ValidationError('Raster validation needs Pillow; run this helper with the bundled Python interpreter.') from exc
        try:
            with Image.open(io.BytesIO(data)) as image:
                metadata.update({'format': image.format, 'pixels': list(image.size)})
                frames = getattr(image, 'n_frames', 1)
                if frames > 1:
                    durations = []
                    for index in range(frames):
                        image.seek(index)
                        durations.append(image.info.get('duration', 0))
                        image.load()
                    metadata.update({'frames': frames, 'loop_ms': sum(durations), 'loop': image.info.get('loop')})
                else:
                    image.verify()
        except Exception as exc:
            raise ValidationError(f'Invalid raster image {name}: {exc}') from exc
    return metadata


def markdown_images(text):
    # HTML remains the primary profile format, but native Markdown images are
    # supported so a future terminal-banner rename cannot silently miss assets.
    without_comments = re.sub(r'<!--.*?-->', '', text, flags=re.S)
    without_fences = re.sub(r'(?ms)^\s*(`{3,}|~{3,}).*?^\s*\1\s*$', '', without_comments)
    pattern = r'!\[([^\]]*)\]\(\s*(?:<([^>]+)>|([^\s)]+))(?:\s+["\'][^\n]*?["\'])?\s*\)'
    return [(m.group(1), m.group(2) or m.group(3), text.count('\n', 0, m.start())+1)
            for m in re.finditer(pattern, without_fences)]


def read_snapshot():
    raw = (ROOT / 'README.md').read_bytes()
    text = raw.decode('utf-8')
    parsed = Readme()
    parsed.feed(text)
    parsed.close()
    if parsed.details_stack:
        parsed.errors.append('README has an unclosed <details> section.')
    for alt, url, line in markdown_images(text):
        parsed.images.append({'alt': alt, 'line': line, 'src': url})
        parsed.references.append((url, line))
        if not alt.strip():
            parsed.errors.append(f'Markdown image near line {line} needs alt text.')
    headings = parsed.headings + re.findall(r'(?m)^#{1,6}\s+(.+?)\s*#*$', text)
    forbidden_headings = [heading for heading in headings
                          if re.fullmatch(r'(?:experience|selected projects|development projects|projects)(?: (?:md|json|log|txt))?',
                                          re.sub(r'[^a-z]+', ' ', heading.lower()).strip())]
    if forbidden_headings:
        parsed.errors.append('Removed experience/project section returned: '+', '.join(forbidden_headings))
    # The user now explicitly requested a professional, resume-backed bio.
    # Verified education is allowed; removed standalone project sections stay guarded.
    assets = {}
    remote = set()
    for url, line in parsed.references:
        try:
            name = asset_path(url)
            if name is None:
                remote.add(url)
            elif re.search(r'(^|/)about-corner(?:[-.]|$)', name, re.I):
                parsed.errors.append(f'The removed About illustration is referenced: {name}')
            elif re.search(r'(^|/)project-(?:planado|tugmatik|ecollect)(?:[-.]|$)', name, re.I):
                parsed.errors.append(f'A removed selected-project image is referenced: {name}')
            elif name not in assets:
                assets[name] = (ROOT / name).read_bytes()
        except (ValidationError, OSError) as exc:
            parsed.errors.append(f'Line {line}: {exc}')
    if parsed.errors:
        raise ValidationError('\n'.join(parsed.errors))
    metadata = {name: image_metadata(name, data) for name, data in sorted(assets.items())}
    preview = (ROOT / 'preview.html').read_text()
    start, end = article_span(preview)
    synced = preview[:start] + text + preview[end:]
    check_start, check_end = article_span(synced)
    if synced[check_start:check_end] != text:
        raise ValidationError('Could not synchronize the exact README into preview.html.')
    return raw, text, parsed, assets, metadata, remote, synced


def atomic_bytes(path, data):
    handle = tempfile.NamedTemporaryFile(prefix='.'+path.name+'-', dir=path.parent, delete=False)
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(data)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def zip_bytes(readme, assets):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in [('README.md', readme)] + sorted(assets.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    data = output.getvalue()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        expected = {'README.md', *assets}
        if set(archive.namelist()) != expected or archive.testzip() is not None:
            raise ValidationError('ZIP integrity or exact asset inventory verification failed.')
        if archive.read('README.md') != readme:
            raise ValidationError('ZIP README differs from the validated README.')
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-only', action='store_true', help='Validate and report without writing any output.')
    parser.add_argument('--stage', action='store_true', help='Additionally create a fresh owned staging directory; existing files are never deleted.')
    args = parser.parse_args(argv)
    if args.check_only and args.stage:
        parser.error('--stage cannot be combined with --check-only')
    raw, text, parsed, assets, images, remote, preview = read_snapshot()
    package = zip_bytes(raw, assets)
    details = parsed.details
    top = [item for item in details if item['depth'] == 0]
    nested = [item for item in details if item['depth'] > 0]
    badges = [name for name in assets if 'badges' in PurePosixPath(name).parts]
    technologies = [name for name in badges if Path(name).stem not in {'discord', 'email', 'linkedin'}]
    animations = {name: value for name, value in images.items() if value.get('frames', 1) > 1}
    loops = {item['loop_ms'] for item in animations.values()}
    counts = {
        'readme_sha256': hashlib.sha256(raw).hexdigest(),
        'local_references_valid': True,
        'local_reference_occurrences': sum(1 for url, line in parsed.references if not urlsplit(url).scheme),
        'local_image_assets': len(assets),
        'images_with_alt_text': len(parsed.images),
        'remote_image_urls': len(remote),
        'package_files': len(assets)+1,
        'package_bytes': len(package),
        'package_uncompressed_bytes': len(raw)+sum(len(data) for data in assets.values()),
        'sections_removed': True,
        'about_illustrations': False,
        'about_image_removed': True,
        'preview_matches_readme': True,
        'native_expandable_sections': len(top),
        'native_expandable_panels': sum(item['summary_images'] > 0 for item in details),
        'details_total': len(details),
        'details_open_by_default': sum(item['open'] for item in details),
        'nested_tool_groups': len(nested),
        'technology_badges': len(technologies),
        'discord_badge': sum(Path(name).stem == 'discord' for name in badges),
        'about_open_by_default': any('about' in item['summary'].lower() and item['open'] for item in details),
        'about_visible_immediately': parsed.about_visible_immediately,
        'bonus_chapter_reveal': any('bonus' in item['summary'].lower() for item in details),
        'nested_personal_reveals': sum(item['depth'] > 0 and 'bonus' in item['summary'].lower() for item in details),
        'animation_layouts': animations,
        'animation_loop_ms': next(iter(loops)) if len(loops) == 1 else None,
        'reduced_motion_fallback': any('prefers-reduced-motion' in item.get('media', '') for item in parsed.sources),
        'profile_repository': 'yana16-afk/yana16-afk',
        'package_scope': 'README.md and exactly its referenced local assets; remote images are not downloaded',
    }
    summary = {
        'status': 'validated; no files written' if args.check_only else 'packaged',
        'local_assets': len(assets), 'image_tags': len(parsed.images),
        'remote_images': len(remote), 'zip_files': len(assets)+1,
        'zip_bytes': len(package), 'animated_assets': len(animations),
        'top_level_disclosures': len(top), 'technology_badges': len(technologies),
        'target_repository': 'yana16-afk/yana16-afk',
    }
    if not args.check_only:
        # All files are byte snapshots; fail before mutations if README changed
        # while validation was running rather than packaging a mixed version.
        if (ROOT / 'README.md').read_bytes() != raw:
            raise ValidationError('README changed during validation; rerun after edits finish.')
        existing = json.loads(VALIDATION.read_text()) if VALIDATION.exists() else {}
        if not isinstance(existing, dict):
            raise ValidationError('validation.json must contain a JSON object.')
        existing.pop('gif_frames_per_layout', None)
        existing.update(counts)
        existing['local_package_validated_at'] = datetime.now(timezone.utc).isoformat()
        if args.stage:
            stage = Path(tempfile.mkdtemp(prefix='profile-stage-', dir=BUILD))
            (stage / 'README.md').write_bytes(raw)
            for name, data in assets.items():
                destination = stage / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
            summary['stage_directory'] = str(stage)
        atomic_bytes(ROOT / 'preview.html', preview.encode('utf-8'))
        atomic_bytes(ROOT / 'github-profile.zip', package)
        atomic_bytes(VALIDATION, (json.dumps(existing, indent=2, ensure_ascii=False)+'\n').encode('utf-8'))
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return summary


if __name__ == '__main__':
    try:
        main()
    except (ValidationError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SystemExit('Profile packaging stopped:\n'+str(exc))
