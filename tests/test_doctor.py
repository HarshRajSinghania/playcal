import json

from playcal.doctor import diagnose


def runner_with(instances, code=0, success=True):
    return lambda args, timeout=120: (code, {"success": success, "data": {"instances": instances}})


def status(checks):
    return {c["check"]: c["status"] for c in checks}


def test_missing_cli_stops_early():
    checks = diagnose(lambda a, timeout=120: (127, {"success": False, "errors": [{"code": "UNITY_CLI_MISSING"}]}))
    assert status(checks)["unity cli"] == "fail" and "editor" not in status(checks)


def test_editor_states(tmp_path):
    a, b, c = str(tmp_path / "a"), str(tmp_path / "b"), str(tmp_path / "c")
    insts = [{"projectPath": a, "isRunning": True, "pipelineServer": {"isReachable": True}},
             {"projectPath": b, "isRunning": True, "pipelineServer": {"isReachable": False}},
             {"projectPath": c, "isRunning": True, "safeMode": {"detected": True}}]
    s = status(diagnose(runner_with(insts)))
    assert (s[f"editor {a}"], s[f"editor {b}"], s[f"editor {c}"]) == ("ok", "fail", "fail")


def test_project_filter_and_sdk_check(tmp_path):
    proj = tmp_path / "Game"
    (proj / "Packages").mkdir(parents=True)
    (proj / "Packages/manifest.json").write_text(json.dumps({"dependencies": {"com.playcal.sdk": "file:x"}}),
                                                 encoding="utf-8")
    s = status(diagnose(runner_with([{"projectPath": str(tmp_path / "Other"), "isRunning": True}]), str(proj)))
    assert s["editor"] == "warn" and s["sdk"] == "ok"
