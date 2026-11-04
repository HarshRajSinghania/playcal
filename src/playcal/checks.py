"""Engine-independent checks on JSON results: dotted-path lookups, expectations and a small diff.

Paths are dotted: `scene.objects.0.name`. A `*` segment fans out over every list item or dict value,
so `objects.*.name=PlaycalProbe` passes when any object has that name. `**` is the node and
everything under it at any depth, for nested hierarchies: `**.name=Probe`.
"""
from __future__ import annotations

import json

def lookup(data, path: str) -> list:
    """Every value at `path` (more than one when the path has `*`). Empty list = nothing there."""
    found = [data]
    for seg in [s for s in path.split(".") if s] if path else []:
        nxt = []
        for node in found:
            if seg == "**":
                nxt.extend(_descend(node))
            elif seg == "*":
                nxt.extend(node.values() if isinstance(node, dict) else node if isinstance(node, list) else [])
            elif isinstance(node, dict) and seg in node:
                nxt.append(node[seg])
            elif isinstance(node, list) and seg.lstrip("-").isdigit() and -len(node) <= int(seg) < len(node):
                nxt.append(node[int(seg)])
        found = nxt
    return found


def _descend(node) -> list:
    """`node` and everything under it, depth first."""
    out = [node]
    for child in node.values() if isinstance(node, dict) else node if isinstance(node, list) else []:
        out.extend(_descend(child))
    return out


def _value(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def parse_expect(spec: str) -> dict:
    """`path=value` equals (value read as JSON when it parses, else as text), `path!=value`,
    `path~text` contains, bare `path` exists and is not null/false/empty."""
    for op in ("!=", "=", "~"):
        if op in spec:
            path, _, raw = spec.partition(op)
            return {"path": path.strip(), "op": op, "expected": raw if op == "~" else _value(raw)}
    return {"path": spec.strip(), "op": "exists", "expected": None}


def _hit(op: str, value, expected) -> bool:
    if op == "exists":
        return value not in (None, False, "", [], {})
    if op == "=":
        return value == expected
    if op == "~":
        return expected in (value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
    return False


def check(data, spec: str) -> dict:
    e = parse_expect(spec)
    values = lookup(data, e["path"])
    if e["op"] == "!=":
        ok = all(v != e["expected"] for v in values)
    else:
        ok = any(_hit(e["op"], v, e["expected"]) for v in values)
    fan_out = bool({"*", "**"} & set(e["path"].split(".")))
    actual = values if fan_out else values[0] if values else None
    return {"expect": spec, "ok": ok, "actual": _clip(actual)}


def _clip(value, limit: int = 200):
    text = json.dumps(value, ensure_ascii=False)
    return value if len(text) <= limit else text[:limit] + "..."


def diff(before, after, limit: int = 50, ignore=(), id_keys=None) -> list[dict]:
    """Paths that were added, removed or changed between two JSON values. At most `limit` entries;
    a final {"truncated": n} entry says how many more there were. `ignore`: dict keys to skip
    everywhere (ids that change between sessions). `id_keys`: which field names a list item,
    first match wins (default: instanceId, id, guid, path, name)."""
    out: list[dict] = []
    ignore, id_keys = set(ignore), tuple(id_keys or _ID_KEYS)

    def walk(a, b, path):
        if isinstance(a, dict) and isinstance(b, dict):
            for k in sorted((set(a) | set(b)) - ignore, key=str):
                p = f"{path}.{k}" if path else str(k)
                if k not in a:
                    out.append({"path": p, "added": _clip(b[k])})
                elif k not in b:
                    out.append({"path": p, "removed": _clip(a[k])})
                else:
                    walk(a[k], b[k], p)
        elif isinstance(a, list) and isinstance(b, list) and not (_named(a, id_keys) and _named(b, id_keys)):
            for i in range(max(len(a), len(b))):
                p = f"{path}.{i}" if path else str(i)
                if i >= len(a):
                    out.append({"path": p, "added": _clip(b[i])})
                elif i >= len(b):
                    out.append({"path": p, "removed": _clip(a[i])})
                else:
                    walk(a[i], b[i], p)
        elif isinstance(a, list) and isinstance(b, list):
            # Lists of named things (scene objects, assets): match by name so one insert isn't N changes.
            ka, kb = dict(zip(_keys(a, id_keys), a)), dict(zip(_keys(b, id_keys), b))
            for k in sorted(set(ka) | set(kb), key=str):
                p = f"{path}[{k}]"
                if k not in ka:
                    out.append({"path": p, "added": _clip(kb[k])})
                elif k not in kb:
                    out.append({"path": p, "removed": _clip(ka[k])})
                else:
                    walk(ka[k], kb[k], p)
        elif a != b:
            out.append({"path": path, "before": _clip(a), "after": _clip(b)})

    walk(before, after, "")
    if len(out) > limit:
        return out[:limit] + [{"truncated": len(out) - limit}]
    return out


_ID_KEYS = ("instanceId", "instanceID", "id", "guid", "path", "name")


def _key(x, id_keys=_ID_KEYS):
    for k in id_keys:
        if isinstance(x, dict) and k in x:
            return f"{k}={x[k]}"
    return json.dumps(x, sort_keys=True, ensure_ascii=False)


def _keys(items: list, id_keys=_ID_KEYS) -> list[str]:
    """One key per item; repeats (two siblings both called Enemy) become name=Enemy#2, #3..."""
    seen: dict[str, int] = {}
    out = []
    for x in items:
        k = _key(x, id_keys)
        seen[k] = seen.get(k, 0) + 1
        out.append(k if seen[k] == 1 else f"{k}#{seen[k]}")
    return out


def _named(items: list, id_keys=_ID_KEYS) -> bool:
    """True when every item is a dict named by the same id-like field."""
    if not items or not all(isinstance(x, dict) for x in items):
        return False
    fields = {_key(x, id_keys).partition("=")[0] for x in items}
    return len(fields) == 1 and not next(iter(fields)).startswith("{")
