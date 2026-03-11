import os
from pathlib import Path

from tools import core


def test_create_repo_wrapper(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    key = "/home/user/.ssh/id_test"
    wrapper = core.create_repo_wrapper(str(repo), key)
    assert Path(wrapper).exists()
    assert os.access(wrapper, os.X_OK)
    content = Path(wrapper).read_text()
    assert "-i" in content and key in content
