using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text;

namespace Playcal
{
    /// <summary>
    /// Recorded input for `playcal replay`: per-frame values of named channels plus marks the game
    /// writes (score, position, "boss dead"). Only changes are stored. Text form, one event per line:
    /// <code>
    /// playcal-replay 1 fps=60 seed=1234
    /// 12 in jump 1
    /// 14 in jump 0
    /// 40 mark score 10
    /// 600 end
    /// </code>
    /// A channel holds its last value until the next change; one never set reads 0.
    /// </summary>
    public sealed class InputTrack
    {
        public const string Header = "playcal-replay 1";

        public readonly struct Mark
        {
            public readonly int Frame;
            public readonly string Name, Value;
            public Mark(int frame, string name, string value) { Frame = frame; Name = name; Value = value; }
        }

        readonly Dictionary<string, List<KeyValuePair<int, float>>> channels = new Dictionary<string, List<KeyValuePair<int, float>>>();
        readonly List<string> names = new List<string>();  // channels in the order they first changed
        readonly List<Mark> marks = new List<Mark>();

        public int Fps { get; }
        public int Seed { get; }
        public int EndFrame { get; private set; } = -1;
        public IReadOnlyList<Mark> Marks => marks;

        public InputTrack(int fps = 60, int seed = 0)
        {
            if (fps < 1) throw new ArgumentOutOfRangeException(nameof(fps));
            Fps = fps;
            Seed = seed;
        }

        /// <summary>Stores a channel's value at a frame; a value equal to the current one is not stored.</summary>
        public void Set(int frame, string channel, float value)
        {
            if (!channels.TryGetValue(channel, out var list))
            {
                CheckName(channel);  // once per channel: Set runs every frame
                channels[channel] = list = new List<KeyValuePair<int, float>>();
                names.Add(channel);
            }
            if (list.Count > 0)
            {
                var last = list[list.Count - 1];
                if (frame < last.Key) throw new ArgumentException($"frame {frame} is before {last.Key} on {channel}");
                if (last.Value == value) return;
                if (last.Key == frame) { list[list.Count - 1] = new KeyValuePair<int, float>(frame, value); return; }
            }
            else if (value == 0f) return;  // unset already reads 0
            list.Add(new KeyValuePair<int, float>(frame, value));
        }

        /// <summary>The value a channel had at a frame.</summary>
        public float Value(int frame, string channel)
        {
            if (!channels.TryGetValue(channel, out var list)) return 0f;
            int lo = 0, hi = list.Count - 1, found = -1;
            while (lo <= hi)
            {
                int mid = (lo + hi) / 2;
                if (list[mid].Key <= frame) { found = mid; lo = mid + 1; } else hi = mid - 1;
            }
            return found < 0 ? 0f : list[found].Value;
        }

        public void AddMark(int frame, string name, string value)
        {
            CheckName(name);
            marks.Add(new Mark(frame, name, (value ?? "").Replace('\n', ' ').Replace('\r', ' ')));
        }

        public void End(int frame) => EndFrame = frame;

        public string Write()
        {
            var sb = new StringBuilder();
            sb.Append(Header).Append(" fps=").Append(Fps.ToString(CultureInfo.InvariantCulture))
              .Append(" seed=").Append(Seed.ToString(CultureInfo.InvariantCulture)).Append('\n');
            // input and marks merged by frame; within a frame, input first (OrderBy is stable)
            var input = names.SelectMany(c => channels[c].Select(e => new KeyValuePair<int, string>(e.Key, Line(e.Key, c, e.Value))))
                             .OrderBy(e => e.Key);
            int m = 0;
            foreach (var e in input)
            {
                for (; m < marks.Count && marks[m].Frame < e.Key; m++) MarkLine(sb, marks[m]);
                sb.Append(e.Value).Append('\n');
            }
            for (; m < marks.Count; m++) MarkLine(sb, marks[m]);
            if (EndFrame >= 0) sb.Append(EndFrame.ToString(CultureInfo.InvariantCulture)).Append(" end\n");
            return sb.ToString();
        }

        public static InputTrack Parse(string text)
        {
            var lines = (text ?? "").Replace("\r", "").Split('\n');
            if (!lines[0].StartsWith(Header + " ", StringComparison.Ordinal) && lines[0] != Header)
                throw new FormatException("not a playcal replay: first line must start with \"" + Header + "\"");
            int fps = 60, seed = 0;
            foreach (var kv in lines[0].Substring(Header.Length).Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries))
            {
                if (kv.StartsWith("fps=", StringComparison.Ordinal)) fps = int.Parse(kv.Substring(4), CultureInfo.InvariantCulture);
                else if (kv.StartsWith("seed=", StringComparison.Ordinal)) seed = int.Parse(kv.Substring(5), CultureInfo.InvariantCulture);
            }
            var track = new InputTrack(fps, seed);
            for (int i = 1; i < lines.Length; i++)
            {
                var line = lines[i];
                if (line.Length == 0 || line[0] == '#') continue;
                var parts = line.Split(new[] { ' ' }, 4);
                int frame = int.Parse(parts[0], CultureInfo.InvariantCulture);
                if (parts.Length == 2 && parts[1] == "end") track.End(frame);
                else if (parts.Length == 4 && parts[1] == "in")
                    track.Set(frame, parts[2], float.Parse(parts[3], NumberStyles.Float, CultureInfo.InvariantCulture));
                else if (parts.Length >= 3 && parts[1] == "mark")
                    track.AddMark(frame, parts[2], parts.Length == 4 ? parts[3] : "");
                else throw new FormatException($"line {i + 1}: expected \"<frame> in <channel> <value>\", \"<frame> mark <name> <value>\" or \"<frame> end\"");
            }
            return track;
        }

        static string Line(int frame, string channel, float value) =>
            frame.ToString(CultureInfo.InvariantCulture) + " in " + channel + " " + value.ToString("R", CultureInfo.InvariantCulture);

        static void MarkLine(StringBuilder sb, Mark m) =>
            sb.Append(m.Frame.ToString(CultureInfo.InvariantCulture)).Append(" mark ").Append(m.Name).Append(' ').Append(m.Value).Append('\n');

        static readonly char[] Whitespace = { ' ', '\t', '\n', '\r' };

        static void CheckName(string name)
        {
            if (string.IsNullOrEmpty(name) || name.IndexOfAny(Whitespace) >= 0)
                throw new ArgumentException($"names can't be empty or hold whitespace: \"{name}\"");
        }
    }
}
