"""programs/tests/conftest.py — unified test-tree conftest.

v0.2.19: the two former test trees (programs/tests/ unit tests + the
plugin-level tests/ integration/regression gates) were merged into this
single tree (user directive "let two test folders be one"). The split had
caused real regressions to be missed because `pytest programs/tests/` alone
skipped the gate tree. Now `testpaths = programs/tests` is the whole suite.

This conftest makes every test importable regardless of which tree it came
from, by putting BOTH `programs/` and the plugin root on sys.path. Tests
that came from the old plugin-level tests/ used to compute the plugin root
as Path(__file__).resolve().parents[1]; after the move they sit one level
deeper, so any data-path that relied on parents[N] was re-pointed at move
time. Bare module imports (`import <prog>`) all resolve via the two entries
below.
"""
from __future__ import annotations

import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent       # .../programs/tests
_PROGRAMS = _TESTS_DIR.parent                       # .../programs
_PLUGIN_ROOT = _PROGRAMS.parent                     # .../vibe-ic

for _p in (str(_PROGRAMS), str(_PLUGIN_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# flow #486: also put the tests dir on sys.path so the shared plugin-root
# resolver (`import _plugin_tree`) and sibling-test imports resolve by bare
# name in BOTH the source monorepo and the flattened install cache.
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))


# Preserved from the former tests/conftest.py (#401): read a hand-extracted,
# chip-AGNOSTIC real-benchmark fixture slice. Fixtures now live under
# programs/tests/fixtures/real_benchmark/ (moved with the merge).
_REAL_BENCHMARK_DIR = _TESTS_DIR / "fixtures" / "real_benchmark"


def load_real_fixture(name: str) -> str:
    """Read a real-benchmark fixture from
    `programs/tests/fixtures/real_benchmark/<name>` and return its UTF-8 text.
    Chip-AGNOSTIC: fixtures carry no chip-class literal.
    """
    return (_REAL_BENCHMARK_DIR / name).read_text(encoding="utf-8")
