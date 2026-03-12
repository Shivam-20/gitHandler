"""tools.gui_tk — SSH Git Manager (GTK 3)

Pages
─────
  Clone Repo   · Status      · Log & Commits
  Branches     · Merge/Rebase · Remotes
  Worktrees    · SSH Keys

Falls back to a Tkinter hint-window if GTK / PyGObject is unavailable.
"""
from __future__ import annotations

import json
import os
import shlex
import sys
import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional

try:
    from tools import ssh_keys, core, clone_actions, ssh_config
except Exception:
    import tools.ssh_keys as ssh_keys          # type: ignore
    import tools.core as core                  # type: ignore
    import tools.clone_actions as clone_actions  # type: ignore
    import tools.ssh_config as ssh_config      # type: ignore

# ── GTK import ────────────────────────────────────────────────────────────────
_GTK_OK = False
try:
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk, GLib, Pango, Gdk
    _GTK_OK = True
except Exception:
    pass

# ── Colours (PyGitDesk palette) ────────────────────────────────────────────────
C_GREEN  = '#4CAF50'
C_RED    = '#E64A19'
C_ORANGE = '#FF5722'
C_BLUE   = '#1a73e8'
C_GRAY   = '#757575'
C_DIM    = '#9E9E9E'
C_ACCENT = '#E64A19'

_GtkBoxBase = Gtk.Box if _GTK_OK else object  # type: ignore[name-defined]

# ── PyGitDesk-style CSS ───────────────────────────────────────────────────────
_APP_CSS = """
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

# ── Recent repos ──────────────────────────────────────────────────────────────
_RECENT_FILE = Path.home() / '.local' / 'share' / 'git-ssh-helper' / 'recent.json'


def _load_recent() -> List[str]:
    try:
        return json.loads(_RECENT_FILE.read_text())[:10]
    except Exception:
        return []


def _add_recent(path: str) -> None:
    try:
        lst = [p for p in _load_recent() if p != path]
        lst.insert(0, path)
        _RECENT_FILE.parent.mkdir(parents=True, exist_ok=True)
        _RECENT_FILE.write_text(json.dumps(lst[:10]))
    except Exception:
        pass


# ── Pango markup ──────────────────────────────────────────────────────────────
def _markup(text: str, color: str, bold: bool = False) -> str:
    b, eb = ('<b>', '</b>') if bold else ('', '')
    return f'<span foreground="{color}">{b}{GLib.markup_escape_text(text)}{eb}</span>' \
        if _GTK_OK else text


# ── Git runner ────────────────────────────────────────────────────────────────
def _git(repo: str, *args) -> Dict:
    return core.run_git(list(args), cwd=repo)


# ── Diff colouriser ───────────────────────────────────────────────────────────
def _apply_diff_colors(buf, text: str) -> None:
    buf.set_text('')
    for line in text.splitlines(keepends=True):
        it = buf.get_end_iter()
        if line.startswith('+') and not line.startswith('+++'):
            buf.insert_with_tags_by_name(it, line, 'diff-add')
        elif line.startswith('-') and not line.startswith('---'):
            buf.insert_with_tags_by_name(it, line, 'diff-del')
        elif line.startswith('@@'):
            buf.insert_with_tags_by_name(it, line, 'diff-hunk')
        else:
            buf.insert(it, line)


def _make_diff_view() -> tuple:
    """Return (scrolled_window, text_view, text_buffer) ready for diff display."""
    scroll = Gtk.ScrolledWindow()
    scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    tv = Gtk.TextView()
    tv.set_editable(False)
    tv.set_cursor_visible(False)
    tv.set_monospace(True)
    tv.set_wrap_mode(Gtk.WrapMode.NONE)
    tv.set_margin_start(8)
    tv.set_margin_top(4)
    buf = tv.get_buffer()
    buf.create_tag('diff-add',  foreground=C_GREEN)
    buf.create_tag('diff-del',  foreground=C_RED)
    buf.create_tag('diff-hunk', foreground=C_BLUE)
    scroll.add(tv)
    return scroll, tv, buf


# ── Dialog helpers ────────────────────────────────────────────────────────────
def _ask_string(parent, title: str, prompt: str, default: str = '') -> Optional[str]:
    dlg = Gtk.Dialog(title=title, transient_for=parent,
                     flags=Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT)
    dlg.set_default_size(420, -1)
    dlg.add_button('Cancel', Gtk.ResponseType.CANCEL)
    ok = dlg.add_button('OK', Gtk.ResponseType.OK)
    ok.get_style_context().add_class('suggested-action')
    dlg.set_default_response(Gtk.ResponseType.OK)
    box = dlg.get_content_area()
    box.set_margin_top(16); box.set_margin_bottom(16)
    box.set_margin_start(16); box.set_margin_end(16)
    box.set_spacing(8)
    box.pack_start(Gtk.Label(label=prompt, xalign=0.0), False, False, 0)
    entry = Gtk.Entry()
    entry.set_text(default)
    entry.set_activates_default(True)
    box.pack_start(entry, False, False, 0)
    dlg.show_all()
    resp = dlg.run()
    txt = entry.get_text().strip()
    dlg.destroy()
    return txt if resp == Gtk.ResponseType.OK and txt else None


def _ask_yes_no(parent, title: str, message: str = '') -> bool:
    dlg = Gtk.MessageDialog(transient_for=parent, flags=Gtk.DialogFlags.MODAL,
                             message_type=Gtk.MessageType.QUESTION,
                             buttons=Gtk.ButtonsType.YES_NO, text=title)
    if message:
        dlg.format_secondary_text(message)
    resp = dlg.run(); dlg.destroy()
    return resp == Gtk.ResponseType.YES


def _show_error(parent, title: str, message: str = '') -> None:
    dlg = Gtk.MessageDialog(transient_for=parent, flags=Gtk.DialogFlags.MODAL,
                             message_type=Gtk.MessageType.ERROR,
                             buttons=Gtk.ButtonsType.CLOSE, text=title)
    if message:
        dlg.format_secondary_text(message)
    dlg.run(); dlg.destroy()


def _browse_dir(parent, title: str = 'Select directory') -> Optional[str]:
    dlg = Gtk.FileChooserDialog(title=title, transient_for=parent,
                                 action=Gtk.FileChooserAction.SELECT_FOLDER)
    dlg.add_button('Cancel', Gtk.ResponseType.CANCEL)
    dlg.add_button('Select', Gtk.ResponseType.OK)
    resp = dlg.run(); path = dlg.get_filename(); dlg.destroy()
    return path if resp == Gtk.ResponseType.OK else None


def _browse_file(parent, title: str = 'Select file',
                 start_dir: str = '~') -> Optional[str]:
    dlg = Gtk.FileChooserDialog(title=title, transient_for=parent,
                                 action=Gtk.FileChooserAction.OPEN)
    dlg.add_button('Cancel', Gtk.ResponseType.CANCEL)
    dlg.add_button('Select', Gtk.ResponseType.OK)
    dlg.set_current_folder(os.path.expanduser(start_dir))
    resp = dlg.run(); path = dlg.get_filename(); dlg.destroy()
    return path if resp == Gtk.ResponseType.OK else None


# ── Global repo bar ───────────────────────────────────────────────────────────
class _RepoBar(_GtkBoxBase):
    def __init__(self, parent_win, on_load: Callable[[str], None]):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.get_style_context().add_class('repo-strip')
        self._win = parent_win
        self._on_load = on_load

        lbl = Gtk.Label(label='Repo:')
        lbl.set_width_chars(5)
        self.pack_start(lbl, False, False, 0)

        self._entry = Gtk.Entry()
        self._entry.set_hexpand(True)
        self._entry.set_placeholder_text('/path/to/repository')
        self._entry.connect('activate', lambda _: self._do_load())
        self.pack_start(self._entry, True, True, 0)

        btn_browse = Gtk.Button(label='Browse…')
        btn_browse.connect('clicked', self._browse)
        self.pack_start(btn_browse, False, False, 0)

        self._recent_btn = Gtk.MenuButton(label='Recent ▾')
        self._recent_menu = Gtk.Menu()
        self._recent_btn.set_popup(self._recent_menu)
        self.pack_start(self._recent_btn, False, False, 0)

        btn_load = Gtk.Button(label='↺ Load')
        btn_load.get_style_context().add_class('suggested-action')
        btn_load.connect('clicked', lambda _: self._do_load())
        self.pack_start(btn_load, False, False, 0)

        sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        sep.set_margin_start(4); sep.set_margin_end(4)
        self.pack_start(sep, False, False, 0)

        self._branch_lbl = Gtk.Label()
        self._branch_lbl.get_style_context().add_class('branch-badge')
        self._branch_lbl.set_markup(_markup('no repo', C_GRAY))
        self.pack_start(self._branch_lbl, False, False, 0)

        self._rebuild_recent_menu()

    def set_path(self, path: str) -> None:
        self._entry.set_text(path)

    def get_path(self) -> str:
        return self._entry.get_text().strip()

    def update_branch(self, branch: str) -> None:
        self._branch_lbl.set_markup(
            _markup(f'⑂  {branch}', C_GREEN, bold=True) if branch
            else _markup('no repo', C_GRAY))

    def _browse(self, *_):
        p = _browse_dir(self._win, 'Select git repository')
        if p:
            self._entry.set_text(p)
            self._do_load()

    def _do_load(self, *_):
        rd = self._entry.get_text().strip()
        if not rd or not Path(rd).is_dir():
            _show_error(self._win, 'Not a directory', rd or '(empty)'); return
        self._on_load(rd)

    def _rebuild_recent_menu(self):
        for child in self._recent_menu.get_children():
            self._recent_menu.remove(child)
        for p in _load_recent():
            item = Gtk.MenuItem(label=p)
            item.connect('activate', lambda _, pp=p: [self._entry.set_text(pp), self._do_load()])
            self._recent_menu.append(item)
        self._recent_menu.show_all()


# ── SSH Key selector ──────────────────────────────────────────────────────────
class _KeySelector(_GtkBoxBase):
    def __init__(self, parent_win):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._win = parent_win
        self._combo = Gtk.ComboBoxText()
        self._combo.set_hexpand(True)
        self.pack_start(self._combo, True, True, 0)
        btn_r = Gtk.Button(label='↺')
        btn_r.set_tooltip_text('Refresh key list')
        btn_r.connect('clicked', lambda _: self.refresh())
        self.pack_start(btn_r, False, False, 0)
        btn_b = Gtk.Button(label='Browse…')
        btn_b.connect('clicked', self._browse)
        self.pack_start(btn_b, False, False, 0)
        self.refresh()

    def refresh(self):
        cur = self.get_value()
        self._combo.remove_all()
        for k in ssh_keys.discover_keys():
            if k.get('path'):
                self._combo.append_text(k['path'])
        if cur:
            self._set_text(cur)
        elif self._combo.get_model() and len(self._combo.get_model()):
            self._combo.set_active(0)

    def _browse(self, *_):
        p = _browse_file(self._win, 'Select SSH private key', '~/.ssh')
        if p:
            self._set_text(p)

    def _set_text(self, text: str):
        for i, row in enumerate(self._combo.get_model() or []):
            if row[0] == text:
                self._combo.set_active(i); return
        self._combo.append_text(text)
        self._combo.set_active(len(self._combo.get_model()) - 1)

    def get_value(self) -> str:
        return self._combo.get_active_text() or ''


# ══════════════════════════════════════════════════════════════════════════════
# Main application
# ══════════════════════════════════════════════════════════════════════════════
class _GTKApp:

    _NAV = [
        # (section_header, page_key, label, icon)
        ('REPOSITORY',   None,          None,            None),
        (None,           'clone',       'Clone Repo',    'document-save-symbolic'),
        (None,           'status',      'Status',        'dialog-information-symbolic'),
        ('HISTORY',      None,          None,            None),
        (None,           'log',         'Log & Commits', 'document-open-recent-symbolic'),
        ('BRANCHES',     None,          None,            None),
        (None,           'branches',    'Branches',      'vcs-branch-symbolic'),
        (None,           'merge',       'Merge / Rebase','media-playlist-shuffle-symbolic'),
        ('COLLABORATION',None,          None,            None),
        (None,           'remotes',     'Remotes',       'network-server-symbolic'),
        (None,           'worktrees',   'Worktrees',     'folder-open-symbolic'),
        ('SECURITY',     None,          None,            None),
        (None,           'keys',        'SSH Keys',      'dialog-password-symbolic'),
    ]

    def __init__(self):
        self._repo_path = ''
        self._current_branch = ''
        self._page_reload_callbacks: Dict[str, Callable] = {}
        self._nav_buttons: Dict[str, 'Gtk.Button'] = {}
        self._log_buffer = None
        self._log_view   = None
        self._status_lbl = None
        self._repo_bar: Optional[_RepoBar] = None
        self._win = None
        self.stack = None
        self._build_window()

    # ── Window skeleton ───────────────────────────────────────────────────────
    def _build_window(self):
        self._win = Gtk.Window(title='SSH Git Manager')
        self._win.set_default_size(1100, 740)
        self._win.set_resizable(True)
        self._win.connect('delete-event', Gtk.main_quit)

        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        header.props.title = 'SSH Git Manager'
        header.props.subtitle = 'PyGitDesk · Keys · Remotes · Branches · Commits'
        self._win.set_titlebar(header)

        try:
            self._set_icon()
        except Exception:
            pass

        self._apply_css()

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._win.add(root)

        # Global repo strip
        self._repo_bar = _RepoBar(self._win, self._on_global_repo_load)
        root.pack_start(self._repo_bar, False, False, 0)
        root.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)

        # Body
        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        root.pack_start(body, True, True, 0)

        sidebar = self._build_sidebar()
        sidebar.set_size_request(180, -1)
        sidebar.get_style_context().add_class('sidebar')
        body.pack_start(sidebar, False, False, 0)
        body.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)

        stack_wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        stack_wrap.get_style_context().add_class('content-bg')
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(100)
        stack_wrap.pack_start(self.stack, True, True, 0)
        body.pack_start(stack_wrap, True, True, 0)

        root.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)

        # Output log
        root.pack_start(self._build_log(), False, False, 0)
        root.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)

        # Status bar
        status_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        status_bar.get_style_context().add_class('status-bar')
        status_bar.set_margin_start(12)
        status_bar.set_margin_top(4)
        status_bar.set_margin_bottom(4)
        root.pack_start(status_bar, False, False, 0)
        self._status_lbl = Gtk.Label()
        self._status_lbl.set_markup(_markup('● Ready', C_GRAY))
        status_bar.pack_start(self._status_lbl, False, False, 0)

        # Register pages
        pages = [
            ('clone',     self._build_clone_page),
            ('status',    self._build_status_page),
            ('log',       self._build_log_page),
            ('branches',  self._build_branch_page),
            ('merge',     self._build_merge_page),
            ('remotes',   self._build_remote_page),
            ('worktrees', self._build_worktree_page),
            ('keys',      self._build_keys_page),
        ]
        for key, builder in pages:
            self.stack.add_named(builder(), key)

        self._win.show_all()
        GLib.idle_add(self._load_startup_repo)

    # ── CSS ───────────────────────────────────────────────────────────────────
    def _apply_css(self):
        provider = Gtk.CssProvider()
        provider.load_from_data(_APP_CSS.encode())
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    # ── Sidebar ───────────────────────────────────────────────────────────────
    def _build_sidebar(self) -> 'Gtk.Box':
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Brand header
        brand = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        brand.set_margin_start(14); brand.set_margin_end(14)
        brand.set_margin_top(14);   brand.set_margin_bottom(6)
        try:
            brand_icon = Gtk.Image.new_from_icon_name(
                'applications-development-symbolic', Gtk.IconSize.DND)
            brand.pack_start(brand_icon, False, False, 0)
        except Exception:
            pass
        brand_label = Gtk.Label(label='SSH Git Manager')
        brand_label.get_style_context().add_class('sidebar-brand')
        brand_label.set_xalign(0.0)
        brand.pack_start(brand_label, True, True, 0)
        box.pack_start(brand, False, False, 0)

        brand_sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        brand_sep.set_margin_start(10); brand_sep.set_margin_end(10)
        brand_sep.set_margin_top(4);    brand_sep.set_margin_bottom(4)
        box.pack_start(brand_sep, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_hexpand(False)

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        inner.set_margin_bottom(8)

        for section, key, label, icon in self._NAV:
            if section is not None:
                lbl = Gtk.Label(label=section)
                lbl.set_xalign(0.0)
                lbl.get_style_context().add_class('sidebar-section')
                inner.pack_start(lbl, False, False, 0)
            else:
                btn = Gtk.Button()
                btn.set_relief(Gtk.ReliefStyle.NONE)
                btn.get_style_context().add_class('nav-button')
                btn_inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                btn_inner.set_margin_start(4)
                try:
                    img = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU)
                    btn_inner.pack_start(img, False, False, 0)
                except Exception:
                    pass
                lbl_w = Gtk.Label(label=label)
                lbl_w.set_xalign(0.0)
                btn_inner.pack_start(lbl_w, True, True, 0)
                btn.add(btn_inner)
                btn.connect('clicked', lambda _, k=key: self._navigate(k))
                self._nav_buttons[key] = btn
                btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
                btn_box.set_margin_start(6)
                btn_box.set_margin_end(6)
                btn_box.set_margin_top(1)
                btn_box.pack_start(btn, True, True, 0)
                inner.pack_start(btn_box, False, False, 0)

        scroll.add(inner)
        box.pack_start(scroll, True, True, 0)
        return box

    def _navigate(self, key: str):
        self.stack.set_visible_child_name(key)
        for k, btn in self._nav_buttons.items():
            ctx = btn.get_style_context()
            if k == key:
                ctx.add_class('nav-active')
            else:
                ctx.remove_class('nav-active')
        if self._repo_path and key in self._page_reload_callbacks:
            self._page_reload_callbacks[key]()

    # ── Global repo state ─────────────────────────────────────────────────────
    def _on_global_repo_load(self, rd: str):
        self._repo_path = rd
        _add_recent(rd)
        self._repo_bar._rebuild_recent_menu()

        def _do():
            r = _git(rd, 'rev-parse', '--abbrev-ref', 'HEAD')
            branch = r.get('stdout', '').strip() or '?'
            self._current_branch = branch
            GLib.idle_add(self._repo_bar.update_branch, branch)
            name = Path(rd).name
            self.set_status(f'Repo: {name}  ⑂  {branch}', C_GREEN)
            # Reload the current page
            current = self.stack.get_visible_child_name()
            if current and current in self._page_reload_callbacks:
                GLib.idle_add(self._page_reload_callbacks[current])

        threading.Thread(target=_do, daemon=True).start()

    def _load_startup_repo(self):
        recent = _load_recent()
        if recent:
            self._repo_bar.set_path(recent[0])
            self._repo_bar._do_load()
        self._navigate('status')

    # ── Log widget ────────────────────────────────────────────────────────────
    def _build_log(self) -> 'Gtk.Box':
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_start(12); box.set_margin_end(12)
        box.set_margin_top(6);    box.set_margin_bottom(6)

        hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.pack_start(hdr, False, False, 0)
        lbl = Gtk.Label()
        lbl.set_markup('<b>Output</b>')
        lbl.set_xalign(0.0); lbl.set_hexpand(True)
        hdr.pack_start(lbl, True, True, 0)
        btn_clear = Gtk.Button(label='Clear')
        btn_clear.connect('clicked', lambda *_: self._log_buffer.set_text(''))
        hdr.pack_start(btn_clear, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(130)
        box.pack_start(scroll, True, True, 0)

        self._log_view = Gtk.TextView()
        self._log_view.set_editable(False)
        self._log_view.set_cursor_visible(False)
        self._log_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._log_view.set_monospace(True)
        self._log_view.set_margin_start(8); self._log_view.set_margin_end(8)
        self._log_view.set_margin_top(4);   self._log_view.set_margin_bottom(4)

        self._log_buffer = self._log_view.get_buffer()
        for tag, color in [('ok', C_GREEN), ('err', C_RED), ('info', C_BLUE),
                           ('warn', C_ORANGE), ('dim', C_GRAY)]:
            self._log_buffer.create_tag(tag, foreground=color)

        scroll.add(self._log_view)
        return box

    def log(self, msg: str, tag: str = '') -> None:
        GLib.idle_add(self._append_log, msg, tag)

    def _append_log(self, msg: str, tag: str) -> bool:
        it = self._log_buffer.get_end_iter()
        if tag in ('ok', 'err', 'info', 'warn', 'dim'):
            self._log_buffer.insert_with_tags_by_name(it, msg + '\n', tag)
        else:
            self._log_buffer.insert(it, msg + '\n')
        GLib.idle_add(self._log_view.scroll_mark_onscreen,
                      self._log_buffer.get_insert())
        return False

    def set_status(self, msg: str, color: str = C_GRAY) -> None:
        GLib.idle_add(self._status_lbl.set_markup,
                      _markup(f'● {msg}', color, bold=True))

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _require_repo(self) -> Optional[str]:
        if not self._repo_path:
            _show_error(self._win, 'No repository loaded',
                        'Use the repo bar at the top to load a repository first.')
            return None
        return self._repo_path

    @staticmethod
    def _scrolled_body() -> tuple:
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        body.set_margin_top(16); body.set_margin_bottom(16)
        body.set_margin_start(18); body.set_margin_end(18)
        scroll.add(body)
        return scroll, body

    @staticmethod
    def _section_label(text: str) -> 'Gtk.Label':
        lbl = Gtk.Label()
        lbl.set_markup(f'<b>{GLib.markup_escape_text(text)}</b>')
        lbl.set_xalign(0.0)
        return lbl

    @staticmethod
    def _sep() -> 'Gtk.Separator':
        return Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)

    def _action_bar(self, *btn_defs) -> 'Gtk.Box':
        """Build a bottom action bar. Each def is (label, style_class, callback) or None for sep."""
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        bar.set_margin_start(18); bar.set_margin_end(18)
        bar.set_margin_top(8);    bar.set_margin_bottom(8)
        for item in btn_defs:
            if item is None:
                s = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
                s.set_margin_start(4); s.set_margin_end(4)
                bar.pack_start(s, False, False, 0)
            else:
                label, style, cb, *_tip = item
                tooltip = _tip[0] if _tip else None
                btn = Gtk.Button(label=label)
                if style:
                    btn.get_style_context().add_class(style)
                if cb:
                    btn.connect('clicked', lambda _, f=cb: f())
                if tooltip:
                    btn.set_tooltip_text(tooltip)
                bar.pack_start(btn, False, False, 0)
        return bar

    def _tree_view(self, columns: List[tuple], store_types=None) -> tuple:
        """
        columns: list of (title, width, stretch, color_col_idx or None)
        Returns (store, tree, scroll)
        """
        types = store_types or ([str] * (len(columns) + 1))  # +1 for color col
        store = Gtk.ListStore(*types)
        tree = Gtk.TreeView(model=store)
        tree.set_headers_visible(True)
        tree.get_selection().set_mode(Gtk.SelectionMode.SINGLE)

        n_data_cols = len(types) - 1  # last col is color
        for i, (title, width, stretch, _color_from) in enumerate(columns):
            r = Gtk.CellRendererText()
            r.set_property('ellipsize', Pango.EllipsizeMode.MIDDLE)
            color_idx = n_data_cols  # last col
            col = Gtk.TreeViewColumn(title, r, text=i, foreground=color_idx)
            col.set_min_width(width)
            col.set_resizable(True)
            col.set_expand(stretch)
            tree.append_column(col)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.add(tree)
        return store, tree, scroll

    def _get_selected_value(self, tree: 'Gtk.TreeView', col: int) -> Optional[str]:
        model, it = tree.get_selection().get_selected()
        return model.get_value(it, col) if it else None

    # ═══════════════════════════════════════════════════════════════════════════
    # Page: Clone
    # ═══════════════════════════════════════════════════════════════════════════
    def _build_clone_page(self) -> 'Gtk.Widget':
        scroll, body = self._scrolled_body()

        body.pack_start(self._section_label('Clone Repository'), False, False, 0)
        body.pack_start(self._sep(), False, False, 0)

        grid = Gtk.Grid(row_spacing=10, column_spacing=12)
        body.pack_start(grid, False, False, 0)

        def _lbl(text):
            l = Gtk.Label(label=text)
            l.set_width_chars(14); l.set_xalign(1.0)
            return l

        url_entry = Gtk.Entry()
        url_entry.set_hexpand(True)
        url_entry.set_placeholder_text('git@github.com:user/repo.git  or  https://…')
        grid.attach(_lbl('Repository URL:'), 0, 0, 1, 1)
        grid.attach(url_entry, 1, 0, 2, 1)

        dir_entry = Gtk.Entry()
        dir_entry.set_hexpand(True)
        dir_entry.set_placeholder_text('(leave blank — auto name)')
        btn_dir = Gtk.Button(label='Browse…')
        btn_dir.connect('clicked', lambda _: dir_entry.set_text(
            _browse_dir(self._win, 'Clone into…') or dir_entry.get_text()))
        grid.attach(_lbl('Clone into:'), 0, 1, 1, 1)
        grid.attach(dir_entry, 1, 1, 1, 1)
        grid.attach(btn_dir, 2, 1, 1, 1)

        key_sel = _KeySelector(self._win)
        grid.attach(_lbl('SSH Key:'), 0, 2, 1, 1)
        grid.attach(key_sel, 1, 2, 2, 1)

        body.pack_start(self._sep(), False, False, 0)
        btn_clone = Gtk.Button(label='  ⬇   Clone Repository')
        btn_clone.get_style_context().add_class('suggested-action')
        btn_clone.set_halign(Gtk.Align.START)
        body.pack_start(btn_clone, False, False, 0)

        clone_status = Gtk.Label()
        clone_status.set_xalign(0.0)
        body.pack_start(clone_status, False, False, 0)

        body.pack_start(self._sep(), False, False, 0)
        body.pack_start(self._section_label('Post-Clone Actions'), False, False, 0)
        post_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        body.pack_start(post_row, False, False, 0)

        _repo_ref: Dict = {'path': None}

        def _go_status(*_):
            rd = _repo_ref['path']
            if rd:
                self._repo_bar.set_path(rd)
                self._on_global_repo_load(rd)
                self._navigate('status')

        for label, cb in [
            ('List Branches',
             lambda *_: [self.log(b, 'dim') for b in clone_actions.list_branches(_repo_ref['path'])]
                         if _repo_ref.get('path') else self.log('Clone a repo first', 'warn')),
            ('Checkout Branch',
             lambda *_: _checkout_post() if _repo_ref.get('path') else self.log('Clone a repo first', 'warn')),
            ('Open Folder',
             lambda *_: os.system(f'xdg-open {shlex.quote(_repo_ref["path"] or ".")} &')),
            ('→ Status Page', _go_status),
        ]:
            btn = Gtk.Button(label=label)
            btn.connect('clicked', cb)
            post_row.pack_start(btn, False, False, 0)

        def _checkout_post():
            rd = _repo_ref['path']
            if not rd: return
            br = _ask_string(self._win, 'Checkout', 'Branch name:')
            if not br: return
            def _do():
                r = _git(rd, 'checkout', br)
                self.log(f'✔ {br}' if r['returncode'] == 0 else r['stderr'],
                         'ok' if r['returncode'] == 0 else 'err')
            threading.Thread(target=_do, daemon=True).start()

        def _do_clone(*_):
            url = url_entry.get_text().strip()
            key = key_sel.get_value()
            dest = dir_entry.get_text().strip() or None
            if not url: _show_error(self._win, 'Repository URL is required.'); return
            if not key: _show_error(self._win, 'SSH key is required.'); return
            btn_clone.set_sensitive(False)
            self.set_status('Cloning…', C_ORANGE)
            GLib.idle_add(clone_status.set_markup, _markup('● Cloning…', C_ORANGE, bold=True))

            def _run():
                try:
                    cmd = core.build_ssh_command(key)
                    env = {'GIT_SSH_COMMAND': ' '.join(shlex.quote(c) for c in cmd)}
                    self.log(f'git clone {url}', 'info')
                    r = core.run_git(['clone', url] + ([dest] if dest else []), env_overrides=env)
                    if r['returncode'] != 0:
                        self.log('✖ Clone failed', 'err')
                        self.log(r.get('stderr') or r.get('stdout') or '', 'err')
                        self.set_status('Clone failed', C_RED)
                        GLib.idle_add(clone_status.set_markup,
                                      _markup('● Clone failed', C_RED, bold=True))
                        return
                    name = dest or url.rstrip('/').split('/')[-1].removesuffix('.git')
                    rd = dest or str(Path.cwd() / name)
                    _repo_ref['path'] = rd
                    _add_recent(rd)
                    self.log(f'✔ Cloned → {rd}', 'ok')
                    GLib.idle_add(self._repo_bar._rebuild_recent_menu)
                    self.set_status('Clone succeeded', C_GREEN)
                    GLib.idle_add(clone_status.set_markup,
                                  _markup(f'● Cloned → {rd}', C_GREEN, bold=True))
                finally:
                    GLib.idle_add(btn_clone.set_sensitive, True)

            threading.Thread(target=_run, daemon=True).start()

        btn_clone.connect('clicked', _do_clone)
        return scroll

    # ═══════════════════════════════════════════════════════════════════════════
    # Page: Status
    # ═══════════════════════════════════════════════════════════════════════════
    def _build_status_page(self) -> 'Gtk.Widget':
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        _state: Dict = {'staged': [], 'unstaged': [], 'branch_lbl': None}

        STATUS_COLOR = {
            'M': C_ORANGE, 'A': C_GREEN, 'D': C_RED,
            'R': C_BLUE,   'C': C_BLUE,  '?': C_GRAY,
            'U': C_RED,
        }

        # Toolbar
        tb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        tb.set_margin_start(18); tb.set_margin_end(18)
        tb.set_margin_top(10);   tb.set_margin_bottom(6)
        outer.pack_start(tb, False, False, 0)

        lbl = Gtk.Label()
        lbl.set_markup('<b>Working Tree Status</b>')
        lbl.set_hexpand(True); lbl.set_xalign(0.0)
        tb.pack_start(lbl, True, True, 0)

        btn_refresh = Gtk.Button(label='↺ Refresh')
        btn_refresh.connect('clicked', lambda _: _refresh())
        btn_refresh.set_tooltip_text('Reload working tree status from git')
        tb.pack_start(btn_refresh, False, False, 0)

        # Paned: file list | diff
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_position(340)
        outer.pack_start(paned, True, True, 0)

        # LEFT: file list (ListBox)
        left_scroll = Gtk.ScrolledWindow()
        left_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        file_list = Gtk.ListBox()
        file_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        left_scroll.add(file_list)
        paned.pack1(left_scroll, resize=False, shrink=False)

        # RIGHT: diff view
        diff_scroll, diff_tv, diff_buf = _make_diff_view()
        paned.pack2(diff_scroll, resize=True, shrink=True)

        def _make_file_row(code: str, filepath: str, is_staged: bool) -> 'Gtk.ListBoxRow':
            row = Gtk.ListBoxRow()
            row._fp = filepath
            row._code = code
            row._is_staged = is_staged
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            box.set_margin_start(8); box.set_margin_end(8)
            box.set_margin_top(3);   box.set_margin_bottom(3)
            dot_color = C_GREEN if is_staged else C_ORANGE
            badge = Gtk.Label()
            badge.set_markup(_markup(f'● {code}', dot_color))
            badge.set_width_chars(5)
            path_lbl = Gtk.Label(label=filepath)
            path_lbl.set_xalign(0.0); path_lbl.set_hexpand(True)
            path_lbl.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            box.pack_start(badge, False, False, 0)
            box.pack_start(path_lbl, True, True, 0)
            row.add(box)
            return row

        def _section_row(text: str) -> 'Gtk.ListBoxRow':
            row = Gtk.ListBoxRow()
            row.set_selectable(False)
            row.set_activatable(False)
            lbl = Gtk.Label()
            lbl.set_markup(f'<span foreground="{C_GRAY}"><b>  {text}</b></span>')
            lbl.set_xalign(0.0)
            lbl.set_margin_start(8); lbl.set_margin_top(6); lbl.set_margin_bottom(2)
            row.add(lbl)
            return row

        def _populate_list():
            for row in file_list.get_children():
                file_list.remove(row)
            file_list.add(_section_row('STAGED'))
            for code, filepath in _state['staged']:
                file_list.add(_make_file_row(code, filepath, True))
            file_list.add(_section_row('UNSTAGED / UNTRACKED'))
            for code, filepath in _state['unstaged']:
                file_list.add(_make_file_row(code, filepath, False))
            file_list.show_all()

        def _on_file_select(lb, row):
            if not row or not hasattr(row, '_fp'): return
            rd = self._repo_path
            if not rd: return
            fp = row._fp
            is_staged = getattr(row, '_is_staged', False)
            def _do():
                if is_staged:
                    r = _git(rd, 'diff', '--cached', '--', fp)
                else:
                    r = _git(rd, 'diff', 'HEAD', '--', fp)
                    if not r['stdout'].strip():
                        r = _git(rd, 'diff', '--', fp)
                GLib.idle_add(_apply_diff_colors, diff_buf,
                              r['stdout'] or '(no diff)')
            threading.Thread(target=_do, daemon=True).start()

        file_list.connect('row-selected', _on_file_select)

        def _refresh():
            rd = self._repo_path
            if not rd: return
            diff_buf.set_text('')
            def _do():
                r = _git(rd, 'status', '--porcelain=v1')
                staged, unstaged = [], []
                for line in r['stdout'].splitlines():
                    if len(line) < 2: continue
                    idx, wt = line[0], line[1]
                    fp = line[3:].strip()
                    if idx != ' ' and idx != '?':
                        staged.append((idx, fp))
                    if wt != ' ':
                        code = '?' if wt == '?' else wt
                        unstaged.append((code, fp))
                _state['staged']   = staged
                _state['unstaged'] = unstaged
                GLib.idle_add(_populate_list)
                self.set_status(f'{len(staged)} staged, {len(unstaged)} unstaged', C_BLUE)
                if _state.get('branch_lbl'):
                    GLib.idle_add(_state['branch_lbl'].set_markup,
                                  _markup(f'On branch: {self._current_branch or "?"}', C_GRAY))
            threading.Thread(target=_do, daemon=True).start()

        def _stage_selected():
            rd = self._repo_path
            if not rd: return
            row = file_list.get_selected_row()
            if not row: return
            fp = row._fp
            def _do():
                r = _git(rd, 'add', fp)
                self.log(f'✔ Staged {fp}' if r['returncode'] == 0 else r['stderr'],
                         'ok' if r['returncode'] == 0 else 'err')
                GLib.idle_add(_refresh)
            threading.Thread(target=_do, daemon=True).start()

        def _unstage_selected():
            rd = self._repo_path
            if not rd: return
            row = file_list.get_selected_row()
            if not row: return
            fp = row._fp
            def _do():
                r = _git(rd, 'reset', 'HEAD', '--', fp)
                self.log(f'Unstaged {fp}' if r['returncode'] == 0 else r['stderr'],
                         'ok' if r['returncode'] == 0 else 'err')
                GLib.idle_add(_refresh)
            threading.Thread(target=_do, daemon=True).start()

        def _stage_all():
            rd = self._repo_path
            if not rd: return
            def _do():
                r = _git(rd, 'add', '-A')
                self.log('✔ Staged all' if r['returncode'] == 0 else r['stderr'],
                         'ok' if r['returncode'] == 0 else 'err')
                GLib.idle_add(_refresh)
            threading.Thread(target=_do, daemon=True).start()

        def _discard_selected():
            rd = self._repo_path
            if not rd: return
            row = file_list.get_selected_row()
            if not row: return
            fp = row._fp
            if not _ask_yes_no(self._win, f'Discard changes to:\n{fp}',
                               'This cannot be undone.'): return
            def _do():
                r = _git(rd, 'checkout', '--', fp)
                self.log(f'✔ Discarded {fp}' if r['returncode'] == 0 else r['stderr'],
                         'ok' if r['returncode'] == 0 else 'err')
                GLib.idle_add(_refresh)
            threading.Thread(target=_do, daemon=True).start()

        # Commit area
        outer.pack_start(self._sep(), False, False, 0)
        commit_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        commit_box.set_margin_start(18); commit_box.set_margin_end(18)
        commit_box.set_margin_top(8);    commit_box.set_margin_bottom(8)
        outer.pack_start(commit_box, False, False, 0)

        # Metadata row: branch label + char counter
        meta_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        commit_box.pack_start(meta_row, False, False, 0)
        branch_lbl = Gtk.Label()
        branch_lbl.set_markup(_markup(f'On branch: {self._current_branch or "?"}', C_GRAY))
        branch_lbl.set_xalign(0.0)
        branch_lbl.get_style_context().add_class('dim-label')
        meta_row.pack_start(branch_lbl, True, True, 0)
        _state['branch_lbl'] = branch_lbl
        char_counter = Gtk.Label(label='0 chars')
        char_counter.set_xalign(1.0)
        char_counter.get_style_context().add_class('dim-label')
        meta_row.pack_end(char_counter, False, False, 0)

        commit_entry = Gtk.Entry()
        commit_entry.set_placeholder_text('Commit message…')
        commit_entry.set_hexpand(True)
        commit_entry.connect('changed', lambda e: char_counter.set_label(
            f'{len(e.get_text())} chars'))
        commit_entry.connect('changed', lambda e: e.get_style_context().remove_class('commit-error'))
        commit_box.pack_start(commit_entry, False, False, 0)

        # File-ops row
        file_ops_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        file_ops_row.set_margin_top(4)
        commit_box.pack_start(file_ops_row, False, False, 0)

        def _make_btn(label, style=None, cb=None, tip=None):
            b = Gtk.Button(label=label)
            if style: b.get_style_context().add_class(style)
            if cb:    b.connect('clicked', lambda _: cb())
            if tip:   b.set_tooltip_text(tip)
            return b

        file_ops_row.pack_start(_make_btn(
            'Stage Selected', None, _stage_selected,
            'Add the selected file\'s changes to the staging area'), False, False, 0)
        file_ops_row.pack_start(_make_btn(
            'Unstage Selected', None, _unstage_selected,
            'Remove the selected file from the staging area (keeps changes in working tree)'), False, False, 0)
        file_ops_row.pack_start(_make_btn(
            'Stage All', None, _stage_all,
            'Stage every modified and untracked file at once (git add -A)'), False, False, 0)
        file_ops_row.pack_start(_make_btn(
            'Discard Selected', 'destructive-action', _discard_selected,
            'Permanently revert the selected file to its last committed state — cannot be recovered'), False, False, 0)

        # Commit-ops row
        commit_ops_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        commit_ops_row.set_margin_top(2)
        commit_box.pack_start(commit_ops_row, False, False, 0)

        def _commit():
            rd = self._repo_path
            if not rd: return
            msg = commit_entry.get_text().strip()
            if not msg:
                commit_entry.get_style_context().add_class('commit-error')
                self.set_status('Commit message is required', C_RED)
                return
            commit_entry.get_style_context().remove_class('commit-error')
            def _do():
                r = _git(rd, 'commit', '-m', msg)
                self.log(r['stdout'].strip() or r['stderr'].strip(),
                         'ok' if r['returncode'] == 0 else 'err')
                if r['returncode'] == 0:
                    GLib.idle_add(commit_entry.set_text, '')
                GLib.idle_add(_refresh)
            threading.Thread(target=_do, daemon=True).start()

        def _amend():
            rd = self._repo_path
            if not rd: return
            msg = commit_entry.get_text().strip()
            def _do():
                args = ['commit', '--amend'] + (['-m', msg] if msg else ['--no-edit'])
                r = _git(rd, *args)
                self.log(r['stdout'].strip() or r['stderr'].strip(),
                         'ok' if r['returncode'] == 0 else 'err')
                if r['returncode'] == 0:
                    GLib.idle_add(commit_entry.set_text, '')
                GLib.idle_add(_refresh)
            threading.Thread(target=_do, daemon=True).start()

        def _stage_all_and_commit():
            rd = self._repo_path
            if not rd: return
            msg = commit_entry.get_text().strip()
            if not msg:
                commit_entry.get_style_context().add_class('commit-error')
                self.set_status('Commit message is required', C_RED)
                return
            commit_entry.get_style_context().remove_class('commit-error')
            def _do():
                r1 = _git(rd, 'add', '-A')
                if r1['returncode'] != 0:
                    self.log(r1['stderr'].strip(), 'err')
                    return
                r2 = _git(rd, 'commit', '-m', msg)
                self.log(r2['stdout'].strip() or r2['stderr'].strip(),
                         'ok' if r2['returncode'] == 0 else 'err')
                if r2['returncode'] == 0:
                    GLib.idle_add(commit_entry.set_text, '')
                GLib.idle_add(_refresh)
            threading.Thread(target=_do, daemon=True).start()

        commit_entry.connect('activate', lambda _: _commit())

        commit_ops_row.pack_start(_make_btn(
            'Commit', 'suggested-action', _commit,
            'Create a new commit from staged files using the message above'), False, False, 0)
        commit_ops_row.pack_start(_make_btn(
            'Amend Last', None, _amend,
            'Rewrite the most recent commit — use with care on already-pushed commits'), False, False, 0)
        commit_ops_row.pack_start(_make_btn(
            'Stage All & Commit', 'suggested-action', _stage_all_and_commit,
            'Stage every change and commit immediately — fast path for simple single-task changes'), False, False, 0)

        self._page_reload_callbacks['status'] = _refresh
        return outer

    # ═══════════════════════════════════════════════════════════════════════════
    # Page: Log & Commits
    # ═══════════════════════════════════════════════════════════════════════════
    def _build_log_page(self) -> 'Gtk.Widget':
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        tb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        tb.set_margin_start(18); tb.set_margin_end(18)
        tb.set_margin_top(10);   tb.set_margin_bottom(6)
        outer.pack_start(tb, False, False, 0)
        lbl = Gtk.Label()
        lbl.set_markup('<b>Commit History</b>')
        lbl.set_hexpand(True); lbl.set_xalign(0.0)
        tb.pack_start(lbl, True, True, 0)

        limit_entry = Gtk.Entry()
        limit_entry.set_text('200')
        limit_entry.set_width_chars(6)
        limit_entry.set_placeholder_text('limit')
        tb.pack_start(Gtk.Label(label='Show:'), False, False, 0)
        tb.pack_start(limit_entry, False, False, 0)
        btn_ref = Gtk.Button(label='↺ Refresh')
        btn_ref.connect('clicked', lambda _: _refresh())
        tb.pack_start(btn_ref, False, False, 0)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_position(480)
        outer.pack_start(paned, True, True, 0)

        # Commit list — store: full_hash, short_hash, author, date, subject, color
        store = Gtk.ListStore(str, str, str, str, str, str)
        tree = Gtk.TreeView(model=store)
        tree.set_headers_visible(True)
        tree.get_selection().set_mode(Gtk.SelectionMode.SINGLE)
        for i, (title, width, stretch) in enumerate([
            ('Hash', 72, False), ('Author', 140, False),
            ('Date', 88, False), ('Subject', 300, True)
        ]):
            r = Gtk.CellRendererText()
            r.set_property('ellipsize', Pango.EllipsizeMode.END)
            col = Gtk.TreeViewColumn(title, r, text=i + 1, foreground=5)
            col.set_min_width(width); col.set_expand(stretch); col.set_resizable(True)
            tree.append_column(col)

        left_scroll = Gtk.ScrolledWindow()
        left_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        left_scroll.add(tree)
        paned.pack1(left_scroll, resize=False, shrink=False)

        diff_scroll, _diff_tv, diff_buf = _make_diff_view()
        paned.pack2(diff_scroll, resize=True, shrink=True)

        def _refresh():
            rd = self._repo_path
            if not rd: return
            limit = limit_entry.get_text().strip() or '200'
            def _do():
                r = _git(rd, 'log',
                         f'--format=%H\x1f%an\x1f%ad\x1f%s',
                         '--date=short', f'-{limit}')
                rows = []
                for line in r['stdout'].splitlines():
                    parts = line.split('\x1f', 3)
                    if len(parts) == 4:
                        full, author, date, subject = parts
                        rows.append([full, full[:8], author, date, subject, '#cdd6f4'])
                def _populate():
                    store.clear()
                    for row in rows:
                        store.append(row)
                GLib.idle_add(_populate)
                self.set_status(f'{len(rows)} commits loaded', C_BLUE)
            threading.Thread(target=_do, daemon=True).start()

        def _on_select(_sel):
            model, it = tree.get_selection().get_selected()
            if not it: return
            full_hash = model.get_value(it, 0)
            rd = self._repo_path
            if not rd: return
            def _do():
                r = _git(rd, 'show', '--stat', '-p', full_hash)
                GLib.idle_add(_apply_diff_colors, diff_buf, r['stdout'])
            threading.Thread(target=_do, daemon=True).start()

        tree.get_selection().connect('changed', _on_select)

        def _selected_hash() -> Optional[str]:
            return self._get_selected_value(tree, 0)

        # Actions
        outer.pack_start(self._sep(), False, False, 0)
        act = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        act.set_margin_start(18); act.set_margin_end(18)
        act.set_margin_top(8);    act.set_margin_bottom(8)
        outer.pack_start(act, False, False, 0)

        def _revert():
            rd = self._require_repo()
            h = _selected_hash()
            if not rd or not h: return
            if not _ask_yes_no(self._win, f'Revert commit {h[:8]}?',
                               'Creates a new commit that undoes it.'): return
            def _do():
                r = _git(rd, 'revert', '--no-edit', h)
                self.log(r['stdout'].strip() or r['stderr'].strip(),
                         'ok' if r['returncode'] == 0 else 'err')
                GLib.idle_add(_refresh)
            threading.Thread(target=_do, daemon=True).start()

        def _reset(mode: str):
            rd = self._require_repo()
            h = _selected_hash()
            if not rd or not h: return
            warn = 'ALL uncommitted changes will be lost!' if mode == 'hard' else ''
            if not _ask_yes_no(self._win, f'Reset ({mode}) to {h[:8]}?', warn): return
            def _do():
                r = _git(rd, 'reset', f'--{mode}', h)
                self.log(r['stdout'].strip() or r['stderr'].strip(),
                         'ok' if r['returncode'] == 0 else 'err')
                GLib.idle_add(_refresh)
            threading.Thread(target=_do, daemon=True).start()

        def _cherry_pick():
            rd = self._require_repo()
            h = _selected_hash()
            if not rd or not h: return
            def _do():
                r = _git(rd, 'cherry-pick', h)
                self.log(r['stdout'].strip() or r['stderr'].strip(),
                         'ok' if r['returncode'] == 0 else 'err')
                GLib.idle_add(_refresh)
            threading.Thread(target=_do, daemon=True).start()

        def _tag():
            rd = self._require_repo()
            h = _selected_hash()
            if not rd or not h: return
            name = _ask_string(self._win, 'Create Tag', f'Tag name for {h[:8]}:')
            if not name: return
            def _do():
                r = _git(rd, 'tag', name, h)
                self.log(f'✔ Tag {name} → {h[:8]}' if r['returncode'] == 0
                         else r['stderr'], 'ok' if r['returncode'] == 0 else 'err')
            threading.Thread(target=_do, daemon=True).start()

        def _copy_hash():
            h = _selected_hash()
            if h:
                clip = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
                clip.set_text(h, -1)
                self.log(f'Copied: {h}', 'dim')

        _LOG_TIPS = {
            'Revert Commit': 'Create a new commit that undoes the selected commit\'s changes',
            'Reset Soft':    'Move HEAD back to the selected commit, keeping all changes staged',
            'Reset Mixed':   'Move HEAD back, keeping changes unstaged in the working tree',
            'Reset Hard':    'Move HEAD back and discard ALL changes — this cannot be undone',
            'Cherry-pick':   'Apply the selected commit\'s changes onto the current branch as a new commit',
            'Tag':           'Create a lightweight tag pointing at the selected commit',
            'Copy Hash':     'Copy the full commit hash to the clipboard',
        }
        for _item in [
            ('Revert Commit',  None,                 _revert),
            None,
            ('Reset Soft',     None,                 lambda: _reset('soft')),
            ('Reset Mixed',    None,                 lambda: _reset('mixed')),
            ('Reset Hard',     'destructive-action', lambda: _reset('hard')),
            None,
            ('Cherry-pick',    'suggested-action',   _cherry_pick),
            ('Tag',            None,                 _tag),
            ('Copy Hash',      None,                 _copy_hash),
        ]:
            if _item is None:
                s = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
                s.set_margin_start(4); s.set_margin_end(4)
                act.pack_start(s, False, False, 0)
            else:
                label, style, cb = _item
                b = Gtk.Button(label=label)
                if style: b.get_style_context().add_class(style)
                b.connect('clicked', lambda _, f=cb: f())
                if label in _LOG_TIPS:
                    b.set_tooltip_text(_LOG_TIPS[label])
                act.pack_start(b, False, False, 0)

        self._page_reload_callbacks['log'] = _refresh
        return outer

    # ═══════════════════════════════════════════════════════════════════════════
    # Page: Branches
    # ═══════════════════════════════════════════════════════════════════════════
    def _build_branch_page(self) -> 'Gtk.Widget':
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        _state: Dict = {'current': ''}

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        outer.pack_start(scroll, True, True, 0)

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        scroll.add(inner)

        # Branch list toolbar
        tb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        tb.set_margin_start(18); tb.set_margin_end(18)
        tb.set_margin_top(10);   tb.set_margin_bottom(6)
        inner.pack_start(tb, False, False, 0)
        lbl = Gtk.Label()
        lbl.set_markup('<b>Branches</b>')
        lbl.set_hexpand(True); lbl.set_xalign(0.0)
        tb.pack_start(lbl, True, True, 0)
        show_remote = Gtk.CheckButton(label='Show remote')
        show_remote.set_active(True)
        show_remote.connect('toggled', lambda _: _refresh())
        tb.pack_start(show_remote, False, False, 0)
        tb.pack_start(Gtk.Button(label='↺ Refresh'), False, False, 0)
        tb.get_children()[-1].connect('clicked', lambda _: _refresh())

        # Branch TreeView — branch | location | notes | color | weight
        store = Gtk.ListStore(str, str, str, str, int)
        tree = Gtk.TreeView(model=store)
        tree.set_headers_visible(True)
        tree.get_selection().set_mode(Gtk.SelectionMode.SINGLE)
        for i, (title, width, stretch) in enumerate([
            ('Branch', 280, True), ('Local / Remote', 110, False), ('Notes', 120, False)
        ]):
            r = Gtk.CellRendererText()
            r.set_property('ellipsize', Pango.EllipsizeMode.MIDDLE)
            col = Gtk.TreeViewColumn(title, r, text=i, foreground=3, weight=4)
            col.set_min_width(width); col.set_expand(stretch); col.set_resizable(True)
            tree.append_column(col)

        tbl_scroll = Gtk.ScrolledWindow()
        tbl_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        tbl_scroll.set_min_content_height(200)
        tbl_scroll.add(tree)
        tbl_frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        tbl_frame.set_margin_start(18); tbl_frame.set_margin_end(18)
        tbl_frame.pack_start(tbl_scroll, True, True, 0)
        inner.pack_start(tbl_frame, True, True, 0)

        # Stash section
        inner.pack_start(self._sep(), False, False, 0)
        stash_tb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        stash_tb.set_margin_start(18); stash_tb.set_margin_end(18)
        stash_tb.set_margin_top(8);    stash_tb.set_margin_bottom(4)
        inner.pack_start(stash_tb, False, False, 0)
        stash_lbl = Gtk.Label()
        stash_lbl.set_markup('<b>Stashes</b>')
        stash_lbl.set_hexpand(True); stash_lbl.set_xalign(0.0)
        stash_tb.pack_start(stash_lbl, True, True, 0)
        stash_refresh_btn = Gtk.Button(label='↺')
        stash_refresh_btn.set_tooltip_text('Refresh stash list')
        stash_tb.pack_start(stash_refresh_btn, False, False, 0)

        stash_hint = Gtk.Label(label='Stash saves uncommitted changes temporarily so you can switch tasks.')
        stash_hint.set_xalign(0.0)
        stash_hint.set_margin_start(18); stash_hint.set_margin_end(18)
        stash_hint.set_margin_bottom(4)
        stash_hint.get_style_context().add_class('dim-label')
        inner.pack_start(stash_hint, False, False, 0)

        stash_store = Gtk.ListStore(str, str, str, str)  # ref, date, message, color
        stash_tree = Gtk.TreeView(model=stash_store)
        stash_tree.set_headers_visible(True)
        stash_tree.get_selection().set_mode(Gtk.SelectionMode.SINGLE)
        for i, (title, width, stretch) in enumerate([
            ('Ref', 90, False), ('Date', 120, False), ('Message', 340, True)
        ]):
            r = Gtk.CellRendererText()
            r.set_property('ellipsize', Pango.EllipsizeMode.END)
            col = Gtk.TreeViewColumn(title, r, text=i, foreground=3)
            col.set_min_width(width); col.set_resizable(True); col.set_expand(stretch)
            stash_tree.append_column(col)

        stash_scroll = Gtk.ScrolledWindow()
        stash_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        stash_scroll.set_min_content_height(100)
        stash_scroll.add(stash_tree)
        stash_diff_scroll, stash_diff_tv, stash_diff_buf = _make_diff_view()
        stash_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        stash_paned.set_position(380)
        stash_paned.pack1(stash_scroll, resize=False, shrink=False)
        stash_paned.pack2(stash_diff_scroll, resize=True, shrink=True)

        stash_frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        stash_frame.set_margin_start(18); stash_frame.set_margin_end(18)
        stash_frame.set_margin_bottom(8)
        stash_frame.pack_start(stash_paned, True, True, 0)
        inner.pack_start(stash_frame, False, False, 0)

        def _on_stash_select(sel):
            model, it = sel.get_selected()
            if not it: return
            ref = model.get_value(it, 0)
            rd = self._repo_path
            if not rd: return
            def _do():
                r = _git(rd, 'stash', 'show', '-p', ref)
                GLib.idle_add(_apply_diff_colors, stash_diff_buf,
                              r['stdout'] or '(empty stash)')
            threading.Thread(target=_do, daemon=True).start()
        stash_tree.get_selection().connect('changed', _on_stash_select)

        def _refresh():
            rd = self._repo_path
            if not rd: return
            cur = _git(rd, 'rev-parse', '--abbrev-ref', 'HEAD').get('stdout', '').strip()
            _state['current'] = cur
            store.clear()
            r = _git(rd, 'branch', '-a', '--format=%(refname:short)')
            for raw in r['stdout'].splitlines():
                b = raw.strip().removeprefix('remotes/')
                if not b or b.startswith('HEAD'): continue
                is_remote = '/' in b
                if is_remote and not show_remote.get_active(): continue
                loc   = 'remote' if is_remote else 'local'
                note  = '● current' if b == cur else ''
                color = C_GREEN if b == cur else (C_GRAY if is_remote else '#cdd6f4')
                weight = Pango.Weight.BOLD if b == cur else Pango.Weight.NORMAL
                store.append([b, loc, note, color, weight])
            # Stash
            stash_store.clear()
            sr = _git(rd, 'stash', 'list', '--format=%gd|%ci|%s')
            for line in sr['stdout'].splitlines():
                parts = line.split('|', 2)
                if len(parts) == 3:
                    ref, date, message = parts
                    stash_store.append([ref.strip(), date.strip()[:10], message.strip(), C_ORANGE])

        def _get_branch() -> Optional[str]:
            return self._get_selected_value(tree, 0)

        def _get_stash_ref() -> Optional[str]:
            return self._get_selected_value(stash_tree, 0)

        def _checkout():
            rd = self._require_repo(); br = _get_branch()
            if not rd or not br: return
            def _do():
                r = _git(rd, 'checkout', br)
                if r['returncode'] == 0:
                    _state['current'] = br
                    self._current_branch = br
                    GLib.idle_add(self._repo_bar.update_branch, br)
                    self.log(f'✔ Checked out {br}', 'ok')
                    self.set_status(f'Branch: {br}', C_GREEN)
                    GLib.idle_add(_refresh)
                else:
                    self.log(r['stderr'] or r['stdout'], 'err')
            threading.Thread(target=_do, daemon=True).start()

        def _new_branch():
            rd = self._require_repo()
            if not rd: return
            name = _ask_string(self._win, 'New Branch', 'Branch name:')
            if not name: return
            checkout = _ask_yes_no(self._win, f'Checkout "{name}" after creating?')
            def _do():
                r = _git(rd, 'checkout', '-b', name) if checkout else _git(rd, 'branch', name)
                if r['returncode'] == 0:
                    self.log(f'✔ Created {"& checked out " if checkout else ""}{name}', 'ok')
                    if checkout:
                        _state['current'] = name
                        self._current_branch = name
                        GLib.idle_add(self._repo_bar.update_branch, name)
                    GLib.idle_add(_refresh)
                else:
                    self.log(r['stderr'] or r['stdout'], 'err')
            threading.Thread(target=_do, daemon=True).start()

        def _delete_branch():
            rd = self._require_repo(); br = _get_branch()
            if not rd or not br: return
            if br == _state['current']:
                _show_error(self._win, 'Cannot delete the current branch.'); return
            force = _ask_yes_no(self._win, f'Delete "{br}"?', 'Force if unmerged?')
            def _do():
                r = _git(rd, 'branch', '-D' if force else '-d', br)
                self.log(f'✔ Deleted {br}' if r['returncode'] == 0 else r['stderr'],
                         'ok' if r['returncode'] == 0 else 'err')
                GLib.idle_add(_refresh)
            threading.Thread(target=_do, daemon=True).start()

        def _pull():
            rd = self._require_repo()
            if not rd: return
            def _do():
                self.log('git pull…', 'info'); self.set_status('Pulling…', C_ORANGE)
                r = _git(rd, 'pull')
                self.log(r['stdout'].strip() or '✔ Up to date',
                         'ok' if r['returncode'] == 0 else 'err')
                if r['returncode'] != 0: self.log(r['stderr'], 'err')
                self.set_status('Pull done' if r['returncode'] == 0 else 'Pull failed',
                                C_GREEN if r['returncode'] == 0 else C_RED)
            threading.Thread(target=_do, daemon=True).start()

        def _push(upstream=False):
            rd = self._require_repo()
            if not rd: return
            remote = _ask_string(self._win, 'Push', 'Remote name:', 'origin')
            if not remote: return
            cur = _state['current']
            def _do():
                args = ['push'] + (['--set-upstream'] if upstream else []) + [remote, cur]
                r = _git(rd, *args)
                self.log(r['stdout'].strip() or r['stderr'].strip() or '✔ Pushed',
                         'ok' if r['returncode'] == 0 else 'err')
                self.set_status('Push done' if r['returncode'] == 0 else 'Push failed',
                                C_GREEN if r['returncode'] == 0 else C_RED)
            threading.Thread(target=_do, daemon=True).start()

        def _fetch_all():
            rd = self._require_repo()
            if not rd: return
            def _do():
                self.log('git fetch --all --prune…', 'info')
                r = _git(rd, 'fetch', '--all', '--prune')
                self.log(r['stdout'].strip() or r['stderr'].strip() or '✔ Fetched',
                         'ok' if r['returncode'] == 0 else 'warn')
                GLib.idle_add(_refresh)
            threading.Thread(target=_do, daemon=True).start()

        def _stash_push():
            rd = self._require_repo()
            if not rd: return
            msg = _ask_string(self._win, 'Stash Push', 'Message (optional):') or ''
            def _do():
                args = ['stash', 'push'] + (['-m', msg] if msg else [])
                r = _git(rd, *args)
                self.log(r['stdout'].strip() or r['stderr'].strip(),
                         'ok' if r['returncode'] == 0 else 'err')
                GLib.idle_add(_refresh)
            threading.Thread(target=_do, daemon=True).start()

        def _stash_action(action: str):
            rd = self._repo_path
            if not rd: return
            ref = _get_stash_ref()
            if not ref:
                self.set_status(f'Select a stash entry before {action}', C_ORANGE)
                return
            if action == 'drop':
                if not _ask_yes_no(self._win, f'Drop {ref}?',
                                   'This permanently deletes the stash entry and cannot be undone.'):
                    return
            def _do():
                r = _git(rd, 'stash', action, ref)
                self.log(r['stdout'].strip() or r['stderr'].strip(),
                         'ok' if r['returncode'] == 0 else 'err')
                GLib.idle_add(_refresh)
            threading.Thread(target=_do, daemon=True).start()

        def _stash_refresh():
            rd = self._repo_path
            if not rd: return
            def _do():
                stash_store.clear()
                sr = _git(rd, 'stash', 'list', '--format=%gd|%ci|%s')
                for line in sr['stdout'].splitlines():
                    parts = line.split('|', 2)
                    if len(parts) == 3:
                        ref, date, message = parts
                        GLib.idle_add(stash_store.append,
                                      [ref.strip(), date.strip()[:10], message.strip(), C_ORANGE])
            threading.Thread(target=_do, daemon=True).start()
        stash_refresh_btn.connect('clicked', lambda _: _stash_refresh())

        tree.connect('row-activated', lambda *_: _checkout())

        def _on_branch_key(widget, event):
            if event.keyval == Gdk.KEY_Delete:
                _delete_branch()
                return True
            return False
        tree.connect('key-press-event', _on_branch_key)

        outer.pack_start(self._sep(), False, False, 0)

        # Branch actions
        branch_act = self._action_bar(
            ('Checkout',        'suggested-action',   _checkout,
             'Switch your working tree to the selected branch'),
            ('New Branch',      None,                 _new_branch,
             'Create a new branch, optionally checking it out immediately'),
            ('Delete',          'destructive-action', _delete_branch,
             'Delete the selected branch — prompts for force-delete if unmerged'),
            None,
            ('Pull',            None,                 _pull,
             'Fetch and merge changes from the upstream tracking branch'),
            ('Push',            None,                 lambda: _push(False),
             'Push the current branch to a remote — you will be prompted for the remote name'),
            ('Push (upstream)', None,                 lambda: _push(True),
             'Push and set the remote tracking reference with --set-upstream'),
            None,
            ('Fetch All',       None,                 _fetch_all,
             'Download all objects from all remotes and prune deleted remote branches'),
        )
        outer.pack_start(branch_act, False, False, 0)
        outer.pack_start(self._sep(), False, False, 0)

        # Stash actions
        stash_act = self._action_bar(
            ('Stash Push', None, _stash_push,
             'Save all uncommitted changes onto the stash stack so your working tree becomes clean'),
            ('Pop',        None, lambda: _stash_action('pop'),
             'Apply the selected stash and remove it from the stack'),
            ('Apply',      None, lambda: _stash_action('apply'),
             'Apply the selected stash without removing it from the stack'),
            ('Drop',       'destructive-action', lambda: _stash_action('drop'),
             'Permanently delete the selected stash entry — this cannot be undone'),
        )
        outer.pack_start(stash_act, False, False, 0)

        self._page_reload_callbacks['branches'] = _refresh
        return outer

    # ═══════════════════════════════════════════════════════════════════════════
    # Page: Merge / Rebase
    # ═══════════════════════════════════════════════════════════════════════════
    def _build_merge_page(self) -> 'Gtk.Widget':
        scroll, body = self._scrolled_body()

        # ── Merge ────────────────────────────────────────────────────────────
        body.pack_start(self._section_label('Merge'), False, False, 0)
        body.pack_start(self._sep(), False, False, 0)

        merge_grid = Gtk.Grid(row_spacing=10, column_spacing=12)
        body.pack_start(merge_grid, False, False, 0)

        def _lbl(text):
            l = Gtk.Label(label=text); l.set_width_chars(14); l.set_xalign(1.0); return l

        merge_combo = Gtk.ComboBoxText()
        merge_combo.set_hexpand(True)
        merge_grid.attach(_lbl('Merge branch:'), 0, 0, 1, 1)
        merge_grid.attach(merge_combo, 1, 0, 1, 1)

        noff_chk   = Gtk.CheckButton(label='--no-ff (always create merge commit)')
        squash_chk = Gtk.CheckButton(label='--squash')
        merge_grid.attach(noff_chk,   1, 1, 1, 1)
        merge_grid.attach(squash_chk, 1, 2, 1, 1)

        merge_btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        body.pack_start(merge_btn_row, False, False, 0)

        btn_merge = Gtk.Button(label='Merge into Current')
        btn_merge.get_style_context().add_class('suggested-action')
        btn_abort_merge = Gtk.Button(label='Abort Merge')
        btn_abort_merge.get_style_context().add_class('destructive-action')
        for b in (btn_merge, btn_abort_merge):
            merge_btn_row.pack_start(b, False, False, 0)

        # ── Rebase ───────────────────────────────────────────────────────────
        body.pack_start(self._sep(), False, False, 0)
        body.pack_start(self._section_label('Rebase'), False, False, 0)
        body.pack_start(self._sep(), False, False, 0)

        rebase_grid = Gtk.Grid(row_spacing=10, column_spacing=12)
        body.pack_start(rebase_grid, False, False, 0)

        rebase_combo = Gtk.ComboBoxText()
        rebase_combo.set_hexpand(True)
        rebase_grid.attach(_lbl('Rebase onto:'), 0, 0, 1, 1)
        rebase_grid.attach(rebase_combo, 1, 0, 1, 1)

        rebase_btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        body.pack_start(rebase_btn_row, False, False, 0)

        for label, style in [
            ('Rebase', 'suggested-action'), ('Continue', None),
            ('Skip', None), ('Abort', 'destructive-action')
        ]:
            b = Gtk.Button(label=label)
            if style: b.get_style_context().add_class(style)
            rebase_btn_row.pack_start(b, False, False, 0)

        # ── Cherry-pick / other ───────────────────────────────────────────────
        body.pack_start(self._sep(), False, False, 0)
        body.pack_start(self._section_label('Other'), False, False, 0)
        body.pack_start(self._sep(), False, False, 0)

        other_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        body.pack_start(other_row, False, False, 0)

        btn_cherry = Gtk.Button(label='Cherry-pick (enter hash)…')
        btn_revert = Gtk.Button(label='Revert (enter hash)…')
        btn_reset_h = Gtk.Button(label='Reset Hard to HEAD')
        btn_reset_h.get_style_context().add_class('destructive-action')
        for b in (btn_cherry, btn_revert, btn_reset_h):
            other_row.pack_start(b, False, False, 0)

        def _populate_branches():
            rd = self._repo_path
            if not rd: return
            r = _git(rd, 'branch', '-a', '--format=%(refname:short)')
            for combo in (merge_combo, rebase_combo):
                combo.remove_all()
                for b in r['stdout'].splitlines():
                    b = b.strip().removeprefix('remotes/')
                    if b and not b.startswith('HEAD'):
                        combo.append_text(b)
                combo.set_active(0)

        def _do_merge():
            rd = self._require_repo()
            if not rd: return
            br = merge_combo.get_active_text()
            if not br: return
            flags = []
            if noff_chk.get_active():   flags.append('--no-ff')
            if squash_chk.get_active(): flags.append('--squash')
            def _do():
                self.log(f'git merge {" ".join(flags)} {br}…', 'info')
                r = _git(rd, 'merge', *flags, br)
                self.log(r['stdout'].strip() or r['stderr'].strip(),
                         'ok' if r['returncode'] == 0 else 'err')
                self.set_status('Merge done' if r['returncode'] == 0 else 'Merge failed',
                                C_GREEN if r['returncode'] == 0 else C_RED)
            threading.Thread(target=_do, daemon=True).start()

        def _abort_merge():
            rd = self._require_repo()
            if not rd: return
            def _do():
                r = _git(rd, 'merge', '--abort')
                self.log(r['stdout'].strip() or r['stderr'].strip() or '✔ Merge aborted',
                         'ok' if r['returncode'] == 0 else 'err')
            threading.Thread(target=_do, daemon=True).start()

        def _do_rebase():
            rd = self._require_repo()
            if not rd: return
            onto = rebase_combo.get_active_text()
            if not onto: return
            def _do():
                self.log(f'git rebase {onto}…', 'info')
                r = _git(rd, 'rebase', onto)
                self.log(r['stdout'].strip() or r['stderr'].strip(),
                         'ok' if r['returncode'] == 0 else 'err')
            threading.Thread(target=_do, daemon=True).start()

        def _rebase_ctrl(action: str):
            rd = self._require_repo()
            if not rd: return
            def _do():
                r = _git(rd, 'rebase', f'--{action}')
                self.log(r['stdout'].strip() or r['stderr'].strip(),
                         'ok' if r['returncode'] == 0 else 'err')
            threading.Thread(target=_do, daemon=True).start()

        def _cherry_pick_prompt():
            rd = self._require_repo()
            if not rd: return
            h = _ask_string(self._win, 'Cherry-pick', 'Commit hash:')
            if not h: return
            def _do():
                r = _git(rd, 'cherry-pick', h)
                self.log(r['stdout'].strip() or r['stderr'].strip(),
                         'ok' if r['returncode'] == 0 else 'err')
            threading.Thread(target=_do, daemon=True).start()

        def _revert_prompt():
            rd = self._require_repo()
            if not rd: return
            h = _ask_string(self._win, 'Revert', 'Commit hash:')
            if not h: return
            def _do():
                r = _git(rd, 'revert', '--no-edit', h)
                self.log(r['stdout'].strip() or r['stderr'].strip(),
                         'ok' if r['returncode'] == 0 else 'err')
            threading.Thread(target=_do, daemon=True).start()

        def _reset_hard_head():
            rd = self._require_repo()
            if not rd: return
            if not _ask_yes_no(self._win, 'Reset Hard to HEAD?',
                               'ALL uncommitted changes will be LOST.'): return
            def _do():
                r = _git(rd, 'reset', '--hard', 'HEAD')
                self.log(r['stdout'].strip() or r['stderr'].strip(),
                         'ok' if r['returncode'] == 0 else 'err')
            threading.Thread(target=_do, daemon=True).start()

        btn_merge.connect('clicked', lambda _: _do_merge())
        btn_abort_merge.connect('clicked', lambda _: _abort_merge())

        rebase_btns = rebase_btn_row.get_children()
        rebase_btns[0].connect('clicked', lambda _: _do_rebase())
        rebase_btns[1].connect('clicked', lambda _: _rebase_ctrl('continue'))
        rebase_btns[2].connect('clicked', lambda _: _rebase_ctrl('skip'))
        rebase_btns[3].connect('clicked', lambda _: _rebase_ctrl('abort'))

        btn_cherry.connect('clicked', lambda _: _cherry_pick_prompt())
        btn_revert.connect('clicked', lambda _: _revert_prompt())
        btn_reset_h.connect('clicked', lambda _: _reset_hard_head())

        self._page_reload_callbacks['merge'] = _populate_branches
        return scroll

    # ═══════════════════════════════════════════════════════════════════════════
    # Page: Remotes
    # ═══════════════════════════════════════════════════════════════════════════
    def _build_remote_page(self) -> 'Gtk.Widget':
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        outer.pack_start(scroll, True, True, 0)

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        inner.set_margin_start(18); inner.set_margin_end(18)
        inner.set_margin_top(10);   inner.set_margin_bottom(10)
        scroll.add(inner)

        tb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        inner.pack_start(tb, False, False, 0)
        lbl = Gtk.Label()
        lbl.set_markup('<b>Remotes</b>')
        lbl.set_hexpand(True); lbl.set_xalign(0.0)
        tb.pack_start(lbl, True, True, 0)
        btn_ref = Gtk.Button(label='↺ Refresh')
        btn_ref.connect('clicked', lambda _: _refresh())
        tb.pack_start(btn_ref, False, False, 0)

        # Remote TreeView — name | url | type | color
        store = Gtk.ListStore(str, str, str, str)
        tree = Gtk.TreeView(model=store)
        tree.set_headers_visible(True)
        tree.get_selection().set_mode(Gtk.SelectionMode.SINGLE)
        for i, (title, width, stretch) in enumerate([
            ('Remote', 100, False), ('URL', 380, True), ('Direction', 80, False)
        ]):
            r = Gtk.CellRendererText()
            r.set_property('ellipsize', Pango.EllipsizeMode.MIDDLE)
            col = Gtk.TreeViewColumn(title, r, text=i, foreground=3)
            col.set_min_width(width); col.set_expand(stretch); col.set_resizable(True)
            tree.append_column(col)
        inner.pack_start(tree, True, True, 0)

        # SSH key section
        inner.pack_start(self._sep(), False, False, 0)
        inner.pack_start(self._section_label('SSH Key for URL Update'), False, False, 0)

        key_grid = Gtk.Grid(row_spacing=8, column_spacing=12)
        inner.pack_start(key_grid, False, False, 0)
        key_lbl = Gtk.Label(label='SSH Key:')
        key_lbl.set_width_chars(12); key_lbl.set_xalign(1.0)
        key_sel = _KeySelector(self._win)
        key_grid.attach(key_lbl, 0, 0, 1, 1)
        key_grid.attach(key_sel, 1, 0, 1, 1)

        dry_run = Gtk.CheckButton(label='Dry run (preview — no changes written)')
        dry_run.set_active(True)
        dry_run.set_margin_start(120)
        inner.pack_start(dry_run, False, False, 0)

        def _refresh():
            rd = self._repo_path
            if not rd: return
            store.clear()
            seen = set()
            r = _git(rd, 'remote', '-v')
            for line in r['stdout'].splitlines():
                parts = line.split()
                if len(parts) < 3: continue
                name, url, kind = parts[0], parts[1], parts[2].strip('()')
                if (name, url, kind) in seen: continue
                seen.add((name, url, kind))
                color = C_GREEN if (url.startswith('git@') or url.startswith('ssh://')) \
                        else (C_ORANGE if url.startswith('https://') else C_GRAY)
                store.append([name, url, kind, color])
            self.set_status(f'{len(seen)} remote entries', C_BLUE)

        def _sel() -> tuple:
            model, it = tree.get_selection().get_selected()
            if not it: return None, None
            v = model[it]
            return v[0], v[1]

        def _update_ssh():
            rd = self._require_repo(); key = key_sel.get_value()
            if not rd: return
            if not key: _show_error(self._win, 'No SSH key selected.'); return
            name, _ = _sel(); dry = dry_run.get_active()
            def _do():
                results = ssh_config.update_repo_remotes(
                    rd, key, remotes=[name] if name else None,
                    dry_run=dry, yes=not dry)
                for res in results:
                    if res.get('skipped'):
                        self.log(f"{res['remote']}: skipped — {res.get('reason')}", 'warn')
                    else:
                        pfx = '[DRY] ' if dry else ''
                        self.log(f"{pfx}{res['remote']}: {res.get('original_url')}", 'dim')
                        self.log(f"  → {res.get('new_url')} (alias={res.get('alias')})",
                                 'info' if dry else 'ok')
                if not dry: GLib.idle_add(_refresh)
                self.set_status('Done' if not dry else 'Dry run done',
                                C_GREEN if not dry else C_BLUE)
            threading.Thread(target=_do, daemon=True).start()

        def _add_remote():
            rd = self._require_repo()
            if not rd: return
            name = _ask_string(self._win, 'Add Remote', 'Remote name:', 'origin')
            if not name: return
            url = _ask_string(self._win, 'Add Remote', 'Remote URL:')
            if not url: return
            def _do():
                r = _git(rd, 'remote', 'add', name, url)
                self.log(f'✔ Added {name}' if r['returncode'] == 0 else r['stderr'],
                         'ok' if r['returncode'] == 0 else 'err')
                GLib.idle_add(_refresh)
            threading.Thread(target=_do, daemon=True).start()

        def _remove_remote():
            rd = self._require_repo(); name, _ = _sel()
            if not rd or not name: return
            if not _ask_yes_no(self._win, f'Remove remote "{name}"?'): return
            def _do():
                r = _git(rd, 'remote', 'remove', name)
                self.log(f'✔ Removed {name}' if r['returncode'] == 0 else r['stderr'],
                         'ok' if r['returncode'] == 0 else 'err')
                GLib.idle_add(_refresh)
            threading.Thread(target=_do, daemon=True).start()

        def _rename_remote():
            rd = self._require_repo(); name, _ = _sel()
            if not rd or not name: return
            new = _ask_string(self._win, 'Rename Remote', 'New name:', name)
            if not new or new == name: return
            def _do():
                r = _git(rd, 'remote', 'rename', name, new)
                self.log(f'✔ Renamed {name} → {new}' if r['returncode'] == 0 else r['stderr'],
                         'ok' if r['returncode'] == 0 else 'err')
                GLib.idle_add(_refresh)
            threading.Thread(target=_do, daemon=True).start()

        def _set_url():
            rd = self._require_repo(); name, old = _sel()
            if not rd or not name: return
            new = _ask_string(self._win, f'Set URL — {name}', 'New URL:', old or '')
            if not new or new == old: return
            def _do():
                r = _git(rd, 'remote', 'set-url', name, new)
                self.log(f'✔ {name} → {new}' if r['returncode'] == 0 else r['stderr'],
                         'ok' if r['returncode'] == 0 else 'err')
                GLib.idle_add(_refresh)
            threading.Thread(target=_do, daemon=True).start()

        def _fetch(sel_only=False):
            rd = self._require_repo()
            if not rd: return
            name, _ = _sel() if sel_only else (None, None)
            if sel_only and not name: return
            args = ['fetch', name, '--prune'] if name else ['fetch', '--all', '--prune']
            def _do():
                self.log(f'git {" ".join(args)}…', 'info')
                r = _git(rd, *args)
                self.log(r['stdout'].strip() or r['stderr'].strip() or '✔ Fetched',
                         'ok' if r['returncode'] == 0 else 'warn')
            threading.Thread(target=_do, daemon=True).start()

        outer.pack_start(self._sep(), False, False, 0)
        outer.pack_start(self._action_bar(
            ('Update to SSH',   'suggested-action',   _update_ssh,
             'Rewrite remote URLs to use the chosen SSH key alias'),
            ('Add Remote',      None,                 _add_remote,
             'Register a new named remote URL'),
            ('Remove',          'destructive-action', _remove_remote,
             'Delete the selected remote from the repository configuration'),
            ('Rename',          None,                 _rename_remote,
             'Give the selected remote a new name'),
            ('Set URL',         None,                 _set_url,
             'Change the URL of the selected remote'),
            None,
            ('Fetch All',       None,                 _fetch,
             'Download new objects from every configured remote'),
        ), False, False, 0)

        self._page_reload_callbacks['remotes'] = _refresh
        return outer

    # ═══════════════════════════════════════════════════════════════════════════
    # Page: Worktrees
    # ═══════════════════════════════════════════════════════════════════════════
    def _build_worktree_page(self) -> 'Gtk.Widget':
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        tb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        tb.set_margin_start(18); tb.set_margin_end(18)
        tb.set_margin_top(10);   tb.set_margin_bottom(6)
        outer.pack_start(tb, False, False, 0)
        lbl = Gtk.Label()
        lbl.set_markup('<b>Worktrees</b>')
        lbl.set_hexpand(True); lbl.set_xalign(0.0)
        tb.pack_start(lbl, True, True, 0)
        btn_ref = Gtk.Button(label='↺ Refresh')
        btn_ref.connect('clicked', lambda _: _refresh())
        tb.pack_start(btn_ref, False, False, 0)

        # path | branch | head | flags | color
        store = Gtk.ListStore(str, str, str, str, str)
        tree = Gtk.TreeView(model=store)
        tree.set_headers_visible(True)
        tree.get_selection().set_mode(Gtk.SelectionMode.SINGLE)
        for i, (title, width, stretch) in enumerate([
            ('Path', 300, True), ('Branch', 160, False),
            ('HEAD', 80, False), ('Flags', 80, False)
        ]):
            r = Gtk.CellRendererText()
            r.set_property('ellipsize', Pango.EllipsizeMode.MIDDLE)
            col = Gtk.TreeViewColumn(title, r, text=i, foreground=4)
            col.set_min_width(width); col.set_expand(stretch); col.set_resizable(True)
            tree.append_column(col)

        tbl_scroll = Gtk.ScrolledWindow()
        tbl_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        tbl_scroll.add(tree)
        tbl_frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        tbl_frame.set_margin_start(18); tbl_frame.set_margin_end(18)
        tbl_frame.pack_start(tbl_scroll, True, True, 0)
        outer.pack_start(tbl_frame, True, True, 0)

        def _parse_worktrees(stdout: str):
            result = []
            for block in stdout.strip().split('\n\n'):
                d: Dict = {}
                for line in block.strip().splitlines():
                    if ' ' in line:
                        k, v = line.split(' ', 1)
                        d[k] = v
                    else:
                        d[line.strip()] = True
                if 'worktree' in d:
                    result.append(d)
            return result

        def _refresh():
            rd = self._repo_path
            if not rd: return
            def _do():
                r = _git(rd, 'worktree', 'list', '--porcelain')
                trees = _parse_worktrees(r['stdout'])
                def _populate():
                    store.clear()
                    for wt in trees:
                        path   = wt.get('worktree', '?')
                        branch = wt.get('branch', 'detached').replace('refs/heads/', '')
                        head   = wt.get('HEAD', '?')[:8]
                        flags  = ' '.join(f for f in ('locked', 'prunable', 'bare', 'detached')
                                         if wt.get(f) is True)
                        color  = C_ORANGE if wt.get('locked') else \
                                 (C_GRAY if wt.get('prunable') else '#cdd6f4')
                        store.append([path, branch, head, flags, color])
                GLib.idle_add(_populate)
                self.set_status(f'{len(trees)} worktree(s)', C_BLUE)
            threading.Thread(target=_do, daemon=True).start()

        def _sel_path() -> Optional[str]:
            return self._get_selected_value(tree, 0)

        def _add_worktree():
            rd = self._require_repo()
            if not rd: return
            path = _ask_string(self._win, 'Add Worktree', 'Directory path for new worktree:')
            if not path: return
            branch = _ask_string(self._win, 'Add Worktree',
                                  'Branch (existing or new — prefix new with +):')
            if not branch: return
            def _do():
                args = ['worktree', 'add', path]
                if branch.startswith('+'):
                    args += ['-b', branch[1:]]
                else:
                    args.append(branch)
                r = _git(rd, *args)
                self.log(r['stdout'].strip() or r['stderr'].strip(),
                         'ok' if r['returncode'] == 0 else 'err')
                GLib.idle_add(_refresh)
            threading.Thread(target=_do, daemon=True).start()

        def _remove_worktree():
            rd = self._require_repo(); path = _sel_path()
            if not rd or not path: return
            if path == rd:
                _show_error(self._win, 'Cannot remove the main worktree.'); return
            if not _ask_yes_no(self._win, f'Remove worktree?\n{path}'): return
            def _do():
                r = _git(rd, 'worktree', 'remove', path)
                self.log(r['stdout'].strip() or r['stderr'].strip(),
                         'ok' if r['returncode'] == 0 else 'err')
                GLib.idle_add(_refresh)
            threading.Thread(target=_do, daemon=True).start()

        def _lock_worktree():
            rd = self._require_repo(); path = _sel_path()
            if not rd or not path: return
            reason = _ask_string(self._win, 'Lock Worktree', 'Reason (optional):') or ''
            def _do():
                args = ['worktree', 'lock'] + (['--reason', reason] if reason else []) + [path]
                r = _git(rd, *args)
                self.log(r['stdout'].strip() or r['stderr'].strip() or '✔ Locked',
                         'ok' if r['returncode'] == 0 else 'err')
                GLib.idle_add(_refresh)
            threading.Thread(target=_do, daemon=True).start()

        def _unlock_worktree():
            rd = self._require_repo(); path = _sel_path()
            if not rd or not path: return
            def _do():
                r = _git(rd, 'worktree', 'unlock', path)
                self.log(r['stdout'].strip() or r['stderr'].strip() or '✔ Unlocked',
                         'ok' if r['returncode'] == 0 else 'err')
                GLib.idle_add(_refresh)
            threading.Thread(target=_do, daemon=True).start()

        def _open_fm():
            path = _sel_path()
            if path:
                os.system(f'xdg-open {shlex.quote(path)} &')

        def _prune():
            rd = self._require_repo()
            if not rd: return
            def _do():
                r = _git(rd, 'worktree', 'prune')
                self.log(r['stdout'].strip() or r['stderr'].strip() or '✔ Pruned',
                         'ok' if r['returncode'] == 0 else 'err')
                GLib.idle_add(_refresh)
            threading.Thread(target=_do, daemon=True).start()

        outer.pack_start(self._sep(), False, False, 0)
        outer.pack_start(self._action_bar(
            ('Open Folder',  None,                 _open_fm,
             'Open the selected worktree directory in the system file manager'),
            ('Add Worktree', 'suggested-action',   _add_worktree,
             'Create a new linked worktree at a specified path, on an existing or new branch'),
            ('Remove',       'destructive-action', _remove_worktree,
             'Delete the selected linked worktree (the main worktree cannot be removed)'),
            None,
            ('Lock',         None,                 _lock_worktree,
             'Mark the selected worktree as locked to prevent automatic pruning'),
            ('Unlock',       None,                 _unlock_worktree,
             'Remove the lock from the selected worktree'),
            ('Prune',        None,                 _prune,
             'Clean up stale worktree files for worktrees no longer on disk'),
        ), False, False, 0)

        self._page_reload_callbacks['worktrees'] = _refresh
        return outer

    # ═══════════════════════════════════════════════════════════════════════════
    # Page: SSH Keys
    # ═══════════════════════════════════════════════════════════════════════════
    def _build_keys_page(self) -> 'Gtk.Widget':
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        tb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        tb.set_margin_start(18); tb.set_margin_end(18)
        tb.set_margin_top(10);   tb.set_margin_bottom(6)
        outer.pack_start(tb, False, False, 0)
        lbl = Gtk.Label()
        lbl.set_markup('<b>SSH Keys</b>')
        lbl.set_hexpand(True); lbl.set_xalign(0.0)
        tb.pack_start(lbl, True, True, 0)
        tb.pack_start(Gtk.Button(label='↺ Refresh'), False, False, 0)
        tb.get_children()[-1].connect('clicked', lambda _: _refresh())

        # Keys: path | type | perms | dup | fingerprint | color
        store = Gtk.ListStore(str, str, str, str, str, str)
        tree = Gtk.TreeView(model=store)
        tree.set_headers_visible(True)
        tree.get_selection().set_mode(Gtk.SelectionMode.SINGLE)
        for i, (title, width, stretch) in enumerate([
            ('Path', 260, True), ('Type', 80, False), ('Perms', 65, False),
            ('Dup', 40, False), ('Fingerprint (SHA-256)', 280, True)
        ]):
            r = Gtk.CellRendererText()
            r.set_property('ellipsize', Pango.EllipsizeMode.MIDDLE)
            col = Gtk.TreeViewColumn(title, r, text=i, foreground=5)
            col.set_min_width(width); col.set_expand(stretch); col.set_resizable(True)
            tree.append_column(col)

        tbl_scroll = Gtk.ScrolledWindow()
        tbl_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        tbl_scroll.add(tree)
        tbl_frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        tbl_frame.set_margin_start(18); tbl_frame.set_margin_end(18)
        tbl_frame.pack_start(tbl_scroll, True, True, 0)
        outer.pack_start(tbl_frame, True, True, 0)

        # Agent section
        inner_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        inner_box.set_margin_start(18); inner_box.set_margin_end(18)
        inner_box.set_margin_top(8);    inner_box.set_margin_bottom(8)
        outer.pack_start(self._sep(), False, False, 0)
        outer.pack_start(inner_box, False, False, 0)
        inner_box.pack_start(self._section_label('ssh-agent Loaded Keys'), False, False, 0)
        agent_lbl = Gtk.Label()
        agent_lbl.set_xalign(0.0)
        agent_lbl.set_line_wrap(True)
        agent_lbl.set_markup(_markup('(unknown)', C_GRAY))
        inner_box.pack_start(agent_lbl, False, False, 0)

        def _refresh():
            def _do():
                import subprocess
                keys = ssh_keys.discover_keys()
                ar = subprocess.run(['ssh-add', '-l'], capture_output=True, text=True)
                lines = ar.stdout.strip() or ar.stderr.strip() or '(no keys loaded)'
                def _populate():
                    store.clear()
                    for k in keys:
                        perms = '✔' if k.get('permissions_ok') else '✖'
                        dup   = '●' if k.get('duplicate') else ''
                        fp    = k.get('fingerprint') or '—'
                        color = C_ORANGE if k.get('duplicate') else \
                                (C_RED if not k.get('permissions_ok') else C_GREEN)
                        store.append([k.get('path', ''), k.get('type', '—'), perms, dup, fp, color])
                    agent_lbl.set_markup(
                        _markup(lines, C_GREEN if ar.returncode == 0 else C_GRAY))
                    self.log(f'Found {len(keys)} key(s)', 'info')
                    self.set_status(f'{len(keys)} key(s) found', C_BLUE)
                GLib.idle_add(_populate)
            threading.Thread(target=_do, daemon=True).start()

        def _sel_path() -> Optional[str]:
            return self._get_selected_value(tree, 0)

        def _fix_sel():
            path = _sel_path()
            if not path: return
            dry = _ask_yes_no(self._win, f'Fix permissions on:\n{path}', 'Dry run?')
            def _do():
                r = ssh_keys.fix_permissions_for_file(path, dry_run=dry)
                if dry:
                    self.log(f'[DRY] {path}: would set {r.get("would_set_mode")} '
                             f'(current {r.get("current_mode")})', 'info')
                elif r.get('changed'):
                    self.log(f'✔ Fixed {path} → {r.get("current_mode")}', 'ok')
                else:
                    self.log(f'{r.get("reason")} ({r.get("current_mode")})', 'dim')
                GLib.idle_add(_refresh)
            threading.Thread(target=_do, daemon=True).start()

        def _fix_all():
            def _do():
                fixed = 0
                for k in ssh_keys.discover_keys():
                    if not k.get('permissions_ok') and k.get('path'):
                        r = ssh_keys.fix_permissions_for_file(k['path'], dry_run=False)
                        if r.get('changed'):
                            self.log(f'✔ Fixed {k["path"]}', 'ok'); fixed += 1
                self.log(f'Fixed {fixed} key(s)', 'info' if fixed else 'dim')
                GLib.idle_add(_refresh)
            threading.Thread(target=_do, daemon=True).start()

        def _add_agent():
            path = _sel_path()
            if not path: return
            def _do():
                r = ssh_keys.add_to_agent(path)
                self.log('✔ Added to agent' if r.get('added')
                         else f'✖ {r.get("reason") or r.get("stderr") or "Failed"}',
                         'ok' if r.get('added') else 'err')
                GLib.idle_add(_refresh)
            threading.Thread(target=_do, daemon=True).start()

        def _remove_agent():
            path = _sel_path()
            if not path: return
            def _do():
                import subprocess
                r = subprocess.run(['ssh-add', '-d', path], capture_output=True, text=True)
                self.log('✔ Removed from agent' if r.returncode == 0
                         else r.stderr.strip(), 'ok' if r.returncode == 0 else 'err')
                GLib.idle_add(_refresh)
            threading.Thread(target=_do, daemon=True).start()

        outer.pack_start(self._sep(), False, False, 0)
        outer.pack_start(self._action_bar(
            ('Fix Selected',      None,                 _fix_sel,
             'Correct the file permissions of the selected SSH key to 600 (required by SSH)'),
            ('Fix All',           None,                 _fix_all,
             'Fix permissions on every key that currently has incorrect permissions'),
            None,
            ('Add to Agent',      'suggested-action',   _add_agent,
             'Load the selected SSH key into the running ssh-agent for passwordless use'),
            ('Remove from Agent', 'destructive-action', _remove_agent,
             'Unload the selected SSH key from the ssh-agent'),
        ), False, False, 0)

        self._page_reload_callbacks['keys'] = _refresh
        GLib.idle_add(_refresh)
        return outer

    # ── Window icon ───────────────────────────────────────────────────────────
    def _set_icon(self):
        here = Path(__file__).parent.parent
        for p in [
            here / 'assets' / 'git-ssh-helper.png',
            Path.home() / '.local' / 'share' / 'icons' / 'hicolor' / '48x48' / 'apps' / 'git-ssh-helper.png',
            Path('/usr/share/icons/hicolor/48x48/apps/git-ssh-helper.png'),
            here / 'assets' / 'git-ssh-helper.svg',
        ]:
            if p.exists():
                self._win.set_icon_from_file(str(p)); return


# ══════════════════════════════════════════════════════════════════════════════
# Tkinter fallback
# ══════════════════════════════════════════════════════════════════════════════
def _run_tk_fallback() -> int:
    try:
        import tkinter as tk
    except Exception:
        print('[SSH Git Manager] Neither GTK 3 nor Tkinter is available.', file=sys.stderr)
        return 1
    root = tk.Tk()
    root.title('SSH Git Manager')
    root.geometry('600x300')
    root.configure(bg='#1e1e2e')
    tk.Label(root, text='SSH Git Manager', bg='#1e1e2e', fg='#cba6f7',
             font=('sans-serif', 16, 'bold')).pack(pady=30)
    tk.Label(root, text='GTK 3 (PyGObject) is not available.\nInstall it for the full GUI:',
             bg='#1e1e2e', fg='#888888', font=('sans-serif', 10)).pack()
    tk.Label(root, text='sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0',
             bg='#1e1e2e', fg='#fab387', font=('monospace', 10)).pack(pady=16)
    root.mainloop()
    return 0


# ══════════════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════════════
def run_gui() -> int:
    # Re-exec with snap GTK vars stripped to avoid libpthread clash
    _SNAP_GTK_VARS = (
        'GTK_PATH', 'GTK_EXE_PREFIX', 'GTK_IM_MODULE_FILE',
        'GDK_PIXBUF_MODULEDIR', 'GDK_PIXBUF_MODULE_FILE',
        'GIO_MODULE_DIR', 'GSETTINGS_SCHEMA_DIR',
    )
    if any('/snap/' in os.environ.get(v, '') for v in _SNAP_GTK_VARS):
        import subprocess
        clean_env = {k: v for k, v in os.environ.items() if k not in _SNAP_GTK_VARS}
        return subprocess.run([sys.executable] + sys.argv, env=clean_env).returncode

    if not _GTK_OK:
        return _run_tk_fallback()
    _GTKApp()
    Gtk.main()
    return 0


if __name__ == '__main__':
    sys.exit(run_gui())
