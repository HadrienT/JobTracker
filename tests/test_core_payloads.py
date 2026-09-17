from jobtracker.core.payloads import pack, unpack


def test_pack_unpack_round_trips_utf8() -> None:
    original = "Développeur quant — Paris, France · CDI · f/h".encode()
    assert unpack(pack(original)) == original


def test_pack_unpack_round_trips_empty_bytes() -> None:
    assert unpack(pack(b"")) == b""


def test_pack_compresses_repetitive_text() -> None:
    original = ("quantitative developer " * 200).encode()
    assert len(pack(original)) < len(original)
