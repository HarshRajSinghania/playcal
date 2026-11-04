# Changelog

## 0.1.0 (unreleased)

First public release. Everything here runs without Unity except `loop`, `observe`, `doctor`'s Editor checks and the Unity SDK; those were checked on a live Unity 6000.3 Editor with Pipeline 0.10.0-exp.1.

- `loop`: settle, run one Editor command, settle again, read back and assert, one JSON digest with `fault: infra|task`.
- `logs`, `query`, `snap`, `checkpoint`, `lock`, `doctor`.
- `observe`: press Play, run the game a few seconds, report console errors, `--expect` checks and the scene diff; a Game view screenshot only when the run goes red.
- `baseline` (perf and memory), `visual` (screenshot gate), `tests` (flaky history, quarantine, affected test assemblies).
- `ingest`, `report`, `calibrate`: an event schema with no room for personal data, per-level pass rates with Wilson intervals, and human pass-rate predictions from bot runs.
- `playcal mcp` (stdio MCP server) and `playcal skill` (SKILL.md), both generated from the module registry.
- Unity SDK `com.playcal.sdk`: level events, paste-back result line, frame and memory recorder, screenshots.
- `bench/sim.py` (scripted regression guard) and `bench/live.py` (naive CLI vs `loop` on a real Editor).
