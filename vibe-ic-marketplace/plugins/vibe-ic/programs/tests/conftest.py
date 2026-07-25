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

import re
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent       # .../programs/tests
_PROGRAMS = _TESTS_DIR.parent                       # .../programs
_PLUGIN_ROOT = _PROGRAMS.parent                     # .../vibe-ic


# Test-hygiene (#574 companion): several plugin programs run `vvp` on a testbench
# that carries `$dumpfile("wave.vcd")`; when a test invokes such a program from
# the programs/ cwd the dump lands in the plugin tree and trips the waveform-
# hygiene gate on a FULL-suite run (order-dependent). Snapshot the *.vcd present
# BEFORE any test runs — a genuinely COMMITTED dump is in this baseline, so the
# hygiene gate still catches it (non-masking) — and after each test remove only a
# *.vcd a test NEWLY created. Robust to any vvp-leaking program, present or future.
_VCD_BASELINE = {p.resolve() for p in _PROGRAMS.glob("*.vcd")}


@pytest.fixture(autouse=True)
def _clean_stray_waveform_dumps():
    yield
    for _vcd in _PROGRAMS.glob("*.vcd"):
        if _vcd.resolve() not in _VCD_BASELINE:
            try:
                _vcd.unlink()
            except OSError:
                pass


# #204 — the flow runner spawns a DETACHED (start_new_session) web dashboard by
# default; nothing in a test reaps it, so any test that drives
# vibe_ic_one_shot_runner.main() used to leak an orphan daemon that squats the
# port and stalls later runs (the suite leaked ~30 across two hosts). Set
# VIBE_IC_NO_DASHBOARD for EVERY test so `_launch_dashboard` suppresses the
# spawn at the source. Tests that genuinely need a real daemon spawn it through
# the reaping `_dashboard_daemon` fixture (test_issue204_*), which bypasses this
# guard and stops its own child on teardown.
@pytest.fixture(autouse=True)
def _no_leaked_dashboard_daemon(monkeypatch):
    monkeypatch.setenv("VIBE_IC_NO_DASHBOARD", "1")
    yield

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


def func_src(src: str, name: str) -> str:
    """Source of exactly ONE top-level function: from its `def` to the next one.

    Source-pin tests assert that a program's implementation still contains some
    token. They used to scope that with a magic character count
    (``src[i:i + 6800]``), which is wrong in BOTH directions as the file evolves:

      * window too SHORT -> **false FAIL**. `_report_check_types_tcl` grew to
        1845 chars, so a 1200-char window stopped before the marker it asserts
        (offset 1763) and the test failed on correct code.
      * window too LONG  -> **false PASS**. A 6800-char window over
        `_emit_spef_sta` (really 6323) bled 477 chars into the NEXT function, so
        an assertion could be satisfied by a neighbouring function's text —
        precisely the regression a source-pin exists to catch.

    Anchoring on the real function extent removes both failure modes and needs
    no maintenance when the file grows.
    """
    i = src.index(f"def {name}")
    m = re.search(r"\ndef ", src[i + 1:])
    return src[i:i + 1 + m.start()] if m else src[i:]
