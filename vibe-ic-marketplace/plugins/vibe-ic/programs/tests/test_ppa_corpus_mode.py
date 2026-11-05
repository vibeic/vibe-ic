#!/usr/bin/env python3
"""The corpus mode of the five PPA record gates, and the three ways it can lie.

WHAT THIS FILE IS DEFENDING
===========================
`ppa_head_to_head_check` took `--corpus` and resolved it through
`_corpus_location`; its five siblings took an EXACT document path, so a record
filed under any other name was simply not judged. Closing that asymmetry is
easy to do badly, and there are exactly three ways:

    an EMPTY corpus becomes rc 0        the gate now certifies a scan that
                                        never happened -- a vacuous 100%
                                        coverage, a frontier nobody
                                        recomputed, "every candidate feasible"
                                        over an empty list. Every one of those
                                        is the sentence its gate exists to
                                        refuse.
    an exact path AND a corpus          the caller named a document and got a
      are both accepted silently        verdict about a different population.
    two records for one identity        the walk takes `records[0]` and buries
      become a pick                     the disagreement, which is exactly what
                                        `_ppa.contract` refuses to do with two
                                        sources that disagree about a key.

So every gate below gets a POSITIVE corpus (one good record -> rc 0), a
NEGATIVE corpus (one bad record -> rc 1), a VACUOUS corpus (nothing -> rc 2
with the corpus root NAMED), a CONFLICT corpus, and a both-given refusal.

WHY THE RECORD IS FOUND BY CONTENT AND NOT BY NAME
==================================================
Several positives below deliberately file their record under a name no glob
would guess (`whatever-name.json`, `nested/deep/x.json`). The complaint that
produced the corpus mode is that a record under an unexpected name went
unjudged; a filename glob answers that complaint with a smaller version of
itself, so the selection is on the document's declared schema or shape.

chip-AGNOSTIC: synthetic bytes and declared policy only.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

pytestmark = pytest.mark.usefixtures("landing_corpus_binding_is_test_local")

TESTS = pathlib.Path(__file__).resolve().parent
PROGRAMS = TESTS.parent
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(TESTS))

from test_ppa_feasibility import VIEW, candidate, clean_metrics

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

CONTRACT_GATE = PROGRAMS / "ppa_contract_check.py"
MEASUREMENT_GATE = PROGRAMS / "ppa_measurement_check.py"
FEASIBILITY_GATE = PROGRAMS / "ppa_feasibility_check.py"
PARETO_GATE = PROGRAMS / "ppa_pareto_check.py"
INTEGRITY_GATE = PROGRAMS / "ppa_problem_integrity_check.py"

def gate(program, *args, env=None):
    """Drive the REAL entry point. Deliberately not `main(argv)` in-process:
    the flow acts on the EXIT CODE, and a test that calls a function leaves the
    verdict-to-exit-code mapping unmeasured."""
    return _pr.run([sys.executable, str(program), *args],
                          capture_output=True, text=True,
                          env=env)


def put(path: pathlib.Path, obj) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")
    return path


def corpus(tmp_path, name) -> pathlib.Path:
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Fixture documents
# ---------------------------------------------------------------------------
SCOPE = {"stage": "post_route_extracted", "process": "ss"}
SRC = {"path": "sta.rpt", "tool": "opensta"}
EXPECT_TWO = [
    {"metric": "area.die_um2", "scope": SCOPE},
    {"metric": "timing.setup.wns_ns", "scope": SCOPE},
]






def candidate_set(*cands, **extra):
    doc = {"candidates": list(cands), "required_views": [dict(VIEW)]}
    doc.update(extra)
    return doc


def infeasible_candidate(cid="bad"):
    ms = clean_metrics()
    ms[4]["value"] = "MISMATCH"          # LVS dirty -- one measured violation
    return candidate(cid, ms)






# ===========================================================================
# 1. ppa_contract_check
# ===========================================================================














# ===========================================================================
# 2. ppa_measurement_check
# ===========================================================================










# ===========================================================================
# 3. ppa_feasibility_check
# ===========================================================================
def test_feasibility_corpus_positive(tmp_path):
    c = corpus(tmp_path, "good")
    put(c / "runs" / "not-named-candidates.json",
        candidate_set(candidate("ok")))
    r = gate(FEASIBILITY_GATE, "--corpus", str(c))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "1 published candidate set(s) selected" in r.stdout


def test_feasibility_corpus_negative(tmp_path):
    c = corpus(tmp_path, "bad")
    put(c / "x.json", candidate_set(infeasible_candidate()))
    r = gate(FEASIBILITY_GATE, "--corpus", str(c))
    assert r.returncode == 1, r.stdout + r.stderr


def test_feasibility_corpus_vacuous_is_rc2_and_names_the_root(tmp_path):
    """"Every candidate is feasible" over an empty corpus is the empty-tree
    lie this gate already refuses for an empty candidate list."""
    c = corpus(tmp_path, "empty")
    r = gate(FEASIBILITY_GATE, "--corpus", str(c))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "VACUOUS" in r.stderr and str(c) in r.stderr


def test_feasibility_corpus_conflicting_candidate_id_is_refused(tmp_path):
    c = corpus(tmp_path, "conflict")
    put(c / "a.json", candidate_set(candidate("shared")))
    put(c / "b.json", candidate_set(infeasible_candidate("shared")))
    r = gate(FEASIBILITY_GATE, "--corpus", str(c))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "candidate_id" in r.stderr and "DISAGREE" in r.stderr


def test_feasibility_does_not_read_its_own_verdict_document_as_an_input(
        tmp_path):
    """`vibeic.ppa.feasibility.v1` carries a `candidates` key too. Selecting on
    shape alone would adjudicate the gate's own output as if it were a run."""
    c = corpus(tmp_path, "report_only")
    report = gate(FEASIBILITY_GATE, "--candidates",
                  str(put(tmp_path / "in.json",
                          candidate_set(candidate("ok")))),
                  "--json", str(tmp_path / "out.json"))
    assert report.returncode == 0, report.stderr
    put(c / "verdict.json",
        json.loads((tmp_path / "out.json").read_text(encoding="utf-8")))
    r = gate(FEASIBILITY_GATE, "--corpus", str(c))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "VACUOUS" in r.stderr


def test_feasibility_exact_and_corpus_together_is_bad_invocation(tmp_path):
    c = corpus(tmp_path, "both")
    one = put(tmp_path / "one.json", candidate_set(candidate("ok")))
    put(c / "a.json", candidate_set(candidate("ok")))
    r = gate(FEASIBILITY_GATE, "--candidates", str(one), "--corpus", str(c))
    assert r.returncode == 3, r.stdout + r.stderr
    assert "bad invocation" in r.stderr


# ===========================================================================
# 4. ppa_pareto_check
# ===========================================================================












# ===========================================================================
# 5. ppa_problem_integrity_check
# ===========================================================================




def test_integrity_corpus_vacuous_is_rc2_and_names_the_root(tmp_path):
    c = corpus(tmp_path, "empty")
    r = gate(INTEGRITY_GATE, "--corpus", str(c))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "VACUOUS" in r.stderr and str(c) in r.stderr




















# ===========================================================================
# 6. The shared seam itself
# ===========================================================================
