#!/usr/bin/env python3
"""
tools.core - small utility helpers for git operations.

This module provides:
- build_ssh_command(key_path: str) -> List[str]
- run_git(args: List[str], cwd: Optional[str]=None, env_overrides: Optional[Dict]=None) -> Dict
- validate_repo_url(url: str) -> bool

Only uses the Python standard library and handles errors gracefully.
"""
from __future__ import annotations

import os
import subprocess
import re
from typing import List, Optional, Dict


def build_ssh_command(key_path: str) -> List[str]:
    """Return a command list suitable for GIT_SSH_COMMAND to use the given private key.

    Example:
        ['ssh', '-i', key_path, '-o', 'IdentitiesOnly=yes']
    """
    if not key_path or not isinstance(key_path, str):
        raise ValueError("key_path must be a non-empty string")
    return ['ssh', '-i', key_path, '-o', 'IdentitiesOnly=yes']


def run_git(args: List[str], cwd: Optional[str] = None, env_overrides: Optional[Dict] = None) -> Dict:
    """Run git with the provided arguments.

    - args: list of git arguments (e.g. ['status'])
    - cwd: optional working directory
    - env_overrides: dict of environment variables to set/override for the subprocess

    Returns a dict: {'returncode': int, 'stdout': str, 'stderr': str}
    Errors are captured in 'stderr' and returncode is -1 for unexpected exceptions.
    """
    if not isinstance(args, (list, tuple)):
        raise TypeError('args must be a list of strings')

    cmd = ['git'] + [str(a) for a in args]
    env = os.environ.copy()
    if env_overrides:
        try:
            for k, v in env_overrides.items():
                env[str(k)] = str(v)
        except Exception:
            # fall back to ignoring env overrides if they are malformed
            pass

    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return {
            'returncode': proc.returncode,
            'stdout': proc.stdout or '',
            'stderr': proc.stderr or '',
        }
    except FileNotFoundError as e:
        return {'returncode': -1, 'stdout': '', 'stderr': f'git not found: {e}'}
    except Exception as e:
        return {'returncode': -1, 'stdout': '', 'stderr': f'error running git: {e}'}


def validate_repo_url(url: str) -> bool:
    """Basic validation for common git repo URL formats.

    Accepts:
      - scp-like SSH: git@host:owner/repo.git
      - scheme-based: ssh://, git://, https://, http://, git+ssh://

    Returns True for recognized formats, False otherwise.
    """
    if not url or not isinstance(url, str):
        return False
    s = url.strip()
    # scheme-based URLs (git, ssh, http, https, git+ssh)
    if re.match(r'^(git\+ssh|ssh|git|https?|git\+https)://', s, re.IGNORECASE):
        # quick sanity check: must contain a netloc/host and a path
        try:
            from urllib.parse import urlparse

            p = urlparse(s)
            if p.scheme and p.netloc and p.path:
                return True
        except Exception:
            return False

    # scp-like syntax: user@host:owner/repo(.git)
    if re.match(r'^[\w.-]+@[\w.-]+:[\w./~-]+(?:\.git)?$', s):
        return True

    return False


if __name__ == '__main__':
    # Simple example usage when run as a script
    import argparse

    parser = argparse.ArgumentParser(description='tools.core example usage')
    parser.add_argument('--key', help='path to ssh key', default='~/.ssh/id_rsa')
    parser.add_argument('--git-args', nargs='*', help='git arguments to run', default=['--version'])
    parser.add_argument('--validate', help='repo URL to validate', default='git@github.com:user/repo.git')
    args = parser.parse_args()

    key = os.path.expanduser(args.key)
    print('SSH command:', build_ssh_command(key))
    result = run_git(args.git_args)
    print('git returncode:', result['returncode'])
    print('git stdout:', (result['stdout'] or '').strip())
    print('git stderr:', (result['stderr'] or '').strip())
    print('validate', args.validate, '->', validate_repo_url(args.validate))
