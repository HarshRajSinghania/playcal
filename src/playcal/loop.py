"""playcal loop: run one Unity Editor command the way an agent should, then report one JSON digest.

  settle  wait until the Editor is really ready: "ready" on several polls in a row,
          so a compile or domain reload that flickers between polls isn't missed.
          Safe Mode (compile errors) is reported as itself, not as "no editor".
  run     settle -> unity command NAME ... -> settle again -> verify.
          --verify "CMD ARGS" re-reads the Editor after the write, --expect PATH=VALUE checks
          the read (or the command's own result when there is no --verify), --diff shows only
          what changed in the --verify read between before and after.

Every digest says whose fault a failure is: "infra" (no Editor, Safe Mode, stuck, CLI broken)
or "task" (the command failed, or it said it worked but the check disagrees).
Built on Unity's official CLI (`unity status`, `unity pipeline list`, `unity command`).
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from typing import Callable

from . import checks
from .registry import Module

Runner = Callable[[list[str]], "tuple[int, dict]"]

EXIT = {"ready": 0, "command_failed": 1, "ambiguous": 2, "timeout": 3, "no_editor": 3, "safe_mode": 4,
        "verify_failed": 5}
INFRA = {"ambiguous", "timeout", "no_editor", "safe_mode"}


def unity_runner(args: list[str], timeout: float = 120) -> tuple[int, dict]:
    """Calls the real `unity` binary (or $PLAYCAL_UNITY) and parses its JSON envelope from stdout."""
    exe = os.environ.get("PLAYCAL_UNITY", "unity")
    env = dict(os.environ, UNITY_NO_UPDATE_CHECK="1", UNITY_NO_CONSENT_PROMPT="1")
    try:
        p = subprocess.run([exe, *args, "--json", "--no-banner", "--non-interactive"], capture_output=True,
                           text=True, encoding="utf-8", timeout=timeout, env=env)
    except FileNotFoundError:
        return 127, {"success": False, "errors": [{"code": "UNITY_CLI_MISSING", "message": f"{exe} not on PATH"}]}
    except subprocess.TimeoutExpired:
        return 124, {"success": False, "errors": [{"code": "UNITY_CLI_TIMEOUT", "message": f"{args[0]} took over {timeout}s"}]}
    try:
        return p.returncode, json.loads(p.stdout)
    except json.JSONDecodeError:
        return p.returncode, {"success": False, "errors": [{"code": "UNITY_CLI_BAD_JSON", "message": p.stdout[-500:] or p.stderr[-500:]}]}


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def _pick(instances: list[dict], project: str | None) -> tuple[dict | None, str | None]:
    if project:
        hits = [i for i in instances if i.get("project") and _norm(i["project"]) == _norm(project)]
        return (hits[0], None) if hits else (None, None)
    if len(instances) > 1:
        return None, "ambiguous"
    return (instances[0] if instances else None), None


def _safe_mode(runner: Runner, project: str | None) -> bool:
    _, env = runner(["pipeline", "list"])
    for inst in (env.get("data") or {}).get("instances") or []:
        if (inst.get("safeMode") or {}).get("detected") and (not project or not inst.get("project")
                                                             or _norm(inst["project"]) == _norm(project)):
            return True
    return False


def settle(runner: Runner, project: str | None = None, timeout: float = 120, poll: float = 0.5, stable: int = 2,
           sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> dict:
    start, streak, seen, state, checked_safe = clock(), 0, [], None, False
    while True:
        _, env = runner(["status"])
        inst, problem = _pick((env.get("data") or {}).get("instances") or [], project)
        if problem:
            return _settled(problem, project, None, seen, clock() - start)
        state = inst.get("state") if inst else None
        if not seen or seen[-1] != (state or "none"):
            seen.append(state or "none")
        if inst and state == "ready":
            streak += 1
            if streak >= stable:
                return _settled("ready", project or inst.get("project"), state, seen, clock() - start)
        else:
            streak = 0
            if inst is None and not checked_safe:
                checked_safe = True
                if _safe_mode(runner, project):
                    return _settled("safe_mode", project, None, seen, clock() - start)
        if clock() - start >= timeout:
            return _settled("timeout" if inst else "no_editor", project, state, seen, clock() - start)
        sleep(poll)


def _settled(reason: str, project, state, seen, waited: float) -> dict:
    hints = {
        "safe_mode": "Editor is in Safe Mode because of compile errors. Fix them in the C# source, then restart Unity.",
        "no_editor": "No Editor with the Pipeline package found. Open the project in Unity, or run `unity pipeline install`.",
        "ambiguous": "More than one Editor is open. Pass --project-path.",
        "timeout": "Editor never stayed ready. It may be compiling, importing, or blocked by a modal dialog.",
    }
    out = {"settled": reason == "ready", "reason": reason, "project": project, "state": state,
           "states_seen": seen, "waited_ms": round(waited * 1000)}
    if reason in hints:
        out["hint"] = hints[reason]
    return out


def _call(runner: Runner, argv: list[str], project: str | None) -> dict:
    rc, env = runner(["command", *argv, *(["--project-path", project] if project else [])])
    return {"success": bool(env.get("success")) and rc == 0, "exit_code": rc,
            "errors": env.get("errors") or [], "warnings": env.get("warnings") or [], "data": env.get("data")}


def _fault(reason: str, result: dict | None) -> str | None:
    if reason == "ready":
        return None
    if reason in INFRA:
        return "infra"
    codes = [str(e.get("code", "")) for e in (result or {}).get("errors", [])]
    return "infra" if any(c.startswith("UNITY_CLI_") for c in codes) else "task"


def run_command(runner: Runner, name: str, params: list[str], project: str | None = None, timeout: float = 120,
                verify: list[str] | None = None, expect: list[str] = (), want_diff: bool = False,
                **settle_kw) -> dict:
    t0 = time.monotonic()
    digest: dict = {"command": name, "params": params, "before": settle(runner, project, timeout, **settle_kw)}
    if not digest["before"]["settled"]:
        digest["ok"], digest["reason"] = False, digest["before"]["reason"]
        digest["fault"] = _fault(digest["reason"], None)
        return digest
    snapshot = _call(runner, verify, project) if verify and want_diff else None
    digest["result"] = _call(runner, [name, *params], project)
    digest["after"] = settle(runner, project, timeout, **settle_kw)
    reason = ("command_failed" if not digest["result"]["success"] else
              digest["after"]["reason"] if not digest["after"]["settled"] else "ready")

    if reason == "ready" and (verify or expect):
        read = _call(runner, verify, project) if verify else digest["result"]
        if verify:
            digest["verify"] = {"command": verify, "success": read["success"], "errors": read["errors"]}
        digest["checks"] = [checks.check(read["data"], e) for e in expect]
        if snapshot is not None and snapshot["success"] and read["success"]:
            digest["diff"] = checks.diff(snapshot["data"], read["data"])
        if not read["success"]:
            reason, digest["fault"] = "verify_failed", _fault("command_failed", read)
        elif not all(c["ok"] for c in digest["checks"]):
            reason = "verify_failed"

    digest["ok"], digest["reason"] = reason == "ready", reason
    digest.setdefault("fault", _fault(reason, digest["result"]))
    digest["elapsed_ms"] = round((time.monotonic() - t0) * 1000)
    return digest


def _add_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("action", choices=["settle", "run"], help="settle: wait for a ready Editor. run: settle, run, settle")
    p.add_argument("name", nargs="?", help="Editor command for `run` (see `unity command`)")
    p.add_argument("params", nargs="*", help="passed to the command unchanged; put them after --, e.g. run save_scene -- --name x")
    p.add_argument("--project-path", help="Unity project folder; needed when several Editors are open")
    p.add_argument("--timeout", type=float, default=120, help="seconds to wait for a ready Editor (default 120)")
    p.add_argument("--verify", metavar="CMD", help='read command run after the write, e.g. "get_hierarchy --depth 1"')
    p.add_argument("--expect", action="append", default=[], metavar="PATH=VALUE",
                   help="check on the --verify read (or the command result). PATH=VALUE, PATH!=VALUE, PATH~TEXT, "
                        "or bare PATH (exists). * matches any list item: objects.*.name=Probe. Repeatable")
    p.add_argument("--diff", action="store_true", help="run --verify before the write too and report only what changed")
    p.add_argument("--json", action="store_true", help="print the digest as JSON")


def _run(args: argparse.Namespace) -> int:
    if args.action == "run" and not args.name:
        print("playcal loop run: give an Editor command name", file=sys.stderr)
        return 2
    if args.action == "settle":
        out = settle(unity_runner, args.project_path, args.timeout)
        reason = out["reason"]
    else:
        verify = shlex.split(args.verify) if args.verify else None
        out = run_command(unity_runner, args.name, args.params, args.project_path, args.timeout,
                          verify=verify, expect=args.expect, want_diff=args.diff)
        reason = out["reason"]
    if args.json:
        print(json.dumps(out, ensure_ascii=False))
    else:
        print(f"{reason} ({' -> '.join(out.get('states_seen') or out.get('before', {}).get('states_seen', []))})")
        if "hint" in out:
            print(out["hint"])
        for e in (out.get("result") or {}).get("errors", []):
            print(f"  {e.get('code')}: {e.get('message')}")
        for c in out.get("checks", []):
            print(f"  {'ok  ' if c['ok'] else 'FAIL'} {c['expect']}  (got {json.dumps(c['actual'], ensure_ascii=False)})")
        for d in out.get("diff", []):
            print(f"  diff {json.dumps(d, ensure_ascii=False)}")
        if out.get("fault"):
            print(f"  fault: {out['fault']}")
    return EXIT.get(reason, 1)


MODULE = Module(name="loop", summary="run a Unity Editor command safely: wait until ready, run, wait again, one digest",
                add_args=_add_args, run=_run, engines=("unity",))
