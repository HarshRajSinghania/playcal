# Changelog

## 0.1.0 (2026-11-05)

First public release. Everything here runs without Unity except `loop`, `observe`, `replay`, `doctor`'s Editor checks and the Unity SDK; those were checked on a live Unity 6000.3 Editor with Pipeline 0.10.0-exp.1.

- `loop`: settle, run one Editor command, settle again, read back and assert, one JSON digest with `fault: infra|task`. After a write that starts no reload, one `job batch` call checks `editor status` and does the read-back, so a write is 4 CLI calls instead of 6 (idle write ~15 s live, was ~24 s). `--diff` no longer reports the request echo as a change.
- `logs`, `query`, `snap`, `checkpoint`, `lock`, `doctor`.
- `observe`: press Play, run the game a few seconds, report console errors, `--expect` checks and the scene diff; a Game view screenshot only when the run goes red. Reads go through `job batch` and Play Mode is checked with `editor status`, so a clean run is 7 CLI calls (~33 s live) instead of 16 (~70 s); `played_ms` says how long the game really ran.
- `replay`: record input through the SDK, play it back with a fixed frame rate and seed, report the first frame where the marks differ; stop on a frame and step from there.
- `baseline` (perf and memory), `visual` (screenshot gate), `tests` (flaky history, quarantine, affected test assemblies).
- `ingest`, `report`, `calibrate`: an event schema with no room for personal data, per-level pass rates with Wilson intervals, and human pass-rate predictions from bot runs.
- `playcal mcp` (stdio MCP server) and `playcal skill` (SKILL.md), both generated from the module registry.
- Unity SDK `com.playcal.sdk`: level events, paste-back result line, frame and memory recorder, screenshots, input recording and replay.
- `bench/sim.py` (scripted regression guard) and `bench/live.py` (naive CLI vs `loop` on a real Editor).
