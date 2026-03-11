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
from pathlib import Path
from typing import List, Dict, Optional
import sys


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

    return results


def _print_discovered():
    keys = discover_keys()
    if not keys:
        print("No candidate private keys found under ~/.ssh")
        return
    import json
    print(json.dumps(keys, indent=2))


if __name__ == "__main__":
    _print_discovered()
