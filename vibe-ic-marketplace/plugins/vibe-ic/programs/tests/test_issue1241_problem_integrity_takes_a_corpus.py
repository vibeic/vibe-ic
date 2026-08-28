#!/usr/bin/env python3
"""`ppa_problem_integrity_check --corpus` — every published pair, not the headline pair.

WHY (vibe-ic#1241). This gate was wired at ONE exact pair under
`benchmark-data/ppa/`, a directory that left this repository in v1.10.56, so it
compared nothing at all. Re-aiming it at the comparison each campaign quotes
made it decide — about TWO pairs, while EIGHTY sat committed in this tree.

A gate examining 2 of 80 available comparisons is under-aimed by exactly the
argument that re-aimed it. A contract that drifts in trial 37 is a comparison
nobody may quote, and with two rows nothing would say so.

WHY THIS FILE WAS REWRITTEN, AND WHAT IT COST TO FIND OUT
=========================================================
Every test here was RED, and had been, on `AttributeError: module has no
attribute '_CONTRACT_SCHEMA'`. That is a guard raising before it reaches an
assertion — which checks nothing at all, and is worse than a gate reporting
NOT_CHECKED because it also occupies the slot a real check would go in.

The cause was not a rename with a forwarding address. `--corpus` mode was
rebuilt: it no longer takes a baseline and pairs everything against it, it
GROUPS contracts by their problem identity and pairs inside each group. So
`corpus_candidates(corpus, baseline)` did not move, it stopped existing, and the
PROPERTIES it carried had to be re-expressed one level up. A shim restoring the
old signature inside this file would have made these tests vacuous — the
exclusion performed by the test and then asserted by the test, with the program
out of the loop.

WHAT THAT COST: while this file was red, NOTHING was checking
`test_an_internal_error_is_rc_3_and_never_rc_1`, and the guard it pins was
absent from the program. Two contracts that GROUP on a well-formed `problem`
identity but whose `analysis` is a bare digest STRING raised AttributeError out
of `identity.compare`, the traceback escaped, and the process exited **1** — the
code §1 reserves for "these two runs were not solving the same problem", a
verdict nothing reached. In corpus mode ONE such document decides a row over a
whole campaign, and the wired rows sweep 21 and 61 contracts. Fixed in the
program alongside this rewrite.

EVERY NUMBER BELOW WAS MEASURED BEFORE IT WAS ASSERTED, and the positive control
is the load-bearing one: without a corpus that reaches rc 0, every refusal test
here is satisfied by a gate that refuses everything.

    comparable pair                     rc 0, 1 pair
    one contract alone                  rc 2, 0 pairs      <- never self-paired
    three comparable                    rc 0, 3 pairs      = C(3,2)
    toolchain differs                   rc 1, PPA-C-012
    comparable + an unreadable document rc 2               <- unread outranks a pass
    REFUSED pair + an unreadable one    rc 1               <- and never softens a refusal
    a contract under another filename   rc 0, 1 pair       <- selection by declaration

chip-AGNOSTIC: no design, PDK, vendor or node literal.
"""
import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"
sys.path.insert(0, str(PROGRAMS))

_spec = importlib.util.spec_from_file_location(
    "_ppa_pi_cli", PROGRAMS / "ppa_problem_integrity_check.py")
PI = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(PI)

C = PI.C

#: The three identities `_MUST_MATCH` names. A pair that agrees on all three and
#: differs on `implementation` is the one shape that may be quoted.
_SAME = {"problem": "a" * 8, "analysis": "c" * 8, "toolchain": "t" * 8}


def _identity(kind, digest):
    """The real shape: an identity is a RECORD, not a bare digest string."""
    return {"schema": "vibeic.ppa.identity.v1", "kind": kind,
            "digest": f"sha256:{digest}", "status": "MEASURED",
            "members": {"artefacts": [], "facts": []}}


def _contract(run_label, implementation="e" * 8, **over):
    """A contract that HASHES TO ITS OWN DIGEST, which is not decoration.

    `PPA-C-001` refuses a contract whose `contract_digest` does not match its
    own content -- "it was edited after it was built, so it describes a document
    that no longer exists". A fixture that omits it is refused for that, and
    every test built on it then asserts a refusal it did not mean to cause.
    """
    ids = {k: _identity(k, v) for k, v in _SAME.items()}
    ids["implementation"] = _identity("implementation", implementation)
    ids.update({k: _identity(k, v) for k, v in over.items()})
    doc = {"schema": C.CONTRACT_SCHEMA, "run_label": run_label,
           "identities": ids}
    doc["contract_digest"] = C.contract_digest_of(doc)
    return doc


def _write(path: Path, doc) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return path


def _arm(root: Path, name, implementation="e" * 8, filename="contract.json",
         **over):
    return _write(root / name / filename,
                  _contract(name, implementation, **over))


def _corpus_rc(root: Path) -> int:
    return PI.main(["--corpus", str(root)])


def _pairs_compared(root: Path, capsys) -> int:
    """The pair count the gate PRINTS, read back from its own roll-up."""
    PI.main(["--corpus", str(root)])
    out = capsys.readouterr()
    for line in (out.out + out.err).splitlines():
        if "pair(s) compared" in line:
            return int(line.split("pair(s) compared")[0].strip().split()[-1])
    raise AssertionError(f"no roll-up line in:\n{out.out}{out.err}")


# ---------------------------------------------------------------------------
# THE POSITIVE CONTROL. Everything below is a refusal test, and a file of
# refusal tests alone is satisfied by a gate that refuses unconditionally.
# ---------------------------------------------------------------------------
def test_a_comparable_pair_passes(tmp_path):
    """Two runs agreeing on problem, analysis and toolchain and differing on
    implementation ARE comparable, and the gate must say so."""
    _arm(tmp_path, "b", "e" * 8)
    _arm(tmp_path, "t1", "f" * 8)
    assert _corpus_rc(tmp_path) == 0


def test_a_contract_is_never_paired_with_itself(tmp_path):
    """A contract compared against itself matches on every identity by
    construction. Counting that as a passing pair would be the gate writing its
    own evidence, and it would make a corpus of ONE document look checked.

    Self-exclusion moved out of a helper and into the group pairing, so it is
    asserted where it now lives: one arm makes ZERO pairs and cannot be rc 0.
    """
    _arm(tmp_path, "b")
    assert _corpus_rc(tmp_path) == 2


def test_the_pair_count_is_every_pair_and_no_self_pair(tmp_path, capsys):
    """N arms make exactly C(N,2) pairs. N would mean a self-pair; N*N would
    mean each pair counted twice and one arm compared to itself."""
    for i in range(3):
        _arm(tmp_path, f"x{i}", chr(97 + i) * 8)
    assert _pairs_compared(tmp_path, capsys) == 3            # C(3,2)
    assert _corpus_rc(tmp_path) == 0


def test_the_corpus_is_identified_by_declaration_not_by_filename(tmp_path):
    """A contract filed under another name is IN the population; a document
    that is not a contract is not, whatever it is called."""
    _arm(tmp_path, "b", "e" * 8)
    _arm(tmp_path, "t1", "f" * 8, filename="not_called_contract.json")
    _write(tmp_path / "t2" / "contract.json", {"schema": "vibeic.ppa.metric.v1"})
    assert _corpus_rc(tmp_path) == 0        # the oddly-named one WAS paired


def test_an_unreadable_document_is_two_and_never_a_pass(tmp_path):
    """UNREADABLE IS NOT ABSENT. A document that was named a contract and could
    not be opened must hold the verdict down; dropping it would let a corpus
    improve by becoming unreadable."""
    _arm(tmp_path, "b", "e" * 8)
    _arm(tmp_path, "t1", "f" * 8)
    (tmp_path / "t2").mkdir()
    (tmp_path / "t2" / "contract.json").write_text('{"schema": "vibeic',
                                                   encoding="utf-8")
    assert _corpus_rc(tmp_path) == 2


def test_absent_corpus_is_two_and_never_zero(tmp_path):
    assert PI.main(["--corpus", str(tmp_path / "nope")]) == 2


def test_a_corpus_holding_one_contract_is_two_and_never_zero(tmp_path):
    """VACUOUS. Nothing was compared, and 'no pair to make' must not print the
    same verdict as 'every pair held'."""
    _arm(tmp_path, "b")
    assert _corpus_rc(tmp_path) == 2


def test_a_disagreeing_pair_is_a_finding(tmp_path):
    """The other half of the positive control: the gate must be able to REFUSE
    a pair as well as accept one."""
    _arm(tmp_path, "b", "e" * 8)
    _arm(tmp_path, "t1", "f" * 8, toolchain="u" * 8)
    assert _corpus_rc(tmp_path) == 1


def test_a_refusal_is_not_softened_by_an_undetermined_beside_it(tmp_path):
    """THE DEFEAT-THE-GATE SHAPE. Under `max()`, [1, 2] rolls up to 2 and adding
    an unreadable contract would SUBTRACT a refusal from the corpus verdict."""
    _arm(tmp_path, "b", "e" * 8)
    _arm(tmp_path, "t1", "f" * 8, toolchain="u" * 8)
    assert _corpus_rc(tmp_path) == 1, "a pair that disagrees is rc 1"
    (tmp_path / "t2").mkdir()
    (tmp_path / "t2" / "contract.json").write_text("{oops", encoding="utf-8")
    assert _corpus_rc(tmp_path) == 1, (
        "an unreadable contract beside a refused pair does not soften it")


def test_needs_exactly_one_of_candidate_or_corpus(tmp_path):
    """3 and not 2: the caller named both a single document and a population,
    and running either silently would report a verdict about something they did
    not ask about. THIS IS THE ROW THE WIRING GOT WRONG -- both `PPA arms solved
    one problem` rows passed `--baseline` beside `--corpus` and exited 3,
    examining no pair in either campaign."""
    base = _write(tmp_path / "b" / "contract.json", _contract("b"))
    assert PI.main(["--baseline", str(base), "--candidate", "a",
                    "--corpus", "b"]) == 3
    assert PI.main(["--baseline", str(base)]) == 3


def test_an_internal_error_is_never_rc_1(tmp_path):
    """§1: 1 is reserved for a finding about the design.

    REACHED THROUGH THE CORPUS, which is the only way it matters. Both arms
    GROUP on a well-formed `problem` identity -- so the pairing runs -- and
    their `analysis` is a bare digest STRING instead of a record, which raises
    out of `identity.compare`. With no guard the traceback exits 1 and the
    roll-up reads it as "these two runs were not solving the same problem".

    MEASURED RED against the program as it stood: rc=1 with the traceback on
    stderr. The guard `ppa-gate-audit/RESULT.md` Part 7 said this program
    carried was not in it, and this test -- which would have caught that -- had
    been failing on an unrelated AttributeError the whole time.

    2 and not 3: the INVOCATION was correct. One badly shaped pair must not
    decide a row about the other twenty.
    """
    for name, impl in (("b", "e" * 8), ("t1", "f" * 8)):
        doc = _contract(name, impl)
        doc["identities"]["analysis"] = "sha256:" + "c" * 8   # a STRING
        doc["contract_digest"] = C.contract_digest_of(doc)
        _write(tmp_path / name / "contract.json", doc)
    out = _pr.run(
        [sys.executable, str(PROGRAMS / "ppa_problem_integrity_check.py"),
         "--corpus", str(tmp_path)],
        capture_output=True, text=True)
    assert "Traceback (most recent call last)" not in out.stderr, (
        f"a traceback escaped; §1 reserves 1 for a finding and a crash must "
        f"never publish itself as one\n{out.stderr[-700:]}")
    assert out.returncode == 2, (
        f"rc={out.returncode}; an internal error must never wear the exit code "
        f"reserved for a finding\n{out.stderr[-600:]}")
    assert "CANNOT CHECK" in out.stderr
    assert "NOT a finding" in out.stderr
    assert "contract.v1.schema.json" in out.stderr, (
        "the refusal does not name the missing input, so a reader is told a "
        "comparison failed and not what to go and fix")
