(() => {
  const stages = [...document.querySelectorAll('.stage')];
  const nav = [...document.querySelectorAll('nav a')];

  function currentStage() {
    const name = (location.hash || '#tutorial').slice(1);
    return stages.some((s) => s.dataset.stage === name) ? name : 'tutorial';
  }

  function showStage(name) {
    stages.forEach((s) => s.classList.toggle('active', s.dataset.stage === name));
    nav.forEach((a) => a.classList.toggle('active', a.dataset.stage === name));
    if (name === 'labels') loadLabels();
    if (name === 'crops') loadCrops();
  }

  window.addEventListener('hashchange', () => showStage(currentStage()));
  showStage(currentStage());

  async function loadStatus() {
    const el = document.getElementById('env-status');
    try {
      const s = await fetch('/api/status').then((r) => r.json());
      const rows = [
        ['Source PNG', s.source, 'source/Splunk_Documentation_Icons_August2018.png'],
        ['Title catalog', s.catalog, 'canonical_titles.json'],
        ['Labels', s.labels, 'dist/labels_final.json'],
      ];
      if (s.custom_crops) {
        rows.push(['Custom crops (extra)', true, 'dist/custom_crops.json']);
      }
      for (const [name, ok] of Object.entries(s.libraries || {})) {
        rows.push([name, ok, `dist/${name}`]);
      }
      el.innerHTML = rows
        .map(([label, ok, path]) =>
          `<li class="${ok ? 'ok' : 'bad'}">${ok ? '✓' : '✗'} ${esc(label)}${ok ? '' : ` — missing ${esc(path)}`}</li>`,
        )
        .join('');
    } catch {
      el.innerHTML = '<li class="bad">Could not read /api/status</li>';
    }
  }
  loadStatus();

  function esc(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/"/g, '&quot;')
      .replace(/</g, '&lt;');
  }

  async function rebuild(statusEl) {
    statusEl.textContent = 'rebuilding…';
    statusEl.style.color = '#666';
    const r = await fetch('/api/rebuild', { method: 'POST' });
    const text = await r.text();
    let j;
    try {
      j = JSON.parse(text);
    } catch {
      statusEl.textContent = 'Rebuild returned non-JSON: ' + text.slice(0, 80);
      statusEl.style.color = '#c00';
      return;
    }
    statusEl.textContent = j.ok ? 'libraries rebuilt' : 'rebuild failed: ' + (j.error || r.status);
    statusEl.style.color = j.ok ? '#0a7' : '#c00';
    if (j.ok) loadStatus();
  }

  /* —— labels —— */
  let labels = [];
  const dirty = new Set();
  let labelsLoaded = false;
  const grid = document.getElementById('grid');
  const q = document.getElementById('q');
  const showDone = document.getElementById('showDone');
  const labelStatus = document.getElementById('labelStatus');
  const labelEmpty = document.getElementById('labelEmpty');

  function setLabelStatus(msg, ok) {
    labelStatus.textContent = msg;
    labelStatus.style.color = ok === false ? '#c00' : '#0a7';
  }

  function renderLabels() {
    const f = (q.value || '').toLowerCase();
    const show = showDone.checked;
    grid.innerHTML = '';
    let n = 0;
    let done = 0;
    const sorted = [...labels].sort((a, b) =>
      (a.title || '').localeCompare(b.title || '', undefined, { numeric: true, sensitivity: 'base' }),
    );
    for (const row of sorted) {
      if (row.complete) done += 1;
      if (row.complete && !show) continue;
      const hay = (row.title + ' ' + row.raw_ocr + ' ' + row.file).toLowerCase();
      if (f && !hay.includes(f)) continue;
      n += 1;
      const el = document.createElement('div');
      el.className = 'card' + (dirty.has(row.id) ? ' changed' : '') + (row.complete ? ' done' : '');
      const btn = row.complete
        ? '<button type="button" class="done-btn undo" title="Mark incomplete">↩</button>'
        : '<button type="button" class="done-btn" title="Mark complete">✓ Done</button>';
      const imgBase = row.custom ? '/custom/' : '/crops/';
      const label = row.custom ? row.file : `#${Number(row.id) + 1} ${row.file}`;
      const sub = row.custom
        ? 'Custom crop'
        : row.source === 'catalog'
          ? 'Catalog title'
          : row.source === 'user'
            ? 'Saved title'
            : 'OCR: ' + esc(row.raw_ocr || '—');
      el.innerHTML = `<img src="${imgBase}${row.file}" alt="">
        <div style="flex:1;min-width:0">
          <div class="id"><span>${label}</span>${btn}</div>
          <input value="${esc(row.title)}" data-id="${row.id}">
          <div class="ocr">${sub}</div>
        </div>`;
      el.querySelector('input').oninput = (e) => {
        row.title = e.target.value;
        dirty.add(row.id);
        el.classList.add('changed');
        setLabelStatus('unsaved changes');
      };
      el.querySelector('.done-btn').onclick = () => {
        row.complete = !row.complete;
        dirty.add(row.id);
        renderLabels();
        setLabelStatus('unsaved changes');
      };
      grid.appendChild(el);
    }
    document.getElementById('count').textContent =
      `${labels.length - done} left · ${done} done · ${n} shown`;
  }

  async function loadLabels() {
    if (labelsLoaded) return;
    labels = await fetch('/api/labels').then((r) => r.json());
    for (const row of labels) if (row.complete == null) row.complete = false;
    labelsLoaded = true;
    labelEmpty.hidden = labels.length > 0;
    if (!labels.length) {
      labelEmpty.textContent = 'No labels yet. From the repo root run: uv run python run_pipeline.py all — then reload. Titles come from canonical_titles.json.';
    }
    if (labels.length && labels.every((row) => row.complete)) {
      showDone.checked = true;
    }
    renderLabels();
  }

  q.oninput = renderLabels;
  showDone.onchange = renderLabels;
  document.getElementById('save').onclick = async () => {
    const r = await fetch('/api/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ labels }),
    });
    if (!r.ok) {
      setLabelStatus('save failed', false);
      return;
    }
    dirty.clear();
    renderLabels();
    setLabelStatus('saved ' + new Date().toLocaleTimeString(), true);
  };
  document.getElementById('rebuildLabels').onclick = () => rebuild(labelStatus);
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 's' && currentStage() === 'labels') {
      e.preventDefault();
      document.getElementById('save').click();
    }
  });

  /* —— custom crops —— */
  let drag = null;
  let rect = null;
  let cropsReady = false;
  const sheet = document.getElementById('sheet');
  const sel = document.getElementById('sel');
  const wrap = document.getElementById('wrap');
  const cropEmpty = document.getElementById('cropEmpty');
  const cropStatus = document.getElementById('cropStatus');

  function imgPt(clientX, clientY) {
    const r = sheet.getBoundingClientRect();
    const x = ((clientX - r.left) / r.width) * sheet.naturalWidth;
    const y = ((clientY - r.top) / r.height) * sheet.naturalHeight;
    return [
      Math.max(0, Math.min(sheet.naturalWidth, x)),
      Math.max(0, Math.min(sheet.naturalHeight, y)),
    ];
  }
  function toSource(px, py) {
    return [Math.round(px), Math.round(py)];
  }
  function showRect(a, b) {
    const x0 = Math.min(a[0], b[0]);
    const y0 = Math.min(a[1], b[1]);
    const x1 = Math.max(a[0], b[0]);
    const y1 = Math.max(a[1], b[1]);
    const r = sheet.getBoundingClientRect();
    const sx = r.width / sheet.naturalWidth;
    const sy = r.height / sheet.naturalHeight;
    sel.style.display = 'block';
    sel.style.left = x0 * sx + 'px';
    sel.style.top = y0 * sy + 'px';
    sel.style.width = (x1 - x0) * sx + 'px';
    sel.style.height = (y1 - y0) * sy + 'px';
    rect = { x0, y0, x1, y1 };
    const [sx0, sy0] = toSource(x0, y0);
    const [sx1, sy1] = toSource(x1, y1);
    document.getElementById('coords').textContent =
      `${Math.round(x1 - x0)}×${Math.round(y1 - y0)} px · [${sx0},${sy0},${sx1},${sy1}]`;
    document.getElementById('saveCrop').disabled = x1 - x0 < 4 || y1 - y0 < 4;
  }

  sheet.onmousedown = (e) => {
    if (e.button !== 0) return;
    drag = imgPt(e.clientX, e.clientY);
    rect = null;
    showRect(drag, drag);
    e.preventDefault();
  };
  window.addEventListener('mousemove', (e) => {
    if (!drag) return;
    showRect(drag, imgPt(e.clientX, e.clientY));
  });
  window.addEventListener('mouseup', () => {
    drag = null;
  });

  async function loadCropList() {
    const items = await fetch('/api/crops').then((r) => r.json());
    const el = document.getElementById('list');
    el.innerHTML = '';
    if (!items.length) {
      el.innerHTML =
        '<p class="empty" style="padding:8px 0">None saved. Form Inputs and Panels on the August 2018 sheet are auto-detected — add a crop only for something the grid missed.</p>';
      return;
    }
    for (const c of items.slice().reverse()) {
      const d = document.createElement('div');
      d.className = 'crop-item';
      d.innerHTML = `<img src="/custom/${c.file}?t=${Date.now()}" alt="">
        <div style="flex:1;min-width:0"><div>${esc(c.title || c.file)}</div>
        <div style="color:#888">${c.w}×${c.h}</div></div>
        <button type="button" data-id="${c.id}">Del</button>`;
      d.querySelector('button').onclick = async () => {
        await fetch('/api/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: c.id }),
        });
        labelsLoaded = false;
        loadCropList();
      };
      el.appendChild(d);
    }
  }

  async function loadCrops() {
    if (cropsReady) return;
    const meta = await fetch('/api/meta');
    if (!meta.ok) {
      cropEmpty.hidden = false;
      wrap.hidden = true;
      cropEmpty.textContent =
        'Missing source/Splunk_Documentation_Icons_August2018.png. Download it from Splunk docs, then reload.';
      cropsReady = true;
      return;
    }
    cropEmpty.hidden = true;
    wrap.hidden = false;
    cropStatus.textContent = 'Loading full PNG…';
    cropStatus.style.color = '#666';
    sheet.src = '/sheet?' + Date.now();
    await sheet.decode();
    cropStatus.textContent = 'Ready';
    cropStatus.style.color = '#0a7';
    cropsReady = true;
    loadCropList();
  }

  document.getElementById('saveCrop').onclick = async () => {
    if (!rect) return;
    const [sx0, sy0] = toSource(rect.x0, rect.y0);
    const [sx1, sy1] = toSource(rect.x1, rect.y1);
    const title = document.getElementById('cropTitle').value.trim();
    const r = await fetch('/api/crop', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ x0: sx0, y0: sy0, x1: sx1, y1: sy1, title }),
    });
    const j = await r.json();
    cropStatus.textContent = j.ok ? 'Saved ' + j.file : j.error || 'failed';
    cropStatus.style.color = j.ok ? '#0a7' : '#c00';
    if (j.ok) {
      document.getElementById('cropTitle').value = '';
      sel.style.display = 'none';
      rect = null;
      labelsLoaded = false;
      loadCropList();
    }
  };
  document.getElementById('rebuildCrops').onclick = () => rebuild(cropStatus);
})();
