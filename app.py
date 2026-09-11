#!/usr/bin/env python3
"""Single local workbench: tutorial, label editor, and custom crops.

Usage:
  python app.py              # http://127.0.0.1:8765
"""
from __future__ import annotations

import json
import mimetypes
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image

Image.MAX_IMAGE_PIXELS = None

ROOT = Path(__file__).resolve().parent
WEB = ROOT / 'web'
DIST = ROOT / 'dist'
SOURCE = ROOT / 'source' / 'Splunk_Documentation_Icons_August2018.png'
LABELS = DIST / 'labels_final.json'
CUSTOM = DIST / 'custom_crops.json'
CROPS = DIST / 'crops'
CUSTOM_CROPS = DIST / 'custom_crops'
PORT = 8765

LIBRARIES = (
    'Splunk-Icons-configurable.xml',
    'Splunk-Icons-adaptive.xml',
    'Splunk-Icons-color.xml',
    'Splunk-Icons-dark.xml',
    'Splunk-Connectors.xml',
)


def load_all_labels() -> list[dict]:
    labels = json.loads(LABELS.read_text()) if LABELS.is_file() else []
    if not CUSTOM.is_file():
        return labels

    def rect(item: dict):
        if all(k in item for k in ('x0', 'y0', 'x1', 'y1')):
            return item['x0'], item['y0'], item['x1'], item['y1']
        if all(k in item for k in ('x', 'y', 'w', 'h')):
            return item['x'], item['y'], item['x'] + item['w'], item['y'] + item['h']
        return None

    def iou(a, b) -> float:
        ax0, ay0, ax1, ay1 = a
        bx0, by0, bx1, by1 = b
        ix0, iy0 = max(ax0, bx0), max(ay0, by0)
        ix1, iy1 = min(ax1, bx1), min(ay1, by1)
        inter = max(0, ix1 - ix0) * max(0, iy1 - iy0)
        union = max(0, ax1 - ax0) * max(0, ay1 - ay0) + max(0, bx1 - bx0) * max(0, by1 - by0) - inter
        return inter / union if union else 0.0

    auto_rects = [r for r in (rect(x) for x in labels) if r]
    for entry in json.loads(CUSTOM.read_text()):
        crect = rect(entry)
        if crect and any(iou(crect, a) >= 0.35 for a in auto_rects):
            continue
        labels.append({
            'id': f"custom_{entry.get('id', entry['file'])}",
            'custom_id': entry.get('id'),
            'custom': True,
            'file': entry['file'],
            'title': entry.get('title') or entry['file'],
            'raw_ocr': '',
            'complete': entry.get('complete', False),
        })
    return labels


def save_all_labels(all_labels: list[dict]) -> None:
    existing = (
        {e['file']: e for e in json.loads(CUSTOM.read_text())}
        if CUSTOM.is_file()
        else {}
    )
    auto, custom = [], []
    for row in all_labels:
        if row.get('custom'):
            base = existing.get(row['file'], {})
            custom.append({
                **base,
                'id': row.get('custom_id', base.get('id', 0)),
                'file': row['file'],
                'title': row.get('title') or row['file'],
                'complete': row.get('complete', False),
            })
        else:
            auto.append({k: v for k, v in row.items() if k != 'custom'})
    LABELS.write_text(json.dumps(auto, indent=2))
    if custom:
        CUSTOM.write_text(json.dumps(custom, indent=2))
    elif CUSTOM.is_file():
        CUSTOM.unlink()


def load_custom_manifest() -> list[dict]:
    if CUSTOM.is_file():
        return json.loads(CUSTOM.read_text())
    return []


def save_custom_manifest(items: list[dict]) -> None:
    CUSTOM_CROPS.mkdir(parents=True, exist_ok=True)
    CUSTOM.write_text(json.dumps(items, indent=2))


def next_crop_id(items: list[dict]) -> int:
    return max((int(x['id']) for x in items), default=-1) + 1


def rebuild_libraries() -> None:
    from splunk_icons_pipeline import step_build

    if not LABELS.is_file():
        raise FileNotFoundError(f'Missing {LABELS} — run: uv run python run_pipeline.py all')
    connectors = json.loads((DIST / 'connectors.json').read_text()) if (DIST / 'connectors.json').is_file() else []
    step_build(json.loads(LABELS.read_text()), connectors)


def api_status() -> dict:
    return {
        'source': SOURCE.is_file(),
        'catalog': (ROOT / 'canonical_titles.json').is_file(),
        'labels': LABELS.is_file(),
        'custom_crops': CUSTOM.is_file(),
        'libraries': {name: (DIST / name).is_file() for name in LIBRARIES},
    }


def safe_file(base: Path, name: str) -> Path | None:
    path = (base / Path(name).name).resolve()
    try:
        path.relative_to(base.resolve())
    except ValueError:
        return None
    return path if path.is_file() else None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, _fmt, *_args) -> None:
        pass

    def _json(self, code: int, obj) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _bytes(self, data: bytes, ctype: str) -> None:
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, path: Path, ctype: str | None = None) -> None:
        self._bytes(path.read_bytes(), ctype or mimetypes.guess_type(path.name)[0] or 'application/octet-stream')

    def do_GET(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if path in ('/', '/index.html'):
            self._send_file(WEB / 'index.html', 'text/html; charset=utf-8')
            return
        if path in ('/app.css', '/app.js'):
            f = WEB / path.lstrip('/')
            if f.is_file():
                ctype = 'text/css' if path.endswith('.css') else 'text/javascript; charset=utf-8'
                self._send_file(f, ctype)
                return
        if path == '/api/status':
            self._json(200, api_status())
            return
        if path == '/api/labels':
            self._json(200, load_all_labels())
            return
        if path == '/api/meta':
            if not SOURCE.is_file():
                self._json(404, {'ok': False, 'error': f'Missing {SOURCE.name}'})
                return
            with Image.open(SOURCE) as img:
                w, h = img.size
            self._json(200, {'source_w': w, 'source_h': h, 'full_resolution': True})
            return
        if path == '/api/crops':
            self._json(200, load_custom_manifest())
            return
        if path == '/sheet':
            if not SOURCE.is_file():
                self.send_error(404)
                return
            self._send_file(SOURCE, 'image/png')
            return
        if path.startswith('/crops/'):
            f = safe_file(CROPS, Path(path).name)
            if f:
                self._send_file(f)
                return
            self.send_error(404)
            return
        if path.startswith('/custom/'):
            f = safe_file(CUSTOM_CROPS, Path(path).name)
            if f:
                self._send_file(f)
                return
            self.send_error(404)
            return
        if path.startswith('/libraries/'):
            f = safe_file(DIST, Path(path).name)
            if f and f.name in LIBRARIES:
                self._send_file(f, 'application/xml')
                return
            self.send_error(404)
            return
        self.send_error(404)

    def do_POST(self) -> None:
        n = int(self.headers.get('Content-Length', 0))
        raw = self.rfile.read(n) if n else b'{}'
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            self._json(400, {'ok': False, 'error': 'invalid json'})
            return
        path = urllib.parse.urlparse(self.path).path

        if path == '/api/save':
            labels = body.get('labels')
            if not isinstance(labels, list):
                self._json(400, {'ok': False, 'error': 'labels must be a list'})
                return
            save_all_labels(labels)
            self._json(200, {'ok': True})
            return

        if path == '/api/rebuild':
            try:
                rebuild_libraries()
                self._json(200, {'ok': True})
            except Exception as exc:  # noqa: BLE001 — surface rebuild errors to UI
                self._json(500, {'ok': False, 'error': str(exc)})
            return

        if path == '/api/crop':
            if not SOURCE.is_file():
                self._json(404, {'ok': False, 'error': f'Missing {SOURCE.name}'})
                return
            try:
                x0, y0, x1, y1 = int(body['x0']), int(body['y0']), int(body['x1']), int(body['y1'])
            except (KeyError, TypeError, ValueError):
                self._json(400, {'ok': False, 'error': 'need x0,y0,x1,y1'})
                return
            if x1 <= x0 or y1 <= y0:
                self._json(400, {'ok': False, 'error': 'empty rectangle'})
                return
            title = (body.get('title') or '').strip()
            CUSTOM_CROPS.mkdir(parents=True, exist_ok=True)
            with Image.open(SOURCE) as img:
                w, h = img.size
                x0, y0 = max(0, min(x0, w - 1)), max(0, min(y0, h - 1))
                x1, y1 = max(x0 + 1, min(x1, w)), max(y0 + 1, min(y1, h))
                crop = img.crop((x0, y0, x1, y1))
            items = load_custom_manifest()
            cid = next_crop_id(items)
            fname = f'custom_{cid:03d}.png'
            crop.save(CUSTOM_CROPS / fname)
            entry = {
                'id': cid,
                'file': fname,
                'title': title or f'Custom {cid + 1:03d}',
                'x0': x0,
                'y0': y0,
                'x1': x1,
                'y1': y1,
                'w': x1 - x0,
                'h': y1 - y0,
                'complete': False,
            }
            items.append(entry)
            save_custom_manifest(items)
            self._json(200, {'ok': True, 'file': fname, 'entry': entry})
            return

        if path == '/api/delete':
            cid = body.get('id')
            items = load_custom_manifest()
            kept, removed = [], None
            for item in items:
                if item['id'] == cid:
                    removed = item
                else:
                    kept.append(item)
            if removed:
                f = CUSTOM_CROPS / removed['file']
                if f.is_file():
                    f.unlink()
            save_custom_manifest(kept)
            self._json(200, {'ok': True})
            return

        self.send_error(404)


def main() -> None:
    if not (WEB / 'index.html').is_file():
        raise SystemExit(f'Missing {WEB / "index.html"}')
    host = '127.0.0.1'
    httpd = ThreadingHTTPServer((host, PORT), Handler)
    print(f'Workbench: http://{host}:{PORT}  (Ctrl+C to stop)', flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped.')


if __name__ == '__main__':
    main()
