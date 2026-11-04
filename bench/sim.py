"""Simulated benchmark: a naive agent vs playcal loop against a scripted Editor.

This is NOT a measurement of Unity. It replays failure modes people report (a write sent during a
domain reload is lost, a command says success and does nothing, Safe Mode after a compile error)
so we can see whether loop catches them, and keep it that way as the code changes. The real
benchmark runs against a live Editor.

    python bench/sim.py          # table
    python bench/sim.py --json
"""
from __future__ import annotations

import json
import sys

from playcal import loop

PROJECT = "C:/Games/Lab"


class SimEditor:
    """A runner (argv -> (exit code, envelope)) with a timeline. Every call is one tick.
    `states[i]` is the Editor state at tick i (the last one repeats). A write that arrives
    while the Editor isn't ready is dropped but still reports success, like a reload eating it.
    Envelopes follow a live Unity 6000.3 Editor with Pipeline 0.10.0-exp.1: while it compiles or
    reloads, `unity status` lists no instance at all; `pipeline list` says projectPath."""

    def __init__(self, states, noop=False, safe_mode=False, dialog=False):
        self.states, self.noop, self.safe_mode, self.dialog = states, noop, safe_mode, dialog
        self.tick, self.objects = 0, ["Main Camera"]

    def state(self):
        return self.states[min(self.tick, len(self.states) - 1)]

    def __call__(self, args):
        s = self.state()
        self.tick += 1
        if args[0] == "status":
            if self.safe_mode or self.dialog or s != "ready":
                return 6, {"success": False, "errors": [{"code": "STATUS_NO_INSTANCES"}], "data": {"instances": []}}
            return 0, {"success": True, "data": {"instances": [{"project": PROJECT, "state": "ready"}]}}
        if args[0] == "pipeline":
            return 0, {"data": {"instances": [{"projectPath": PROJECT, "isRunning": True, "hasPipelinePackage": True,
                                               "safeMode": {"detected": True} if self.safe_mode else None,
                                               "pipelineServer": {"isReachable": not self.dialog}}]}}
        name = args[1]
        if self.dialog:
            return 6, {"success": False, "errors": [{"code": "COMMAND_FAILED", "message": "No Pipeline instance found"}]}
        if self.safe_mode:
            return 1, {"success": False, "errors": [{"code": "UNITY_CLI_NO_INSTANCE", "message": "no editor"}]}
        if name == "get_hierarchy":
            return 0, {"success": True, "data": {"objects": [{"name": n} for n in self.objects]}}
        if name == "create_gameobject":
            if s == "ready" and not self.noop:
                self.objects.append(args[args.index("--name") + 1])
            return 0, {"success": True, "data": {}}
        return 1, {"success": False, "errors": [{"code": "UNKNOWN_COMMAND"}]}


SCENARIOS = {
    "clean": dict(states=["ready"]),
    "reload_during_write": dict(states=["compiling", "compiling", "reloading", "ready"]),
    "ready_flicker": dict(states=["compiling", "ready", "reloading", "ready"]),
    "compile_storm": dict(states=["compiling"] * 40 + ["ready"]),
    "silent_noop": dict(states=["ready"], noop=True),
    "safe_mode": dict(states=["ready"], safe_mode=True),
    "dialog_blocked": dict(states=["ready"], dialog=True),
}

WRITE = ["create_gameobject", "--name", "Probe"]


def naive(ed: SimEditor) -> dict:
    """What an agent does with the plain CLI: fire the command, trust `success`."""
    _, env = ed(["command", *WRITE, "--project-path", PROJECT])
    errors: list = env.get("errors") or [{}]
    return {"reported_ok": bool(env.get("success")), "said": errors[0].get("code", "ok")}


def playcal(ed: SimEditor) -> dict:
    t = {"now": 0.0}

    def sleep(s):
        t["now"] += s

    out = loop.run_command(ed, WRITE[0], WRITE[1:], project=PROJECT, timeout=60, verify=["get_hierarchy"],
                           expect=["objects.*.name=Probe"], sleep=sleep, clock=lambda: t["now"])
    return {"reported_ok": out["ok"], "said": f"{out['reason']}/{out['fault']}" if out["fault"] else out["reason"]}


def run() -> list[dict]:
    rows = []
    for name, cfg in SCENARIOS.items():
        for agent, fn in (("naive", naive), ("playcal", playcal)):
            ed = SimEditor(**cfg)
            r = fn(ed)
            landed = "Probe" in ed.objects
            rows.append({"scenario": name, "agent": agent, "landed": landed, "reported_ok": r["reported_ok"],
                         "false_success": r["reported_ok"] and not landed, "said": r["said"], "calls": ed.tick})
    return rows


def main(argv=None) -> int:
    rows = run()
    if "--json" in (argv or sys.argv[1:]):
        print(json.dumps(rows))
        return 0
    print(f"{'scenario':<22}{'agent':<9}{'landed':<8}{'said ok':<9}{'FALSE OK':<10}{'calls':<7}said")
    for r in rows:
        print(f"{r['scenario']:<22}{r['agent']:<9}{str(r['landed']):<8}{str(r['reported_ok']):<9}"
              f"{'YES' if r['false_success'] else '-':<10}{r['calls']:<7}{r['said']}")
    for agent in ("naive", "playcal"):
        n = sum(r["false_success"] for r in rows if r["agent"] == agent)
        print(f"{agent}: {n} false successes out of {len(SCENARIOS)} scenarios")
    return 0


if __name__ == "__main__":
    sys.exit(main())
