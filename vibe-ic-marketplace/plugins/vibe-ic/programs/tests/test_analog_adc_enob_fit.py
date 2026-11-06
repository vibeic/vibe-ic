#!/usr/bin/env python3
"""Guards for the A4 ENOB producer.

THE GAP, pinned by `test_the_only_corner_results_writer_never_writes_enob`:
the ENOB gate reads `enob`/`sndr_db` out of `corner_results.json`, and the one
program that writes that file never puts either field in it. Without a
producer, the gate can only SKIP. That test holds on the PRE-FIX tree too — it
is a statement about `analog_real_corner_sweep.py`, which this change does not
touch — so it stays true as a description of why this file exists.

The fit itself is guarded BIDIRECTIONALLY: a clean modulator and the SAME
modulator with injected quantiser noise must both MEASURE and must DIFFER in
the right direction. A test that only asserts "a number came out" would pass
against a function that returns a constant.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

GATE = _PROGRAMS / "analog_adc_enob_corner_check.py"

FS = 1e6


# ---------------------------------------------------------------------------
# 1. the fit MEASURES, and it DISCRIMINATES
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 2. it REFUSES rather than inventing a number
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 3. the row it writes is the row the GATE reads — proven by driving the gate
# ---------------------------------------------------------------------------
def _block(tmp_path, target=14.0):
    b = tmp_path / "phase3" / "analog" / "adc"
    b.mkdir(parents=True)
    (b / "spec.json").write_text(json.dumps({
        "specs": [{"name": "enob", "min": target},
                  {"name": "fclk", "target": FS},
                  {"name": "tone", "target": TONE},
                  {"name": "osr", "target": OSR}]}))
    return b


def test_before_this_producer_the_gate_cannot_reach_a_verdict(tmp_path):
    """The pre-fix state, driven rather than asserted: with an ENOB target and
    no corner_results.json the gate reports NO MEASURED ENOB and does not pass.

    THE ASSERTION IS THE SUBSTANCE, NOT THE WORD. This test used to require
    `rc == 0` and the literal word SKIP, which described how live main behaved
    when the branch was written (2026-07-30). Main has since made that state
    honest on its own: the gate now exits 2 with

        [UNMEASURED] analog_adc_enob_corner_check: a block declares this axis
        and no data measures it — not a pass.

    which is a strictly better answer to the same question, and the old test
    failed on the improvement. What this branch is about is that no ENOB can be
    REACHED without a producer, so that is what is asserted; both SKIP and
    UNMEASURED satisfy it and a measured number does not."""
    b = _block(tmp_path)
    out = tmp_path / "g.json"
    r = subprocess.run([sys.executable, str(GATE), str(tmp_path),
                        "--json", str(out)], capture_output=True, text=True)
    blob = (out.read_text() if out.exists() else "") + r.stdout + r.stderr
    assert not (b / "corner_results.json").exists()
    # not a pass, by either spelling
    assert r.returncode != 0 or "SKIP" in blob.upper(), blob
    # and NO measured ENOB anywhere in what it reported
    verdict = json.loads(out.read_text()) if out.exists() else {}
    assert not _reported_enobs(verdict), (
        f"the gate reported an ENOB with no producer present: {verdict}")


# ---------------------------------------------------------------------------
# 4. the gap statement itself — holds on the pre-fix tree
# ---------------------------------------------------------------------------
def _reported_enobs(verdict):
    """Every MEASURED enob the gate put in its own report."""
    rows = []
    for key in ("blocks", "corners", "rows", "results"):
        v = verdict.get(key) if isinstance(verdict, dict) else None
        if isinstance(v, list):
            rows.extend(x for x in v if isinstance(x, dict))
    out = [r for r in rows
           if isinstance(r.get("enob"), (int, float))
           or isinstance(r.get("sndr_db"), (int, float))]
    if isinstance(verdict, dict) and isinstance(verdict.get("enob"), (int, float)):
        out.append(verdict)
    return out


def test_a_corner_sweep_row_alone_never_carries_a_measured_enob(tmp_path):
    """The gap statement, asserted BEHAVIOURALLY instead of by reading source.

    This was a substring scan: it required the literal `sndr` to be absent from
    `analog_real_corner_sweep.py`. That is not the property anybody wanted, and
    it broke on an unrelated landing — main added a SPEC-NAME NORMALISATION
    table so a converter's declared L5 target can be read at all::

        "sndr":    {"sndr", "sinad", "signaltonoiseanddistortion"},

    Reading a declared spec NAME is not emitting a measured value, so the scan
    fired on a change that has nothing to do with this branch. A test that
    watches a file's spelling watches the wrong thing.

    The invariant that matters: a corner row as the sweep produces it — no
    `enob`, no `sndr_db` — cannot make the gate report a measured ENOB. That is
    checked by RUNNING the gate on exactly such a row, so an unrelated edit to
    any producer's prose can never move it."""
    b = _block(tmp_path)
    (b / "corner_results.json").write_text(json.dumps({"corners": [
        {"name": "tt_27c", "status": "OK", "vout": 1.8},
        {"name": "ff_125c", "status": "OK", "vout": 1.81}]}), encoding="utf-8")
    out = tmp_path / "g.json"
    r = subprocess.run([sys.executable, str(GATE), str(tmp_path),
                        "--json", str(out)], capture_output=True, text=True)
    verdict = json.loads(out.read_text()) if out.exists() else {}
    assert not _reported_enobs(verdict), (
        f"a sweep row with no enob/sndr_db yielded a measured ENOB: {verdict}")
    assert r.returncode != 0 or "SKIP" in (r.stdout + r.stderr).upper(), (
        r.stdout + r.stderr)
