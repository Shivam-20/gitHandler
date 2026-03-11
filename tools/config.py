from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Any

DEFAULT_CONFIG: Dict[str, Any] = {
    "backup_dir": None,
    "auto_fix": False,
    "exclude_patterns": [],
    "agent_auto_add": False,
}


def load_config() -> Dict[str, Any]:
    """Load configuration from XDG paths or fallbacks.

    Looks for (in order):
      $XDG_CONFIG_HOME/gitHandler/config.json
      ~/.gitHandler.json
      ~/.githandlerrc

    Returns a dict with keys from DEFAULT_CONFIG merged with any provided values.
    """
    xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    candidates = [
        Path(xdg) / "gitHandler" / "config.json",
        Path.home() / ".gitHandler.json",
        Path.home() / ".githandlerrc",
    ]

    for p in candidates:
        try:
            if p.exists():
                txt = p.read_text()
                data = json.loads(txt)
                cfg = DEFAULT_CONFIG.copy()
                cfg.update(data)
                return cfg
        except Exception:
            # Ignore malformed config files
            continue

    return DEFAULT_CONFIG.copy()
