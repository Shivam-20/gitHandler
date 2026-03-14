"""Integration tests for GUI logic using real git repos (no display needed)."""
from __future__ import annotations

import pytest

from tools.core import run_git


class TestGitOperations:
    """Test the git operations used by the GUI pages."""

    def test_status_porcelain(self, tmp_git_repo):
        """Status page parsing: --porcelain=v1 format."""
        r = run_git(['status', '--porcelain=v1'], cwd=tmp_git_repo)
        assert r['returncode'] == 0
        lines = r['stdout'].splitlines()
        staged = [l for l in lines if l[0] != ' ' and l[0] != '?']
        unstaged = [l for l in lines if l[1] != ' ']
        assert len(staged) >= 1   # staged.txt
        assert len(unstaged) >= 1  # unstaged.txt

    def test_log_format_parsing(self, tmp_git_repo):
        """Log page: commit format with unit separator."""
        r = run_git(['log', '--format=%H\x1f%an\x1f%ad\x1f%s', '--date=short'],
                    cwd=tmp_git_repo)
        assert r['returncode'] == 0
        rows = []
        for line in r['stdout'].splitlines():
            parts = line.split('\x1f', 3)
            if len(parts) == 4:
                rows.append(parts)
        assert len(rows) == 2  # main has 2 commits
        assert rows[0][2]  # date is non-empty
        assert len(rows[0][0]) == 40  # full hash

    def test_log_graph_format(self, tmp_git_repo):
        """Log page with --graph flag."""
        r = run_git(['log', '--graph', '--format=%H\x1f%an\x1f%ad\x1f%s',
                     '--date=short', '--all'], cwd=tmp_git_repo)
        assert r['returncode'] == 0
        assert r['stdout'].strip()

    def test_branch_listing(self, tmp_git_repo):
        """Branch page: local branch listing."""
        r = run_git(['branch', '--format=%(refname:short)'], cwd=tmp_git_repo)
        assert r['returncode'] == 0
        branches = [b.strip() for b in r['stdout'].splitlines() if b.strip()]
        assert 'main' in branches
        assert 'feature' in branches

    def test_commits_page_format(self, tmp_git_repo):
        """Commits page: null-separated format."""
        r = run_git(['log', '--format=%h%x00%an%x00%s%x00%ar', 'main'],
                    cwd=tmp_git_repo)
        assert r['returncode'] == 0
        for line in r['stdout'].splitlines():
            parts = line.split('\x00')
            assert len(parts) >= 4

    def test_diff_output(self, tmp_git_repo):
        """Status page: diff for staged file."""
        r = run_git(['diff', '--cached'], cwd=tmp_git_repo)
        assert r['returncode'] == 0
        assert '+staged content' in r['stdout']

    def test_rev_parse_branch(self, tmp_git_repo):
        """Repo bar: current branch detection."""
        r = run_git(['rev-parse', '--abbrev-ref', 'HEAD'], cwd=tmp_git_repo)
        assert r['returncode'] == 0
        assert r['stdout'].strip() == 'main'

    def test_stash_list_empty(self, tmp_git_repo):
        """Branch page: stash list on repo with no stashes."""
        r = run_git(['stash', 'list', '--format=%gd|%ci|%s'], cwd=tmp_git_repo)
        assert r['returncode'] == 0
        assert r['stdout'].strip() == ''

    def test_worktree_list(self, tmp_git_repo):
        """Worktree page: porcelain format parsing."""
        r = run_git(['worktree', 'list', '--porcelain'], cwd=tmp_git_repo)
        assert r['returncode'] == 0
        assert 'worktree' in r['stdout']

    def test_blame_output(self, tmp_git_repo):
        """Status page: blame for a tracked file."""
        r = run_git(['blame', '--date=short', 'file1.txt'], cwd=tmp_git_repo)
        assert r['returncode'] == 0
        assert 'hello' in r['stdout']


class TestFilterLogic:
    """Test the in-memory filter logic used by commits and log pages."""

    def _make_commits(self):
        return [
            ('abc1234', 'Alice', 'feat: add login (#123)', '2d ago'),
            ('def5678', 'Bob', 'fix: resolve crash', '3d ago'),
            ('ghi9012', 'Alice', 'refactor: cleanup utils', '5d ago'),
            ('jkl3456', 'Charlie', 'feat: dashboard (!45)', '1w ago'),
        ]

    def test_filter_all_fields(self):
        commits = self._make_commits()
        q = 'alice'
        result = [c for c in commits
                  if q in c[0].lower() or q in c[1].lower() or q in c[2].lower()]
        assert len(result) == 2

    def test_filter_author_only(self):
        commits = self._make_commits()
        q = 'bob'
        result = [c for c in commits if q in c[1].lower()]
        assert len(result) == 1
        assert result[0][1] == 'Bob'

    def test_filter_message_only(self):
        commits = self._make_commits()
        q = 'crash'
        result = [c for c in commits if q in c[2].lower()]
        assert len(result) == 1

    def test_filter_hash_prefix(self):
        commits = self._make_commits()
        q = 'abc'
        result = [c for c in commits if c[0].lower().startswith(q)]
        assert len(result) == 1

    def test_filter_pr_number(self):
        commits = self._make_commits()
        q = '123'
        result = [c for c in commits
                  if f'#{q}' in c[2].lower() or f'!{q}' in c[2].lower()]
        assert len(result) == 1

    def test_filter_mr_number(self):
        """GitLab-style !45 merge request reference."""
        commits = self._make_commits()
        q = '45'
        result = [c for c in commits
                  if f'#{q}' in c[2].lower() or f'!{q}' in c[2].lower()]
        assert len(result) == 1
        assert 'dashboard' in result[0][2]

    def test_empty_query_returns_all(self):
        commits = self._make_commits()
        q = ''
        result = commits if not q else []
        assert len(result) == 4

    def test_no_match_returns_empty(self):
        commits = self._make_commits()
        q = 'zzzznotfound'
        result = [c for c in commits
                  if q in c[0].lower() or q in c[1].lower() or q in c[2].lower()]
        assert len(result) == 0


class TestWorktreeParser:
    """Test the worktree porcelain format parser."""

    def test_parse_worktrees(self):
        stdout = (
            "worktree /home/user/repo\n"
            "HEAD abc1234567890abc1234567890abc1234567890ab\n"
            "branch refs/heads/main\n"
            "\n"
            "worktree /home/user/repo-wt\n"
            "HEAD def5678901234def5678901234def5678901234de\n"
            "branch refs/heads/feature\n"
            "locked\n"
            "\n"
        )
        result = []
        for block in stdout.strip().split('\n\n'):
            d = {}
            for line in block.strip().splitlines():
                if ' ' in line:
                    k, v = line.split(' ', 1)
                    d[k] = v
                else:
                    d[line.strip()] = True
            if 'worktree' in d:
                result.append(d)

        assert len(result) == 2
        assert result[0]['worktree'] == '/home/user/repo'
        assert result[0].get('branch') == 'refs/heads/main'
        assert result[1].get('locked') is True

    def test_parse_bare_worktree(self):
        stdout = "worktree /home/user/repo.git\nHEAD abc123\nbare\n\n"
        result = []
        for block in stdout.strip().split('\n\n'):
            d = {}
            for line in block.strip().splitlines():
                if ' ' in line:
                    k, v = line.split(' ', 1)
                    d[k] = v
                else:
                    d[line.strip()] = True
            if 'worktree' in d:
                result.append(d)
        assert len(result) == 1
        assert result[0].get('bare') is True
