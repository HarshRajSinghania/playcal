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

// Frame samples for playcal baseline; one unknown value drops that series.
var frames = new FrameSamples(4);
frames.Add(16.5f, 0, 1000); frames.Add(17.25f, 512, 1512); frames.Add(33.333f, 0, 1512); frames.Add(16f, 0, 1400);
frames.Add(99f, 0, 9);
Console.WriteLine("FRAMES:" + frames.ToJson());
var partial = new FrameSamples();
partial.Add(16f, 0); partial.Add(16f);
Console.WriteLine("FRAMES:" + partial.ToJson());

// Replay track for playcal replay: written by C#, read back by C# and by Python.
var track = new InputTrack(60, 1234);
track.Set(0, "move.x", 0f);          // 0 is the default, not stored
track.Set(12, "jump", 1f);
track.Set(12, "move.x", -0.5f);
track.Set(13, "jump", 1f);           // unchanged, not stored
track.Set(14, "jump", 0f);
track.Set(20, "move.x", 0.1f);
track.Set(20, "move.x", 0.25f);      // same frame: last value wins
track.AddMark(12, "state", "jumping high");
track.AddMark(40, "score", "10");
track.End(59);
var text = track.Write();
var back = InputTrack.Parse(text);
if (back.Write() != text) throw new Exception("replay round trip changed the text");
if (back.Value(11, "jump") != 0f || back.Value(13, "jump") != 1f || back.Value(100, "move.x") != 0.25f || back.Value(5, "none") != 0f)
    throw new Exception("replay Value lookup is wrong");
if (back.EndFrame != 59 || back.Fps != 60 || back.Seed != 1234 || back.Marks.Count != 2) throw new Exception("replay header or marks lost");
foreach (var line in text.TrimEnd('\n').Split('\n')) Console.WriteLine("REPLAY:" + line);
