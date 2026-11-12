"""The candidate's CV photo (#605): what is accepted, what is stripped, what the saved file is."""

import io

import pytest
from PIL import Image

from door.core import photo


def _jpeg(size=(1600, 2000), exif=False, color=(200, 120, 40)) -> bytes:
    image = Image.new("RGB", size, color)
    buf = io.BytesIO()
    if exif:
        data = Image.Exif()
        data[0x010F] = "SecretCamera"                       # Make
        data[0x8825] = {1: "N", 2: (55.0, 40.0, 0.0), 3: "E", 4: (12.0, 34.0, 0.0)}  # GPS
        image.save(buf, "JPEG", exif=data)
    else:
        image.save(buf, "JPEG")
    return buf.getvalue()


def _png(size=(900, 900), mode="RGBA") -> bytes:
    buf = io.BytesIO()
    Image.new(mode, size, (10, 20, 30, 0) if mode == "RGBA" else (10, 20, 30)).save(buf, "PNG")
    return buf.getvalue()


def test_a_jpeg_and_a_png_are_accepted(tmp_path):
    for name, data in (("a.jpg", _jpeg()), ("b.png", _png())):
        (tmp_path / name).write_bytes(data)
        assert photo.problem(tmp_path / name) is None


@pytest.mark.parametrize("data, why", [
    (b"GIF89a....", "JPEG or PNG"),
    (b"%PDF-1.4 ...", "JPEG or PNG"),
    (b"", "empty"),
])
def test_other_files_are_refused_whatever_their_name(tmp_path, data, why):
    path = tmp_path / "me.jpg"                               # the name lies; the bytes decide
    path.write_bytes(data)
    assert why in photo.problem(path)


def test_a_missing_file_and_a_folder_are_refused(tmp_path):
    assert "not found" in photo.problem(tmp_path / "nope.jpg")
    assert "not found" in photo.problem(tmp_path)


def test_a_file_over_the_size_limit_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(photo, "MAX_BYTES", 1000)
    (tmp_path / "big.jpg").write_bytes(_jpeg())
    assert "over" in photo.problem(tmp_path / "big.jpg")


def test_a_photo_too_small_to_print_is_refused(tmp_path):
    (tmp_path / "tiny.jpg").write_bytes(_jpeg((60, 60)))
    with pytest.raises(photo.PhotoError, match="small"):
        photo.clean(tmp_path / "tiny.jpg")


def test_a_corrupt_image_is_refused(tmp_path):
    (tmp_path / "bad.jpg").write_bytes(_jpeg()[:200])
    with pytest.raises(photo.PhotoError):
        photo.clean(tmp_path / "bad.jpg")


def test_clean_scales_down_to_the_cv_photo_size_and_never_up(tmp_path):
    (tmp_path / "big.jpg").write_bytes(_jpeg((3000, 4000)))
    out = Image.open(io.BytesIO(photo.clean(tmp_path / "big.jpg")))
    assert out.width <= photo.MAX_SIZE[0] and out.height <= photo.MAX_SIZE[1]
    assert abs(out.width / out.height - 0.75) < 0.01          # the shape is kept
    (tmp_path / "small.jpg").write_bytes(_jpeg((300, 400)))
    assert Image.open(io.BytesIO(photo.clean(tmp_path / "small.jpg"))).size == (300, 400)


def test_clean_strips_exif_and_gps(tmp_path):
    (tmp_path / "me.jpg").write_bytes(_jpeg(exif=True))
    assert Image.open(tmp_path / "me.jpg").getexif().get(0x8825)   # the fixture does carry GPS
    out = Image.open(io.BytesIO(photo.clean(tmp_path / "me.jpg")))
    assert len(out.getexif()) == 0 and not out.getexif().get_ifd(0x8825)
    assert b"SecretCamera" not in photo.clean(tmp_path / "me.jpg")


def test_clean_applies_the_exif_orientation_before_dropping_it(tmp_path):
    image = Image.new("RGB", (800, 600), (255, 0, 0))
    exif = Image.Exif()
    exif[0x0112] = 6                                          # rotate 90 clockwise to view
    buf = io.BytesIO()
    image.save(buf, "JPEG", exif=exif)
    (tmp_path / "r.jpg").write_bytes(buf.getvalue())
    assert Image.open(io.BytesIO(photo.clean(tmp_path / "r.jpg"))).size == (600, 800)


def test_a_png_with_transparency_becomes_a_jpeg_on_white(tmp_path):
    (tmp_path / "t.png").write_bytes(_png())
    out = Image.open(io.BytesIO(photo.clean(tmp_path / "t.png")))
    assert out.format == "JPEG" and out.getpixel((5, 5)) == (255, 255, 255)


def test_save_writes_the_cleaned_photo_into_the_profile_folder(tmp_path):
    (tmp_path / "me.jpg").write_bytes(_jpeg(exif=True))
    target = photo.save(tmp_path / "me.jpg", tmp_path / "profile")
    assert target == tmp_path / "profile" / photo.NAME
    assert Image.open(target).format == "JPEG" and len(Image.open(target).getexif()) == 0


def test_save_refusing_leaves_the_old_photo(tmp_path):
    (tmp_path / "profile").mkdir()
    (tmp_path / "profile" / photo.NAME).write_bytes(b"old")
    (tmp_path / "x.gif").write_bytes(b"GIF89a")
    with pytest.raises(photo.PhotoError):
        photo.save(tmp_path / "x.gif", tmp_path / "profile")
    assert (tmp_path / "profile" / photo.NAME).read_bytes() == b"old"


def test_kind_reads_the_bytes():
    assert photo.kind(_jpeg()) == "jpeg" and photo.kind(_png()) == "png" and photo.kind(b"nope") is None
