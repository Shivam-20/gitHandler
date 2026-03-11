from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from typing import List, Optional

# Local imports
try:
    from tools import ssh_keys, core, ssh_config
except Exception:
    import tools.ssh_keys as ssh_keys
    import tools.core as core
    import tools.ssh_config as ssh_config


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="git-ssh-helper", description="Clone a git repo using a selected SSH key (GIT_SSH_COMMAND).")
    parser.add_argument('repo', nargs='?', help='Repository URL to clone', default=None)
    parser.add_argument('--key', help='Path to private SSH key to use', default=None)
    parser.add_argument('--list-keys', action='store_true', help='List discovered SSH keys and exit')
    parser.add_argument('--ui', action='store_true', help='Launch GUI/TUI mode')
    parser.add_argument('--clone-dir', help='Directory to clone into (optional)', default=None)
    parser.add_argument('--json', action='store_true', help='Output JSON where applicable')

    # update-remote options
    parser.add_argument('--update-remote', action='store_true', help='Update git remotes in a local repo to use an SSH Host alias pointing to the selected key')
    parser.add_argument('--repo-dir', help='Local git repo path to update remotes in (required for --update-remote)')
    parser.add_argument('--remotes', action='append', help='Remote names to update (repeatable). If omitted all remotes are considered.')
    parser.add_argument('--dry-run', action='store_true', help='Show planned changes without applying')
    parser.add_argument('--backup-dir', help='Directory to store backups (for ssh_config changes)')
    parser.add_argument('--yes', '-y', action='store_true', help='Apply changes without prompting (non-interactive)')

    args = parser.parse_args(argv)

    if args.list_keys:
        keys = ssh_keys.discover_keys()
        if args.json:
            print(json.dumps(keys, indent=2))
        else:
            for k in keys:
                print(f"{k['path']}: type={k.get('type')} fp={k.get('fingerprint')} perms_ok={k.get('permissions_ok')} dup={k.get('duplicate')}")
        return 0

    if args.ui:
        # Prefer Tkinter GUI; gui_tk.run_gui() already falls back to TUI internally.
        # Only import ui_tui directly if gui_tk itself cannot be imported at all.
        try:
            from tools import gui_tk as _gui
        except Exception:
            try:
                import tools.gui_tk as _gui
            except Exception:
                _gui = None  # type: ignore

        if _gui is not None:
            rc = _gui.run_gui()
        else:
            try:
                from tools import ui_tui as _tui
            except Exception:
                import tools.ui_tui as _tui
            rc = _tui.run_tui()
        return 0 if rc is None else int(rc)

    selected_key = None
    if args.key:
        selected_key = os.path.expanduser(args.key)
    else:
        keys = ssh_keys.discover_keys()
        selected_key = None
        if keys:
            # simple interactive selection
            for i, k in enumerate(keys, start=1):
                print(f"{i}) {k.get('path')}  type={k.get('type')} perms_ok={k.get('permissions_ok')}")
            print('0) Enter custom path')
            while True:
                try:
                    choice = input('Select key number (or 0): ').strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    return 2
                if not choice:
                    continue
                try:
                    idx = int(choice)
                except ValueError:
                    print('Please enter a number')
                    continue
                if idx == 0:
                    path = input('Enter path to private key: ').strip()
                    if not path:
                        print('Empty path, try again')
                        continue
                    selected_key = os.path.expanduser(path)
                    break
                if 1 <= idx <= len(keys):
                    selected_key = os.path.expanduser(keys[idx - 1].get('path'))
                    break
                print('Invalid selection')
        else:
            print('No key found, please provide --key', file=sys.stderr)
            return 2

    # Handle update-remote flow before clone requirements
    if args.update_remote:
        repo_dir = args.repo_dir or args.repo
        if not repo_dir:
            print('Repository directory is required for --update-remote (use --repo-dir)', file=sys.stderr)
            return 2
        if not selected_key:
            print('No key selected, exiting', file=sys.stderr)
            return 2
        results = ssh_config.update_repo_remotes(repo_dir, selected_key, remotes=args.remotes, dry_run=args.dry_run, backup_dir=args.backup_dir, yes=args.yes)
        if args.json:
            print(json.dumps(results, indent=2))
        else:
            for r in results:
                if r.get('skipped'):
                    print(f"{r.get('remote')}: skipped - {r.get('reason')}")
                else:
                    conf = r.get('config', {})
                    print(f"{r.get('remote')}: {r.get('original_url')} -> {r.get('new_url')} (alias={r.get('alias')}) config_written={conf.get('written')}")
        return 0

    if not selected_key:
        print('No key selected, exiting', file=sys.stderr)
        return 2

    try:
        ssh_cmd_list = core.build_ssh_command(selected_key)
    except Exception as e:
        print(f'Failed to build SSH command from key "{selected_key}": {e}', file=sys.stderr)
        return 3

    ssh_cmd_str = ' '.join(shlex.quote(p) for p in ssh_cmd_list)

    if not args.repo:
        print('Repository URL required. Use: git-ssh-helper REPO_URL [options]', file=sys.stderr)
        return 1

    clone_args: List[str] = ['clone', args.repo]
    if args.clone_dir:
        clone_args.append(args.clone_dir)

    print(f"Cloning {args.repo}...")
    res = core.run_git(clone_args, env_overrides={'GIT_SSH_COMMAND': ssh_cmd_str})
    if res.get('returncode') != 0:
        print('git clone failed', file=sys.stderr)
        if res.get('stderr'):
            print(res.get('stderr'), file=sys.stderr)
        elif res.get('stdout'):
            print(res.get('stdout'), file=sys.stderr)
        return 4

    if args.clone_dir:
        repo_dir = os.path.expanduser(args.clone_dir)
    else:
        repo_dir = os.path.join(os.getcwd(), args.repo.rstrip('/').split('/')[-1].replace('.git',''))

    print(f"Cloned into {repo_dir}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
