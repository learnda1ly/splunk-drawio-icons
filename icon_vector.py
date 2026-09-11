"""PNG crop → SVG paths (VTracer, one image at a time)."""

from __future__ import annotations

import io
import re
from typing import Literal

import numpy as np
import vtracer
from PIL import Image

TraceMode = Literal['color', 'adaptive']

_VTRACER = dict(
    hierarchical='stacked',
    mode='polygon',
    filter_speckle=4,
    corner_threshold=60,
    length_threshold=4.0,
    max_iterations=10,
    splice_threshold=45,
    path_precision=2,
)


def _png_bytes_for_trace(crop: Image.Image, *, adaptive: bool) -> bytes:
    """PNG for VTracer: RGBA (transparent) for color; black-on-white for adaptive binary."""
    buf = io.BytesIO()
    if not adaptive:
        crop.convert('RGBA').save(buf, format='PNG')
        return buf.getvalue()
    rgba = np.array(crop.convert('RGBA'))
    alpha = rgba[:, :, 3]
    rgb = np.full(rgba.shape[:2] + (3,), 255, dtype=np.uint8)
    rgb[alpha > 32] = 0
    Image.fromarray(rgb, 'RGB').save(buf, format='PNG')
    return buf.getvalue()


def _drop_background_paths(svg_inner: str, vw: int, vh: int) -> str:
    """Remove full-canvas white fills VTracer sometimes emits on flattened inputs."""
    if vw <= 0 or vh <= 0:
        return svg_inner
    area = vw * vh
    parts = re.split(r'(?=<path\b)', svg_inner)
    kept = [parts[0]] if parts else []
    frame_re = re.compile(
        rf'<path\b[^>]*\bd="[^"]*M0,0 L{vw},0 L{vw},{vh} L0,{vh} Z[^"]*"[^>]*fill="#(?:FFF|FFFFFF|fefefe|FEFEFE)"',
        re.I,
    )
    for chunk in parts[1:]:
        if not chunk.startswith('path'):
            kept.append(chunk)
            continue
        m = re.search(r'\bfill="(#[0-9A-Fa-f]{3,8})"', chunk)
        fill = m.group(1).lower() if m else ''
        if fill in ('#fff', '#ffffff', '#fefefe') and frame_re.search(chunk[:400]):
            continue
        kept.append('<' + chunk if not chunk.startswith('<') else chunk)
    out = ''.join(kept)
    return out if out.strip() else svg_inner


def _normalize_svg(raw: str, display_w: int, display_h: int, *, adaptive: bool) -> str:
    raw = re.sub(r'<\?xml[^>]*\?>\s*', '', raw)
    raw = re.sub(r'<!--.*?-->\s*', '', raw, flags=re.DOTALL).strip()
    open_tag = re.search(r'<svg\b([^>]*)>', raw, flags=re.DOTALL)
    if not open_tag:
        return raw
    attrs = open_tag.group(1)
    w_m = re.search(r'\bwidth="([\d.]+)"', attrs)
    h_m = re.search(r'\bheight="([\d.]+)"', attrs)
    vw = int(float(w_m.group(1))) if w_m else display_w
    vh = int(float(h_m.group(1))) if h_m else display_h
    inner = raw[open_tag.end() : raw.rfind('</svg>')].strip()
    if not adaptive:
        inner = _drop_background_paths(inner, vw, vh)
    if adaptive:
        fill = 'var(--icon-color, light-dark(#111111, #ffffff))'
        inner = re.sub(r'\sfill="[^"]*"', f' fill="{fill}"', inner)
        inner = re.sub(
            r'(<path\b(?![^>]*\bfill=)[^>]*)(/?>)',
            rf'\1 fill="{fill}"\2',
            inner,
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{display_w}" height="{display_h}" '
        f'viewBox="0 0 {vw} {vh}">{inner}</svg>'
    )


def vectorize_crop(
    crop: Image.Image,
    *,
    mode: TraceMode,
    width: int,
    height: int,
) -> str:
    """Trace one RGBA crop to an SVG string."""
    adaptive = mode == 'adaptive'
    png_bytes = _png_bytes_for_trace(crop, adaptive=adaptive)
    raw = vtracer.convert_raw_image_to_svg(
        png_bytes,
        img_format='png',
        colormode='binary' if adaptive else 'color',
        color_precision=8 if not adaptive else None,
        layer_difference=16 if not adaptive else None,
        **_VTRACER,
    )
    return _normalize_svg(raw, width, height, adaptive=adaptive)
