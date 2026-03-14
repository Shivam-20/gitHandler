"""tools.settings — Persistent GUI settings for PyGitDesk.

Settings stored at ~/.config/PyGitDesk/settings.json.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

_SETTINGS_DIR = Path(
    os.environ.get('XDG_CONFIG_HOME') or (Path.home() / '.config')
) / 'PyGitDesk'

_SETTINGS_FILE = _SETTINGS_DIR / 'settings.json'

DEFAULTS: Dict[str, Any] = {
    'window_width': 1100,
    'window_height': 740,
    'sidebar_visible': True,
    'log_panel_visible': True,
    'theme': 'dark',
    'font_scale': 1.0,
    'last_page': 'status',
    'restore_last_page': True,
    'status_paned_pos': 340,
    'log_paned_pos': 480,
    'commit_limit': 500,
    'revert_limit': 100,
}

_cache: Dict[str, Any] | None = None


def load_settings() -> Dict[str, Any]:
    """Load settings from disk, merging with defaults."""
    global _cache
    cfg = DEFAULTS.copy()
    try:
        if _SETTINGS_FILE.exists():
            data = json.loads(_SETTINGS_FILE.read_text())
            if isinstance(data, dict):
                cfg.update(data)
    except Exception:
        pass
    _cache = cfg
    return cfg


def save_settings(settings: Dict[str, Any] | None = None) -> None:
    """Write settings dict to disk."""
    global _cache
    if settings is not None:
        _cache = settings
    if _cache is None:
        return
    try:
        _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        _SETTINGS_FILE.write_text(json.dumps(_cache, indent=2))
    except Exception:
        pass


def get(key: str, default: Any = None) -> Any:
    """Get a single setting value."""
    if _cache is None:
        load_settings()
    return (_cache or DEFAULTS).get(key, default)


def put(key: str, value: Any) -> None:
    """Set a single setting value and persist."""
    if _cache is None:
        load_settings()
    if _cache is not None:
        _cache[key] = value
    save_settings()
