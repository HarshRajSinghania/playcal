"""playcal observe: press Play, let the game run a few seconds, and report one digest of what changed
in the scene and what went wrong. A screenshot is taken only when something went red.

  1. settle, read the scene (default `scene get_hierarchy`), mark the console cursor
  2. enter Play Mode and settle again (entering Play reloads the domain: ~30 s on a small project)
  3. wait --seconds, read the scene again, pull the console errors logged since the mark
  4. --expect checks run on the second read
  5. red (errors, a failed check, a failed read) -> `capture game_view` into --shots
  6. leave Play Mode, diff the two reads with snap's rules (instanceIds left out)

The scene diff is reported, not gated on: a running game is supposed to change. Gate on it with
--expect. If the Editor is already in Play Mode, observe watches it for --seconds and leaves it running.
"""
from __future__ import annotations

import argparse
import json
import shlex
import time
from typing import Callable, Sequence

from . import checks, logs, loop, snap
from .registry import Module

EXIT = {"clean": 0, "errors": 1, "expect_failed": 1, "read_failed": 1, "play_failed": 1}


def _console_mark(runner, project) -> dict | None:
    res = loop._call(runner, ["console", "status"], project)
    r = ((res["data"] or {}).get("result") or {}) if res["success"] else {}
    return {"cursor": r["cursor"], "session": r.get("session")} if "cursor" in r else None


def _console_since(runner, project, mark: dict, limit: int) -> dict:
    argv = ["console", "get", "--level", "error", "--since", str(mark["cursor"])]
    if mark.get("session"):
        argv += ["--since-session", mark["session"]]
    res = loop._call(runner, argv, project)
    if not res["success"]:
        return {"read": False, "errors_seen": None, "problem": res["errors"]}
    r = (res["data"] or {}).get("result") or {}
    entries = r.get("entries") or []
    lines = [ln for e in entries for ln in [str(e.get("message", "")), *str(e.get("stackTrace") or "").splitlines()]]
    out = {"read": True, "errors_seen": len(entries), **logs.summarize(lines, limit)}
    out.pop("lines_read", None)
    for flag in ("dropped", "reset"):  # buffer overflowed, or the console was cleared mid-run
        if r.get(flag):
            out[flag] = True
    return out


def _playing(runner, project) -> bool:
    res = loop._call(runner, ["editor", "status"], project)
    return ((res["data"] or {}).get("result") or {}).get("playMode") == "playing" if res["success"] else False


def observe(runner, project: str | None = None, read: Sequence[str] = ("scene", "get_hierarchy"), seconds: float = 3,
            play: bool = True, expect: Sequence[str] = (), shots: str | None = ".playcal/observe", name: str = "observe",
            timeout: float = 120, ignore=snap.VOLATILE, limit: int = 50,
            sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> dict:
    t0 = clock()
    d: dict = {"read": list(read), "seconds": seconds,
               "before": loop.settle(runner, project, timeout, sleep=sleep, clock=clock)}

    def done(reason: str, result=None) -> dict:
        d["ok"], d["reason"] = reason == "clean", reason
        # our own reasons are the game's fault unless the CLI itself broke; settle's keep loop's verdict
        d["fault"] = (None if reason == "clean" else
                      loop._fault("command_failed" if reason in EXIT else reason, result))
        d["elapsed_ms"] = round((clock() - t0) * 1000)
        return d

    if not d["before"]["settled"]:
        return done(d["before"]["reason"])
    first = loop._call(runner, list(read), project)
    if not first["success"]:
        d["read_errors"] = first["errors"]
        return done("read_failed", first)
    mark = _console_mark(runner, project)
    started = False
    if play and not _playing(runner, project):
        res = loop._call(runner, ["editor.playmode", "start"], project)
        if not res["success"]:
            d["play_errors"] = res["errors"]
            return done("play_failed", res)
        started = True
        d["entered_play"] = loop.settle(runner, project, timeout, await_gone=10, sleep=sleep, clock=clock)
        if not d["entered_play"]["settled"]:
            return done(d["entered_play"]["reason"])
    sleep(seconds)

    second = loop._call(runner, list(read), project)
    d["console"] = _console_since(runner, project, mark, 20) if mark else {"read": False, "errors_seen": None}
    d["checks"] = [checks.check(second["data"], e) for e in expect] if second["success"] else []
    reason = ("read_failed" if not second["success"] else "errors" if d["console"].get("errors_seen")
              else "expect_failed" if not all(c["ok"] for c in d["checks"]) else "clean")
    if not second["success"]:
        d["read_errors"] = second["errors"]
    if reason != "clean" and shots:
        cap = loop._call(runner, ["capture", "game_view", "--output-path", f"{shots.rstrip('/')}/{name}.png"], project)
        res = (cap["data"] or {}).get("result") or {}
        d["shot"] = res.get("savedPath") if cap["success"] else {"failed": cap["errors"]}
    if started:
        res = loop._call(runner, ["editor.playmode", "stop"], project)
        d["left_play"] = res["success"] and loop.settle(runner, project, timeout, sleep=sleep, clock=clock)["settled"]
    if second["success"]:
        d["diff"] = snap.compare(first["data"], second["data"], ignore, limit)
    return done(reason, second)


def _add_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--read", default="scene get_hierarchy", metavar="CMD",
                   help='Editor read to diff before and during play (default "scene get_hierarchy")')
    p.add_argument("--seconds", type=float, default=3, help="how long to let the game run before the second read (default 3)")
    p.add_argument("--no-play", action="store_true", help="don't touch Play Mode; diff two reads --seconds apart")
    p.add_argument("--expect", action="append", default=[], metavar="PATH=VALUE",
                   help="check on the read during play, same syntax as playcal loop --expect. Repeatable")
    p.add_argument("--shots", default=".playcal/observe", metavar="DIR",
                   help="where the red-run screenshot goes, relative to the Unity project (default .playcal/observe)")
    p.add_argument("--name", default="observe", help="screenshot file name without .png (default observe)")
    p.add_argument("--no-shot", action="store_true", help="never take a screenshot")
    p.add_argument("--ignore", action="append", default=None, metavar="KEY",
                   help="field to leave out of the diff, repeatable (default: instanceId, isDirty)")
    p.add_argument("--limit", type=int, default=50, help="most diff entries to list (default 50)")
    p.add_argument("--project-path", help="Unity project folder; needed when several Editors are open")
    p.add_argument("--timeout", type=float, default=120, help="seconds to wait for a ready Editor (default 120)")
    p.add_argument("--json", action="store_true", help="print the digest as JSON")


def _run(args: argparse.Namespace) -> int:
    ignore = snap.VOLATILE if args.ignore is None else [k for k in args.ignore if k]
    out = observe(loop.unity_runner, args.project_path, shlex.split(args.read), args.seconds, not args.no_play,
                  args.expect, None if args.no_shot else args.shots, args.name, args.timeout, ignore, args.limit)
    if args.json:
        print(json.dumps(out, ensure_ascii=False))
    else:
        con = out.get("console") or {}
        print(f"{out['reason']}" + (f" ({out['fault']})" if out["fault"] else ""))
        for e in con.get("errors") or []:
            print(f"  {e.get('code')}: {e.get('message')}" + (f"  at {e['file']}:{e.get('line')}" if e.get("file") else "")
                  + (f"  x{e['count']}" if e.get("count", 1) > 1 else ""))
        if con.get("errors_seen") and not con.get("errors"):
            print(f"  {con['errors_seen']} console errors (none matched a known shape; see the Console)")
        for c in out.get("checks", []):
            print(f"  {'ok  ' if c['ok'] else 'FAIL'} {c['expect']}  (got {json.dumps(c['actual'], ensure_ascii=False)})")
        for e in out.get("read_errors", []) + out.get("play_errors", []):
            print(f"  {e.get('code')}: {e.get('message')}")
        if "diff" in out:
            df = out["diff"]
            print("  scene: no changes" if df["same"] else
                  f"  scene: {df['added']} added, {df['removed']} removed, {df['changed']} changed")
        if out.get("shot"):
            print(f"  shot: {out['shot']}")
        if "hint" in out.get("before", {}):
            print(f"  {out['before']['hint']}")
    return EXIT.get(out["reason"], loop.EXIT.get(out["reason"], 1))


MODULE = Module(name="observe", summary="press Play, run the game a few seconds, diff the scene and collect console errors; screenshot only on red",
                add_args=_add_args, run=_run, engines=("unity",))
