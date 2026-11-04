"""The Unity SDK core (C#) must write events the Python side accepts, both as JSONL and as a PC0 paste.

Runs the dotnet check program in unity/tests/CoreCheck; skipped when dotnet isn't installed.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from playcal.ingest import check_lines, decode_paste

CHECK = Path(__file__).parent.parent / "unity" / "tests" / "CoreCheck"


@pytest.fixture(scope="module")
def output():
    if not shutil.which("dotnet"):
        pytest.skip("dotnet not installed")
    run = subprocess.run(["dotnet", "run", "-c", "Release", "--project", str(CHECK)],
                         capture_output=True, text=True, encoding="utf-8", timeout=600)
    assert run.returncode == 0, run.stdout[-2000:] + run.stderr[-2000:]
    return [ln for ln in run.stdout.splitlines() if ln.strip()]


def test_every_jsonl_line_valid(output):
    jsonl = [ln for ln in output if ln.startswith("{")]
    res = check_lines(("cs", ln) for ln in jsonl)
    assert len(jsonl) == 10 and not res.rejected, res.rejected


def test_paste_decodes_to_same_events(output):
    paste = [ln for ln in output if ln.startswith("PC0:")]
    assert len(paste) == 1
    res = check_lines(decode_paste(paste[0]))
    assert not res.rejected, res.rejected
    first_session = [json.loads(ln) for ln in output if ln.startswith("{")][:9]
    assert res.accepted == first_session


def test_attempts_and_quotes_survive(output):
    events = [json.loads(ln) for ln in output if ln.startswith("{")]
    assert [e["attempt"] for e in events if e["type"] == "level_start"] == [1, 2, 1, 3]
    assert any(e.get("level") == 'lv "quoted"' for e in events)
