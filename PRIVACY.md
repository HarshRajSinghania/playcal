# Privacy

playcal is built for small player panels: friends and classmates playing a test build. This page covers what the event format records.

**Recorded:**
- a random install ID that the player can reset;
- a session ID;
- the game and its version;
- the level, seed and attempt number;
- start, fail, complete and quit events;
- moves used and moves left, goal left, and duration;
- two optional answers: "do you play this genre: yes/no", and an age band.

Players under 18 aren't recorded at all.

**Never recorded:** names, emails, device fingerprints, location or IP. The schema rejects unknown fields, so these can't be added by accident.

**Where the data goes:** nowhere, unless the player sends it. Data stays on the device. The player taps "send result" and pastes the short `PC0:` line wherever they like. Nothing is uploaded automatically.

**Deleting:** the SDK's "delete my data" button wipes the local log and resets the install ID. To remove data that was already sent, ask the person running the playtest. Their copy is a plain JSONL file, and they can delete your install ID's lines from it.
