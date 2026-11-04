# playcal

**One open-source toolkit for AI agents that build games.** It gives your agent a loop it can trust (edit → wait until the editor has really settled → check the change actually landed → look only at what changed → assert), and it is the only tool that checks bot playtests against real players: *"the bot finds level 12 easy, but people will pass it about 41% of the time (CI 30–53%)."*

Unity first, built on top of Unity's official CLI. Godot and Unreal plug into the same core later.

*AI agents: read [llms.txt](llms.txt) first.*

> **Status: pre-alpha (v0.0.1).** Today the event schema, `playcal ingest`, `playcal report`, `playcal logs`, the MCP server and the Unity SDK work. `playcal loop` works against a scripted fake of the Unity CLI and is being tried on a live Editor now. Everything below marked *planned* isn't built yet. I'd rather show a short honest list than a long fake one. Progress is tracked in the [roadmap](#roadmap).

<!-- DEMO: a 30-second GIF goes here with the first release (agent fixes a level, playcal catches the regression). No mock-ups. -->

## Why

Agents working in a game editor fail in boring, repeatable ways:

- they run a tool before compile or domain reload has finished, then reason about stale state;
- the editor isn't focused, so Play Mode sits on frame 1 while reporting "playing";
- a modal dialog blocks everything and nobody notices;
- they report "done" when the prefab was never saved;
- a single console read or hierarchy dump eats 10k+ tokens.

Unity's official CLI and the community MCP servers give you the building blocks: play, test, capture, console. Nothing ties them into a loop that handles these failures. playcal is that loop, plus the features nobody ships yet: whole-scene runtime state diffs, perf baselines, replay without changing game code, flaky-test quarantine, and calibration against human players.

## Install

Requires Python 3.10+.

```bash
pipx install git+https://github.com/RizgarOzan/playcal
playcal modules
```

A PyPI release (`pipx install playcal`) and the Unity UPM package come with v0.1.

### Install with your AI agent

Paste this into Claude Code, Cursor, Codex or any agent with a shell:

```text
Install playcal for this project:
1. Make sure pipx exists (python -m pip install --user pipx && python -m pipx ensurepath).
2. Run: pipx install git+https://github.com/RizgarOzan/playcal
3. Run: playcal modules --json  and show me the module list.
4. Read https://github.com/RizgarOzan/playcal#usage and tell me which commands fit this project.
Do not change project files yet.
```

### MCP server and skill

`playcal mcp` is a stdio MCP server. Every module becomes a tool (`playcal_ingest`, `playcal_logs`, `playcal_loop`, ...), built from the same argument definitions as the CLI, so the two can't drift apart.

```bash
claude mcp add --transport stdio playcal -- playcal mcp
code --add-mcp '{"name":"playcal","type":"stdio","command":"playcal","args":["mcp"]}'
```

If your agent has a shell, a skill file is cheaper than MCP (no tool list in every prompt):

```bash
mkdir -p .claude/skills/playcal && playcal skill > .claude/skills/playcal/SKILL.md
```

## Usage

Every command can print `--json`, so agents can read the result without scraping text.

### `playcal ingest` (works today)

This command validates gameplay events against [`schema/event-v0.json`](schema/event-v0.json). It accepts JSONL files, or free text that contains `PC0:` blobs. The in-game "send result" button produces those blobs, and players can paste them into any chat.

```bash
playcal ingest sessions.jsonl --json
playcal ingest whatsapp-export.txt --paste
```

Valid events go to `accepted.jsonl`. Every line that fails goes to `rejected.jsonl` with the reason.

The schema doesn't accept unknown fields, so names, emails, device IDs, location and IP can't slip in. See [PRIVACY.md](PRIVACY.md).

### `playcal report` (works today)

Per-level pass rates, counted two ways: per player and per attempt. Each rate comes with a 95% Wilson interval, because with 10 players a single "60%" means very little.

```bash
playcal report accepted.jsonl
playcal report accepted.jsonl --json
```

Different `game_version`s stay separate, and levels sort naturally (1, 2, 10).

### `playcal logs` (works today)

Boils a Unity `Editor.log` (or Player.log, or pasted console text) down to what an agent needs. The same error a thousand times becomes one entry with `count: 1000`, and the first cause is pulled out on its own, since later errors are usually fallout.

```bash
playcal logs --json                         # this machine's Editor.log
playcal logs Editor.log --since "Reloading assemblies"
cat Player.log | playcal logs -
```

Exit code 1 means it found errors.

### `playcal loop` (works on a live Editor)

`loop settle` waits until the Editor is really ready: two "ready" polls in a row, because a domain reload can flicker. While Unity compiles or reloads, `unity status` shows no Editor at all, so settle asks `unity pipeline list` why: Safe Mode, Unity running but stuck on a dialog (`editor_blocked`), or really no Editor. Two open Editors are reported too, instead of timing out on all of them.

`loop run` settles, runs one `unity command`, settles again, and can check its own work:

```bash
playcal loop run "gameobject create" --verify "scene get_hierarchy" --expect "result.roots.*.name=Probe" --diff --json -- --name Probe
```

`--verify` runs a read command after the write, `--expect` asserts on its JSON (`path=value`, `path!=value`, `path~text`, or a bare `path` for "exists"; `*` matches any item), and `--diff` shows what changed between the read before and after. The digest says `fault: "infra"` when the Editor or CLI broke and `fault: "task"` when the command itself was wrong, so an agent knows whether to retry or rethink. A write that reported success but didn't land fails with `verify_failed` (exit 5).

Two traps we hit on a live Editor (Unity 6000.3, Pipeline 0.10.0-exp.1):

- An Editor with compile errors still says "ready". `--compile` also runs `unity recompile` and fails with `compile_error` (exit 6) and the errors as `file`, `line`, `code`, `message`.
- Some commands start a reload a few seconds *after* they return (`package resolve` says `requiresRecompile`). loop sees that and waits for the reload to start before it trusts "ready" again; `--reload-wait SECONDS` forces the same wait for anything else, like a script written to disk.

Read, write and `--expect` passed against that Editor. The Safe Mode branch itself hasn't been seen live yet.

### `playcal query` (works today on JSON)

A full hierarchy dump can be tens of thousands of tokens when the agent needs three names. `query` keeps only what you ask for and says how much it cut:

```bash
playcal query --unity "scene get_hierarchy" --from "result.roots.**" --where "name~Enemy" --select name --select activeSelf --json
playcal query scene.json --from data.objects --where "tag=Enemy" --select name
```

`--where` uses the same syntax as `loop --expect`. `*` is any item of a list, `**` is anything at any depth.

### `playcal checkpoint` (works today)

Saves the project's files before an agent step and brings any save back. Saves are git commits on a private ref (`refs/playcal/checkpoints`), so your branch, HEAD and staging area don't move and nothing is pushed. `.gitignore` is respected.

```bash
playcal checkpoint save "before level 4 tweak"
playcal checkpoint list
playcal checkpoint diff latest
playcal checkpoint restore ~1     # one save back; prints how to undo the restore
```

Restore only rewrites files that differ, so Unity doesn't reimport everything. With `loop run --checkpoint`, every write is preceded by a save and a failed digest carries an `undo` command. Unity only writes scenes and prefabs to disk when they're saved, so unsaved Editor changes aren't in a checkpoint.

### `playcal snap` (works today on JSON)

Saves a read under a name and later tells you what changed, so "what did this run do to the scene" is a few lines instead of two dumps:

```bash
playcal snap save before --unity "scene get_hierarchy"
# ... the agent works, or you play a round ...
playcal snap diff before --unity "scene get_hierarchy"     # exit 1 when something changed
playcal snap diff run-a run-b --json
```

Unity's instanceIds only hold within one Editor session, so a plain diff across a restart or into play mode says everything was removed and re-added. snap leaves `instanceId` out and matches objects by `hierarchyPath`, then `path`, `guid`, `name`; two siblings with the same name become `Enemy` and `Enemy#2`. Any JSON file works, not only Unity reads. Saves go to `.playcal/snaps/`.

### `playcal baseline` (works today on JSON)

Keeps a perf run as the baseline and fails a later run only when it is slower by more than noise. Feed it per-frame samples, `{"frame_ms": [...], "gc_alloc_bytes": [...]}` or a bare list of frame times:

```bash
playcal baseline save level4 run-main.json
playcal baseline check level4 run-branch.json                 # exit 1 only when slower
playcal baseline check level4 run.json --percentile 99 --tolerance 5 --floor frame_ms=0.5
```

It compares p95 by default and bootstraps the difference. The check fails only when even the low end of the 95% interval is past the tolerance (10% by default). A short run with a couple of hitches comes out `inconclusive`, so one noisy CI machine doesn't turn the build red. `--floor` ignores slowdowns that are too small to matter in absolute units. Baselines live in `.playcal/baselines/`. Visual and memory gates aren't built yet, and nothing in the Unity SDK records frame samples yet either; for now you bring the JSON.

### `playcal tests` (works today)

Keeps a history of test results and tells a flaky failure from a real one. It reads what Unity's `-testResults` writes (NUnit3 XML) and JUnit XML:

```bash
playcal tests check TestResults.xml        # exit 1 only on failures of tests that aren't flaky
playcal tests flaky                        # tests that passed and failed on the same commit
```

A test counts as flaky once it has both passed and failed on one commit, so the first rerun that passes is what marks it. After that its failures show up as `quarantined` instead of turning the run red. They're still listed, so nobody forgets them. `check` judges the run against the history first and then adds it (`--no-record` skips that). The history is `.playcal/tests/history.jsonl`; keep it in CI's cache or commit it.

### Unity SDK (works today)

Install from git URL `https://github.com/RizgarOzan/playcal.git?path=/unity/com.playcal.sdk`, then call `PlaycalLog.Init()`, `log.LevelStart("04")`, `log.LevelFail(...)`. The "send result" button calls `PlaycalLog.CopyResult()`. Usage is in the [package README](unity/com.playcal.sdk/README.md). A test checks that the C# output passes the same schema as the Python side.

## Roadmap

| Module | What it does | State |
|---|---|---|
| `ingest` | event schema, validation, paste blobs | ✅ works |
| `report` | per-level pass rate, attempts, Wilson CI | ✅ works |
| Unity SDK | level events, PC0 "send result" line, delete-my-data, under-18 off | ✅ works |
| `loop` | edit → settle (compile/reload, focus, modal) → verify write → diff → assert, one JSON digest | ✅ read, write and `--expect` checked on a live Unity 6000.3 Editor; Safe Mode branch not seen live |
| `calibrate` / `predict` | bot metrics + small human panel → predicted human pass rate with CI | planned |
| `query` | pick, filter and project fields from any JSON result (file, stdin or a Unity read command) | 🟡 works on JSON; Unity shapes not checked live |
| `checkpoint` | every agent step is a git-backed, revertible checkpoint | ✅ works (`loop run --checkpoint` saves before each write) |
| `logs` | console/Editor.log summary: dedupe, first cause, error kinds | ✅ works |
| `mcp`, `skill` | MCP server and SKILL.md generated from the module registry | ✅ works |
| `snap` | save a read, diff two saves with session ids left out | ✅ works on JSON |
| `observe` | whole-scene runtime diff, screenshots only on red | planned (`snap` covers the diff part) |
| `baseline` | visual, perf (p95 frame time, GC) and memory gates per commit | 🟡 perf gate works on JSON; visual, memory and an SDK recorder planned |
| `replay` | frame stepping, recorded input, replay → regression test | planned |
| `tests` | flaky history and quarantine, affected tests | 🟡 history, flaky detection and quarantine work (NUnit3, JUnit); affected tests planned |
| `lock` | scene/asset locks for several agents at once | planned |
| Godot, Unreal | same core, new backend | later |

Every row is one module. A module is a Python entry point in the `playcal.modules` group, with optional Editor C#, its own tests and its own benchmark scenario. New features arrive as new modules, not as new tools to install.

## How we'll prove it's better

There's a public benchmark: 20 planted bugs plus scenarios rebuilt from real issue reports (domain reload drop, unfocused editor, modal dialog, compile storm, unsaved prefab, 15 MB hierarchy). Each task runs three ways:

1. plain official Unity CLI;
2. a popular MCP server;
3. playcal.

We measure success, *false success*, tokens and time. If playcal doesn't win a row, that row isn't advertised.

Until the live benchmark exists, [`bench/sim.py`](bench/sim.py) replays those failure modes against a scripted Editor (a write lost in a domain reload, a command that says success and does nothing, Safe Mode, an Editor stuck on a dialog), using envelopes shaped like a live Editor's. It's a regression guard, not evidence about Unity: in it the naive agent reports 4 false successes out of 7 scenarios and `loop run --verify` reports none.

Predicting human difficulty with agents isn't a new idea. Roohi et al. ([2021](https://arxiv.org/abs/2107.12061)) did it for a Rovio game with a large player base. What playcal adds is doing it with a small panel (10–30 friends), honest confidence intervals, and open code.

## Contributing

Issues and module ideas are welcome. Read the module contract in [`src/playcal/registry.py`](src/playcal/registry.py), and run tests with `pytest`.

## License

[Apache-2.0](LICENSE). Use it in commercial games. The patent grant is there so studios don't have to ask.
