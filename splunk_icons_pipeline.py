"""Splunk icon sheet → draw.io libraries."""

import base64
import difflib
import html
import io
import hashlib
import json
import re
import logging
import time
from collections import defaultdict
import urllib.error
import urllib.parse
import urllib.request
import xml.sax.saxutils as xml_utils
import zlib
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps, ImageFilter
from scipy import ndimage

from icon_stencil import svg_to_stencil
from icon_vector import vectorize_crop

Image.MAX_IMAGE_PIXELS = None

ROOT = Path(__file__).resolve().parent
SOURCE_DIR = ROOT / 'source'
DIST_DIR = ROOT / 'dist'
CROPS_DIR = DIST_DIR / 'crops'
SOURCE_DIR.mkdir(exist_ok=True)
DIST_DIR.mkdir(exist_ok=True)
CROPS_DIR.mkdir(exist_ok=True)

SHEET = SOURCE_DIR / 'Splunk_Documentation_Icons_August2018.png'
DEFAULT_SHEET_DOCS_URL = (
    'https://help.splunk.com/en/splunk-enterprise/administer/inherit-a-splunk-deployment/'
    '10.4/inherited-deployment-tasks/draw-a-diagram-of-your-deployment'
)
# Splunk docs return 403 without a browser-like User-Agent.
HTTP_USER_AGENT = (
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36'
)
SHEET_HREF_RE = re.compile(
    r'''href=["']([^"']*Splunk_Documentation_Icons_August2018\.png[^"']*)["']''',
    re.I,
)
PNG_MAGIC = b'\x89PNG\r\n\x1a\n'


class SheetDownloadError(RuntimeError):
    """Splunk docs page or PNG URL could not be fetched."""


logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('pipeline')

CUSTOM_CROPS_DIR = DIST_DIR / 'custom_crops'
CUSTOM_MANIFEST = DIST_DIR / 'custom_crops.json'
CUSTOM_CROPS_DIR.mkdir(exist_ok=True)
TITLES_PATH = ROOT / 'canonical_titles.json'
CUSTOM_OVERLAP_IOU = 0.35
OCR_INSTALL_HINT = 'OCR is optional. Install with: uv sync --extra ocr'

_CANONICAL_DOC: dict | None = None
_CANONICAL_ROWS: list[list[str]] | None = None


def catalog_document() -> dict:
    """Load canonical_titles.json (may be empty)."""
    global _CANONICAL_DOC
    if _CANONICAL_DOC is None:
        if TITLES_PATH.is_file():
            _CANONICAL_DOC = json.loads(TITLES_PATH.read_text())
        else:
            _CANONICAL_DOC = {}
    return _CANONICAL_DOC


def invalidate_catalog_cache() -> None:
    global _CANONICAL_DOC, _CANONICAL_ROWS
    _CANONICAL_DOC = None
    _CANONICAL_ROWS = None


def canonical_title_rows() -> list[list[str]]:
    """Sheet titles by row, left to right (committed names, not artwork)."""
    global _CANONICAL_ROWS
    if _CANONICAL_ROWS is None:
        _CANONICAL_ROWS = [list(r) for r in catalog_document().get('rows') or []]
    return _CANONICAL_ROWS


def catalog_title(row: int, col: int) -> str | None:
    rows = canonical_title_rows()
    if 0 <= row < len(rows) and 0 <= col < len(rows[row]):
        title = str(rows[row][col]).strip()
        return title or None
    return None


def known_titles() -> list[str]:
    seen: list[str] = []
    for row in canonical_title_rows():
        for title in row:
            text = str(title).strip()
            if text and text not in seen:
                seen.append(text)
    return seen


def catalog_covers(manifest: list[dict]) -> bool:
    return bool(manifest) and all(
        catalog_title(item['icon_row'], item['col']) for item in manifest
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def sheet_docs_url() -> str:
    meta = catalog_document().get('sheet')
    if isinstance(meta, dict):
        url = str(meta.get('docs_url') or '').strip()
        if url:
            return url
    return DEFAULT_SHEET_DOCS_URL


def sheet_moved_message(detail: str) -> str:
    return (
        f'{detail.rstrip()}\n'
        f'Splunk may have moved the icon sheet. Open:\n'
        f'  {sheet_docs_url()}\n'
        'and save the Transparent PNG as:\n'
        f'  {SHEET}'
    )


def find_sheet_png_url(page_html: str, page_url: str = '') -> str | None:
    """Return the Transparent PNG href from a Splunk docs HTML page, or None."""
    match = SHEET_HREF_RE.search(page_html)
    if not match:
        return None
    href = html.unescape(match.group(1))
    return urllib.parse.urljoin(page_url or sheet_docs_url(), href)


def _http_get(url: str, timeout: float) -> tuple[bytes, str]:
    req = urllib.request.Request(
        url,
        headers={'User-Agent': HTTP_USER_AGENT, 'Accept': '*/*'},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        ctype = resp.headers.get('Content-Type') or ''
        return resp.read(), ctype


def download_sheet(*, force: bool = False) -> Path:
    """Fetch the August 2018 PNG from Splunk docs into source/.

    The docs page is the stable location; the PNG href itself is a short-lived
    CDN link. If Splunk moves the page or the file, raise SheetDownloadError.
    """
    if SHEET.is_file() and not force:
        return SHEET
    SOURCE_DIR.mkdir(exist_ok=True)
    docs = sheet_docs_url()
    try:
        page, _ctype = _http_get(docs, timeout=30)
    except urllib.error.HTTPError as exc:
        raise SheetDownloadError(sheet_moved_message(
            f'Could not open Splunk docs (HTTP {exc.code}).'
        )) from exc
    except urllib.error.URLError as exc:
        raise SheetDownloadError(sheet_moved_message(
            f'Could not open Splunk docs ({exc.reason}).'
        )) from exc
    png_url = find_sheet_png_url(page.decode('utf-8', errors='replace'), docs)
    if not png_url:
        raise SheetDownloadError(sheet_moved_message(
            'Could not find a Transparent PNG link on the Splunk docs page.'
        ))
    log.info('Downloading icon sheet from Splunk docs…')
    try:
        data, ctype = _http_get(png_url, timeout=120)
    except urllib.error.HTTPError as exc:
        raise SheetDownloadError(sheet_moved_message(
            f'PNG download failed (HTTP {exc.code}).'
        )) from exc
    except urllib.error.URLError as exc:
        raise SheetDownloadError(sheet_moved_message(
            f'PNG download failed ({exc.reason}).'
        )) from exc
    if not data.startswith(PNG_MAGIC) or 'html' in ctype.lower():
        raise SheetDownloadError(sheet_moved_message(
            'The download link did not return a PNG.'
        ))
    tmp = SHEET.with_suffix('.png.part')
    tmp.write_bytes(data)
    try:
        with Image.open(tmp) as img:
            sheet = img.convert('RGBA')
            verify_sheet(sheet, tmp)
    except ValueError as exc:
        tmp.unlink(missing_ok=True)
        raise SheetDownloadError(sheet_moved_message(str(exc))) from exc
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        raise SheetDownloadError(sheet_moved_message(
            f'Downloaded file is not a readable PNG ({exc}).'
        )) from exc
    tmp.replace(SHEET)
    log.info('Saved %s (%d bytes)', SHEET, len(data))
    return SHEET


def verify_sheet(sheet: Image.Image, path: Path | None = None) -> None:
    """Refuse a PNG that does not match the catalog's August 2018 sheet fingerprint."""
    meta = catalog_document().get('sheet')
    if not isinstance(meta, dict):
        return
    width, height = meta.get('width'), meta.get('height')
    if width and height and sheet.size != (int(width), int(height)):
        raise ValueError(
            f'Source PNG is {sheet.size[0]}×{sheet.size[1]}, but canonical_titles.json '
            f'was built for {width}×{height} ({meta.get("file", "the August 2018 sheet")}). '
            'Download that sheet from Splunk docs — a newer or different PNG will attach the wrong names.'
        )
    expected = meta.get('sha256')
    if expected and path and path.is_file():
        digest = sha256_file(path)
        if digest.lower() != str(expected).lower():
            raise ValueError(
                f'Source PNG sha256 {digest[:16]}… does not match catalog {str(expected)[:16]}…. '
                'This file is not the sheet the titles were written for.'
            )


def write_canonical_from_labels(labels: list[dict]) -> dict:
    """Write workbench titles back to canonical_titles.json by grid position."""
    doc = dict(catalog_document())
    old_rows = [list(r) for r in doc.get('rows') or []]
    updates: dict[tuple[int, int], str] = {}
    for item in labels:
        if item.get('custom'):
            continue
        row, col = item.get('icon_row'), item.get('col')
        title = (item.get('title') or '').strip()
        if isinstance(row, int) and isinstance(col, int) and title:
            updates[(row, col)] = title
    if not updates:
        raise ValueError('No grid titles to write — run the pipeline so labels have icon_row and col.')
    max_row = max(max(r for r, _ in updates), len(old_rows) - 1)
    rows: list[list[str]] = []
    for r in range(max_row + 1):
        old = old_rows[r] if r < len(old_rows) else []
        cols = [c for rr, c in updates if rr == r]
        max_col = max(cols + [len(old) - 1])
        row = []
        for c in range(max_col + 1):
            if (r, c) in updates:
                row.append(updates[(r, c)])
            elif c < len(old):
                row.append(old[c])
            else:
                row.append('')
        rows.append(row)
    if isinstance(doc.get('sheet'), str):
        doc['sheet'] = {'file': doc['sheet']}
    doc['rows'] = rows
    doc.setdefault(
        'note',
        'Icon titles by sheet row, left to right. Names only — not Splunk artwork.',
    )
    TITLES_PATH.write_text(json.dumps(doc, indent=2) + '\n', encoding='utf-8')
    invalidate_catalog_cache()
    log.info('Wrote %d titles to %s', sum(len(r) for r in rows), TITLES_PATH)
    return catalog_document()


def shape_tags(title: str) -> str:
    """draw.io sidebar search tags derived from the icon title."""
    words = re.findall(r'[a-z0-9]+', title.lower())
    stop = {'with', 'and', 'the', 'a', 'an', 'of', 'on', 'or'}
    tags = ['splunk']
    if 'search' in words and 'head' in words:
        tags.append('search-head')
    if 'load' in words and 'balancer' in words:
        tags.append('load-balancer')
    if 'form' in words:
        tags.append('form-input')
    if 'panel' in words or 'panels' in words:
        tags.append('panel')
    for os_name in ('linux', 'mac', 'windows', 'solaris'):
        if os_name in words:
            tags.extend((os_name, 'os'))
    tags.extend(w for w in words if w not in stop and len(w) > 1)
    return ' '.join(dict.fromkeys(tags))


def assign_row_cols(boxes: list[dict]) -> None:
    counts: dict[int, int] = defaultdict(int)
    for box in boxes:
        row = box['icon_row']
        box['col'] = counts[row]
        counts[row] += 1


def _rect(item: dict) -> tuple[int, int, int, int] | None:
    if all(k in item for k in ('x0', 'y0', 'x1', 'y1')):
        return item['x0'], item['y0'], item['x1'], item['y1']
    if all(k in item for k in ('x', 'y', 'w', 'h')):
        return item['x'], item['y'], item['x'] + item['w'], item['y'] + item['h']
    return None


def _rect_iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    inter = max(0, ix1 - ix0) * max(0, iy1 - iy0)
    area_a = max(0, ax1 - ax0) * max(0, ay1 - ay0)
    area_b = max(0, bx1 - bx0) * max(0, by1 - by0)
    union = area_a + area_b - inter
    return inter / union if union else 0.0


def custom_crop_overlaps_auto(entry: dict, auto_items: list[dict]) -> bool:
    crect = _rect(entry)
    if not crect:
        return False
    for item in auto_items:
        arect = _rect(item)
        if arect and _rect_iou(crect, arect) >= CUSTOM_OVERLAP_IOU:
            return True
    return False


def labels_for_build(labels_final: list[dict]) -> list[dict]:
    """Merge hand-picked custom crops that are not already auto-detected."""
    items = list(labels_final)
    if not CUSTOM_MANIFEST.is_file():
        return items
    for i, entry in enumerate(json.loads(CUSTOM_MANIFEST.read_text())):
        if custom_crop_overlaps_auto(entry, items):
            log.info('Skipping custom crop %s (overlaps auto-detected icon)', entry.get('title') or entry['file'])
            continue
        crop_path = CUSTOM_CROPS_DIR / entry['file']
        if not crop_path.is_file():
            log.warning('Skipping missing custom crop: %s', entry['file'])
            continue
        crop = Image.open(crop_path).convert('RGBA')
        color_info = analyze_pixel_colors(crop)
        items.append({
            'id': f"custom_{entry.get('id', i)}",
            'file': entry['file'],
            'title': (entry.get('title') or f'Custom {i + 1:03d}').strip(),
            'raw_ocr': '',
            'custom': True,
            'dominant_color': color_info['dominant_color'],
            'color_name': color_info['color_name'],
            'palette': color_info['palette'],
        })
    return items


_OCR_READER = None


def ocr_reader():
    """Lazy EasyOCR reader (English). Created once per process."""
    global _OCR_READER
    if _OCR_READER is None:
        try:
            import easyocr
        except ImportError as exc:
            raise ImportError(OCR_INSTALL_HINT) from exc
        log.info('Loading EasyOCR English model (first run may download weights)…')
        _OCR_READER = easyocr.Reader(['en'], gpu=False, verbose=False)
    return _OCR_READER


def ocr_label_band(img: Image.Image, box: dict, pad_x: int = 12, scale: int = 4) -> str:
    """OCR label text below an icon (alpha-only); supports one- or two-line labels."""
    bounds = box.get('label_bounds')
    if not bounds:
        return ''
    x0, y0, x1, y1 = bounds
    x0 = max(0, x0 + pad_x)
    x1 = min(img.width, x1 - pad_x)
    if y1 <= y0 or x1 <= x0:
        return ''
    band = img.crop((x0, y0, x1, y1)).convert('RGBA')
    arr = np.array(band)
    alpha = arr[:, :, 3].astype(np.float32)
    bg = ndimage.gaussian_filter(alpha, sigma=4)
    enhanced = np.clip((alpha - bg) * 3 + 128, 0, 255).astype(np.uint8)
    proc = Image.fromarray(enhanced, 'L')
    proc = ImageOps.autocontrast(proc)
    label_h = y1 - y0
    min_h = max(48, label_h * scale)
    proc = proc.resize((proc.width * scale, max(proc.height * scale, min_h)), Image.LANCZOS)
    proc = proc.filter(ImageFilter.MedianFilter(3))
    rgb = np.array(proc.convert('RGB'))
    lines = ocr_reader().readtext(rgb, detail=0, paragraph=True)
    return re.sub(r'\s+', ' ', ' '.join(str(t) for t in lines)).strip()



def compress_mx_graph(xml_str: str) -> str:
    """Compress mxGraphModel XML for mxlibrary entries (draw.io Graph.compress)."""
    quoted = urllib.parse.quote(xml_str, safe='')
    compressor = zlib.compressobj(wbits=-15)
    compressed = compressor.compress(quoted.encode('utf-8')) + compressor.flush()
    return base64.b64encode(compressed).decode('ascii')

def encode_mx(data: str) -> str:
    """draw.io mxlibrary compression: quote → raw-deflate → base64."""
    quoted = urllib.parse.quote(data, safe='')
    compressor = zlib.compressobj(wbits=-15)
    compressed = compressor.compress(quoted.encode('utf-8')) + compressor.flush()
    return base64.b64encode(compressed).decode('ascii')


def decode_mx(data: str) -> str:
    """Inverse of encode_mx / compress_mx_graph."""
    raw = zlib.decompress(base64.b64decode(data), wbits=-15)
    return urllib.parse.unquote(raw.decode('utf-8'))


def display_size(w: int, h: int, max_size: int = 96) -> tuple[int, int]:
    scale = min(max_size / w, max_size / h, 1.0)
    return max(1, int(w * scale)), max(1, int(h * scale))


def png_data_uri(png_bytes: bytes) -> str:
    return 'data:image/png;base64,' + base64.b64encode(png_bytes).decode('ascii')


def svg_data_uri(svg: str) -> str:
    return 'data:image/svg+xml,' + urllib.parse.quote(svg, safe='')


def invert_for_dark(img: Image.Image) -> Image.Image:
    """Invert RGB where alpha > 10 (keep transparent pixels transparent)."""
    rgba = np.array(img.convert('RGBA'))
    mask = rgba[:, :, 3] > 10
    out = rgba.copy()
    out[mask, 0] = 255 - out[mask, 0]
    out[mask, 1] = 255 - out[mask, 1]
    out[mask, 2] = 255 - out[mask, 2]
    return Image.fromarray(out, 'RGBA')


def alpha_mask_png(png_bytes: bytes) -> bytes:
    """White silhouette on transparent — strips source grey/black RGB."""
    img = Image.open(io.BytesIO(png_bytes)).convert('RGBA')
    arr = np.array(img)
    mask = arr[:, :, 3] > 10
    out = np.zeros_like(arr)
    out[mask, 0] = 255
    out[mask, 1] = 255
    out[mask, 2] = 255
    out[mask, 3] = arr[mask, 3]
    buf = io.BytesIO()
    Image.fromarray(out, 'RGBA').save(buf, format='PNG')
    return buf.getvalue()


_ADAPTIVE_FILL = 'var(--icon-color, light-dark(#111111, #ffffff))'


def silhouette_svg(png_bytes: bytes, w: int, h: int) -> str:
    """SVG silhouette themed via cssVars and light-dark() fallback (draw.io 30.4+)."""
    img = Image.open(io.BytesIO(png_bytes)).convert('RGBA')
    if img.size != (w, h):
        img = img.resize((w, h), Image.LANCZOS)
    scaled = io.BytesIO()
    img.save(scaled, format='PNG')
    mask_bytes = alpha_mask_png(scaled.getvalue())
    b64 = base64.b64encode(mask_bytes).decode('ascii')
    mid = hashlib.sha1(mask_bytes).hexdigest()[:8]
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" color-scheme="light dark">'
        f'<defs><mask id="m{mid}">'
        f'<image width="{w}" height="{h}" href="data:image/png;base64,{b64}"/>'
        f'</mask></defs>'
        f'<rect width="{w}" height="{h}" fill="{_ADAPTIVE_FILL}" mask="url(#m{mid})"/>'
        '</svg>'
    )


def adaptive_image_entry(title: str, w: int, h: int, svg_uri: str) -> dict:
    """Adaptive icon entry — cssVars + light-dark() for light/dark editor modes."""
    entry = image_entry(title, w, h, svg_uri)
    # cssVars must be declared; --icon-color may use light-dark (no semicolons in values).
    entry['style'] = (
        'cssVars=icon-color;'
        '--icon-color=light-dark(#111111,#ffffff);'
    )
    return entry


def rgb_to_hex(rgb) -> str:
    r, g, b = (int(rgb[0]), int(rgb[1]), int(rgb[2]))
    return f'#{r:02x}{g:02x}{b:02x}'


def color_luminance(rgb) -> float:
    r, g, b = (float(rgb[0]), float(rgb[1]), float(rgb[2]))
    return 0.299 * r + 0.587 * g + 0.114 * b


def name_pixel_color(hexcolor: str, lum: float) -> str:
    """Map sampled RGB to a human label (black/grey/splunk tones)."""
    h = hexcolor.lower()
    r, g, b = int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)
    if b >= 0x90 and g >= 0x60 and r < 0x40:
        return 'splunk-teal'
    if r >= 0xe0 and g >= 0x70 and b < 0x50:
        return 'splunk-orange'
    if g >= 0x70 and 0x50 <= r <= 0x90 and b < 0x60:
        return 'splunk-olive'
    if g >= 0x90 and r >= 0x80 and b < 0x70:
        return 'splunk-gold'
    if lum >= 200:
        return 'white'
    if lum >= 120:
        return 'light'
    if lum >= 70:
        return 'grey'
    if lum >= 24:
        return 'grey'
    return 'black'


def analyze_pixel_colors(img: Image.Image, min_pixels: int = 16, max_colors: int = 4) -> dict:
    """Sample opaque pixels; return dominant color, label, and palette."""
    from collections import Counter

    arr = np.array(img.convert('RGBA'))
    mask = arr[:, :, 3] > 10
    rgb = arr[mask][:, :3]
    if len(rgb) < min_pixels:
        return {
            'dominant_color': '#000000',
            'color_name': 'black',
            'palette': [],
        }
    q = (rgb // 8) * 8
    counts = Counter(map(tuple, q))
    palette = []
    for (r, g, b), count in counts.most_common(max_colors):
        if count < min_pixels:
            continue
        hexcolor = rgb_to_hex((r, g, b))
        lum = color_luminance((r, g, b))
        palette.append({
            'hex': hexcolor,
            'name': name_pixel_color(hexcolor, lum),
            'pixels': int(count),
            'share': round(count / len(rgb), 3),
        })
    if not palette:
        return {
            'dominant_color': '#000000',
            'color_name': 'black',
            'palette': [],
        }
    dominant = palette[0]
    color_name = dominant['name']
    if len(palette) > 1 and palette[1]['share'] >= 0.06:
        secondary = palette[1]
        if secondary['name'] != color_name:
            color_name = f"{color_name}+{secondary['name']}"
    return {
        'dominant_color': dominant['hex'],
        'color_name': color_name,
        'palette': palette,
    }


def title_with_color(title: str, color_name: str, hexcolor: str) -> str:
    """Append color metadata to a library sidebar title."""
    return f"{title} [{color_name} {hexcolor}]"


def image_entry(
    title: str,
    w: int,
    h: int,
    data_uri: str,
    aspect: str = 'fixed',
) -> dict:
    """draw.io mxlibrary image entry (data property — avoids style-parser issues)."""
    dw, dh = display_size(w, h)
    entry = {
        'data': data_uri,
        'w': dw,
        'h': dh,
        'title': title,
        'aspect': aspect,
        'tags': shape_tags(title),
    }
    return entry


def configurable_entry(title: str, w: int, h: int, svg: str) -> dict:
    """Native stencil + Edit Data fields (title, hostname, ip, notes)."""
    stencil = svg_to_stencil(svg, name=title)
    dw, dh = display_size(w, h)
    title_attr = xml_utils.escape(title, {'"': '&quot;'})
    style = (
        f'shape=stencil({encode_mx(stencil)});'
        'whiteSpace=wrap;html=1;aspect=fixed;'
        'verticalLabelPosition=bottom;verticalAlign=top;align=center;'
        'spacingTop=4;fontSize=11;'
        # fillColor=default is shape *background* (white in light, black in dark).
        # These icons are line art painted with fill, so invert that pair.
        'fillColor=light-dark(#111111,#ffffff);strokeColor=none;strokeWidth=1.5;'
    )
    label = '%title%&lt;br&gt;%hostname%&lt;br&gt;%ip%'
    raw = (
        '<mxGraphModel><root>'
        '<mxCell id="0"/><mxCell id="1" parent="0"/>'
        f'<object id="2" label="{label}" title="{title_attr}" '
        'hostname="" ip="" notes="" placeholders="1">'
        f'<mxCell style="{style}" vertex="1" parent="1">'
        f'<mxGeometry width="{dw}" height="{dh}" as="geometry"/>'
        '</mxCell></object>'
        '</root></mxGraphModel>'
    )
    return {
        'xml': compress_mx_graph(raw),
        'w': dw,
        'h': dh,
        'title': title,
        'tags': shape_tags(title) + ' configurable',
    }



def library_json(shapes: list[dict]) -> str:
    """Uncompressed mxlibrary JSON payload (draw.io / .drawiolib)."""
    return json.dumps(shapes, ensure_ascii=True, separators=(',', ':'))


def build_library(shapes: list[dict]) -> str:
    """Wrap shape dicts in <mxlibrary> XML (device import)."""
    return '<?xml version="1.0" encoding="UTF-8"?>\n<mxlibrary>' + library_json(shapes) + '</mxlibrary>'


def write_library(path: Path, shapes: list[dict]) -> None:
    """Write .xml (mxlibrary) and .drawiolib (pure JSON) for the same shapes."""
    payload = library_json(shapes)
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<mxlibrary>' + payload + '</mxlibrary>',
        encoding='utf-8',
    )
    path.with_suffix('.drawiolib').write_text(payload, encoding='utf-8')




# Detection tuning — grid icons vs connector samples at sheet bottom
SCAN_SCALE = 4
CROP_PAD = 10
ICON_ROW_TOP_PAD = 80  # icons may extend above the shared row band
ICON_ROW_MERGE_GAP = 40  # attach a short chrome/header band just above an icon row
LABEL_SEARCH_DEPTH = 220
LABEL_LINE_MIN_H = 8
LABEL_LINE_GAP = 14
LABEL_MAX_LINE_H = 80
ROW_THRESH = 0.05
COL_THRESH = 0.06
MIN_COL_W = 150
ICON_ROW_MIN_H = 200
LABEL_ROW_MAX_H = 150
LABEL_ROW_MIN_H = 25
ICON_Y_MIN = 400
ICON_Y_MAX = 19000  # include Form Inputs / Panels rows; connectors start ~20500
CONNECTOR_REGION_Y_MIN = 20500
LABEL_GAP_MAX = 200


def connector_xml(title: str, style: str, w: int = 120, h: int = 40) -> dict:
    """mxGraphModel connector entry; xml is Graph.compress encoded for draw.io import."""
    y = h // 2
    raw = (
        '<mxGraphModel><root>'
        '<mxCell id="0"/><mxCell id="1" parent="0"/>'
        f'<mxCell id="2" value="" style="{style}" edge="1" parent="1" source="3" target="4">'
        '<mxGeometry relative="1" as="geometry"/>'
        '</mxCell>'
        '<mxCell id="3" value="" style="ellipse;fillColor=none;strokeColor=none;" vertex="1" parent="1">'
        f'<mxGeometry x="4" y="{y}" width="1" height="1" as="geometry"/>'
        '</mxCell>'
        '<mxCell id="4" value="" style="ellipse;fillColor=none;strokeColor=none;" vertex="1" parent="1">'
        f'<mxGeometry x="{w - 4}" y="{y}" width="1" height="1" as="geometry"/>'
        '</mxCell>'
        '</root></mxGraphModel>'
    )
    return {
        'xml': compress_mx_graph(raw),
        'w': w,
        'h': h,
        'title': title,
    }


def load_sheet() -> Image.Image:
    """Load the Splunk icon sheet from source/, downloading it if missing."""
    if not SHEET.is_file():
        log.info('Source PNG missing; downloading from Splunk docs…')
        download_sheet()
    t0 = time.perf_counter()
    sheet = Image.open(SHEET).convert('RGBA')
    log.info('Loaded %s %s in %.1fs', SHEET, sheet.size, time.perf_counter() - t0)
    verify_sheet(sheet, SHEET)
    return sheet


def scan_row_bands(
    proj: np.ndarray,
    scale: int = SCAN_SCALE,
    thresh_ratio: float = ROW_THRESH,
    min_rows: int = 2,
) -> list[dict]:
    """Group consecutive occupied rows into horizontal bands (top-to-bottom scan)."""
    smooth = ndimage.uniform_filter1d(proj.astype(np.float64), size=3)
    thresh = smooth.max() * thresh_ratio
    bands, in_band, start = [], False, 0
    for i, val in enumerate(smooth):
        if val > thresh and not in_band:
            start = i
            in_band = True
        elif val <= thresh and in_band:
            if i - start >= min_rows:
                bands.append({
                    'y0': start * scale,
                    'y1': i * scale,
                    'h': (i - start) * scale,
                })
            in_band = False
    if in_band and len(smooth) - start >= min_rows:
        bands.append({
            'y0': start * scale,
            'y1': len(smooth) * scale,
            'h': (len(smooth) - start) * scale,
        })
    return bands


def scan_col_bands(
    proj: np.ndarray,
    scale: int = SCAN_SCALE,
    thresh_ratio: float = COL_THRESH,
    min_col_w: int = MIN_COL_W,
) -> list[dict]:
    """Find column cells within one icon row, merging narrow gutter gaps."""
    if proj.max() == 0:
        return []
    thresh = proj.max() * thresh_ratio
    raw, in_band, start = [], False, 0
    for i, val in enumerate(proj):
        if val > thresh and not in_band:
            start = i
            in_band = True
        elif val <= thresh and in_band:
            raw.append((start, i))
            in_band = False
    if in_band:
        raw.append((start, len(proj)))
    if not raw:
        return []
    min_gap = max(2, min_col_w // scale)
    merged = [list(raw[0])]
    for s, e in raw[1:]:
        if s - merged[-1][1] < min_gap:
            merged[-1][1] = e
        else:
            merged.append([s, e])
    return [
        {'x0': s * scale, 'x1': e * scale, 'w': (e - s) * scale}
        for s, e in merged
        if (e - s) * scale >= min_col_w
    ]


def find_cell_label_bounds(
    alpha: np.ndarray,
    x0: int,
    x1: int,
    y_start: int,
    search_depth: int = LABEL_SEARCH_DEPTH,
) -> list[int] | None:
    """Find one- or two-line label text below a grid cell using per-column alpha scan."""
    x0 = max(0, x0)
    x1 = min(alpha.shape[1], x1)
    y_end = min(alpha.shape[0], y_start + search_depth)
    if y_end <= y_start or x1 <= x0:
        return None
    region = alpha[y_start:y_end, x0:x1] > 10
    row_sum = region.sum(axis=1)
    raw, in_band, start = [], False, 0
    for i, val in enumerate(row_sum):
        if val > 0 and not in_band:
            start = i
            in_band = True
        elif val == 0 and in_band:
            if i - start >= LABEL_LINE_MIN_H:
                raw.append([start, i])
            in_band = False
    if in_band and len(row_sum) - start >= LABEL_LINE_MIN_H:
        raw.append([start, len(row_sum)])
    if not raw:
        return None
    merged = [raw[0]]
    for s, e in raw[1:]:
        if s - merged[-1][1] <= LABEL_LINE_GAP:
            merged[-1][1] = e
        else:
            merged.append([s, e])
    parts = [b for b in merged if (b[1] - b[0]) <= LABEL_MAX_LINE_H]
    if not parts:
        parts = merged[:2]
    return [x0, y_start + parts[0][0], x1, y_start + parts[-1][1]]


def crop_icon_cell(
    img: Image.Image,
    x0: int,
    x1: int,
    y0: int,
    y1: int,
    pad: int = CROP_PAD,
    top_pad: int = ICON_ROW_TOP_PAD,
) -> tuple[Image.Image, tuple[int, int, int, int]] | tuple[None, None]:
    """Crop icon content from a grid cell, allowing extra headroom above the row band."""
    crop_y0 = max(0, y0 - top_pad)
    cell = img.crop((x0, crop_y0, x1, y1))
    arr = np.array(cell)
    mask = arr[:, :, 3] > 10
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return None, None
    cx0 = max(0, int(xs.min()) - pad)
    cy0 = max(0, int(ys.min()) - pad)
    cx1 = min(cell.width, int(xs.max()) + pad + 1)
    cy1 = min(cell.height, int(ys.max()) + pad + 1)
    abs_box = (x0 + cx0, crop_y0 + cy0, x0 + cx1, crop_y0 + cy1)
    return cell.crop((cx0, cy0, cx1, cy1)), abs_box


def sample_region_colors(band: np.ndarray, mask: np.ndarray, x0: int, x1: int, y0: int, y1: int, max_colors: int = 3) -> list[dict]:
    """Dominant colors within a sub-region of a connector band."""
    from collections import Counter

    sub = band[y0:y1, x0:x1]
    sub_mask = mask[y0:y1, x0:x1]
    rgb = sub[sub_mask][:, :3]
    if len(rgb) < 8:
        return []
    q = (rgb // 8) * 8
    counts = Counter(map(tuple, q))
    out = []
    for (r, g, b), count in counts.most_common(max_colors):
        hexcolor = rgb_to_hex((r, g, b))
        lum = color_luminance((r, g, b))
        out.append({
            'hex': hexcolor,
            'name': name_pixel_color(hexcolor, lum),
            'pixels': int(count),
            'share': round(count / len(rgb), 3),
        })
    return out


def parse_connector_style(band: np.ndarray) -> dict | None:
    """Infer draw.io edge style and sampled colors from a connector band."""
    mask = band[:, :, 3] > 10
    if mask.sum() < 50:
        return None
    ys, xs = np.where(mask)
    x0, x1 = xs.min(), xs.max() + 1
    y0, y1 = ys.min(), ys.max() + 1
    mid_y = (y0 + y1) // 2
    row_slice = mask[mid_y, x0:x1]
    runs = []
    k = 0
    while k < len(row_slice):
        if row_slice[k]:
            s = k
            while k < len(row_slice) and row_slice[k]:
                k += 1
            runs.append(k - s)
        else:
            k += 1
    dashed = len(runs) >= 4 and np.median(runs) < 30
    end_slice = row_slice[max(0, len(row_slice) - 24):]
    has_arrow = end_slice.sum() > end_slice.size * 0.12
    col_heights = mask[:, x0:x1].sum(axis=1)
    active_cols = np.where(mask[:, x0:x1].sum(axis=0) > 0)[0]
    span = active_cols[-1] - active_cols[0] if len(active_cols) else 0
    peak_rows = np.where(col_heights > span * 0.25)[0]
    orthogonal = len(peak_rows) >= 3 and (peak_rows.max() - peak_rows.min()) > 8

    width = x1 - x0
    margin = max(8, width // 20)
    line_y0 = max(y0, mid_y - 2)
    line_y1 = min(y1, mid_y + 3)
    line_colors = sample_region_colors(band, mask, x0 + margin, x1 - margin, line_y0, line_y1)
    start_colors = sample_region_colors(band, mask, x0, x0 + margin * 2, y0, y1)
    end_colors = sample_region_colors(band, mask, x1 - margin * 2, x1, y0, y1)

    stroke = line_colors[0]['hex'] if line_colors else rgb_to_hex(band[mask][:, :3].mean(axis=0))
    stroke_name = line_colors[0]['name'] if line_colors else name_pixel_color(stroke, color_luminance(tuple(int(stroke[i:i+2], 16) for i in (1, 3, 5))))
    endpoint_colors = []
    for bucket in (start_colors[:1], end_colors[:1]):
        if bucket and bucket[0]['hex'] != stroke:
            endpoint_colors.append(bucket[0])

    parts = ['html=1', 'rounded=0', f'strokeColor={stroke}', 'strokeWidth=2']
    if endpoint_colors:
        parts.append(f'fillColor={endpoint_colors[0]["hex"]}')
    if orthogonal:
        parts[:0] = ['edgeStyle=orthogonalEdgeStyle', 'jettySize=auto', 'orthogonalLoop=1']
    else:
        parts[:0] = ['edgeStyle=none']
    if dashed:
        parts.append('dashed=1')
    parts.append('endArrow=classic' if has_arrow else 'endArrow=none')
    parts.append('startArrow=none')

    title_bits = []
    if orthogonal:
        title_bits.append('elbow')
    if dashed:
        title_bits.append('dashed')
    if has_arrow:
        title_bits.append('arrow')
    if not title_bits:
        title_bits.append('line')
    palette = line_colors + [c for c in start_colors + end_colors if c['hex'] not in {p['hex'] for p in line_colors}][:2]

    return {
        'title': f"{' '.join(title_bits).title()} [{stroke_name} {stroke}]",
        'style': ';'.join(parts) + ';',
        'stroke_color': stroke,
        'stroke_name': stroke_name,
        'endpoint_colors': endpoint_colors,
        'palette': palette,
        'dashed': bool(dashed),
        'arrow': bool(has_arrow),
        'orthogonal': bool(orthogonal),
    }


def detect_connectors(img: Image.Image, y_min: int = CONNECTOR_REGION_Y_MIN) -> list[dict]:
    """Parse connector line samples from the bottom connector palette."""
    t0 = time.perf_counter()
    alpha = np.array(img.split()[3])
    region = alpha[y_min:, :]
    small = region[::SCAN_SCALE, ::SCAN_SCALE] > 10
    row_proj = small.sum(axis=1)
    rows = []
    i = 0
    while i < len(row_proj):
        if row_proj[i] > 0:
            j = i
            while j < len(row_proj) and row_proj[j] > 0:
                j += 1
            if j - i >= 2:
                rows.append(((i + j - 1) // 2) * SCAN_SCALE + y_min)
            i = j
        else:
            i += 1
    log.info('Connector region: found %d sample rows (y>=%d)', len(rows), y_min)
    connectors = []
    for idx, ry in enumerate(rows):
        y0 = max(y_min, ry - 48)
        y1 = min(img.height, ry + 48)
        parsed = parse_connector_style(np.array(img.crop((0, y0, img.width, y1))))
        if parsed is None:
            continue
        parsed['id'] = idx
        parsed['y'] = ry
        connectors.append(parsed)
    log.info('Parsed %d connector styles in %.1fs', len(connectors), time.perf_counter() - t0)
    return connectors


def detect_boxes(img: Image.Image) -> list[dict]:
    """Detect icons by scanning row bands then column bands within each icon row."""
    t0 = time.perf_counter()
    alpha = np.array(img.split()[3])
    small = alpha[::SCAN_SCALE, ::SCAN_SCALE] > 10
    log.info('Scanning row bands on mask %s (scale=%d)', small.shape, SCAN_SCALE)

    row_bands = scan_row_bands(small.sum(axis=1))
    icon_rows = [
        dict(b) for b in row_bands
        if b['h'] >= ICON_ROW_MIN_H and ICON_Y_MIN <= b['y0'] < ICON_Y_MAX
    ]
    for icon_row in icon_rows:
        changed = True
        while changed:
            changed = False
            for band in row_bands:
                if band['y1'] <= icon_row['y0'] and icon_row['y0'] - band['y1'] <= ICON_ROW_MERGE_GAP:
                    new_y0 = min(icon_row['y0'], band['y0'])
                    if new_y0 < icon_row['y0']:
                        icon_row['y0'] = new_y0
                        icon_row['h'] = icon_row['y1'] - icon_row['y0']
                        changed = True
    log.info('Found %d row bands, %d icon rows (h>=%d, y=%d–%d)',
             len(row_bands), len(icon_rows), ICON_ROW_MIN_H, ICON_Y_MIN, ICON_Y_MAX)

    boxes = []
    for row_idx, icon_row in enumerate(icon_rows):
        y0, y1 = icon_row['y0'], icon_row['y1']
        col_proj = small[y0 // SCAN_SCALE:y1 // SCAN_SCALE].sum(axis=0)
        cols = scan_col_bands(col_proj)
        log.info('Icon row %d: y=%d–%d h=%d → %d columns', row_idx, y0, y1, icon_row['h'], len(cols))
        for col in cols:
            crop, abs_box = crop_icon_cell(img, col['x0'], col['x1'], y0, y1)
            if crop is None or crop.width < 40 or crop.height < 40:
                continue
            ax0, ay0, ax1, ay1 = abs_box
            label_bounds = find_cell_label_bounds(alpha, col['x0'] + 12, col['x1'] - 12, y1)
            entry = {
                'x': ax0,
                'y': ay0,
                'w': ax1 - ax0,
                'h': ay1 - ay0,
                'crop': crop,
                'icon_row': row_idx,
                'cell': [col['x0'], y0, col['x1'], y1],
            }
            if label_bounds:
                entry['label_bounds'] = label_bounds
            boxes.append(entry)

    boxes.sort(key=lambda b: (b['icon_row'], b['x']))
    assign_row_cols(boxes)
    log.info('Detected %d icons in %.1fs', len(boxes), time.perf_counter() - t0)
    return boxes


def step_crops(sheet: Image.Image) -> tuple[list[dict], list[dict]]:
    """Detect icons on the sheet, write dist/crops/ and manifest.json."""
    t0 = time.perf_counter()
    log.info('Starting crop detection')
    boxes = detect_boxes(sheet)
    connectors = detect_connectors(sheet)

    for old in CROPS_DIR.glob('icon_*.png'):
        old.unlink()

    manifest = []
    for i, box in enumerate(boxes):
        fname = f'icon_{i:03d}.png'
        box['crop'].save(CROPS_DIR / fname)
        color_info = analyze_pixel_colors(box['crop'])
        manifest.append({
            'id': i,
            'file': fname,
            'x': box['x'],
            'y': box['y'],
            'w': box['w'],
            'h': box['h'],
            'icon_row': box['icon_row'],
            'col': box['col'],
            'cell': box['cell'],
            'label_bounds': box.get('label_bounds'),
            'dominant_color': color_info['dominant_color'],
            'color_name': color_info['color_name'],
            'palette': color_info['palette'],
        })

    manifest_path = DIST_DIR / 'manifest.json'
    manifest_path.write_text(json.dumps(manifest, indent=2))
    (DIST_DIR / 'connectors.json').write_text(json.dumps(connectors, indent=2))
    log.info(
        'Wrote %s (%d crops) and connectors.json (%d styles) in %.1fs total',
        manifest_path,
        len(manifest),
        len(connectors),
        time.perf_counter() - t0,
    )
    return manifest, connectors


def run_ocr_pass(sheet: Image.Image, manifest: list[dict]) -> list[dict]:
    """OCR every icon label band; labels are alpha-only text below each grid cell."""
    ocr_results = []
    t0 = time.perf_counter()
    log.info('Starting OCR on %d icon crops (alpha-channel labels)', len(manifest))
    for i, box in enumerate(manifest):
        raw = ocr_label_band(sheet, box)
        ocr_results.append({'id': i, 'raw_ocr': raw})
        if i == 0 or (i + 1) % 25 == 0 or i + 1 == len(manifest):
            elapsed = time.perf_counter() - t0
            rate = (i + 1) / elapsed if elapsed > 0 else 0.0
            remaining = (len(manifest) - i - 1) / rate if rate > 0 else 0.0
            nonempty = sum(1 for r in ocr_results if r['raw_ocr'])
            log.info(
                'OCR %d/%d (%.1f/s, ~%.0fs left, %d named) latest: %r',
                i + 1, len(manifest), rate, remaining, nonempty, raw,
            )

    (DIST_DIR / 'labels_ocr.json').write_text(json.dumps(ocr_results, indent=2))
    log.info('OCR complete: %d labels (%d non-empty) in %.1fs',
             len(ocr_results), sum(1 for r in ocr_results if r['raw_ocr']), time.perf_counter() - t0)
    return ocr_results


KEEP_BARE = {'js', 'html', 'css', 'sdk'}
KEEP_SUBSTRINGS = ('custom visualization', 'simple xml', 'panels html', 'form inputs')

OCR_FIXES = [
    (r'\byeployment\b', 'deployment'),
    (r'\bapo\b', 'app'),
    (r'\bontfigquratic\b', 'configuration'),
    (r'\bsvstem\b', 'system'),
    (r'\bsvstems\b', 'systems'),
    (r'\bheavv\b', 'heavy'),
    (r'\byvdocuments\b', 'documents'),
    (r'\beookup\b', 'lookup'),
    (r'\btavelfer\b', 'forwarder'),
    (r'\b1ndexer\b', 'indexer'),
    (r'\b1ndexers\b', 'indexers'),
    (r'\bfile inout\b', 'file input'),
    (r'\bscripted inout\b', 'scripted input'),
    (r'\beventilypes\b', 'event types'),
    (r'\bsearch heac\b', 'search head'),
    (r'\bsplunk instan\b', 'splunk instance'),
]


def clean_ocr(text: str) -> str:
    text = text.strip().lower()
    for pat, repl in OCR_FIXES:
        text = re.sub(pat, repl, text)
    text = re.sub(r"[^a-z0-9+\-/\s']", ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def is_bare_letter(text: str) -> bool:
    t = clean_ocr(text)
    if not t:
        return True
    if t in KEEP_BARE:
        return False
    if any(s in t for s in KEEP_SUBSTRINGS):
        return False
    tokens = t.split()
    if len(tokens) == 1 and len(tokens[0]) <= 2:
        return True
    return False


def fuzzy_title(raw: str, cutoff: float = 0.52) -> str | None:
    cleaned = clean_ocr(raw)
    if not cleaned or len(cleaned) < 2:
        return None
    titles = known_titles()
    known_clean = [clean_ocr(t) for t in titles]
    for title, kc in zip(titles, known_clean):
        if kc == cleaned:
            return title
    matches = difflib.get_close_matches(cleaned, known_clean, n=1, cutoff=cutoff)
    if matches:
        return titles[known_clean.index(matches[0])]
    for title, kc in sorted(zip(titles, known_clean), key=lambda x: -len(x[0])):
        if len(kc) >= 5 and (kc in cleaned or cleaned in kc):
            return title
    if len(cleaned) >= 3 and not is_bare_letter(cleaned):
        return cleaned.title()
    return None


def _ocr_by_id(ocr_results: list[dict]) -> dict[int, str]:
    return {int(entry['id']): (entry.get('raw_ocr') or '') for entry in ocr_results}


def _previous_labels_by_cell() -> dict[tuple[int, int], dict]:
    path = DIST_DIR / 'labels_final.json'
    if not path.is_file():
        return {}
    out: dict[tuple[int, int], dict] = {}
    for row in json.loads(path.read_text()):
        if row.get('custom'):
            continue
        r, c = row.get('icon_row'), row.get('col')
        if isinstance(r, int) and isinstance(c, int):
            out[(r, c)] = row
    return out


def _placeholder_title(icon_id: int) -> str:
    return f'Splunk Icon {icon_id + 1:03d}'


def step_labels(ocr_results: list[dict] | None, manifest: list[dict]) -> list[dict]:
    """Assign titles from the catalog (by row/col), saved edits, then OCR fallback."""
    ocr_map = _ocr_by_id(ocr_results or [])
    previous = _previous_labels_by_cell()
    if any('col' not in item for item in manifest):
        assign_row_cols(sorted(manifest, key=lambda item: (item.get('icon_row', 0), item.get('x', 0))))
    labels_final = []
    labels_dropped = []
    n_catalog = n_saved = n_ocr = n_placeholder = 0

    for meta in manifest:
        row, col = meta['icon_row'], meta['col']
        raw = ocr_map.get(meta['id'], '')
        if raw and is_bare_letter(raw):
            labels_dropped.append({'id': meta['id'], 'raw_ocr': raw, 'reason': 'bare_letter'})
            raw = ''
        title = None
        source = 'placeholder'
        complete = False
        saved = previous.get((row, col))
        saved_title = ((saved or {}).get('title') or '').strip()
        cat = catalog_title(row, col)
        user_locked = (
            saved
            and saved.get('source') == 'user'
            and saved_title
            and not saved_title.startswith('Splunk Icon')
        )
        if user_locked:
            title = saved_title
            complete = bool(saved.get('complete'))
            source = 'user'
            n_saved += 1
        elif cat:
            title = cat
            complete = True
            source = 'catalog'
            n_catalog += 1
        if title is None:
            title = fuzzy_title(raw) if raw else None
            if title:
                source = 'ocr'
                n_ocr += 1
            else:
                title = _placeholder_title(meta['id'])
                source = 'placeholder'
                n_placeholder += 1
        labels_final.append({
            'id': meta['id'],
            'raw_ocr': raw,
            'title': title,
            'file': meta['file'],
            'icon_row': row,
            'col': col,
            'x': meta['x'],
            'y': meta['y'],
            'w': meta['w'],
            'h': meta['h'],
            'source': source,
            'complete': complete,
            'dominant_color': meta.get('dominant_color'),
            'color_name': meta.get('color_name'),
            'palette': meta.get('palette'),
        })

    (DIST_DIR / 'labels_final.json').write_text(json.dumps(labels_final, indent=2))
    (DIST_DIR / 'labels_dropped.json').write_text(json.dumps(labels_dropped, indent=2))
    log.info(
        'Titles: %d catalog, %d saved, %d OCR, %d placeholder (%d total)',
        n_catalog, n_saved, n_ocr, n_placeholder, len(labels_final),
    )
    return labels_final


def uniquify_titles(items: list[dict]) -> list[dict]:
    seen: dict[str, int] = {}
    out = []
    for item in items:
        title = item['title']
        count = seen.get(title, 0) + 1
        seen[title] = count
        final_title = title if count == 1 else f'{title} ({count})'
        out.append({**item, 'title': final_title})
    return out


def step_build(labels_final: list[dict], connectors: list[dict]) -> None:
    """Pack crops into draw.io mxlibrary XML files under dist/."""
    labeled = uniquify_titles(labels_for_build(labels_final))

    color_shapes = []
    dark_shapes = []
    adaptive_shapes = []
    configurable_shapes = []
    color_index: dict[str, list[str]] = {}

    t0 = time.perf_counter()
    log.info('Building icon libraries for %d labeled shapes', len(labeled))
    for n, item in enumerate(labeled, start=1):
        crop_path = (CUSTOM_CROPS_DIR if item.get('custom') else CROPS_DIR) / item['file']
        crop = Image.open(crop_path).convert('RGBA')
        w, h = crop.size
        png_bytes = io.BytesIO()
        crop.save(png_bytes, format='PNG')
        png_bytes = png_bytes.getvalue()

        dark_crop = invert_for_dark(crop)
        dark_buf = io.BytesIO()
        dark_crop.save(dark_buf, format='PNG')
        dark_bytes = dark_buf.getvalue()

        dw, dh = display_size(w, h)
        svg = silhouette_svg(png_bytes, dw, dh)

        color_name = item.get('color_name') or 'black'
        color_index.setdefault(color_name, []).append(item['file'])

        color_shapes.append(image_entry(item['title'], w, h, png_data_uri(png_bytes)))
        dark_shapes.append(image_entry(item['title'], w, h, png_data_uri(dark_bytes)))
        adaptive_shapes.append(adaptive_image_entry(item['title'], dw, dh, svg_data_uri(svg)))

        svg_trace = vectorize_crop(crop, mode='adaptive', width=w, height=h)
        configurable_shapes.append(configurable_entry(item['title'], w, h, svg_trace))

        if n == 1 or n % 50 == 0 or n == len(labeled):
            log.info('Packaged %d/%d icon shapes (%.1fs)', n, len(labeled), time.perf_counter() - t0)

    connector_shapes = []
    seen_conn: dict[str, int] = {}
    for conn in connectors:
        base_title = re.sub(r'\s*\[[^\]]+\]$', '', conn['title']).strip()
        count = seen_conn.get(base_title, 0) + 1
        seen_conn[base_title] = count
        title = base_title if count == 1 else f'{base_title} ({count})'
        connector_shapes.append(connector_xml(title, conn['style']))

    log.info('Built %d connector edge styles', len(connector_shapes))

    (DIST_DIR / 'color_index.json').write_text(json.dumps({
        'icons': color_index,
        'connectors': [
            {
                'title': c['title'],
                'stroke_color': c.get('stroke_color'),
                'stroke_name': c.get('stroke_name'),
                'endpoint_colors': c.get('endpoint_colors', []),
                'palette': c.get('palette', []),
            }
            for c in connectors
        ],
    }, indent=2))

    library_sets = {
        DIST_DIR / 'Splunk-Icons-color.xml': color_shapes,
        DIST_DIR / 'Splunk-Icons-dark.xml': dark_shapes,
        DIST_DIR / 'Splunk-Icons-adaptive.xml': adaptive_shapes,
        DIST_DIR / 'Splunk-Icons-configurable.xml': configurable_shapes,
        DIST_DIR / 'Splunk-Connectors.xml': connector_shapes,
    }

    for path, shapes in library_sets.items():
        write_library(path, shapes)
        log.info('Wrote %s + %s (%d entries)', path, path.with_suffix('.drawiolib'), len(shapes))

    log.info('Color index: %s', ', '.join(f"{k}={len(v)}" for k, v in sorted(color_index.items())))
    log.info('Done — import in draw.io via File → Open Library From → Device')


def run_all() -> None:
    sheet = load_sheet()
    manifest, connectors = step_crops(sheet)
    ocr_path = DIST_DIR / 'labels_ocr.json'
    if catalog_covers(manifest):
        log.info('Canonical titles cover all %d icons; skipping OCR', len(manifest))
        if ocr_path.is_file():
            cached = json.loads(ocr_path.read_text())
            ocr_results = cached if len(cached) == len(manifest) else []
        else:
            ocr_results = []
    else:
        missing = sum(1 for item in manifest if not catalog_title(item['icon_row'], item['col']))
        log.info('OCR for %d icons not in %s', missing, TITLES_PATH.name)
        try:
            ocr_results = run_ocr_pass(sheet, manifest)
        except ImportError as exc:
            raise ImportError(
                f'{missing} detected icons have no catalog title. {OCR_INSTALL_HINT}'
            ) from exc
    labels_final = step_labels(ocr_results, manifest)
    step_build(labels_final, connectors)


def _load_json(path: Path) -> list:
    if not path.is_file():
        raise FileNotFoundError(f'Missing {path} — run an earlier pipeline step first.')
    return json.loads(path.read_text())


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description='Splunk icon sheet → draw.io libraries')
    parser.add_argument(
        'step',
        choices=('all', 'download', 'crops', 'ocr', 'labels', 'build'),
        help='pipeline step (default: all)',
        nargs='?',
        default='all',
    )
    args = parser.parse_args(argv)

    if args.step == 'download':
        download_sheet(force=True)
        return 0

    if args.step == 'all':
        run_all()
        return 0

    if args.step == 'crops':
        step_crops(load_sheet())
        return 0

    if args.step == 'ocr':
        sheet = load_sheet()
        manifest = _load_json(DIST_DIR / 'manifest.json')
        run_ocr_pass(sheet, manifest)
        return 0

    if args.step == 'labels':
        manifest = _load_json(DIST_DIR / 'manifest.json')
        ocr_path = DIST_DIR / 'labels_ocr.json'
        ocr_results = json.loads(ocr_path.read_text()) if ocr_path.is_file() else []
        step_labels(ocr_results, manifest)
        return 0

    labels_final = _load_json(DIST_DIR / 'labels_final.json')
    connectors = _load_json(DIST_DIR / 'connectors.json')
    step_build(labels_final, connectors)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
