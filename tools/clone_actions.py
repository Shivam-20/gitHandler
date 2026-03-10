"""tools.clone_actions

Utilities for performing common post-clone git actions used by the CLI.

Functions:
- list_branches(repo_path: str) -> List[str]
- checkout_branch(repo_path: str, branch: str) -> Dict
- show_remote(repo_path: str) -> str
- run_custom(repo_path: str, args: List[str]) -> Dict

These helpers use tools.core.run_git and return structured outputs. Errors are handled
and returned in stderr / as informative strings where appropriate.
"""
from __future__ import annotations

import os
from typing import List, Dict, Optional

from tools.core import run_git


def _validate_repo_path(repo_path: str) -> Optional[str]:
    """Return an error message string if repo_path is invalid, otherwise None."""
    if not repo_path or not isinstance(repo_path, str):
        return "repo_path must be a non-empty string"
    if not os.path.isdir(repo_path):
        return f"repo_path does not exist or is not a directory: {repo_path}"
    # It's okay if .git is missing (worktrees, bare repos, etc.) — we rely on git to report errors.
    return None


def list_branches(repo_path: str) -> List[str]:
    """List local and remote branches for the repository at repo_path.

    Returns a list of branch names. Remote branches are returned in the form
    "remote/name" (e.g. "origin/main"). On error, returns a single-item list
    whose element begins with "ERROR:" describing the problem.
    """
    err = _validate_repo_path(repo_path)
    if err:
        return [f"ERROR: {err}"]

    result = run_git(['branch', '--all', '--no-color'], cwd=repo_path)
    if result.get('returncode') != 0:
        msg = (result.get('stderr') or result.get('stdout') or '').strip()
        return [f"ERROR: git branch failed: {msg}"]

    lines = (result.get('stdout') or '').splitlines()
    branches: List[str] = []
    seen = set()

    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        # skip symbolic refs like: remotes/origin/HEAD -> origin/main
        if '->' in ln:
            continue
        # remove leading '*' for current branch
        if ln.startswith('* '):
            ln = ln[2:].strip()
        # normalize remote branches by removing the leading 'remotes/' prefix
        if ln.startswith('remotes/'):
            ln = ln[len('remotes/') :]
        if ln not in seen:
            branches.append(ln)
            seen.add(ln)

    return branches


def checkout_branch(repo_path: str, branch: str) -> Dict:
    """Checkout the given branch in the repository at repo_path.

    Returns the dict result from tools.core.run_git (keys: returncode, stdout, stderr).
    If a simple "git checkout <branch>" fails but a remote branch exists with that
    name (e.g. origin/<branch>), the function will attempt to create a local branch
    that tracks the remote (git checkout -b <branch> origin/<branch>).
    """
    err = _validate_repo_path(repo_path)
    if err:
        return {'returncode': -1, 'stdout': '', 'stderr': err}
    if not branch or not isinstance(branch, str):
        return {'returncode': -1, 'stdout': '', 'stderr': 'branch must be a non-empty string'}

    res = run_git(['checkout', branch], cwd=repo_path)
    if res.get('returncode') == 0:
        return res

    # Attempt fallback: find remote branch with the requested name and create local tracking branch
    branches = list_branches(repo_path)
    if branches and not (len(branches) == 1 and branches[0].startswith('ERROR:')):
        # look for a remote branch like "origin/<branch>" or "<remote>/<branch>"
        candidate = None
        for b in branches:
            if '/' in b and b.split('/', 1)[1] == branch:
                candidate = b
                break
        if candidate:
            # candidate is like 'origin/feature/foo'
            remote, _, remote_branch = candidate.partition('/')
            attempt = run_git(['checkout', '-b', branch, f'{remote}/{remote_branch}'], cwd=repo_path)
            if attempt.get('returncode') == 0:
                return attempt
            # if attempt failed, fall through and return original error augmented with attempt stderr
            combined_stderr = (res.get('stderr') or '').strip()
            attempt_stderr = (attempt.get('stderr') or '').strip()
            combined = '\n'.join([s for s in [combined_stderr, attempt_stderr] if s])
            return {'returncode': attempt.get('returncode', -1), 'stdout': attempt.get('stdout', ''), 'stderr': combined}

    # No fallback available — return original error
    return res


def show_remote(repo_path: str) -> str:
    """Return the remote URL for 'origin' if available, otherwise the first remote's URL.

    On error, returns a string that starts with "ERROR:" describing the problem.
    """
    err = _validate_repo_path(repo_path)
    if err:
        return f"ERROR: {err}"

    # Preferred: git remote get-url origin
    res = run_git(['remote', 'get-url', 'origin'], cwd=repo_path)
    if res.get('returncode') == 0 and (res.get('stdout') or '').strip():
        return (res.get('stdout') or '').strip()

    # Fallback: parse `git remote -v` and extract the first URL
    res2 = run_git(['remote', '-v'], cwd=repo_path)
    if res2.get('returncode') != 0:
        return f"ERROR: git remote failed: {(res2.get('stderr') or '').strip()}"

    out = (res2.get('stdout') or '').strip()
    if not out:
        return ''

    # Example line: "origin\tgit@github.com:user/repo.git (fetch)"
    first_line = out.splitlines()[0]
    parts = first_line.split()
    if len(parts) >= 2:
        return parts[1]
    return first_line


def run_custom(repo_path: str, args: List[str]) -> Dict:
    """Run an arbitrary git command (args is a list of git arguments) in repo_path.

    Returns the dict result from tools.core.run_git.
    On invalid inputs returns a dict with returncode -1 and an explanatory stderr.
    """
    err = _validate_repo_path(repo_path)
    if err:
        return {'returncode': -1, 'stdout': '', 'stderr': err}
    if not isinstance(args, (list, tuple)) or not args:
        return {'returncode': -1, 'stdout': '', 'stderr': 'args must be a non-empty list of git arguments'}

    try:
        args = [str(a) for a in args]
    except Exception as e:
        return {'returncode': -1, 'stdout': '', 'stderr': f'invalid args: {e}'}

    return run_git(args, cwd=repo_path)


__all__ = [
    'list_branches',
    'checkout_branch',
    'show_remote',
    'run_custom',
]
