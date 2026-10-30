import hashlib

from isycode.effect_fs import apply_file, digest, read_file


def test_digest():
    assert digest(None) is None

    payload = b"test payload"
    expected = hashlib.sha256(payload).hexdigest()
    assert digest((payload, 0o644)) == expected


def test_apply_and_read_file(tmp_path):
    rel_path = "sub/test.txt"
    payload = b"hello world\n"
    expected_digest = hashlib.sha256(payload).hexdigest()

    # Apply file creation (expected=None for new file)
    apply_file(tmp_path, rel_path, payload, expected=None)

    # Read file back
    read_data = read_file(tmp_path, rel_path)
    assert read_data is not None
    assert read_data[0] == payload
    assert digest(read_data) == expected_digest
