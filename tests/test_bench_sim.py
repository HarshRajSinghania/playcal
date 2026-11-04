"""The simulated benchmark doubles as a regression guard: loop must never report a write that didn't land,
and observe must catch a write that lands but breaks the game in Play."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("sim", Path(__file__).parent.parent / "bench" / "sim.py")
sim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sim)


def test_playcal_has_no_false_success_and_catches_what_naive_misses():
    rows = sim.run()
    pc = {r["scenario"]: r for r in rows if r["agent"] == "playcal"}
    naive = {r["scenario"]: r for r in rows if r["agent"] == "naive"}
    assert not any(r["false_success"] for r in pc.values())
    assert naive["reload_during_write"]["false_success"] and pc["reload_during_write"]["landed"]
    assert pc["silent_noop"]["said"] == "verify_failed/task"
    assert pc["safe_mode"]["said"] == "safe_mode/infra"
    assert naive["throws_in_play"]["false_success"] and pc["throws_in_play"]["said"] == "errors/task"
