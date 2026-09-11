"""SVG path data → draw.io native stencil (fill/stroke + custom properties)."""

from __future__ import annotations

import re
from xml.etree import ElementTree as ET

# VTracer emits M/L/Z plus translate(); keep the parser general enough for H/V/C/Q.
_NUM = r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?'
_CMD = set('MmLlHhVvCcSsQqTtAaZz')


def _fmt(n: float) -> str:
    n = round(float(n), 2)
    if abs(n - round(n)) < 0.005:
        return str(int(round(n)))
    return f'{n:.2f}'.rstrip('0').rstrip('.')


def _tokenize_path(d: str) -> list[tuple[str, float | None]]:
    tokens: list[tuple[str, float | None]] = []
    i, n = 0, len(d)
    while i < n:
        ch = d[i]
        if ch.isspace() or ch == ',':
            i += 1
            continue
        if ch in _CMD:
            tokens.append(('cmd', ch))
            i += 1
            continue
        m = re.match(_NUM, d[i:])
        if m:
            tokens.append(('num', float(m.group(0))))
            i += m.end()
            continue
        i += 1
    return tokens


def _parse_translate(transform: str | None) -> tuple[float, float]:
    if not transform:
        return 0.0, 0.0
    m = re.search(
        rf'translate\(\s*({_NUM})(?:[,\s]+({_NUM}))?\s*\)',
        transform,
    )
    if not m:
        return 0.0, 0.0
    tx = float(m.group(1))
    ty = float(m.group(2)) if m.group(2) is not None else 0.0
    return tx, ty


def path_d_to_stencil_elements(d: str, tx: float = 0.0, ty: float = 0.0) -> list[str]:
    """Convert one SVG path `d` to draw.io stencil path children (absolute coords)."""
    tokens = _tokenize_path(d)
    out: list[str] = []
    i = 0
    cx = cy = 0.0
    sx = sy = 0.0
    last_cmd = ''

    def take(count: int) -> list[float]:
        nonlocal i
        nums: list[float] = []
        while len(nums) < count and i < len(tokens) and tokens[i][0] == 'num':
            nums.append(tokens[i][1])  # type: ignore[arg-type]
            i += 1
        return nums

    def abs_pt(x: float, y: float, *, relative: bool) -> tuple[float, float]:
        if relative:
            x += cx
            y += cy
        return x + tx, y + ty

    while i < len(tokens):
        kind, val = tokens[i]
        if kind == 'cmd':
            cmd = val  # type: ignore[assignment]
            i += 1
        elif last_cmd:
            cmd = 'L' if last_cmd in 'Mm' else last_cmd
        else:
            i += 1
            continue
        last_cmd = cmd
        rel = cmd.islower()
        op = cmd.upper()

        if op == 'Z':
            out.append('<close/>')
            cx, cy = sx, sy
            continue

        if op == 'M':
            nums = take(2)
            if len(nums) < 2:
                break
            x, y = abs_pt(nums[0], nums[1], relative=rel)
            out.append(f'<move x="{_fmt(x)}" y="{_fmt(y)}"/>')
            cx, cy = x - tx, y - ty
            sx, sy = cx, cy
            last_cmd = 'l' if rel else 'L'
            continue

        if op == 'L':
            nums = take(2)
            if len(nums) < 2:
                break
            x, y = abs_pt(nums[0], nums[1], relative=rel)
            out.append(f'<line x="{_fmt(x)}" y="{_fmt(y)}"/>')
            cx, cy = x - tx, y - ty
            continue

        if op == 'H':
            nums = take(1)
            if not nums:
                break
            x = (cx + nums[0]) if rel else nums[0]
            x, y = x + tx, cy + ty
            out.append(f'<line x="{_fmt(x)}" y="{_fmt(y)}"/>')
            cx = x - tx
            continue

        if op == 'V':
            nums = take(1)
            if not nums:
                break
            y = (cy + nums[0]) if rel else nums[0]
            x, y = cx + tx, y + ty
            out.append(f'<line x="{_fmt(x)}" y="{_fmt(y)}"/>')
            cy = y - ty
            continue

        if op == 'C':
            nums = take(6)
            if len(nums) < 6:
                break
            x1, y1 = abs_pt(nums[0], nums[1], relative=rel)
            x2, y2 = abs_pt(nums[2], nums[3], relative=rel)
            x3, y3 = abs_pt(nums[4], nums[5], relative=rel)
            out.append(
                f'<curve x1="{_fmt(x1)}" y1="{_fmt(y1)}" '
                f'x2="{_fmt(x2)}" y2="{_fmt(y2)}" '
                f'x3="{_fmt(x3)}" y3="{_fmt(y3)}"/>'
            )
            cx, cy = x3 - tx, y3 - ty
            continue

        if op == 'Q':
            nums = take(4)
            if len(nums) < 4:
                break
            x1, y1 = abs_pt(nums[0], nums[1], relative=rel)
            x, y = abs_pt(nums[2], nums[3], relative=rel)
            out.append(
                f'<quad x1="{_fmt(x1)}" y1="{_fmt(y1)}" x2="{_fmt(x)}" y2="{_fmt(y)}"/>'
            )
            cx, cy = x - tx, y - ty
            continue

        # Skip unsupported (S/T/A) argument blobs so the rest of the path can continue.
        if op == 'S':
            take(4)
        elif op == 'T':
            take(2)
        elif op == 'A':
            take(7)
        else:
            i += 1

    return out


def _svg_paths(svg: str) -> list[tuple[str, str | None]]:
    svg = re.sub(r'\sxmlns="[^"]*"', '', svg, count=1)
    root = ET.fromstring(svg)
    found: list[tuple[str, str | None]] = []
    for el in root.iter():
        tag = el.tag.split('}')[-1]
        if tag != 'path':
            continue
        d = el.get('d')
        if d:
            found.append((d, el.get('transform')))
    return found


def svg_to_stencil(svg: str, *, name: str = 'icon') -> str:
    """Build a draw.io <shape> stencil from a VTracer SVG (silhouette)."""
    view = re.search(r'\bviewBox="0 0 ([\d.]+) ([\d.]+)"', svg)
    if view:
        vw, vh = float(view.group(1)), float(view.group(2))
    else:
        wm = re.search(r'\bwidth="([\d.]+)"', svg)
        hm = re.search(r'\bheight="([\d.]+)"', svg)
        vw = float(wm.group(1)) if wm else 100.0
        vh = float(hm.group(1)) if hm else 100.0

    chunks: list[str] = []
    for d, transform in _svg_paths(svg):
        tx, ty = _parse_translate(transform)
        els = path_d_to_stencil_elements(d, tx, ty)
        if not els:
            continue
        chunks.append('<path>')
        chunks.extend(els)
        chunks.append('</path>')
        chunks.append('<fillstroke/>')

    if not chunks:
        chunks = [
            '<path>',
            f'<move x="0" y="0"/>',
            f'<line x="{_fmt(vw)}" y="0"/>',
            f'<line x="{_fmt(vw)}" y="{_fmt(vh)}"/>',
            f'<line x="0" y="{_fmt(vh)}"/>',
            '<close/>',
            '</path>',
            '<fillstroke/>',
        ]

    safe_name = name.replace('"', "'")
    return (
        f'<shape name="{safe_name}" h="{_fmt(vh)}" w="{_fmt(vw)}" '
        f'aspect="variable" strokewidth="inherit">'
        '<connections>'
        '<constraint x="0.5" y="0" perimeter="0" name="N"/>'
        '<constraint x="1" y="0.5" perimeter="0" name="E"/>'
        '<constraint x="0.5" y="1" perimeter="0" name="S"/>'
        '<constraint x="0" y="0.5" perimeter="0" name="W"/>'
        '</connections>'
        '<foreground>'
        + ''.join(chunks)
        + '</foreground>'
        '</shape>'
    )


def stencil_preview_svg(stencil_xml: str) -> str:
    """Rebuild a simple SVG from stencil path commands (sanity check)."""
    wm = re.search(r'\bw="([\d.]+)"', stencil_xml)
    hm = re.search(r'\bh="([\d.]+)"', stencil_xml)
    vw = wm.group(1) if wm else '100'
    vh = hm.group(1) if hm else '100'
    parts: list[str] = []
    for path in re.findall(r'<path>(.*?)</path>', stencil_xml, flags=re.DOTALL):
        cmds: list[str] = []
        for el in re.finditer(r'<(\w+)([^/]*)/>', path):
            tag, attrs = el.group(1), el.group(2)
            nums = dict(re.findall(r'(\w+)="([\d.-]+)"', attrs))
            if tag == 'move':
                cmds.append(f"M{nums.get('x', '0')},{nums.get('y', '0')}")
            elif tag == 'line':
                cmds.append(f"L{nums.get('x', '0')},{nums.get('y', '0')}")
            elif tag == 'curve':
                cmds.append(
                    f"C{nums.get('x1')},{nums.get('y1')} "
                    f"{nums.get('x2')},{nums.get('y2')} "
                    f"{nums.get('x3')},{nums.get('y3')}"
                )
            elif tag == 'quad':
                cmds.append(f"Q{nums.get('x1')},{nums.get('y1')} {nums.get('x2')},{nums.get('y2')}")
            elif tag == 'close':
                cmds.append('Z')
        if cmds:
            parts.append(f'<path d="{" ".join(cmds)}" fill="#111" fill-rule="evenodd"/>')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{vw}" height="{vh}" '
        f'viewBox="0 0 {vw} {vh}">{"".join(parts)}</svg>'
    )
