"""Tests for tools.settings — persistent GUI settings."""
import json
import os
import tempfile

import pytest

from tools import settings


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    """Redirect settings to a temp directory for every test."""
    monkeypatch.setattr(settings, '_SETTINGS_DIR', tmp_path)
    monkeypatch.setattr(settings, '_SETTINGS_FILE', tmp_path / 'settings.json')
    settings._cache = None
    yield


def test_load_defaults_when_no_file():
    cfg = settings.load_settings()
    assert cfg['window_width'] == 1100
    assert cfg['theme'] == 'dark'
    assert cfg['sidebar_visible'] is True


def test_save_and_reload():
    settings.put('theme', 'light')
    settings.put('window_width', 800)
    # Force reload from disk
    settings._cache = None
    cfg = settings.load_settings()
    assert cfg['theme'] == 'light'
    assert cfg['window_width'] == 800


def test_get_returns_default_for_unknown_key():
    assert settings.get('nonexistent_key', 42) == 42


def test_put_creates_file(tmp_path):
    settings.put('font_scale', 1.2)
    assert (tmp_path / 'settings.json').exists()
    data = json.loads((tmp_path / 'settings.json').read_text())
    assert data['font_scale'] == 1.2


def test_corrupt_file_returns_defaults(tmp_path):
    (tmp_path / 'settings.json').write_text('NOT VALID JSON!!!')
    cfg = settings.load_settings()
    assert cfg == settings.DEFAULTS


def test_partial_file_merges_with_defaults(tmp_path):
    (tmp_path / 'settings.json').write_text('{"theme": "light"}')
    cfg = settings.load_settings()
    assert cfg['theme'] == 'light'
    assert cfg['window_width'] == 1100  # from defaults


def test_save_settings_with_explicit_dict(tmp_path):
    settings.save_settings({'custom': True, 'window_width': 500})
    data = json.loads((tmp_path / 'settings.json').read_text())
    assert data['custom'] is True
    assert data['window_width'] == 500
