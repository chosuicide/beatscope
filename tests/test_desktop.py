"""Portable decoding finds the bundled tools without changing the system PATH."""
import os
import sys

import pytest

from beatscope import desktop


@pytest.mark.parametrize("frozen", [True, False])
def test_bundled_tools_are_on_path_only_in_frozen_app(tmp_path, monkeypatch, frozen):
    tools = tmp_path / "tools"
    tools.mkdir()
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Beathi Studio.exe"))
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    monkeypatch.setenv("PATH", "original-path")
    monkeypatch.setenv("BEATSCOPE_NO_BROWSER", "1")
    observed = []
    monkeypatch.setattr(desktop, "serve", lambda *args, **kwargs: observed.append(os.environ["PATH"]))
    assert desktop.main() == 0
    assert observed == [str(tools) + os.pathsep + "original-path" if frozen else "original-path"]
