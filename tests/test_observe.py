"""observe against a fake Editor: envelopes follow a live Unity 6000.3 Editor with Pipeline 0.10.0-exp.1
(`editor.playmode start` returns once Play runs, but `unity status` lists no instance for a few polls
after it; `job batch` returns one result per op, a refused op carries `error`; console entries carry
seq, level, message, stackTrace)."""
import json

from playcal import loop, observe as ob
from playcal.cli import main

P = "C:/Games/Lab"


def ok(result):
    return 0, {"success": True, "data": {"result": result}}


class Editor:
    def __init__(self, errors_in_play=(), objects=("Main Camera",), spawn=(), playing=False, reload_polls=2,
                 read_fails=False, capture_fails=False, paused=False, play_ignored=False, console_fails=False,
                 console_reset=False, no_batch=False, unbatchable=(), mute_after_start=False):
        self.objects, self.spawn, self.errors_in_play = list(objects), list(spawn), list(errors_in_play)
        self.playing, self.reload, self.reload_polls = playing, 0, reload_polls
        self.read_fails, self.capture_fails = read_fails, capture_fails
        self.paused, self.play_ignored, self.console_fails, self.console_reset = paused, play_ignored, console_fails, console_reset
        self.no_batch, self.unbatchable, self.mute_after_start = no_batch, set(unbatchable), mute_after_start
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
        if self.mute_after_start and self.playing and cmd != ["editor.playmode", "stop"]:
            return 1, {"success": False, "errors": [{"code": "UNITY_CLI_NO_INSTANCE", "message": "no editor"}]}
        if cmd == ["job", "batch"] and not self.no_batch:
            results = []
            for op in json.loads(args[args.index("--operations") + 1]):
                if op["command"] in self.unbatchable:
                    results.append({"command": op["command"], "success": False, "error": "not batchable (not_batchable)"})
                    continue
                argv = ["command", *op["command"].split()]
                for k, v in op["params"].items():
                    argv += [f"--{k}"] + ([] if v is True else [str(v)])
                rc, env = self(argv)
                self.calls.pop()  # ran inside the one batch call
                results.append({"command": op["command"], "success": bool(env.get("success")),
                                **({"result": env["data"]["result"]} if env.get("success") else
                                   {"error": env["errors"][0]["message"]})})
            return ok({"results": results})
        if cmd == ["scene", "get_hierarchy"]:
            if self.read_fails:
                return 1, {"success": False, "errors": [{"code": "COMMAND_FAILED", "message": "no scene"}]}
            return ok({"roots": [{"name": n, "hierarchyPath": "/" + n, "instanceId": id(self) % 1000 + i + 1000 * self.playing}
                                 for i, n in enumerate(self.objects)]})
        if cmd == ["editor", "status"]:
            return ok({"playMode": ("paused" if self.paused else "playing") if self.playing else "stopped"})
        if args[1] == "editor.playmode":
            if args[2] == "start":
                self.reload = self.reload_polls
                if self.play_ignored:  # e.g. compile errors: the CLI says yes, the Editor stays in Edit Mode
                    return ok("Entered play mode")
                self.playing = True
                self.objects += self.spawn
                for msg in self.errors_in_play:
                    self.console.append({"seq": len(self.console) + 1, "level": "error", "message": msg,
                                         "stackTrace": "UnityEngine.Debug:LogError (object)\nBoss:Update () (at Assets/Boss.cs:12)"})
                return ok("Entered play mode")
            self.playing = False
            return ok("Exited play mode")
        if cmd == ["console", "status"]:
            if self.console_fails:
                return 1, {"success": False, "errors": [{"code": "COMMAND_FAILED", "message": "console unavailable"}]}
            return ok({"entries": [], "cursor": len(self.console), "session": "s1"})
        if cmd == ["console", "get"]:
            since = int(args[args.index("--since") + 1])
            return ok({"entries": self.console[since:], "cursor": len(self.console), "session": "s1",
                       **({"reset": True} if self.console_reset else {})})
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


def test_clean_run_enters_play_and_leaves_play():
    ed = Editor(spawn=["Enemy"])
    out = ob.observe(ed, P, **fast())
    assert out["ok"] and out["reason"] == "clean" and out["fault"] is None
    assert out["entered_play"]["playing"] and out["played_ms"]["min"] >= 3000
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


def test_reads_are_batched_and_unity_status_lag_after_play_costs_nothing():
    ed = Editor(reload_polls=10)  # `unity status` keeps saying "no Editor" for 10 polls after start
    out = ob.observe(ed, P, **fast())
    assert out["ok"] and [c[0] for c in ed.calls].count("status") == 2  # only the settle before
    assert names(ed) == ["job batch", "editor.playmode start", "editor status", "job batch", "editor.playmode stop"]


def test_a_read_the_batch_refuses_runs_on_its_own():
    for ed in (Editor(spawn=["Enemy"], unbatchable={"scene get_hierarchy"}), Editor(spawn=["Enemy"], no_batch=True)):
        out = ob.observe(ed, P, **fast())
        assert out["ok"] and out["diff"]["added"] == 1, out
        assert names(ed).count("scene get_hierarchy") == 2


def test_op_turns_cli_words_into_batch_params():
    assert loop._op(["gameobject", "get", "--path", "/Player", "--with-children", "--depth=2"]) == {
        "command": "gameobject get", "params": {"path": "/Player", "with-children": True, "depth": "2"}}
    assert loop._op(["scene", "get_hierarchy"]) == {"command": "scene get_hierarchy", "params": {}}
    assert loop._op(["a", "b", "--k", "v", "stray"]) is None and loop._op(["--k", "v"]) is None


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


def test_paused_editor_counts_as_play_mode_and_is_left_alone():
    ed = Editor(playing=True, paused=True)
    out = ob.observe(ed, P, **fast())
    assert out["ok"] and ed.playing and ed.paused and not any("playmode" in n for n in names(ed))


def test_unreadable_console_is_not_clean():
    out = ob.observe(Editor(errors_in_play=["boom"], console_fails=True), P, **fast())
    assert not out["ok"] and out["reason"] == "console_unread" and out["fault"] == "infra"
    assert ob.observe(Editor(console_reset=True), P, **fast())["reason"] == "console_unread"
    out = ob.observe(Editor(errors_in_play=["boom"], console_reset=True), P, **fast())
    assert out["reason"] == "errors"  # errors that were read still count


def test_editor_going_quiet_after_play_starts_still_leaves_play():
    ed = Editor(mute_after_start=True)
    out = ob.observe(ed, P, timeout=3, **fast())
    assert out["reason"] == "timeout" and out["fault"] == "infra" and not ed.playing and out["left_play"]


def test_elapsed_counts_the_stop_on_an_early_return():
    ed, t = Editor(mute_after_start=True), fast()

    def slow_stop(args):
        if args[1:3] == ["editor.playmode", "stop"]:
            t["sleep"](7)
        return ed(args)
    out = ob.observe(slow_stop, P, timeout=3, **t)
    assert out["reason"] == "timeout" and out["elapsed_ms"] == round(t["clock"]() * 1000) >= 10000


def test_play_that_never_starts_is_play_failed():
    out = ob.observe(Editor(play_ignored=True), P, **fast())
    assert out["reason"] == "play_failed" and "diff" not in out


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
