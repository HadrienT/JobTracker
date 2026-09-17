"""Deduplication fingerprint — blueprint/03-INTERFACES.md §3.4.

The algorithm itself lives in `core.hashing` (WP01): `store` needs it too,
for the same collision resolution (I4), so it could not live only here.
This module is where `cascade.py` reaches for it, keeping normalize's stage
files from importing `core.hashing` directly one by one.
"""

from jobtracker.core.hashing import fingerprint

__all__ = ["fingerprint"]
