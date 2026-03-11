# git-ssh-helper

A lightweight Python utility for cloning Git repositories using a specific SSH private key — without touching your global SSH config. Ships with a modern dark-themed GUI, a curses TUI, and a plain CLI fallback.

---

## Features

- **Key discovery** — scans `~/.ssh` for private keys and validates permissions
- **GUI mode** — Tkinter dark-themed interface (Catppuccin Mocha palette)
- **TUI / CLI mode** — curses-based or plain interactive CLI fallback
- **GIT_SSH_COMMAND** — forces the selected key via `IdentitiesOnly=yes`; nothing in `~/.ssh/config` is modified
- **Post-clone actions** — list branches, checkout, print shell command
- **Standard-library only** — no runtime dependencies beyond Python ≥ 3.8 and `git`

---

## Requirements

| Requirement | Notes |
|---|---|
| Python ≥ 3.8 | Standard library only |
| `git` binary | Must be on `$PATH` |
| `tkinter` | Optional — bundled with most Python installs; GUI falls back to TUI |
| `curses` | Optional — Unix only; TUI falls back to plain CLI |

---

## Installation

```bash
# Clone this repo
git clone git@github.com:Shivam-20/gitHandler.git
cd gitHandler

# Install (creates the git-ssh-helper console script)
pip install .

# Or install editable for development
pip install -e .
```

Verify:

```bash
git-ssh-helper --help
```

---

## Quick Start

### List discovered SSH keys

```bash
git-ssh-helper --list-keys --json
```

Output is JSON — each entry includes the key path, detected type, fingerprint, permission status, duplicate flag, and a human-readable reason.

### Clone with a specific key

```bash
git-ssh-helper --key ~/.ssh/id_ed25519 git@github.com:user/repo.git
```

### Clone into a specific directory

```bash
git-ssh-helper --key ~/.ssh/id_ed25519 --clone-dir ~/projects/myrepo git@github.com:user/repo.git
```

### Fix permissions (dry-run)

```bash
git-ssh-helper fix-permissions --dry-run --path ~/.ssh/id_ed25519
```

### Add a key to ssh-agent (start agent if needed)

```bash
git-ssh-helper add-to-agent --path ~/.ssh/id_ed25519 --start-agent
```

### Update repository remotes to use a selected key

Dry-run preview (shows planned changes):

```bash
git-ssh-helper --update-remote --repo-dir /path/to/repo --key ~/.ssh/id_ed25519 --dry-run --backup-dir ~/.ssh/backup --json
```

Apply changes (non-interactive):

```bash
git-ssh-helper --update-remote --repo-dir /path/to/repo --key ~/.ssh/id_ed25519 --backup-dir ~/.ssh/backup --yes
```

### Interactive key selection (CLI)

```bash
git-ssh-helper git@github.com:user/repo.git
```

Displays a numbered list of discovered keys. Enter the number, or `0` to type a custom path.

### GUI / TUI mode

```bash
git-ssh-helper --ui
```

Launches the Tkinter GUI if available, otherwise falls back to curses TUI, then plain CLI.

---

## GUI Overview

```
┌─────────────────────────────────────────────────────────────────┐
│ ║  git-ssh-helper  —  clone repos with your SSH key            │
├─────────────────────────────────────────────────────────────────┤
│  REPOSITORY URL                                                  │
│  [ git@github.com:user/repo.git                               ] │
│  CLONE DIRECTORY  (optional)                                     │
│  [ ~/projects/myrepo                             ]  [ Browse… ] │
│  SSH KEY                                                         │
│  [ ~/.ssh/id_ed25519   ▼ ]  [ ↺ Refresh ]  [ Choose file… ]   │
│                                                                  │
│  [  ⬇  Clone  ]   ● Ready                                       │
├─────────────────────────────────────────────────────────────────┤
│  OUTPUT                                                          │
│  Using key: /home/user/.ssh/id_ed25519                          │
│  Running: git clone git@github.com:user/repo.git → (auto)      │
│  ✔ Cloned into /home/user/repo                                  │
├─────────────────────────────────────────────────────────────────┤
│  POST-CLONE:  [ List branches ]  [ Checkout branch ]  [ Print shell cmd ] │
└─────────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
gitHandler/
├── bin/
│   └── git-ssh-helper       # CLI entry point
├── tools/
│   ├── __init__.py
│   ├── core.py              # build_ssh_command, run_git, validate_repo_url
│   ├── ssh_keys.py          # discover_keys, validate_key
│   ├── clone_actions.py     # list_branches, checkout_branch, run_custom
│   ├── gui_tk.py            # Tkinter GUI (dark theme)
│   └── ui_tui.py            # curses TUI + CLI fallback
├── tests/
│   ├── test_core.py
│   └── test_ssh_keys.py
├── pyproject.toml
└── README.md
```

---

## API Reference

### `tools.core`

```python
build_ssh_command(key_path: str) -> list[str]
```
Returns `['ssh', '-i', key_path, '-o', 'IdentitiesOnly=yes']` — suitable for `GIT_SSH_COMMAND`.

```python
run_git(args: list[str], cwd: str | None = None,
        env_overrides: dict | None = None) -> dict
```
Runs `git <args>` and returns `{'returncode': int, 'stdout': str, 'stderr': str}`.

```python
validate_repo_url(url: str) -> bool
```
Returns `True` for SCP-style (`git@host:path`) and scheme-based URLs (`ssh://`, `https://`, etc.).

### `tools.ssh_keys`

```python
discover_keys() -> list[dict]
```
Scans `~/.ssh` and returns a list of dicts: `{path, type, permissions_ok, reason}`.

```python
validate_key(path: str) -> dict
```
Validates a single key file (existence, permissions, header type).

### `tools.clone_actions`

```python
list_branches(repo_path: str) -> list[str]
checkout_branch(repo_path: str, branch: str) -> dict
show_remote(repo_path: str) -> dict
run_custom(repo_path: str, args: list[str]) -> dict
```

---

## Running Tests

```bash
# From the project root, with the venv active
pytest tests/ -v
```

All tests use the standard library only (`unittest`, `tempfile`, `os`).

---

## Security Notes

- **Never commit private keys.** The `.gitignore` excludes common key patterns.
- Key files must be `chmod 600` (owner read/write only). `discover_keys()` will flag keys with looser permissions.
- `GIT_SSH_COMMAND` is set only for the subprocess — your shell environment and `~/.ssh/config` are not modified.
- Using `IdentitiesOnly=yes` ensures SSH does not fall back to other keys in the agent.

---

## License

MIT — see [LICENSE](LICENSE).
