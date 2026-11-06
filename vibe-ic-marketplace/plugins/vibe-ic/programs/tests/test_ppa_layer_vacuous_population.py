#!/usr/bin/env python3
"""The VACUOUS arm, at the level the absent-file arm cannot reach.

TWO DIFFERENT EMPTINESSES, AND ONLY ONE OF THEM WAS TESTED
==========================================================
`test_ppa_layer_exit_contract.py` invokes every program against input that is
NOT THERE. That arm is green across the layer: every program answers 2 with a
marker. It is also the easy half.

The half that gets missed is input that IS there, IS well-formed, and holds
NOTHING:

    a metric bundle whose `records` list is empty
    a search space that declares no lever
    a candidate set with `"candidates": []`
    a corpus directory containing no record

The file opens, the parse succeeds, the population is zero, and the natural
control flow -- `for x in population: check(x)` followed by `return rc` -- falls
straight through to 0. That is not a hypothetical: `docs/PPA_INTERFACES.md` §7
says this repository has shipped it twice, and this file found two more.

MEASURED ON `e36d81c0a` (v1.11.33), BEFORE THIS BRANCH
======================================================
    ppa_metric_extract.py --records <bundle with "records": []>   rc=0
        printed "1 document(s) named, 1 read, 0 record(s) indexed" and
        exited 0. The program ALREADY guarded `n_docs == 0` with the
        comment "An empty bundle would read as a clean run" -- the same
        sentence, one level in, was not guarded.  FIXED in this branch.

    ppa_predict_aggregate.py --cell-count 0                       rc=0
        published "Estimated area: 0.0 um^2 / power 0.00 uW" and exited 0.
        §2 forbids exactly this: `0` never means "not measured".
        FIXED in this branch.

    ppa_search_run.py '{}'                                        rc=0
        invented "budget 1 trial(s) / 1 full-PnR: proposed 1, ran 0" over a
        document declaring no lever at all, and exited 0. FIXED: before a
        candidate is proposed the CLI now REFUSES (rc=2) a space that names
        no population -- no lever searchable and none recorded as
        unsearchable -- and publishes no manifest. A space that merely
        proposes no VALUE still names its levers and stays a PASS. Mutation
        arm + positive control at the foot of this file.

WHY THIS IS A SEPARATE FILE FROM THE EXIT CONTRACT
==================================================
Because the invocations are not uniform. "Absent" is one shape for every
program; "present and empty" is a different document per program, and writing
them means knowing what each program's population IS. A table that pretends
otherwise would emit an input the program legitimately reads as non-empty, and
then the arm passes for the wrong reason.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_TESTS = pathlib.Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent


def _run(args, timeout=120):
    return _pr.run([sys.executable, *args], capture_output=True,
                          text=True, cwd=str(_PROGRAMS))




def _w(p: pathlib.Path, obj) -> str:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj) if not isinstance(obj, str) else obj,
                 encoding="utf-8")
    return str(p)


# Each entry: (program, how to build the EMPTY-but-well-formed input,
#              what the population is). The third field is prose for the
#              failure message -- a reader of a red needs to know what was
#              supposed to be in there.






# ---------------------------------------------------------------------------
# MUTATION ARMS for the two fixes this branch makes
# ---------------------------------------------------------------------------
def test_mutation_metric_extract_empty_bundle(tmp_path):
    """MUTATION ARM. Revert `report["records"] == 0` from the rc branch in
    `ppa_metric_extract.main` and this goes red: the run reports a bundle
    written and exits 0 having indexed nothing."""
    b = _w(tmp_path / "m.json", {"schema": "vibeic.ppa.metric_bundle.v1",
                                 "records": []})
    r = _run(["ppa_metric_extract.py", "--records", b])
    assert r.returncode == 2
    assert "NOT ONE record was indexed" in r.stderr, r.stderr[:400]


def test_mutation_metric_extract_still_passes_on_a_real_record(tmp_path):
    """The positive control for the arm above -- without it, `return 2`
    unconditionally would also make it green, and the fix would have broken
    every real extraction."""
    rec = {"schema": "vibeic.ppa.metric.v1",
           "metric": "timing.setup.wns_ns", "status": "MEASURED",
           "value": -0.124, "unit": "ns",
           "scope": {"stage": "post_route_extracted", "process": "ss",
                     "check": "setup", "clock": "clk"},
           "source": {"path": "sta.rpt", "sha256": "sha256:" + "ab" * 32,
                      "tool": "opensta", "parser": "p.py",
                      "parser_sha256": "sha256:" + "cd" * 32}}
    b = _w(tmp_path / "one.json", {"schema": "vibeic.ppa.metric_bundle.v1",
                                   "records": [rec]})
    r = _run(["ppa_metric_extract.py", "--records", b])
    assert r.returncode == 0, (
        f"a bundle carrying one valid record must still pass. "
        f"rc={r.returncode}\nstdout: {r.stdout[:400]}\n"
        f"stderr: {r.stderr[:400]}")
    assert "1 record(s) indexed" in r.stdout, r.stdout[:300]


def test_mutation_predict_aggregate_zero_cells(tmp_path):
    """MUTATION ARM. Remove the `args.cell_count <= 0` guard and this goes
    red: the program prints `Estimated area: 0.0 um²` and exits 0."""
    r = _run(["ppa_predict_aggregate.py", "--cell-count", "0"])
    assert r.returncode == 2, r.stdout[:400]
    assert "[CANNOT CHECK]" in r.stderr
    assert "0.0 um" not in r.stdout, (
        "a zero-cell estimate was printed anyway; the refusal must produce no "
        "estimate at all, or a reader downstream picks the number up")


def test_mutation_predict_aggregate_still_estimates_a_real_count():
    """Positive control for the guard above."""
    r = _run(["ppa_predict_aggregate.py", "--cell-count", "262"])
    assert r.returncode == 0, r.stderr[:400]
    assert "ESTIMATED" in r.stdout


def test_mutation_search_run_space_with_no_searchable_lever(tmp_path):
    """MUTATION ARM. Delete the `if not values and not lever_notes` guard from
    `ppa_search_run.build` and this goes red: the run publishes
    `proposed 1, ran 0` over a document that names no lever at all and exits
    0. The guard's line is NOT `values is empty` -- a space that proposes no
    value still names every lever it could not enumerate, and
    `test_ppa_pnr_search_space` pins that degrade as a PASS."""
    sp = _w(tmp_path / "s.json", {})
    r = _run(["ppa_search_run.py", sp, "--json", str(tmp_path / "m.json")])
    assert r.returncode == 2, r.stdout[:400]
    assert "names no population" in r.stderr, r.stderr[:400]
    assert "proposed 1" not in (r.stdout + r.stderr), (
        "the fabricated budget sentence was printed anyway; the refusal must "
        "produce no trial count at all")
    assert not (tmp_path / "m.json").exists() or \
        "candidates" not in json.loads(
            (tmp_path / "m.json").read_text(encoding="utf-8")), \
        "no manifest may be left on disk for the next stage to read"


def test_mutation_search_run_still_searches_a_real_space(tmp_path):
    """Positive control for the guard above -- without it, an unconditional
    `return 2` would also make the arm green and every real search would be
    refused. A space with one enumerable lever must still produce its manifest
    and its real counts."""
    sp = _w(tmp_path / "real.json",
            {"program": "crosslayer_search_space",
             "levers": [{"lever": "state_encoding", "admitted": True,
                         "status": "FREE", "domain": "binary | gray"}]})
    out = tmp_path / "real_manifest.json"
    r = _run(["ppa_search_run.py", sp, "--json", str(out)])
    assert r.returncode == 0, f"stderr: {r.stderr[:400]}"
    assert "budget 1 trial(s)" in r.stdout, r.stdout[:400]
    man = json.loads(out.read_text(encoding="utf-8"))
    assert len(man["candidates"]) == 2, \
        "both points of a two-value lever must still be published"
    assert [c["knobs"]["state_encoding"] for c in man["candidates"]] == \
        ["binary", "gray"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
