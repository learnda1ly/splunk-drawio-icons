# splunk-drawio-icons

Jupyter notebook pipeline that builds [diagrams.net / draw.io](https://www.diagrams.net/) shape libraries from Splunk’s official icon sheet [`Splunk_Documentation_Icons_August2018.png`](https://help.splunk.com/en/splunk-enterprise/administer/inherit-a-splunk-deployment/10.4/inherited-deployment-tasks/draw-a-diagram-of-your-deployment).

## Outputs

| File | Description |
|------|-------------|
| `dist/Splunk-Icons-adaptive.xml` | CSS `light-dark()` SVG silhouettes — **recommended** for light and dark themes |
| `dist/Splunk-Icons-color.xml` | Full-color PNG icons |
| `dist/Splunk-Icons-dark.xml` | Inverted-color PNG icons for dark backgrounds |

Intermediate artifacts (`dist/crops/`, `manifest.json`, `labels_final.json`, etc.) are written while the notebook runs.

## Pipeline

1. **Crop** — detect icon bounding boxes on the source sheet
2. **OCR** — read labels printed below each icon
3. **Fuzzy-match** — align OCR text to a seed vocabulary of known Splunk icon titles
4. **Filter** — drop bare single-letter noise (but keep `JS`, `HTML`, `CSS`, `SDK`, and titles containing *custom visualization*, *simple xml*, or *panels html*)
5. **Build libraries** — emit the three draw.io XML libraries

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Install [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) on your system (required by `pytesseract`):

- **macOS:** `brew install tesseract`
- **Ubuntu/Debian:** `sudo apt install tesseract-ocr`
- **Windows:** [installer](https://github.com/UB-Mannheim/tesseract/wiki)

Download the official Splunk icon sheet and place it at:

```
source/Splunk_Documentation_Icons_August2018.png
```

Then open and run `splunk_drawio_icons_pipeline.ipynb`.

## Import into draw.io

1. Open [diagrams.net](https://app.diagrams.net/) or the desktop app
2. **File → Open Library From → Device**
3. Select one of the `dist/Splunk-Icons-*.xml` files

## Source documentation

- [Draw a diagram of your deployment](https://help.splunk.com/en/splunk-enterprise/administer/inherit-a-splunk-deployment/10.4/inherited-deployment-tasks/draw-a-diagram-of-your-deployment) — Splunk Enterprise admin guide

## Legal note

The icons are Splunk artwork. This repository ships the **notebook and build tooling only** — it does **not** redistribute Splunk icon binaries. Obtain the source PNG from Splunk’s documentation and use the generated libraries in accordance with Splunk’s terms.
