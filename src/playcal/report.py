"""playcal report: per-level pass rates from gameplay events, with Wilson confidence intervals.

Small panels give wide intervals. The report prints them instead of hiding them."""
from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from .ingest import check_lines
from .registry import Module

TERMINAL = {"level_complete": "pass", "level_fail": "fail", "level_quit": "quit"}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for k successes out of n. (0, 1) when n == 0."""
    if n == 0:
        return 0.0, 1.0
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


@dataclass
class LevelStats:
    game_version: str
    level: str
    players: int
    players_passed: int
    player_pass_rate: float
    player_pass_ci: tuple[float, float]
    attempts: int
    attempts_passed: int
    attempt_pass_rate: float
    attempt_pass_ci: tuple[float, float]
    quit_rate: float
    median_attempts_to_pass: float | None
    unfinished_attempts: int


def _level_sort_key(key: tuple[str, str]) -> tuple:
    version, level = key
    return (version, [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", level)])


def summarize(events: Iterable[dict]) -> list[LevelStats]:
    # (version, level) -> install_id -> attempt -> (ts, outcome or None)
    tree: dict[tuple[str, str], dict[str, dict[int, tuple[str, str | None]]]] = defaultdict(lambda: defaultdict(dict))
    for ev in events:
        if "level" not in ev:
            continue
        key = (ev["game_version"], ev["level"])
        attempts = tree[key][ev["install_id"]]
        outcome = TERMINAL.get(ev["type"])
        prev = attempts.get(ev["attempt"])
        if outcome is None:
            attempts.setdefault(ev["attempt"], (ev["ts"], None))
        elif prev is None or prev[1] is None or ev["ts"] >= prev[0]:
            attempts[ev["attempt"]] = (ev["ts"], outcome)  # last terminal event wins

    out = []
    for key in sorted(tree, key=_level_sort_key):
        players = tree[key]
        n_att = k_att = quits = unfinished = passed_players = 0
        to_pass = []
        for attempts in players.values():
            done = sorted((ts, o) for ts, o in attempts.values() if o is not None)
            unfinished += sum(1 for _, o in attempts.values() if o is None)
            n_att += len(done)
            k_att += sum(o == "pass" for _, o in done)
            quits += sum(o == "quit" for _, o in done)
            first = next((i for i, (_, o) in enumerate(done, 1) if o == "pass"), None)
            if first is not None:
                passed_players += 1
                to_pass.append(first)
        n_pl = len(players)
        out.append(LevelStats(
            game_version=key[0], level=key[1],
            players=n_pl, players_passed=passed_players,
            player_pass_rate=passed_players / n_pl if n_pl else 0.0, player_pass_ci=wilson(passed_players, n_pl),
            attempts=n_att, attempts_passed=k_att,
            attempt_pass_rate=k_att / n_att if n_att else 0.0, attempt_pass_ci=wilson(k_att, n_att),
            quit_rate=quits / n_att if n_att else 0.0,
            median_attempts_to_pass=statistics.median(to_pass) if to_pass else None,
            unfinished_attempts=unfinished,
        ))
    return out


def _pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def _add_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("files", nargs="+", help="event JSONL files (usually accepted.jsonl from ingest)")
    p.add_argument("--json", action="store_true", help="print JSON instead of a table")


def _run(args: argparse.Namespace) -> int:
    try:
        lines = [(f, line) for f in args.files for line in Path(f).read_text(encoding="utf-8").splitlines()]
    except OSError as e:
        print(f"playcal report: {e}", file=sys.stderr)
        return 2
    res = check_lines(lines)
    stats = summarize(res.accepted)
    if args.json:
        print(json.dumps({"skipped_invalid": len(res.rejected), "levels": [asdict(s) for s in stats]}, ensure_ascii=False))
        return 0
    if res.rejected:
        print(f"skipped {len(res.rejected)} invalid line(s); run `playcal ingest` to see why", file=sys.stderr)
    if not stats:
        print("no level events found")
        return 0
    print(f"{'version':<10} {'level':<8} {'players':>7} {'pass (players)':>22} {'pass (attempts)':>22} {'quit':>5} {'med.try':>7}")
    for s in stats:
        pl = f"{_pct(s.player_pass_rate)} [{_pct(s.player_pass_ci[0])}-{_pct(s.player_pass_ci[1])}]"
        at = f"{_pct(s.attempt_pass_rate)} [{_pct(s.attempt_pass_ci[0])}-{_pct(s.attempt_pass_ci[1])}]"
        med = "-" if s.median_attempts_to_pass is None else f"{s.median_attempts_to_pass:g}"
        print(f"{s.game_version:<10} {s.level:<8} {s.players:>7} {pl:>22} {at:>22} {_pct(s.quit_rate):>5} {med:>7}")
    print("brackets = 95% Wilson interval. With under ~10 players these are wide; read them, don't round them away.")
    return 0


MODULE = Module(name="report", summary="per-level pass rate, attempts and quit rate with 95% Wilson intervals",
                add_args=_add_args, run=_run)
