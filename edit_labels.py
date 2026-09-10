#!/usr/bin/env python3
"""Lightweight web UI to edit icon titles in dist/labels_final.json.

Usage:
  python edit_labels.py              # http://127.0.0.1:8765
  python edit_labels.py --rebuild    # rebuild draw.io XML from labels_final.json
"""
from __future__ import annotations

import json
import mimetypes
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / 'dist'
LABELS = DIST / 'labels_final.json'
CUSTOM = DIST / 'custom_crops.json'
CROPS = DIST / 'crops'
CUSTOM_CROPS = DIST / 'custom_crops'
PORT = 8765


def load_all_labels() -> list[dict]:
    labels = json.loads(LABELS.read_text()) if LABELS.is_file() else []
    if not CUSTOM.is_file():
        return labels
    for entry in json.loads(CUSTOM.read_text()):
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

PAGE = """<!doctype html>
<meta charset=utf-8>
<meta name="color-scheme" content="light">
<title>Splunk icon labels</title>
<style>
  :root{color-scheme:light}
  *{box-sizing:border-box} body{font:14px/1.4 system-ui,sans-serif;margin:12px;background:#f5f5f5;color:#222}
  header{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:12px;position:sticky;top:0;background:#f5f5f5;padding:8px 0;z-index:1;border-bottom:1px solid #ddd}
  input,button{padding:6px 10px;border:1px solid #ccc;border-radius:6px;background:#fff;color:#222}
  button{cursor:pointer} button.primary{background:#007098;border-color:#007098;color:#fff}
  #q{min-width:220px} .meta{color:#666;font-size:12px}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:8px}
  .card{display:flex;gap:8px;padding:8px;border:1px solid #ddd;border-radius:8px;background:#fff}
  .card.changed{border-color:#f88018;box-shadow:0 0 0 1px #f88018}
  .card img{width:56px;height:56px;object-fit:contain;background:#fafafa;border:1px solid #eee;border-radius:4px;flex-shrink:0}
  .card input{width:100%;margin-top:4px}
  .card.done{opacity:.55}
  .ocr{font-size:11px;color:#666;word-break:break-word}
  .id{font-size:11px;color:#888;display:flex;justify-content:space-between;align-items:center;gap:4px}
  .done-btn{font-size:11px;padding:2px 8px;border:1px solid #ccc;border-radius:4px;background:#fff;cursor:pointer;white-space:nowrap}
  .done-btn:hover{background:#e8f5e9;border-color:#4caf50}
  .done-btn.undo{color:#666}
  label.show-done{font-size:12px;color:#666;display:flex;align-items:center;gap:4px;cursor:pointer;user-select:none}
  #status{margin-left:auto;color:#0a7}
</style>
<header>
  <strong>Icon labels</strong>
  <input id=q placeholder="Filter…" autofocus>
  <label class=show-done><input type=checkbox id=showDone> Show completed</label>
  <button class=primary id=save>Save</button>
  <button id=rebuild>Rebuild XML</button>
  <span class=meta id=count></span>
  <span id=status></span>
</header>
<div class=grid id=grid></div>
<script>
let labels=[], dirty=new Set();
const grid=document.getElementById('grid'), q=document.getElementById('q'), status=document.getElementById('status');
const showDone=document.getElementById('showDone');

async function load(){
  labels=await fetch('/api/labels').then(r=>r.json());
  for(const row of labels) if(row.complete==null) row.complete=false;
  render();
}
function render(){
  const f=(q.value||'').toLowerCase();
  const show=showDone.checked;
  grid.innerHTML='';
  let n=0, done=0;
  const sorted=[...labels].sort((a,b)=>(a.title||'').localeCompare(b.title||'',undefined,{numeric:true,sensitivity:'base'}));
  for(const row of sorted){
    if(row.complete) done++;
    if(row.complete && !show) continue;
    const hay=(row.title+' '+row.raw_ocr+' '+row.file).toLowerCase();
    if(f && !hay.includes(f)) continue;
    n++;
    const el=document.createElement('div');
    el.className='card'+(dirty.has(row.id)?' changed':'')+(row.complete?' done':'');
    const btn=row.complete
      ? `<button type=button class="done-btn undo" title="Mark incomplete">↩</button>`
      : `<button type=button class="done-btn" title="Mark complete">✓ Done</button>`;
    const imgBase=row.custom?'/custom/':'/crops/';
    const label=row.custom?row.file:`#${Number(row.id)+1} ${row.file}`;
    const sub=row.custom?'Custom crop':('OCR: '+esc(row.raw_ocr||'—'));
    el.innerHTML=`<img src="${imgBase}${row.file}" alt="">
      <div style="flex:1;min-width:0">
        <div class=id><span>${label}</span>${btn}</div>
        <input value="${esc(row.title)}" data-id="${row.id}">
        <div class=ocr>${sub}</div>
      </div>`;
    el.querySelector('input').oninput=e=>{row.title=e.target.value; dirty.add(row.id); el.classList.add('changed'); setStatus('unsaved changes');};
    el.querySelector('.done-btn').onclick=()=>{row.complete=!row.complete; dirty.add(row.id); render(); setStatus('unsaved changes');};
    grid.appendChild(el);
  }
  const left=labels.length-done;
  document.getElementById('count').textContent=left+' left · '+done+' done · '+n+' shown';
}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;');}
function setStatus(msg, ok){status.textContent=msg; status.style.color=ok===false?'#c00':'#0a7';}
q.oninput=render;
showDone.onchange=render;
document.getElementById('save').onclick=async()=>{
  const r=await fetch('/api/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({labels})});
  if(!r.ok){setStatus('save failed',false);return;}
  dirty.clear(); render(); setStatus('saved '+new Date().toLocaleTimeString(),true);
};
document.getElementById('rebuild').onclick=async()=>{
  setStatus('rebuilding…');
  const r=await fetch('/api/rebuild',{method:'POST'});
  const text=await r.text();
  let j;
  try{ j=JSON.parse(text); }catch{
    setStatus('Rebuild returned non-JSON (wrong server/URL?): '+text.slice(0,80), false);
    return;
  }
  setStatus(j.ok?'libraries rebuilt':'rebuild failed: '+(j.error||r.status), j.ok);
};
document.onkeydown=e=>{if((e.ctrlKey||e.metaKey)&&e.key==='s'){e.preventDefault();document.getElementById('save').click();}};
load();
</script>
"""


def rebuild_libraries() -> None:
    from splunk_icons_pipeline import step_build

    labels_final = json.loads(LABELS.read_text())
    connectors = json.loads((DIST / 'connectors.json').read_text())
    step_build(labels_final, connectors)


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
        if path == '/api/labels':
            self._json(200, load_all_labels())
            return
        if path.startswith('/custom/'):
            f = CUSTOM_CROPS / Path(path).name
            if not f.is_file():
                self.send_error(404)
                return
            data = f.read_bytes()
            ctype = mimetypes.guess_type(f.name)[0] or 'application/octet-stream'
            self.send_response(200)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if path.startswith('/crops/'):
            f = CROPS / Path(path).name
            if not f.is_file():
                self.send_error(404)
                return
            data = f.read_bytes()
            ctype = mimetypes.guess_type(f.name)[0] or 'application/octet-stream'
            self.send_response(200)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
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
        if self.path == '/api/save':
            labels = body.get('labels')
            if not isinstance(labels, list):
                self._json(400, {'ok': False, 'error': 'labels must be a list'})
                return
            save_all_labels(labels)
            self._json(200, {'ok': True})
            return
        if self.path == '/api/rebuild':
            try:
                rebuild_libraries()
                self._json(200, {'ok': True})
            except Exception as exc:  # noqa: BLE001 — surface rebuild errors to UI
                self._json(500, {'ok': False, 'error': str(exc)})
            return
        self.send_error(404)


def main() -> None:
    if '--rebuild' in sys.argv:
        rebuild_libraries()
        print('Rebuilt dist/Splunk-Icons-*.xml')
        return
    if not LABELS.is_file():
        sys.exit(f'Missing {LABELS} — run the notebook crop/OCR cells first.')
    host = '127.0.0.1'
    httpd = ThreadingHTTPServer((host, PORT), Handler)
    print(f'Label editor: http://{host}:{PORT}  (Ctrl+C to stop)')
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped.')


if __name__ == '__main__':
    main()
