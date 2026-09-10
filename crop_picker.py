#!/usr/bin/env python3
"""Draw rectangles on the source icon sheet to save custom crops.

Usage:
  python crop_picker.py    # http://127.0.0.1:8766
"""
from __future__ import annotations

import json
import mimetypes
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image

Image.MAX_IMAGE_PIXELS = None

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'source' / 'Splunk_Documentation_Icons_August2018.png'
DIST = ROOT / 'dist'
CUSTOM_DIR = DIST / 'custom_crops'
MANIFEST = DIST / 'custom_crops.json'
PORT = 8766

PAGE = """<!doctype html>
<meta charset=utf-8>
<meta name="color-scheme" content="light">
<title>Custom icon crops</title>
<style>
  :root{color-scheme:light}
  *{box-sizing:border-box} body{font:14px/1.4 system-ui,sans-serif;margin:0;background:#f5f5f5;color:#222}
  header{padding:10px 12px;background:#fff;border-bottom:1px solid #ddd;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
  input,button{padding:6px 10px;border:1px solid #ccc;border-radius:6px;background:#fff;color:#222}
  button.primary{background:#007098;border-color:#007098;color:#fff;cursor:pointer}
  button{cursor:pointer}
  .layout{display:flex;height:calc(100vh - 52px)}
  .main{flex:1;overflow:auto;padding:16px;background:#fafafa}
  .aside{width:280px;border-left:1px solid #ddd;background:#fff;overflow:auto;padding:8px}
  .wrap{position:relative;display:inline-block;line-height:0;background:#fff;padding:8px;border:1px solid #ddd;border-radius:4px;box-shadow:0 1px 3px rgba(0,0,0,.06)}
  #sheet{display:block;max-width:none;user-select:none;-webkit-user-drag:none}
  #sel{position:absolute;border:2px solid #007098;background:rgba(0,112,152,.15);pointer-events:none;display:none}
  .hint{font-size:12px;color:#666}
  .crop-item{display:flex;gap:8px;padding:6px;border-bottom:1px solid #eee;font-size:12px;align-items:center}
  .crop-item img{width:40px;height:40px;object-fit:contain;background:#fafafa;border:1px solid #eee}
  .crop-item button{font-size:11px;padding:2px 6px}
  #status{font-size:12px;color:#0a7}
</style>
<header>
  <strong>Custom crops</strong>
  <span class=hint>Full resolution · drag to select · scroll to pan (first load may take a moment)</span>
  <input id=title placeholder="Title (optional)" style="min-width:160px">
  <button class=primary id=saveCrop disabled>Save crop</button>
  <span id=coords class=hint></span>
  <span id=status></span>
</header>
<div class=layout>
  <div class=main id=main>
    <div class=wrap id=wrap>
      <img id=sheet alt="source sheet">
      <div id=sel></div>
    </div>
  </div>
  <aside><strong>Saved</strong><div id=list></div></aside>
</div>
<script>
let meta=null, drag=null, rect=null;
const sheet=document.getElementById('sheet'), sel=document.getElementById('sel'), wrap=document.getElementById('wrap');

function imgPt(clientX, clientY){
  const r=sheet.getBoundingClientRect();
  const x=(clientX-r.left)/r.width*sheet.naturalWidth;
  const y=(clientY-r.top)/r.height*sheet.naturalHeight;
  return [Math.max(0,Math.min(sheet.naturalWidth,x)), Math.max(0,Math.min(sheet.naturalHeight,y))];
}
function toSource(px, py){
  return [Math.round(px), Math.round(py)];
}
function showRect(a,b){
  const x0=Math.min(a[0],b[0]), y0=Math.min(a[1],b[1]), x1=Math.max(a[0],b[0]), y1=Math.max(a[1],b[1]);
  const r=sheet.getBoundingClientRect();
  const sx=r.width/sheet.naturalWidth, sy=r.height/sheet.naturalHeight;
  sel.style.display='block';
  sel.style.left=(x0*sx)+'px'; sel.style.top=(y0*sy)+'px';
  sel.style.width=((x1-x0)*sx)+'px'; sel.style.height=((y1-y0)*sy)+'px';
  rect={x0,y0,x1,y1};
  const [sx0,sy0]=toSource(x0,y0), [sx1,sy1]=toSource(x1,y1);
  document.getElementById('coords').textContent=`${Math.round(x1-x0)}×${Math.round(y1-y0)} px · [${sx0},${sy0},${sx1},${sy1}]`;
  document.getElementById('saveCrop').disabled=(x1-x0)<4||(y1-y0)<4;
}
sheet.onmousedown=e=>{if(e.button!==0)return; drag=imgPt(e.clientX,e.clientY); rect=null; showRect(drag,drag); e.preventDefault();};
window.onmousemove=e=>{if(!drag)return; showRect(drag, imgPt(e.clientX,e.clientY));};
window.onmouseup=()=>{drag=null;};

async function loadMeta(){
  meta=await fetch('/api/meta').then(r=>r.json());
  sheet.src='/sheet?'+Date.now();
  document.getElementById('status').textContent='Loading full PNG…';
  document.getElementById('status').style.color='#666';
  await sheet.decode();
  document.getElementById('status').textContent='Ready';
  document.getElementById('status').style.color='#0a7';
  loadList();
}
async function loadList(){
  const items=await fetch('/api/crops').then(r=>r.json());
  const el=document.getElementById('list');
  el.innerHTML='';
  for(const c of items.slice().reverse()){
    const d=document.createElement('div');
    d.className='crop-item';
    d.innerHTML=`<img src="/custom/${c.file}?t=${Date.now()}" alt="">
      <div style="flex:1;min-width:0"><div>${esc(c.title||c.file)}</div>
      <div style="color:#888">${c.w}×${c.h}</div></div>
      <button type=button data-id="${c.id}">Del</button>`;
    d.querySelector('button').onclick=async()=>{
      await fetch('/api/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:c.id})});
      loadList();
    };
    el.appendChild(d);
  }
}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;');}
document.getElementById('saveCrop').onclick=async()=>{
  if(!rect)return;
  const [sx0,sy0]=toSource(rect.x0,rect.y0), [sx1,sy1]=toSource(rect.x1,rect.y1);
  const title=document.getElementById('title').value.trim();
  const r=await fetch('/api/crop',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({x0:sx0,y0:sy0,x1:sx1,y1:sy1,title})});
  const j=await r.json();
  document.getElementById('status').textContent=j.ok?'Saved '+j.file:(j.error||'failed');
  document.getElementById('status').style.color=j.ok?'#0a7':'#c00';
  if(j.ok){document.getElementById('title').value=''; sel.style.display='none'; rect=null; loadList();}
};
loadMeta();
</script>
"""


def sheet_meta() -> dict:
    CUSTOM_DIR.mkdir(parents=True, exist_ok=True)
    if not SOURCE.is_file():
        raise FileNotFoundError(SOURCE)
    with Image.open(SOURCE) as img:
        w, h = img.size
    return {'source_w': w, 'source_h': h, 'full_resolution': True}


def load_manifest() -> list[dict]:
    if MANIFEST.is_file():
        return json.loads(MANIFEST.read_text())
    return []


def save_manifest(items: list[dict]) -> None:
    MANIFEST.write_text(json.dumps(items, indent=2))


def next_crop_id(items: list[dict]) -> int:
    return max((int(x['id']) for x in items), default=-1) + 1


class Handler(BaseHTTPRequestHandler):
    def log_message(self, _fmt, *_args) -> None:
        pass

    def _json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path, ctype: str | None = None) -> None:
        data = path.read_bytes()
        ctype = ctype or mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if path == '/':
            body = PAGE.encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == '/api/meta':
            self._json(200, sheet_meta())
            return
        if path == '/sheet':
            self._file(SOURCE, 'image/png')
            return
        if path == '/api/crops':
            self._json(200, load_manifest())
            return
        if path.startswith('/custom/'):
            f = CUSTOM_DIR / Path(path).name
            if f.is_file():
                self._file(f)
            else:
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

        if self.path == '/api/crop':
            try:
                x0, y0, x1, y1 = int(body['x0']), int(body['y0']), int(body['x1']), int(body['y1'])
            except (KeyError, TypeError, ValueError):
                self._json(400, {'ok': False, 'error': 'need x0,y0,x1,y1'})
                return
            if x1 <= x0 or y1 <= y0:
                self._json(400, {'ok': False, 'error': 'empty rectangle'})
                return
            title = (body.get('title') or '').strip()
            with Image.open(SOURCE) as img:
                w, h = img.size
                x0, y0 = max(0, min(x0, w - 1)), max(0, min(y0, h - 1))
                x1, y1 = max(x0 + 1, min(x1, w)), max(y0 + 1, min(y1, h))
                crop = img.crop((x0, y0, x1, y1))
            items = load_manifest()
            cid = next_crop_id(items)
            fname = f'custom_{cid:03d}.png'
            crop.save(CUSTOM_DIR / fname)
            entry = {
                'id': cid,
                'file': fname,
                'title': title or f'Custom {cid + 1:03d}',
                'x0': x0,
                'y0': y0,
                'x1': x1,
                'y1': y1,
                'w': x1 - x0,
                'h': y1 - y1,
            }
            items.append(entry)
            save_manifest(items)
            self._json(200, {'ok': True, 'file': fname, 'entry': entry})
            return

        if self.path == '/api/delete':
            cid = body.get('id')
            items = load_manifest()
            kept, removed = [], None
            for item in items:
                if item['id'] == cid:
                    removed = item
                else:
                    kept.append(item)
            if removed:
                f = CUSTOM_DIR / removed['file']
                if f.is_file():
                    f.unlink()
            save_manifest(kept)
            self._json(200, {'ok': True})
            return

        self.send_error(404)


def main() -> None:
    if not SOURCE.is_file():
        sys.exit(f'Missing source PNG: {SOURCE}')
    host = '127.0.0.1'
    httpd = ThreadingHTTPServer((host, PORT), Handler)
    print(f'Crop picker: http://{host}:{PORT}  (Ctrl+C to stop)')
    print(f'Crops → {CUSTOM_DIR}')
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped.')


if __name__ == '__main__':
    main()
