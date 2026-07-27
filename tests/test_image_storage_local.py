from app.services.image_storage.local_storage import LocalImageStorage


def test_put_writes_file(tmp_path):
    storage = LocalImageStorage(str(tmp_path))

    storage.put("abc.png", b"image-bytes", "image/png")

    assert (tmp_path / "abc.png").read_bytes() == b"image-bytes"


def test_delete_removes_file(tmp_path):
    storage = LocalImageStorage(str(tmp_path))
    storage.put("abc.png", b"image-bytes", "image/png")

    storage.delete("abc.png")

    assert not (tmp_path / "abc.png").exists()


def test_delete_missing_key_is_a_no_op(tmp_path):
    storage = LocalImageStorage(str(tmp_path))

    storage.delete("does-not-exist.png")


def test_put_creates_base_dir_if_missing(tmp_path):
    base_dir = tmp_path / "nested" / "images"
    storage = LocalImageStorage(str(base_dir))

    storage.put("abc.png", b"image-bytes", "image/png")

    assert (base_dir / "abc.png").read_bytes() == b"image-bytes"
