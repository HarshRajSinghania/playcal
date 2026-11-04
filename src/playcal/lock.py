"""playcal lock: scene and asset locks so several agents (or an agent and a person) don't edit the same
file at once. A lock is a small file under .playcal/locks, created atomically; it expires after a TTL
so a crashed agent doesn't hold a scene forever.

    playcal lock take Assets/Scenes/Level4.unity --owner agent-a
    playcal lock release Assets/Scenes/Level4.unity --owner agent-a
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from .registry import Module


class LockError(Exception):
    pass


def _key(path: str) -> str:
    return path.replace("\\", "/").strip("/")


def _file(folder: Path, path: str) -> Path:
    return folder / (hashlib.sha1(_key(path).lower().encode()).hexdigest()[:16] + ".json")


def _read(f: Path) -> dict | None:
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _live(doc: dict | None, now: float) -> bool:
    return bool(doc) and doc["expires"] > now


def take(folder: Path, paths: list[str], owner: str, ttl: float, now: float | None = None) -> dict:
    """All or nothing: takes every path or none, and says who holds the ones it couldn't get."""
    now = time.time() if now is None else now
    folder.mkdir(parents=True, exist_ok=True)
    held = {}
    for p in paths:
        doc = _read(_file(folder, p))
        if doc is not None and _live(doc, now) and doc["owner"] != owner:
            held[_key(p)] = {"owner": doc["owner"], "expires_in": math.ceil(doc["expires"] - now)}
    if held:
        return {"ok": False, "held": held}
    taken = []
    for p in paths:
        f = _file(folder, p)
        doc = {"path": _key(p), "owner": owner, "taken": now, "expires": now + ttl}
        old = _read(f)
        if old is not None and (not _live(old, now) or old["owner"] == owner):
            f.unlink(missing_ok=True)  # expired, or ours: renew
        try:
            fd = os.open(f, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:  # someone took it between our check and now
            release(folder, taken, owner)
            other = _read(f) or {"owner": "?", "expires": now}
            return {"ok": False, "held": {_key(p): {"owner": other["owner"], "expires_in": math.ceil(other["expires"] - now)}}}
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(doc, out)
        taken.append(p)
    return {"ok": True, "taken": [_key(p) for p in taken], "expires_in": math.ceil(ttl)}


def release(folder: Path, paths: list[str], owner: str, force: bool = False) -> dict:
    released, not_ours = [], {}
    for p in paths:
        f = _file(folder, p)
        doc = _read(f)
        if doc is None:
            continue
        if doc["owner"] != owner and not force and _live(doc, time.time()):
            not_ours[_key(p)] = doc["owner"]
            continue
        f.unlink(missing_ok=True)
        released.append(_key(p))
    return {"ok": not not_ours, "released": released, **({"not_yours": not_ours} if not_ours else {})}


def list_(folder: Path, now: float | None = None) -> list[dict]:
    now = time.time() if now is None else now
    out = []
    for f in sorted(folder.glob("*.json")) if folder.exists() else []:
        doc = _read(f)
        if doc is not None and _live(doc, now):
            out.append({"path": doc["path"], "owner": doc["owner"], "expires_in": math.ceil(doc["expires"] - now)})
    return out


def _ttl(s: str) -> float:
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([smh]?)", s)
    if not m:
        raise argparse.ArgumentTypeError("--ttl is a number with s, m or h, e.g. 30m")
    return float(m[1]) * {"": 1, "s": 1, "m": 60, "h": 3600}[m[2]]


def _add_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("action", choices=["take", "release", "list", "check"],
                   help="take PATH...: lock all or none. release PATH...: unlock yours. list: live locks. "
                        "check PATH...: exit 1 if someone else holds one")
    p.add_argument("paths", nargs="*", help="scene or asset paths, e.g. Assets/Scenes/Level4.unity")
    p.add_argument("--owner", default=os.environ.get("PLAYCAL_OWNER", ""),
                   help="who holds the lock (default $PLAYCAL_OWNER)")
    p.add_argument("--ttl", type=_ttl, default=_ttl("30m"), help="how long a lock lasts, e.g. 90s, 30m, 2h (default 30m)")
    p.add_argument("--force", action="store_true", help="release: also drop someone else's lock")
    p.add_argument("--dir", default=".playcal/locks", help="where locks live (default .playcal/locks)")
    p.add_argument("--json", action="store_true", help="print the result as JSON")


def _run(args: argparse.Namespace) -> int:
    folder = Path(args.dir)
    out: Any
    try:
        if args.action == "list":
            out = list_(folder)
        else:
            if not args.paths:
                raise LockError(f"{args.action} needs at least one path")
            if args.action in ("take", "release") and not args.owner:
                raise LockError("say who you are: --owner NAME or PLAYCAL_OWNER")
            if args.action == "take":
                out = take(folder, args.paths, args.owner, args.ttl)
            elif args.action == "release":
                out = release(folder, args.paths, args.owner, args.force)
            else:
                live = {l["path"].lower(): l for l in list_(folder)}
                held = {_key(p): live[_key(p).lower()] for p in args.paths
                        if _key(p).lower() in live and live[_key(p).lower()]["owner"] != args.owner}
                out = {"ok": not held, "held": held}
    except (LockError, OSError) as e:
        print(f"playcal lock: {e}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(out, ensure_ascii=False))
    elif args.action == "list":
        for l in out:
            print(f"{l['path']}  {l['owner']}  {l['expires_in']}s left")
        print(f"{len(out)} lock(s)")
    else:
        for p, h in out.get("held", {}).items():
            print(f"held: {p} by {h['owner']} ({h['expires_in']}s left)")
        for p, who in out.get("not_yours", {}).items():
            print(f"not yours: {p} is held by {who}; --force drops it")
        for k in ("taken", "released"):
            for p in out.get(k, []):
                print(f"{k} {p}")
        if args.action == "check" and out["ok"]:
            print("free")
    return 0 if out is None or not isinstance(out, dict) or out["ok"] else 1


MODULE = Module(name="lock", summary="lock scenes and assets so several agents don't edit the same file at once",
                add_args=_add_args, run=_run)
