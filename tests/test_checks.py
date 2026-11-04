from playcal import checks

SCENE = {"objects": [{"name": "Main Camera", "active": True}, {"name": "Light", "active": True}], "count": 2}


def test_lookup_dotted_index_and_star():
    assert checks.lookup(SCENE, "objects.1.name") == ["Light"]
    assert checks.lookup(SCENE, "objects.*.name") == ["Main Camera", "Light"]
    assert checks.lookup(SCENE, "objects.9.name") == [] and checks.lookup(SCENE, "nope") == []


def test_expect_operators():
    assert checks.check(SCENE, "count=2")["ok"]  # JSON value, not the text "2"
    assert not checks.check(SCENE, "count=3")["ok"]
    assert checks.check(SCENE, "objects.*.name=Light")["ok"]
    assert checks.check(SCENE, "objects.*.name!=Probe")["ok"]
    assert not checks.check(SCENE, "objects.*.name!=Light")["ok"]
    assert checks.check(SCENE, "objects.0.name~Camera")["ok"]
    assert checks.check(SCENE, "objects")["ok"] and not checks.check(SCENE, "missing")["ok"]


def test_failed_check_shows_what_was_there():
    out = checks.check(SCENE, "objects.*.name=PlaycalProbe")
    assert not out["ok"] and out["actual"] == ["Main Camera", "Light"]


def test_diff_matches_named_items_so_one_insert_is_one_line():
    after = {"objects": [{"name": "PlaycalProbe", "active": True}, *SCENE["objects"]], "count": 3}
    d = checks.diff(SCENE, after)
    assert d == [{"path": "count", "before": 2, "after": 3},
                 {"path": "objects[name=PlaycalProbe]", "added": {"name": "PlaycalProbe", "active": True}}]


def test_diff_nested_change_and_truncation():
    after = {"objects": [{"name": "Main Camera", "active": False}, {"name": "Light", "active": True}], "count": 2}
    assert checks.diff(SCENE, after) == [{"path": "objects[name=Main Camera].active", "before": True, "after": False}]
    big = checks.diff({str(i): i for i in range(80)}, {}, limit=10)
    assert len(big) == 11 and big[-1] == {"truncated": 70}


def test_double_star_any_depth():
    from playcal.checks import check
    tree = {"a": [{"name": "x", "children": [{"name": "Probe"}]}]}
    assert check(tree, "**.name=Probe")["ok"] and not check(tree, "a.*.name=Probe")["ok"]
