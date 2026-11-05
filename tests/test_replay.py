"""replay against a fake Editor that also plays the SDK's part: on Play it reads .playcal/replays/request
and writes NAME.replay / NAME.result / NAME.paused the way PlaycalReplay.cs does."""
import json
import time

import pytest

from playcal import replay as rp
from playcal.cli import main

REC = """playcal-replay 1 fps=60 seed=7
0 in move.x 1
0 mark pos 0
30 in move.x 0
30 mark pos 0.5
59 mark state landed
59 end
"""


def ok(result):
    return 0, {"success": True, "data": {"result": result}}


class Editor:
    """result: text the SDK writes as NAME.result on replay (default: the recording's marks, i.e. a match)."""

    def __init__(self, root, result=None, sdk=True, errors=(), playing=False, play_ignored=False, console_fails=False):
        self.root, self.result, self.sdk, self.errors = root, result, sdk, list(errors)
        self.play_ignored, self.console_fails, self.request = play_ignored, console_fails, None
        self.folder = root / ".playcal" / "replays"
        self.playing, self.paused, self.frame, self.reload, self.console, self.calls = playing, False, -1, 0, [], []

    def __call__(self, args):
        self.calls.append(args)
        if args[0] == "status":
            if self.reload:
                self.reload -= 1
                return 6, {"success": False, "data": {"instances": []}}
            return 0, {"success": True, "data": {"instances": [{"project": str(self.root), "state": "ready"}]}}
        if args[0] == "pipeline":
            return 0, {"data": {"instances": []}}
        cmd = args[1:3]
        if cmd == ["editor", "status"]:
            return ok({"playMode": ("paused" if self.paused else "playing") if self.playing else "stopped",
                       "projectPath": str(self.root)})
        if args[1] == "editor.playmode":
            if args[2] == "start":
                self.reload = 2
                if self.play_ignored:
                    return ok("Entered play mode")
                self.playing = True
                self.console += [{"seq": len(self.console) + 1, "level": "error", "message": m, "stackTrace": ""}
                                 for m in self.errors]
                if self.sdk:
                    self._sdk()
                return ok("Entered play mode")
            self.playing = False
            return ok("Exited play mode")
        if cmd == ["console", "status"]:
            if self.console_fails:
                return 1, {"success": False, "errors": [{"code": "COMMAND_FAILED", "message": "console unavailable"}]}
            return ok({"entries": [], "cursor": len(self.console), "session": "s1"})
        if cmd == ["console", "get"]:
            return ok({"entries": self.console[int(args[args.index("--since") + 1]):], "cursor": len(self.console)})
        if cmd == ["script", "eval"]:
            code = args[args.index("--code") + 1]
            if "Step()" in code:
                self.paused, self.frame = True, self.frame + 1
                return ok({"result": "0"})
            return ok({"result": str(self.frame)})
        return 1, {"success": False, "errors": [{"code": "UNKNOWN_COMMAND", "message": " ".join(args)}]}

    def _sdk(self):
        req = self.folder / "request"
        if not req.exists():
            return
        r = self.request = dict(ln.split("=", 1) for ln in req.read_text(encoding="utf-8").splitlines())
        req.unlink()
        name = r["name"]
        if r["mode"] == "record":
            (self.folder / f"{name}.replay").write_text(REC, encoding="utf-8")
        elif int(r["stop_at"]) >= 0:
            self.frame, self.paused = int(r["stop_at"]), True
            (self.folder / f"{name}.paused").write_text(f"{self.frame}\n", encoding="utf-8")
        else:
            rec = rp.parse((self.folder / f"{name}.replay").read_text(encoding="utf-8"))
            text = self.result or "playcal-replay 1 fps=60 seed=7\n" + "".join(
                f"{f} mark {n} {v}\n" for f, n, v in rec["marks"]) + f"{rec['end']} end\n"
            (self.folder / f"{name}.result").write_text(text, encoding="utf-8")


def clock():
    t = {"now": 0.0}
    return dict(sleep=lambda s: t.__setitem__("now", t["now"] + s), clock=lambda: t["now"])


@pytest.fixture
def root(tmp_path):
    (tmp_path / "Assets").mkdir()
    return tmp_path


def recorded(root):
    folder = root / ".playcal" / "replays"
    folder.mkdir(parents=True)
    (folder / "jump.replay").write_text(REC, encoding="utf-8")
    return folder


def test_parse_reads_input_marks_and_end():
    r = rp.parse(REC)
    assert (r["fps"], r["seed"], r["end"]) == (60, 7, 59)
    assert r["input"] == [(0, "move.x", 1.0), (30, "move.x", 0.0)]
    assert r["marks"][2] == (59, "state", "landed")


def test_parse_keeps_spaces_in_mark_values():
    assert rp.parse("playcal-replay 1\n4 mark state jumping high\n")["marks"] == [(4, "state", "jumping high")]


@pytest.mark.parametrize("text", ["hello\n", "playcal-replay 1\nx in a 1\n", "playcal-replay 1\n3 jump\n",
                                  "playcal-replay 1\n3 in a\n"])
def test_parse_rejects_bad_files(text):
    with pytest.raises(rp.ReplayError):
        rp.parse(text)


def test_compare_numbers_within_tolerance_match():
    a = rp.parse(REC)
    b = rp.parse(REC.replace("pos 0.5", "pos 0.50001"))
    assert rp.compare(a, b)["reason"] == "match"
    assert rp.compare(a, b, tolerance=1e-9)["reason"] == "diverged"


def test_compare_whole_numbers_must_match_exactly():
    score = "playcal-replay 1\n5 mark score {}\n9 end\n"
    assert rp.compare(rp.parse(score.format(10001)), rp.parse(score.format(10002)))["reason"] == "diverged"
    # the tolerance is absolute, so it doesn't widen for big numbers
    assert rp.compare(rp.parse(score.format(10000.5)), rp.parse(score.format(10000.6)))["reason"] == "diverged"


def test_compare_without_marks_is_not_a_match():
    empty = rp.parse("playcal-replay 1\n59 end\n")
    assert rp.compare(empty, empty)["reason"] == "no_marks"


def test_compare_names_first_divergence():
    out = rp.compare(rp.parse(REC), rp.parse(REC.replace("30 mark pos 0.5", "30 mark pos 0.9")))
    assert out["reason"] == "diverged"
    assert out["first_divergence"]["frame"] == 30
    assert out["first_divergence"]["expected"]["value"] == "0.5" and out["first_divergence"]["got"]["value"] == "0.9"


def test_compare_mark_on_another_frame_diverges_at_the_earlier_one():
    out = rp.compare(rp.parse(REC), rp.parse(REC.replace("59 mark state landed", "44 mark state landed")))
    assert out["first_divergence"]["frame"] == 44


def test_compare_missing_mark_and_early_end():
    short = "playcal-replay 1\n0 mark pos 0\n30 mark pos 0.5\n40 end\n"
    out = rp.compare(rp.parse(REC), rp.parse(short))
    assert out["reason"] == "diverged" and out["first_divergence"]["got"] is None
    early = REC.replace("59 end", "50 end").replace("59 mark state landed", "50 mark state landed")
    assert rp.compare(rp.parse(REC.replace("59 mark state landed\n", "")),
                      rp.parse(early.replace("50 mark state landed\n", "")))["reason"] == "ended_early"


def test_record_writes_request_and_reports_the_recording(root):
    ed = Editor(root)
    out = rp.record(ed, str(root), "jump", frames=60, **clock())
    assert out["reason"] == "recorded" and out["ok"]
    assert (out["frames"], out["input_changes"], out["marks"]) == (60, 2, 3)
    assert not ed.playing and not (root / ".playcal" / "replays" / "request").exists()
    assert ["editor.playmode", "start"] == ed.calls[[c[1:3] for c in ed.calls].index(["editor.playmode", "start"])][1:3]


def test_record_refuses_to_overwrite(root):
    recorded(root)
    assert rp.record(Editor(root), str(root), "jump", **clock())["reason"] == "exists"
    assert rp.record(Editor(root), str(root), "jump", force=True, **clock())["reason"] == "recorded"


def test_run_matches(root):
    recorded(root)
    ed = Editor(root)
    out = rp.run(ed, str(root), "jump", **clock())
    assert out["reason"] == "match" and out["ok"] and not ed.playing
    assert out["marks_replayed"] == 3


def test_run_reports_divergence(root):
    recorded(root)
    out = rp.run(Editor(root, result=REC.replace("pos 0.5", "pos 2")), str(root), "jump", **clock())
    assert out["reason"] == "diverged" and not out["ok"] and out["first_divergence"]["frame"] == 30


def test_run_with_console_errors_fails_even_when_marks_match(root):
    recorded(root)
    out = rp.run(Editor(root, errors=["NullReferenceException: boom"]), str(root), "jump", **clock())
    assert out["reason"] == "errors" and out["console"]["errors_seen"] == 1


def test_run_without_sdk_says_so(root):
    recorded(root)
    ed = Editor(root, sdk=False)
    out = rp.run(ed, str(root), "jump", wait=5, **clock())
    assert out["reason"] == "no_sdk" and not ed.playing
    assert not (root / ".playcal" / "replays" / "request").exists()


def test_run_refuses_while_playing(root):
    recorded(root)
    assert rp.run(Editor(root, playing=True), str(root), "jump", **clock())["reason"] == "already_playing"


def test_run_refuses_while_paused(root):
    recorded(root)
    ed = Editor(root, playing=True)
    ed.paused = True
    assert rp.run(ed, str(root), "jump", **clock())["reason"] == "already_playing"


def test_run_with_unreadable_console_is_not_a_match(root):
    recorded(root)
    out = rp.run(Editor(root, console_fails=True), str(root), "jump", **clock())
    assert out["reason"] == "console_unread" and not out["ok"]


def test_run_where_play_never_starts_is_play_failed_not_no_sdk(root):
    recorded(root)
    out = rp.run(Editor(root, play_ignored=True), str(root), "jump", wait=5, **clock())
    assert out["reason"] == "play_failed"
    assert not (root / ".playcal" / "replays" / "request").exists()


def test_request_is_stamped_and_removed_when_interrupted(root):
    recorded(root)
    ed = Editor(root)
    rp.run(ed, str(root), "jump", **clock())
    assert abs(int(ed.request["created"]) - time.time()) < 60  # the SDK ignores old requests

    def runner(args):
        if args[1:3] == ["editor.playmode", "start"]:
            raise KeyboardInterrupt
        return ed(args)
    with pytest.raises(KeyboardInterrupt):
        rp.run(runner, str(root), "jump", **clock())
    assert not (root / ".playcal" / "replays" / "request").exists()


def test_run_missing_or_bad_recording(root):
    assert rp.run(Editor(root), str(root), "nope", **clock())["reason"] == "no_recording"
    (recorded(root) / "bad.replay").write_text("junk\n", encoding="utf-8")
    assert rp.run(Editor(root), str(root), "bad", **clock())["reason"] == "bad_file"


def test_stop_at_leaves_editor_paused_then_step(root):
    recorded(root)
    ed = Editor(root)
    out = rp.run(ed, str(root), "jump", stop_at=20, **clock())
    assert out["reason"] == "paused" and out["frame"] == 20 and ed.playing
    st = rp.step(ed, str(root), 3)
    assert st == {"ok": True, "reason": "stepped", "steps": 3, "frame": 23}


def test_step_needs_play_mode(root):
    assert rp.step(Editor(root), str(root))["reason"] == "not_playing"


def test_no_project(tmp_path):
    assert rp.record(Editor(tmp_path), str(tmp_path), "x", **clock())["reason"] == "no_project"


def test_cli_check_two_files(tmp_path, capsys):
    a, b = tmp_path / "a.replay", tmp_path / "b.result"
    a.write_text(REC, encoding="utf-8")
    b.write_text(REC.replace("state landed", "state falling"), encoding="utf-8")
    assert main(["replay", "check", str(a), str(b), "--json"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["reason"] == "diverged" and out["first_divergence"]["got"]["value"] == "falling"
    b.write_text(REC, encoding="utf-8")
    assert main(["replay", "check", str(a), str(b)]) == 0
    assert capsys.readouterr().out.startswith("match")


def test_cli_check_by_name(root, capsys):
    folder = recorded(root)
    (folder / "jump.result").write_text(REC, encoding="utf-8")
    assert main(["replay", "check", "jump", "--project-path", str(root)]) == 0
    assert main(["replay", "check", "a", "b", "c"]) == 2
    assert "check takes" in capsys.readouterr().out
