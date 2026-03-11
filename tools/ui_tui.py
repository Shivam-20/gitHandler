"""tools.ui_tui

A minimal terminal UI (TUI) wrapper around existing tools to help the user
select an SSH private key and clone a repository using GIT_SSH_COMMAND.

This module prefers a curses-based UI when available and falls back to a
simple CLI interactive flow when curses cannot be used. It intentionally
uses only the Python standard library and the existing tools.* helpers.

Functions:
- run_tui() -> int|None : run the interactive flow (returns 0 on success)

Notes:
- This module never writes private keys to disk.
"""
from __future__ import annotations

import os
import shlex
import sys
import traceback
from typing import List, Dict, Optional

# Import the project helpers (follow the pattern used elsewhere in the repo)
try:
    from tools import ssh_keys, core, clone_actions, ssh_config
except Exception:
    import tools.ssh_keys as ssh_keys
    import tools.core as core
    import tools.clone_actions as clone_actions
    import tools.ssh_config as ssh_config


def _repo_dir_from_url(url: str) -> str:
    s = url.rstrip('/')
    # scp-like (git@host:owner/repo.git)
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


def choose_key_interactively(keys: List[Dict]) -> Optional[str]:
    """Simple CLI number-based selection of discovered keys or custom path."""
    if keys:
        print("Discovered SSH keys:")
        for i, k in enumerate(keys, start=1):
            dup = '[DUP]' if k.get('duplicate') else ''
            fp = k.get('fingerprint') or '<no-fp>'
            print(f"{i}) {k.get('path')} {dup}  type={k.get('type')} fp={fp} perms_ok={k.get('permissions_ok')} reason={k.get('reason')}")
    else:
        print("No candidate private keys found under ~/.ssh")

    print("0) Enter custom path to private key")
    while True:
        try:
            choice = input("Select key number (or 0 to enter custom path): ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if not choice:
            continue
        try:
            idx = int(choice)
        except ValueError:
            print("Please enter a number")
            continue
        if idx == 0:
            try:
                path = input("Enter path to private key: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return None
            if not path:
                print("Empty path, try again")
                continue
            return os.path.expanduser(path)
        if 1 <= idx <= len(keys):
            return os.path.expanduser(keys[idx - 1].get('path'))
        print("Invalid selection")


def _clone_with_key(repo: str, clone_dir: Optional[str], selected_key: str) -> Optional[str]:
    """Build SSH command and perform git clone. Returns repo_dir on success or None on failure."""
    try:
        ssh_cmd_list = core.build_ssh_command(selected_key)
    except Exception as e:
        print(f'Failed to build SSH command from key "{selected_key}": {e}', file=sys.stderr)
        return None

    ssh_cmd_str = ' '.join(shlex.quote(p) for p in ssh_cmd_list)

    clone_args: List[str] = ['clone', repo]
    if clone_dir:
        clone_args.append(clone_dir)

    print(f"Cloning {repo}...")
    res = core.run_git(clone_args, env_overrides={'GIT_SSH_COMMAND': ssh_cmd_str})
    if res.get('returncode') != 0:
        print('git clone failed', file=sys.stderr)
        if res.get('stderr'):
            print(res.get('stderr'), file=sys.stderr)
        elif res.get('stdout'):
            print(res.get('stdout'), file=sys.stderr)
        return None

    if clone_dir:
        repo_dir = os.path.expanduser(clone_dir)
    else:
        repo_dir = os.path.join(os.getcwd(), _repo_dir_from_url(repo))

    print(f"Cloned into {repo_dir}")
    return repo_dir


def _post_clone_cli(repo_dir: str, selected_key: Optional[str] = None) -> None:
    """Simple CLI interaction loop for post-clone actions."""
    while True:
        print('\nPost-clone actions:')
        print('1) List branches')
        print('2) Checkout branch')
        print('3) Print shell command to open a shell in the repo')
        print('4) Run custom git command')
        print('5) Update remote SSH URL to use selected key')
        print('0) Exit')
        try:
            choice = input('Select action: ').strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if choice == '1':
            branches = clone_actions.list_branches(repo_dir)
            if branches and len(branches) == 1 and branches[0].startswith('ERROR:'):
                print(branches[0])
            else:
                for b in branches:
                    print(b)
        elif choice == '2':
            branch = input('Enter branch name to checkout: ').strip()
            if not branch:
                print('No branch entered')
                continue
            r = clone_actions.checkout_branch(repo_dir, branch)
            if r.get('returncode') == 0:
                print(f'Checked out {branch}')
            else:
                print(r.get('stderr') or r.get('stdout') or '')
        elif choice == '3':
            print(f'To open a shell: cd {repo_dir} && $SHELL')
        elif choice == '4':
            cmd = input('Enter git command (e.g. status or log --oneline): ').strip()
            if not cmd:
                continue
            try:
                parsed = shlex.split(cmd)
            except Exception:
                print('Failed to parse command')
                continue
            if parsed and parsed[0] == 'git':
                parsed = parsed[1:]
            if not parsed:
                print('No git subcommand provided')
                continue
            r = clone_actions.run_custom(repo_dir, parsed)
            if r.get('stdout'):
                print(r['stdout'])
            else:
                print(r.get('stderr') or '')
        elif choice == '5':
            if not selected_key:
                print('No key available to update remotes with')
                continue
            print('Showing planned changes (dry-run)')
            res = ssh_config.update_repo_remotes(repo_dir, selected_key, remotes=None, dry_run=True, backup_dir=None, yes=False)
            for r in res:
                if r.get('skipped'):
                    print(f"{r.get('remote')}: skipped - {r.get('reason')}")
                else:
                    print(f"{r.get('remote')}: {r.get('original_url')} -> {r.get('new_url')}")
            ans = input('Apply these changes? (y/N): ').strip().lower()
            if ans == 'y':
                applied = ssh_config.update_repo_remotes(repo_dir, selected_key, remotes=None, dry_run=False, backup_dir=None, yes=True)
                for a in applied:
                    if a.get('skipped'):
                        print(f"{a.get('remote')}: skipped - {a.get('reason')}")
                    else:
                        print(f"{a.get('remote')}: updated -> {a.get('new_url')}")
            else:
                print('Aborted')
            continue
        elif choice == '0':
            break
        else:
            print('Invalid selection')


def run_cli_flow() -> int:
    """Fallback interactive flow when curses isn't available or fails."""
    try:
        repo = input('Repository URL to clone: ').strip()
    except (EOFError, KeyboardInterrupt):
        print('\nCancelled')
        return 1
    if not repo:
        print('No repository URL provided')
        return 2

    clone_dir = ''
    try:
        clone_dir = input('Clone directory (optional): ').strip()
    except (EOFError, KeyboardInterrupt):
        clone_dir = ''

    keys = ssh_keys.discover_keys()
    selected_key = choose_key_interactively(keys)
    if not selected_key:
        print('No key selected, exiting', file=sys.stderr)
        return 3

    repo_dir = _clone_with_key(repo, clone_dir or None, selected_key)
    if not repo_dir:
        return 4

    _post_clone_cli(repo_dir, selected_key)
    return 0


def _curses_main(stdscr) -> int:
    """A minimal curses-based UI. If anything goes wrong we bubble up an exception
    and let the caller fall back to CLI mode.
    """
    import curses

    curses.curs_set(1)
    stdscr.clear()
    stdscr.refresh()

    maxy, maxx = stdscr.getmaxyx()
    title = 'git-ssh-helper TUI'
    try:
        stdscr.addstr(0, max(0, (maxx - len(title)) // 2), title, curses.A_BOLD)
    except Exception:
        # If terminal too small, ignore styling errors
        stdscr.addstr(0, 0, title)

    curses.echo()
    stdscr.addstr(2, 2, 'Repository URL: ')
    stdscr.refresh()
    repo = stdscr.getstr(2, 18, 1024).decode('utf-8').strip()
    if not repo:
        curses.noecho()
        print('\nNo repository URL provided')
        return 2

    stdscr.addstr(3, 2, 'Clone directory (optional): ')
    stdscr.refresh()
    clone_dir = stdscr.getstr(3, 27, 512).decode('utf-8').strip()
    curses.noecho()

    stdscr.addstr(5, 2, 'Discovering SSH keys...')
    stdscr.refresh()
    keys = ssh_keys.discover_keys()

    stdscr.clear()
    stdscr.addstr(0, 0, 'Select SSH key (enter number). Keys marked [OK] have acceptable perms.')
    y = 2
    for i, k in enumerate(keys, start=1):
        mark = '[OK]' if k.get('permissions_ok') else '[BAD]'
        line = f"{i}) {k.get('path')} {mark} {k.get('reason')}"
        # Truncate long lines to fit
        try:
            stdscr.addstr(y, 2, line[: max(0, maxx - 4)])
        except Exception:
            pass
        y += 1
        if y >= maxy - 4:
            break
    try:
        stdscr.addstr(y, 2, '0) Enter custom path')
    except Exception:
        pass
    y += 2
    stdscr.addstr(y, 2, 'Selection: ')
    curses.echo()
    sel = stdscr.getstr(y, 13, 8).decode('utf-8').strip()
    curses.noecho()

    selected_key: Optional[str] = None
    try:
        idx = int(sel) if sel else -1
    except Exception:
        idx = -1
    if idx == 0:
        stdscr.addstr(y + 2, 2, 'Enter path to private key: ')
        curses.echo()
        p = stdscr.getstr(y + 2, 28, 512).decode('utf-8').strip()
        curses.noecho()
        if not p:
            stdscr.addstr(y + 4, 2, 'Empty path, cancelling')
            stdscr.refresh()
            return 3
        selected_key = os.path.expanduser(p)
    elif 1 <= idx <= len(keys):
        selected_key = os.path.expanduser(keys[idx - 1].get('path'))
    else:
        stdscr.addstr(y + 2, 2, 'Invalid selection')
        stdscr.refresh()
        return 3

    stdscr.addstr(y + 4, 2, f'Using key: {selected_key}')
    stdscr.addstr(y + 5, 2, 'Cloning...')
    stdscr.refresh()

    repo_dir = _clone_with_key(repo, clone_dir or None, selected_key)
    if not repo_dir:
        stdscr.addstr(y + 6, 2, 'Clone failed. See output.')
        stdscr.refresh()
        return 4

    # Show a very simple action loop
    while True:
        stdscr.clear()
        stdscr.addstr(0, 0, f'Cloned into: {repo_dir}')
        stdscr.addstr(2, 0, 'Post-clone actions:')
        stdscr.addstr(3, 2, '1) List branches')
        stdscr.addstr(4, 2, '2) Checkout branch')
        stdscr.addstr(5, 2, '3) Print shell command to open a shell in the repo')
        stdscr.addstr(6, 2, '4) Run custom git command')
        stdscr.addstr(7, 2, '5) Update remote SSH URL to use selected key')
        stdscr.addstr(8, 2, '0) Exit')
        stdscr.addstr(10, 2, 'Selection: ')
        stdscr.refresh()
        curses.echo()
        ch = stdscr.getstr(10, 12, 16).decode('utf-8').strip()
        curses.noecho()
        if ch == '1':
            branches = clone_actions.list_branches(repo_dir)
            stdscr.clear()
            stdscr.addstr(0, 0, 'Branches:')
            y = 2
            for b in branches:
                try:
                    stdscr.addstr(y, 2, b[: max(0, maxx - 4)])
                except Exception:
                    pass
                y += 1
                if y >= maxy - 2:
                    break
            stdscr.addstr(maxy - 1, 0, 'Press any key to continue...')
            stdscr.getch()
        elif ch == '2':
            stdscr.addstr(11, 2, 'Enter branch name to checkout: ')
            curses.echo()
            br = stdscr.getstr(11, 33, 256).decode('utf-8').strip()
            curses.noecho()
            if br:
                r = clone_actions.checkout_branch(repo_dir, br)
                stdscr.clear()
                if r.get('returncode') == 0:
                    stdscr.addstr(0, 0, f'Checked out {br}')
                else:
                    stdscr.addstr(0, 0, r.get('stderr') or r.get('stdout') or '')
                stdscr.addstr(maxy - 1, 0, 'Press any key to continue...')
                stdscr.getch()
        elif ch == '3':
            stdscr.clear()
            stdscr.addstr(0, 0, f'To open a shell: cd {repo_dir} && $SHELL')
            stdscr.addstr(maxy - 1, 0, 'Press any key to continue...')
            stdscr.getch()
        elif ch == '4':
            stdscr.addstr(11, 2, 'Enter git command (e.g. status or log --oneline): ')
            curses.echo()
            cmd = stdscr.getstr(11, 52, 512).decode('utf-8').strip()
            curses.noecho()
            if not cmd:
                continue
            try:
                parsed = shlex.split(cmd)
            except Exception:
                stdscr.addstr(13, 2, 'Failed to parse command')
                stdscr.getch()
                continue
            if parsed and parsed[0] == 'git':
                parsed = parsed[1:]
            r = clone_actions.run_custom(repo_dir, parsed)
            stdscr.clear()
            out = (r.get('stdout') or '') or (r.get('stderr') or '')
            lines = out.splitlines()
            y = 0
            for line in lines:
                try:
                    stdscr.addstr(y, 0, line[: max(0, maxx - 1)])
                except Exception:
                    pass
                y += 1
                if y >= maxy - 2:
                    break
            stdscr.addstr(maxy - 1, 0, 'Press any key to continue...')
            stdscr.getch()
        elif ch == '5':
            # show dry-run first
            stdscr.clear()
            stdscr.addstr(0, 0, 'Planning update (dry-run)...')
            stdscr.refresh()
            results = ssh_config.update_repo_remotes(repo_dir, selected_key, remotes=None, dry_run=True, backup_dir=None, yes=False)
            y = 2
            for r in results:
                line = f"{r.get('remote')}: {'skipped' if r.get('skipped') else 'will update -> ' + (r.get('new_url') or '')}"
                try:
                    stdscr.addstr(y, 2, line[: max(0, maxx - 4)])
                except Exception:
                    pass
                y += 1
                if y >= maxy - 2:
                    break
            stdscr.addstr(maxy - 1, 0, 'Apply changes? (y/N): ')
            curses.echo()
            ans = stdscr.getstr(maxy - 1, len('Apply changes? (y/N): '), 3).decode('utf-8').strip().lower()
            curses.noecho()
            if ans == 'y':
                applied = ssh_config.update_repo_remotes(repo_dir, selected_key, remotes=None, dry_run=False, backup_dir=None, yes=True)
                stdscr.clear()
                y = 0
                for a in applied:
                    line = f"{a.get('remote')}: {'skipped' if a.get('skipped') else 'updated -> ' + (a.get('new_url') or '')}"
                    try:
                        stdscr.addstr(y, 0, line[: max(0, maxx - 1)])
                    except Exception:
                        pass
                    y += 1
                    if y >= maxy - 2:
                        break
                stdscr.addstr(maxy - 1, 0, 'Press any key to continue...')
                stdscr.getch()
            else:
                stdscr.addstr(maxy - 1, 0, 'Aborted. Press any key to continue...')
                stdscr.getch()
        elif ch == '0' or ch == '':
            break
        else:
            continue

    return 0


def run_tui() -> Optional[int]:
    """Run the TUI. Prefer curses, but fall back to a simple CLI flow if curses
    cannot be used on the running system.
    """
    try:
        import curses  # type: ignore
    except Exception:
        # No curses available - fall back to CLI
        return run_cli_flow()

    try:
        # Use curses.wrapper to initialise/cleanup the terminal state
        return_value = curses.wrapper(_curses_main)
        # wrapper returns whatever the inner function returned
        if isinstance(return_value, int):
            return return_value
        return 0
    except Exception as _curses_err:
        # curses fails in non-TTY environments (e.g. IDE terminals); fall back silently
        print(f'Curses-based UI unavailable ({_curses_err}), falling back to CLI.')
        return run_cli_flow()


if __name__ == '__main__':
    rc = run_tui()
    if rc is None:
        rc = 0
    sys.exit(int(rc))
