// Records frame time, GC allocation and used memory per frame into FrameSamples, for `playcal baseline`.
using System.IO;
using Unity.Profiling;
using UnityEngine;

namespace Playcal
{
    public sealed class PlaycalFrames : MonoBehaviour
    {
        [Tooltip("Name of the file written by Save: frames-<label>.json")]
        public string label = "run";
        [Tooltip("Frames skipped at the start (loading, shader warmup)")]
        public int warmupFrames = 30;
        [Tooltip("Recording stops when this many frames are stored")]
        public int maxFrames = 36000;

        FrameSamples samples;
        ProfilerRecorder gcAlloc, usedMemory;
        int skipped;

        public FrameSamples Samples => samples;

        /// <summary>Adds a recorder that survives scene loads. Call Save when the run is over.</summary>
        public static PlaycalFrames Begin(string label = "run", int warmupFrames = 30)
        {
            var go = new GameObject("playcal frames");
            DontDestroyOnLoad(go);
            go.SetActive(false);
            var rec = go.AddComponent<PlaycalFrames>();
            rec.label = label;
            rec.warmupFrames = warmupFrames;
            go.SetActive(true);
            return rec;
        }

        void OnEnable()
        {
            samples = new FrameSamples(maxFrames);
            skipped = 0;
            gcAlloc = ProfilerRecorder.StartNew(ProfilerCategory.Memory, "GC Allocated In Frame");
            usedMemory = ProfilerRecorder.StartNew(ProfilerCategory.Memory, "Total Used Memory");
        }

        void OnDisable()
        {
            gcAlloc.Dispose();
            usedMemory.Dispose();
        }

        void Update()
        {
            if (skipped < warmupFrames) { skipped++; return; }
            samples.Add(Time.unscaledDeltaTime * 1000f, gcAlloc.Valid ? gcAlloc.LastValue : -1,
                        usedMemory.Valid ? usedMemory.LastValue : -1);
        }

        /// <summary>Writes persistentDataPath/playcal/frames-label.json and returns its path.</summary>
        public string Save()
        {
            var path = Path.Combine(Application.persistentDataPath, "playcal", $"frames-{label}.json");
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            File.WriteAllText(path, samples.ToJson());
            return path;
        }
    }
}
