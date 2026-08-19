#!/usr/bin/env python3
"""A scored run recorded WHICH TOOLS ran and never WHICH PROCESS — W6, part 2.

THE GAP THESE TESTS BIND
========================
`benchmark_run_manifest` exists so a scored run leaves behind what a later
comparison needs. Its own list of that: verdicts, dataset+sha256,
plugin_version, `image`, scorer_argv. `image` is the toolchain digest — the
answer to "which tools ran". Nothing answered "against which process data",
and a benchmark number is a claim about both.

MEASURED on `origin/main` before a line of this was written:

    62 published evaluation run directories   0 name a PDK revision anywhere
    62 of those                               kept no tool log at all
    a manifest with no PDK field              `check` returned rc=0 PASS

The sign-off-cell channel had been closed already (`benchmark_evidence_publish`
REFUSES a cell that cannot name its revision). The scored-run channel had not,
and it is the channel `tools/gatekeeper-land.sh` gates on every landing — so a
number could reach the published corpus with its toolchain named and its
process anonymous, and the only gate that reads the run's own record said PASS.

THE CONTROL PAIR, and which half is which
-----------------------------------------
`test_a_manifest_that_names_no_process_*` are the FIRING half: each fails
against the pre-change program, which writes and accepts exactly that manifest.
`test_*_is_accepted` are the CLEARS half and are meaningless alone — before the
field existed they passed vacuously. They are a control only together.

THE THIRD STATE, and why it is not a softening
----------------------------------------------
A scored run is not a sign-off cell. Some runs synthesise against a library and
some are pure RTL simulation that opens no process data at all, so a blanket
"name a revision" would refuse the second kind for a property it correctly does
not have. What is admitted is exactly one extra state and only when the record's
OWN NUMBERS establish it — the run's tools were observed and were observed to
open nothing. `logs_scanned == 0` is "nobody looked" and is admitted by nothing.
`test_a_hand_claimed_*` are the tests that hold that line.

EVERY FIXTURE IS SYNTHESIZED. `procx` / `cellsA` are placeholders and the
revisions are arbitrary hex with no meaning. No process, foundry, node, SKU,
vendor or design identifier appears in this file.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROGRAMS = _HERE.parent
for _p in (str(_PROGRAMS), str(_HERE)):
    if _p not in sys.path:                          # pragma: no cover - path setup
        sys.path.insert(0, _p)

import benchmark_run_manifest as brm                # noqa: E402
import pdk_revision_resolve as prr                  # noqa: E402

MANIFEST = _PROGRAMS / "benchmark_run_manifest.py"

_REV = "4f2b8c1d9e0a7361bd52c48af90136e7ab2d5c80"
_REV_OTHER = "0011223344556677889900aabbccddeeff001122"


@pytest.fixture
def log_safe_tmp(tmp_path):
    """A temp root whose path survives a round trip through a TEXT LOG.

    Same reason as `test_w6_pdk_revision_is_recorded.py`'s fixture of this
    name: the pinned EDA image reports `$USER` as `1000\\ndesigner`, with a
    real newline, and pytest roots `tmp_path` under it. A path with a newline
    cannot be recovered from a log line at all. These tests derive the PDK tree
    from a log, so they need a clean root; that is a property of the host, not
    of the code under test.
    """
    if "\n" not in str(tmp_path):
        yield tmp_path
        return
    d = Path(tempfile.mkdtemp(prefix="w6man_"))
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------------------
# Fixtures: three run shapes, distinguished only by what their logs say.
# ---------------------------------------------------------------------------

def _scored(run: Path) -> Path:
    """A run directory carrying a scorer output and a dataset."""
    run.mkdir(parents=True, exist_ok=True)
    (run / "scorer.json").write_text(json.dumps(
        {"results": [{"design": "alpha", "verdict": "PASS"},
                      {"design": "beta", "verdict": "FAIL"}]}))
    (run / "ds.txt").write_text("dataset\n")
    return run


def _run_that_read_a_pdk(base: Path, revision: str = _REV) -> Path:
    """A scored run whose own tool log names a library under a tree that
    declares `revision`."""
    run = _scored(base / "run_pdk")
    store = run / "pdkstore" / "versions" / revision / "procx"
    (store / "libs.ref" / "cellsA" / "lib").mkdir(parents=True, exist_ok=True)
    (store / "SOURCES").write_text(f"upstream_pdk {revision}\n")
    lib = store / "libs.ref" / "cellsA" / "lib" / "cellsA__tt.lib"
    lib.write_text("/* synthesized liberty stub */\n")
    (run / "synth.log").write_text(f"reading liberty {lib}\n")
    return run


def _run_that_read_no_pdk(base: Path) -> Path:
    """A scored run that kept a tool log, and whose log names no library."""
    run = _scored(base / "run_nopdk")
    (run / "sim.log").write_text("simulation finished, 2 tests\n")
    return run


def _run_that_kept_no_log(base: Path) -> Path:
    """A scored run that destroyed the only evidence of what it read."""
    return _scored(base / "run_nolog")


def _emit(run: Path, extra=()) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MANIFEST), "emit", str(run),
         "--scorer-output", str(run / "scorer.json"),
         "--dataset", str(run / "ds.txt"),
         "--plugin-version", "0.0.0-test",
         "--image", "sha256:" + "0" * 12,
         "--scorer-argv", "score --x", *extra],
        capture_output=True, text=True, timeout=300)


def _check(run: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(MANIFEST), "check", str(run)],
                          capture_output=True, text=True, timeout=300)


# ---------------------------------------------------------------------------
# THE FIRING HALF. Each of these passes on the pre-change program.
# ---------------------------------------------------------------------------

def test_a_manifest_that_names_no_process_is_incomplete():
    """The pre-change manifest shape, verbatim. `image` is present and the
    process half is absent — which is exactly the state 62 of 62 published
    runs are in, and which `check` used to call PASS."""
    man = brm.build_manifest({"alpha": "pass"}, dataset=None,
                             plugin_version="0.0.0", image="sha256:abc",
                             scorer_argv=["score"])
    # `pop`, not `del`: on the PRE-CHANGE program the key is not there, and a
    # control that dies in its own setup has observed nothing. The failure this
    # test is here to produce must come from the assertion below.
    man.pop("pdk_revision", None)           # the pre-change shape
    gaps = brm.manifest_gaps(man)
    assert any(g.startswith("pdk_revision") for g in gaps), (
        "a manifest recording the toolchain and not the process passed as "
        "complete; the number in it cannot be re-derived", gaps)


def test_a_manifest_that_names_no_process_is_refused_by_check(log_safe_tmp):
    """End to end, through the CLI the landing gate actually runs."""
    run = _run_that_read_a_pdk(log_safe_tmp)
    assert _emit(run).returncode == 0
    man_path = run / brm.MANIFEST_NAME
    man = json.loads(man_path.read_text())
    man.pop("pdk_revision", None)           # see the note in the test above
    man_path.write_text(json.dumps(man, indent=2))

    r = _check(run)
    assert r.returncode == 1, (r.stdout, r.stderr)
    assert "pdk_revision" in r.stdout, r.stdout


@pytest.mark.parametrize("placeholder", ["unknown", "UNKNOWN", "NOT DETERMINED",
                                          "none", "n/a", "TBD"])
def test_a_placeholder_where_the_revision_goes_is_refused(placeholder):
    """TRAP 2 of the brief, at the manifest layer. Writing a word into the
    field passes every structural check and re-creates the gap one layer up
    while looking closed."""
    man = brm.build_manifest({"alpha": "pass"}, plugin_version="0.0.0",
                             image="sha256:abc", scorer_argv=["score"],
                             pdk_revision={"schema": prr.SCHEMA,
                                           "resolved": True,
                                           "revision": placeholder,
                                           "trees": [{"tree": "/t"}]})
    gaps = brm.manifest_gaps(man)
    assert any("not a revision token" in g for g in gaps), (placeholder, gaps)


def test_a_hand_claimed_no_pdk_read_that_the_evidence_refutes_is_refused():
    """The word in the file is a RENDERING, never the authority.
    `determination_of` recomputes the state from the record's own numbers, so
    typing the admissible state into the field does not produce it."""
    man = brm.build_manifest(
        {"alpha": "pass"}, plugin_version="0.0.0", image="sha256:abc",
        scorer_argv=["score"],
        pdk_revision={"schema": prr.SCHEMA, "resolved": False,
                      "revision": None, "trees": [],
                      "determination": prr.NO_PDK_READ,
                      # the run DID load a library — so "read no PDK" is false
                      "evidence": {"logs_scanned": 3, "libraries_loaded": 7,
                                   "trees_offered": 0}})
    assert brm.manifest_gaps(man), "a refuted claim of NO_PDK_READ was admitted"


def test_a_hand_claimed_no_pdk_read_with_nothing_scanned_is_refused():
    """`logs_scanned == 0` is NOBODY LOOKED, and no flag admits it. This is the
    distinction the whole determination field exists for: over the published
    corpus it is the state of 62 of 62 evaluation runs, so a rule that read it
    as "no PDK used" would have signed off every one of them as PDK-free."""
    man = brm.build_manifest(
        {"alpha": "pass"}, plugin_version="0.0.0", image="sha256:abc",
        scorer_argv=["score"],
        pdk_revision={"schema": prr.SCHEMA, "resolved": False,
                      "revision": None, "trees": [],
                      "determination": prr.NO_PDK_READ,
                      "evidence": {"logs_scanned": 0, "libraries_loaded": 0,
                                   "trees_offered": 0}})
    assert brm.manifest_gaps(man), (
        "'nobody looked' was admitted as 'this run used no PDK'")


def test_emit_refuses_to_write_rather_than_writing_unknown(log_safe_tmp):
    """TRAP 2 again, at the moment of writing. A run that cannot say which
    process it was measured against gets NO manifest — not one with a word in
    the field."""
    run = _run_that_kept_no_log(log_safe_tmp)
    r = _emit(run)
    assert r.returncode == 1, (r.stdout, r.stderr)
    assert "REFUSED" in r.stderr, r.stderr
    assert not (run / brm.MANIFEST_NAME).exists(), (
        "a manifest was written for a run whose process is unknown")


def test_there_is_no_flag_that_supplies_a_revision(log_safe_tmp):
    """TRAP 1 of the brief. A revision that came from the command line is a
    record of the REQUEST — the same class of artefact as `--pdk <name>`,
    `env_PDK_ROOT` and the cell's directory name, every one of which this repo
    already had and none of which says what ran."""
    run = _run_that_kept_no_log(log_safe_tmp)
    for flag in ("--pdk-revision", "--revision", "--pdk"):
        r = _emit(run, extra=[flag, _REV])
        assert r.returncode == 2, (
            f"{flag} was accepted; a revision from argv is the request", flag,
            r.stdout, r.stderr)
        assert "unrecognized arguments" in r.stderr, (flag, r.stderr)


# ---------------------------------------------------------------------------
# THE CLEARS HALF. Vacuous before the field existed; a control only with the
# firing half above.
# ---------------------------------------------------------------------------

def test_a_run_that_read_a_pdk_records_the_revision_the_tree_declares(
        log_safe_tmp):
    """The value comes from the RESOLVED TREE. Nothing on the command line
    names a revision, and the token that lands in the manifest is the one the
    tree's own SOURCES file states."""
    run = _run_that_read_a_pdk(log_safe_tmp)
    r = _emit(run)
    assert r.returncode == 0, (r.stdout, r.stderr)

    man = json.loads((run / brm.MANIFEST_NAME).read_text())
    rec = man["pdk_revision"]
    assert rec["determination"] == prr.RESOLVED, rec
    assert _REV in (rec["revision"] or ""), rec
    assert brm.manifest_gaps(man) == [], man
    # ...and it sits next to the toolchain digest, which is the point.
    assert man["image"], man


def test_the_recorded_revision_follows_the_tree_and_not_the_run(log_safe_tmp):
    """Two runs identical but for the tree their logs name record two different
    revisions. If the field were copied from anything the operator supplies,
    these would be equal — the argv is byte-identical across both."""
    a = _run_that_read_a_pdk(log_safe_tmp / "a", _REV)
    b = _run_that_read_a_pdk(log_safe_tmp / "b", _REV_OTHER)
    assert _emit(a).returncode == 0
    assert _emit(b).returncode == 0
    ra = json.loads((a / brm.MANIFEST_NAME).read_text())["pdk_revision"]
    rb = json.loads((b / brm.MANIFEST_NAME).read_text())["pdk_revision"]
    assert ra["revision"] != rb["revision"], (ra, rb)
    assert _REV in ra["revision"] and _REV_OTHER in rb["revision"], (ra, rb)


def test_a_pure_simulation_run_is_accepted_and_says_so(log_safe_tmp):
    """NO FALSE REFUSAL. A run whose tools were observed to open no process
    data owes no revision, and the manifest records that as a MEASURED absence
    with the counts that establish it."""
    run = _run_that_read_no_pdk(log_safe_tmp)
    r = _emit(run)
    assert r.returncode == 0, (r.stdout, r.stderr)
    man = json.loads((run / brm.MANIFEST_NAME).read_text())
    rec = man["pdk_revision"]
    assert rec["determination"] == prr.NO_PDK_READ, rec
    assert rec["evidence"]["logs_scanned"] > 0, rec
    assert rec["evidence"]["libraries_loaded"] == 0, rec
    assert brm.manifest_gaps(man) == [], man
    assert _check(run).returncode == 0


def test_the_run_s_own_record_is_preferred_and_the_manifest_says_which(
        log_safe_tmp):
    """`reports/pdk_revision.json` is written at finalize, while the tree is
    live. That is a stronger claim than one recomputed at emit time, and a
    reader is owed which one they are looking at."""
    run = _run_that_read_a_pdk(log_safe_tmp)
    derived = brm.resolve_run_pdk_revision(run)
    assert derived["source"].startswith("derived"), derived

    # Now give the run the record the one-shot runner would have left.
    rec_path = run / prr.RECORD_REL
    rec_path.parent.mkdir(parents=True, exist_ok=True)
    rec_path.write_text(json.dumps(derived, indent=2))
    from_record = brm.resolve_run_pdk_revision(run)
    assert from_record["source"].startswith("run record"), from_record
    assert from_record["revision"] == derived["revision"], (from_record, derived)


# ---------------------------------------------------------------------------
# The publish gate must not have been loosened on the way past.
# ---------------------------------------------------------------------------

def test_the_sign_off_gate_still_refuses_a_run_that_read_no_pdk():
    """`record_gaps` DEFAULTS to strict, and `benchmark_evidence_publish` calls
    it with the default. A sign-off cell ran a physical implementation; the
    admission made for scored benchmark runs must not reach it."""
    rec = prr.build_record([], "host", "run tool logs",
                           evidence={"logs_scanned": 4, "libraries_loaded": 0})
    assert rec["determination"] == prr.NO_PDK_READ, rec
    assert prr.record_gaps(rec) != [], (
        "the publish gate now accepts a cell that names no PDK revision", rec)
    assert prr.record_gaps(rec, no_pdk_read_ok=True) == [], rec


def test_determination_is_derived_from_the_evidence_not_asserted():
    """Three states, each reachable only from its own numbers."""
    read = prr.build_record(
        [{"resolved": True, "revision": f"{prr.TREE_COMPONENT}:{_REV}"}],
        "host", "t", evidence={"logs_scanned": 1, "libraries_loaded": 1})
    none = prr.build_record([], "host", "t",
                            evidence={"logs_scanned": 4, "libraries_loaded": 0})
    blind = prr.build_record([], "host", "t",
                             evidence={"logs_scanned": 0, "libraries_loaded": 0})
    unread = prr.build_record([], "host", "t",
                              evidence={"logs_scanned": 4,
                                        "libraries_loaded": 9})
    assert read["determination"] == prr.RESOLVED, read
    assert none["determination"] == prr.NO_PDK_READ, none
    assert blind["determination"] == prr.NOT_DETERMINED, blind
    # libraries WERE loaded, from a tree that declares nothing — a finding,
    # and the one state that must never collapse into NO_PDK_READ.
    assert unread["determination"] == prr.NOT_DETERMINED, unread


def test_pdk_revision_is_named_in_the_required_field_list():
    """The emitter and the checker share one notion of "complete"; a field the
    checker demands and the list omits is a drift waiting to happen."""
    assert "pdk_revision" in brm.REQUIRED_FIELDS, brm.REQUIRED_FIELDS
