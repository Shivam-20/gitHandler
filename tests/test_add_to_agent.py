import subprocess
import shutil

from tools import ssh_keys


def test_add_to_agent_calls_subprocess(monkeypatch):
    # ensure ssh-add is "available"
    monkeypatch.setattr(shutil, "which", lambda cmd: "/usr/bin/ssh-add" if cmd == "ssh-add" else None)

    calls = []

    def fake_run(*args, **kwargs):
        # record the command and return a success-like object
        calls.append(args[0])

        class R:
            returncode = 0
            stdout = "ok"
            stderr = ""

        return R()

    monkeypatch.setattr(subprocess, "run", fake_run)

    res = ssh_keys.add_to_agent("/some/key", start_agent=False)
    assert res["added"] is True
    assert calls, "ssh-add was not called"
    assert calls[0][0] == "ssh-add"
