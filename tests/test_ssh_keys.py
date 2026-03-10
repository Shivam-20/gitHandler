import stat
from pathlib import Path

import pytest

from tools import ssh_keys


def test_discover_keys_and_permissions(tmp_path, monkeypatch):
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()

    # secure key (id_rsa) with RSA header
    secure = ssh_dir / "id_rsa"
    secure.write_bytes(b"-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAAB\n")
    secure.chmod(0o600)

    # insecure key with OPENSSH header
    insecure = ssh_dir / "otherkey"
    insecure.write_bytes(b"-----BEGIN OPENSSH PRIVATE KEY-----\nAAAAB3NzaC1yc2E\n")
    insecure.chmod(0o644)

    # non-key file (should be ignored)
    nonkey = ssh_dir / "not_a_key"
    nonkey.write_text("hello")
    nonkey.chmod(0o600)

    # Point HOME to the temp dir so discover_keys scans tmp_path/.ssh
    monkeypatch.setenv("HOME", str(tmp_path))

    results = ssh_keys.discover_keys()
    names = {Path(r["path"]).name: r for r in results}

    assert "id_rsa" in names
    assert "otherkey" in names
    # id_rsa should be detected as rsa and have permissions_ok True
    assert names["id_rsa"]["type"] == "rsa"
    assert names["id_rsa"]["permissions_ok"] is True
    # otherkey contains a key header but has open permissions
    assert names["otherkey"]["permissions_ok"] is False
