#!/usr/bin/env python3
"""The three corpus-B gates after the published corpus moved out (#1710's shape).

WHY THIS FILE EXISTS
====================
v1.10.56 moved `benchmark-data/` into its own repository. Three gates in
`tools/ci/repo_hygiene_gates.sh` were still aimed at the tree it left behind:

    cross-layer reference regression  [SKIP] corpus not found: <repo>/benchmark-data/ic
    step FAIL bubbles up             error: not a directory: <repo>/benchmark-data/ic
    published records not superseded ERROR: not a directory: <repo>/benchmark-data

The first two REFUSED, correctly, for what they were asked, and `run` in
`_gate_dispatch.sh` maps rc 2 to FAIL, so they blocked every landing. The third
did not refuse, it CRASHED at rc 1 — the code that program uses for "a published
record carries a verdict its gate would no longer issue". It reported a defect it
had never measured. A crash is not a verdict.

THE FOUR OUTCOMES, WHICH MUST NOT COLLAPSE INTO THREE
=====================================================
    pointer set + unreadable        -> UNDETERMINED (rc 2). Never excused.
    pointer set + present but NOT a
      git checkout                  -> UNDETERMINED (rc 2). An empty
                                       `git ls-files` is "I could not look",
                                       not "there are none".
    nothing anywhere + caller opted -> NO_CORPUS (rc 0). Nothing scanned and
                                       NOTHING CLAIMED to have been scanned.
    nothing anywhere + no opt-in    -> UNDETERMINED (rc 2). Unchanged.

EVERY CASE HERE IS PAIRED, AND THE PAIRINGS THAT MATTER MOST ARE THE LAST TWO
GROUPS. A change that only proved "the gates stopped blocking" would pass just
as well against gates that had been deleted, so:

  * a corpus WITH A PLANTED DEFECT is supplied through $VIBE_IC_BENCHMARK_DATA,
    with --corpus-may-be-absent set, and all three must still return rc 1; and
  * the DEBT REGISTERS, which live in this repo and did NOT move with the
    corpus, are still adjudicated on the NO_CORPUS path — because an rc 0 that
    never opens the register is exactly the hole `repo_hygiene_gates.sh`
    withdrew this gate's `gate_scope` in v1.10.55 to close, re-entered through
    the other door.

All fixtures are SYNTHESIZED. No design, vendor, PDK or part number appears.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
REPO = PROGRAMS.parents[3]
#: The one file that DEFINES the gate dispatchers. Read rather than
#: re-spelled — see `_dispatchers`.
DISPATCH = REPO / "tools" / "ci" / "_gate_dispatch.sh"
CROSS = PROGRAMS / "cross_layer_reference_check.py"
BUBBLE = PROGRAMS / "step_internal_fail_bubble_up_check.py"
STALE = PROGRAMS / "published_record_staleness_check.py"
ENV = "VIBE_IC_BENCHMARK_DATA"

if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import cross_layer_reference_check as CL      # noqa: E402

#: vibe-ic#1711 — the harness runs pytest at `--timeout=180` and kills the
#: SESSION, so any inner bound above 180 // 3 = 60 s is a promise it cannot
#: keep. MEASURED here: the slowest case builds a two-cell git corpus and makes
#: one gate call, well under two seconds of wall time.
_GATE_TIMEOUT_S = 60


def _run(prog: Path, *args: str, env_tree: str | None = None):
    """Invoke a gate the way CI does — as a process, reading only its rc.

    The exit code is the entire contract with `_gate_dispatch.sh`. A test that
    imported `main()` and asserted on returned objects would leave the rc free
    to be anything, which is how a gate that had stopped gating once kept eight
    green tests.
    """
    env = dict(os.environ)
    env.pop(ENV, None)                      # never inherit the developer's own
    if env_tree is not None:
        env[ENV] = env_tree
    r = subprocess.run([sys.executable, str(prog), *args], env=env,
                       capture_output=True, text=True, timeout=_GATE_TIMEOUT_S)
    return r.returncode, (r.stdout + r.stderr)


def _git(cwd: Path, *a: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *a], check=True, timeout=60,
                   capture_output=True)


def _commit(root: Path) -> Path:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "corpus")
    return root


# ───────────────────────────── fixtures: the corpora ────────────────────────
def _ports(width_symbolic, width=1):
    data = {"name": "sample_bus", "mode": "input", "direction": "input",
            "width": width}
    if width_symbolic is not None:
        data["width_symbolic"] = width_symbolic
    return [{"name": "clk_in", "mode": "input", "direction": "input",
             "width": 1},
            {"name": "rst_in", "mode": "input", "direction": "input",
             "width": 1},
            data]


def _cell(cell: Path, *, width: int) -> None:
    """One published cell. `width` 24 agrees with the parameter (clean); `1`
    is the CONSUMER_CANNOT_REACH break this gate exists for."""
    docs = cell / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    ports = _ports("ACCUM_W-1:0", width)
    (docs / "L1_DATASHEET.json").write_text(json.dumps(
        {"ic_name": "synth_block", "pin_table": ports}))
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(
        {"ic_name": "synth_block", "top_module": "synth_block",
         "top_ports": ports, "ports": ports}))
    (docs / "L8_RTL_CONSTANTS.json").write_text(json.dumps(
        {"parameters": [{"name": "ACCUM_W", "default": "24"}]}))
    (docs / "L17_CHANNEL_SIGNAL_CATALOG.json").write_text(json.dumps(
        {"extraction_status": "EXTRACTION_FOUND_NOTHING",
         "channels": [], "global_signals": []}))


@pytest.fixture()
def cross_clone(tmp_path) -> Path:
    """A clone-shaped corpus carrying ONE cross-layer break, under `ic/`.

    A real git repository because `corpus_cells` reads git's INDEX: whether a
    path materialises is not the condition under test, whether it is PUBLISHED
    is.
    """
    root = tmp_path / "benchmark-data-clone"
    _cell(root / "ic" / "designA" / "v1_0_0_pdkX", width=1)     # the break
    _cell(root / "ic" / "designB" / "v1_0_0_pdkX", width=24)    # clean
    return _commit(root)


@pytest.fixture()
def bubble_clone(tmp_path) -> Path:
    """A clone-shaped corpus whose one published run tree carries an
    unacknowledged step-internal FAIL — no waivers.json, no orchestrator or
    audit record naming it, so neither limb of the acknowledgment rule grants
    it."""
    root = tmp_path / "benchmark-data-clone"
    d = root / "ic" / "designA" / "v1_0_0_pdkX" / "reports" / "phase3"
    d.mkdir(parents=True)
    (d / "clean_gate.json").write_text(json.dumps({"verdict": "PASS"}))
    (d / "planted_gate.json").write_text(json.dumps(
        {"verdict": "FAIL", "detail": "synthetic unacknowledged fail"}))
    return _commit(root)


def _si_record(coupling_pairs: int):
    """A published si_mcf_sta_check record in the shape HEAD actually holds.

    `coupling_pairs: 0` beside `verdict: PASS` is the vibe-ic#502 rule's
    refutation on paper — no SPEF needed, which is the whole premise of
    re-adjudicating from the record.
    """
    return {"program": "si_mcf_sta_check", "version": "1.0.0",
            "project_dir": ".", "verdict": "PASS",
            "summary": {"corners_checked": ["setup", "hold"],
                        "windows_exact": True,
                        "coupling_pairs": coupling_pairs,
                        "errors_count": 0, "findings_count": 0, "pass": True},
            "recount": {}, "monotonicity": {}, "findings": []}


@pytest.fixture()
def stale_clone(tmp_path) -> Path:
    """A clone-shaped corpus carrying ONE superseded published record."""
    root = tmp_path / "benchmark-data-clone"
    p = root / "ic" / "designA" / "reports" / "phase3" / "si_mcf_sta_check.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(_si_record(0), indent=2) + "\n")
    return _commit(root)


@pytest.fixture()
def stale_clean_clone(tmp_path) -> Path:
    """The control for the arm above: same shape, a record the current rules
    WOULD still issue. Without it, "the gate failed" is compatible with a gate
    that fails on every corpus it is handed."""
    root = tmp_path / "clean-clone"
    p = root / "ic" / "designA" / "reports" / "phase3" / "si_mcf_sta_check.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(_si_record(1558), indent=2) + "\n")
    return _commit(root)


def _empty_register(tmp_path) -> str:
    """An explicitly-empty debt register, so a FAIL below is about the planted
    defect and not about whatever the shipped register happens to hold today.

    The bookkeeping fields are not decoration: since #922 the READ path refuses
    a register `--write-baseline` could not have produced, so a fixture that
    omits them describes a file this program is RIGHT to reject and would pin
    the wrong behaviour.
    """
    p = tmp_path / "register.json"
    p.write_text(json.dumps({"previous_size": None, "size": 0,
                             "scope_expanded": None, "known": []}, indent=2))
    return str(p)


_GONE = "/nonexistent-corpus-root-for-this-test"


# ===========================================================================
# 1. NOTHING ANYWHERE + the caller said so -> rc 0, and it SAYS nothing was
#    scanned. This is the case that unblocks the removal.
# ===========================================================================
def test_cross_layer_no_corpus_with_the_flag_is_rc0_and_says_it_scanned_nothing():
    rc, out = _run(CROSS, "--corpus", _GONE, "--corpus-may-be-absent")
    assert rc == 0, out
    assert "NO_CORPUS" in out, out
    assert "NOTHING WAS SCANNED" in out, \
        "an rc 0 must not read as a sweep that happened"
    assert "0 published cell(s) were examined" in out, \
        "the zero must be stated, not left to be inferred from silence"
    assert "[PASS]" not in out, "a sweep that did not happen was spelled a pass"


def test_bubble_up_no_corpus_with_the_flag_is_rc0_and_says_it_scanned_nothing():
    rc, out = _run(BUBBLE, "--corpus", _GONE, "--corpus-may-be-absent")
    assert rc == 0, out
    assert "NO_CORPUS" in out, out
    assert "NOTHING WAS SCANNED" in out, out
    assert "0 published run tree(s) swept, 0 report(s) examined" in out, out
    assert "[PASS]" not in out, out


def test_staleness_no_corpus_with_the_flag_is_rc0_and_says_it_scanned_nothing(
        tmp_path):
    rc, out = _run(STALE, _GONE, "--baseline", _empty_register(tmp_path),
                   "--corpus-may-be-absent")
    assert rc == 0, out
    assert "NO_CORPUS" in out, out
    assert "NOTHING WAS SCANNED" in out, out
    assert "0 published gate record(s) found, 0 adjudicated" in out, out
    assert "[PASS]" not in out, out


def test_staleness_no_longer_crashes_where_a_verdict_belongs():
    """THE THIRD GATE'S OWN DEFECT. `ERROR: not a directory` at rc 1 is this
    program's code for "a published record carries a verdict its gate would not
    issue" — a finding against records it never opened."""
    rc, out = _run(STALE, _GONE, "--corpus-may-be-absent")
    assert rc != 1, (
        f"an absent corpus is still being reported as a superseded record\n"
        f"{out}")
    assert "ERROR: not a directory" not in out, out


# ===========================================================================
# 2. …AND WITHOUT THE FLAG ALL THREE STILL BLOCK. The half that makes case 1
#    mean something: the relaxation is OPT-IN AT THE CALL SITE, not a default.
# ===========================================================================
@pytest.mark.parametrize("prog,args", [
    (CROSS, ("--corpus", _GONE)),
    (BUBBLE, ("--corpus", _GONE)),
    (STALE, (_GONE,)),
])
def test_without_the_flag_it_is_still_undetermined(prog, args):
    rc, out = _run(prog, *args)
    assert rc == 2, f"the relaxation must be opt-in\n{out}"
    assert "UNDETERMINED" in out, out
    assert "has not passed" in out, out


# ===========================================================================
# 3. A BROKEN POINTER IS NEVER EXCUSED — not even with the flag. "Somebody said
#    where the corpus is and was wrong" is a different event from "there is
#    none", and a mistyped path or a no-op CI fetch step must not go green.
# ===========================================================================
@pytest.mark.parametrize("prog,args", [
    (CROSS, ("--corpus", _GONE, "--corpus-may-be-absent")),
    (BUBBLE, ("--corpus", _GONE, "--corpus-may-be-absent")),
    (STALE, (_GONE, "--corpus-may-be-absent")),
])
def test_a_broken_pointer_is_undetermined_even_with_the_flag(prog, args,
                                                             tmp_path):
    rc, out = _run(prog, *args, env_tree=str(tmp_path / "nowhere"))
    assert rc == 2, f"a set-and-wrong pointer must never be waved through\n{out}"
    assert "UNDETERMINED" in out and ENV in out, out
    assert "NO_CORPUS" not in out, \
        "a broken pointer was laundered as an absent corpus"


# ===========================================================================
# 4. A CORPUS THAT IS PRESENT BUT NOT A CHECKOUT IS REFUSED, NOT WALKED.
#    All three read git's INDEX to decide what is PUBLISHED, and all three fall
#    back to the DISK when git cannot answer. Over a tarball fetch, an archive
#    export or a dead clone that fallback silently swaps the population — and a
#    ratchet compared across two populations is worse than no ratchet.
# ===========================================================================
def test_cross_layer_a_present_but_unversioned_corpus_is_undetermined(tmp_path):
    """Built byte-identically to `cross_clone` except for `git init` — the one
    difference under test — and carrying the same break."""
    _cell(tmp_path / "ic" / "designA" / "v1_0_0_pdkX", width=1)
    rc, out = _run(CROSS, "--corpus", _GONE, "--corpus-may-be-absent",
                   env_tree=str(tmp_path))
    assert rc == 2, (
        f"a corpus PRESENT and unreadable by git was adjudicated from a disk "
        f"walk\n{out}")
    assert "not a git checkout" in out, out
    assert "NO_CORPUS" not in out, (
        "a present-but-unversioned corpus was laundered as an absent one; the "
        "corpus is right there")


def test_bubble_up_a_present_but_unversioned_corpus_is_undetermined(tmp_path):
    d = tmp_path / "ic" / "designA" / "reports" / "phase3"
    d.mkdir(parents=True)
    (d / "planted_gate.json").write_text(json.dumps({"verdict": "FAIL"}))
    rc, out = _run(BUBBLE, "--corpus", _GONE, "--corpus-may-be-absent",
                   env_tree=str(tmp_path))
    assert rc == 2, out
    assert "not a git checkout" in out, out
    assert "NO_CORPUS" not in out, out


def test_staleness_a_present_but_unversioned_corpus_is_undetermined(tmp_path):
    p = tmp_path / "ic" / "designA" / "reports" / "phase3" / "si_mcf_sta_check.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(_si_record(0), indent=2) + "\n")
    rc, out = _run(STALE, _GONE, "--corpus-may-be-absent",
                   env_tree=str(tmp_path))
    assert rc == 2, out
    assert "not a git checkout" in out, out
    assert "NO_CORPUS" not in out, out


# --- the same empty result with a `.git` beside it -------------------------
#
# `_published_tree.published_paths` returns None for "git could not answer" AND
# for "the index is empty", and both send the two sweeping gates to a DISK
# WALK. `git init` alone therefore defeats the refusal above while leaving the
# population just as unpublished — a dead clone that fetched no content looks
# exactly like this. Both arms are built byte-identically except for the commit.
def test_cross_layer_a_checkout_that_tracks_nothing_is_undetermined(tmp_path):
    _cell(tmp_path / "ic" / "designA" / "v1_0_0_pdkX", width=1)
    _git(tmp_path, "init", "-q")            # a checkout, and nothing committed
    rc, out = _run(CROSS, "--corpus", _GONE, "--corpus-may-be-absent",
                   env_tree=str(tmp_path))
    assert rc == 2, (
        f"an empty index was read as 'there are none' and the cells on disk "
        f"were swept anyway\n{out}")
    assert "tracks NOTHING" in out, out
    assert "NO_CORPUS" not in out, out


def test_cross_layer_the_same_tree_committed_is_swept(tmp_path):
    """The control. Without it the refusal above is compatible with a gate that
    refuses every corpus reached through the pointer."""
    _cell(tmp_path / "ic" / "designA" / "v1_0_0_pdkX", width=1)
    _commit(tmp_path)
    rep = tmp_path / "r.json"
    rc, out = _run(CROSS, "--corpus", _GONE, "--corpus-may-be-absent",
                   "--baseline", str(tmp_path / "b.json"), "--json", str(rep),
                   env_tree=str(tmp_path))
    assert rc == 1, out
    assert json.loads(rep.read_text())["cells_swept"] == 1, out


def test_bubble_up_a_checkout_that_tracks_nothing_is_undetermined(tmp_path):
    d = tmp_path / "ic" / "designA" / "reports" / "phase3"
    d.mkdir(parents=True)
    (d / "planted_gate.json").write_text(json.dumps({"verdict": "FAIL"}))
    _git(tmp_path, "init", "-q")
    rc, out = _run(BUBBLE, "--corpus", _GONE, "--corpus-may-be-absent",
                   env_tree=str(tmp_path))
    assert rc == 2, out
    assert "tracks NOTHING" in out, out
    assert "NO_CORPUS" not in out, out


def test_bubble_up_the_same_tree_committed_is_swept(tmp_path):
    d = tmp_path / "ic" / "designA" / "reports" / "phase3"
    d.mkdir(parents=True)
    (d / "planted_gate.json").write_text(json.dumps({"verdict": "FAIL"}))
    _commit(tmp_path)
    base = tmp_path / "baseline.json"
    # `previous_*: null` is what `--write-baseline` records on a FIRST write:
    # the register states that it moved from nothing. The keys being ABSENT is a
    # different fact — a register no writer that records provenance ever touched
    # — and the gate answers NOT DETERMINED to it (vibe-ic#1704). These fixtures
    # are about where the corpus is found, so they declare the honest first-write
    # form. Same in every hand-built register below.
    base.write_text(json.dumps({
        "findings_total": 0, "corpus_population": "benchmark-data/ic",
        "previous_findings_total": None, "previous_runs_swept": None,
        "previous_runs_with_reports": None,
        "runs_swept": 1, "runs_with_reports": 1,
        "per_run": {}, "withdrawn_unexamined": {}}))
    rc, out = _run(BUBBLE, "--corpus", _GONE, "--corpus-may-be-absent",
                   "--baseline", str(base), env_tree=str(tmp_path))
    assert rc == 1, out
    assert "GREW" in out, out


# ===========================================================================
# 5. THE POINTER IS FOLLOWED, AND ANNOUNCED. A gate that scans a different tree
#    from the one on its command line must say so — that silence is how a
#    mis-aimed `--tree` once reported "13/28 conformant" over a tree an absolute
#    path found 8 failures in.
# ===========================================================================
def test_cross_layer_announces_the_override(cross_clone, tmp_path):
    rc, out = _run(CROSS, "--corpus", _GONE, "--corpus-may-be-absent",
                   "--baseline", str(tmp_path / "b.json"),
                   env_tree=str(cross_clone))
    assert f"{ENV} overrides" in out, out
    assert str(cross_clone) in out, "the tree actually scanned must be named"


def test_bubble_up_announces_the_override(bubble_clone, tmp_path):
    rc, out = _run(BUBBLE, "--corpus", _GONE, "--corpus-may-be-absent",
                   "--baseline", str(tmp_path / "b.json"),
                   env_tree=str(bubble_clone))
    assert f"{ENV} overrides" in out, out
    assert str(bubble_clone) in out, out


def test_staleness_announces_the_override(stale_clean_clone, tmp_path):
    rc, out = _run(STALE, _GONE, "--corpus-may-be-absent",
                   "--baseline", _empty_register(tmp_path),
                   env_tree=str(stale_clean_clone))
    assert f"{ENV} overrides" in out, out
    assert str(stale_clean_clone) in out, out


# ===========================================================================
# 6. THE LOAD-BEARING PAIR: A PLANTED DEFECT IN A SUPPLIED CORPUS STILL FAILS,
#    WITH THE FLAG SET. If the rc 2 -> rc 0 widening above had been bought by
#    weakening the gates, these are the tests that would have gone green with it.
# ===========================================================================
def test_cross_layer_still_fails_on_a_new_break_in_a_supplied_corpus(
        cross_clone, tmp_path):
    """One cell whose port is 1 bit wide against a parameter that says 24. The
    baseline records the CLEAN corpus, then the break is supplied."""
    base = tmp_path / "baseline.json"
    clean = tmp_path / "clean-clone"
    _cell(clean / "ic" / "designB" / "v1_0_0_pdkX", width=24)
    _commit(clean)
    rc, out = _run(CROSS, "--corpus", _GONE, "--corpus-may-be-absent",
                   "--baseline", str(base), "--write-baseline",
                   env_tree=str(clean))
    assert rc == 0, out
    rc, out = _run(CROSS, "--corpus", _GONE, "--corpus-may-be-absent",
                   "--baseline", str(base), env_tree=str(cross_clone))
    assert rc == 1, (
        f"--corpus-may-be-absent reached a corpus that IS present and excused "
        f"a NEW cross-layer break in it\n{out}")
    assert "NEW cross-layer break" in out, out


def test_cross_layer_really_sweeps_a_supplied_corpus(cross_clone, tmp_path):
    """The denominator, without which everything above is compatible with a
    gate that never sweeps."""
    rep = tmp_path / "r.json"
    _run(CROSS, "--corpus", _GONE, "--corpus-may-be-absent",
         "--baseline", str(tmp_path / "b.json"), "--json", str(rep),
         env_tree=str(cross_clone))
    doc = json.loads(rep.read_text())
    assert doc["cells_swept"] == 2, doc
    assert doc["examined"]["port_width_symbolic_to_parameter"] > 0, doc


def test_bubble_up_still_fails_on_growth_in_a_supplied_corpus(bubble_clone,
                                                              tmp_path):
    base = tmp_path / "baseline.json"
    base.write_text(json.dumps({
        "findings_total": 0, "corpus_population": "benchmark-data/ic",
        "previous_findings_total": None, "previous_runs_swept": None,
        "previous_runs_with_reports": None,
        "runs_swept": 1, "runs_with_reports": 1,
        "per_run": {}, "withdrawn_unexamined": {}}))
    rc, out = _run(BUBBLE, "--corpus", _GONE, "--corpus-may-be-absent",
                   "--baseline", str(base), env_tree=str(bubble_clone))
    assert rc == 1, (
        f"--corpus-may-be-absent reached a corpus that IS present and excused "
        f"an unacknowledged step-internal FAIL in it\n{out}")
    assert "GREW" in out, out


def test_bubble_up_population_key_survives_the_move(bubble_clone, tmp_path):
    """The baseline records `benchmark-data/ic` and the clone spells the same
    set `ic`. If the two were not reconciled the gate would answer NOT CHECKED
    for every supplied corpus — a green-by-refusal that looks like a fix."""
    base = tmp_path / "baseline.json"
    base.write_text(json.dumps({
        "findings_total": 1, "corpus_population": "benchmark-data/ic",
        "previous_findings_total": None, "previous_runs_swept": None,
        "previous_runs_with_reports": None,
        "runs_swept": 1, "runs_with_reports": 1,
        "per_run": {"designA/v1_0_0_pdkX": 1}, "withdrawn_unexamined": {}}))
    rc, out = _run(BUBBLE, "--corpus", _GONE, "--corpus-may-be-absent",
                   "--baseline", str(base), env_tree=str(bubble_clone))
    assert "NOT CHECKED" not in out, (
        f"the same population under its two names was refused as two\n{out}")
    assert rc == 0, out


def test_staleness_still_fails_on_a_superseded_record_in_a_supplied_corpus(
        stale_clone, tmp_path):
    rc, out = _run(STALE, _GONE, "--corpus-may-be-absent",
                   "--baseline", _empty_register(tmp_path),
                   env_tree=str(stale_clone))
    assert rc == 1, (
        f"--corpus-may-be-absent reached a corpus that IS present and excused "
        f"a published record whose gate would no longer issue its verdict\n"
        f"{out}")
    assert "si_mcf_sta_check" in out, "the offending record must be named"
    assert "NO_CORPUS" not in out, out


def test_staleness_control_a_current_record_in_the_same_shape_passes(
        stale_clean_clone, tmp_path):
    """Without this, the FAIL above is compatible with a gate that fails on
    every corpus it is handed."""
    rc, out = _run(STALE, _GONE, "--corpus-may-be-absent",
                   "--baseline", _empty_register(tmp_path),
                   env_tree=str(stale_clean_clone))
    assert rc == 0, out
    assert "[PASS] no NEW superseded record" in out, out


# ===========================================================================
# 7. NO_CORPUS EXCUSES THE SWEEP, NEVER THE REGISTER.
#    The registers live in THIS repo and did not move. `repo_hygiene_gates.sh`
#    withdrew the cross-layer gate's `gate_scope` in v1.10.55 precisely because
#    a scope naming benchmark-data/ic excludes the checker's own body and its
#    own register, so a commit that only widens the register would not run the
#    one gate guarding it. An rc 0 that never opens the file gives that back.
# ===========================================================================
def _seal(doc) -> str:
    return CL.register_seal(doc)


def _sealed_register(tmp_path, breaks: int, examined: int) -> Path:
    p = tmp_path / "cl_register.json"
    doc = {"recorded": {"port_width_symbolic_to_parameter":
                        {"CONSUMER_CANNOT_REACH": breaks}},
           "examined": {"port_width_symbolic_to_parameter": examined}}
    doc["seal"] = _seal(doc)
    p.write_text(json.dumps(doc, indent=2))
    return p


def test_cross_layer_no_corpus_still_verifies_the_register_seal(tmp_path):
    reg = _sealed_register(tmp_path, 3, 9)
    rc, out = _run(CROSS, "--corpus", _GONE, "--corpus-may-be-absent",
                   "--baseline", str(reg))
    assert rc == 0, out
    assert "seal verifies" in out, out
    assert "NOT RE-MEASURED" in out, (
        "an rc 0 over a register nobody re-measured must say so")


def test_cross_layer_no_corpus_fails_on_a_register_widened_by_hand(tmp_path):
    """THE PLANTED DEFECT FOR THE REGISTER. Raising a recorded count is the
    cheapest way to stop a real break being NEW, and with no corpus the seal is
    the only thing that can notice."""
    reg = _sealed_register(tmp_path, 3, 9)
    doc = json.loads(reg.read_text())
    doc["recorded"]["port_width_symbolic_to_parameter"][
        "CONSUMER_CANNOT_REACH"] = 300
    reg.write_text(json.dumps(doc, indent=2))
    rc, out = _run(CROSS, "--corpus", _GONE, "--corpus-may-be-absent",
                   "--baseline", str(reg))
    assert rc == 1, f"a hand-widened register went green with no corpus\n{out}"
    assert "EDITED after it was written" in out, out


def test_cross_layer_no_corpus_refuses_an_unsealed_register(tmp_path):
    """`--write-baseline` is the only thing that seals, and it refuses a sweep
    that reached no cell — so "no seal" means nothing has vouched for these
    numbers, which is NOT CHECKED, not a pass."""
    p = tmp_path / "unsealed.json"
    p.write_text(json.dumps({
        "recorded": {"port_width_symbolic_to_parameter":
                     {"CONSUMER_CANNOT_REACH": 3}},
        "examined": {"port_width_symbolic_to_parameter": 9}}))
    rc, out = _run(CROSS, "--corpus", _GONE, "--corpus-may-be-absent",
                   "--baseline", str(p))
    assert rc == 2, out
    assert "NOT CHECKED" in out, out


def test_cross_layer_no_corpus_refuses_a_missing_register(tmp_path):
    rc, out = _run(CROSS, "--corpus", _GONE, "--corpus-may-be-absent",
                   "--baseline", str(tmp_path / "absent.json"))
    assert rc == 2, f"an absent ratchet was read as an empty one\n{out}"
    assert "NOT CHECKED" in out, out


def test_the_shipped_cross_layer_register_is_sealed():
    """The in-repo register, not a fixture. An unsealed shipped register would
    turn the CI gate into NOT CHECKED on every corpus-less run."""
    p = PROGRAMS / "cross_layer_reference_baseline.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    assert doc.get("seal") == _seal(doc), (
        "the shipped register does not match its own seal")


def test_cross_layer_write_baseline_refuses_a_sweep_that_reached_nothing(
        tmp_path):
    """vibe-ic#1025's shape, which this program still carried: the write used to
    happen unconditionally, so `--corpus <empty> --write-baseline` recorded {}
    as a measurement and destroyed the reference point. It would now also mint
    a valid seal over nothing."""
    reg = _sealed_register(tmp_path, 3, 9)
    before = reg.read_text()
    empty = tmp_path / "empty_corpus"
    empty.mkdir()
    rc, out = _run(CROSS, "--corpus", str(empty), "--baseline", str(reg),
                   "--write-baseline")
    assert rc == 2, out
    assert "REFUSED" in out, out
    assert reg.read_text() == before, "the register was destroyed anyway"


def test_bubble_up_no_corpus_still_checks_the_registers_own_arithmetic(
        tmp_path):
    base = tmp_path / "baseline.json"
    base.write_text(json.dumps({
        "findings_total": 3, "corpus_population": "benchmark-data/ic",
        "previous_findings_total": None, "previous_runs_swept": None,
        "previous_runs_with_reports": None,
        "runs_swept": 1, "runs_with_reports": 1,
        "per_run": {"designA": 1, "designB": 2}, "withdrawn_unexamined": {}}))
    rc, out = _run(BUBBLE, "--corpus", _GONE, "--corpus-may-be-absent",
                   "--baseline", str(base))
    assert rc == 0, out
    assert "sum agrees" in out, out
    assert "NOT RE-MEASURED" in out, out


def test_bubble_up_no_corpus_fails_on_a_ceiling_raised_by_hand(tmp_path):
    """THE PLANTED DEFECT FOR THIS REGISTER. `findings_total` and `per_run` come
    from the same counter in `check_corpus`, so a ceiling raised to buy headroom
    for a finding nobody measured contradicts the map printed beside it."""
    base = tmp_path / "baseline.json"
    base.write_text(json.dumps({
        "findings_total": 300, "corpus_population": "benchmark-data/ic",
        "previous_findings_total": None, "previous_runs_swept": None,
        "previous_runs_with_reports": None,
        "runs_swept": 1, "runs_with_reports": 1,
        "per_run": {"designA": 1, "designB": 2}, "withdrawn_unexamined": {}}))
    rc, out = _run(BUBBLE, "--corpus", _GONE, "--corpus-may-be-absent",
                   "--baseline", str(base))
    assert rc == 1, f"a hand-raised ratchet went green with no corpus\n{out}"
    assert "contradicts itself" in out, out


def test_bubble_up_no_corpus_refuses_a_missing_register(tmp_path):
    rc, out = _run(BUBBLE, "--corpus", _GONE, "--corpus-may-be-absent",
                   "--baseline", str(tmp_path / "absent.json"))
    assert rc == 2, out
    assert "An absent ratchet is not an empty one" in out, out


def test_bubble_up_write_baseline_with_no_corpus_is_refused(tmp_path):
    base = tmp_path / "baseline.json"
    base.write_text(json.dumps({
        "findings_total": 3, "corpus_population": "benchmark-data/ic",
        "previous_findings_total": None, "previous_runs_swept": None,
        "previous_runs_with_reports": None,
        "runs_swept": 1, "runs_with_reports": 1,
        "per_run": {"designA": 3}, "withdrawn_unexamined": {}}))
    before = base.read_text()
    rc, out = _run(BUBBLE, "--corpus", _GONE, "--corpus-may-be-absent",
                   "--baseline", str(base), "--write-baseline")
    assert rc == 2, out
    assert "REFUSED" in out, out
    assert base.read_text() == before, "the register was zeroed anyway"


def test_staleness_no_corpus_still_runs_the_may_only_shrink_checks(tmp_path):
    """#922: a register is a plain JSON file, so `--write-baseline` was never
    the only way to add an entry to it. That question needs no corpus."""
    p = tmp_path / "register.json"
    p.write_text(json.dumps({
        "previous_size": 1, "size": 1, "scope_expanded": None,
        "known": ["gateX::ic/a/r.json::PASS->VACUOUS_PASS::rule",
                  "gateX::ic/b/r.json::PASS->VACUOUS_PASS::rule"]}))
    rc, out = _run(STALE, _GONE, "--corpus-may-be-absent", "--baseline", str(p))
    assert rc == 1, (
        f"an entry appended by hand went green with no corpus\n{out}")
    assert "(register)" in out, out


def test_staleness_no_corpus_refuses_an_unreadable_register(tmp_path):
    p = tmp_path / "register.json"
    p.write_text("{not json")
    rc, out = _run(STALE, _GONE, "--corpus-may-be-absent", "--baseline", str(p))
    assert rc == 2, out
    assert "NOT CHECKED" in out, out


def test_staleness_write_baseline_with_no_corpus_is_refused(tmp_path):
    reg = _empty_register(tmp_path)
    before = Path(reg).read_text()
    rc, out = _run(STALE, _GONE, "--corpus-may-be-absent", "--baseline", reg,
                   "--write-baseline")
    assert rc == 2, out
    assert "REFUSED" in out, out
    assert Path(reg).read_text() == before, "the register was emptied anyway"


# ===========================================================================
# 8. THE SHIPPED CALL SITES CARRY THE FLAG. Everything above tests the
#    programs; this tests the only lines that ever invoke them in production.
#    Without it all three programs could be perfect and all three gates red.
# ===========================================================================
def _dispatchers():
    """Every wrapper `_gate_dispatch.sh` DEFINES, read from that file.

    THIS USED TO BE THE LITERAL `"run "`, and that is a name, not a property.
    `f7f00e9e48` moved two of the three dispatch lines below onto the sibling
    wrapper `run_tolerating_uncheckable`; the invocations were still there,
    still carrying the flag this test is about, and the test reported

        AssertionError: the hygiene sweep no longer invokes
                        cross_layer_reference_check.py at all

    which is not what it had measured. A predicate must not be able to say
    "not invoked" about a line it can see. Reading the dispatcher names from
    the file that defines them means a NEW wrapper cannot blind this test
    either, and it cannot drift into matching prose: the wrapper must be the
    line's FIRST token.

    The public dispatchers only — `_`-prefixed names in that file are its
    internals and never appear at a call site. WHICH WRAPPER a given gate
    deserves is a real question and a different test's:
    `test_issue1025_empty_corpus_sweep_blocks` owns it, and pins it for the
    one gate whose rc-2 must block. This test is section 8's question only —
    the shipped call sites carry the flag.
    """
    names = set(re.findall(r"^([A-Za-z][A-Za-z0-9_]*)\(\)",
                           DISPATCH.read_text(), re.M))
    assert names, (
        f"no dispatcher definitions found in {DISPATCH} — this test would "
        f"then match nothing and pass by looking at an empty set")
    return names


@pytest.mark.parametrize("prog", ["cross_layer_reference_check.py",
                                  "step_internal_fail_bubble_up_check.py",
                                  "published_record_staleness_check.py"])
def test_the_hygiene_sweep_actually_passes_the_flag(prog):
    sweep = REPO / "tools" / "ci" / "repo_hygiene_gates.sh"
    if not sweep.is_file():
        pytest.skip(f"{sweep} not present in this checkout")
    if not DISPATCH.is_file():
        pytest.skip(f"{DISPATCH} not present in this checkout")
    wrappers = _dispatchers()
    lines = [ln for ln in sweep.read_text().splitlines()
             if prog in ln and ln.strip().split(" ", 1)[0] in wrappers]
    assert lines, (
        f"the hygiene sweep no longer invokes {prog} through any of the "
        f"dispatchers {sorted(wrappers)}")
    assert all("--corpus-may-be-absent" in ln for ln in lines), (
        f"the sweep invokes {prog} without the flag, so a repo with no corpus "
        f"is still blocked:\n" + "\n".join(lines))
