"""playcal baseline: keep a perf baseline (frame time, GC allocation, any per-frame number) and fail
only when a new run is slower by more than noise.

Input is per-frame samples: {"frame_ms": [...], "gc_alloc_bytes": [...]}, or a bare list (taken as
frame_ms). check compares a percentile (p95 by default) and bootstraps the difference: it fails only
when even the low end of the 95% interval is past the tolerance. One hitchy run on a busy machine
then shows up as "inconclusive", not as a red build.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from pathlib import Path
from typing import Any

from .registry import Module

ROUNDS = 400


class BaselineError(Exception):
    pass


def samples(doc) -> dict[str, list[float]]:
    if isinstance(doc, list):
        doc = {"frame_ms": doc}
    if not isinstance(doc, dict):
        raise BaselineError("samples must be a list of numbers or {metric: [numbers]}")
    out = {}
    for k, v in doc.items():
        if isinstance(v, list) and v and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v):
            out[k] = [float(x) for x in v]
    if not out:
        raise BaselineError("no metric with a list of numbers found")
    return out


def pct(xs: list[float], q: float) -> float:
    s = sorted(xs)
    i = (len(s) - 1) * q / 100
    lo = int(i)
    return s[lo] + (s[min(lo + 1, len(s) - 1)] - s[lo]) * (i - lo)


def stats(xs: list[float]) -> dict:
    return {"n": len(xs), "mean": round(sum(xs) / len(xs), 4), "p50": round(pct(xs, 50), 4),
            "p95": round(pct(xs, 95), 4), "p99": round(pct(xs, 99), 4), "max": max(xs)}


def compare(base: list[float], new: list[float], q: float = 95, tolerance: float = 0.10,
            floor: float = 0.0, rounds: int = ROUNDS, seed: int = 0) -> dict:
    """Relative change of the q-th percentile with a bootstrap 95% interval.
    verdict: "slower" (interval's low end > tolerance and the absolute change > floor),
    "faster", "same" (interval inside ±tolerance), or "inconclusive"."""
    b0, n0 = pct(base, q), pct(new, q)
    rng = random.Random(seed)
    rel = sorted((pct(rng.choices(new, k=len(new)), q) - pct(rng.choices(base, k=len(base)), q)) / (b0 or 1)
                 for _ in range(rounds))
    lo, hi = rel[int(rounds * 0.025)], rel[int(rounds * 0.975) - 1]
    change = (n0 - b0) / (b0 or 1)
    if lo > tolerance and n0 - b0 > floor:
        verdict = "slower"
    elif hi < -tolerance:
        verdict = "faster"
    elif -tolerance <= lo and hi <= tolerance:
        verdict = "same"
    else:
        verdict = "inconclusive"
    return {"verdict": verdict, f"p{q:g}_base": round(b0, 4), f"p{q:g}_new": round(n0, 4),
            "change": round(change, 4), "ci95": [round(lo, 4), round(hi, 4)]}


def _file(folder: Path, name: str) -> Path:
    if not re.fullmatch(r"[\w.-]+", name):
        raise BaselineError(f"baseline names are letters, digits, . _ - only: {name!r}")
    return folder / f"{name}.json"


def _read(src: str):
    text = sys.stdin.read() if src == "-" else Path(src).read_text(encoding="utf-8")
    return samples(json.loads(text))


def save(folder: Path, name: str, data: dict[str, list[float]], source: str) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    doc = {"source": source, "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "stats": {k: stats(v) for k, v in data.items()}, "samples": data}
    _file(folder, name).write_text(json.dumps(doc), encoding="utf-8")
    return {"name": name, "stats": doc["stats"]}


def check(folder: Path, name: str, data: dict[str, list[float]], q: float, tolerance: float,
          floors: dict[str, float], metrics: list[str] | None = None) -> dict:
    path = _file(folder, name)
    if not path.exists():
        raise BaselineError(f"no baseline {name!r} in {folder}; make one with: playcal baseline save {name} FILE")
    base = json.loads(path.read_text(encoding="utf-8"))["samples"]
    results, missing = {}, []
    for m in metrics or sorted(set(base) & set(data)):
        if m not in base or m not in data:
            missing.append(m)
            continue
        results[m] = compare(base[m], data[m], q, tolerance, floors.get(m, 0.0))
        results[m]["n"] = [len(base[m]), len(data[m])]
    if not results:
        raise BaselineError(f"no metric in both the baseline and the new run (asked for {metrics or 'all'})")
    verdicts = {r["verdict"] for r in results.values()}
    return {"ok": "slower" not in verdicts, "verdict": "slower" if "slower" in verdicts else
            "inconclusive" if "inconclusive" in verdicts else "same_or_faster",
            "metrics": results, **({"missing": missing} if missing else {})}


def _floor(spec: str) -> tuple[str, float]:
    k, sep, v = spec.partition("=")
    if not sep:
        raise argparse.ArgumentTypeError("--floor is METRIC=VALUE, e.g. frame_ms=0.5")
    return k, float(v)


def _add_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("action", choices=["save", "check", "show"],
                   help="save NAME FILE: keep a run as the baseline. check NAME FILE: compare a new run. show NAME")
    p.add_argument("name", help="baseline name, e.g. level4-android")
    p.add_argument("source", nargs="?", default="-", help="samples JSON file, or - for stdin (default)")
    p.add_argument("--dir", default=".playcal/baselines", help="where baselines live (default .playcal/baselines)")
    p.add_argument("--percentile", type=float, default=95, help="percentile to compare (default 95)")
    p.add_argument("--tolerance", type=float, default=10, help="allowed slowdown in percent (default 10)")
    p.add_argument("--floor", type=_floor, action="append", default=[], metavar="METRIC=VALUE",
                   help="ignore slowdowns smaller than this in absolute units, e.g. frame_ms=0.5. Repeatable")
    p.add_argument("--metric", action="append", default=None, help="only these metrics (default: all in both)")
    p.add_argument("--json", action="store_true", help="print the result as JSON")


def _run(args: argparse.Namespace) -> int:
    folder = Path(args.dir)
    out: Any
    try:
        if args.action == "show":
            path = _file(folder, args.name)
            if not path.exists():
                raise BaselineError(f"no baseline {args.name!r} in {folder}")
            doc = json.loads(path.read_text(encoding="utf-8"))
            out = {"name": args.name, "source": doc["source"], "saved_at": doc["saved_at"], "stats": doc["stats"]}
        elif args.action == "save":
            out = save(folder, args.name, _read(args.source), args.source)
        else:
            out = check(folder, args.name, _read(args.source), args.percentile, args.tolerance / 100,
                        dict(args.floor), args.metric)
    except (BaselineError, OSError, json.JSONDecodeError) as e:
        print(f"playcal baseline: {e}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(out, ensure_ascii=False))
    elif args.action == "check":
        for m, r in out["metrics"].items():
            q = f"p{args.percentile:g}"
            print(f"{m}: {r['verdict']}  {q} {r[q + '_base']} -> {r[q + '_new']} ({r['change']:+.1%}, "
                  f"95% CI {r['ci95'][0]:+.1%} .. {r['ci95'][1]:+.1%})")
        print("ok" if out["ok"] else "slower than the baseline")
    else:
        for m, s in out["stats"].items():
            print(f"{m}: n={s['n']} p50={s['p50']} p95={s['p95']} p99={s['p99']} max={s['max']}")
    return 0 if args.action != "check" or out["ok"] else 1


MODULE = Module(name="baseline", summary="keep a perf baseline (p95 frame time, GC) and fail only when a run is slower by more than noise",
                add_args=_add_args, run=_run)
