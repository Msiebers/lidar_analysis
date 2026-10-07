"""The `python -m lidar_analysis.webapp` launcher (Web-P1D)."""
from __future__ import annotations

import pytest
import uvicorn

from lidar_analysis.webapp import __main__ as launcher


@pytest.fixture
def captured(monkeypatch):
    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: calls.append((app, kwargs)))
    return calls


def test_binds_to_loopback_only_on_the_default_port(captured, capsys):
    launcher.main([])
    (app, kwargs), = captured
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 8000
    assert hasattr(app.state, "sessions")
    assert "http://127.0.0.1:8000" in capsys.readouterr().out


def test_port_can_be_chosen(captured):
    launcher.main(["--port", "8765"])
    assert captured[0][1]["port"] == 8765


@pytest.mark.parametrize("args", [["--host", "0.0.0.0"], ["--port", "0"], ["--port", "70000"], ["--port", "abc"]])
def test_no_way_to_bind_elsewhere_or_to_a_bad_port(captured, args):
    with pytest.raises(SystemExit):
        launcher.main(args)
    assert captured == []


def test_startup_message_explains_the_ssh_tunnel(captured, capsys):
    launcher.main(["--port", "8123"])
    out = capsys.readouterr().out
    assert "ssh -L 8123:127.0.0.1:8123" in out
