import os
import subprocess
from pathlib import Path

import pytest


def test_update_remote_ssh_scheme(tmp_path, monkeypatch):
    home = tmp_path / "home"
    ssh_dir = home / ".ssh"
    ssh_dir.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main"], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    orig_url = "ssh://git@github.com/owner/test-repo.git"
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", orig_url], check=True)

    key_path = ssh_dir / "id_testkey"
    key_path.write_text("FAKE-PRIVATE-KEY")
    os.chmod(key_path, 0o600)

    from tools import ssh_config

    res = ssh_config.update_repo_remotes(str(repo), str(key_path), remotes=None, dry_run=False, backup_dir=str(home / "backup"), yes=True)

    origins = [r for r in res if r.get("remote") == "origin"]
    assert origins
    o = origins[0]
    assert o.get("original_url") == orig_url
    assert o.get("new_url") is not None
    assert o.get("alias")

    conf = ssh_dir / "config"
    assert conf.exists()
    txt = conf.read_text()
    assert f"Host {o['alias']}" in txt
    assert f"IdentityFile {str(key_path)}" in txt

    p = subprocess.run(["git", "-C", str(repo), "remote", "get-url", "origin"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert p.returncode == 0
    new_remote = p.stdout.strip()
    assert new_remote != orig_url
    from tools import ssh_config as sc
    parsed = sc.parse_git_remote(new_remote)
    assert parsed["host"] == o["alias"]


def test_update_remote_multiple_remotes(tmp_path, monkeypatch):
    home = tmp_path / "home"
    ssh_dir = home / ".ssh"
    ssh_dir.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main"], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    orig1 = "git@github.com:owner/test-repo.git"
    orig2 = "git@github.com:owner/other.git"
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", orig1], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "upstream", orig2], check=True)

    key_path = ssh_dir / "id_testkey"
    key_path.write_text("FAKE-PRIVATE-KEY")
    os.chmod(key_path, 0o600)

    from tools import ssh_config
    res = ssh_config.update_repo_remotes(str(repo), str(key_path), remotes=None, dry_run=False, backup_dir=str(home / "backup"), yes=True)

    # Both remotes should be processed
    remotes = {r['remote']: r for r in res}
    assert 'origin' in remotes and 'upstream' in remotes
    assert remotes['origin'].get('new_url')
    assert remotes['upstream'].get('new_url')

    conf = ssh_dir / "config"
    assert conf.exists()
    txt = conf.read_text()
    assert remotes['origin']['alias'] in txt
    assert remotes['upstream']['alias'] in txt


def test_update_remote_non_ssh_skipped(tmp_path, monkeypatch):
    home = tmp_path / "home"
    ssh_dir = home / ".ssh"
    ssh_dir.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main"], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    orig = "https://github.com/owner/test-repo.git"
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", orig], check=True)

    key_path = ssh_dir / "id_testkey"
    key_path.write_text("FAKE-PRIVATE-KEY")
    os.chmod(key_path, 0o600)

    from tools import ssh_config
    res = ssh_config.update_repo_remotes(str(repo), str(key_path), remotes=None, dry_run=True, backup_dir=str(home / "backup"), yes=False)

    # Should be skipped
    o = next((r for r in res if r.get('remote') == 'origin'), None)
    assert o is not None
    assert o.get('skipped') is True
