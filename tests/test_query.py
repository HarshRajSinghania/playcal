import json

from playcal.cli import main
from playcal.query import query

SCENE = {"data": {"objects": [
    {"name": "Main Camera", "tag": "MainCamera", "active": True, "pos": [0, 1, -10]},
    {"name": "Enemy_1", "tag": "Enemy", "active": True, "pos": [3, 0, 0], "components": [{"type": "Rigidbody"}]},
    {"name": "Enemy_2", "tag": "Enemy", "active": False, "pos": [5, 0, 0]},
]}}


def test_from_where_select():
    out = query(SCENE, "data.objects", where=["name~Enemy", "active=true"], select=["name", "pos.0"])
    assert out == {"count": 1, "items": [{"name": "Enemy_1", "pos.0": 3}]}


def test_fan_out_select_and_limit():
    out = query(SCENE, "data.objects", select=["components.*.type"], limit=2)
    assert out["count"] == 3 and out["truncated"] == 1
    assert out["items"][1] == {"components.*.type": ["Rigidbody"]}


def test_cli_from_file_reports_saving(tmp_path, capsys):
    f = tmp_path / "scene.json"
    f.write_text(json.dumps(SCENE))
    assert main(["query", str(f), "--from", "data.objects", "--where", "tag=Enemy", "--select", "name", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert [r["name"] for r in out["items"]] == ["Enemy_1", "Enemy_2"] and out["bytes_out"] < out["bytes_in"]


def test_double_star_walks_nested_children():
    tree = {"roots": [{"name": "Level", "children": [{"name": "Room", "children": [{"name": "Enemy_9", "hp": 3}]}]}]}
    out = query(tree, "roots.**", where=["name~Enemy"], select=["hp"])
    assert out == {"count": 1, "items": [{"hp": 3}]}
