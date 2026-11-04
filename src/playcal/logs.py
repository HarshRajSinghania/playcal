"""playcal logs: boil a Unity Editor.log (or Player.log, or any pasted console text) down to what an agent needs.

Compile errors and exceptions are collapsed: the same error a thousand times is one entry with
count 1000. The first cause is pulled out on its own, because later errors are usually fallout.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from .registry import Module

COMPILE = re.compile(r"^(?P<file>[^\s(][^(]*?)\((?P<line>\d+),(?P<col>\d+)\): (?P<level>error|warning) (?P<code>[A-Z]+\d+): (?P<msg>.*)$")
EXCEPTION = re.compile(r"^(?P<type>[A-Za-z_][\w.]*(?:Exception|Error)): ?(?P<msg>.*)$")
AT = re.compile(r"\(at (?P<file>[^:)]+(?::[^:)]+)?):(?P<line>\d+)\)")
LOG_ERROR = re.compile(r"^UnityEngine\.Debug:Log(?:Error|Exception)")


def default_log() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", "~")) / "Unity" / "Editor" / "Editor.log"
    if sys.platform == "darwin":
        return Path("~/Library/Logs/Unity/Editor.log").expanduser()
    return Path("~/.config/unity3d/Editor.log").expanduser()


def summarize(lines: list[str], limit: int = 20) -> dict:
    found: dict[tuple, dict] = {}
    order: list[tuple] = []
    warnings: dict[tuple, int] = {}

    def add(key, entry, n):
        if key in found:
            found[key]["count"] += 1
        else:
            found[key] = {**entry, "count": 1, "first_line": n}
            order.append(key)

    for n, raw in enumerate(lines, 1):
        line = raw.rstrip("\r\n")
        m = COMPILE.match(line.strip())
        if m:
            if m["level"] == "warning":
                k = (m["file"], m["line"], m["code"])
                warnings[k] = warnings.get(k, 0) + 1
                continue
            entry = {"kind": "compile", "code": m["code"], "file": m["file"].replace("\\", "/"),
                     "line": int(m["line"]), "message": m["msg"].strip()}
            add(("compile", entry["code"], entry["file"], entry["line"], entry["message"]), entry, n)
            continue
        m = EXCEPTION.match(line)
        if m and not line.startswith(" "):
            where = _where(lines, n)
            entry = {"kind": "exception", "code": m["type"].rsplit(".", 1)[-1], "message": m["msg"].strip(), **where}
            add(("exception", entry["code"], entry["message"], where.get("file"), where.get("line")), entry, n)
            continue
        if LOG_ERROR.match(line) and n >= 2:
            msg = lines[n - 2].strip()
            if msg and not EXCEPTION.match(msg) and not COMPILE.match(msg):
                where = _where(lines, n - 1)
                entry = {"kind": "log_error", "code": "LogError", "message": msg[:300], **where}
                add(("log_error", msg, where.get("file"), where.get("line")), entry, n - 1)

    entries = [found[k] for k in order]
    compile_errors = [e for e in entries if e["kind"] == "compile"]
    first = compile_errors[0] if compile_errors else entries[0] if entries else None
    out = {"ok": not entries, "lines_read": len(lines), "first_cause": first,
           "errors": entries[:limit], "error_kinds": len(entries),
           "error_total": sum(e["count"] for e in entries), "warnings": sum(warnings.values()),
           "warning_kinds": len(warnings)}
    if len(entries) > limit:
        out["truncated"] = len(entries) - limit
    return out


def _where(lines: list[str], n: int) -> dict:
    """Where the error came from: the first `(at File.cs:12)` frame under line n (1-based),
    preferring the project's own code (Assets/, Packages/) over engine frames."""
    frames = []
    for raw in lines[n: n + 15]:
        if not raw.strip():
            break
        m = AT.search(raw)
        if m:
            frames.append({"file": m["file"].replace("\\", "/"), "line": int(m["line"])})
    own = [f for f in frames if f["file"].startswith(("Assets/", "Packages/"))]
    return (own or frames or [{}])[0]


def since(lines: list[str], marker: str | None) -> list[str]:
    """Lines after the last line that contains `marker` (whole log if it never appears)."""
    if not marker:
        return lines
    for i in range(len(lines) - 1, -1, -1):
        if marker in lines[i]:
            return lines[i + 1:]
    return lines


def _add_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("path", nargs="?", help="log file, or - for stdin (default: this machine's Unity Editor.log)")
    p.add_argument("--since", metavar="TEXT", help='only read after the last line containing TEXT, e.g. "Reloading assemblies"')
    p.add_argument("--limit", type=int, default=20, help="most distinct errors to list (default 20)")
    p.add_argument("--json", action="store_true", help="print the summary as JSON")


def _run(args: argparse.Namespace) -> int:
    if args.path == "-":
        lines = sys.stdin.read().splitlines()
    else:
        path = Path(args.path) if args.path else default_log()
        if not path.exists():
            print(f"playcal logs: {path} not found", file=sys.stderr)
            return 2
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    out = summarize(since(lines, args.since), args.limit)
    if args.json:
        print(json.dumps(out, ensure_ascii=False))
        return 0 if out["ok"] else 1
    if out["ok"]:
        print(f"no errors in {out['lines_read']} lines ({out['warnings']} warnings)")
        return 0
    f = out["first_cause"]
    print(f"first cause: {_fmt(f)}")
    print(f"{out['error_kinds']} distinct errors, {out['error_total']} total, {out['warnings']} warnings")
    for e in out["errors"]:
        print(f"  {e['count']:>5}x {_fmt(e)}")
    if "truncated" in out:
        print(f"  ... {out['truncated']} more (raise --limit)")
    return 1


def _fmt(e: dict) -> str:
    where = f"{e['file']}:{e['line']} " if e.get("file") else ""
    return f"{where}{e['code']}: {e['message']}"


MODULE = Module(name="logs", summary="summarize a Unity log: collapse repeats, show the first cause",
                add_args=_add_args, run=_run, engines=("unity",))
