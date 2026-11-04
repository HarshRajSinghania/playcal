using System;
using System.Globalization;
using System.Text;

namespace Playcal
{
    /// <summary>
    /// Per-frame samples for `playcal baseline`: frame time in ms and, when known, GC bytes allocated in
    /// the frame. ToJson writes {"frame_ms":[...],"gc_alloc_bytes":[...]}. Fixed capacity, no allocation per frame.
    /// </summary>
    public sealed class FrameSamples
    {
        readonly float[] ms;
        readonly long[] gc;
        bool gcKnown = true;

        public int Count { get; private set; }
        public bool Full => Count == ms.Length;

        public FrameSamples(int capacity = 36000)
        {
            if (capacity < 1) throw new ArgumentOutOfRangeException(nameof(capacity));
            ms = new float[capacity];
            gc = new long[capacity];
        }

        /// <summary>Adds one frame. gcBytes below 0 means unknown; one unknown frame leaves gc_alloc_bytes out.</summary>
        public void Add(float frameMs, long gcBytes = -1)
        {
            if (Full) return;
            if (gcBytes < 0) gcKnown = false;
            ms[Count] = frameMs;
            gc[Count] = gcBytes;
            Count++;
        }

        public void Clear() { Count = 0; gcKnown = true; }

        public string ToJson()
        {
            var sb = new StringBuilder(Count * 12 + 40);
            sb.Append("{\"frame_ms\":[");
            for (int i = 0; i < Count; i++)
            {
                if (i > 0) sb.Append(',');
                sb.Append(ms[i].ToString("0.###", CultureInfo.InvariantCulture));
            }
            sb.Append(']');
            if (gcKnown && Count > 0)
            {
                sb.Append(",\"gc_alloc_bytes\":[");
                for (int i = 0; i < Count; i++)
                {
                    if (i > 0) sb.Append(',');
                    sb.Append(gc[i].ToString(CultureInfo.InvariantCulture));
                }
                sb.Append(']');
            }
            return sb.Append('}').ToString();
        }
    }
}
