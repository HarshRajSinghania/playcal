"""checkpoint against a real throwaway git repo."""
import json
import subprocess

import pytest

from playcal import checkpoint as cp
from playcal.cli import main


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "root")
    (tmp_path / ".gitignore").write_text("Library/\n")
    (tmp_path / "Assets").mkdir()
    (tmp_path / "Assets" / "a.txt").write_text("one")
    (tmp_path / "Library").mkdir()
    (tmp_path / "Library" / "cache.bin").write_text("junk")
    return tmp_path


def test_save_diff_restore_and_undo(repo):
    r = cp.Repo(repo)
    head, status = git(repo, "rev-parse", "HEAD"), git(repo, "status", "--porcelain")
    first = cp.save(r, "start")
    assert first["saved"] and cp.save(r)["reason"] == "unchanged"

    (repo / "Assets" / "a.txt").write_text("two")
    (repo / "Assets" / "b.txt").write_text("new")
    assert {(c["status"], c["path"]) for c in cp.changes(r, r.resolve("latest"))} == \
        {("modified", "Assets/a.txt"), ("added", "Assets/b.txt")}

    out = cp.restore(r, first["id"])
    assert (repo / "Assets" / "a.txt").read_text() == "one" and not (repo / "Assets" / "b.txt").exists()
    assert out["rewrote"] == 1 and out["removed"] == 1
    assert (repo / "Library" / "cache.bin").exists()  # ignored files are left alone

    cp.restore(r, out["undo"])  # the restore itself can be undone
    assert (repo / "Assets" / "a.txt").read_text() == "two" and (repo / "Assets" / "b.txt").read_text() == "new"

    # the user's branch and staging area never moved
    assert git(repo, "rev-parse", "HEAD") == head
    assert git(repo, "diff", "--cached", "--name-only") == ""
    assert "Library" not in git(repo, "ls-tree", "-r", "--name-only", cp.REF)


def test_list_and_relative_ids(repo):
    r = cp.Repo(repo)
    cp.save(r, "a")
    (repo / "Assets" / "a.txt").write_text("x")
    cp.save(r, "b")
    rows = cp.list_(r)
    assert [x["message"] for x in rows] == ["b", "a"] and rows[1]["back"] == 1
    assert r.resolve("~1")[:10] == rows[1]["id"]
    with pytest.raises(cp.GitError):
        r.resolve(git(repo, "rev-parse", "HEAD"))  # a normal commit is not a checkpoint


def test_cli_json(repo, capsys, monkeypatch):
    monkeypatch.chdir(repo)
    assert main(["checkpoint", "save", "first", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["saved"]
    assert main(["checkpoint", "restore", "nope", "--json"]) == 2
    assert main(["checkpoint", "list", "--json"]) == 0
    assert len(json.loads(capsys.readouterr().out)) == 1
