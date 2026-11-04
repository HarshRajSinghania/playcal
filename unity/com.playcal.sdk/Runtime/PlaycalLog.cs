// Unity glue for Playcal.EventLog: keeps the install id in PlayerPrefs and the log in persistentDataPath.
using System.Collections.Generic;
using System.IO;
using UnityEngine;

namespace Playcal
{
    public static class PlaycalLog
    {
        const string InstallKey = "playcal.install_id";
        const string Under18Key = "playcal.under18";
        static string path, initGame, initVersion;

        /// <summary>The running log. Null until Init is called.</summary>
        public static EventLog Current { get; private set; }

        /// <summary>Call once at startup. Defaults to Application.productName and Application.version.</summary>
        public static EventLog Init(string game = null, string gameVersion = null)
        {
            if (Current != null) return Current;
            initGame = game; initVersion = gameVersion;
            var id = PlayerPrefs.GetString(InstallKey, "");
            if (id.Length < 8) { id = EventLog.NewId(); PlayerPrefs.SetString(InstallKey, id); PlayerPrefs.Save(); }

            path = Path.Combine(Application.persistentDataPath, "playcal", "events.jsonl");
            Directory.CreateDirectory(Path.GetDirectoryName(path));

            var log = new EventLog(game ?? Application.productName, gameVersion ?? Application.version, id);
            log.Enabled = PlayerPrefs.GetInt(Under18Key, 0) == 0;
            if (File.Exists(path)) log.Restore(File.ReadAllLines(path));
            log.LineWritten += line => File.AppendAllText(path, line + "\n");
            Application.quitting += log.SessionEnd;
            Current = log;
            return log;
        }

        /// <summary>
        /// The two optional questions. Under 18 turns recording off and wipes the local log.
        /// ageBand examples: "18-24", "25-34", "35+". Pass null to skip a question.
        /// </summary>
        public static void StartSession(bool underEighteen, bool? playsGenre = null, string ageBand = null)
        {
            var log = Current ?? Init();
            PlayerPrefs.SetInt(Under18Key, underEighteen ? 1 : 0);
            PlayerPrefs.Save();
            if (underEighteen) { DeleteMyData(); return; }
            log.Enabled = true;
            var props = new Dictionary<string, object>();
            if (playsGenre.HasValue) props["plays_genre"] = playsGenre.Value;
            if (!string.IsNullOrEmpty(ageBand)) props["age_band"] = ageBand;
            log.SessionStart(props);
        }

        /// <summary>The "send result" text. Copies it to the clipboard and returns it.</summary>
        public static string CopyResult()
        {
            var lines = path != null && File.Exists(path) ? File.ReadAllLines(path) : new string[0];
            var text = Paste.Encode(lines);
            GUIUtility.systemCopyBuffer = text;
            return text;
        }

        /// <summary>Wipes the local log and resets the install id. Current is replaced by a fresh log, never left null.</summary>
        public static void DeleteMyData()
        {
            if (path != null && File.Exists(path)) File.Delete(path);
            PlayerPrefs.DeleteKey(InstallKey);
            PlayerPrefs.Save();
            if (Current != null) Application.quitting -= Current.SessionEnd;
            Current = null;
            Init(initGame, initVersion);
        }
    }
}
