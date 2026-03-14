"""tools.gui — PyGitDesk GTK 3 GUI package.

Re-exports ``run_gui()`` from the main application module.
"""
from tools.gui_tk import run_gui  # noqa: F401

__all__ = ['run_gui']
