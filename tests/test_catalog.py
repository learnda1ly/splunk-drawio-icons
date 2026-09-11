"""Catalog structure — no source PNG required."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _catalog() -> dict:
    return json.loads((ROOT / 'canonical_titles.json').read_text())


def test_catalog_has_fingerprint_and_unique_titles():
    data = _catalog()
    sheet = data['sheet']
    assert sheet['file'] == 'Splunk_Documentation_Icons_August2018.png'
    assert 'draw-a-diagram-of-your-deployment' in sheet['docs_url']
    assert sheet['width'] == 13137
    assert sheet['height'] == 24770
    assert len(sheet['sha256']) == 64
    rows = data['rows']
    flat = [title for row in rows for title in row]
    assert len(rows) == 14
    assert len(flat) == 195
    assert rows[0][0] == 'Add-On'
    assert rows[-1][-1] == 'Panels Inline Search'
    assert len(set(flat)) == len(flat)


def test_form_inputs_and_panels_rows():
    rows = _catalog()['rows']
    assert rows[12][0].startswith('Form Inputs')
    assert rows[13][0].startswith('Panels')
    assert 'Hadoop' in rows[10]
    assert 'Indexer With Load Balancer' in rows[4]
    assert 'Splunk Web' in rows[9]


def test_verify_sheet_rejects_wrong_size():
    from PIL import Image

    from splunk_icons_pipeline import invalidate_catalog_cache, verify_sheet

    invalidate_catalog_cache()
    img = Image.new('RGBA', (10, 10))
    with pytest.raises(ValueError, match='Source PNG is'):
        verify_sheet(img)


def test_shape_tags_include_os_and_role():
    from splunk_icons_pipeline import shape_tags

    tags = shape_tags('Search Head, Linux')
    assert 'splunk' in tags
    assert 'linux' in tags
    assert 'search-head' in tags
    assert 'os' in tags
