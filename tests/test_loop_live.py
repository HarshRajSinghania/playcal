"""loop against envelopes shaped like the ones a live Unity 6000.3 Editor gave (Pipeline 0.10.0-exp.1):
busy = no instance at all, pipeline list says projectPath, recompile reports errors in data."""
from playcal import loop
from playcal.cli import parse

from test_loop import Fake, fast, status

P = "C:/Games/Lab"
GONE = {"success": False, "errors": [{"code": "STATUS_NO_INSTANCES"}], "data": {"count": 0, "instances": []}}
OK = (0, {"success": True, "data": {"status": "up_to_date", "failed": False, "errors": [], "warnings": []}})
BROKEN = (6, {"success": False, "data": {"status": "completed", "failed": True, "compilationFailed": True, "errors": [
    {"type": "compile-error", "file": "Assets\\Broken.cs", "line": 1, "column": 49, "code": "CS1525",
     "message": "Invalid expression term ';'"}]}})
RACE = (6, {"success": False, "errors": [{"code": "COMMAND_FAILED", "message": "Pipeline server returned 400 Bad Request"}]})


class Live(Fake):
    def __init__(self, statuses, recompile=(OK,), **kw):
        super().__init__(statuses, **kw)
        self.recompile = list(recompile)

    def __call__(self, args):
        if args[0] == "recompile":
            self.calls.append(args)
            return self.recompile.pop(0) if len(self.recompile) > 1 else self.recompile[0]
        return super().__call__(args)


def test_blocked_editor_is_not_called_missing():
    pipe = {"data": {"instances": [
        {"projectPath": "C:/Other", "isRunning": True, "hasPipelinePackage": True, "pipelineServer": {"isReachable": True}},
        {"projectPath": "C:/wiki", "isRunning": True, "hasPipelinePackage": False},
        {"projectPath": P, "isRunning": True, "hasPipelinePackage": True, "safeMode": None,
         "pipelineServer": {"isReachable": False}}]}}
    out = loop.settle(Live([GONE], pipeline=pipe), project=P, timeout=3, **fast())
    assert out["reason"] == "editor_blocked" and "dialog" in out["hint"]
    assert loop.EXIT["editor_blocked"] == 4 and loop._fault("editor_blocked", None) == "infra"


def test_safe_mode_matches_on_project_path_only():
    other = {"data": {"instances": [{"projectPath": "C:/Other", "safeMode": {"detected": True}}]}}
    assert loop.settle(Live([GONE], pipeline=other), project=P, timeout=3, **fast())["reason"] == "no_editor"
    mine = {"data": {"instances": [{"projectPath": P, "safeMode": {"detected": True}}]}}
    assert loop.settle(Live([GONE], pipeline=mine), project=P, timeout=3, **fast())["reason"] == "safe_mode"


def test_reload_gap_counts_as_busy():
    out = loop.settle(Live([status("ready"), GONE, GONE, status("ready"), status("ready")]), project=P, **fast())
    assert out["settled"] and out["states_seen"] == ["ready", "none", "ready"]


def test_late_reload_after_package_resolve_is_waited_for():
    # resolve says it needs a recompile; the Editor stays "ready" for two polls, then reloads
    after = [status("ready")] * 4 + [status("ready"), status("ready"), GONE, GONE, status("ready"), status("ready")]
    fake = Live(after, command=(0, {"success": True, "data": {"result": {"status": "completed", "requiresRecompile": True}}}))
    out = loop.run_command(fake, "package resolve", [], project=P, **fast())
    assert out["ok"] and out["after"]["reload_seen"] and "none" in out["after"]["states_seen"]


def test_no_reload_wait_for_plain_writes():
    out = loop.run_command(Live([status("ready")]), "gameobject create", ["--name", "x"], project=P, **fast())
    assert out["ok"] and "reload_seen" not in out["after"]


def test_compile_errors_fail_even_when_ready():
    out = loop.run_command(Live([status("ready")], recompile=[BROKEN]), "script eval", [], project=P, compile=True, **fast())
    assert not out["ok"] and out["reason"] == "compile_error" and out["fault"] == "task"
    assert out["compile"]["errors"][0] == {"file": "Assets/Broken.cs", "line": 1, "code": "CS1525",
                                           "message": "Invalid expression term ';'"}
    assert loop.EXIT["compile_error"] == 6


def test_compile_retries_once_after_a_reload_race():
    fake = Live([status("ready")], recompile=[RACE, OK])
    out = loop.run_command(fake, "script eval", [], project=P, compile=True, **fast())
    assert out["ok"] and out["compile"]["ok"]
    assert sum(c[0] == "recompile" for c in fake.calls) == 2
    assert fake.calls[-1][:3] == ["recompile", "--project-path", P]


def test_compile_check_that_never_answers_is_infra():
    out = loop.run_command(Live([status("ready")], recompile=[RACE]), "script eval", [], project=P, compile=True, **fast())
    assert out["reason"] == "compile_check_failed" and out["fault"] == "infra"


def test_params_after_double_dash_with_options_before():
    args = parse(["loop", "run", "gameobject create", "--compile", "--timeout", "5", "--", "--name", "x", "--", "y"])
    assert args.name == "gameobject create" and args.params == ["--name", "x", "--", "y"] and args.compile
