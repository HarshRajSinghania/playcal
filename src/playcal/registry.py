"""Module registry. Every playcal feature is a module; the CLI (and later the
MCP server and SKILL.md) are generated from this one list."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Callable

ENTRY_POINT_GROUP = "playcal.modules"


@dataclass(frozen=True)
class Module:
    name: str
    summary: str
    add_args: Callable[[argparse.ArgumentParser], None]
    run: Callable[[argparse.Namespace], int]
    engines: tuple[str, ...] = ("any",)


def load_modules() -> list[Module]:
    mods: dict[str, Module] = {}
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        mod = ep.load()
        if not isinstance(mod, Module):
            raise TypeError(f"entry point {ep.name!r} must point at a playcal Module")
        if mod.name in mods:
            raise ValueError(f"two modules registered as {mod.name!r}")
        mods[mod.name] = mod
    return sorted(mods.values(), key=lambda m: m.name)
