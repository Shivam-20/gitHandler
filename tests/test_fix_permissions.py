import stat
from pathlib import Path

from tools import ssh_keys


def test_fix_permissions_dry_run(tmp_path):
    f = tmp_path / "id_test"
    f.write_bytes(b"-----BEGIN RSA PRIVATE KEY-----\nabc\n")
    f.chmod(0o644)
    res = ssh_keys.fix_permissions(paths=[str(f)], dry_run=True)
    assert isinstance(res, list) and res
    r = res[0]
    assert r["changed"] is False
    assert r["would_set_mode"] == oct(0o600)
    assert r["current_mode"] == oct(0o644)


def test_fix_permissions_apply(tmp_path):
    f = tmp_path / "id_test_apply"
    f.write_bytes(b"-----BEGIN RSA PRIVATE KEY-----\nabc\n")
    f.chmod(0o644)
    bdir = tmp_path / "backups"
    res = ssh_keys.fix_permissions(paths=[str(f)], backup_dir=str(bdir), dry_run=False)
    r = res[0]
    assert r["changed"] is True
    assert r["backup"] is not None
    assert Path(r["backup"]).exists()
    assert stat.S_IMODE(f.stat().st_mode) == 0o600
