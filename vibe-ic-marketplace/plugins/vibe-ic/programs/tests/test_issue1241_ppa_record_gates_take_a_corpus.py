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


def _write(path: Path, doc) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return path


# --- contract corpus -------------------------------------------------------

def test_contract_corpus_finds_by_declaration_not_by_filename(tmp_path):
    _write(tmp_path / "deep" / "not_called_contract.json",
           {"schema": CC._CONTRACT_SCHEMA, "run_label": "a"})
    _write(tmp_path / "contract.json", {"schema": "vibeic.ppa.metric.v1"})
    found = CC.corpus_contracts(tmp_path)
    assert [p.name for p in found] == ["not_called_contract.json"], (
        "a document is a contract because it says so, not because of its name")


def test_contract_corpus_absent_is_two_and_never_zero(tmp_path):
    assert CC.main(["--corpus", str(tmp_path / "nope")]) == 2


def test_contract_corpus_present_but_empty_is_two_and_never_zero(tmp_path):
    (tmp_path / "empty").mkdir()
    assert CC.main(["--corpus", str(tmp_path / "empty")]) == 2, (
        "a corpus that carries no contract has not certified one")


def test_contract_corpus_needs_exactly_one_of_contract_or_corpus(tmp_path):
    assert CC.main([]) == 2
    assert CC.main(["--contract", "a", "--corpus", "b"]) == 2


# --- feasibility corpus ----------------------------------------------------

def _candidate_set(cid, feasible):
    """A one-candidate set. `feasible=False` withholds the metric an axis needs,
    which is how a real INFEASIBLE/UNDETERMINED arises."""
    return {"schema": FC._CANDIDATES_SCHEMA,
            "required_views_by_axis": {"drv": [{"stage": "post_route"}]},
            "required_views": [{"stage": "post_route"}],
            "limits": {},
            "allow_waivers": False,
            "candidates": [{"candidate_id": cid,
                            "metrics": ([] if not feasible else [])}]}


def test_feasibility_corpus_finds_by_declaration_not_by_filename(tmp_path):
    _write(tmp_path / "x" / "arm.json", _candidate_set("a", True))
    _write(tmp_path / "candidates.json", {"schema": "vibeic.ppa.contract.v1"})
    assert [p.name for p in FC.corpus_candidate_sets(tmp_path)] == ["arm.json"]


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
    (tmp_path / "contract.json").write_text('{"schema": "vibeic.ppa.',
                                            encoding="utf-8")
    assert [p.name for p in CC.corpus_contracts(tmp_path)] == ["contract.json"]
    assert CC.main(["--corpus", str(tmp_path)]) == 2

    (tmp_path / "candidates.json").write_text('{"candidates": [',
                                              encoding="utf-8")
    assert [p.name for p in FC.corpus_candidate_sets(tmp_path)] == [
        "candidates.json"]
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
    _write(tmp_path / "refused_contract.json", {"schema": CC._CONTRACT_SCHEMA})
    assert CC.main(["--corpus", str(tmp_path)]) == 1, "the refusal alone is rc 1"

    # Now put an UNDETERMINED document beside it. Under max() this becomes 2.
    (tmp_path / "truncated_contract.json").write_text('{"schema": "vibeic',
                                                      encoding="utf-8")
    assert CC.main(["--corpus", str(tmp_path)]) == 1, (
        "an undetermined document beside a refused one does not soften it")


def test_the_contract_roll_up_is_not_softened_by_a_pass_either(tmp_path):
    """The other half: a clean document beside a refused one is still rc 1."""
    _write(tmp_path / "refused_contract.json", {"schema": CC._CONTRACT_SCHEMA})
    _write(tmp_path / "b" / "another_contract.json",
           {"schema": CC._CONTRACT_SCHEMA})
    assert CC.main(["--corpus", str(tmp_path)]) == 1
