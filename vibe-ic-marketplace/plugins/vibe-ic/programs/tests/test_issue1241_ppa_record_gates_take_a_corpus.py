#!/usr/bin/env python3
"""`ppa_contract_check` and `ppa_feasibility_check` must be able to judge a
CORPUS, and the corpus verdict must never be softer than its worst member.

WHY (vibe-ic#1241, measured 2026-08-22 on origin/main a00f53f20). Both gates
were wired at an EXACT path under `benchmark-data/ppa/`, a directory that left
this repository in v1.10.56. Both exited 2 naming that absent file, under
exemptions declaring "no run in this repository has filed one yet". Eighty-two
contracts and twenty-one candidate sets are filed here. An exact path could not
find them, and one exact path could only ever have judged one of them.

The two properties that make a corpus mode worth having rather than merely
convenient are asserted below:

  IT MUST NOT BE ABLE TO LAUNDER A REFUSAL. `max()` over exit codes makes 2 the
  winning verdict, so adding one unreadable document to a corpus holding one
  refused document would return 2 — "could not check" — and SUBTRACT a finding.
  That exact defeat-the-gate shape is documented in `ppa_head_to_head_check`'s
  `_SEVERITY` comment, where it was measured happening.

  ABSENT AND EMPTY MUST NOT SHARE A VERDICT, and neither may be a pass.
"""
import importlib.util
import json
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"
sys.path.insert(0, str(PROGRAMS))


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, PROGRAMS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FC = _load("_ppa_feasibility_cli", "ppa_feasibility_check.py")


import _ppa_corpus as corpus_seam  # noqa: E402  the shared walk


def _seam_walk(predicate, d):
    """The walk these gates now share, reached the way they reach it.

    `corpus_contracts` and `corpus_candidate_sets` were replaced by a SELECTION
    PREDICATE handed to `_ppa_corpus.collect`, and this file went on calling the
    old names, so it raised AttributeError before reaching a single assertion.
    THE WALK IS STILL PROGRAM CODE -- `collect` is the seam and the predicate is
    the gate's own -- so nothing under test moves into this file. That is what
    makes this an ADAPTER rather than the vacuous shim the problem-integrity
    guard needed a rewrite instead of.
    """
    return [path for path, _ in corpus_seam.collect(d, predicate).records]


#: The candidates schema, as a LITERAL and no longer read off the program.
#: `_CANDIDATES_SCHEMA` has no successor because selection stopped being a
#: schema comparison at all: `is_candidate_set` decides on the document's SHAPE
#: (a mapping carrying a `candidates` list, excluding this lane's own output
#: schemas). The string here is what a producer declares, which is exactly what
#: a fixture should state for itself rather than borrow from the reader.
_CANDIDATES_SCHEMA = "vibeic.ppa.candidates.v1"


def _write(path: Path, doc) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return path


# --- contract corpus -------------------------------------------------------









# --- feasibility corpus ----------------------------------------------------

def _candidate_set(cid, feasible):
    """A one-candidate set. `feasible=False` withholds the metric an axis needs,
    which is how a real INFEASIBLE/UNDETERMINED arises."""
    return {"schema": _CANDIDATES_SCHEMA,
            "required_views_by_axis": {"drv": [{"stage": "post_route"}]},
            "required_views": [{"stage": "post_route"}],
            "limits": {},
            "allow_waivers": False,
            "candidates": [{"candidate_id": cid,
                            "metrics": ([] if not feasible else [])}]}


def test_feasibility_corpus_finds_by_declaration_not_by_filename(tmp_path):
    _write(tmp_path / "x" / "arm.json", _candidate_set("a", True))
    _write(tmp_path / "candidates.json", {"schema": "vibeic.ppa.contract.v1"})
    assert [p.name for p in _seam_walk(FC.is_candidate_set, tmp_path)] == ["arm.json"]


def test_feasibility_corpus_absent_is_two_and_never_zero(tmp_path):
    assert FC.main(["--corpus", str(tmp_path / "nope")]) == 2


def test_feasibility_corpus_present_but_empty_is_two_and_never_zero(tmp_path):
    (tmp_path / "empty").mkdir()
    assert FC.main(["--corpus", str(tmp_path / "empty")]) == 2


def test_feasibility_corpus_needs_exactly_one_of_candidates_or_corpus():
    assert FC.main([]) == 3
    assert FC.main(["--candidates", "a", "--corpus", "b"]) == 3


# --- the roll-up, which is the whole point ---------------------------------
