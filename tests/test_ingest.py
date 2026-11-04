import json
from pathlib import Path

import pytest

from playcal.cli import main
from playcal.ingest import check_lines, decode_paste, encode_paste

FIXTURE = Path(__file__).parent / "fixtures" / "events-20.jsonl"


def lines(path):
    return [(path.name, line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_fixture_18_valid_2_bad():
    res = check_lines(lines(FIXTURE))
    assert len(res.accepted) == 18
    assert len(res.rejected) == 2
    reasons = " | ".join(r["reason"] for r in res.rejected)
    assert "'type' is a required property" in reasons
    assert "attempt" in reasons


def test_level_events_need_level_and_attempt():
    ev = {"v": 0, "ts": "2026-11-04T10:00:00Z", "install_id": "inst_9f3k2a7q", "session_id": "s001",
          "game": "g", "game_version": "1", "type": "level_fail"}
    res = check_lines([("x", json.dumps(ev))])
    assert not res.accepted and "required" in res.rejected[0]["reason"]


def test_unknown_fields_rejected_so_nothing_personal_sneaks_in():
    ev = {"v": 0, "ts": "2026-11-04T10:00:00Z", "install_id": "inst_9f3k2a7q", "session_id": "s001",
          "game": "g", "game_version": "1", "type": "session_start", "email": "a@b.c"}
    assert check_lines([("x", json.dumps(ev))]).rejected


def test_bad_timestamp_rejected():
    ev = {"v": 0, "ts": "yesterday", "install_id": "inst_9f3k2a7q", "session_id": "s001",
          "game": "g", "game_version": "1", "type": "session_start"}
    assert check_lines([("x", json.dumps(ev))]).rejected


def test_paste_roundtrip_inside_chat_noise():
    valid = check_lines(lines(FIXTURE)).accepted
    blob = encode_paste(valid)
    chat = f"[10:42] Ayşe: işte sonucum\n[10:42] Ayşe: {blob}\n[10:43] Ayşe: 05 zordu"
    res = check_lines(decode_paste(chat))
    assert res.accepted == valid and not res.rejected


def test_broken_paste_reported_not_crashing():
    res = check_lines(decode_paste("PC0:AAAAbroken"))
    assert not res.accepted and "paste blob broken" in res.rejected[0]["reason"]


def test_cli_writes_files_and_json_summary(tmp_path, capsys):
    out, rej = tmp_path / "ok.jsonl", tmp_path / "bad.jsonl"
    assert main(["ingest", str(FIXTURE), "--out", str(out), "--rejected", str(rej), "--json"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert (summary["accepted"], summary["rejected"]) == (18, 2)
    assert len(out.read_text().splitlines()) == 18 and len(rej.read_text().splitlines()) == 2


def test_cli_missing_file_exit_2(tmp_path):
    assert main(["ingest", str(tmp_path / "nope.jsonl"), "--out", str(tmp_path / "o"), "--rejected", str(tmp_path / "r")]) == 2


def test_modules_listed_from_registry(capsys):
    assert main(["modules", "--json"]) == 0
    names = [m["name"] for m in json.loads(capsys.readouterr().out)]
    assert "ingest" in names
