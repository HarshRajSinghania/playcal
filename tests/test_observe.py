"""observe against a fake Editor: envelopes follow a live Unity 6000.3 Editor with Pipeline 0.10.0-exp.1
(entering Play drops the instance from `unity status` during the reload; console entries carry seq,
level, message, stackTrace)."""
import json

from playcal import observe as ob
from playcal.cli import main

P = "C:/Games/Lab"


def ok(result):
    return 0, {"success": True, "data": {"result": result}}


class Editor:
    def __init__(self, errors_in_play=(), objects=("Main Camera",), spawn=(), playing=False, reload_polls=2,
                 read_fails=False, capture_fails=False):
        self.objects, self.spawn, self.errors_in_play = list(objects), list(spawn), list(errors_in_play)
        self.playing, self.reload, self.reload_polls = playing, 0, reload_polls
        self.read_fails, self.capture_fails = read_fails, capture_fails
        self.console, self.calls = [], []

    def __call__(self, args):
        self.calls.append(args)
        if args[0] == "status":
            if self.reload:
                self.reload -= 1
                return 6, {"success": False, "data": {"instances": []}}
            return 0, {"success": True, "data": {"instances": [{"project": P, "state": "ready"}]}}
        if args[0] == "pipeline":
            return 0, {"data": {"instances": []}}
        cmd = args[1:3]
        if cmd == ["scene", "get_hierarchy"]:
            if self.read_fails:
                return 1, {"success": False, "errors": [{"code": "COMMAND_FAILED", "message": "no scene"}]}
            return ok({"roots": [{"name": n, "hierarchyPath": "/" + n, "instanceId": id(self) % 1000 + i + 1000 * self.playing}
                                 for i, n in enumerate(self.objects)]})
        if cmd == ["editor", "status"]:
            return ok({"playMode": "playing" if self.playing else "stopped"})
        if args[1] == "editor.playmode":
            if args[2] == "start":
                self.playing, self.reload = True, self.reload_polls
                self.objects += self.spawn
                for msg in self.errors_in_play:
                    self.console.append({"seq": len(self.console) + 1, "level": "error", "message": msg,
                                         "stackTrace": "UnityEngine.Debug:LogError (object)\nBoss:Update () (at Assets/Boss.cs:12)"})
                return ok("Entered play mode")
            self.playing = False
            return ok("Exited play mode")
        if cmd == ["console", "status"]:
            return ok({"entries": [], "cursor": len(self.console), "session": "s1"})
        if cmd == ["console", "get"]:
            since = int(args[args.index("--since") + 1])
            return ok({"entries": self.console[since:], "cursor": len(self.console), "session": "s1"})
        if cmd == ["capture", "game_view"]:
            if self.capture_fails:
                return 1, {"success": False, "errors": [{"code": "COMMAND_FAILED", "message": "no game view"}]}
            return ok({"savedPath": "C:/Games/Lab/" + args[args.index("--output-path") + 1]})
        return 1, {"success": False, "errors": [{"code": "UNKNOWN_COMMAND", "message": " ".join(args)}]}


def fast():
    t = {"now": 0.0}

    def sleep(s):
        t["now"] += s

    return dict(sleep=sleep, clock=lambda: t["now"])


def names(ed):
    return [" ".join(c[1:3]) for c in ed.calls if c[0] == "command"]


def test_clean_run_enters_play_waits_out_the_reload_and_leaves_play():
    ed = Editor(spawn=["Enemy"])
    out = ob.observe(ed, P, **fast())
    assert out["ok"] and out["reason"] == "clean" and out["fault"] is None
    assert "none" in out["entered_play"]["states_seen"]  # the reload was seen, not skipped over
    assert out["diff"]["added"] == 1 and out["diff"]["changes"][0]["path"] == "result.roots[hierarchyPath=/Enemy]"
    assert out["diff"]["changed"] == 0  # instanceIds differ between edit and play mode; left out
    assert "shot" not in out and out["left_play"] and not ed.playing
    assert "capture game_view" not in names(ed)


def test_console_error_in_play_is_red_and_gets_a_screenshot():
    ed = Editor(errors_in_play=["boss has no target", "boss has no target"])
    out = ob.observe(ed, P, name="boss", **fast())
    assert not out["ok"] and out["reason"] == "errors" and out["fault"] == "task"
    con = out["console"]
    assert con["errors_seen"] == 2 and con["error_kinds"] == 1
    assert con["first_cause"]["message"] == "boss has no target" and con["first_cause"]["file"] == "Assets/Boss.cs"
    assert out["shot"] == "C:/Games/Lab/.playcal/observe/boss.png"
    assert not ed.playing  # still leaves Play Mode on a red run


def test_errors_from_before_the_run_dont_count():
    ed = Editor()
    ed.console.append({"seq": 1, "level": "error", "message": "old error", "stackTrace": ""})
    out = ob.observe(ed, P, **fast())
    assert out["ok"] and out["console"]["errors_seen"] == 0


def test_failed_expect_is_red():
    out = ob.observe(Editor(), P, expect=["result.roots.*.name=Player"], **fast())
    assert out["reason"] == "expect_failed" and "shot" in out and not out["checks"][0]["ok"]


def test_no_play_never_touches_play_mode():
    ed = Editor()
    out = ob.observe(ed, P, play=False, **fast())
    assert out["ok"] and not any("playmode" in n for n in names(ed)) and "entered_play" not in out


def test_already_playing_is_watched_and_left_running():
    ed = Editor(playing=True)
    out = ob.observe(ed, P, **fast())
    assert out["ok"] and ed.playing and not any("playmode" in n for n in names(ed))


def test_no_editor_is_infra():
    ed = Editor(reload_polls=10**6)
    ed.reload = 10**6
    out = ob.observe(ed, P, timeout=3, **fast())
    assert out["reason"] == "no_editor" and out["fault"] == "infra"


def test_failed_read_is_reported_and_shot_failure_doesnt_crash():
    out = ob.observe(Editor(read_fails=True), P, **fast())
    assert out["reason"] == "read_failed" and out["read_errors"][0]["code"] == "COMMAND_FAILED"
    out = ob.observe(Editor(errors_in_play=["x"], capture_fails=True), P, **fast())
    assert out["reason"] == "errors" and out["shot"]["failed"][0]["message"] == "no game view"


def test_cli_exit_codes_and_json(monkeypatch, capsys):
    ed = Editor(errors_in_play=["boom"])
    monkeypatch.setattr("playcal.loop.unity_runner", ed)
    monkeypatch.setattr("time.sleep", lambda s: None)
    assert main(["observe", "--project-path", P, "--seconds", "0", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["reason"] == "errors"
    monkeypatch.setattr("playcal.loop.unity_runner", Editor())
    assert main(["observe", "--project-path", P, "--seconds", "0"]) == 0
    assert capsys.readouterr().out.startswith("clean")
