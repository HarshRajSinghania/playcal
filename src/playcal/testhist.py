"""playcal tests: keep a history of test results and tell a flaky failure from a real one.

Reads Unity Test Framework results (NUnit3 XML, what `-testResults` writes) and JUnit XML. A test
is flaky when it both passed and failed on the same commit. `check` fails CI only on failures of
tests that aren't flaky, and lists the flaky ones as quarantined instead of hiding them.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Any

from . import affected
from .registry import Module

NUNIT = {"passed": "pass", "failed": "fail", "skipped": "skip", "inconclusive": "skip", "ignored": "skip"}


class TestsError(Exception):
    pass


def parse(path: str | Path) -> list[dict]:
    """[{test, outcome: pass|fail|skip, seconds}] from an NUnit3 or JUnit file."""
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as e:
        raise TestsError(f"{path}: not XML ({e})") from None
    out = []
    for tc in root.iter("test-case"):  # NUnit3
        name = tc.get("fullname") or tc.get("name")
        out.append({"test": name, "outcome": NUNIT.get((tc.get("result") or "").lower(), "skip"),
                    "seconds": float(tc.get("duration") or 0)})
    for tc in root.iter("testcase"):  # JUnit
        cls, name = tc.get("classname"), tc.get("name")
        kids = {c.tag for c in tc}
        outcome = "fail" if kids & {"failure", "error"} else "skip" if "skipped" in kids else "pass"
        out.append({"test": f"{cls}.{name}" if cls else name, "outcome": outcome,
                    "seconds": float(tc.get("time") or 0)})
    if not out:
        raise TestsError(f"{path}: no test-case (NUnit3) or testcase (JUnit) elements")
    return out


def head_commit() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10)
        return r.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def history(folder: Path) -> list[dict]:
    f = folder / "history.jsonl"
    if not f.exists():
        return []
    return [json.loads(ln) for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]


def record(folder: Path, results: list[dict], commit: str) -> int:
    folder.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    rows = [{"ts": ts, "commit": commit, "test": r["test"], "outcome": r["outcome"]}
            for r in results if r["outcome"] != "skip"]
    with (folder / "history.jsonl").open("a", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    return len(rows)


def flaky(rows: list[dict]) -> dict[str, dict]:
    """Tests that passed and failed on the same commit, with their run and fail counts."""
    seen: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    runs: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in rows:
        seen[r["test"]][r["commit"]].add(r["outcome"])
        runs[r["test"]][0] += 1
        runs[r["test"]][1] += r["outcome"] == "fail"
    out = {}
    for test, commits in seen.items():
        mixed = [c for c, o in commits.items() if {"pass", "fail"} <= o]
        if mixed:
            n, fails = runs[test]
            out[test] = {"runs": n, "fails": fails, "fail_rate": round(fails / n, 3), "commits": len(mixed)}
    return dict(sorted(out.items(), key=lambda kv: -kv[1]["fail_rate"]))


def check(folder: Path, results: list[dict]) -> dict:
    known = flaky(history(folder))
    failed = [r["test"] for r in results if r["outcome"] == "fail"]
    new = [t for t in failed if t not in known]
    return {"ok": not new, "passed": sum(r["outcome"] == "pass" for r in results), "failed": new,
            "quarantined": [t for t in failed if t in known], "flaky_known": len(known)}


def _add_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("action", choices=["record", "check", "flaky", "affected"],
                   help="record FILE...: add results to the history. check FILE...: fail only on non-flaky "
                        "failures, then record. flaky: list tests that passed and failed on one commit. "
                        "affected [PATH...]: test assemblies a change can break (default: git diff --base)")
    p.add_argument("files", nargs="*", help="NUnit3 (Unity -testResults) or JUnit XML files; for affected, changed paths")
    p.add_argument("--base", default="HEAD", help="affected: git ref to diff against (default HEAD: uncommitted work)")
    p.add_argument("--project", default=".", help="affected: Unity project folder (default .)")
    p.add_argument("--commit", help="commit the run belongs to (default: git rev-parse HEAD)")
    p.add_argument("--dir", default=".playcal/tests", help="where the history lives (default .playcal/tests)")
    p.add_argument("--no-record", action="store_true", help="check without adding this run to the history")
    p.add_argument("--json", action="store_true", help="print the result as JSON")


def _run(args: argparse.Namespace) -> int:
    folder = Path(args.dir)
    out: Any
    try:
        if args.action == "flaky":
            out = flaky(history(folder))
        elif args.action == "affected":
            root = Path(args.project)
            if not (root / "Assets").is_dir():
                raise TestsError(f"{root}: no Assets folder, pass --project")
            out = affected.affected(root, args.files or affected.changed_files(root, args.base))
        else:
            if not args.files:
                raise TestsError(f"{args.action} needs at least one results file")
            results = [r for f in args.files for r in parse(f)]
            commit = args.commit or head_commit()
            if args.action == "check":
                out = check(folder, results)  # judge against the history before this run joins it
                if not args.no_record:
                    out["recorded"] = record(folder, results, commit)
            else:
                out = {"recorded": record(folder, results, commit), "commit": commit}
    except (TestsError, OSError, ValueError) as e:
        print(f"playcal tests: {e}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(out, ensure_ascii=False))
    elif args.action == "affected":
        for p in out["unmapped"]:
            print(f"can't trace {p}: run every test")
        names = out["all_tests"] if out["run_all"] else out["assemblies"]
        if names:
            print('-runTests -assemblyNames "' + ";".join(names) + '"')
        else:
            print("no test assembly depends on this change")
    elif args.action == "flaky":
        for t, s in out.items():
            print(f"{t}: failed {s['fails']} of {s['runs']} runs, mixed on {s['commits']} commit(s)")
        print(f"{len(out)} flaky test(s)")
    elif args.action == "check":
        for t in out["failed"]:
            print(f"FAIL {t}")
        for t in out["quarantined"]:
            print(f"flaky {t} (known flaky, not failing the run)")
        print(f"{out['passed']} passed, {len(out['failed'])} failed, {len(out['quarantined'])} quarantined")
    else:
        print(f"recorded {out['recorded']} results for {out['commit'][:12]}")
    return 1 if args.action == "check" and not out["ok"] else 0


MODULE = Module(name="tests", summary="test result history: spot flaky tests, fail CI only on real failures, run only affected test assemblies",
                add_args=_add_args, run=_run)
