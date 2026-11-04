import json
from pathlib import Path

import pytest

from playcal.cli import main
from playcal.ingest import check_lines
from playcal.report import summarize, wilson

FIXTURE = Path(__file__).parent / "fixtures" / "events-20.jsonl"


def ev(inst, level, attempt, typ, ts):
    return {"v": 0, "install_id": inst, "session_id": "s1", "game": "g", "game_version": "1",
            "ts": f"2026-11-04T10:{ts:02d}:00Z", "type": typ, "level": level, "attempt": attempt}


def test_wilson_known_values():
    lo, hi = wilson(4, 10)  # textbook: 0.168 - 0.687
    assert lo == pytest.approx(0.168, abs=1e-3) and hi == pytest.approx(0.687, abs=1e-3)
    assert wilson(0, 0) == (0.0, 1.0)
    assert wilson(10, 10)[1] == 1.0


def test_fixture_levels():
    stats = {s.level: s for s in summarize(check_lines((str(FIXTURE), l) for l in FIXTURE.read_text().splitlines()).accepted)}
    l4, l5, l6 = stats["04"], stats["05"], stats["06"]
    assert (l4.attempts, l4.attempts_passed, l4.median_attempts_to_pass) == (2, 1, 2)
    assert (l5.attempts, l5.attempts_passed, l5.player_pass_rate) == (1, 1, 1.0)
    assert (l6.attempts, l6.quit_rate, l6.players_passed, l6.median_attempts_to_pass) == (1, 1.0, 0, None)


def test_players_vs_attempts():
    events = [ev("aaaaaaaa", "1", 1, "level_fail", 1), ev("aaaaaaaa", "1", 2, "level_fail", 2),
              ev("aaaaaaaa", "1", 3, "level_complete", 3),
              ev("bbbbbbbb", "1", 1, "level_complete", 4),
              ev("cccccccc", "1", 1, "level_start", 5)]  # never finished
    (s,) = summarize(events)
    assert (s.players, s.players_passed) == (3, 2)
    assert (s.attempts, s.attempts_passed, s.unfinished_attempts) == (4, 2, 1)
    assert s.median_attempts_to_pass == 2  # median of [3, 1]


def test_versions_kept_apart():
    events = [ev("aaaaaaaa", "1", 1, "level_complete", 1)]
    events.append({**ev("aaaaaaaa", "1", 1, "level_fail", 2), "game_version": "2"})
    assert [(s.game_version, s.attempt_pass_rate) for s in summarize(events)] == [("1", 1.0), ("2", 0.0)]


def test_natural_level_order():
    events = [ev("aaaaaaaa", lv, 1, "level_complete", i) for i, lv in enumerate(["10", "2", "1"])]
    assert [s.level for s in summarize(events)] == ["1", "2", "10"]


def test_cli_json(capsys):
    assert main(["report", str(FIXTURE), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["skipped_invalid"] == 2
    assert [l["level"] for l in out["levels"]] == ["04", "05", "06"]
