"""tools.ssh_config

Helpers to add Host aliases to ~/.ssh/config and update git remotes to use them.

Primary function:
- update_repo_remotes(repo_path, key_path, remotes=None, dry_run=True, backup_dir=None, yes=False)

This module is careful to avoid following symlinks when touching ~/.ssh/config and writes
atomically using a temp file + os.replace. Backups are optional. Functions return structured
results suitable for CLI printing and tests.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse


def parse_git_remote(url: str) -> Dict:
    """Parse a git remote URL into a normalized dict.

    Supports scp-style (git@host:owner/repo.git) and ssh:// URLs. Any URL with
    an explicit non-SSH scheme (http://, https://, etc.) is treated as "other".
    Returns: {"style": "scp"|"ssh"|"other", "user": str|None, "host": str|None, "path": str|None, "port": int|None}
    """
    if not url:
        return {"style": "other", "user": None, "host": None, "path": None, "port": None}

    url = url.strip()
    # If a scheme is present, only accept SSH-style schemes; treat others as 'other'.
    if "://" in url:
        if url.startswith("ssh://") or url.startswith("git+ssh://"):
            p = urlparse(url)
            user = p.username
            host = p.hostname
            port = p.port
            path = p.path.lstrip("/")
            return {"style": "ssh", "user": user, "host": host, "path": path, "port": port}
        return {"style": "other", "user": None, "host": None, "path": None, "port": None}

    # scp-like: [user@]host:path  (only when no scheme is present)
    m = re.match(r"^(?:(?P<user>[^@]+)@)?(?P<host>[^:]+):(?P<path>.+)$", url)
    if m:
        return {"style": "scp", "user": m.group("user"), "host": m.group("host"), "path": m.group("path"), "port": None}

    return {"style": "other", "user": None, "host": None, "path": None, "port": None}


def _repo_name_from_path(path: str) -> str:
    if not path:
        return "repo"
    name = path.rstrip("/").split("/")[-1]
    if name.endswith('.git'):
        name = name[:-4]
    # sanitize
    name = re.sub(r"[^A-Za-z0-9_-]", "-", name)
    if not name:
        return "repo"
    return name


def make_host_alias(host: str, repo_path: Optional[str], key_path: str) -> str:
    """Create a deterministic, filesystem-friendly Host alias name.

    Format: <host>-<repo>-<sha8>
    """
    repo = _repo_name_from_path(repo_path or "")
    digest = hashlib.sha1(f"{host}:{repo}:{key_path}".encode()).hexdigest()[:8]
    base = f"{host}-{repo}-{digest}"
    alias = re.sub(r"[^A-Za-z0-9_-]", "-", base)
    # hostnames in ssh config must not be ridiculously long; truncate if needed
    return alias[:64]


def _build_host_entry(alias: str, hostname: str, user: Optional[str], identity_file: str, port: Optional[int]) -> str:
    lines = [f"Host {alias}"]
    lines.append(f"    HostName {hostname}")
    if user:
        lines.append(f"    User {user}")
    if port:
        lines.append(f"    Port {port}")
    lines.append(f"    IdentityFile {identity_file}")
    lines.append("    IdentitiesOnly yes")
    return "\n" + "\n".join(lines) + "\n"


def write_ssh_config_entry(alias: str, hostname: str, user: Optional[str], identity_file: str, port: Optional[int] = None, backup_dir: Optional[str] = None, dry_run: bool = True) -> Dict:
    """Write (append) an SSH config Host entry for the alias.

    Returns a dict describing the action. Does not follow symlinks for ~/.ssh/config.
    """
    config_path = Path("~/.ssh/config").expanduser()
    res = {"config_path": str(config_path), "alias": alias, "written": False, "backup": None, "reason": ""}

    # Refuse to operate on symlinked config
    try:
        if config_path.exists() and config_path.is_symlink():
            res["reason"] = "Refusing to operate on symlinked ssh config"
            return res
    except OSError as e:
        res["reason"] = f"OS error inspecting config: {e}"
        return res

    entry = _build_host_entry(alias, hostname, user, identity_file, port)

    if dry_run:
        res["reason"] = "Dry run"
        res["would_write"] = entry
        return res

    # Create parent dir if needed
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        res["reason"] = f"Failed to create ~/.ssh directory: {e}"
        return res

    # Backup existing config if requested
    if config_path.exists() and backup_dir:
        try:
            bdir = Path(backup_dir).expanduser()
            bdir.mkdir(parents=True, exist_ok=True)
            bakname = f"ssh_config.{int(time.time())}.bak"
            bakpath = bdir / bakname
            shutil.copy2(config_path, bakpath)
            res["backup"] = str(bakpath)
        except Exception as e:
            res["reason"] = f"Backup failed: {e}"
            return res

    # Read existing content (if any)
    existing = ""
    if config_path.exists():
        try:
            existing = config_path.read_text()
        except Exception as e:
            res["reason"] = f"Failed to read existing config: {e}"
            return res

    # Write atomically in same directory
    try:
        parent = str(config_path.parent)
        with tempfile.NamedTemporaryFile("w", delete=False, dir=parent, prefix=".ssh_config_tmp_") as tf:
            tf.write(existing)
            tf.write("\n")
            tf.write(entry)
            tf.flush()
            os.fsync(tf.fileno())
        os.replace(tf.name, str(config_path))
        res["written"] = True
        res["reason"] = "Config updated"
        return res
    except Exception as e:
        res["reason"] = f"Failed to write config: {e}"
        # Cleanup temp if left behind
        try:
            if 'tf' in locals() and hasattr(tf, 'name') and Path(tf.name).exists():
                Path(tf.name).unlink()
        except Exception:
            pass
        return res


def _construct_new_url(parsed: Dict, new_host: str) -> str:
    if parsed["style"] == "scp":
        user = f"{parsed['user']}@" if parsed.get('user') else ""
        return f"{user}{new_host}:{parsed['path']}"
    if parsed["style"] == "ssh":
        user = f"{parsed['user']}@" if parsed.get('user') else ""
        port = f":{parsed['port']}" if parsed.get('port') else ""
        return f"ssh://{user}{new_host}{port}/{parsed['path'].lstrip('/')}"
    # Fallback: return original
    return None


def _git_list_remotes(repo_path: str) -> List[str]:
    p = subprocess.run(["git", "-C", repo_path, "remote"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        return []
    return [r.strip() for r in p.stdout.splitlines() if r.strip()]


def _git_get_remote_url(repo_path: str, remote: str) -> Optional[str]:
    p = subprocess.run(["git", "-C", repo_path, "remote", "get-url", remote], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        return None
    return p.stdout.strip()


def _git_set_remote_url(repo_path: str, remote: str, new_url: str) -> Dict:
    p = subprocess.run(["git", "-C", repo_path, "remote", "set-url", remote, new_url], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return {"returncode": p.returncode, "stdout": p.stdout, "stderr": p.stderr}


def update_repo_remotes(repo_path: str, key_path: str, remotes: Optional[List[str]] = None, dry_run: bool = True, backup_dir: Optional[str] = None, yes: bool = False) -> List[Dict]:
    """Update remotes in a git repo to use an ssh Host alias that points to the provided key.

    Returns a list of result dicts for each processed remote.
    """
    results: List[Dict] = []
    repo = Path(repo_path)
    if not repo.exists():
        return [{"error": "repo not found", "repo_path": repo_path}]

    all_remotes = _git_list_remotes(str(repo))
    if remotes is None:
        targets = all_remotes
    else:
        targets = [r for r in remotes if r in all_remotes]

    for remote in targets:
        orig = _git_get_remote_url(str(repo), remote)
        if not orig:
            results.append({"remote": remote, "skipped": True, "reason": "failed to read remote url"})
            continue
        parsed = parse_git_remote(orig)
        if parsed["style"] not in ("scp", "ssh") or not parsed.get("host"):
            results.append({"remote": remote, "skipped": True, "reason": "non-ssh remote"})
            continue

        alias = make_host_alias(parsed["host"], parsed.get("path"), key_path)
        # Prepare config write
        conf_res = write_ssh_config_entry(alias, parsed["host"], parsed.get("user"), identity_file=key_path, port=parsed.get("port"), backup_dir=backup_dir, dry_run=dry_run)

        new_url = _construct_new_url(parsed, alias)
        if new_url is None:
            results.append({"remote": remote, "skipped": True, "reason": "cannot construct new url"})
            continue

        git_res = {"would_set": new_url, "changed": False}
        if not dry_run:
            if not yes:
                # For programmatic call, we treat lack of yes as interactive refusal.
                # Caller may pass yes=True to proceed non-interactively.
                results.append({"remote": remote, "skipped": True, "reason": "confirmation required (yes=False)"})
                continue
            gr = _git_set_remote_url(str(repo), remote, new_url)
            git_res = {"returncode": gr.get("returncode"), "stdout": gr.get("stdout"), "stderr": gr.get("stderr")}
            git_res["changed"] = gr.get("returncode") == 0

        results.append({"remote": remote, "original_url": orig, "new_url": new_url, "alias": alias, "config": conf_res, "git": git_res})

    return results
