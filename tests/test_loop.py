"""loop against a scripted fake of the Unity CLI: each test plays back the JSON envelopes a real Editor would give."""
import json

from playcal import loop
from playcal.cli import main


def status(*states, project="C:/Games/Lab"):
    return {"success": bool(states), "data": {"instances": [{"project": project, "state": s} for s in states]}}


class Fake:
    """Plays back `unity status` envelopes in order (the last one repeats) and records every call."""

    def __init__(self, statuses, command=(0, {"success": True, "data": {"ok": 1}}), pipeline=None):
        self.statuses, self.command, self.calls = list(statuses), command, []
        self.pipeline = pipeline or {"data": {"instances": []}}

    def __call__(self, args):
        self.calls.append(args)
        if args[0] == "status":
            return 0, self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        if args[0] == "pipeline":
            return 0, self.pipeline
        return self.command


def fast(**kw):
    t = {"now": 0.0}

    def sleep(s):
        t["now"] += s

    return dict(sleep=sleep, clock=lambda: t["now"], **kw)


def test_one_ready_poll_is_not_enough_a_reload_can_flicker():
    fake = Fake([status("ready"), status("compiling"), status("ready"), status("ready")])
    out = loop.settle(fake, **fast())
    assert out["settled"] and out["states_seen"] == ["ready", "compiling", "ready"]
    assert sum(c[0] == "status" for c in fake.calls) == 4


def test_safe_mode_reported_as_itself():
    pipeline = {"data": {"instances": [{"project": "C:/Games/Lab", "safeMode": {"detected": True}}]}}
    out = loop.settle(Fake([status()], pipeline=pipeline), project="C:/Games/Lab", **fast())
    assert out["reason"] == "safe_mode" and "compile errors" in out["hint"]


def test_no_editor_after_timeout():
    out = loop.settle(Fake([status()]), timeout=3, **fast())
    assert out["reason"] == "no_editor" and not out["settled"]


def test_stuck_editor_times_out_with_last_state():
    out = loop.settle(Fake([status("busy")]), timeout=3, **fast())
    assert out["reason"] == "timeout" and out["state"] == "busy"


def test_two_editors_need_project_path():
    two = {"data": {"instances": [{"project": "C:/A", "state": "ready"}, {"project": "C:/B", "state": "ready"}]}}
    assert loop.settle(Fake([two]), **fast())["reason"] == "ambiguous"
    assert loop.settle(Fake([two]), project="C:/B", **fast())["settled"]


def test_run_settles_on_both_sides_and_passes_project():
    fake = Fake([status("ready")])
    out = loop.run_command(fake, "save_scene", ["--name", "x"], project="C:/Games/Lab", **fast())
    assert out["ok"] and out["reason"] == "ready" and out["result"]["data"] == {"ok": 1}
    cmd = [c for c in fake.calls if c[0] == "command"]
    assert cmd == [["command", "save_scene", "--name", "x", "--project-path", "C:/Games/Lab"]]


def test_run_does_not_fire_into_a_busy_editor():
    fake = Fake([status("compiling")])
    out = loop.run_command(fake, "save_scene", [], timeout=2, **fast())
    assert not out["ok"] and out["reason"] == "timeout"
    assert not any(c[0] == "command" for c in fake.calls)


def test_failed_command_surfaces_error_code():
    fake = Fake([status("ready")], command=(6, {"success": False, "errors": [{"code": "NOT_FOUND", "message": "no"}]}))
    out = loop.run_command(fake, "delete_gameobject", [], **fast())
    assert out["reason"] == "command_failed" and out["result"]["errors"][0]["code"] == "NOT_FOUND"


def test_cli_without_unity_installed(monkeypatch, capsys):
    monkeypatch.setenv("PLAYCAL_UNITY", "definitely-not-a-unity-binary")
    assert main(["loop", "settle", "--timeout", "0", "--json"]) == 3
    out = json.loads(capsys.readouterr().out)
    assert out["reason"] == "no_editor"


def test_cli_params_after_double_dash(monkeypatch):
    seen = {}

    def fake_run(runner, name, params, project, timeout):
        seen.update(name=name, params=params, timeout=timeout)
        return {"reason": "ready", "before": {"states_seen": ["ready"]}}

    monkeypatch.setattr(loop, "run_command", fake_run)
    assert main(["loop", "run", "save_scene", "--timeout", "5", "--", "--name", "x"]) == 0
    assert seen == {"name": "save_scene", "params": ["--name", "x"], "timeout": 5.0}
