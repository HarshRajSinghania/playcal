# playcal SDK for Unity

Records level start / fail / complete / quit for small playtests. Players send back one short `PC0:` line; you paste it into `playcal ingest --paste`.

## Install

Package Manager → Add package from git URL:

```
https://github.com/RizgarOzan/playcal.git?path=/unity/com.playcal.sdk
```

## Use

```csharp
using Playcal;

PlaycalLog.Init();                                    // once, at startup
PlaycalLog.StartSession(underEighteen: false, playsGenre: true, ageBand: "25-34");

var log = PlaycalLog.Current;
log.LevelStart("04", seed: 1234);
log.Move("04", movesUsed: 1, movesLeft: 19, goalLeft: 30);
log.LevelFail("04", movesUsed: 20, movesLeft: 0, goalLeft: 4);

string line = PlaycalLog.CopyResult();               // "send result" button
PlaycalLog.DeleteMyData();                           // "delete my data" button
```

For a perf baseline, record a run and hand the file to `playcal baseline`:

```csharp
var frames = PlaycalFrames.Begin("level4");          // skips the first 30 frames
// ... play the level ...
string path = frames.Save();                          // persistentDataPath/playcal/frames-level4.json
```

For a screenshot gate, capture from a coroutine or a `[UnityTest]` and hand the file to `playcal visual`:

```csharp
yield return PlaycalShots.Capture("level4-start");   // persistentDataPath/playcal/shots/level4-start.png
PlaycalShots.CaptureCamera("level4-end", cam);         // one camera right away, 640x360 by default
```

`Capture` grabs the whole screen at the end of the frame. In batch mode that moment never comes, so there it renders `Camera.main` instead (overlay UI isn't in that picture, and `-nographics` gives no picture at all). Feed the PNGs to `playcal visual`.

For `playcal replay`, read input through `PlaycalInput` and mark what a replay should reproduce:

```csharp
float move = PlaycalInput.Axis("move.x", Input.GetAxis("Horizontal"));  // in Update
bool jump = PlaycalInput.Button("jump", Input.GetButton("Jump"));
PlaycalReplay.Mark("score", score);
```

With no replay running these return the live value and `Mark` does nothing. `Mark` has `int` and `float` overloads, so marking a number every frame in a normal game session doesn't box it or allocate anything. `playcal replay record` / `run` start one through a request file when Play starts; from code, `PlaycalReplay.Record("name", frames: 600)` and `PlaycalReplay.Play("name")` do the same. Files go to `<project>/.playcal/replays/`. The request file is only read in the Editor, and one older than 10 minutes (left behind by a run that crashed) is deleted with a warning instead of starting a replay; and `Record` / `Play` from code haven't been tried in a player build yet.

Frame samples are only frame time, GC bytes and used memory, nothing about the player. In the Editor, GC numbers include the Editor's own allocations, so take baselines from a player build.

Saying under 18 turns recording off and wipes the local log. Nothing leaves the device unless the player pastes the line themselves. See [PRIVACY.md](../../PRIVACY.md).
