using System;
using System.Collections.Generic;
using Playcal;

// Fixed clock so the output is deterministic.
var t = new DateTime(2026, 11, 4, 10, 0, 0, DateTimeKind.Utc);
DateTime Clock() { t = t.AddSeconds(30); return t; }

var log = new EventLog("match3-lab", "0.4.0", "inst_check01", Clock);
log.SessionStart(new Dictionary<string, object> { ["plays_genre"] = true, ["age_band"] = "18-24" });
log.LevelStart("04", seed: 1234);
log.Move("04", 1, movesLeft: 19, goalLeft: 30);
log.LevelFail("04", movesUsed: 20, movesLeft: 0, goalLeft: 4);
log.LevelStart("04", seed: 1234);
log.LevelComplete("04", movesUsed: 17, movesLeft: 3, goalLeft: 0);
log.LevelStart("lv \"quoted\"");
log.LevelQuit("lv \"quoted\"");
log.SessionEnd();

// A later session on the same install must continue attempt numbers.
var later = new EventLog("match3-lab", "0.4.0", "inst_check01", Clock);
later.Restore(log.Lines);
int next = later.LevelStart("04");
if (next != 3) throw new Exception($"Restore: expected attempt 3, got {next}");

// Under-18 / disabled log writes nothing.
var off = new EventLog("g", "1", "inst_check02", Clock) { Enabled = false };
off.LevelStart("1");
if (off.Lines.Count != 0) throw new Exception("disabled log wrote lines");

foreach (var line in log.Lines) Console.WriteLine(line);
foreach (var line in later.Lines) Console.WriteLine(line);
Console.WriteLine(Paste.Encode(log.Lines));
