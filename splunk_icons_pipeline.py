"""Splunk icon sheet → draw.io libraries."""

import base64
import difflib
import io
import hashlib
import json
import re
import logging
import time
from collections import defaultdict
import urllib.parse
import xml.sax.saxutils as xml_utils
import zlib
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps, ImageFilter
import pytesseract
from scipy import ndimage

from icon_stencil import stencil_preview_svg, svg_to_stencil
from icon_vector import vectorize_crop

Image.MAX_IMAGE_PIXELS = None

ROOT = Path(__file__).resolve().parent
SOURCE_DIR = ROOT / 'source'
DIST_DIR = ROOT / 'dist'
CROPS_DIR = DIST_DIR / 'crops'
SOURCE_DIR.mkdir(exist_ok=True)
DIST_DIR.mkdir(exist_ok=True)
CROPS_DIR.mkdir(exist_ok=True)

CUSTOM_CROPS_DIR = DIST_DIR / 'custom_crops'
CUSTOM_MANIFEST = DIST_DIR / 'custom_crops.json'
CUSTOM_CROPS_DIR.mkdir(exist_ok=True)

# Single-icon SVG experiment (added to color library with a distinct sidebar title).
SVG_PROTOTYPE_CROP = 'icon_072.png'
SVG_PROTOTYPE_TITLE = 'Indexer — SVG prototype (icon_072)'


def labels_for_build(labels_final: list[dict]) -> list[dict]:
    """Merge hand-picked custom crops (custom_crops.json) into library build list."""
    items = list(labels_final)
    if not CUSTOM_MANIFEST.is_file():
        return items
    for i, entry in enumerate(json.loads(CUSTOM_MANIFEST.read_text())):
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


SHEET = SOURCE_DIR / 'Splunk_Documentation_Icons_August2018.png'
DIRECT_PNG_URL = ''  # optional: direct URL or JWT-backed CDN link to the PNG



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
    configs = ('--psm 6 -c preserve_interword_spaces=1', '--psm 7 -c preserve_interword_spaces=1') if label_h > 52 else (
        '--psm 7 -c preserve_interword_spaces=1', '--psm 6 -c preserve_interword_spaces=1')
    best = ''
    for cfg in configs:
        text = pytesseract.image_to_string(proc, config=cfg).strip()
        text = re.sub(r'\s+', ' ', text)
        if len(text) > len(best):
            best = text
    return best



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
        'tags': f'splunk configurable {title.lower()}',
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




logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('pipeline')

# Detection tuning — grid icons vs connector samples at sheet bottom
SCAN_SCALE = 4
CROP_PAD = 10
ICON_ROW_TOP_PAD = 80  # icons may extend above the shared row band
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
ICON_Y_MAX = 14000
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


import urllib.request


def load_sheet() -> Image.Image:
    """Load the Splunk icon sheet from source/ or DIRECT_PNG_URL."""
    if DIRECT_PNG_URL:
        log.info('Fetching %s', DIRECT_PNG_URL)
        req = urllib.request.Request(DIRECT_PNG_URL, headers={'User-Agent': 'splunk-drawio-icons/1.0'})
        with urllib.request.urlopen(req, timeout=60) as resp:
            sheet_bytes = resp.read()
        sheet = Image.open(io.BytesIO(sheet_bytes)).convert('RGBA')
        SHEET.write_bytes(sheet_bytes)
        log.info('Saved to %s (%d bytes)', SHEET, len(sheet_bytes))
        return sheet
    if SHEET.is_file():
        t0 = time.perf_counter()
        sheet = Image.open(SHEET).convert('RGBA')
        log.info('Loaded %s %s in %.1fs', SHEET, sheet.size, time.perf_counter() - t0)
        return sheet
    raise FileNotFoundError(
        f'Missing {SHEET}. Download Splunk_Documentation_Icons_August2018.png from Splunk docs '
        'or set DIRECT_PNG_URL in splunk_icons_pipeline.py.'
    )


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
        b for b in row_bands
        if b['h'] >= ICON_ROW_MIN_H and ICON_Y_MIN <= b['y0'] < ICON_Y_MAX
    ]
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

    boxes.sort(key=lambda b: (b['y'], b['x']))
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


KNOWN_TITLES = [
    'Alert', 'Add-on', 'App', 'Application', 'Base', 'Bucket', 'Cluster', 'Cloud',
    'Configuration', 'Custom Visualization', 'Data Model', 'Data Model Object', 'Data Packet',
    'Database', 'Datastore', 'Datastores', 'Deployer', 'Deployment', 'Deployment Server',
    'Desktop', 'Dimension', 'Directories', 'Directory', 'Directory Inputs',
    'Document', 'Documents', 'Distributed Management', 'ES Server', 'Event Handler',
    'Event Types', 'External Nodes', 'Fields', 'File Input', 'File Inputs', 'Firewall',
    'Forwarder', 'Forwarders', 'Heavy Forwarder', 'Universal Forwarder', 'Light Forwarder',
    'Intermediate Forwarder', 'Indexer', 'Indexers', 'Indexer Cluster',
    'Indexer Cluster Master', 'Indexer Cluster Peer', 'KV Store', 'KV Store Captain',
    'Knowledge Object', 'Laptop', 'License', 'License Master', 'License Server',
    'Load Balancer', 'Load File', 'Lookup', 'Lookup Dataset', 'Metric Index',
    'Monitoring Console', 'Network Input', 'Parsing Queue', 'Panels HTML',
    'People', 'Person', 'Pipeline', 'Pool', 'Queue', 'Report', 'Reports', 'Router',
    'SDK', 'Saved Search', 'Scheduled Report', 'Script', 'Scripted Input', 'Search',
    'Search Head', 'Search Heads', 'Search Head Cluster', 'Search Head Cluster Captain',
    'Search Head Cluster Deployer', 'Search Head Cluster Member', 'Search Head Cluster',
    'Settings', 'Simple XML', 'Splunk App', 'Splunk Cloud', 'Splunk Enterprise',
    'Splunk Enterprise Security', 'Splunk Instance', 'Splunk IT Service Intelligence',
    'ITSI Server', 'Summaries', 'Summary', 'System', 'Systems', 'Table Dataset', 'Tag',
    'Third Party App', 'Time', 'UBA Server', 'User', 'Users', 'Value', 'Virtual Index',
    'Web Interface', 'Behavior Analytics', 'Master Cluster', 'Search Pool',
    'JS', 'HTML', 'CSS',
]

KEEP_BARE = {'js', 'html', 'css', 'sdk'}
KEEP_SUBSTRINGS = ('custom visualization', 'simple xml', 'panels html')

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
    (r'\bdatastores\b', 'datastore'),
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
    known_clean = [clean_ocr(t) for t in KNOWN_TITLES]
    for title, kc in zip(KNOWN_TITLES, known_clean):
        if kc == cleaned:
            return title
    matches = difflib.get_close_matches(cleaned, known_clean, n=1, cutoff=cutoff)
    if matches:
        return KNOWN_TITLES[known_clean.index(matches[0])]
    for title, kc in sorted(zip(KNOWN_TITLES, known_clean), key=lambda x: -len(x[0])):
        if len(kc) >= 5 and (kc in cleaned or cleaned in kc):
            return title
    if len(cleaned) >= 3 and not is_bare_letter(cleaned):
        return cleaned.title()
    return None


def step_labels(ocr_results: list[dict], manifest: list[dict]) -> list[dict]:
    """Fuzzy-match OCR text to titles; write labels_final.json."""
    labels_final = []
    labels_dropped = []

    for entry in ocr_results:
        raw = entry['raw_ocr']
        if raw and is_bare_letter(raw):
            labels_dropped.append({**entry, 'reason': 'bare_letter'})
            continue
        title = fuzzy_title(raw) if raw else None
        if title is None:
            title = f"Splunk Icon {entry['id'] + 1:03d}"
        meta = manifest[entry['id']]
        labels_final.append({
            'id': entry['id'],
            'raw_ocr': raw,
            'title': title,
            'file': meta['file'],
            'dominant_color': meta.get('dominant_color'),
            'color_name': meta.get('color_name'),
            'palette': meta.get('palette'),
        })

    (DIST_DIR / 'labels_final.json').write_text(json.dumps(labels_final, indent=2))
    (DIST_DIR / 'labels_dropped.json').write_text(json.dumps(labels_dropped, indent=2))
    named = sum(1 for x in labels_final if not x['title'].startswith('Splunk Icon'))
    log.info('Label filter: kept %d (%d OCR-named), dropped %d', len(labels_final), named, len(labels_dropped))
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

        if item['file'] == SVG_PROTOTYPE_CROP:
            svg_color = vectorize_crop(crop, mode='color', width=w, height=h)
            proto_dir = DIST_DIR / 'prototypes'
            proto_dir.mkdir(exist_ok=True)
            (proto_dir / 'indexer_icon_072.svg').write_text(svg_color, encoding='utf-8')
            stencil_xml = svg_to_stencil(svg_trace, name=item['title'])
            (proto_dir / 'indexer_icon_072.stencil.xml').write_text(stencil_xml, encoding='utf-8')
            (proto_dir / 'indexer_icon_072.stencil.svg').write_text(
                stencil_preview_svg(stencil_xml), encoding='utf-8',
            )
            sample_model = decode_mx(configurable_shapes[-1]['xml'])
            sample_model = sample_model.replace(
                'hostname="" ip="" notes=""',
                'hostname="idx1.example.com" ip="10.0.0.12" notes="cluster=prod"',
            )
            sample_model = sample_model.replace(
                '<mxGeometry ',
                '<mxGeometry x="80" y="40" ',
                1,
            )
            (proto_dir / 'configurable-indexer.drawio').write_text(
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<mxfile host="app.diagrams.net">\n'
                '<diagram name="Configurable Indexer" id="indexer">\n'
                f'{sample_model}\n'
                '</diagram>\n'
                '</mxfile>\n',
                encoding='utf-8',
            )
            color_shapes.append(
                image_entry(SVG_PROTOTYPE_TITLE, w, h, svg_data_uri(svg_color)),
            )
            log.info('Added SVG prototype library entry: %s', SVG_PROTOTYPE_TITLE)

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
    ocr_results = run_ocr_pass(sheet, manifest)
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
        choices=('all', 'crops', 'ocr', 'labels', 'build'),
        help='pipeline step (default: all)',
        nargs='?',
        default='all',
    )
    args = parser.parse_args(argv)

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
        ocr_results = _load_json(DIST_DIR / 'labels_ocr.json')
        step_labels(ocr_results, manifest)
        return 0

    labels_final = _load_json(DIST_DIR / 'labels_final.json')
    connectors = _load_json(DIST_DIR / 'connectors.json')
    step_build(labels_final, connectors)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
