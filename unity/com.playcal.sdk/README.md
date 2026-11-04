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

Saying under 18 turns recording off and wipes the local log. Nothing leaves the device unless the player pastes the line themselves. See [PRIVACY.md](../../PRIVACY.md).
