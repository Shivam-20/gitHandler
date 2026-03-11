import os
import stat
import subprocess
from pathlib import Path

import pytest


def test_update_remote_creates_ssh_config_and_updates_remote(tmp_path, monkeypatch):
    # Simulate HOME
    home = tmp_path / "home"
    ssh_dir = home / ".ssh"
    ssh_dir.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))

    # Create a fresh git repo
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main"], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # Add an ssh remote in scp-style
    orig_url = "git@github.com:owner/test-repo.git"
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", orig_url], check=True)

    # Create a dummy key file
    key_path = ssh_dir / "id_testkey"
    key_path.write_text("FAKE-PRIVATE-KEY")
    # set secure perms
    os.chmod(key_path, 0o600)

    # Run update_repo_remotes (non-dry-run)
    from tools import ssh_config

    res = ssh_config.update_repo_remotes(str(repo), str(key_path), remotes=None, dry_run=False, backup_dir=str(home / "backup"), yes=True)

    # Should have processed 'origin'
    origins = [r for r in res if r.get("remote") == "origin"]
    assert origins, f"Expected origin in results, got: {res}"
    o = origins[0]
    assert o.get("original_url") == orig_url
    assert o.get("new_url") is not None
    assert o.get("alias")

    # Check that ~/.ssh/config was written and contains the alias and IdentityFile
    conf = ssh_dir / "config"
    assert conf.exists(), "~/.ssh/config not created"
    txt = conf.read_text()
    assert f"Host {o['alias']}" in txt
    assert f"IdentityFile {str(key_path)}" in txt

    # Check that git remote was updated
    p = subprocess.run(["git", "-C", str(repo), "remote", "get-url", "origin"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert p.returncode == 0
    new_remote = p.stdout.strip()
    assert new_remote != orig_url
    parsed = ssh_config.parse_git_remote(new_remote)
    assert parsed["host"] == o["alias"]


def test_update_remote_dry_run_reports_actions(tmp_path, monkeypatch):
    home = tmp_path / "home"
    ssh_dir = home / ".ssh"
    ssh_dir.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main"], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    orig_url = "git@github.com:owner/test-repo.git"
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", orig_url], check=True)

    key_path = ssh_dir / "id_testkey"
    key_path.write_text("FAKE-PRIVATE-KEY")
    os.chmod(key_path, 0o600)

    from tools import ssh_config
    res = ssh_config.update_repo_remotes(str(repo), str(key_path), remotes=["origin"], dry_run=True, backup_dir=str(home / "backup"), yes=False)

    # dry-run should report would_write and not actually create config or change remote
    o = next((r for r in res if r.get("remote") == "origin"), None)
    assert o is not None
    assert o["config"]["written"] is False
    assert "would_write" in o["config"]

    conf = ssh_dir / "config"
    assert not conf.exists()

    p = subprocess.run(["git", "-C", str(repo), "remote", "get-url", "origin"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert p.returncode == 0
    assert p.stdout.strip() == orig_url
