import pytest

from tools.core import build_ssh_command, validate_repo_url


def test_build_ssh_command_and_invalid():
    cmd = build_ssh_command("/some/key")
    assert isinstance(cmd, list)
    assert cmd[0] == "ssh"
    assert "-i" in cmd
    assert "/some/key" in cmd

    with pytest.raises(ValueError):
        build_ssh_command("")
    with pytest.raises(ValueError):
        build_ssh_command(None)


@pytest.mark.parametrize("url,expected", [
    ("git@github.com:user/repo.git", True),
    ("ssh://git@github.com/user/repo.git", True),
    ("https://github.com/user/repo.git", True),
    ("not a url", False),
    ("", False),
])
def test_validate_repo_url(url, expected):
    assert validate_repo_url(url) is expected
