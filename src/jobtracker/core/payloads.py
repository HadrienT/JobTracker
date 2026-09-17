"""Compression of archived raw payloads — blueprint/wp/WP01-core.md §2.

Level 3: a posting description compresses 4-6x, and the project archives
roughly 150k of them a year.
"""

import zstandard

_LEVEL = 3


def pack(data: bytes) -> bytes:
    """Compress raw bytes for archival storage."""
    return zstandard.ZstdCompressor(level=_LEVEL).compress(data)


def unpack(data: bytes) -> bytes:
    """Decompress bytes produced by ``pack()``."""
    return zstandard.ZstdDecompressor().decompress(data)
