import json
from pathlib import Path

from playcal import logs
from playcal.cli import main

SAMPLE = Path(__file__).parent / "fixtures" / "editor_sample.log"


def summary(marker=None):
    return logs.summarize(logs.since(SAMPLE.read_text(encoding="utf-8").splitlines(), marker))


def test_repeats_collapse_and_compile_error_is_first_cause():
    out = summary("Begin MonoManager")
    assert out["first_cause"]["code"] == "CS0103" and out["first_cause"]["file"] == "Assets/Scripts/Board.cs"
    kinds = [(e["kind"], e["code"], e["count"]) for e in out["errors"]]
    assert kinds == [("compile", "CS0103", 2), ("compile", "CS1061", 1),
                     ("exception", "NullReferenceException", 2), ("log_error", "LogError", 1)]
    assert out["error_total"] == 6 and out["warnings"] == 1 and not out["ok"]


def test_exception_points_at_project_code_not_engine_frames():
    nre = [e for e in summary()["errors"] if e["kind"] == "exception"][0]
    assert (nre["file"], nre["line"]) == ("Assets/Scripts/Player.cs", 21)
    log_error = [e for e in summary()["errors"] if e["kind"] == "log_error"][0]
    assert log_error["message"] == "Level 4 has no goal set" and log_error["line"] == 55


def test_since_drops_older_errors_and_backslashes_are_normalized():
    assert [e["file"] for e in summary("Begin MonoManager")["errors"]][1] == "Assets/Scripts/Hud.cs"
    assert "Assets/Scripts/Old.cs" in [e.get("file") for e in summary()["errors"]]
    assert "Assets/Scripts/Old.cs" not in [e.get("file") for e in summary("Begin MonoManager")["errors"]]


def test_clean_log_and_limit(tmp_path):
    clean = tmp_path / "clean.log"
    clean.write_text("Refreshing native plugins\nAll good\n", encoding="utf-8")
    assert main(["logs", str(clean), "--json"]) == 0
    assert logs.summarize(SAMPLE.read_text(encoding="utf-8").splitlines(), limit=2)["truncated"] == 3


def test_cli_json(capsys):
    assert main(["logs", str(SAMPLE), "--since", "Begin MonoManager", "--json"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["first_cause"]["message"].startswith("The name 'tiles'")


def test_logcat_prefix_is_stripped_and_other_apps_are_ignored():
    lines = (Path(__file__).parent / "fixtures" / "logcat_sample.log").read_text(encoding="utf-8").splitlines()
    out = logs.summarize(lines)
    kinds = [(e["kind"], e["code"], e["count"]) for e in out["errors"]]
    assert kinds == [("exception", "NullReferenceException", 2), ("log_error", "LogError", 1)]
    assert out["errors"][0]["first_line"] == 2 and out["error_total"] == 3
    assert not any("IllegalState" in e["message"] for e in out["errors"])


def test_editor_log_lines_are_not_touched_by_delogcat():
    lines = SAMPLE.read_text(encoding="utf-8").splitlines()
    assert logs.delogcat(lines) == lines
