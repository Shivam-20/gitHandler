from pathlib import Path

from tools import ssh_keys


def test_fingerprint_duplicates(tmp_path, monkeypatch):
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()

    content = b"-----BEGIN RSA PRIVATE KEY-----\nMIIEfakekeydata\n"
    k1 = ssh_dir / "key1"
    k2 = ssh_dir / "key2"
    k1.write_bytes(content)
    k2.write_bytes(content)
    k1.chmod(0o600)
    k2.chmod(0o600)

    monkeypatch.setenv("HOME", str(tmp_path))

    keys = ssh_keys.discover_keys()
    names = {Path(k["path"]).name: k for k in keys}

    assert "key1" in names and "key2" in names
    assert names["key1"]["fingerprint"] == names["key2"]["fingerprint"]
    assert names["key1"]["duplicate"] is True and names["key2"]["duplicate"] is True
