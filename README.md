# splunk-drawio-icons

Unofficial local tooling to turn Splunk’s documentation icon sheet into [diagrams.net / draw.io](https://www.diagrams.net/) shape libraries for diagrams of **your own Splunk deployment**.

This is **not** a Splunk product. Splunk does not sponsor, endorse, or certify this repository.

The icon artwork is Splunk’s. This repo ships **scripts only**. Generated libraries stay on your machine (`dist/` is gitignored).

## Quick start

1. Install [uv](https://docs.astral.sh/uv/).
2. Download the transparent PNG from [Draw a diagram of your deployment](https://help.splunk.com/en/splunk-enterprise/administer/inherit-a-splunk-deployment/10.4/inherited-deployment-tasks/draw-a-diagram-of-your-deployment) and save it as `source/Splunk_Documentation_Icons_August2018.png` (see `source/README.md`).
3. From the repo root:

```bash
uv sync
uv run python run_pipeline.py all    # crops → titles → libraries
uv run python app.py                 # optional workbench → http://127.0.0.1:8765
```

4. In draw.io: **File → Open Library From → Device** and choose a generated **`.xml`** file from your local `dist/` (not `.drawiolib`).

For the August 2018 sheet you do **not** need to hand-label icons or draw extra crops. `canonical_titles.json` names each icon by grid position (row, left to right). `run_pipeline.py all` writes about 195 shapes plus connector presets. [EasyOCR](https://github.com/JaidedAI/EasyOCR) runs only if that catalog has no name for a detected icon. No Tesseract install, and no Jupyter.

## Workbench

Optional. After a pipeline run, open `uv run python app.py`.

| Stage | What it does |
|-------|----------------|
| **Tutorial** | Import steps, library list, CLI, legal note |
| **Labels** | Search or rename catalog titles, then rebuild XML |
| **Custom crops** | Extra boxes only if the grid still missed an icon |

Saved title edits persist in local `dist/labels_final.json`. To change the default names for everyone, edit `canonical_titles.json` (names only, not Splunk artwork) and re-run the pipeline.

## Outputs (local, after you build)

| File | Description |
|------|-------------|
| `dist/Splunk-Icons-configurable.xml` | Native draw.io **stencils** — Style panel fill/line, N/E/S/W points, stored `title` / `hostname` / `ip` / `notes` |
| `dist/Splunk-Icons-adaptive.xml` | Theme-aware SVG **pictures** (`cssVars` + `light-dark()`) |
| `dist/Splunk-Icons-color.xml` | Full-color PNG pictures (fixed colors) |
| `dist/Splunk-Icons-dark.xml` | Inverted PNG pictures for dark backgrounds |
| `dist/Splunk-Connectors.xml` | Connector / edge style presets |

On a configurable shape: **Fill** is the icon color (black in light mode, white in dark). **Line color** is an optional outline. **Edit → Edit Data** (`Ctrl+M` / `Cmd+M`) stores hostname, IP, and notes.

```bash
uv run python run_pipeline.py crops    # re-detect icons on the sheet
uv run python run_pipeline.py ocr      # optional; only needed for uncatalogued icons
uv run python run_pipeline.py labels   # apply catalog / saved titles
uv run python run_pipeline.py build    # libraries from existing local dist/ data
```

Implementation: `splunk_icons_pipeline.py`, `icon_vector.py`, `icon_stencil.py`.

## Source documentation

- [Draw a diagram of your deployment](https://help.splunk.com/en/splunk-enterprise/administer/inherit-a-splunk-deployment/10.4/inherited-deployment-tasks/draw-a-diagram-of-your-deployment)
- [Custom shape library format](https://www.drawio.com/docs/reference/format-custom-shape-library/)
- [Splunk Websites Terms of Use](https://www.splunk.com/en_us/legal/terms/terms-of-use.html)
- [Splunk Trademark Usage Guidelines](https://www.splunk.com/en_us/legal/trademark-usage-guidelines.html)

## Legal

**Artwork.** The icon sheet and anything derived from it (crops, PNGs, SVGs, stencils, draw.io libraries) are Splunk copyrighted material. Splunk’s docs offer the PNG so you can diagram a Splunk deployment. Their [website terms](https://www.splunk.com/en_us/legal/terms/terms-of-use.html) do **not** grant a license to republish, retransmit, or distribute that artwork. Do not commit `source/*.png` or `dist/` to git or otherwise share the icon pack.

**Intended use.** Use generated libraries in your own diagrams that refer to Splunk products. Do not present this project as official Splunk artwork or imply Splunk affiliation, sponsorship, or endorsement.

**Name.** “Splunk” is used only to describe compatibility with Splunk documentation icons. Splunk, Splunk>, and Turn Data Into Doing are trademarks or registered trademarks of Splunk LLC in the United States and other countries. All other brand names, product names, or trademarks belong to their respective owners. © Splunk LLC. All rights reserved.

For permission to redistribute the icons, contact Splunk Legal (`trademarks@splunk.com`).
