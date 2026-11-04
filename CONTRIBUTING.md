# Contributing to playcal

Thanks for looking. playcal is small and young, so a good bug report is worth as much as a patch.

## Quick start

```bash
git clone https://github.com/RizgarOzan/playcal
cd playcal
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"      # Windows: .venv\Scripts\python
.venv/bin/python -m pytest -q
python bench/sim.py
```

Tests run on Python 3.10 and 3.13, on Linux, Windows and macOS. They don't need Unity.

## What helps most

- **A failure you hit with an agent in a real editor.** What the agent did, what the editor said, what was actually true. These become benchmark scenarios. Use the "Editor failure" issue template.
- **A module.** Every feature is one module: a Python entry point in the `playcal.modules` group. The contract is in [`src/playcal/registry.py`](src/playcal/registry.py), and [`src/playcal/lock.py`](src/playcal/lock.py) is a short one to copy from. A module brings its own tests and, where it touches the Editor, a scenario for `bench/`.
- **Godot or Unreal.** The core is engine-independent on purpose. If you know either engine's CLI or editor API well, open an issue first so we can agree on the shape.
- Issues labelled [`good first issue`](https://github.com/RizgarOzan/playcal/labels/good%20first%20issue).

## Ground rules

- Keep it honest. If a feature only works on JSON files, or was never seen on a live Editor, the README says so. A row in the benchmark that playcal doesn't win stays in the table.
- Every command prints `--json`, and its exit codes mean something. Agents read these, so changing them is a breaking change.
- No telemetry, and no new fields in the event schema that could carry personal data. See [PRIVACY.md](PRIVACY.md).
- Standard library first. A new runtime dependency needs a reason in the PR.
- Never hand-edit Unity `.unity`, `.prefab` or `.meta` YAML in code or tests; go through the Editor.

## Pull requests

Small PRs get merged faster. Say what changed and why, and how you checked it (tests, a live Editor run, both). CI has to be green.

By contributing you agree that your work is licensed under [Apache-2.0](LICENSE), like the rest of the project.

## Conduct

Be kind and assume good faith. The [code of conduct](CODE_OF_CONDUCT.md) applies everywhere the project lives.
