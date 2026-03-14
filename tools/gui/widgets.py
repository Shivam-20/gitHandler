"""tools.gui.widgets — Shared GTK widgets and dialog helpers."""
from __future__ import annotations

import json
import os
import shlex
from pathlib import Path
from typing import Callable, Dict, List, Optional

from gi.repository import Gtk, GLib, Pango, Gdk

from tools.gui.css import C_GREEN, C_RED, C_ORANGE, C_BLUE, C_GRAY

try:
    from tools import ssh_keys, core
except Exception:
    import tools.ssh_keys as ssh_keys  # type: ignore
    import tools.core as core          # type: ignore


# ── Recent repos ──────────────────────────────────────────────────────────────
_RECENT_FILE = Path.home() / '.local' / 'share' / 'git-ssh-helper' / 'recent.json'


def load_recent() -> List[str]:
    try:
        return json.loads(_RECENT_FILE.read_text())[:10]
    except Exception:
        return []


def add_recent(path: str) -> None:
    try:
        lst = [p for p in load_recent() if p != path]
        lst.insert(0, path)
        _RECENT_FILE.parent.mkdir(parents=True, exist_ok=True)
        _RECENT_FILE.write_text(json.dumps(lst[:10]))
    except Exception:
        pass


# ── Pango markup ──────────────────────────────────────────────────────────────
def markup(text: str, color: str, bold: bool = False) -> str:
    b, eb = ('<b>', '</b>') if bold else ('', '')
    return f'<span foreground="{color}">{b}{GLib.markup_escape_text(text)}{eb}</span>'


# ── Git runner ────────────────────────────────────────────────────────────────
def git(repo: str, *args) -> Dict:
    return core.run_git(list(args), cwd=repo)


# ── Diff colouriser ───────────────────────────────────────────────────────────
def apply_diff_colors(buf, text: str) -> None:
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


def make_diff_view() -> tuple:
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
def ask_string(parent, title: str, prompt: str, default: str = '') -> Optional[str]:
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


def ask_yes_no(parent, title: str, message: str = '') -> bool:
    dlg = Gtk.MessageDialog(transient_for=parent, flags=Gtk.DialogFlags.MODAL,
                             message_type=Gtk.MessageType.QUESTION,
                             buttons=Gtk.ButtonsType.YES_NO, text=title)
    if message:
        dlg.format_secondary_text(message)
    resp = dlg.run(); dlg.destroy()
    return resp == Gtk.ResponseType.YES


def show_error(parent, title: str, message: str = '') -> None:
    dlg = Gtk.MessageDialog(transient_for=parent, flags=Gtk.DialogFlags.MODAL,
                             message_type=Gtk.MessageType.ERROR,
                             buttons=Gtk.ButtonsType.CLOSE, text=title)
    if message:
        dlg.format_secondary_text(message)
    dlg.run(); dlg.destroy()


def browse_dir(parent, title: str = 'Select directory') -> Optional[str]:
    dlg = Gtk.FileChooserDialog(title=title, transient_for=parent,
                                 action=Gtk.FileChooserAction.SELECT_FOLDER)
    dlg.add_button('Cancel', Gtk.ResponseType.CANCEL)
    dlg.add_button('Select', Gtk.ResponseType.OK)
    resp = dlg.run(); path = dlg.get_filename(); dlg.destroy()
    return path if resp == Gtk.ResponseType.OK else None


def browse_file(parent, title: str = 'Select file',
                start_dir: str = '~') -> Optional[str]:
    dlg = Gtk.FileChooserDialog(title=title, transient_for=parent,
                                 action=Gtk.FileChooserAction.OPEN)
    dlg.add_button('Cancel', Gtk.ResponseType.CANCEL)
    dlg.add_button('Select', Gtk.ResponseType.OK)
    dlg.set_current_folder(os.path.expanduser(start_dir))
    resp = dlg.run(); path = dlg.get_filename(); dlg.destroy()
    return path if resp == Gtk.ResponseType.OK else None


# ── Global repo bar ───────────────────────────────────────────────────────────
class RepoBar(Gtk.Box):
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

        btn_browse = Gtk.Button(label='Browse\u2026')
        btn_browse.connect('clicked', self._browse)
        self.pack_start(btn_browse, False, False, 0)

        self._recent_btn = Gtk.MenuButton(label='Recent \u25be')
        self._recent_menu = Gtk.Menu()
        self._recent_btn.set_popup(self._recent_menu)
        self.pack_start(self._recent_btn, False, False, 0)

        btn_load = Gtk.Button(label='\u21ba Load')
        btn_load.get_style_context().add_class('suggested-action')
        btn_load.connect('clicked', lambda _: self._do_load())
        self.pack_start(btn_load, False, False, 0)

        sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        sep.set_margin_start(4); sep.set_margin_end(4)
        self.pack_start(sep, False, False, 0)

        self._branch_lbl = Gtk.Label()
        self._branch_lbl.get_style_context().add_class('branch-badge')
        self._branch_lbl.set_markup(markup('no repo', C_GRAY))
        self.pack_start(self._branch_lbl, False, False, 0)

        sep2 = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        sep2.set_margin_start(4); sep2.set_margin_end(4)
        self.pack_start(sep2, False, False, 0)

        self._btn_pull = Gtk.Button(label='\u2193 Pull')
        self._btn_pull.set_tooltip_text('Fetch and merge from upstream (Ctrl+Shift+P)')
        self.pack_start(self._btn_pull, False, False, 0)

        self._btn_push = Gtk.Button(label='\u2191 Push')
        self._btn_push.set_tooltip_text('Push current branch to remote (Ctrl+Shift+U)')
        self.pack_start(self._btn_push, False, False, 0)

        self._rebuild_recent_menu()

    def set_path(self, path: str) -> None:
        self._entry.set_text(path)

    def get_path(self) -> str:
        return self._entry.get_text().strip()

    def update_branch(self, branch: str) -> None:
        self._branch_lbl.set_markup(
            markup(f'\u2481  {branch}', C_GREEN, bold=True) if branch
            else markup('no repo', C_GRAY))

    def _browse(self, *_):
        p = browse_dir(self._win, 'Select git repository')
        if p:
            self._entry.set_text(p)
            self._do_load()

    def _do_load(self, *_):
        rd = self._entry.get_text().strip()
        if not rd or not Path(rd).is_dir():
            show_error(self._win, 'Not a directory', rd or '(empty)'); return
        self._on_load(rd)

    def _rebuild_recent_menu(self):
        for child in self._recent_menu.get_children():
            self._recent_menu.remove(child)
        for p in load_recent():
            item = Gtk.MenuItem(label=p)
            item.connect('activate', lambda _, pp=p: [self._entry.set_text(pp), self._do_load()])
            self._recent_menu.append(item)
        self._recent_menu.show_all()


# ── SSH Key selector ──────────────────────────────────────────────────────────
class KeySelector(Gtk.Box):
    def __init__(self, parent_win):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._win = parent_win
        self._combo = Gtk.ComboBoxText()
        self._combo.set_hexpand(True)
        self.pack_start(self._combo, True, True, 0)
        btn_r = Gtk.Button(label='\u21ba')
        btn_r.set_tooltip_text('Refresh key list')
        btn_r.connect('clicked', lambda _: self.refresh())
        self.pack_start(btn_r, False, False, 0)
        btn_b = Gtk.Button(label='Browse\u2026')
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
        p = browse_file(self._win, 'Select SSH private key', '~/.ssh')
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
