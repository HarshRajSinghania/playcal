import json

from playcal import lock
from playcal.cli import main

SCENE = "Assets/Scenes/Level4.unity"


def test_second_owner_is_refused_and_told_who(tmp_path):
    assert lock.take(tmp_path, [SCENE], "a", 60, now=0)["ok"]
    r = lock.take(tmp_path, ["Assets\\Scenes\\level4.unity"], "b", 60, now=10)  # same file, other spelling
    assert not r["ok"] and r["held"] == {"Assets/Scenes/level4.unity": {"path": "Assets/Scenes/Level4.unity", "owner": "a", "expires_in": 50}}


def test_all_or_nothing(tmp_path):
    lock.take(tmp_path, ["B.prefab"], "a", 60, now=0)
    assert not lock.take(tmp_path, ["A.unity", "B.prefab"], "b", 60, now=1)["ok"]
    assert [l["path"] for l in lock.list_(tmp_path, now=1)] == ["B.prefab"]  # A wasn't taken


def test_expired_lock_is_taken_over_and_own_lock_renews(tmp_path):
    lock.take(tmp_path, [SCENE], "a", 60, now=0)
    assert lock.take(tmp_path, [SCENE], "a", 60, now=30)["ok"]  # renew
    assert not lock.take(tmp_path, [SCENE], "b", 60, now=80)["ok"]  # renewed until 90
    assert lock.take(tmp_path, [SCENE], "b", 60, now=91)["ok"]


def test_cli_take_check_release(tmp_path, capsys):
    d = ["--dir", str(tmp_path)]
    assert main(["lock", "take", SCENE, "--owner", "a", *d]) == 0
    assert main(["lock", "take", SCENE, "--owner", "b", *d]) == 1
    assert main(["lock", "check", SCENE, "--owner", "b", *d]) == 1
    assert main(["lock", "check", SCENE, "--owner", "a", *d]) == 0
    assert main(["lock", "release", SCENE, "--owner", "b", *d]) == 1  # not b's
    capsys.readouterr()
    assert main(["lock", "list", "--json", *d]) == 0
    assert json.loads(capsys.readouterr().out)[0]["owner"] == "a"
    assert main(["lock", "release", SCENE, "--owner", "a", *d]) == 0
    assert main(["lock", "take", SCENE, *d]) == 2  # no owner
