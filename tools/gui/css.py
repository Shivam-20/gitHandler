"""tools.gui.css — PyGitDesk CSS and colour constants."""
from __future__ import annotations

# ── Colours (PyGitDesk palette) ──────────────────────────────────────────────
C_GREEN  = '#4CAF50'
C_RED    = '#E64A19'
C_ORANGE = '#FF5722'
C_BLUE   = '#1a73e8'
C_GRAY   = '#757575'
C_DIM    = '#9E9E9E'
C_ACCENT = '#E64A19'

# ── PyGitDesk-style CSS ─────────────────────────────────────────────────────
APP_CSS = """
/* ── Sidebar ────────────────────────────────────────────── */
.sidebar {
    background-color: #555555;
}
.sidebar-brand {
    color: #FFFFFF;
    font-size: 1.15em;
    font-weight: bold;
    padding: 16px 14px 8px 14px;
}
.sidebar-section {
    color: rgba(255,255,255,0.55);
    font-size: 0.72em;
    font-weight: bold;
    letter-spacing: 0.5px;
    padding-left: 14px;
    padding-top: 14px;
    padding-bottom: 2px;
}
.nav-button {
    padding: 6px 10px;
    border-radius: 8px;
    border: none;
    background: transparent;
    box-shadow: none;
    color: #FFFFFF;
}
.nav-button:hover {
    background-color: rgba(255,255,255,0.12);
}
.nav-button.nav-active {
    background-color: rgba(255,255,255,0.22);
    color: #FFFFFF;
    font-weight: bold;
}
.nav-button image {
    color: #FFFFFF;
    -gtk-icon-style: symbolic;
}

/* ── Repo strip ─────────────────────────────────────────── */
.repo-strip {
    padding: 5px 14px 5px 14px;
    border-bottom: 1px solid alpha(@theme_fg_color, 0.10);
}

/* ── Branch badge ───────────────────────────────────────── */
.branch-badge {
    background-color: alpha(#4CAF50, 0.18);
    color: #4CAF50;
    border-radius: 12px;
    padding: 2px 10px;
    font-size: 0.85em;
    font-weight: bold;
}

/* ── Content area — inherit theme bg so dark/light both work ── */
.content-bg {
    background-color: alpha(@theme_bg_color, 0.95);
}

/* ── Buttons (PyGitDesk pill style) ─────────────────────── */
button.suggested-action {
    background-image: none;
    background-color: #E64A19;
    color: #FFFFFF;
    border-radius: 20px;
    border: none;
    padding: 6px 18px;
    font-weight: bold;
    box-shadow: none;
}
button.suggested-action:hover {
    background-color: #D84315;
}
button.destructive-action {
    background-image: none;
    background-color: #C62828;
    color: #FFFFFF;
    border-radius: 20px;
    border: none;
    padding: 6px 18px;
    font-weight: bold;
    box-shadow: none;
}
button.destructive-action:hover {
    background-color: #B71C1C;
}

/* ── Misc. ──────────────────────────────────────────────── */
.diff-view {
    font-family: monospace;
}
.dim-label {
    color: alpha(@theme_fg_color, 0.50);
    font-size: 0.88em;
}
entry.commit-error {
    border-color: #E64A19;
    box-shadow: inset 0 0 0 1px #E64A19;
    background-color: alpha(#E64A19, 0.06);
}

/* ── Status bar ─────────────────────────────────────────── */
.status-bar {
    background-color: alpha(@theme_bg_color, 0.85);
    padding: 4px 12px;
}

/* ── Section headings (theme-aware) ─────────────────────── */
.section-heading {
    font-weight: bold;
    font-size: 1.05em;
    color: @theme_fg_color;
}
"""
