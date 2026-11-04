"""Which Unity test assemblies a change can break, from the project's .asmdef graph.

A changed .cs file belongs to the assembly of the nearest .asmdef (or .asmref) above it, or to
Assembly-CSharp / Assembly-CSharp-Editor when there is none. Every assembly that references a changed
one, directly or not, is affected; the test assemblies among them are the ones worth running.
Changes to scenes, prefabs, settings or packages can't be traced this way, so they ask for a full run.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

CODE = (".cs", ".asmdef", ".asmref")
TRACKED = ("Assets/", "Packages/", "ProjectSettings/")
PLAYER, EDITOR = "Assembly-CSharp", "Assembly-CSharp-Editor"


def _guid(f: Path) -> str | None:
    meta = f.with_name(f.name + ".meta")
    m = re.search(r"^guid:\s*(\w+)", meta.read_text(encoding="utf-8"), re.M) if meta.exists() else None
    return m[1] if m else None


def _json(f: Path) -> dict:
    try:
        return json.loads(f.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}


def _is_test(doc: dict) -> bool:
    return ("UNITY_INCLUDE_TESTS" in doc.get("defineConstraints", [])
            or "TestAssemblies" in doc.get("optionalUnityReferences", [])
            or "nunit.framework.dll" in doc.get("precompiledReferences", [])
            or "UnityEngine.TestRunner" in doc.get("references", []))


def scan(root: Path) -> tuple[dict[str, dict], dict[str, str]]:
    """({assembly: {refs, test, auto}}, {folder: assembly}) for the project's own assemblies."""
    asms: dict[str, dict] = {}
    folders: dict[str, str] = {}
    by_guid: dict[str, str] = {}
    files = [f for top in ("Assets", "Packages") for f in (root / top).rglob("*.asmdef")]
    for f in files:
        doc = _json(f)
        name = doc.get("name") or f.stem
        asms[name] = {"refs": doc.get("references", []), "test": _is_test(doc), "auto": doc.get("autoReferenced", True)}
        folders[f.parent.relative_to(root).as_posix()] = name
        if g := _guid(f):
            by_guid[g] = name
    for f in (r for top in ("Assets", "Packages") for r in (root / top).rglob("*.asmref")):
        ref = _json(f).get("reference", "")
        target = by_guid.get(ref[5:], "") if ref.startswith("GUID:") else ref
        if target:
            folders[f.parent.relative_to(root).as_posix()] = target
    for a in asms.values():
        a["refs"] = [by_guid.get(r[5:], r) if r.startswith("GUID:") else r for r in a["refs"]]
    # the predefined assemblies see every auto-referenced asmdef; the Editor one also sees the player one
    autos = [n for n, a in asms.items() if a["auto"] and not a["test"]]
    asms[PLAYER] = {"refs": autos, "test": False, "auto": False}
    asms[EDITOR] = {"refs": [*autos, PLAYER], "test": _has_tests(root, editor=True), "auto": False}
    return asms, folders


def _has_tests(root: Path, editor: bool) -> bool:
    """Tests can live in Editor folders without an asmdef; look for NUnit there."""
    for f in (root / "Assets").rglob("*.cs"):
        if editor == ("Editor" in f.relative_to(root).parts) and "NUnit.Framework" in f.read_text(encoding="utf-8", errors="ignore"):
            return True
    return False


def owner(path: str, folders: dict[str, str]) -> str:
    parts = path.split("/")
    for i in range(len(parts) - 1, 0, -1):
        if (d := "/".join(parts[:i])) in folders:
            return folders[d]
    return EDITOR if "Editor" in parts[:-1] else PLAYER


def changed_files(root: Path, base: str) -> list[str]:
    run = lambda *a: subprocess.run(["git", *a], cwd=root, capture_output=True, text=True, timeout=30)
    diff = run("diff", "--name-only", "--relative", base)
    if diff.returncode:
        raise ValueError(f"git diff against {base!r} failed: {diff.stderr.strip()}")
    new = run("ls-files", "--others", "--exclude-standard")
    return [ln for ln in (diff.stdout + new.stdout).splitlines() if ln]


def affected(root: Path, changed: list[str]) -> dict:
    asms, folders = scan(root)
    hit, unmapped = set(), []
    for p in changed:
        p = p.replace("\\", "/").removesuffix(".meta")
        if p.endswith(CODE) and p.startswith(("Assets/", "Packages/")):
            if p.endswith((".asmdef", ".asmref")):
                folders.setdefault(p.rsplit("/", 1)[0], Path(p).stem)  # a new or deleted asmdef
            hit.add(owner(p, folders))
        elif p.startswith(TRACKED):
            unmapped.append(p)
    users: dict[str, set] = {}
    for name, a in asms.items():
        for r in a["refs"]:
            users.setdefault(r, set()).add(name)
    seen, todo = set(hit), list(hit)
    while todo:
        for u in users.get(todo.pop(), ()):
            if u not in seen:
                seen.add(u)
                todo.append(u)
    tests = sorted(n for n in seen if asms.get(n, {}).get("test"))
    return {"run_all": bool(unmapped), "assemblies": tests, "changed_assemblies": sorted(hit),
            "unmapped": unmapped, "all_tests": sorted(n for n, a in asms.items() if a["test"])}
