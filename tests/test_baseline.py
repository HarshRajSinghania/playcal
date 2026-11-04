import json
import random

from playcal import baseline
from playcal.cli import main


def frames(n, mean=16.0, sd=1.0, seed=1, hitches=0):
    rng = random.Random(seed)
    xs = [max(1.0, rng.gauss(mean, sd)) for _ in range(n)]
    for i in range(hitches):
        xs[i * 7 % n] = 80.0
    return xs


def test_same_distribution_is_same():
    r = baseline.compare(frames(3000, seed=1), frames(3000, seed=2))
    assert r["verdict"] == "same" and abs(r["change"]) < 0.02


def test_real_slowdown_fails():
    r = baseline.compare(frames(3000, seed=1), frames(3000, mean=21, seed=2))
    assert r["verdict"] == "slower" and r["ci95"][0] > 0.10


def test_faster_is_reported():
    assert baseline.compare(frames(3000, seed=1), frames(3000, mean=12, seed=2))["verdict"] == "faster"


def test_short_hitchy_run_is_inconclusive_not_red():
    # 60 frames where a few hitches land in the top 5%: the p95 jumps, but 60 frames can't prove it
    r = baseline.compare(frames(3000, seed=1), frames(60, seed=3, hitches=4))
    assert r["p95_new"] > r["p95_base"] * 1.1 and r["verdict"] == "inconclusive"


def test_floor_ignores_tiny_absolute_changes():
    base, new = frames(3000, mean=1.0, sd=0.05, seed=1), frames(3000, mean=1.3, sd=0.05, seed=2)
    assert baseline.compare(base, new)["verdict"] == "slower"
    assert baseline.compare(base, new, floor=0.5)["verdict"] != "slower"


def test_samples_shapes():
    assert baseline.samples([16, 17.5]) == {"frame_ms": [16.0, 17.5]}
    assert set(baseline.samples({"frame_ms": [1], "gc_alloc_bytes": [0, 512], "scene": "Lab"})) == {"frame_ms", "gc_alloc_bytes"}


def test_cli_save_check_show(tmp_path, capsys):
    d = str(tmp_path / "b")
    base, same, slow = (tmp_path / f"{n}.json" for n in ("base", "same", "slow"))
    base.write_text(json.dumps({"frame_ms": frames(2000, seed=1), "gc_alloc_bytes": [0] * 2000}), encoding="utf-8")
    same.write_text(json.dumps({"frame_ms": frames(2000, seed=2), "gc_alloc_bytes": [0] * 2000}), encoding="utf-8")
    slow.write_text(json.dumps({"frame_ms": frames(2000, mean=22, seed=2)}), encoding="utf-8")
    assert main(["baseline", "save", "lab", str(base), "--dir", d]) == 0
    assert main(["baseline", "check", "lab", str(same), "--dir", d]) == 0
    capsys.readouterr()
    assert main(["baseline", "check", "lab", str(slow), "--dir", d, "--json"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert not out["ok"] and out["metrics"]["frame_ms"]["verdict"] == "slower" and "gc_alloc_bytes" not in out["metrics"]
    assert main(["baseline", "show", "lab", "--dir", d, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["stats"]["frame_ms"]["n"] == 2000
    assert main(["baseline", "check", "nope", str(same), "--dir", d]) == 2
