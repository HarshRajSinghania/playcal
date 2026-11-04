using System;
using System.Globalization;
using System.Text;

namespace Playcal
{
    /// <summary>
    /// Per-frame samples for `playcal baseline`: frame time in ms and, when known, GC bytes allocated in
    /// the frame and total used memory. ToJson writes {"frame_ms":[...],"gc_alloc_bytes":[...],"used_memory_bytes":[...]}.
    /// Fixed capacity, no allocation per frame.
    /// </summary>
    public sealed class FrameSamples
    {
        readonly float[] ms;
        readonly long[] gc, mem;
        bool gcKnown = true, memKnown = true;

        public int Count { get; private set; }
        public bool Full => Count == ms.Length;

        public FrameSamples(int capacity = 36000)
        {
            if (capacity < 1) throw new ArgumentOutOfRangeException(nameof(capacity));
            ms = new float[capacity];
            gc = new long[capacity];
            mem = new long[capacity];
        }

        /// <summary>Adds one frame. A value below 0 means unknown; one unknown frame leaves that series out.</summary>
        public void Add(float frameMs, long gcBytes = -1, long usedBytes = -1)
        {
            if (Full) return;
            if (gcBytes < 0) gcKnown = false;
            if (usedBytes < 0) memKnown = false;
            ms[Count] = frameMs;
            gc[Count] = gcBytes;
            mem[Count] = usedBytes;
            Count++;
        }

        public void Clear() { Count = 0; gcKnown = memKnown = true; }

        public string ToJson()
        {
            var sb = new StringBuilder(Count * 24 + 60);
            sb.Append("{\"frame_ms\":[");
            for (int i = 0; i < Count; i++)
            {
                if (i > 0) sb.Append(',');
                sb.Append(ms[i].ToString("0.###", CultureInfo.InvariantCulture));
            }
            sb.Append(']');
            if (gcKnown && Count > 0) Series(sb, "gc_alloc_bytes", gc);
            if (memKnown && Count > 0) Series(sb, "used_memory_bytes", mem);
            return sb.Append('}').ToString();
        }

        void Series(StringBuilder sb, string name, long[] values)
        {
            sb.Append(",\"").Append(name).Append("\":[");
            for (int i = 0; i < Count; i++)
            {
                if (i > 0) sb.Append(',');
                sb.Append(values[i].ToString(CultureInfo.InvariantCulture));
            }
            sb.Append(']');
        }
    }
}
