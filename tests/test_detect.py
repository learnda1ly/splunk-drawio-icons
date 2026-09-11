"""Detection vs catalog — skipped when the source PNG is not present."""

from __future__ import annotations

import pytest

from splunk_icons_pipeline import (
    SHEET,
    catalog_title,
    detect_boxes,
    load_sheet,
    canonical_title_rows,
    verify_sheet,
)


pytestmark = pytest.mark.skipif(
    not SHEET.is_file(),
    reason='source/Splunk_Documentation_Icons_August2018.png not present',
)


def test_sheet_matches_catalog_fingerprint():
    sheet = load_sheet()
    verify_sheet(sheet, SHEET)
    assert sheet.size == (13137, 24770)


def test_detection_matches_catalog_grid():
    boxes = detect_boxes(load_sheet())
    rows = canonical_title_rows()
    expected = sum(len(row) for row in rows)
    assert len(boxes) == expected
    by_row: dict[int, int] = {}
    for box in boxes:
        by_row[box['icon_row']] = by_row.get(box['icon_row'], 0) + 1
        assert catalog_title(box['icon_row'], box['col'])
    assert len(by_row) == len(rows)
    assert by_row[0] == 15
    assert by_row[12] == 7
    assert by_row[13] == 8
    assert boxes[0]['icon_row'] == 0 and boxes[0]['col'] == 0
    last = boxes[-1]
    assert last['icon_row'] == 13
    assert catalog_title(last['icon_row'], last['col']) == 'Panels Inline Search'
    assert catalog_title(0, 0) == 'Add-On'
