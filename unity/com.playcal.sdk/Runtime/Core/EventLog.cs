// playcal event log, engine-independent so it compiles and tests outside Unity.
// Writes events that match schema/event-v0.json. No names, emails, device IDs, location or IP.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using System.Text.RegularExpressions;

namespace Playcal
{
    public sealed class EventLog
    {
        readonly string game;
        readonly string gameVersion;
        readonly string installId;
        readonly Func<DateTime> clock;
        readonly List<string> lines = new List<string>();
        readonly Dictionary<string, int> attempts = new Dictionary<string, int>();
        readonly Dictionary<string, DateTime> levelStartedAt = new Dictionary<string, DateTime>();

        /// <summary>Called with every line written, so the host can append it to a file.</summary>
        public event Action<string> LineWritten;

        /// <summary>When false, nothing is recorded (e.g. the player is under 18).</summary>
        public bool Enabled { get; set; } = true;

        public string SessionId { get; private set; }
        public IReadOnlyList<string> Lines => lines;

        public EventLog(string game, string gameVersion, string installId, Func<DateTime> clock = null)
        {
            this.game = Check(game, 64, nameof(game));
            this.gameVersion = Check(gameVersion, 32, nameof(gameVersion));
            if (!Regex.IsMatch(installId ?? "", "^[A-Za-z0-9_-]{8,64}$"))
                throw new ArgumentException("installId must be 8-64 chars of A-Z a-z 0-9 _ -", nameof(installId));
            this.installId = installId;
            this.clock = clock ?? (() => DateTime.UtcNow);
            SessionId = NewId(12);
        }

        /// <summary>Random, URL-safe id. Never derived from the device.</summary>
        public static string NewId(int length = 16)
        {
            const string alphabet = "abcdefghijklmnopqrstuvwxyz0123456789";
            var bytes = Guid.NewGuid().ToByteArray();
            var extra = Guid.NewGuid().ToByteArray();
            var sb = new StringBuilder(length);
            for (int i = 0; i < length; i++)
                sb.Append(alphabet[(i < 16 ? bytes[i] : extra[i % 16]) % alphabet.Length]);
            return sb.ToString();
        }

        /// <summary>Rebuild attempt counters from lines saved in earlier sessions.</summary>
        public void Restore(IEnumerable<string> savedLines)
        {
            var re = new Regex("\"type\":\"level_start\",\"level\":\"((?:[^\"\\\\]|\\\\.)*)\",\"attempt\":(\\d+)");
            foreach (var line in savedLines)
            {
                var m = re.Match(line);
                if (!m.Success) continue;
                var level = Regex.Unescape(m.Groups[1].Value);
                int n = int.Parse(m.Groups[2].Value, CultureInfo.InvariantCulture);
                if (!attempts.TryGetValue(level, out var cur) || n > cur) attempts[level] = n;
            }
        }

        public void SessionStart(IDictionary<string, object> props = null) => Write("session_start", null, 0, null, props);
        public void SessionEnd() => Write("session_end", null, 0, null, null);

        /// <summary>Starts the next attempt of this level. Attempt numbers keep counting across sessions.</summary>
        public int LevelStart(string level, long? seed = null)
        {
            Check(level, 64, nameof(level));
            attempts.TryGetValue(level, out var n);
            attempts[level] = ++n;
            levelStartedAt[level] = clock();
            var f = new Fields();
            if (seed.HasValue) f.Add("seed", seed.Value);
            Write("level_start", level, n, f, null);
            return n;
        }

        public void Move(string level, int movesUsed, int? movesLeft = null, int? goalLeft = null) =>
            Write("move", level, Current(level), Counts(movesUsed, movesLeft, goalLeft), null);

        public void LevelFail(string level, int? movesUsed = null, int? movesLeft = null, int? goalLeft = null) => End("level_fail", level, movesUsed, movesLeft, goalLeft);
        public void LevelComplete(string level, int? movesUsed = null, int? movesLeft = null, int? goalLeft = null) => End("level_complete", level, movesUsed, movesLeft, goalLeft);
        public void LevelQuit(string level, int? movesUsed = null, int? movesLeft = null, int? goalLeft = null) => End("level_quit", level, movesUsed, movesLeft, goalLeft);

        /// <summary>One short line the player can paste into any chat. See playcal ingest --paste.</summary>
        public string ToPaste() => Paste.Encode(lines);

        void End(string type, string level, int? movesUsed, int? movesLeft, int? goalLeft)
        {
            var f = Counts(movesUsed, movesLeft, goalLeft);
            if (levelStartedAt.TryGetValue(level, out var t0))
            {
                f.Add("duration_ms", Math.Max(0L, (long)(clock() - t0).TotalMilliseconds));
                levelStartedAt.Remove(level);
            }
            Write(type, level, Current(level), f, null);
        }

        int Current(string level)
        {
            if (!attempts.TryGetValue(level, out var n))
                throw new InvalidOperationException($"LevelStart(\"{level}\") was not called first");
            return n;
        }

        static Fields Counts(int? used, int? left, int? goal)
        {
            var f = new Fields();
            if (used.HasValue) f.Add("moves_used", NonNegative(used.Value, "movesUsed"));
            if (left.HasValue) f.Add("moves_left", NonNegative(left.Value, "movesLeft"));
            if (goal.HasValue) f.Add("goal_left", NonNegative(goal.Value, "goalLeft"));
            return f;
        }

        void Write(string type, string level, int attempt, Fields extra, IDictionary<string, object> props)
        {
            if (!Enabled) return;
            var sb = new StringBuilder(160);
            sb.Append("{\"v\":0,\"ts\":").Append(Json.Str(clock().ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:ss.fff'Z'", CultureInfo.InvariantCulture)));
            sb.Append(",\"install_id\":").Append(Json.Str(installId));
            sb.Append(",\"session_id\":").Append(Json.Str(SessionId));
            sb.Append(",\"game\":").Append(Json.Str(game));
            sb.Append(",\"game_version\":").Append(Json.Str(gameVersion));
            sb.Append(",\"type\":").Append(Json.Str(type));
            if (level != null) sb.Append(",\"level\":").Append(Json.Str(level)).Append(",\"attempt\":").Append(attempt.ToString(CultureInfo.InvariantCulture));
            if (extra != null) foreach (var kv in extra.Items) sb.Append(",\"").Append(kv.Key).Append("\":").Append(kv.Value.ToString(CultureInfo.InvariantCulture));
            if (props != null && props.Count > 0) sb.Append(",\"props\":").Append(Json.Object(props));
            sb.Append('}');
            var line = sb.ToString();
            lines.Add(line);
            LineWritten?.Invoke(line);
        }

        static string Check(string s, int max, string name)
        {
            if (string.IsNullOrEmpty(s) || s.Length > max) throw new ArgumentException($"{name} must be 1-{max} characters", name);
            return s;
        }

        static int NonNegative(int v, string name) => v >= 0 ? v : throw new ArgumentOutOfRangeException(name, "must be >= 0");

        sealed class Fields
        {
            public readonly List<KeyValuePair<string, long>> Items = new List<KeyValuePair<string, long>>();
            public void Add(string k, long v) => Items.Add(new KeyValuePair<string, long>(k, v));
        }
    }

    static class Json
    {
        public static string Str(string s)
        {
            var sb = new StringBuilder(s.Length + 2).Append('"');
            foreach (var c in s)
            {
                switch (c)
                {
                    case '"': sb.Append("\\\""); break;
                    case '\\': sb.Append("\\\\"); break;
                    case '\n': sb.Append("\\n"); break;
                    case '\r': sb.Append("\\r"); break;
                    case '\t': sb.Append("\\t"); break;
                    default:
                        if (c < 0x20) sb.Append("\\u").Append(((int)c).ToString("x4", CultureInfo.InvariantCulture));
                        else sb.Append(c);
                        break;
                }
            }
            return sb.Append('"').ToString();
        }

        /// <summary>Flat object; values may be string, bool, integer or floating point.</summary>
        public static string Object(IDictionary<string, object> d)
        {
            var sb = new StringBuilder("{");
            bool first = true;
            foreach (var kv in d)
            {
                if (!first) sb.Append(',');
                first = false;
                sb.Append(Str(kv.Key)).Append(':');
                switch (kv.Value)
                {
                    case null: sb.Append("null"); break;
                    case string s: sb.Append(Str(s)); break;
                    case bool b: sb.Append(b ? "true" : "false"); break;
                    case float f: sb.Append(f.ToString("R", CultureInfo.InvariantCulture)); break;
                    case double x: sb.Append(x.ToString("R", CultureInfo.InvariantCulture)); break;
                    case IFormattable n: sb.Append(n.ToString(null, CultureInfo.InvariantCulture)); break;
                    default: throw new ArgumentException($"props[{kv.Key}]: only string, bool and numbers are allowed");
                }
            }
            return sb.Append('}').ToString();
        }
    }
}
