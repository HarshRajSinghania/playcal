// Records input and marks into an InputTrack, or plays a track back, for `playcal replay`.
using System;
using System.Globalization;
using System.IO;
using UnityEngine;

namespace Playcal
{
    /// <summary>
    /// Routes input through a replay. Pass the live value; you get it back while recording or with no
    /// replay running, and the recorded value while a replay plays. Read input in Update so the frame
    /// number matches between the recording and the replay.
    /// </summary>
    public static class PlaycalInput
    {
        public static float Axis(string channel, float live)
        {
            switch (PlaycalReplay.Current)
            {
                case PlaycalReplay.Mode.Record: PlaycalReplay.Track.Set(PlaycalReplay.InputFrame, channel, live); return live;
                case PlaycalReplay.Mode.Replay: return PlaycalReplay.Track.Value(PlaycalReplay.InputFrame, channel);
                default: return live;
            }
        }

        public static bool Button(string channel, bool live) => Axis(channel, live ? 1f : 0f) > 0.5f;
    }

    /// <summary>
    /// Started by `playcal replay record|run` through a request file in &lt;project&gt;/.playcal/replays/,
    /// or from code with Record / Play. Fixes Time.captureFramerate and the Random seed so the game
    /// steps the same way each run; physics and anything time-of-day based may still drift.
    /// </summary>
    [DefaultExecutionOrder(-10000)]
    public sealed class PlaycalReplay : MonoBehaviour
    {
        public enum Mode { Off, Record, Replay }

        public static Mode Current { get; private set; }
        /// <summary>Replay frame: 0 during the first Update after the start, -1 before it.</summary>
        public static int Frame { get; private set; } = -1;
        public static string Folder => Path.Combine(Path.GetDirectoryName(Application.dataPath), ".playcal", "replays");

        internal static InputTrack Track;  // recording: being written; replay: the source
        internal static int InputFrame => Frame < 0 ? 0 : Frame;
        static InputTrack seen;            // replay: marks this run wrote
        static string name;
        static int frames = -1, stopAt = -1, oldTargetFps;
        static PlaycalReplay instance;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        static void ResetStatics()  // statics survive Play with domain reload turned off
        {
            Current = Mode.Off;
            Frame = frames = stopAt = -1;
            Track = seen = null;
            instance = null;
        }

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.BeforeSceneLoad)]
        static void FromRequest()
        {
            if (!Application.isEditor) return;
            var path = Path.Combine(Folder, "request");
            if (!File.Exists(path)) return;
            string mode = "", req = "";
            int n = -1, fps = 60, seed = 0, stop = -1;
            foreach (var line in File.ReadAllLines(path))
            {
                int eq = line.IndexOf('=');
                if (eq < 0) continue;
                string k = line.Substring(0, eq).Trim(), v = line.Substring(eq + 1).Trim();
                if (k == "mode") mode = v;
                else if (k == "name") req = v;
                else if (k == "frames") n = int.Parse(v, CultureInfo.InvariantCulture);
                else if (k == "fps") fps = int.Parse(v, CultureInfo.InvariantCulture);
                else if (k == "seed") seed = int.Parse(v, CultureInfo.InvariantCulture);
                else if (k == "stop_at") stop = int.Parse(v, CultureInfo.InvariantCulture);
            }
            File.Delete(path);  // one request, one Play session
            try
            {
                if (mode == "record") Record(req, n, fps, seed);
                else if (mode == "replay") Play(req, stop);
                else Debug.LogError($"playcal replay: unknown mode \"{mode}\" in {path}");
            }
            catch (Exception e) { Debug.LogError($"playcal replay: {e.Message}"); }
        }

        /// <summary>Records until `frames` frames have run (-1: until Play stops) into Folder/name.replay.</summary>
        public static void Record(string replayName, int frames = -1, int fps = 60, int seed = 0)
        {
            Begin(replayName, new InputTrack(fps, seed));
            PlaycalReplay.frames = frames;
            oldTargetFps = Application.targetFrameRate;
            Application.targetFrameRate = fps;  // a person plays at about real speed
            Current = Mode.Record;
        }

        /// <summary>Plays Folder/name.replay and writes the marks it sees to Folder/name.result.
        /// With stopAt >= 0 the Editor pauses on that frame and writes Folder/name.paused.</summary>
        public static void Play(string replayName, int stopAt = -1)
        {
            Begin(replayName, InputTrack.Parse(File.ReadAllText(Path.Combine(Folder, replayName + ".replay"))));
            seen = new InputTrack(Track.Fps, Track.Seed);
            PlaycalReplay.stopAt = stopAt;
            Current = Mode.Replay;
        }

        /// <summary>Notes a value the replay should reproduce (score, position, a state name).</summary>
        public static void Mark(string markName, object value)
        {
            var text = value is IFormattable f ? f.ToString(value is float || value is double ? "R" : null, CultureInfo.InvariantCulture)
                                               : value?.ToString() ?? "";
            if (Current == Mode.Record) Track.AddMark(InputFrame, markName, text);
            else if (Current == Mode.Replay) seen.AddMark(InputFrame, markName, text);
        }

        static void Begin(string replayName, InputTrack track)
        {
            if (string.IsNullOrEmpty(replayName) || replayName.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0)
                throw new ArgumentException($"bad replay name \"{replayName}\"");
            if (instance != null) throw new InvalidOperationException("a replay is already running");
            name = replayName;
            Track = track;
            Frame = -1;
            Time.captureFramerate = track.Fps;
            UnityEngine.Random.InitState(track.Seed);
            var go = new GameObject("playcal replay");
            DontDestroyOnLoad(go);
            instance = go.AddComponent<PlaycalReplay>();
        }

        void Update()
        {
            Frame++;
            if (Current == Mode.Record && frames >= 0 && Frame >= frames) { Finish(Frame - 1); return; }
            if (Current == Mode.Replay && Track.EndFrame >= 0 && Frame > Track.EndFrame) { Finish(Frame - 1); return; }
            if (Current == Mode.Replay && Frame == stopAt)
            {
                Write(".paused", Frame.ToString(CultureInfo.InvariantCulture) + "\n");
                Debug.Break();
            }
        }

        void OnDisable() => Finish(Frame);  // Play stopped early: keep what was recorded

        static void Finish(int last)  // last frame that ran recorded or replayed
        {
            if (Current == Mode.Off) return;
            if (Current == Mode.Record)
            {
                Track.End(Math.Max(last, 0));
                Application.targetFrameRate = oldTargetFps;
                Write(".replay", Track.Write());
            }
            else
            {
                seen.End(Math.Max(last, 0));
                Write(".result", seen.Write());
            }
            Current = Mode.Off;
            Time.captureFramerate = 0;
        }

        static void Write(string ext, string text)
        {
            Directory.CreateDirectory(Folder);
            var path = Path.Combine(Folder, name + ext);
            File.WriteAllText(path + ".tmp", text);  // Python polls for the file; never let it see half of one
            if (File.Exists(path)) File.Delete(path);
            File.Move(path + ".tmp", path);
        }
    }
}
