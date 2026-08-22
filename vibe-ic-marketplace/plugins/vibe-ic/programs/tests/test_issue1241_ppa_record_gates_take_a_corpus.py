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


CC = _load("_ppa_contract_cli", "ppa_contract_check.py")
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

def test_contract_corpus_finds_by_declaration_not_by_filename(tmp_path):
    _write(tmp_path / "deep" / "not_called_contract.json",
           {"schema": CC.C.CONTRACT_SCHEMA, "run_label": "a"})
    _write(tmp_path / "contract.json", {"schema": "vibeic.ppa.metric.v1"})
    found = _seam_walk(CC.is_contract, tmp_path)
    assert [p.name for p in found] == ["not_called_contract.json"], (
        "a document is a contract because it says so, not because of its name")


def test_contract_corpus_absent_is_two_and_never_zero(tmp_path):
    assert CC.main(["--corpus", str(tmp_path / "nope")]) == 2


def test_contract_corpus_present_but_empty_is_two_and_never_zero(tmp_path):
    (tmp_path / "empty").mkdir()
    assert CC.main(["--corpus", str(tmp_path / "empty")]) == 2, (
        "a corpus that carries no contract has not certified one")


def test_contract_corpus_needs_exactly_one_of_contract_or_corpus(tmp_path):
    """3 AND NOT 2, and the correction is the point.

    This asserted 2 for both, which predates `_ppa/cli_exit.parse_or_refuse`.
    §1 separates them deliberately: 2 is "I could not look", 3 is "you invoked
    me wrong", and collapsing them is how a stale flag in the wiring reads as a
    row that ran. That is not hypothetical here -- both `PPA arms solved one
    problem` rows passed `--baseline` beside `--corpus`, exited 3, examined no
    pair in either campaign, and nothing in the roll-up told it from a pass.

    THAT OBSERVATION IS PAST TENSE as of the 2026-08-22 option-3 ruling: the
    gate now answers `--baseline X --corpus Y` as its own question and those two
    rows PASS, over 20 and 60 pairs. It is left here because it is why 3 and 2
    must stay apart, and that reason did not expire with the symptom.
    """
    assert CC.main([]) == 3
    assert CC.main(["--contract", "a", "--corpus", "b"]) == 3


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

def test_an_unreadable_named_document_stays_in_the_corpus(tmp_path):
    """UNREADABLE IS NOT ABSENT. A truncated `contract.json` must be adjudicated
    UNDETERMINED, never dropped as though it had never been filed."""
    # WHERE THE PROPERTY LIVES NOW. `collect` splits what it opened into
    # `records` (selected) and `unreadable` (could not be decided either way),
    # and a document that cannot be parsed cannot be SELECTED -- there is
    # nothing to run the predicate on. So "stays in the corpus" is asserted on
    # `unreadable`, not on `records`, and the load-bearing half is unchanged:
    # the verdict is 2 and the file is NAMED, never dropped to a silent pass.
    (tmp_path / "contract.json").write_text('{"schema": "vibeic.ppa.',
                                            encoding="utf-8")
    scan = corpus_seam.collect(tmp_path, CC.is_contract)
    assert [q.name for q, _ in scan.unreadable] == ["contract.json"]
    assert scan.files == 1, "the denominator must count what was OPENED"
    assert "unreadable" in scan.denominator("contract(s)"), (
        "the roll-up hides the unreadable document, so a reader sizes the "
        "population wrongly")
    assert CC.main(["--corpus", str(tmp_path)]) == 2

    (tmp_path / "candidates.json").write_text('{"candidates": [',
                                              encoding="utf-8")
    scan = corpus_seam.collect(tmp_path, FC.is_candidate_set)
    assert sorted(q.name for q, _ in scan.unreadable) == [
        "candidates.json", "contract.json"]
    assert FC.main(["--corpus", str(tmp_path)]) == 2


def test_a_refusal_is_not_softened_by_an_undetermined_beside_it(tmp_path):
    """THE DEFEAT-THE-GATE SHAPE, asserted through the program.

    `max()` over exit codes makes 2 the winning verdict, so a corpus holding one
    REFUSED document and one UNDETERMINED document would roll up to 2 — "could
    not check" — and the refusal would never reach the reader. Adding a document
    must never SUBTRACT a finding. `ppa_head_to_head_check`'s `_SEVERITY`
    comment records this happening for real.
    """
    # A contract that declares the schema and nothing else is REFUSED (rc 1):
    # its identities and evidence manifest are absent, which is a finding.
    _write(tmp_path / "refused_contract.json", {"schema": CC.C.CONTRACT_SCHEMA})
    assert CC.main(["--corpus", str(tmp_path)]) == 1, "the refusal alone is rc 1"

    # Now put an UNDETERMINED document beside it. Under max() this becomes 2.
    (tmp_path / "truncated_contract.json").write_text('{"schema": "vibeic',
                                                      encoding="utf-8")
    assert CC.main(["--corpus", str(tmp_path)]) == 1, (
        "an undetermined document beside a refused one does not soften it")


def test_the_contract_roll_up_is_not_softened_by_a_pass_either(tmp_path):
    """The other half: a clean document beside a refused one is still rc 1."""
    _write(tmp_path / "refused_contract.json", {"schema": CC.C.CONTRACT_SCHEMA})
    _write(tmp_path / "b" / "another_contract.json",
           {"schema": CC.C.CONTRACT_SCHEMA})
    assert CC.main(["--corpus", str(tmp_path)]) == 1
