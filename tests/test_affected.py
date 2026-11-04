import json
import subprocess

from playcal import affected
from playcal.cli import main


def asmdef(root, folder, name, guid, **doc):
    d = root / folder
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.asmdef").write_text(json.dumps({"name": name, **doc}), encoding="utf-8")
    (d / f"{name}.asmdef.meta").write_text(f"fileFormatVersion: 2\nguid: {guid}\n", encoding="utf-8")


def project(root):
    asmdef(root, "Assets/Game/Core", "Game.Core", "a1")
    asmdef(root, "Assets/Game/UI", "Game.UI", "b2", references=["GUID:a1"])
    asmdef(root, "Assets/Tests/Core", "Game.Core.Tests", "c3", references=["Game.Core"],
           defineConstraints=["UNITY_INCLUDE_TESTS"], autoReferenced=False)
    asmdef(root, "Assets/Tests/UI", "Game.UI.Tests", "d4", references=["GUID:b2"],
           optionalUnityReferences=["TestAssemblies"], autoReferenced=False)
    (root / "Assets/Game/Core/Board.cs").write_text("class Board {}", encoding="utf-8")
    return root


def test_core_change_reaches_both_test_assemblies_ui_change_only_one(tmp_path):
    root = project(tmp_path)
    r = affected.affected(root, ["Assets/Game/Core/Board.cs"])
    assert r["assemblies"] == ["Game.Core.Tests", "Game.UI.Tests"] and not r["run_all"]
    r = affected.affected(root, ["Assets/Game/UI/Menu.cs.meta", "README.md"])
    assert r["changed_assemblies"] == ["Game.UI"] and r["assemblies"] == ["Game.UI.Tests"]


def test_scenes_ask_for_a_full_run_and_loose_scripts_map_to_assembly_csharp(tmp_path):
    root = project(tmp_path)
    r = affected.affected(root, ["Assets/Scenes/Level4.unity"])
    assert r["run_all"] and r["unmapped"] == ["Assets/Scenes/Level4.unity"]
    r = affected.affected(root, ["Assets/Scripts/Player.cs", "Assets/Scripts/Editor/Tool.cs"])
    assert r["changed_assemblies"] == ["Assembly-CSharp", "Assembly-CSharp-Editor"] and r["assemblies"] == []


def test_cli_reads_git_and_prints_unity_args(tmp_path, capsys):
    root = project(tmp_path)
    git = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=root, check=True,
                                    capture_output=True)
    git("init", "-q")
    git("add", ".")
    git("commit", "-qm", "start")
    (root / "Assets/Game/UI/Menu.cs").write_text("class Menu {}", encoding="utf-8")  # untracked
    capsys.readouterr()
    assert main(["tests", "affected", "--project", str(root)]) == 0
    assert capsys.readouterr().out.strip() == '-runTests -assemblyNames "Game.UI.Tests"'
    assert main(["tests", "affected", "--project", str(tmp_path / "nope")]) == 2
