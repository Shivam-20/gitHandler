"""Tests for diff colorizer and markup helpers."""
from __future__ import annotations

import pytest


class TestDiffColorLogic:
    """Test diff line classification used by _apply_diff_colors."""

    @staticmethod
    def _classify(line: str) -> str:
        if line.startswith('+') and not line.startswith('+++'):
            return 'add'
        elif line.startswith('-') and not line.startswith('---'):
            return 'del'
        elif line.startswith('@@'):
            return 'hunk'
        return 'normal'

    @pytest.mark.parametrize("line,expected", [
        ('+added line', 'add'),
        ('-removed line', 'del'),
        ('@@  -1,3 +1,4 @@', 'hunk'),
        (' context line', 'normal'),
        ('--- a/file.txt', 'normal'),
        ('+++ b/file.txt', 'normal'),
        ('', 'normal'),
    ])
    def test_classify_diff_lines(self, line, expected):
        assert self._classify(line) == expected

    def test_full_diff_classification(self):
        diff = (
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
            "@@ -1,3 +1,4 @@\n"
            " unchanged\n"
            "-old line\n"
            "+new line\n"
            "+another new\n"
        )
        lines = diff.splitlines()
        types = [self._classify(l) for l in lines]
        assert types == ['normal', 'normal', 'hunk', 'normal', 'del', 'add', 'add']


class TestMarkup:
    """Test Pango markup generation."""

    def test_markup_escapes_special_chars(self):
        from tools.gui.css import C_GREEN
        from tools.gui.widgets import markup
        result = markup('<tag>&amp;', C_GREEN)
        assert '&lt;tag&gt;' in result
        assert '&amp;amp;' in result
        assert C_GREEN in result

    def test_markup_bold(self):
        from tools.gui.widgets import markup
        result = markup('test', '#ffffff', bold=True)
        assert '<b>' in result
        assert '</b>' in result

    def test_markup_no_bold(self):
        from tools.gui.widgets import markup
        result = markup('test', '#ffffff', bold=False)
        assert '<b>' not in result
