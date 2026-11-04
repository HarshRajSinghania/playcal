import json
import random
import struct
import subprocess
import sys
import zlib

from playcal.visual import SIG, diff, read_png, write_png


def encode(path, w, h, rows, ctype, bpp):
    """Test-side PNG writer that uses every filter type, to exercise the reader's unfiltering."""
    chunk = lambda k, b: struct.pack(">I", len(b)) + k + b + struct.pack(">I", zlib.crc32(k + b))
    raw, prev = bytearray(), bytes(w * bpp)
    for y, row in enumerate(rows):
        f = y % 5
        out = bytearray()
        for i, v in enumerate(row):
            a = row[i - bpp] if i >= bpp else 0
            b, c = prev[i], (prev[i - bpp] if i >= bpp else 0)
            if f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if pa <= pb and pa <= pc else b if pb <= pc else c
            else:
                pred = [0, a, b, (a + b) // 2][f]
            out.append((v - pred) & 255)
        raw += bytes([f]) + out
        prev = row
    path.write_bytes(SIG + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, ctype, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(bytes(raw))) + chunk(b"IEND", b""))


def test_reader_undoes_every_filter(tmp_path):
    rnd = random.Random(1)
    w, h = 7, 10
    rgb = [bytes(rnd.randrange(256) for _ in range(w * 3)) for _ in range(h)]
    encode(tmp_path / "a.png", w, h, rgb, 2, 3)
    _, _, rows = read_png(tmp_path / "a.png")
    assert [r[0::4] + r[1::4] for r in rows] == [r[0::3] + r[1::3] for r in rgb]
    assert all(r[3::4] == b"\xff" * w for r in rows)
    write_png(tmp_path / "b.png", w, h, rows)
    assert read_png(tmp_path / "b.png")[2] == rows


def test_diff_counts_only_pixels_over_tolerance():
    base = (4, 2, [b"\x10\x10\x10\xff" * 4, b"\x10\x10\x10\xff" * 4])
    new = (4, 2, [b"\x14\x10\x10\xff" * 4, b"\x10\x10\x10\xff" * 3 + b"\xff\x10\x10\xff"])
    out, rows = diff(base, new, tolerance=8)
    assert (out["changed_pixels"], out["box"]) == (1, [3, 1, 3, 1])
    assert rows[1][12:16] == b"\xff\x00\x00\xff"
    assert diff(base, (2, 2, base[2]))[0]["same_size"] is False


def test_cli_save_then_check(tmp_path):
    w, h = 10, 10
    rows = [b"\x20\x40\x60\xff" * w for _ in range(h)]
    write_png(tmp_path / "shot.png", w, h, rows)
    run = lambda *a: subprocess.run([sys.executable, "-m", "playcal", "visual", *a, "--dir", str(tmp_path / "b"), "--json"],
                                    capture_output=True, text=True)
    assert run("save", "lvl", str(tmp_path / "shot.png")).returncode == 0
    r = run("check", "lvl", str(tmp_path / "shot.png"))
    assert r.returncode == 0 and json.loads(r.stdout)["verdict"] == "ok"
    rows[5] = b"\x20\x40\x60\xff" * 5 + b"\xff\xff\xff\xff" * 5
    write_png(tmp_path / "shot2.png", w, h, rows)
    r = run("check", "lvl", str(tmp_path / "shot2.png"))
    out = json.loads(r.stdout)
    assert r.returncode == 1 and out["changed_pixels"] == 5 and (tmp_path / "b" / "lvl.diff.png").exists()
