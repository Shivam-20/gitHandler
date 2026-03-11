"""tools.gui_tk

GTK 3 GUI for git-ssh-helper, styled after the vpnUi project.
Falls back to Tkinter if GTK / PyGObject is not available.

Layout
──────
  Gtk.Window  +  Gtk.HeaderBar
  ├── Gtk.StackSidebar  (left nav)
  ├── Gtk.Stack         (page switcher)
  │   ├── Clone page
  │   ├── Branches page
  │   ├── Remotes page
  │   └── SSH Keys page
  └── Gtk.TextView      (shared log, bottom)
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


# ── Colour constants (match vpnUi palette) ────────────────────────────────────
C_GREEN  = '#2aa32a'
C_RED    = '#cc0000'
C_ORANGE = '#e68a00'
C_BLUE   = '#1a73e8'
C_GRAY   = '#888888'
C_DIM    = '#aaaaaa'
C_WHITE  = '#ffffff'

# Safe base classes for when GTK is not imported
_GtkBoxBase    = Gtk.Box    if _GTK_OK else object  # type: ignore[name-defined]


def _markup(text: str, color: str, bold: bool = False) -> str:
    b = '<b>' if bold else ''
    eb = '</b>' if bold else ''
    return f'<span foreground="{color}">{b}{text}{eb}</span>'


# ── Shared git helper ─────────────────────────────────────────────────────────
def _git(repo: str, *args) -> Dict:
    return core.run_git(list(args), cwd=repo)


# ── Dialog helpers ────────────────────────────────────────────────────────────
def _ask_string(parent, title: str, prompt: str, default: str = '') -> Optional[str]:
    dlg = Gtk.Dialog(title=title, transient_for=parent,
                     flags=Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT)
    dlg.set_default_size(420, -1)
    dlg.add_button('Cancel', Gtk.ResponseType.CANCEL)
    ok_btn = dlg.add_button('OK', Gtk.ResponseType.OK)
    ok_btn.get_style_context().add_class('suggested-action')
    dlg.set_default_response(Gtk.ResponseType.OK)

    box = dlg.get_content_area()
    box.set_margin_top(16)
    box.set_margin_bottom(16)
    box.set_margin_start(16)
    box.set_margin_end(16)
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
    dlg = Gtk.MessageDialog(transient_for=parent,
                             flags=Gtk.DialogFlags.MODAL,
                             message_type=Gtk.MessageType.QUESTION,
                             buttons=Gtk.ButtonsType.YES_NO,
                             text=title)
    if message:
        dlg.format_secondary_text(message)
    resp = dlg.run()
    dlg.destroy()
    return resp == Gtk.ResponseType.YES


def _show_error(parent, title: str, message: str = '') -> None:
    dlg = Gtk.MessageDialog(transient_for=parent,
                             flags=Gtk.DialogFlags.MODAL,
                             message_type=Gtk.MessageType.ERROR,
                             buttons=Gtk.ButtonsType.CLOSE,
                             text=title)
    if message:
        dlg.format_secondary_text(message)
    dlg.run()
    dlg.destroy()


def _browse_dir(parent, title: str = 'Select directory') -> Optional[str]:
    dlg = Gtk.FileChooserDialog(title=title, transient_for=parent,
                                 action=Gtk.FileChooserAction.SELECT_FOLDER)
    dlg.add_button('Cancel', Gtk.ResponseType.CANCEL)
    dlg.add_button('Select', Gtk.ResponseType.OK)
    resp = dlg.run()
    path = dlg.get_filename()
    dlg.destroy()
    return path if resp == Gtk.ResponseType.OK else None


def _browse_file(parent, title: str = 'Select file',
                 start_dir: str = '~') -> Optional[str]:
    dlg = Gtk.FileChooserDialog(title=title, transient_for=parent,
                                 action=Gtk.FileChooserAction.OPEN)
    dlg.add_button('Cancel', Gtk.ResponseType.CANCEL)
    dlg.add_button('Select', Gtk.ResponseType.OK)
    dlg.set_current_folder(os.path.expanduser(start_dir))
    resp = dlg.run()
    path = dlg.get_filename()
    dlg.destroy()
    return path if resp == Gtk.ResponseType.OK else None


# ── Repo bar widget ───────────────────────────────────────────────────────────
class _RepoBar(_GtkBoxBase):
    """Shared repo-directory picker used by Branches and Remotes pages."""

    def __init__(self, parent_win, on_load: Callable[[str], None]):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._win = parent_win
        self._on_load = on_load
        self._branch_label: Optional[Gtk.Label] = None
        self.set_margin_start(18)
        self.set_margin_end(18)
        self.set_margin_top(14)

        # Directory row
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.pack_start(row, False, False, 0)

        lbl = Gtk.Label(label='Repository:')
        lbl.set_width_chars(11)
        lbl.set_xalign(1.0)
        row.pack_start(lbl, False, False, 0)

        self._entry = Gtk.Entry()
        self._entry.set_hexpand(True)
        self._entry.set_placeholder_text('/path/to/repo')
        self._entry.connect('activate', lambda _: self._do_load())
        row.pack_start(self._entry, True, True, 0)

        btn_browse = Gtk.Button(label='Browse…')
        btn_browse.connect('clicked', self._browse)
        row.pack_start(btn_browse, False, False, 0)

        # Recent menu button
        self._recent_btn = Gtk.MenuButton(label='Recent ▾')
        self._recent_menu = Gtk.Menu()
        self._recent_btn.set_popup(self._recent_menu)
        row.pack_start(self._recent_btn, False, False, 0)
        self._rebuild_recent_menu()

        btn_load = Gtk.Button(label='Load')
        btn_load.get_style_context().add_class('suggested-action')
        btn_load.connect('clicked', lambda _: self._do_load())
        row.pack_start(btn_load, False, False, 0)

        # Branch badge row
        branch_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        branch_row.set_margin_start(97)  # align with entry
        self.pack_start(branch_row, False, False, 0)
        self._branch_label = Gtk.Label()
        self._branch_label.set_xalign(0.0)
        self._branch_label.set_markup(_markup('No repository loaded', C_GRAY))
        branch_row.pack_start(self._branch_label, False, False, 0)

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.set_margin_top(8)
        self.pack_start(sep, False, False, 0)

    def set_path(self, path: str) -> None:
        self._entry.set_text(path)

    def get_path(self) -> str:
        return self._entry.get_text().strip()

    def update_branch(self, branch: str) -> None:
        if self._branch_label:
            self._branch_label.set_markup(
                _markup(f'⑂  {branch}', C_GREEN, bold=True) if branch
                else _markup('No repository loaded', C_GRAY)
            )

    def _browse(self, *_):
        p = _browse_dir(self._win, 'Select git repository')
        if p:
            self._entry.set_text(p)
            self._do_load()

    def _do_load(self):
        rd = self._entry.get_text().strip()
        if not rd or not Path(rd).is_dir():
            _show_error(self._win, 'Not a directory', rd); return
        _add_recent(rd)
        self._rebuild_recent_menu()
        r = _git(rd, 'rev-parse', '--abbrev-ref', 'HEAD')
        branch = r.get('stdout', '').strip() or '?'
        self.update_branch(branch)
        self._on_load(rd)

    def _rebuild_recent_menu(self):
        for child in self._recent_menu.get_children():
            self._recent_menu.remove(child)
        for p in _load_recent():
            item = Gtk.MenuItem(label=p)
            item.connect('activate', lambda _, pp=p: [
                self._entry.set_text(pp), self._do_load()])
            self._recent_menu.append(item)
        self._recent_menu.show_all()


# ── Key selector widget ───────────────────────────────────────────────────────
class _KeySelector(_GtkBoxBase):
    def __init__(self, parent_win):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._win = parent_win
        self._combo = Gtk.ComboBoxText()
        self._combo.set_hexpand(True)
        self.pack_start(self._combo, True, True, 0)

        btn_refresh = Gtk.Button(label='↺')
        btn_refresh.set_tooltip_text('Refresh key list')
        btn_refresh.connect('clicked', lambda _: self.refresh())
        self.pack_start(btn_refresh, False, False, 0)

        btn_browse = Gtk.Button(label='Browse…')
        btn_browse.connect('clicked', self._browse)
        self.pack_start(btn_browse, False, False, 0)

        self.refresh()

    def refresh(self):
        current = self.get_value()
        self._combo.remove_all()
        for k in ssh_keys.discover_keys():
            if k.get('path'):
                self._combo.append_text(k['path'])
        if current:
            self._set_text(current)
        elif self._combo.get_model() and len(self._combo.get_model()):
            self._combo.set_active(0)

    def _browse(self, *_):
        p = _browse_file(self._win, 'Select SSH private key', '~/.ssh')
        if p:
            self._set_text(p)

    def _set_text(self, text: str):
        model = self._combo.get_model()
        for i, row in enumerate(model):
            if row[0] == text:
                self._combo.set_active(i)
                return
        self._combo.append_text(text)
        self._combo.set_active(len(model))

    def get_value(self) -> str:
        return self._combo.get_active_text() or ''


# ── Main GTK application ──────────────────────────────────────────────────────
class _GTKApp:
    def __init__(self):
        self._repo_path = ''
        self._log_buffer: Optional['Gtk.TextBuffer'] = None
        self._log_view:   Optional['Gtk.TextView']   = None
        self._status_lbl: Optional['Gtk.Label']      = None
        self._win:        Optional['Gtk.Window']     = None

        self._build_window()

    # ── Window skeleton ───────────────────────────────────────────────────────
    def _build_window(self):
        self._win = Gtk.Window(title='SSH Git Manager')
        self._win.set_default_size(980, 720)
        self._win.set_resizable(True)
        self._win.connect('delete-event', Gtk.main_quit)

        # HeaderBar
        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        header.props.title = 'SSH Git Manager'
        header.props.subtitle = 'Keys · Remotes · Branches'
        self._win.set_titlebar(header)

        try:
            self._set_icon()
        except Exception:
            pass

        # Root: vertical box
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._win.add(root)

        # ── Body: sidebar + stack ─────────────────────────────────────────────
        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        root.pack_start(body, True, True, 0)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(120)

        sidebar = Gtk.StackSidebar()
        sidebar.set_stack(self.stack)
        sidebar.set_size_request(150, -1)
        body.pack_start(sidebar, False, False, 0)

        sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        body.pack_start(sep, False, False, 0)

        body.pack_start(self.stack, True, True, 0)

        # ── Log section ───────────────────────────────────────────────────────
        sep2 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        root.pack_start(sep2, False, False, 0)
        root.pack_start(self._build_log(), False, False, 0)

        # ── Status bar ────────────────────────────────────────────────────────
        sep3 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        root.pack_start(sep3, False, False, 0)
        status_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        status_bar.set_margin_start(12)
        status_bar.set_margin_top(5)
        status_bar.set_margin_bottom(5)
        root.pack_start(status_bar, False, False, 0)
        self._status_lbl = Gtk.Label()
        self._status_lbl.set_markup(_markup('● Ready', C_GRAY))
        status_bar.pack_start(self._status_lbl, False, False, 0)

        # ── Pages ─────────────────────────────────────────────────────────────
        self.stack.add_titled(self._build_clone_page(),   'clone',    'Clone Repo')
        self.stack.add_titled(self._build_branch_page(),  'branches', 'Branches')
        self.stack.add_titled(self._build_remote_page(),  'remotes',  'Remotes')
        self.stack.add_titled(self._build_keys_page(),    'keys',     'SSH Keys')

        self._win.show_all()

    # ── Log ───────────────────────────────────────────────────────────────────
    def _build_log(self) -> 'Gtk.Box':
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(6)
        box.set_margin_bottom(6)

        hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.pack_start(hdr, False, False, 0)
        lbl = Gtk.Label()
        lbl.set_markup('<b>Output</b>')
        lbl.set_xalign(0.0)
        lbl.set_hexpand(True)
        hdr.pack_start(lbl, True, True, 0)
        btn_clear = Gtk.Button(label='Clear')
        btn_clear.connect('clicked', lambda *_: self._log_buffer.set_text(''))
        hdr.pack_start(btn_clear, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(160)
        box.pack_start(scroll, True, True, 0)

        self._log_view = Gtk.TextView()
        self._log_view.set_editable(False)
        self._log_view.set_cursor_visible(False)
        self._log_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._log_view.set_monospace(True)
        self._log_view.set_margin_start(8)
        self._log_view.set_margin_end(8)
        self._log_view.set_margin_top(4)
        self._log_view.set_margin_bottom(4)

        self._log_buffer = self._log_view.get_buffer()
        self._log_buffer.create_tag('ok',   foreground=C_GREEN)
        self._log_buffer.create_tag('err',  foreground=C_RED)
        self._log_buffer.create_tag('info', foreground=C_BLUE)
        self._log_buffer.create_tag('warn', foreground=C_ORANGE)
        self._log_buffer.create_tag('dim',  foreground=C_GRAY)

        scroll.add(self._log_view)
        return box

    def log(self, msg: str, tag: str = '') -> None:
        GLib.idle_add(self._append_log, msg, tag)

    def _append_log(self, msg: str, tag: str) -> bool:
        buf = self._log_buffer
        it = buf.get_end_iter()
        if tag in ('ok', 'err', 'info', 'warn', 'dim'):
            buf.insert_with_tags_by_name(it, msg + '\n', tag)
        else:
            buf.insert(it, msg + '\n')
        GLib.idle_add(self._scroll_log)
        return False

    def _scroll_log(self) -> bool:
        self._log_view.scroll_mark_onscreen(self._log_buffer.get_insert())
        return False

    def set_status(self, msg: str, color: str = C_GRAY) -> None:
        GLib.idle_add(self._status_lbl.set_markup,
                      _markup(f'● {msg}', color, bold=True))

    # ── Helpers ───────────────────────────────────────────────────────────────
    @staticmethod
    def _section_label(text: str) -> 'Gtk.Label':
        lbl = Gtk.Label()
        lbl.set_markup(f'<b>{text}</b>')
        lbl.set_xalign(0.0)
        return lbl

    @staticmethod
    def _sep() -> 'Gtk.Separator':
        s = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        s.set_margin_top(2)
        s.set_margin_bottom(2)
        return s

    @staticmethod
    def _scrolled_body() -> tuple:
        """Returns (scroll_widget, body_box) — use body for content."""
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        body.set_margin_top(18)
        body.set_margin_bottom(18)
        body.set_margin_start(18)
        body.set_margin_end(18)
        scroll.add(body)
        return scroll, body

    # ══════════════════════════════════════════════════════════════════════════
    # Page: Clone
    # ══════════════════════════════════════════════════════════════════════════
    def _build_clone_page(self) -> 'Gtk.Widget':
        scroll, body = self._scrolled_body()

        body.pack_start(self._section_label('Clone Repository'), False, False, 0)
        body.pack_start(self._sep(), False, False, 0)

        # Form grid
        grid = Gtk.Grid(row_spacing=10, column_spacing=12)
        body.pack_start(grid, False, False, 0)

        def _lbl(text):
            l = Gtk.Label(label=text)
            l.set_width_chars(13)
            l.set_xalign(1.0)
            return l

        # URL
        grid.attach(_lbl('Repository URL:'), 0, 0, 1, 1)
        url_entry = Gtk.Entry()
        url_entry.set_hexpand(True)
        url_entry.set_placeholder_text('git@github.com:user/repo.git')
        grid.attach(url_entry, 1, 0, 2, 1)

        # Clone dir
        grid.attach(_lbl('Clone into:'), 0, 1, 1, 1)
        dir_entry = Gtk.Entry()
        dir_entry.set_hexpand(True)
        dir_entry.set_placeholder_text('(leave blank for auto)')
        grid.attach(dir_entry, 1, 1, 1, 1)
        btn_dir = Gtk.Button(label='Browse…')
        btn_dir.connect('clicked', lambda _: dir_entry.set_text(
            _browse_dir(self._win, 'Clone into…') or dir_entry.get_text()))
        grid.attach(btn_dir, 2, 1, 1, 1)

        # SSH key
        grid.attach(_lbl('SSH Key:'), 0, 2, 1, 1)
        key_sel = _KeySelector(self._win)
        grid.attach(key_sel, 1, 2, 2, 1)

        # Clone button
        body.pack_start(self._sep(), False, False, 0)
        btn_clone = Gtk.Button(label='  ⬇   Clone Repository')
        btn_clone.get_style_context().add_class('suggested-action')
        btn_clone.set_halign(Gtk.Align.START)
        body.pack_start(btn_clone, False, False, 0)

        # Status label
        clone_status = Gtk.Label()
        clone_status.set_xalign(0.0)
        body.pack_start(clone_status, False, False, 0)

        # Post-clone
        body.pack_start(self._sep(), False, False, 0)
        body.pack_start(self._section_label('Post-Clone Actions'), False, False, 0)
        post_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        body.pack_start(post_row, False, False, 0)

        _repo_ref: Dict = {'path': None}

        btn_list_br = Gtk.Button(label='List Branches')
        btn_checkout = Gtk.Button(label='Checkout Branch')
        btn_open_fm  = Gtk.Button(label='Open Folder')
        btn_go_br    = Gtk.Button(label='→ Branches Page')
        for b in (btn_list_br, btn_checkout, btn_open_fm, btn_go_br):
            post_row.pack_start(b, False, False, 0)

        def _list_branches(*_):
            rd = _repo_ref['path']
            if not rd:
                self.log('No repo cloned yet.', 'warn'); return
            for b in clone_actions.list_branches(rd):
                self.log(f'  {b}', 'dim')

        def _checkout(*_):
            rd = _repo_ref['path']
            if not rd:
                _show_error(self._win, 'No repo cloned yet.'); return
            br = _ask_string(self._win, 'Checkout', 'Branch name:')
            if not br: return
            def _do():
                r = _git(rd, 'checkout', br)
                self.log(f'✔ {br}' if r['returncode'] == 0
                         else r['stderr'], 'ok' if r['returncode'] == 0 else 'err')
            threading.Thread(target=_do, daemon=True).start()

        def _open_fm(*_):
            rd = _repo_ref['path']
            if rd:
                os.system(f'xdg-open {shlex.quote(rd)} &')

        def _go_branches(*_):
            rd = _repo_ref['path']
            if rd:
                self._repo_path = rd
                self.stack.set_visible_child_name('branches')

        btn_list_br.connect('clicked', _list_branches)
        btn_checkout.connect('clicked', _checkout)
        btn_open_fm.connect('clicked', _open_fm)
        btn_go_br.connect('clicked', _go_branches)

        # Clone action
        def _do_clone(*_):
            url = url_entry.get_text().strip()
            key = key_sel.get_value()
            dest = dir_entry.get_text().strip() or None
            if not url:
                _show_error(self._win, 'Repository URL is required.'); return
            if not key:
                _show_error(self._win, 'SSH key is required.'); return

            btn_clone.set_sensitive(False)
            self.set_status('Cloning…', C_ORANGE)
            GLib.idle_add(clone_status.set_markup,
                          _markup('● Cloning…', C_ORANGE, bold=True))

            def _run():
                try:
                    cmd = core.build_ssh_command(key)
                    env = {'GIT_SSH_COMMAND': ' '.join(shlex.quote(c) for c in cmd)}
                    self.log(f'git clone {url}', 'info')
                    args = ['clone', url] + ([dest] if dest else [])
                    r = core.run_git(args, env_overrides=env)
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
                    self.set_status('Clone succeeded', C_GREEN)
                    GLib.idle_add(clone_status.set_markup,
                                  _markup(f'● Cloned → {rd}', C_GREEN, bold=True))
                    self._repo_path = rd
                finally:
                    GLib.idle_add(btn_clone.set_sensitive, True)

            threading.Thread(target=_run, daemon=True).start()

        btn_clone.connect('clicked', _do_clone)
        return scroll

    # ══════════════════════════════════════════════════════════════════════════
    # Page: Branches
    # ══════════════════════════════════════════════════════════════════════════
    def _build_branch_page(self) -> 'Gtk.Widget':
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        _state: Dict = {'repo': None, 'current': ''}

        # ── Repo bar ──────────────────────────────────────────────────────────
        def _on_load(rd: str):
            _state['repo'] = rd
            self._repo_path = rd
            cur = _git(rd, 'rev-parse', '--abbrev-ref', 'HEAD').get('stdout', '').strip()
            _state['current'] = cur
            repo_bar.update_branch(cur)
            _refresh()
            self.log(f'Loaded branches for {rd}', 'info')
            self.set_status(f'Branch: {cur}', C_GREEN)

        repo_bar = _RepoBar(self._win, _on_load)
        outer.pack_start(repo_bar, False, False, 0)

        # ── Branch list ───────────────────────────────────────────────────────
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        outer.pack_start(scroll, True, True, 0)

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        inner.set_margin_start(18)
        inner.set_margin_end(18)
        inner.set_margin_top(10)
        inner.set_margin_bottom(10)
        scroll.add(inner)

        # Toolbar
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        inner.pack_start(toolbar, False, False, 0)

        self._section_label('Branches')
        lbl_br = Gtk.Label()
        lbl_br.set_markup('<b>Branches</b>')
        lbl_br.set_xalign(0.0)
        lbl_br.set_hexpand(True)
        toolbar.pack_start(lbl_br, True, True, 0)

        show_remote = Gtk.CheckButton(label='Show remote')
        show_remote.set_active(True)
        toolbar.pack_start(show_remote, False, False, 0)

        btn_refresh = Gtk.Button(label='↺ Refresh')
        btn_refresh.connect('clicked', lambda _: _refresh())
        toolbar.pack_start(btn_refresh, False, False, 0)

        # TreeView — cols: name | location | notes | color | weight
        store = Gtk.ListStore(str, str, str, str, int)
        tree = Gtk.TreeView(model=store)
        tree.set_headers_visible(True)
        tree.get_selection().set_mode(Gtk.SelectionMode.SINGLE)

        for col_idx, (title, col_w) in enumerate(
                [('Branch', 320), ('Local / Remote', 110), ('Notes', 120)]):
            renderer = Gtk.CellRendererText()
            renderer.set_property('ellipsize', Pango.EllipsizeMode.MIDDLE)
            col = Gtk.TreeViewColumn(title, renderer,
                                     text=col_idx, foreground=3, weight=4)
            col.set_min_width(col_w)
            col.set_resizable(True)
            tree.append_column(col)

        inner.pack_start(tree, True, True, 0)

        def _refresh():
            rd = _state['repo']
            if not rd: return
            store.clear()
            cur = _state['current']
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

        show_remote.connect('toggled', lambda _: _refresh())

        def _get_selected() -> Optional[str]:
            model, it = tree.get_selection().get_selected()
            return model.get_value(it, 0) if it else None

        # ── Actions ───────────────────────────────────────────────────────────
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        outer.pack_start(sep, False, False, 0)

        act = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        act.set_margin_start(18)
        act.set_margin_end(18)
        act.set_margin_top(8)
        act.set_margin_bottom(8)
        outer.pack_start(act, False, False, 0)

        def _checkout(*_):
            br = _get_selected(); rd = _state['repo']
            if not br or not rd: return
            def _do():
                r = _git(rd, 'checkout', br)
                if r['returncode'] == 0:
                    _state['current'] = br
                    GLib.idle_add(repo_bar.update_branch, br)
                    self.log(f'✔ Checked out {br}', 'ok')
                    self.set_status(f'Branch: {br}', C_GREEN)
                    GLib.idle_add(_refresh)
                else:
                    self.log(r['stderr'] or r['stdout'], 'err')
            threading.Thread(target=_do, daemon=True).start()

        def _new_branch(*_):
            rd = _state['repo']
            if not rd: return
            name = _ask_string(self._win, 'New Branch', 'Branch name:')
            if not name: return
            checkout = _ask_yes_no(self._win, f'Checkout "{name}" after creating?')
            def _do():
                if checkout:
                    r = _git(rd, 'checkout', '-b', name)
                else:
                    r = _git(rd, 'branch', name)
                if r['returncode'] == 0:
                    self.log(f'✔ Created {"& checked out " if checkout else ""}{name}', 'ok')
                    if checkout:
                        _state['current'] = name
                        GLib.idle_add(repo_bar.update_branch, name)
                    GLib.idle_add(_refresh)
                else:
                    self.log(r['stderr'] or r['stdout'], 'err')
            threading.Thread(target=_do, daemon=True).start()

        def _delete(*_):
            br = _get_selected(); rd = _state['repo']
            if not br or not rd: return
            if br == _state['current']:
                _show_error(self._win, 'Cannot delete the current branch.'); return
            force = _ask_yes_no(self._win, f'Delete "{br}"?',
                                'Use force delete (even if unmerged)?')
            def _do():
                r = _git(rd, 'branch', '-D' if force else '-d', br)
                if r['returncode'] == 0:
                    self.log(f'✔ Deleted {br}', 'ok')
                    GLib.idle_add(_refresh)
                else:
                    self.log(r['stderr'] or r['stdout'], 'err')
            threading.Thread(target=_do, daemon=True).start()

        def _pull(*_):
            rd = _state['repo']
            if not rd: return
            def _do():
                self.log('git pull…', 'info')
                self.set_status('Pulling…', C_ORANGE)
                r = _git(rd, 'pull')
                self.log(r['stdout'].strip() or '✔ Up to date',
                         'ok' if r['returncode'] == 0 else 'err')
                if r['returncode'] != 0:
                    self.log(r['stderr'], 'err')
                self.set_status('Pull done' if r['returncode'] == 0 else 'Pull failed',
                                C_GREEN if r['returncode'] == 0 else C_RED)
            threading.Thread(target=_do, daemon=True).start()

        def _push(*_):
            rd = _state['repo']; cur = _state['current']
            if not rd: return
            remote = _ask_string(self._win, 'Push', 'Remote name:', 'origin')
            if not remote: return
            def _do():
                self.log(f'git push {remote} {cur}…', 'info')
                self.set_status('Pushing…', C_ORANGE)
                r = _git(rd, 'push', remote, cur)
                self.log(r['stdout'].strip() or r['stderr'].strip() or '✔ Pushed',
                         'ok' if r['returncode'] == 0 else 'err')
                self.set_status('Push done' if r['returncode'] == 0 else 'Push failed',
                                C_GREEN if r['returncode'] == 0 else C_RED)
            threading.Thread(target=_do, daemon=True).start()

        def _push_upstream(*_):
            rd = _state['repo']; cur = _state['current']
            if not rd: return
            remote = _ask_string(self._win, 'Push (set upstream)', 'Remote name:', 'origin')
            if not remote: return
            def _do():
                self.log(f'git push --set-upstream {remote} {cur}…', 'info')
                r = _git(rd, 'push', '--set-upstream', remote, cur)
                self.log(r['stdout'].strip() or r['stderr'].strip(),
                         'ok' if r['returncode'] == 0 else 'err')
            threading.Thread(target=_do, daemon=True).start()

        def _fetch_all(*_):
            rd = _state['repo']
            if not rd: return
            def _do():
                self.log('git fetch --all --prune…', 'info')
                r = _git(rd, 'fetch', '--all', '--prune')
                self.log(r['stdout'].strip() or r['stderr'].strip() or '✔ Fetched',
                         'ok' if r['returncode'] == 0 else 'warn')
                GLib.idle_add(_refresh)
            threading.Thread(target=_do, daemon=True).start()

        def _stash(*_):
            rd = _state['repo']
            if not rd: return
            msg = _ask_string(self._win, 'Stash', 'Stash message (optional):')
            def _do():
                args = ['stash', 'push'] + (['-m', msg] if msg else [])
                r = _git(rd, *args)
                self.log(r['stdout'].strip() or r['stderr'].strip(),
                         'ok' if r['returncode'] == 0 else 'err')
            threading.Thread(target=_do, daemon=True).start()

        tree.connect('row-activated', lambda *_: _checkout())

        _btn_defs = [
            ('Checkout',          'suggested-action', _checkout),
            ('New Branch',        None,               _new_branch),
            ('Delete',            'destructive-action', _delete),
            (None, None, None),  # separator
            ('Pull',              None,               _pull),
            ('Push',              None,               _push),
            ('Push (upstream)',   None,               _push_upstream),
            (None, None, None),
            ('Fetch All',         None,               _fetch_all),
            ('Stash',             None,               _stash),
        ]
        for label, style, cb in _btn_defs:
            if label is None:
                sep_btn = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
                sep_btn.set_margin_start(4)
                sep_btn.set_margin_end(4)
                act.pack_start(sep_btn, False, False, 0)
            else:
                btn = Gtk.Button(label=label)
                if style:
                    btn.get_style_context().add_class(style)
                btn.connect('clicked', cb)
                act.pack_start(btn, False, False, 0)

        # Auto-load if repo already set
        def _auto_load():
            if self._repo_path:
                repo_bar.set_path(self._repo_path)
                _on_load(self._repo_path)
        self.stack.connect('notify::visible-child-name',
                           lambda s, _: _auto_load() if s.get_visible_child_name() == 'branches' and _state['repo'] is None else None)

        return outer

    # ══════════════════════════════════════════════════════════════════════════
    # Page: Remotes
    # ══════════════════════════════════════════════════════════════════════════
    def _build_remote_page(self) -> 'Gtk.Widget':
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        _state: Dict = {'repo': None}

        def _on_load(rd: str):
            _state['repo'] = rd
            self._repo_path = rd
            _refresh()
            self.log(f'Loaded remotes for {rd}', 'info')

        repo_bar = _RepoBar(self._win, _on_load)
        outer.pack_start(repo_bar, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        outer.pack_start(scroll, True, True, 0)

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        inner.set_margin_start(18)
        inner.set_margin_end(18)
        inner.set_margin_top(10)
        inner.set_margin_bottom(10)
        scroll.add(inner)

        # Toolbar
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        inner.pack_start(toolbar, False, False, 0)
        lbl = Gtk.Label()
        lbl.set_markup('<b>Remotes</b>')
        lbl.set_xalign(0.0)
        lbl.set_hexpand(True)
        toolbar.pack_start(lbl, True, True, 0)
        btn_ref = Gtk.Button(label='↺ Refresh')
        btn_ref.connect('clicked', lambda _: _refresh())
        toolbar.pack_start(btn_ref, False, False, 0)

        # TreeView — name | url | type | color
        store = Gtk.ListStore(str, str, str, str)
        tree = Gtk.TreeView(model=store)
        tree.set_headers_visible(True)
        tree.get_selection().set_mode(Gtk.SelectionMode.SINGLE)

        for col_idx, (title, col_w) in enumerate(
                [('Remote', 100), ('URL', 380), ('Direction', 80)]):
            renderer = Gtk.CellRendererText()
            renderer.set_property('ellipsize', Pango.EllipsizeMode.MIDDLE)
            col = Gtk.TreeViewColumn(title, renderer, text=col_idx, foreground=3)
            col.set_min_width(col_w)
            col.set_resizable(True)
            tree.append_column(col)

        inner.pack_start(tree, True, True, 0)

        def _refresh():
            rd = _state['repo']
            if not rd: return
            store.clear()
            seen = set()
            r = _git(rd, 'remote', '-v')
            for line in r['stdout'].splitlines():
                parts = line.split()
                if len(parts) < 3: continue
                name, url, kind = parts[0], parts[1], parts[2].strip('()')
                key = (name, url, kind)
                if key in seen: continue
                seen.add(key)
                color = C_GREEN if (url.startswith('git@') or url.startswith('ssh://')) \
                        else (C_ORANGE if url.startswith('https://') else C_GRAY)
                store.append([name, url, kind, color])

        def _get_selected():
            model, it = tree.get_selection().get_selected()
            if not it: return None, None
            v = model[it]
            return v[0], v[1]  # name, url

        # SSH key section
        inner.pack_start(self._sep(), False, False, 0)
        inner.pack_start(self._section_label('SSH Key for Update'), False, False, 0)

        key_grid = Gtk.Grid(row_spacing=8, column_spacing=12)
        inner.pack_start(key_grid, False, False, 0)

        lbl_key = Gtk.Label(label='SSH Key:')
        lbl_key.set_width_chars(11)
        lbl_key.set_xalign(1.0)
        key_sel = _KeySelector(self._win)
        key_grid.attach(lbl_key, 0, 0, 1, 1)
        key_grid.attach(key_sel, 1, 0, 1, 1)

        dry_run = Gtk.CheckButton(label='Dry run (preview only)')
        dry_run.set_active(True)
        dry_run.set_margin_start(120)
        inner.pack_start(dry_run, False, False, 0)

        # Actions
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        outer.pack_start(sep, False, False, 0)
        act = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        act.set_margin_start(18)
        act.set_margin_end(18)
        act.set_margin_top(8)
        act.set_margin_bottom(8)
        outer.pack_start(act, False, False, 0)

        def _update_ssh(*_):
            rd = _state['repo']; key = key_sel.get_value()
            name, _ = _get_selected()
            if not rd: return
            if not key:
                _show_error(self._win, 'No SSH key selected.'); return
            dry = dry_run.get_active()
            def _do():
                results = ssh_config.update_repo_remotes(
                    rd, key, remotes=[name] if name else None,
                    dry_run=dry, yes=not dry)
                for res in results:
                    if res.get('skipped'):
                        self.log(f"{res['remote']}: skipped — {res.get('reason')}", 'warn')
                    else:
                        pfx = '[DRY RUN] ' if dry else ''
                        self.log(f"{pfx}{res['remote']}: {res.get('original_url')}", 'dim')
                        self.log(f"  → {res.get('new_url')}  (alias={res.get('alias')})",
                                 'info' if dry else 'ok')
                        cf = res.get('config', {})
                        if cf.get('written'):
                            self.log(f"  ssh_config: {cf.get('config_path')}", 'info')
                        elif cf.get('would_write'):
                            self.log(f"  ssh_config would add:\n{cf['would_write'].strip()}", 'dim')
                if not dry:
                    GLib.idle_add(_refresh)
                self.set_status('Done' if not dry else 'Dry run done',
                                C_GREEN if not dry else C_BLUE)
            threading.Thread(target=_do, daemon=True).start()

        def _add_remote(*_):
            rd = _state['repo']
            if not rd: return
            name = _ask_string(self._win, 'Add Remote', 'Remote name:', 'origin')
            if not name: return
            url = _ask_string(self._win, 'Add Remote', 'Remote URL:')
            if not url: return
            def _do():
                r = _git(rd, 'remote', 'add', name, url)
                self.log(f'✔ Added {name}' if r['returncode'] == 0
                         else r['stderr'], 'ok' if r['returncode'] == 0 else 'err')
                GLib.idle_add(_refresh)
            threading.Thread(target=_do, daemon=True).start()

        def _remove_remote(*_):
            name, _ = _get_selected(); rd = _state['repo']
            if not name or not rd: return
            if not _ask_yes_no(self._win, f'Remove remote "{name}"?'): return
            def _do():
                r = _git(rd, 'remote', 'remove', name)
                self.log(f'✔ Removed {name}' if r['returncode'] == 0
                         else r['stderr'], 'ok' if r['returncode'] == 0 else 'err')
                GLib.idle_add(_refresh)
            threading.Thread(target=_do, daemon=True).start()

        def _rename(*_):
            name, _ = _get_selected(); rd = _state['repo']
            if not name or not rd: return
            new = _ask_string(self._win, 'Rename Remote', 'New name:', name)
            if not new or new == name: return
            def _do():
                r = _git(rd, 'remote', 'rename', name, new)
                self.log(f'✔ Renamed {name} → {new}' if r['returncode'] == 0
                         else r['stderr'], 'ok' if r['returncode'] == 0 else 'err')
                GLib.idle_add(_refresh)
            threading.Thread(target=_do, daemon=True).start()

        def _set_url(*_):
            name, old_url = _get_selected(); rd = _state['repo']
            if not name or not rd: return
            new_url = _ask_string(self._win, f'Set URL — {name}', 'New URL:', old_url or '')
            if not new_url or new_url == old_url: return
            def _do():
                r = _git(rd, 'remote', 'set-url', name, new_url)
                self.log(f'✔ {name} → {new_url}' if r['returncode'] == 0
                         else r['stderr'], 'ok' if r['returncode'] == 0 else 'err')
                GLib.idle_add(_refresh)
            threading.Thread(target=_do, daemon=True).start()

        def _fetch_sel(*_):
            name, _ = _get_selected(); rd = _state['repo']
            if not name or not rd: return
            def _do():
                self.log(f'git fetch {name} --prune…', 'info')
                r = _git(rd, 'fetch', name, '--prune')
                self.log(r['stdout'].strip() or r['stderr'].strip() or f'✔ Fetched {name}',
                         'ok' if r['returncode'] == 0 else 'warn')
            threading.Thread(target=_do, daemon=True).start()

        def _fetch_all(*_):
            rd = _state['repo']
            if not rd: return
            def _do():
                self.log('git fetch --all --prune…', 'info')
                r = _git(rd, 'fetch', '--all', '--prune')
                self.log(r['stdout'].strip() or r['stderr'].strip() or '✔ Fetched all',
                         'ok' if r['returncode'] == 0 else 'warn')
            threading.Thread(target=_do, daemon=True).start()

        _btn_defs = [
            ('Update to SSH',    'suggested-action',   _update_ssh),
            ('Add Remote',       None,                 _add_remote),
            ('Remove',           'destructive-action', _remove_remote),
            ('Rename',           None,                 _rename),
            ('Set URL',          None,                 _set_url),
            (None, None, None),
            ('Fetch Selected',   None,                 _fetch_sel),
            ('Fetch All',        None,                 _fetch_all),
        ]
        for label, style, cb in _btn_defs:
            if label is None:
                s = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
                s.set_margin_start(4); s.set_margin_end(4)
                act.pack_start(s, False, False, 0)
            else:
                btn = Gtk.Button(label=label)
                if style:
                    btn.get_style_context().add_class(style)
                btn.connect('clicked', cb)
                act.pack_start(btn, False, False, 0)

        return outer

    # ══════════════════════════════════════════════════════════════════════════
    # Page: SSH Keys
    # ══════════════════════════════════════════════════════════════════════════
    def _build_keys_page(self) -> 'Gtk.Widget':
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        outer.pack_start(scroll, True, True, 0)

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        inner.set_margin_start(18)
        inner.set_margin_end(18)
        inner.set_margin_top(14)
        inner.set_margin_bottom(10)
        scroll.add(inner)

        # Header
        hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        inner.pack_start(hdr, False, False, 0)
        lbl = Gtk.Label()
        lbl.set_markup('<b>Discovered SSH Keys</b>')
        lbl.set_xalign(0.0)
        lbl.set_hexpand(True)
        hdr.pack_start(lbl, True, True, 0)
        btn_ref = Gtk.Button(label='↺ Refresh')
        btn_ref.connect('clicked', lambda _: _refresh())
        hdr.pack_start(btn_ref, False, False, 0)

        # Keys TreeView — path | type | perms | dup | fingerprint | color
        store = Gtk.ListStore(str, str, str, str, str, str)
        tree = Gtk.TreeView(model=store)
        tree.set_headers_visible(True)
        tree.get_selection().set_mode(Gtk.SelectionMode.SINGLE)

        for col_idx, (title, col_w) in enumerate(
                [('Path', 260), ('Type', 80), ('Perms', 65), ('Dup', 40), ('Fingerprint (SHA-256)', 280)]):
            renderer = Gtk.CellRendererText()
            renderer.set_property('ellipsize', Pango.EllipsizeMode.MIDDLE)
            col = Gtk.TreeViewColumn(title, renderer, text=col_idx, foreground=5)
            col.set_min_width(col_w)
            col.set_resizable(True)
            tree.append_column(col)

        inner.pack_start(tree, True, True, 0)

        # Agent section
        inner.pack_start(self._sep(), False, False, 0)
        inner.pack_start(self._section_label('ssh-agent Loaded Keys'), False, False, 0)
        agent_lbl = Gtk.Label()
        agent_lbl.set_xalign(0.0)
        agent_lbl.set_line_wrap(True)
        agent_lbl.set_markup(_markup('(unknown)', C_GRAY))
        inner.pack_start(agent_lbl, False, False, 0)

        def _refresh():
            store.clear()
            keys = ssh_keys.discover_keys()
            for k in keys:
                perms = '✔' if k.get('permissions_ok') else '✖'
                dup   = '●' if k.get('duplicate') else ''
                fp    = k.get('fingerprint') or '—'
                color = C_ORANGE if k.get('duplicate') else \
                        (C_RED if not k.get('permissions_ok') else C_GREEN)
                store.append([k.get('path', ''), k.get('type', '—'),
                               perms, dup, fp, color])
            # Agent
            import subprocess
            ar = subprocess.run(['ssh-add', '-l'], capture_output=True, text=True)
            lines = ar.stdout.strip() or ar.stderr.strip() or '(no keys loaded)'
            GLib.idle_add(agent_lbl.set_markup,
                          _markup(lines, C_GREEN if ar.returncode == 0 else C_GRAY))
            self.log(f'Found {len(keys)} key(s)', 'info')
            self.set_status(f'{len(keys)} key(s) found', C_BLUE)

        def _sel_path() -> Optional[str]:
            model, it = tree.get_selection().get_selected()
            if not it:
                _show_error(self._win, 'No key selected.'); return None
            return model.get_value(it, 0)

        # Actions
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        outer.pack_start(sep, False, False, 0)
        act = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        act.set_margin_start(18)
        act.set_margin_end(18)
        act.set_margin_top(8)
        act.set_margin_bottom(8)
        outer.pack_start(act, False, False, 0)

        def _fix_sel(*_):
            path = _sel_path()
            if not path: return
            dry = _ask_yes_no(self._win, f'Fix permissions on:\n{path}', 'Dry run first?')
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

        def _fix_all(*_):
            def _do():
                keys = ssh_keys.discover_keys()
                fixed = 0
                for k in keys:
                    if not k.get('permissions_ok') and k.get('path'):
                        r = ssh_keys.fix_permissions_for_file(k['path'], dry_run=False)
                        if r.get('changed'):
                            self.log(f'✔ Fixed {k["path"]}', 'ok')
                            fixed += 1
                self.log(f'Fixed {fixed} key(s)', 'info' if fixed else 'dim')
                GLib.idle_add(_refresh)
            threading.Thread(target=_do, daemon=True).start()

        def _add_agent(*_):
            path = _sel_path()
            if not path: return
            def _do():
                r = ssh_keys.add_to_agent(path)
                self.log(f'✔ Added to agent' if r.get('added')
                         else f'✖ {r.get("reason") or r.get("stderr") or "Failed"}',
                         'ok' if r.get('added') else 'err')
                GLib.idle_add(_refresh)
            threading.Thread(target=_do, daemon=True).start()

        def _remove_agent(*_):
            path = _sel_path()
            if not path: return
            import subprocess
            r = subprocess.run(['ssh-add', '-d', path], capture_output=True, text=True)
            self.log(f'✔ Removed from agent' if r.returncode == 0
                     else r.stderr.strip(), 'ok' if r.returncode == 0 else 'err')
            _refresh()

        for label, style, cb in [
            ('Fix Selected',       None,                 _fix_sel),
            ('Fix All',            None,                 _fix_all),
            (None, None, None),
            ('Add to Agent',       'suggested-action',   _add_agent),
            ('Remove from Agent',  'destructive-action', _remove_agent),
        ]:
            if label is None:
                s = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
                s.set_margin_start(4); s.set_margin_end(4)
                act.pack_start(s, False, False, 0)
            else:
                btn = Gtk.Button(label=label)
                if style:
                    btn.get_style_context().add_class(style)
                btn.connect('clicked', cb)
                act.pack_start(btn, False, False, 0)

        # Load on page visit
        self.stack.connect('notify::visible-child-name',
                           lambda s, _: GLib.idle_add(_refresh)
                           if s.get_visible_child_name() == 'keys' else None)
        GLib.idle_add(_refresh)
        return outer

    # ── Window icon ───────────────────────────────────────────────────────────
    def _set_icon(self):
        here = Path(__file__).parent.parent
        candidates = [
            here / 'assets' / 'git-ssh-helper.png',
            Path.home() / '.local' / 'share' / 'icons' / 'hicolor' / '48x48' / 'apps' / 'git-ssh-helper.png',
            Path('/usr/share/icons/hicolor/48x48/apps/git-ssh-helper.png'),
        ]
        for p in candidates:
            if p.exists():
                self._win.set_icon_from_file(str(p))
                return
        # Try SVG
        svg = here / 'assets' / 'git-ssh-helper.svg'
        if svg.exists():
            self._win.set_icon_from_file(str(svg))


# ══════════════════════════════════════════════════════════════════════════════
# Tkinter fallback (minimal)
# ══════════════════════════════════════════════════════════════════════════════
def _run_tk_fallback() -> int:
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception:
        print('[git-ssh-helper] Neither GTK nor Tkinter is available.', file=sys.stderr)
        return 1

    root = tk.Tk()
    root.title('SSH Git Manager')
    root.geometry('600x400')
    root.configure(bg='#1e1e2e')
    tk.Label(root, text='git-ssh-helper',
             bg='#1e1e2e', fg='#cba6f7', font=('sans-serif', 16, 'bold')).pack(pady=40)
    tk.Label(root, text='GTK 3 is not available.\nInstall python3-gi for the full GUI.',
             bg='#1e1e2e', fg='#888888', font=('sans-serif', 11)).pack()
    tk.Label(root, text='Run: sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0',
             bg='#1e1e2e', fg='#fab387', font=('monospace', 10)).pack(pady=20)
    root.mainloop()
    return 0


# ══════════════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════════════
def run_gui() -> int:
    # If we're inside a VSCode/snap environment, the snap sets GTK_PATH and
    # GTK_EXE_PREFIX to its own snap dirs, causing GTK to load snap-internal
    # modules that conflict with the system libpthread.  Re-exec this process
    # with those vars cleared so GTK uses the system module path.
    _SNAP_GTK_VARS = (
        'GTK_PATH', 'GTK_EXE_PREFIX', 'GTK_IM_MODULE_FILE',
        'GDK_PIXBUF_MODULEDIR', 'GDK_PIXBUF_MODULE_FILE',
        'GIO_MODULE_DIR', 'GSETTINGS_SCHEMA_DIR',
    )
    if any(os.environ.get(v, '').startswith('/snap/') or
           '/snap/code' in os.environ.get(v, '')
           for v in _SNAP_GTK_VARS):
        import subprocess
        clean_env = {k: v for k, v in os.environ.items()
                     if k not in _SNAP_GTK_VARS}
        result = subprocess.run([sys.executable] + sys.argv, env=clean_env)
        return result.returncode

    if not _GTK_OK:
        return _run_tk_fallback()
    app = _GTKApp()
    Gtk.main()
    return 0


if __name__ == '__main__':
    sys.exit(run_gui())
