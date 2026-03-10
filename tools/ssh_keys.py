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

    try:
        if not p.exists():
            result["reason"] = "File does not exist"
            return result
        if not p.is_file():
            result["reason"] = "Not a regular file"
            return result
    except PermissionError:
        result["reason"] = "Permission denied while accessing path"
        return result
    except OSError as e:
        result["reason"] = f"OS error: {e}"
        return result

    try:
        st = p.stat()
    except PermissionError:
        result["reason"] = "Permission denied while stat'ing file"
        return result
    except OSError as e:
        result["reason"] = f"Stat failed: {e}"
        return result

    mode = stat.S_IMODE(st.st_mode)
    # Permissions are considered OK if no group/other bits are set and file is not executable
    permissions_ok = ((mode & (stat.S_IRWXG | stat.S_IRWXO)) == 0) and ((mode & stat.S_IXUSR) == 0)
    result["permissions_ok"] = permissions_ok

    # Read the first chunk to identify PEM/OpenSSH headers
    try:
        with p.open("rb") as fh:
            head = fh.read(8192)
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

    candidates = set()
    common_names = {"id_rsa", "id_dsa", "id_ecdsa", "id_ed25519"}

    try:
        for entry in ssh_dir.iterdir():
            try:
                if not entry.is_file():
                    continue
            except OSError:
                # Skip items we cannot inspect
                continue

            if entry.name in common_names:
                candidates.add(entry)
                continue

            # Read a small portion to detect private key headers
            try:
                with entry.open("rb") as fh:
                    head = fh.read(8192)
            except Exception:
                continue

            up = head.upper()
            if b"-----BEGIN " in up and b"PRIVATE KEY" in up:
                candidates.add(entry)

    except PermissionError:
        return [{"path": str(ssh_dir), "type": None, "permissions_ok": False, "reason": "Permission denied listing ~/.ssh"}]

    for cand in sorted(candidates, key=lambda p: str(p)):
        results.append(validate_key(str(cand)))

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
