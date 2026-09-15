import sys

import pytest

from lidar_analysis import central_watcher


@pytest.mark.parametrize(
    ("arguments", "experiment", "date"),
    [
        (["poll"], None, None),
        (["poll", "--once"], None, None),
        (["poll", "--once", "al_lai"], "al_lai", None),
        (["poll", "--once", "al_lai", "standcount"], "al_lai", "standcount"),
    ],
)
def test_poll_cli_dispatch(monkeypatch, arguments, experiment, date):
    calls = []
    monkeypatch.setattr(sys, "argv", ["central_watcher.py", *arguments])
    monkeypatch.setattr(central_watcher, "ensure_local_root", lambda: None)
    monkeypatch.setattr(central_watcher, "poll_once", lambda **kwargs: calls.append(kwargs))

    central_watcher.main()

    assert calls == [
        {
            "experiment_filter": experiment,
            "date_filter": date,
            "overwrite_config": False,
        }
    ]


def test_poll_cli_keeps_overwrite_config(monkeypatch):
    calls = []
    monkeypatch.setattr(
        sys,
        "argv",
        ["central_watcher.py", "poll", "--once", "al_lai", "standcount", "--overwrite-config"],
    )
    monkeypatch.setattr(central_watcher, "ensure_local_root", lambda: None)
    monkeypatch.setattr(central_watcher, "poll_once", lambda **kwargs: calls.append(kwargs))

    central_watcher.main()

    assert calls[0]["overwrite_config"] is True


@pytest.mark.parametrize(
    ("arguments", "expected_output"),
    [
        (
            ["poll", "--once", "-l"],
            "Available experiments:\n  al_lai\n  corn_2026\n",
        ),
        (
            ["poll", "--once", "-l", "al_lai"],
            "al_lai:\n  2026_07_30\n  standcount\n",
        ),
    ],
)
def test_poll_list_cli_is_read_only(monkeypatch, capsys, arguments, expected_output):
    monkeypatch.setattr(sys, "argv", ["central_watcher.py", *arguments])
    monkeypatch.setattr(
        central_watcher,
        "list_raw_experiments",
        lambda *, log_missing: ["al_lai", "corn_2026"] if not log_missing else pytest.fail("list mode logged"),
    )
    monkeypatch.setattr(central_watcher, "list_raw_dates", lambda experiment: ["2026_07_30", "standcount"])
    monkeypatch.setattr(central_watcher, "ensure_local_root", lambda: pytest.fail("list mode wrote locally"))
    monkeypatch.setattr(central_watcher, "poll_once", lambda **kwargs: pytest.fail("list mode synced"))

    central_watcher.main()

    assert capsys.readouterr().out == expected_output


def test_poll_list_rejects_date(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        ["central_watcher.py", "poll", "--once", "-l", "al_lai", "standcount"],
    )

    with pytest.raises(SystemExit, match="2"):
        central_watcher.main()

    assert "poll --list accepts an optional experiment but no date" in capsys.readouterr().err


def test_rerun_cli_dispatch_is_unchanged(monkeypatch):
    calls = []
    monkeypatch.setattr(sys, "argv", ["central_watcher.py", "rerun", "al_lai", "standcount"])
    monkeypatch.setattr(central_watcher, "ensure_local_root", lambda: None)
    monkeypatch.setattr(central_watcher, "rerun_date", lambda experiment, date: calls.append((experiment, date)))

    central_watcher.main()

    assert calls == [("al_lai", "standcount")]
