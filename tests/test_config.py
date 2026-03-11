import json
from pathlib import Path

from tools import config


def test_load_config_from_xdg(tmp_path, monkeypatch):
    xdg = tmp_path / "xdg"
    cfg_dir = xdg / "gitHandler"
    cfg_dir.mkdir(parents=True)
    cfg_file = cfg_dir / "config.json"
    data = {"backup_dir": "/tmp/backups", "auto_fix": True}
    cfg_file.write_text(json.dumps(data))

    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))

    loaded = config.load_config()
    assert loaded["backup_dir"] == "/tmp/backups"
    assert loaded["auto_fix"] is True
