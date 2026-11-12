"""Turn the phone recorder's screencast frames into an .mp4 (`DOOR_VIDEO_DIR`, see phone.record.ts).

python scripts/demo/video_from_frames.py <frames-dir> <out.mp4>: frames.json lists each frame and when it
arrived; each is held until the next one, resampled to a constant 30 fps (H.264, yuv420p, plays anywhere).
Needs an ffmpeg: `imageio-ffmpeg`'s, or one on PATH.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def ffmpeg() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        found = shutil.which("ffmpeg")
        if not found:
            raise SystemExit("no ffmpeg: pip install imageio-ffmpeg, or install ffmpeg")
        return found


def main(frames_dir: Path, out: Path) -> None:
    frames = json.loads((frames_dir / "frames.json").read_text())
    lines = []
    for i, f in enumerate(frames):
        nxt = frames[i + 1]["at"] if i + 1 < len(frames) else f["at"] + 2500
        lines.append(f"file '{Path(f['file']).resolve()}'\nduration {max(1, nxt - f['at']) / 1000:.3f}")
    lines.append(f"file '{Path(frames[-1]['file']).resolve()}'")  # the concat demuxer wants the last one twice
    listing = frames_dir / "list.txt"
    listing.write_text("\n".join(lines) + "\n")
    subprocess.run(
        [ffmpeg(), "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
         "-vf", "fps=30,scale=trunc(iw/2)*2:trunc(ih/2)*2", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-crf", "20", "-movflags", "+faststart", str(out)],
        check=True,
    )
    print(f"{out}: {len(frames)} frames, {out.stat().st_size // 1024} KB")  # noqa: T201


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
