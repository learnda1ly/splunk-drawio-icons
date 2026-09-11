"""Parse Splunk docs HTML for the icon-sheet PNG; no network required."""

from __future__ import annotations

import urllib.error

import pytest

from splunk_icons_pipeline import (
    DEFAULT_SHEET_DOCS_URL,
    find_sheet_png_url,
    sheet_docs_url,
    sheet_moved_message,
)


SAMPLE_HREF = (
    'https://splunk.deploy.heretto.com/v4/deployments/example/object/abc'
    '?jwt=token&amp;response-content-disposition=attachment%3B+filename%3D%22'
    'Splunk_Documentation_Icons_August2018.png%22'
)


def test_catalog_docs_url_matches_default():
    assert sheet_docs_url() == DEFAULT_SHEET_DOCS_URL
    assert 'draw-a-diagram-of-your-deployment' in sheet_docs_url()


def test_find_sheet_png_url_unescapes_href():
    html = f'<li><a href="{SAMPLE_HREF}">Transparent PNG</a></li>'
    url = find_sheet_png_url(html, DEFAULT_SHEET_DOCS_URL)
    assert url is not None
    assert 'Splunk_Documentation_Icons_August2018.png' in url
    assert '&amp;' not in url
    assert url.startswith('https://splunk.deploy.heretto.com/')


def test_find_sheet_png_url_missing():
    assert find_sheet_png_url('<html><a href="/other.png">x</a></html>') is None


def test_sheet_moved_message_includes_docs_and_path():
    text = sheet_moved_message('Could not find a Transparent PNG link on the Splunk docs page.')
    assert 'Splunk may have moved the icon sheet' in text
    assert DEFAULT_SHEET_DOCS_URL in text
    assert 'source/Splunk_Documentation_Icons_August2018.png' in text


def test_download_sheet_errors_when_docs_have_no_png(monkeypatch, tmp_path):
    from splunk_icons_pipeline import SheetDownloadError, download_sheet
    import splunk_icons_pipeline as pip

    monkeypatch.setattr(pip, 'SHEET', tmp_path / 'Splunk_Documentation_Icons_August2018.png')
    monkeypatch.setattr(pip, 'SOURCE_DIR', tmp_path)

    def fake_get(url: str, timeout: float):
        return b'<html><p>no icons here</p></html>', 'text/html'

    monkeypatch.setattr(pip, '_http_get', fake_get)
    with pytest.raises(SheetDownloadError, match='Could not find a Transparent PNG'):
        download_sheet(force=True)


def test_download_sheet_errors_on_docs_404(monkeypatch, tmp_path):
    from email.message import Message

    from splunk_icons_pipeline import SheetDownloadError, download_sheet
    import splunk_icons_pipeline as pip

    monkeypatch.setattr(pip, 'SHEET', tmp_path / 'Splunk_Documentation_Icons_August2018.png')
    monkeypatch.setattr(pip, 'SOURCE_DIR', tmp_path)

    def fake_get(url: str, timeout: float):
        raise urllib.error.HTTPError(url, 404, 'Not Found', Message(), None)

    monkeypatch.setattr(pip, '_http_get', fake_get)
    with pytest.raises(SheetDownloadError, match='HTTP 404'):
        download_sheet(force=True)


def test_download_sheet_errors_when_link_is_not_png(monkeypatch, tmp_path):
    from splunk_icons_pipeline import SheetDownloadError, download_sheet
    import splunk_icons_pipeline as pip

    dest = tmp_path / 'Splunk_Documentation_Icons_August2018.png'
    monkeypatch.setattr(pip, 'SHEET', dest)
    monkeypatch.setattr(pip, 'SOURCE_DIR', tmp_path)

    def fake_get(url: str, timeout: float):
        if 'help.splunk.com' in url:
            return (
                b'<a href="https://cdn.example/Splunk_Documentation_Icons_August2018.png">PNG</a>',
                'text/html',
            )
        return b'<html>moved</html>', 'text/html'

    monkeypatch.setattr(pip, '_http_get', fake_get)
    with pytest.raises(SheetDownloadError, match='did not return a PNG'):
        download_sheet(force=True)
    assert not dest.exists()


def test_download_sheet_rejects_wrong_fingerprint(monkeypatch, tmp_path):
    import io

    from PIL import Image

    from splunk_icons_pipeline import SheetDownloadError, download_sheet
    import splunk_icons_pipeline as pip

    dest = tmp_path / 'Splunk_Documentation_Icons_August2018.png'
    monkeypatch.setattr(pip, 'SHEET', dest)
    monkeypatch.setattr(pip, 'SOURCE_DIR', tmp_path)
    buf = io.BytesIO()
    Image.new('RGBA', (10, 10), (0, 0, 0, 0)).save(buf, format='PNG')
    png = buf.getvalue()

    def fake_get(url: str, timeout: float):
        if 'help.splunk.com' in url:
            return (
                b'<a href="https://cdn.example/Splunk_Documentation_Icons_August2018.png">PNG</a>',
                'text/html',
            )
        return png, 'image/png'

    monkeypatch.setattr(pip, '_http_get', fake_get)
    with pytest.raises(SheetDownloadError, match='Splunk may have moved'):
        download_sheet(force=True)
    assert not dest.exists()
