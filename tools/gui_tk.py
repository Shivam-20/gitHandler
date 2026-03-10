"""tools.gui_tk

A Tkinter GUI for git-ssh-helper with a modern dark theme. Provides fields to
enter a repository URL, pick or refresh SSH private keys discovered by
tools.ssh_keys, choose an optional clone directory, and run git clone using
GIT_SSH_COMMAND built by tools.core.build_ssh_command(). Post-clone actions
(list branches, checkout) are exposed as buttons.

Falls back to the CLI TUI if Tkinter is not available or unusable.
"""
from __future__ import annotations

import os
import shlex
import sys
import threading

try:
    from tools import ssh_keys, core, clone_actions
except Exception:
    import tools.ssh_keys as ssh_keys
    import tools.core as core
    import tools.clone_actions as clone_actions

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, simpledialog
except Exception:
    tk = None

# ── colour palette (Catppuccin-Mocha-inspired) ────────────────────────────────
BG       = '#1e1e2e'   # base
BG2      = '#181825'   # mantle  (sidebar / log bg)
BG3      = '#313244'   # surface0 (input fields)
BORDER   = '#45475a'   # surface1
FG       = '#cdd6f4'   # text
FG_DIM   = '#6c7086'   # overlay0
ACCENT   = '#89b4fa'   # blue
SUCCESS  = '#a6e3a1'   # green
DANGER   = '#f38ba8'   # red
WARN     = '#fab387'   # peach
HEADER   = '#cba6f7'   # mauve

FONT_UI    = ('Inter', 10)
FONT_MONO  = ('JetBrains Mono', 9)
FONT_TITLE = ('Inter', 13, 'bold')
FONT_LABEL = ('Inter', 10)

# Fallback to common system fonts
_SANS  = ('Inter', 'Segoe UI', 'DejaVu Sans', 'sans-serif')
_MONO  = ('JetBrains Mono', 'Fira Mono', 'DejaVu Sans Mono', 'monospace')


def _first_font(candidates: tuple, size: int, *modifiers) -> tuple:
    import tkinter.font as tkfont
    available = set(tkfont.families())
    for name in candidates:
        if name in available:
            return (name, size, *modifiers) if modifiers else (name, size)
    return (candidates[-1], size, *modifiers) if modifiers else (candidates[-1], size)


# ── helpers ───────────────────────────────────────────────────────────────────

def _repo_dir_from_url(url: str) -> str:
    s = url.rstrip('/')
    if ':' in s and not s.lower().startswith(('http://', 'https://', 'ssh://', 'git://', 'git+ssh://')):
        part = s.split(':', 1)[1]
        name = part.rstrip('/').split('/')[-1]
    else:
        try:
            from urllib.parse import urlparse
            p = urlparse(s)
            name = p.path.rstrip('/').split('/')[-1]
        except Exception:
            name = s.split('/')[-1]
    if name.endswith('.git'):
        name = name[:-4]
    return name


def _get_key_paths() -> list:
    keys = ssh_keys.discover_keys()
    return [k.get('path') for k in keys if k.get('path')]


# ── theme setup ───────────────────────────────────────────────────────────────

def _apply_theme(root: tk.Tk) -> None:
    root.configure(bg=BG)
    style = ttk.Style(root)
    style.theme_use('clam')

    # Global frame / label backgrounds
    style.configure('.',
        background=BG, foreground=FG,
        font=_first_font(_SANS, 10),
        bordercolor=BORDER, focuscolor=ACCENT,
        troughcolor=BG2, selectbackground=ACCENT, selectforeground=BG,
    )

    # Frames
    style.configure('TFrame', background=BG)
    style.configure('Card.TFrame', background=BG2, relief='flat')

    # Labels
    style.configure('TLabel', background=BG, foreground=FG,
                    font=_first_font(_SANS, 10))
    style.configure('Dim.TLabel', background=BG, foreground=FG_DIM,
                    font=_first_font(_SANS, 9))
    style.configure('Title.TLabel', background=BG, foreground=HEADER,
                    font=_first_font(_SANS, 13, 'bold'))
    style.configure('Status.TLabel', background=BG2, foreground=FG_DIM,
                    font=_first_font(_SANS, 9), padding=(8, 4))

    # Entry
    style.configure('TEntry',
        fieldbackground=BG3, foreground=FG, insertcolor=FG,
        bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
        padding=5,
    )
    style.map('TEntry', bordercolor=[('focus', ACCENT)])

    # Combobox
    style.configure('TCombobox',
        fieldbackground=BG3, foreground=FG, background=BG3,
        selectbackground=ACCENT, selectforeground=BG,
        arrowcolor=FG_DIM, bordercolor=BORDER,
        padding=5,
    )
    style.map('TCombobox',
        fieldbackground=[('readonly', BG3)],
        bordercolor=[('focus', ACCENT)],
    )

    # Buttons — default (secondary)
    style.configure('TButton',
        background=BG3, foreground=FG,
        bordercolor=BORDER, lightcolor=BG3, darkcolor=BG3,
        focuscolor=ACCENT, padding=(10, 6), relief='flat',
        font=_first_font(_SANS, 10),
    )
    style.map('TButton',
        background=[('active', BORDER), ('disabled', BG2)],
        foreground=[('disabled', FG_DIM)],
        bordercolor=[('active', ACCENT)],
    )

    # Primary button (Clone)
    style.configure('Primary.TButton',
        background=ACCENT, foreground=BG,
        bordercolor=ACCENT, lightcolor=ACCENT, darkcolor=ACCENT,
        focuscolor=ACCENT, padding=(14, 7), relief='flat',
        font=_first_font(_SANS, 10, 'bold'),
    )
    style.map('Primary.TButton',
        background=[('active', '#74c7ec'), ('disabled', BG3)],
        foreground=[('disabled', FG_DIM)],
    )

    # Danger button
    style.configure('Danger.TButton',
        background=BG3, foreground=DANGER,
        bordercolor=BORDER, padding=(10, 6), relief='flat',
    )
    style.map('Danger.TButton',
        background=[('active', BORDER)],
    )

    # Scrollbar
    style.configure('TScrollbar',
        background=BG3, troughcolor=BG2,
        arrowcolor=FG_DIM, bordercolor=BG2,
    )
    style.map('TScrollbar', background=[('active', BORDER)])

    # Separator
    style.configure('TSeparator', background=BORDER)

    # Notebook (if used)
    style.configure('TNotebook', background=BG2, bordercolor=BORDER)
    style.configure('TNotebook.Tab',
        background=BG3, foreground=FG_DIM, padding=(12, 5),
    )
    style.map('TNotebook.Tab',
        background=[('selected', BG)],
        foreground=[('selected', FG)],
    )


# ── main GUI ──────────────────────────────────────────────────────────────────

def run_gui() -> int:
    """Launch the Tkinter GUI. If unavailable, fall back to the CLI TUI."""
    if tk is None:
        try:
            from tools import ui_tui
        except Exception:
            import tools.ui_tui as ui_tui
        return ui_tui.run_cli_flow()

    root = tk.Tk()
    root.title('git-ssh-helper')
    root.geometry('960x660')
    root.minsize(780, 500)

    _apply_theme(root)

    # ── Header ────────────────────────────────────────────────────────────────
    header = tk.Frame(root, bg=BG2, pady=0)
    header.pack(side='top', fill='x')

    # left accent bar
    tk.Frame(header, bg=ACCENT, width=4).pack(side='left', fill='y')

    hinner = tk.Frame(header, bg=BG2)
    hinner.pack(side='left', fill='both', expand=True, padx=16, pady=12)

    ttk.Label(hinner, text='git-ssh-helper', style='Title.TLabel',
              background=BG2).pack(side='left')
    ttk.Label(hinner, text='  —  clone repos with your SSH key',
              style='Dim.TLabel', background=BG2).pack(side='left')

    # ── Form card ─────────────────────────────────────────────────────────────
    card = tk.Frame(root, bg=BG2, pady=0)
    card.pack(side='top', fill='x', padx=16, pady=(12, 0))

    form = tk.Frame(card, bg=BG2)
    form.pack(fill='x', padx=20, pady=16)
    form.columnconfigure(1, weight=1)

    def _label(row: int, text: str) -> None:
        lbl = tk.Label(form, text=text, bg=BG2, fg=FG_DIM,
                       font=_first_font(_SANS, 9), anchor='w')
        lbl.grid(row=row * 2 - 2, column=0, columnspan=4, sticky='w',
                 padx=(2, 0), pady=(10 if row > 1 else 0, 2))

    # Row 0 – repo URL
    _label(1, 'REPOSITORY URL')
    repo_var = tk.StringVar()
    repo_entry = ttk.Entry(form, textvariable=repo_var)
    repo_entry.grid(row=1, column=0, columnspan=4, sticky='we', ipady=3)

    # Row 2 – clone dir
    _label(2, 'CLONE DIRECTORY  (optional)')
    clone_var = tk.StringVar()
    clone_entry = ttk.Entry(form, textvariable=clone_var)
    clone_entry.grid(row=3, column=0, columnspan=3, sticky='we', ipady=3, padx=(0, 6))

    def browse_clone() -> None:
        d = filedialog.askdirectory(title='Select clone directory')
        if d:
            clone_var.set(d)

    ttk.Button(form, text='Browse…', command=browse_clone).grid(
        row=3, column=3, sticky='e')

    # Row 4 – SSH key
    _label(3, 'SSH KEY')
    key_var = tk.StringVar()
    key_cb = ttk.Combobox(form, textvariable=key_var)
    key_cb.grid(row=5, column=0, columnspan=2, sticky='we', ipady=3, padx=(0, 6))

    def refresh_keys() -> None:
        try:
            vals = _get_key_paths()
            key_cb['values'] = vals
            if vals and not key_var.get():
                key_var.set(vals[0])
        except Exception as e:
            messagebox.showerror('Error', f'Failed to discover keys: {e}')

    ttk.Button(form, text='↺ Refresh', command=refresh_keys).grid(
        row=5, column=2, padx=(0, 6))

    def choose_keyfile() -> None:
        p = filedialog.askopenfilename(
            title='Select private key file',
            initialdir=os.path.expanduser('~/.ssh'))
        if p:
            key_var.set(p)

    choose_file_btn = ttk.Button(form, text='Choose file…', command=choose_keyfile)
    choose_file_btn.grid(row=5, column=3, sticky='e')

    refresh_keys()

    # ── Clone button + status bar ──────────────────────────────────────────────
    btn_bar = tk.Frame(root, bg=BG, pady=0)
    btn_bar.pack(side='top', fill='x', padx=16, pady=10)

    clone_btn = ttk.Button(btn_bar, text='  ⬇  Clone  ', style='Primary.TButton')
    clone_btn.pack(side='left')

    status_var = tk.StringVar(value='Ready')
    status_dot  = tk.Label(btn_bar, text='●', bg=BG, fg=FG_DIM,
                           font=_first_font(_SANS, 11))
    status_dot.pack(side='left', padx=(14, 4))
    status_lbl = tk.Label(btn_bar, textvariable=status_var, bg=BG, fg=FG_DIM,
                          font=_first_font(_SANS, 10))
    status_lbl.pack(side='left')

    # ── Separator ─────────────────────────────────────────────────────────────
    ttk.Separator(root, orient='horizontal').pack(fill='x', padx=16)

    # ── Log area ──────────────────────────────────────────────────────────────
    log_outer = tk.Frame(root, bg=BG)
    log_outer.pack(side='top', fill='both', expand=True, padx=16, pady=(8, 0))

    log_header = tk.Frame(log_outer, bg=BG)
    log_header.pack(fill='x')
    tk.Label(log_header, text='OUTPUT', bg=BG, fg=FG_DIM,
             font=_first_font(_SANS, 9)).pack(side='left', pady=(0, 4))

    log_frame = tk.Frame(log_outer, bg=BG2, highlightthickness=1,
                         highlightbackground=BORDER)
    log_frame.pack(fill='both', expand=True)

    mono = _first_font(_MONO, 9)
    log_text = tk.Text(
        log_frame, wrap='word', state='disabled',
        bg=BG2, fg=FG, insertbackground=FG,
        selectbackground=ACCENT, selectforeground=BG,
        font=mono, relief='flat', padx=10, pady=8,
        borderwidth=0,
    )
    log_text.pack(side='left', fill='both', expand=True)

    # Colour tags for log entries
    log_text.tag_configure('ok',   foreground=SUCCESS)
    log_text.tag_configure('err',  foreground=DANGER)
    log_text.tag_configure('info', foreground=ACCENT)
    log_text.tag_configure('warn', foreground=WARN)

    sb = ttk.Scrollbar(log_frame, orient='vertical', command=log_text.yview)
    sb.pack(side='right', fill='y')
    log_text['yscrollcommand'] = sb.set

    def _append_log(msg: str, tag: str = '') -> None:
        log_text.configure(state='normal')
        log_text.insert('end', msg + '\n', tag or ())
        log_text.see('end')
        log_text.configure(state='disabled')

    def schedule_append(msg: str, tag: str = '') -> None:
        root.after(0, _append_log, msg, tag)

    # ── Post-clone action bar ─────────────────────────────────────────────────
    ttk.Separator(root, orient='horizontal').pack(fill='x', padx=16, pady=(8, 0))

    actions_frame = tk.Frame(root, bg=BG, pady=8)
    actions_frame.pack(side='top', fill='x', padx=16)

    tk.Label(actions_frame, text='POST-CLONE:', bg=BG, fg=FG_DIM,
             font=_first_font(_SANS, 9)).pack(side='left', padx=(0, 10))

    repo_dir_holder: dict = {'path': None}

    def _list_branches_thread() -> None:
        rd = repo_dir_holder.get('path')
        if not rd:
            schedule_append('No repo cloned yet.', 'warn')
            return
        schedule_append('Listing branches…', 'info')
        branches = clone_actions.list_branches(rd)
        for b in branches:
            schedule_append(f'  {b}')

    ttk.Button(actions_frame, text='List branches',
               command=lambda: threading.Thread(
                   target=_list_branches_thread, daemon=True).start()
               ).pack(side='left', padx=(0, 6))

    def _checkout_branch_prompt() -> None:
        rd = repo_dir_holder.get('path')
        if not rd:
            messagebox.showerror('Error', 'No repo cloned yet')
            return
        br = simpledialog.askstring('Checkout branch', 'Branch name:',
                                    parent=root)
        if not br:
            return
        def _do_checkout() -> None:
            schedule_append(f'Checking out {br}…', 'info')
            r = clone_actions.checkout_branch(rd, br)
            if r.get('returncode') == 0:
                schedule_append(f'✔ Checked out {br}', 'ok')
            else:
                schedule_append(r.get('stderr') or r.get('stdout') or '', 'err')
        threading.Thread(target=_do_checkout, daemon=True).start()

    ttk.Button(actions_frame, text='Checkout branch',
               command=_checkout_branch_prompt).pack(side='left', padx=(0, 6))

    ttk.Button(
        actions_frame, text='Print shell cmd',
        command=lambda: schedule_append(
            f'cd {repo_dir_holder.get("path") or "<repo>"} && $SHELL', 'info')
    ).pack(side='left')

    # ── Clone logic ───────────────────────────────────────────────────────────
    def _set_status(msg: str, color: str = FG_DIM) -> None:
        status_var.set(msg)
        status_dot.configure(fg=color)
        status_lbl.configure(fg=color)

    def _do_clone(repo: str, clone_dir: str | None, key_path: str) -> None:
        schedule_append(f'Using key: {key_path}', 'info')
        try:
            ssh_cmd_list = core.build_ssh_command(key_path)
        except Exception as e:
            schedule_append(f'✖ Failed to build SSH command: {e}', 'err')
            root.after(0, on_clone_done, False)
            return
        ssh_cmd_str = ' '.join(shlex.quote(p) for p in ssh_cmd_list)
        schedule_append(f"Running: git clone {repo} → {clone_dir or '(auto)'}", 'info')
        args = ['clone', repo]
        if clone_dir:
            args.append(clone_dir)
        res = core.run_git(args, env_overrides={'GIT_SSH_COMMAND': ssh_cmd_str})
        if res.get('returncode') != 0:
            schedule_append('✖ git clone failed:', 'err')
            if res.get('stderr'):
                schedule_append(res['stderr'], 'err')
            elif res.get('stdout'):
                schedule_append(res['stdout'], 'err')
            root.after(0, on_clone_done, False)
            return
        rd = clone_dir if clone_dir else os.path.join(
            os.getcwd(), _repo_dir_from_url(repo))
        repo_dir_holder['path'] = rd
        schedule_append(f'✔ Cloned into {rd}', 'ok')
        root.after(0, on_clone_done, True)

    def on_clone_done(success: bool) -> None:
        clone_btn['state'] = 'normal'
        choose_file_btn['state'] = 'normal'
        if success:
            _set_status('Clone succeeded', SUCCESS)
        else:
            _set_status('Clone failed', DANGER)

    def on_clone_clicked() -> None:
        repo = repo_var.get().strip()
        if not repo:
            messagebox.showerror('Error', 'Repository URL is required')
            return
        key_path = key_var.get().strip()
        if not key_path:
            messagebox.showerror('Error', 'SSH private key is required')
            return
        clone_btn['state'] = 'disabled'
        choose_file_btn['state'] = 'disabled'
        _set_status('Cloning…', WARN)
        threading.Thread(
            target=_do_clone,
            args=(repo, clone_var.get().strip() or None, key_path),
            daemon=True,
        ).start()

    clone_btn.config(command=on_clone_clicked)

    root.protocol('WM_DELETE_WINDOW', root.quit)
    root.mainloop()
    return 0


if __name__ == '__main__':
    rc = run_gui()
    sys.exit(0 if rc is None else int(rc))
