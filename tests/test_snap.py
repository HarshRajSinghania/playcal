import json

from playcal import checks, snap
from playcal.cli import main


def obj(name, iid, path=None, active=True, children=()):
    return {"name": name, "instanceId": iid, "hierarchyPath": path or name, "activeSelf": active,
            "components": ["Transform"], "children": list(children)}


def scene(iid_base, enemy_active=True, extra=()):
    return {"result": {"sceneName": "Lab", "roots": [
        obj("Main Camera", iid_base + 1),
        obj("Enemies", iid_base + 2, children=[obj("Enemy", iid_base + 3, "Enemies/Enemy"),
                                               obj("Enemy", iid_base + 4, "Enemies/Enemy", active=enemy_active)]),
        *extra]}}


def test_new_instance_ids_after_a_reload_are_not_changes():
    assert snap.compare(scene(100), scene(9000))["same"]
    # the plain diff that loop --diff uses would call that a whole new scene
    assert checks.diff(scene(100), scene(9000))


def test_duplicate_siblings_are_matched_in_order():
    out = snap.compare(scene(100), scene(9000, enemy_active=False))
    assert out["changes"] == [{"path": "result.roots[hierarchyPath=Enemies].children[hierarchyPath=Enemies/Enemy#2].activeSelf",
                               "before": True, "after": False}]
    assert (out["added"], out["removed"], out["changed"]) == (0, 0, 1)


def test_added_object_is_one_change():
    out = snap.compare(scene(100), scene(9000, extra=[obj("Probe", 5)]))
    assert out["added"] == 1 and out["changes"][0]["path"] == "result.roots[hierarchyPath=Probe]"


def test_ignore_nothing_shows_the_ids():
    assert snap.compare(scene(100), scene(9000), ignore=())["changed"] == 4  # camera, Enemies, two Enemy


def test_cli_save_list_diff(tmp_path, capsys):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps(scene(100)), encoding="utf-8")
    b.write_text(json.dumps(scene(7, extra=[obj("Probe", 5)])), encoding="utf-8")
    d = str(tmp_path / "snaps")
    assert main(["snap", "save", "before", str(a), "--dir", d]) == 0
    assert main(["snap", "save", "after", str(b), "--dir", d]) == 0
    assert main(["snap", "diff", "before", "before", "--dir", d]) == 0
    capsys.readouterr()
    assert main(["snap", "diff", "before", "after", "--dir", d, "--json"]) == 1  # 1 = something changed
    out = json.loads(capsys.readouterr().out)
    assert out["added"] == 1 and not out["same"]
    assert main(["snap", "list", "--dir", d, "--json"]) == 0
    assert [s["name"] for s in json.loads(capsys.readouterr().out)] == ["before", "after"]
    # a raw dump file works as B without saving it first
    assert main(["snap", "diff", "before", str(b), "--dir", d]) == 1


def test_bad_name_and_missing_snapshot(tmp_path, capsys):
    d = str(tmp_path)
    assert main(["snap", "save", "../x", "--dir", d]) == 2
    assert main(["snap", "diff", "nope", "nada", "--dir", d]) == 2
    assert "no snapshot" in capsys.readouterr().err
