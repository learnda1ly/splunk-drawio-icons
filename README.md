# splunk-drawio-icons

Build and use [diagrams.net / draw.io](https://www.diagrams.net/) shape libraries from Splunk’s official icon sheet [`Splunk_Documentation_Icons_August2018.png`](https://help.splunk.com/en/splunk-enterprise/administer/inherit-a-splunk-deployment/10.4/inherited-deployment-tasks/draw-a-diagram-of-your-deployment).

Prebuilt libraries are in **`dist/`** (committed). Rebuild them anytime with the scripts below.

## Quick start (draw.io only)

1. Clone this repo.
2. Open [diagrams.net](https://app.diagrams.net/) or the desktop app.
3. **File → Open Library From → Device**
4. Select **`dist/Splunk-Icons-configurable.xml`** if you want Visio-like shapes (fill, line color, hostname/IP). Use **`dist/Splunk-Icons-adaptive.xml`** for theme-aware picture icons.

Optional: **`dist/Splunk-Connectors.xml`** for Splunk-style connector lines.

Use the **`.xml`** files. The matching **`.drawiolib`** files are the same JSON payload without the XML wrapper (for tooling); draw.io’s library import expects **`.xml`**.

## Outputs

| File | Description |
|------|-------------|
| `dist/Splunk-Icons-configurable.xml` | Native draw.io **stencils** — Style panel fill/line, N/E/S/W connection points, stored `title` / `hostname` / `ip` / `notes` |
| `dist/Splunk-Icons-adaptive.xml` | Theme-aware SVG **pictures** (`cssVars` + `light-dark()`) — good in dark mode, not Style-panel fill/line |
| `dist/Splunk-Icons-color.xml` | Full-color PNG pictures (fixed colors — poor contrast on dark canvases) |
| `dist/Splunk-Icons-dark.xml` | Inverted PNG pictures when you want color on a **dark** background only |
| `dist/Splunk-Connectors.xml` | Connector / edge style presets |

### Configurable icons (fill, line, hostname, IP)

These are real draw.io shapes, not pasted images. After you drop one on the canvas:

1. **Fill / line / line width** — Style panel on the right (same as a rectangle). These icons are line art: **Fill** is the icon color (black in light mode, white in dark mode). **Line color** is an optional outline around the artwork (off by default). To put a colored card behind an icon, drop a rectangle in back and group it.
2. **Hostname, IP, notes** — select the shape → **Edit → Edit Data** (`Ctrl+M` / `Cmd+M`). Values are stored on that instance in the `.drawio` file. The visible label is `%title%`, `%hostname%`, and `%ip%` (empty fields stay blank).
3. **Connectors** — hover to see N/E/S/W points, or use the blue arrows.

What draw.io **cannot** do with these icons:

- Recolor the original **PNG pixels**. A raster image has no fill or stroke for the Style panel to change. The configurable library is a vector silhouette traced from each crop.
- Keep official **multi-color** Splunk art *and* independently recolor every region from one Fill picker. Use `Splunk-Icons-color.xml` for the painted look; use the configurable library when you need fill/line/data.
- Visio ShapeSheet formulas or a custom property dialog. draw.io’s equivalent is **Edit Data** plus `%placeholder%` labels.

## Setup (rebuild from source)

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Install [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) if you will re-run OCR:

- **macOS:** `brew install tesseract`
- **Ubuntu/Debian:** `sudo apt install tesseract-ocr`
- **Windows:** [UB Mannheim installer](https://github.com/UB-Mannheim/tesseract/wiki)

Place the Splunk sheet at:

```text
source/Splunk_Documentation_Icons_August2018.png
```

(`source/*.png` is gitignored; the sheet is not redistributed in this repo.)

## Scripts

Run from the repo root with the venv activated.

| Command | Purpose |
|---------|---------|
| `python run_pipeline.py all` | Full pipeline: crops → OCR → labels → libraries |
| `python run_pipeline.py crops` | Detect icons; write `dist/crops/`, `manifest.json`, `connectors.json` |
| `python run_pipeline.py ocr` | OCR label text → `labels_ocr.json` |
| `python run_pipeline.py labels` | Fuzzy-match titles → `labels_final.json` |
| `python run_pipeline.py build` | Build `Splunk-Icons-*.xml` from existing `dist/` data |
| `python edit_labels.py` | Web UI to edit titles → http://127.0.0.1:8765 |
| `python edit_labels.py --rebuild` | Rebuild libraries after saving labels |
| `python crop_picker.py` | Draw custom crops on the sheet → http://127.0.0.1:8766 |

Implementation details live in **`splunk_icons_pipeline.py`**.

## Tutorial notebook

Open **`splunk_drawio_icons_pipeline.ipynb`** for a guided walkthrough (setup, CLI commands, label editor, custom crops, draw.io import). It is documentation-first; the notebook calls the same scripts and Python module as above.

## Pipeline overview

1. **Crop** — scanline grid on the icon sheet  
2. **OCR** — read alpha-only labels under each cell  
3. **Fuzzy-match** — map OCR to known Splunk icon titles  
4. **Build** — emit four icon libraries + connectors (configurable stencils are traced one crop at a time)  

## Source documentation

- [Draw a diagram of your deployment](https://help.splunk.com/en/splunk-enterprise/administer/inherit-a-splunk-deployment/10.4/inherited-deployment-tasks/draw-a-diagram-of-your-deployment) — Splunk Enterprise admin guide  
- [Custom shape library format](https://www.drawio.com/docs/reference/format-custom-shape-library/) — draw.io

## Legal note

Icons are Splunk artwork. This repository ships **generated** libraries under `dist/` and build tooling. Obtain the source PNG from Splunk’s documentation and use the libraries in accordance with Splunk’s terms.
