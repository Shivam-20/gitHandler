"""tools.ssh_keys

Discover and validate private SSH keys under ~/.ssh using only the standard library.

Functions:
- discover_keys() -> List[Dict]: scan ~/.ssh for candidate private keys and validate them
- validate_key(path: str) -> Dict: validate a specific key file

Each returned dict has keys: path, type, permissions_ok, reason

Run as a script to print discovered keys.
"""

from __future__ import annotations
import os
import stat
import hashlib
import subprocess
import json
import shutil
import shlex
from pathlib import Path
from typing import List, Dict, Optional
import sys

# Import core helpers when available
try:
    from tools import core
except Exception:
    import tools.core as core


def _detect_type_from_headers(data: bytes) -> Optional[str]:
    """Return a best-effort key type based on PEM/OpenSSH headers found in data."""
    headers = [
        (b"-----BEGIN OPENSSH PRIVATE KEY-----", "openssh"),
        (b"-----BEGIN RSA PRIVATE KEY-----", "rsa"),
        (b"-----BEGIN EC PRIVATE KEY-----", "ecdsa"),
        (b"-----BEGIN DSA PRIVATE KEY-----", "dsa"),
        (b"-----BEGIN PRIVATE KEY-----", "pkcs8"),
    ]
    up = data.upper()
    for h, t in headers:
        if h in up:
            return t
    # try ED25519 token search
    if b"ED25519" in up:
        return "ed25519"
    return None


def validate_key(path: str) -> Dict:
    """Validate a specific key path.

    Returns a dict: {"path": str, "type": Optional[str], "permissions_ok": bool, "reason": str}

    Reason is a human-readable explanation (OK or why validation failed).
    """
    p = Path(path).expanduser()
    result = {"path": str(p), "type": None, "permissions_ok": False, "reason": ""}

    # First, stat the file to obtain mode information (stat usually succeeds even when open would fail)
    try:
        st0 = p.stat()
    except PermissionError:
        result["reason"] = "Permission denied while accessing path"
        return result
    except OSError as e:
        result["reason"] = f"OS error: {e}"
        return result

    mode = stat.S_IMODE(st0.st_mode)
    # Permissions are considered OK if owner has read, no group/other bits, and file is not executable
    permissions_ok = (
        (mode & (stat.S_IRWXG | stat.S_IRWXO)) == 0
        and (mode & stat.S_IXUSR) == 0
        and (mode & stat.S_IRUSR) != 0
    )
    result["permissions_ok"] = permissions_ok

    # Attempt to open the file safely to read header. Use O_NOFOLLOW when available to avoid symlink attacks.
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    try:
        fd = os.open(str(p), flags)
    except OSError as e:
        # Could not open file (e.g., permission denied) — still return permissions_ok based on stat
        result["reason"] = f"Failed to open file: {e}"
        return result

    try:
        try:
            st = os.fstat(fd)
        except OSError as e:
            result["reason"] = f"fstat failed: {e}"
            return result

        # Ensure we opened a regular file
        if not stat.S_ISREG(st.st_mode):
            result["reason"] = "Not a regular file"
            return result

        # Basic TOCTOU check: ensure inode/dev didn't change between stat and open
        try:
            if st0.st_ino != st.st_ino or st0.st_dev != st.st_dev:
                result["reason"] = "File changed between stat and open"
                return result
        except AttributeError:
            # Platforms without st_ino/st_dev: skip this check
            pass

        # Read header from file descriptor
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            head = os.read(fd, 8192)
        except Exception as e:
            result["reason"] = f"Failed to read file: {e}"
            return result

        ktype = _detect_type_from_headers(head)
        result["type"] = ktype

        if ktype is None:
            result["reason"] = "No recognized private key header found"
        else:
            if permissions_ok:
                result["reason"] = "OK"
            else:
                result["reason"] = f"Permissions too open: {oct(mode)}"
        return result
    finally:
        try:
            os.close(fd)
        except Exception:
            pass


def compute_fingerprint(path: str, max_read: int = 8192) -> Optional[str]:
    """Compute a stable fingerprint for a key file using SHA256 of the first bytes.

    Returns a 'sha256:<hex>' string or None if the file cannot be read.
    """
    p = Path(path).expanduser()
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(str(p), flags)
    except OSError:
        return None
    try:
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            data = os.read(fd, max_read)
        except Exception:
            return None
        h = hashlib.sha256(data).hexdigest()
        return f"sha256:{h}"
    finally:
        try:
            os.close(fd)
        except Exception:
            pass


def discover_keys() -> List[Dict]:
    """Discover candidate private key files in ~/.ssh and validate them.

    Looks for common filenames (id_rsa, id_dsa, id_ecdsa, id_ed25519) and any file
    that contains a PEM/OpenSSH private key header in the first 8KiB.
    """
    ssh_dir = Path("~/.ssh").expanduser()
    results: List[Dict] = []

    if not ssh_dir.exists():
        return [{"path": str(ssh_dir), "type": None, "permissions_ok": False, "reason": "SSH directory not found"}]
    if not ssh_dir.is_dir():
        return [{"path": str(ssh_dir), "type": None, "permissions_ok": False, "reason": "~/.ssh exists but is not a directory"}]

    # Iterate deterministically and validate each file safely inside validate_key().
    try:
        for entry in sorted(ssh_dir.iterdir(), key=lambda p: str(p)):
            try:
                if not entry.is_file():
                    continue
            except OSError:
                # Skip items we cannot inspect
                continue

            res = validate_key(str(entry))
            if res.get("type") is not None:
                results.append(res)
    except PermissionError:
        return [{"path": str(ssh_dir), "type": None, "permissions_ok": False, "reason": "Permission denied listing ~/.ssh"}]

    # Compute fingerprints and detect duplicates
    from collections import defaultdict

    for r in results:
        try:
            r["fingerprint"] = compute_fingerprint(r["path"])
        except Exception:
            r["fingerprint"] = None

    groups: Dict[str, List[Dict]] = defaultdict(list)
    for r in results:
        fp = r.get("fingerprint")
        if fp:
            groups[fp].append(r)

    for fp, items in groups.items():
        if len(items) > 1:
            for it in items:
                it["duplicate"] = True

    for r in results:
        r.setdefault("duplicate", False)

    return results


def _print_discovered(json_out: bool = False):
    keys = discover_keys()
    if not keys:
        print("No candidate private keys found under ~/.ssh")
        return
    import json as _json
    if json_out:
        print(_json.dumps(keys, indent=2))
    else:
        for k in keys:
            print(f"{k['path']}: type={k['type']}, permissions_ok={k['permissions_ok']}, reason={k['reason']}")


def fix_permissions_for_file(pth: str, backup_dir: Optional[str] = None, dry_run: bool = True) -> Dict:
    """Attempt to make a single key's permissions secure (owner read/write only).

    Returns a dict with keys: path, changed (bool), current_mode, would_set_mode, backup (path or None), reason
    """
    from shutil import copy2
    import time as _time

    p = Path(pth).expanduser()
    res = {"path": str(p), "changed": False, "current_mode": None, "would_set_mode": None, "backup": None, "reason": ""}

    try:
        st = p.stat()
    except Exception as e:
        res["reason"] = f"Stat failed: {e}"
        return res

    mode = stat.S_IMODE(st.st_mode)
    res["current_mode"] = oct(mode)

    secure_mode = 0o600
    permissions_ok = (
        (mode & (stat.S_IRWXG | stat.S_IRWXO)) == 0
        and (mode & stat.S_IXUSR) == 0
        and (mode & stat.S_IRUSR) != 0
    )

    if permissions_ok:
        res["reason"] = "Already secure"
        return res

    res["would_set_mode"] = oct(secure_mode)

    if dry_run:
        res["reason"] = "Dry run"
        return res

    # Perform backup if requested
    if backup_dir:
        bdir = Path(backup_dir).expanduser()
        try:
            bdir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            res["reason"] = f"Failed to create backup dir: {e}"
            return res
        bakname = f"{p.name}.{int(_time.time())}.bak"
        bpath = bdir / bakname
        try:
            copy2(str(p), str(bpath))
            res["backup"] = str(bpath)
        except Exception as e:
            res["reason"] = f"Backup failed: {e}"
            return res

    # Apply chmod
    try:
        os.chmod(str(p), secure_mode)
    except Exception as e:
        res["reason"] = f"chmod failed: {e}"
        return res

    try:
        new_mode = stat.S_IMODE(p.stat().st_mode)
    except Exception as e:
        res["reason"] = f"Stat after chmod failed: {e}"
        return res

    res["changed"] = new_mode != mode
    res["current_mode"] = oct(new_mode)
    res["reason"] = "Permissions updated" if res["changed"] else "Permissions unchanged"
    return res


def fix_permissions(paths: Optional[list] = None, backup_dir: Optional[str] = None, dry_run: bool = True) -> List[Dict]:
    """Fix permissions for a list of paths, or scan ~/.ssh when paths is None."""
    results: List[Dict] = []
    if paths is None:
        keys = discover_keys()
        paths = [k["path"] for k in keys]
    for p in paths:
        results.append(fix_permissions_for_file(p, backup_dir=backup_dir, dry_run=dry_run))
    return results


def add_to_agent(path: str, start_agent: bool = False) -> Dict:
    """Add a key to ssh-agent; if start_agent=True attempt to start a new agent and set env vars.

    Returns a dict: {path, added (bool), stdout, stderr, reason}
    """
    res = {"path": str(path), "added": False, "stdout": None, "stderr": None, "reason": ""}
    if shutil.which("ssh-add") is None:
        res["reason"] = "ssh-add not found"
        return res

    env = os.environ.copy()
    if start_agent:
        try:
            p = subprocess.run(["ssh-agent", "-s"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            out = p.stdout or ""
            for line in out.splitlines():
                parts = line.split(";")[0].strip()
                if "=" in parts:
                    k, v = parts.split("=", 1)
                    env[k] = v
        except Exception as e:
            res["reason"] = f"start agent failed: {e}"
            return res

    try:
        p2 = subprocess.run(["ssh-add", str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        res["added"] = p2.returncode == 0
        res["stdout"] = p2.stdout
        res["stderr"] = p2.stderr
    except Exception as e:
        res["reason"] = str(e)
    return res


def _main():
    import argparse as _argparse
    import json as _json
    parser = _argparse.ArgumentParser(prog="ssh_keys", description="Discover and manage SSH private keys under ~/.ssh")
    sub = parser.add_subparsers(dest="command")
    sub.required = False

    d = sub.add_parser("discover", help="Discover keys")
    d.add_argument("--json", action="store_true", dest="json_out", help="Output JSON")

    f = sub.add_parser("fix-permissions", help="Fix permissions for keys")
    f.add_argument("--path", "-p", action="append", help="Specific key path (repeatable). If omitted scan ~/.ssh")
    f.add_argument("--dry-run", action="store_true", help="Show changes without applying")
    f.add_argument("--backup-dir", help="Directory to store backups before changing permissions")
    f.add_argument("--yes", "-y", action="store_true", help="Apply without prompting (use with care)")
    f.add_argument("--json", action="store_true", dest="json_out", help="Output JSON")

    a = sub.add_parser("add-to-agent", help="Add keys to ssh-agent")
    a.add_argument("--path", "-p", action="append", help="Specific key path (repeatable). If omitted scan ~/.ssh")
    a.add_argument("--start-agent", action="store_true", help="Attempt to start ssh-agent if none present")
    a.add_argument("--json", action="store_true", dest="json_out", help="Output JSON")

    m = sub.add_parser("make-wrapper", help="Create a repo-local git SSH wrapper script")
    m.add_argument("--repo", required=True, help="Repository directory to write wrapper into")
    m.add_argument("--key", required=True, help="Path to private key")
    m.add_argument("--name", default="git-ssh-wrapper", help="Filename for the wrapper")
    m.add_argument("--json", action="store_true", dest="json_out", help="Output JSON")

    args = parser.parse_args()

    if args.command == "add-to-agent":
        paths = args.path
        if paths is None:
            keys = discover_keys()
            paths = [k["path"] for k in keys]
        results = [add_to_agent(p, start_agent=args.start_agent) for p in paths]
        if args.json_out:
            print(_json.dumps(results, indent=2))
        else:
            for r in results:
                print(f"{r['path']}: added={r['added']}, reason={r.get('reason')}")
        return

    if args.command == "make-wrapper":
        wrapper = core.create_repo_wrapper(args.repo, args.key, wrapper_name=args.name)
        if args.json_out:
            print(_json.dumps({"wrapper": wrapper}, indent=2))
        else:
            print(f"Created wrapper: {wrapper}")
        return

    if args.command == "fix-permissions":
        paths = args.path
        res = fix_permissions(paths=paths, backup_dir=args.backup_dir, dry_run=args.dry_run)
        if args.json_out:
            print(_json.dumps(res, indent=2))
        else:
            for r in res:
                print(f"{r['path']}: changed={r['changed']}, reason={r['reason']}, backup={r.get('backup')}, mode={r.get('current_mode')}")
        return

    # default to discover
    _print_discovered(json_out=(hasattr(args, 'json_out') and args.json_out))


if __name__ == "__main__":
    _main()
