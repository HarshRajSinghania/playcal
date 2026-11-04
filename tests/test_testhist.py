import json

from playcal import testhist
from playcal.cli import main

NUNIT = """<?xml version="1.0" encoding="utf-8"?>
<test-run id="2" testcasecount="3" result="{run}">
  <test-suite type="Assembly" name="Game.Tests.dll">
    <test-suite type="TestFixture" name="BoardTests" fullname="Game.BoardTests">
      <test-case id="1001" name="Swap" fullname="Game.BoardTests.Swap" result="Passed" duration="0.012"/>
      <test-case id="1002" name="Cascade" fullname="Game.BoardTests.Cascade" result="{cascade}" duration="1.5"/>
      <test-case id="1003" name="Shuffle" fullname="Game.BoardTests.Shuffle" result="Skipped"/>
    </test-suite>
  </test-suite>
</test-run>"""

JUNIT = """<testsuites><testsuite name="ui">
  <testcase classname="UiTests" name="OpensMenu" time="0.2"/>
  <testcase classname="UiTests" name="Closes" time="0.1"><failure message="boom"/></testcase>
  <testcase classname="UiTests" name="Later"><skipped/></testcase>
</testsuite></testsuites>"""


def nunit(tmp_path, name, cascade):
    f = tmp_path / f"{name}.xml"
    f.write_text(NUNIT.format(run="Failed" if cascade == "Failed" else "Passed", cascade=cascade), encoding="utf-8")
    return f


def test_parse_nunit_and_junit(tmp_path):
    rows = testhist.parse(nunit(tmp_path, "a", "Failed"))
    assert [(r["test"], r["outcome"]) for r in rows] == [
        ("Game.BoardTests.Swap", "pass"), ("Game.BoardTests.Cascade", "fail"), ("Game.BoardTests.Shuffle", "skip")]
    j = tmp_path / "j.xml"
    j.write_text(JUNIT, encoding="utf-8")
    assert [(r["test"], r["outcome"]) for r in testhist.parse(j)] == [
        ("UiTests.OpensMenu", "pass"), ("UiTests.Closes", "fail"), ("UiTests.Later", "skip")]


def test_flaky_means_pass_and_fail_on_one_commit():
    rows = [{"commit": "a", "test": "T", "outcome": "pass"}, {"commit": "a", "test": "T", "outcome": "fail"},
            {"commit": "a", "test": "U", "outcome": "fail"}, {"commit": "b", "test": "U", "outcome": "pass"}]
    # U failed on a and passed on b: that's a fix (or a regression), not flakiness
    assert list(testhist.flaky(rows)) == ["T"]


def test_check_fails_on_real_failures_and_quarantines_flaky(tmp_path, capsys):
    d = str(tmp_path / "hist")
    passed, failed = nunit(tmp_path, "p", "Passed"), nunit(tmp_path, "f", "Failed")
    # first failure of Cascade: nobody knows it's flaky yet, so the run is red
    assert main(["tests", "check", str(failed), "--commit", "c1", "--dir", d]) == 1
    # a rerun on the same commit passes: Cascade is now known flaky
    assert main(["tests", "check", str(passed), "--commit", "c1", "--dir", d]) == 0
    capsys.readouterr()
    assert main(["tests", "check", str(failed), "--commit", "c2", "--dir", d, "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["quarantined"] == ["Game.BoardTests.Cascade"] and out["failed"] == [] and out["recorded"] == 2
    assert main(["tests", "flaky", "--dir", d, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["Game.BoardTests.Cascade"]["fails"] == 2


def test_no_record_and_errors(tmp_path, capsys):
    d = tmp_path / "hist"
    assert main(["tests", "check", str(nunit(tmp_path, "p", "Passed")), "--dir", str(d), "--no-record"]) == 0
    assert not d.exists()
    bad = tmp_path / "bad.xml"
    bad.write_text("<nothing/>", encoding="utf-8")
    assert main(["tests", "record", str(bad), "--dir", str(d)]) == 2
    assert main(["tests", "check", "--dir", str(d)]) == 2
    assert "no test-case" in capsys.readouterr().err
