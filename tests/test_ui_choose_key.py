from pathlib import Path

from tools.ui_tui import choose_key_interactively


def test_choose_key_interactively_select(tmp_path, monkeypatch):
    k1 = tmp_path / "k1"
    k1.write_text("dummy")
    keys = [{"path": str(k1), "type": "rsa", "permissions_ok": True, "reason": "OK"}]

    monkeypatch.setattr('builtins.input', lambda prompt='': '1')
    sel = choose_key_interactively(keys)
    assert sel == str(k1)


def test_choose_key_interactively_custom(tmp_path, monkeypatch):
    keys = []
    monkeypatch.setattr('builtins.input', lambda prompt='': '0' if 'Select' in prompt else str(tmp_path / 'custom'))
    sel = choose_key_interactively(keys)
    assert str(Path(sel)) == str(tmp_path / 'custom')
