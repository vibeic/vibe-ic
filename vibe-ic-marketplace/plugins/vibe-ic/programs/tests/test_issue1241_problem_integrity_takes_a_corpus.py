#!/usr/bin/env python3
"""`ppa_problem_integrity_check --corpus` — every published pair, not the headline pair.

WHY (vibe-ic#1241). This gate was wired at ONE exact pair under
`benchmark-data/ppa/`, a directory that left this repository in v1.10.56, so it
compared nothing at all. Re-aiming it at the comparison each campaign quotes made
it decide — about TWO pairs, while EIGHTY sit committed in this tree: `b000`
against 20 cross-layer trials and `baseline` against 60 end-to-end trials.

A gate examining 2 of 80 available comparisons is under-aimed by exactly the
argument that re-aimed it. A contract that drifts in trial 37 is a comparison
nobody may quote, and with two rows nothing would say so.

The properties asserted here are the ones that make a corpus mode worth having
rather than merely wider, and they are the same three the other corpus gates in
this family are pinned on: the baseline is never paired with ITSELF (which would
manufacture a comparison that trivially holds), a refusal is never softened by an
undetermined beside it, and absent / empty / present are three outcomes, none of
which is a pass.
"""
import importlib.util
import json
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"
sys.path.insert(0, str(PROGRAMS))

_spec = importlib.util.spec_from_file_location(
    "_ppa_pi_cli", PROGRAMS / "ppa_problem_integrity_check.py")
PI = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(PI)


def _write(path: Path, doc) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return path


def _contract(**over):
    doc = {"schema": PI._CONTRACT_SCHEMA, "run_label": "x"}
    doc.update(over)
    return doc


def test_the_baseline_is_never_paired_with_itself(tmp_path):
    """A contract compared against itself matches on every identity by
    construction. Counting that as a passing pair would be the gate writing its
    own evidence, and it would make a corpus of ONE document look checked."""
    base = _write(tmp_path / "records" / "baseline" / "contract.json",
                  _contract())
    assert PI.corpus_candidates(tmp_path, base) == []


def test_a_second_contract_becomes_a_pair(tmp_path):
    base = _write(tmp_path / "b" / "contract.json", _contract())
    _write(tmp_path / "t1" / "contract.json", _contract(run_label="t1"))
    assert [p.parent.name for p in PI.corpus_candidates(tmp_path, base)] == ["t1"]


def test_the_corpus_is_identified_by_declaration_not_by_filename(tmp_path):
    base = _write(tmp_path / "b" / "contract.json", _contract())
    _write(tmp_path / "t1" / "not_called_contract.json", _contract(run_label="t1"))
    _write(tmp_path / "t2" / "contract.json", {"schema": "vibeic.ppa.metric.v1"})
    assert [p.name for p in PI.corpus_candidates(tmp_path, base)] == [
        "not_called_contract.json"]


def test_an_unreadable_named_contract_stays_in_the_population(tmp_path):
    """UNREADABLE IS NOT ABSENT: the pair it would have formed must be reported
    rc 2, not dropped as though the trial had never been filed."""
    base = _write(tmp_path / "b" / "contract.json", _contract())
    (tmp_path / "t1").mkdir()
    (tmp_path / "t1" / "contract.json").write_text('{"schema": "vibeic',
                                                   encoding="utf-8")
    assert [p.parent.name for p in PI.corpus_candidates(tmp_path, base)] == ["t1"]
    assert PI.main(["--baseline", str(base), "--corpus", str(tmp_path)]) == 2


def test_absent_corpus_is_two_and_never_zero(tmp_path):
    base = _write(tmp_path / "b" / "contract.json", _contract())
    assert PI.main(["--baseline", str(base),
                    "--corpus", str(tmp_path / "nope")]) == 2


def test_a_corpus_holding_only_the_baseline_is_two_and_never_zero(tmp_path):
    """VACUOUS. Nothing was compared, and 'no pair to make' must not print the
    same verdict as 'every pair held'."""
    base = _write(tmp_path / "b" / "contract.json", _contract())
    assert PI.main(["--baseline", str(base), "--corpus", str(tmp_path)]) == 2


def test_needs_exactly_one_of_candidate_or_corpus(tmp_path):
    base = _write(tmp_path / "b" / "contract.json", _contract())
    assert PI.main(["--baseline", str(base)]) == 2
    assert PI.main(["--baseline", str(base), "--candidate", "a",
                    "--corpus", "b"]) == 2


def _identity(kind, digest):
    """The real shape: an identity is a RECORD, not a bare digest string."""
    return {"schema": "vibeic.ppa.identity.v1", "kind": kind,
            "digest": f"sha256:{digest}", "status": "MEASURED",
            "members": {"artefacts": [], "facts": []}}


def test_a_refusal_is_not_softened_by_an_undetermined_beside_it(tmp_path):
    """THE DEFEAT-THE-GATE SHAPE. Under `max()`, [1, 2] rolls up to 2 and adding
    an unreadable contract would SUBTRACT a refusal from the corpus verdict."""
    base = _write(tmp_path / "b" / "contract.json", _contract(
        identities={"problem": _identity("problem", "a" * 8)}))
    _write(tmp_path / "t1" / "contract.json", _contract(
        run_label="t1", identities={"problem": _identity("problem", "b" * 8)}))
    alone = PI.main(["--baseline", str(base), "--corpus", str(tmp_path)])
    assert alone == 1, "a pair that disagrees on the problem identity is rc 1"

    (tmp_path / "t2").mkdir()
    (tmp_path / "t2" / "contract.json").write_text("{oops", encoding="utf-8")
    assert PI.main(["--baseline", str(base), "--corpus", str(tmp_path)]) == 1, (
        "an unreadable contract beside a refused pair does not soften it")


def test_an_internal_error_is_rc_3_and_never_rc_1(tmp_path):
    """§1: 1 is reserved for a finding about the design.

    NEWLY REACHABLE. While this gate compared ONE hand-named pair, a crash was a
    local accident. `--corpus` sweeps a whole campaign, so one document whose
    `identities` are shaped wrong decides the entire row — and without the guard
    the traceback exits 1, which the roll-up reads as "these two runs were not
    solving the same problem". That verdict was never reached by anything.
    """
    import subprocess
    base = _write(tmp_path / "b" / "contract.json",
                  _contract(identities={"problem": "not-a-record"}))
    _write(tmp_path / "t1" / "contract.json",
           _contract(run_label="t1", identities={"problem": "also-not-one"}))
    out = subprocess.run(
        [sys.executable, str(PROGRAMS / "ppa_problem_integrity_check.py"),
         "--baseline", str(base), "--corpus", str(tmp_path)],
        capture_output=True, text=True, timeout=120)
    assert out.returncode == 3, (
        f"rc={out.returncode}; an internal error must never wear the exit code "
        f"reserved for a finding\n{out.stderr[-600:]}")
    assert "internal error" in out.stderr
    assert "NOT a finding" in out.stderr
