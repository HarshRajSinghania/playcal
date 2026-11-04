"""playcal checkpoint: save the project's files before each agent step, and go back to any save.

Checkpoints are ordinary git commits on a private ref (refs/playcal/checkpoints), written through
a separate index file. Your branch, HEAD, staging area and stash are never touched, and the ref is
not pushed unless you push it on purpose. .gitignore is respected, so Unity's Library/ and Temp/
stay out if your .gitignore says so.

restore only rewrites the files that differ (so Unity doesn't reimport the whole project) and
always saves a checkpoint of the current state first, so a restore can itself be undone.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .registry import Module

REF = "refs/playcal/checkpoints"
IDENTITY = {"GIT_AUTHOR_NAME": "playcal", "GIT_AUTHOR_EMAIL": "playcal@localhost",
            "GIT_COMMITTER_NAME": "playcal", "GIT_COMMITTER_EMAIL": "playcal@localhost"}


class GitError(RuntimeError):
    pass


class Repo:
    def __init__(self, path: str | os.PathLike = "."):
        self.root = Path(self._git(["rev-parse", "--show-toplevel"], cwd=path).strip())
        self.index = Path(self._git(["rev-parse", "--absolute-git-dir"]).strip()) / "playcal-index"

    def _git(self, args, cwd=None, index=False, check=True) -> str:
        env = {**os.environ, **IDENTITY}
        if index:
            env["GIT_INDEX_FILE"] = str(self.index)
        try:
            p = subprocess.run(["git", *args], cwd=cwd or self.root, env=env, capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
        except OSError as e:  # no git on PATH, or the folder doesn't exist
            raise GitError(str(e)) from e
        if check and p.returncode != 0:
            raise GitError(p.stderr.strip() or f"git {args[0]} failed")
        return p.stdout

    def rev(self, name: str) -> str | None:
        out = self._git(["rev-parse", "--verify", "--quiet", f"{name}^{{commit}}"], check=False).strip()
        return out or None

    def snapshot_tree(self) -> str:
        """The working tree as a git tree object, built in playcal's own index."""
        self.index.unlink(missing_ok=True)
        if self.rev("HEAD"):
            self._git(["read-tree", "HEAD"], index=True)  # start from HEAD so add -A only hashes what changed
        self._git(["add", "-A", "--", "."], index=True)
        return self._git(["write-tree"], index=True).strip()

    def resolve(self, ident: str) -> str:
        if ident in ("latest", "last"):
            ident = REF
        elif ident.startswith("~") and ident[1:].isdigit():
            ident = f"{REF}~{ident[1:]}"
        sha = self.rev(ident)
        if not sha or not self._is_checkpoint(sha):
            raise GitError(f"no checkpoint {ident!r} (see: playcal checkpoint list)")
        return sha

    def _is_checkpoint(self, sha: str) -> bool:
        tip = self.rev(REF)
        return bool(tip) and subprocess.run(["git", "merge-base", "--is-ancestor", sha, str(tip)], cwd=self.root,
                                            capture_output=True).returncode == 0


def save(repo: Repo, message: str = "") -> dict:
    tree = repo.snapshot_tree()
    tip = repo.rev(REF)
    if tip and repo._git(["rev-parse", f"{tip}^{{tree}}"]).strip() == tree:
        return {"id": tip[:10], "saved": False, "reason": "unchanged"}
    head = repo.rev("HEAD")
    msg = (message or "checkpoint") + (f"\n\nbase: {head}" if head else "")
    sha = repo._git(["commit-tree", tree, *(["-p", tip] if tip else []), "-m", msg]).strip()
    repo._git(["update-ref", REF, sha, tip or ""])  # fails if someone else moved the ref meanwhile
    return {"id": sha[:10], "saved": True, "message": message or "checkpoint"}


def list_(repo: Repo, limit: int = 20) -> list[dict]:
    if not repo.rev(REF):
        return []
    out = repo._git(["log", f"-{limit}", "--format=%H%x1f%cI%x1f%s", REF])
    rows = []
    for i, line in enumerate(out.splitlines()):
        sha, when, subject = line.split("\x1f")
        rows.append({"id": sha[:10], "back": i, "time": when, "message": subject})
    return rows


def changes(repo: Repo, sha: str, tree: str | None = None) -> list[dict]:
    """What changed from checkpoint `sha` to the working tree (or to `tree`)."""
    tree = tree or repo.snapshot_tree()
    out = repo._git(["diff-tree", "-r", "--no-renames", "--name-status", "-z", f"{sha}^{{tree}}", tree])
    parts = [p for p in out.split("\0") if p]
    names = {"A": "added", "D": "deleted", "M": "modified", "T": "modified"}
    return [{"status": names.get(parts[i], parts[i]), "path": parts[i + 1]} for i in range(0, len(parts) - 1, 2)]


def restore(repo: Repo, ident: str) -> dict:
    sha = repo.resolve(ident)
    before = save(repo, f"before restore to {sha[:10]}")
    diff = changes(repo, sha, repo._git(["rev-parse", f"{REF}^{{tree}}"]).strip())
    gone = [d["path"] for d in diff if d["status"] == "added"]
    back = [d["path"] for d in diff if d["status"] != "added"]
    for path in gone:
        (repo.root / path).unlink(missing_ok=True)
    repo.index.unlink(missing_ok=True)
    repo._git(["read-tree", sha], index=True)
    for i in range(0, len(back), 200):  # keep the command line short on Windows
        repo._git(["checkout-index", "-f", "--", *back[i:i + 200]], index=True)
    return {"restored": sha[:10], "undo": before["id"], "rewrote": len(back), "removed": len(gone),
            "files": diff[:50]}


def _add_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("action", choices=["save", "list", "diff", "restore"],
                   help="save the files now, list saves, diff a save against now, restore a save")
    p.add_argument("target", nargs="?", help="save: a message. diff/restore: checkpoint id, latest, or ~N (N saves back)")
    p.add_argument("--repo", default=".", help="folder inside the git repo (default: current folder)")
    p.add_argument("--limit", type=int, default=20, help="how many saves to list (default 20)")
    p.add_argument("--json", action="store_true", help="print the result as JSON")


def _run(args: argparse.Namespace) -> int:
    out: Any
    try:
        repo = Repo(args.repo)
        if args.action == "save":
            out = save(repo, args.target or "")
        elif args.action == "list":
            out = list_(repo, args.limit)
        elif args.action == "diff":
            sha = repo.resolve(args.target or "latest")
            out = {"id": sha[:10], "changes": changes(repo, sha)}
        else:
            if not args.target:
                print("playcal checkpoint restore: give a checkpoint id, latest or ~N", file=sys.stderr)
                return 2
            out = restore(repo, args.target)
    except GitError as e:
        print(json.dumps({"error": str(e)}) if args.json else f"playcal checkpoint: {e}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(out, ensure_ascii=False))
    elif args.action == "list":
        for r in out:
            print(f"{r['id']}  ~{r['back']:<3} {r['time']}  {r['message']}")
    elif args.action == "diff":
        for c in out["changes"]:
            print(f"{c['status']:<9} {c['path']}")
        print(f"{len(out['changes'])} files differ from {out['id']}")
    elif args.action == "save":
        print(f"{'saved' if out['saved'] else 'nothing changed since'} {out['id']}")
    else:
        print(f"restored {out['restored']}: {out['rewrote']} rewritten, {out['removed']} removed. "
              f"Undo with: playcal checkpoint restore {out['undo']}")
    return 0


MODULE = Module(name="checkpoint", summary="save project files to a private git ref before each step, and restore any save",
                add_args=_add_args, run=_run)
