"""Shared fixtures for PyGitDesk tests."""
from __future__ import annotations

import os
import subprocess

import pytest


@pytest.fixture
def tmp_git_repo(tmp_path):
    """Create a temporary git repo with known state for integration tests.

    Returns the repo path. Repo has:
      - 3 commits (init, second, third)
      - 2 branches (main, feature)
      - 1 staged file, 1 unstaged file
    """
    repo = tmp_path / 'test_repo'
    repo.mkdir()
    env = {**os.environ, 'GIT_AUTHOR_NAME': 'Test', 'GIT_AUTHOR_EMAIL': 'test@test.com',
           'GIT_COMMITTER_NAME': 'Test', 'GIT_COMMITTER_EMAIL': 'test@test.com'}

    def _run(*args):
        return subprocess.run(['git'] + list(args), cwd=str(repo), env=env,
                              capture_output=True, text=True)

    _run('init', '-b', 'main')
    _run('config', 'user.email', 'test@test.com')
    _run('config', 'user.name', 'Test')

    # Commit 1
    (repo / 'file1.txt').write_text('hello\n')
    _run('add', 'file1.txt')
    _run('commit', '-m', 'feat: initial commit')

    # Commit 2
    (repo / 'file2.txt').write_text('world\n')
    _run('add', 'file2.txt')
    _run('commit', '-m', 'fix: add file2')

    # Feature branch
    _run('checkout', '-b', 'feature')
    (repo / 'feature.txt').write_text('feature work\n')
    _run('add', 'feature.txt')
    _run('commit', '-m', 'feat: add feature file')

    # Back to main
    _run('checkout', 'main')

    # Create staged and unstaged changes
    (repo / 'staged.txt').write_text('staged content\n')
    _run('add', 'staged.txt')
    (repo / 'unstaged.txt').write_text('unstaged content\n')

    return str(repo)
