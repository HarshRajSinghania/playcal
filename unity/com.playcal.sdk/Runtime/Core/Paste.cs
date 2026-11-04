using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Text;

namespace Playcal
{
    /// <summary>"PC0:" + base64url(zlib(jsonl)). Same format as playcal.ingest.encode_paste.</summary>
    public static class Paste
    {
        public const string Prefix = "PC0:";

        public static string Encode(IEnumerable<string> lines)
        {
            var raw = Encoding.UTF8.GetBytes(string.Join("\n", lines));
            using (var ms = new MemoryStream())
            {
                ms.WriteByte(0x78); ms.WriteByte(0xDA); // zlib header; .NET Standard 2.1 has no ZLibStream
                using (var d = new DeflateStream(ms, CompressionLevel.Optimal, leaveOpen: true)) d.Write(raw, 0, raw.Length);
                uint a = Adler32(raw);
                ms.WriteByte((byte)(a >> 24)); ms.WriteByte((byte)(a >> 16)); ms.WriteByte((byte)(a >> 8)); ms.WriteByte((byte)a);
                return Prefix + System.Convert.ToBase64String(ms.ToArray()).Replace('+', '-').Replace('/', '_');
            }
        }

        static uint Adler32(byte[] data)
        {
            uint a = 1, b = 0;
            foreach (var x in data) { a = (a + x) % 65521; b = (b + a) % 65521; }
            return (b << 16) | a;
        }
    }
}
