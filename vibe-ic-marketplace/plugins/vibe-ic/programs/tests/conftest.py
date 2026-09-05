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

import ast
import re
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent       # .../programs/tests

# ---------------------------------------------------------------------------
# NDA token store for the suite. The real tokens no longer ship in tracked
# source (they resolve from the private config at runtime), so the suite
# supplies its own FICTIONAL set through the SAME channel a configured host
# uses. This is set before any test module imports `_commercial_pdk`, and it is
# inherited by every gate subprocess the tests spawn.
#
# NOT `setdefault`, and the difference is a measured red. The intent — "a host
# that genuinely has the real tokens configured keeps them, so the suite
# measures that host as it is" — is preserved exactly. What `setdefault` also
# preserved was a NAME WITH NOTHING IN IT: `VIBEIC_NDA_TOKENS=` (the shape a
# harness produces with `docker run -e VIBEIC_NDA_TOKENS=`, and any blank or
# unparseable value) is present, so nothing was supplied, and
# `_commercial_pdk._nda_token_map` resolves it to `{}` — which every builder
# turns into `NoNdaLiterals`.
#
# MEASURED on tree 5e850b3acee8, image ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2,
# with `VIBEIC_NDA_TOKENS=` exported into the container:
#
#     NO_NDA_TOKENS: no NDA token store on this host; the NDA panel cannot
#     answer. A caller must report NOT_MEASURED, never PASS.
#
# rc=2 from `source_chip_agnostic_check`, and
# test_v1_0_68_issue707r2_shapeb_tb_inferred_order::test_chip_agnostic_guard
# reads it as a red about the TREE. It is not: it is a fact about the harness.
# The right answer is not to accept rc=2 (that would blind the strictest guard
# in this repo in CI) and not to ship a token; it is to notice that a blank
# value is the ABSENCE of a store wearing its name, and supply the fictional
# set exactly as if the variable had been unset.
#
# A store is kept only when it parses as an object holding at least one
# non-blank literal — the same bar `_nda_token_map` applies to it.
# ---------------------------------------------------------------------------
import json as _json                                 # noqa: E402
import os as _os                                     # noqa: E402

if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))
from _nda_fixture_tokens import FICTIONAL_NDA_TOKENS  # noqa: E402


def _is_usable_token_store(raw) -> bool:
    """True when `raw` carries at least one token, the way the reader reads it."""
    if not raw:
        return False
    try:
        data = _json.loads(raw)
    except (TypeError, ValueError):
        return False
    return isinstance(data, dict) and any(
        isinstance(v, str) and v.strip() for v in data.values())


if not _is_usable_token_store(_os.environ.get("VIBEIC_NDA_TOKENS")):
    _os.environ["VIBEIC_NDA_TOKENS"] = _json.dumps(FICTIONAL_NDA_TOKENS)
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


# A landing binds the production corpus with BOTH variables below.  Synthetic
# corpus tests opt in to this fixture at module scope; production-corpus tests
# deliberately do not.  This boundary matters: a global autouse fixture made
# collection-time ``needs_corpus`` decisions disagree with the test body.
@pytest.fixture
def landing_corpus_binding_is_test_local(monkeypatch):
    monkeypatch.delenv("GATEKEEPER_BENCHMARK_DATA_SHA", raising=False)
    monkeypatch.delenv("VIBE_IC_BENCHMARK_DATA", raising=False)
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


# func_src now lives in _source_pin.py — see that module for WHY.
from _source_pin import func_src  # noqa: E402,F401


# vibe-ic#1037 — a test that claims to examine REAL data must say WHICH file it
# examined, in the suite's own output, so the next reader sees the premise
# rather than trusting the test's name. `_real_data.select` records every
# selection and every refusal; this prints them on EVERY run, pass or fail,
# with no flag. A `real-data provenance` section that is missing a test you
# expected to see is itself the finding.
def pytest_terminal_summary(terminalreporter, exitstatus, config):  # noqa: ARG001
    try:
        from _real_data import ledger_lines
    except Exception:  # pragma: no cover - the suite must not die on disclosure
        return
    lines = ledger_lines()
    if not lines:
        return
    terminalreporter.write_sep("-", "real-data provenance")
    for line in lines:
        terminalreporter.write_line(line)
