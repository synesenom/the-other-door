"""The candidate's CV photo (#605): a JPEG or PNG the user adds, checked and cleaned before it is
kept as `profile/photo.jpg`.

`problem` is the cheap check (type by the file's bytes, never its name, and size) that `Profile`
and `compile` use on whatever the `photo` key names; `clean` and `save` are what the `save_photo`
tool does: apply the EXIF orientation, drop every piece of metadata (camera, GPS), flatten
transparency onto white and scale down to the size a CV photo is printed at, so a phone picture of
8 MB with a location in it becomes a small, anonymous JPEG. Pure of the network; no `print`.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

NAME = "photo.jpg"                  # what `save` writes in the profile folder
MAX_BYTES = 10 * 1024 * 1024        # the largest file accepted
MAX_SIZE = (600, 800)               # the largest a saved photo is: 3:4, plenty for a 3.5 cm print
MIN_SIDE = 200                      # a smaller one prints blurred
QUALITY = 88

Image.MAX_IMAGE_PIXELS = 60_000_000  # a decompression bomb is refused, not decoded


class PhotoError(ValueError):
    """The photo cannot be used; the message says why, in a line fit for a form."""


def kind(data: bytes) -> str | None:
    """``"jpeg"`` or ``"png"`` by the first bytes of ``data``; ``None`` for anything else."""
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    return None


def _head(path: Path) -> bytes:
    with Path(path).open("rb") as f:
        return f.read(16)


def problem(path) -> str | None:
    """Why ``path`` cannot be a photo (missing, empty, over `MAX_BYTES`, not a JPEG or PNG), or ``None``."""
    path = Path(path)
    try:
        if not path.is_file():
            return f"the photo was not found: {path}"
        size = path.stat().st_size
        if size == 0:
            return "the photo file is empty"
        if size > MAX_BYTES:
            return f"the photo is over {MAX_BYTES // (1024 * 1024)} MB"
        if kind(_head(path)) is None:
            return "the photo must be a JPEG or PNG picture"
    except OSError as exc:
        return f"the photo could not be read: {exc.strerror or exc}"
    return None


def clean(path) -> bytes:
    """The photo at ``path`` as the JPEG that is kept: upright, without metadata, on white, scaled down.

    Raises:
        PhotoError: it is not a usable JPEG or PNG (see `problem`), cannot be decoded, or is too small.
    """
    why = problem(path)
    if why:
        raise PhotoError(why)
    try:
        with Image.open(path) as opened:
            opened.load()
            image = ImageOps.exif_transpose(opened)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError, ValueError):
        raise PhotoError("the picture could not be read; it may be damaged") from None
    if min(image.size) < MIN_SIDE:
        raise PhotoError(f"the picture is too small ({image.width} x {image.height} px); use one at least {MIN_SIDE} px on each side")
    if image.mode in ("RGBA", "LA", "P"):
        rgba = image.convert("RGBA")
        flat = Image.new("RGB", rgba.size, (255, 255, 255))
        flat.paste(rgba, mask=rgba.getchannel("A"))
        image = flat
    else:
        image = image.convert("RGB")
    image.thumbnail(MAX_SIZE, Image.LANCZOS)  # only ever smaller
    out = io.BytesIO()
    image.save(out, "JPEG", quality=QUALITY, optimize=True)  # no exif= and no icc: no metadata is written
    return out.getvalue()


def save(source, profile_dir) -> Path:
    """`clean` the photo at ``source`` into ``profile_dir/photo.jpg`` (replacing the old one only once the new
    one is ready) and return that path.

    Raises:
        PhotoError: see `clean`; nothing is written.
    """
    data = clean(source)
    target = Path(profile_dir) / NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    scratch = target.with_name(NAME + ".tmp")
    scratch.write_bytes(data)
    scratch.replace(target)
    return target
