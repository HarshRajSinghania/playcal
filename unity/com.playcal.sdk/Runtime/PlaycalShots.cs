// Saves a screenshot as a PNG that `playcal visual` reads.
using System.Collections;
using System.IO;
using UnityEngine;

namespace Playcal
{
    public static class PlaycalShots
    {
        /// <summary>persistentDataPath/playcal/shots/name.png</summary>
        public static string PathFor(string name) =>
            Path.Combine(Application.persistentDataPath, "playcal", "shots", name + ".png");

        /// <summary>Writes the screen (UI included) to PathFor(name) at the end of the frame. Use it from a
        /// coroutine or a UnityTest: yield return PlaycalShots.Capture("level4-start"). In batch mode the end
        /// of frame never comes, so there it renders Camera.main through CaptureCamera instead.</summary>
        public static IEnumerator Capture(string name)
        {
            if (Application.isBatchMode)
            {
                CaptureCamera(name, Camera.main);
                yield break;
            }
            yield return new WaitForEndOfFrame();
            var tex = ScreenCapture.CaptureScreenshotAsTexture();
            try { Write(name, tex); }
            finally { Object.Destroy(tex); }
        }

        /// <summary>Renders one camera into a texture and writes it to PathFor(name) right away. Works in
        /// batch mode (not with -nographics). Screen-space overlay UI isn't in the picture.</summary>
        public static string CaptureCamera(string name, Camera cam, int width = 640, int height = 360)
        {
            if (cam == null) throw new System.ArgumentNullException(nameof(cam), "no camera to capture");
            var rt = RenderTexture.GetTemporary(width, height, 24);
            var tex = new Texture2D(width, height, TextureFormat.RGBA32, false);
            var (oldTarget, oldActive) = (cam.targetTexture, RenderTexture.active);
            try
            {
                cam.targetTexture = rt;
                cam.Render();
                RenderTexture.active = rt;
                tex.ReadPixels(new Rect(0, 0, width, height), 0, 0);
                tex.Apply();
                return Write(name, tex);
            }
            finally
            {
                cam.targetTexture = oldTarget;
                RenderTexture.active = oldActive;
                RenderTexture.ReleaseTemporary(rt);
                Object.Destroy(tex);
            }
        }

        static string Write(string name, Texture2D tex)
        {
            var path = PathFor(name);
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            File.WriteAllBytes(path, tex.EncodeToPNG());
            return path;
        }
    }
}
