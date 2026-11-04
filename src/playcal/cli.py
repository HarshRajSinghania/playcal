from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .registry import load_modules


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="playcal", description="playcal: one toolkit for AI agents building games.")
    p.add_argument("--version", action="version", version=f"playcal {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    m = sub.add_parser("modules", help="list installed modules")
    m.add_argument("--json", action="store_true")
    m.set_defaults(func=_list_modules)

    for mod in load_modules():
        sp = sub.add_parser(mod.name, help=mod.summary, description=mod.summary)
        mod.add_args(sp)
        sp.set_defaults(func=mod.run)
    return p


def _list_modules(args: argparse.Namespace) -> int:
    mods = load_modules()
    if args.json:
        print(json.dumps([{"name": m.name, "summary": m.summary, "engines": list(m.engines)} for m in mods]))
    else:
        for m in mods:
            print(f"{m.name:12} {m.summary}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
