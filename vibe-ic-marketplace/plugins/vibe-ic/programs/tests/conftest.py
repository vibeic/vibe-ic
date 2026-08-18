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


# func_src now lives in _source_pin.py — see that module for WHY.
from _source_pin import func_src  # noqa: E402,F401


# The repository root, spelled the way the tests that need it spell it: the
# first ancestor that CONTAINS `vibe-ic-marketplace/`. Resolved once here so a
# consumer of `wiring_haystack` cannot ask for one root and be handed another.
#
# `None` WHEN THERE IS NO SUCH ANCESTOR, and that matters: this conftest is
# imported in the FLATTENED install cache too (see the sys.path note above),
# where the marketplace directory is not on the path to this file. A bare
# `next(...)` raises StopIteration AT IMPORT there, which does not fail one
# test — it takes the whole session down before collection, from a default
# nobody in that layout ever asked for. Tests that pass their own root are
# unaffected; the one default that cannot be computed refuses when it is USED.
_REPO_ROOT = next((b for b in _PLUGIN_ROOT.parents
                   if (b / "vibe-ic-marketplace").is_dir()), None)


@pytest.fixture(scope="session")
def wiring_haystack():
    """`checker_execution_wiring_audit`'s tokenised whole-repo haystack, built
    at most ONCE per (session, plugin, repo root) — and re-built the moment the
    tree it was read from moves.

    WHY IT EXISTS. Building it walks every file `_haystack_sources` names and
    runs `ast.parse` + `tokenize` over the Python ones. Measured 2026-08-18 on
    this fleet: 18.93 s a call over 4024 files (3891 Python), of which 11.36 s
    is `tokenize` and 4.12 s `ast.parse`.
    `test_issue693_signoff_integrity_wiring.py` asked for the IDENTICAL one six
    times — four parametrised cases plus two `audit()` calls — and those six
    rebuilds were 134.19 s of that file's 144.83 s (`--durations=0`, idle host).

    WHY IT CANNOT GO STALE. The tree is not assumed to be still; it is CHECKED.
    Each hand-out re-reads every file `_haystack_sources` names and compares a
    sha256 of their CONTENT against the signature the cached haystack was built
    under, rebuilding on any difference. Measured at 0.10 s, i.e. 0.5% of a
    rebuild, so verifying is affordable where assuming would not have been —
    and being content-based it has no blind spot for an edit that keeps a file's
    size and mtime. A test that mutates the real tree mid-session (there is one:
    `test_issue1129_gatekeeper_prepare_landing.py` drives the real writers) can
    therefore not hand the next consumer an answer about the tree as it was.

    WHY IT IS A FIXTURE AND NOT A CACHE IN THE PROGRAM. See the note on
    `checker_execution_wiring_audit.audit`: that module's own suite proves the
    audit is deterministic by running it twice and comparing, and an internal
    memo would make that comparison unable to fail. Here re-use is opt-in, so
    every test that must re-derive simply does not request this fixture.

    READ-ONLY BY CONTRACT. Consumers look tokens up; nothing writes. A test that
    needs to MUTATE a haystack builds its own — they all already do, over
    `tmp_path`.
    """
    import checker_execution_wiring_audit as _wiring  # noqa: PLC0415

    cache: dict = {}

    def _get(plugin=None, repo_root=None):
        plugin = _PLUGIN_ROOT if plugin is None else Path(plugin)
        if repo_root is None:
            assert _REPO_ROOT is not None, (
                "wiring_haystack was asked for the default repo root, and this "
                f"checkout has no ancestor of {_PLUGIN_ROOT} containing "
                "vibe-ic-marketplace/ — pass repo_root explicitly")
            root = _REPO_ROOT
        else:
            root = Path(repo_root)
        key = (str(plugin.resolve()), str(root.resolve()))
        signature = _wiring.haystack_signature(plugin, root)
        hit = cache.get(key)
        if hit is None or hit[0] != signature:
            cache[key] = (signature,
                          _wiring._tokenise(_wiring._haystacks(plugin, root)))
        return cache[key][1]

    return _get


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
