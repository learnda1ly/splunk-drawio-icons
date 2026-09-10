# splunk-drawio-icons

Build and use [diagrams.net / draw.io](https://www.diagrams.net/) shape libraries from Splunk’s official icon sheet [`Splunk_Documentation_Icons_August2018.png`](https://help.splunk.com/en/splunk-enterprise/administer/inherit-a-splunk-deployment/10.4/inherited-deployment-tasks/draw-a-diagram-of-your-deployment).

Prebuilt libraries are in **`dist/`** (committed). Rebuild them anytime with the scripts below.

## Quick start (draw.io only)

1. Clone this repo.
2. Open [diagrams.net](https://app.diagrams.net/) or the desktop app.
3. **File → Open Library From → Device**
4. Select **`dist/Splunk-Icons-adaptive.xml`** (recommended for light/dark themes).

Optional: **`dist/Splunk-Connectors.xml`** for Splunk-style connector lines.

Use the **`.xml`** files. The matching **`.drawiolib`** files are the same JSON payload without the XML wrapper (for tooling); draw.io’s library import expects **`.xml`**.

## Outputs

| File | Description |
|------|-------------|
| `dist/Splunk-Icons-adaptive.xml` | Theme-aware SVG silhouettes (`light-dark()`) — **recommended** |
| `dist/Splunk-Icons-color.xml` | Full-color PNG icons |
| `dist/Splunk-Icons-dark.xml` | Inverted PNG icons for dark backgrounds |
| `dist/Splunk-Connectors.xml` | Connector / edge style presets |

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
4. **Build** — emit three icon libraries + connectors  

## Source documentation

- [Draw a diagram of your deployment](https://help.splunk.com/en/splunk-enterprise/administer/inherit-a-splunk-deployment/10.4/inherited-deployment-tasks/draw-a-diagram-of-your-deployment) — Splunk Enterprise admin guide  
- [Custom shape library format](https://www.drawio.com/docs/reference/format-custom-shape-library/) — draw.io

## Legal note

Icons are Splunk artwork. This repository ships **generated** libraries under `dist/` and build tooling. Obtain the source PNG from Splunk’s documentation and use the libraries in accordance with Splunk’s terms.
