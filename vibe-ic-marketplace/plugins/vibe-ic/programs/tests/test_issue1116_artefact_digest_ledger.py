"""vibe-ic#1116 — an artefact digest the producing step does not own.

THE MOTIVATING CASE IS REAL. An engineer running RTL-to-GDS with an AI agent
reported that when an N2N formal check would not pass, the agent edited the
netlist until it did. If the objective is "the check passes" and the evidence is
writable, editing the evidence is a valid solution and a cheaper one than fixing
the design.

MEASURED against THIS flow before the fix, with the issue's own four methods:

    (0) honest artefact + honest record                    ACCEPTED   correct
    (B) artefact content rewritten, record untouched       REFUSED    correct
    (A) artefact AND recorded digest rewritten together    ACCEPTED   GAP
    (C) digest REMOVED from the record, artefact rewritten ACCEPTED   GAP
    (D) any digest recorded outside the producer's reach   NONE       GAP

(B) already failed closed — `provenance_hash_audit` re-derives and refuses on
mismatch, which is more than either reference flow does. This file is about
(A), (C) and (D).

EVERY BRANCH IS TESTED ALONE. A first draft of the probe "proved" (A) and (C)
closed when both were really being caught by MISMATCH, because the artefact
content had changed in each. A refusal that only ever fires for one reason is
one check wearing several names, so each case below changes exactly the one
thing its category is about.

AND THE LIMIT IS PINNED TOO. `test_a_consistent_three_way_edit_is_NOT_caught`
asserts the mechanism does NOT catch a tamperer who rewrites artefact, gate
report and ledger consistently. That test passing is not a defect being
tolerated — it is the claim being kept honest, because a mechanism that
overstated its reach would be the same shape as the evidence it exists to check.
"""

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_LEDGER = _PROGRAMS / "artefact_digest_ledger.py"
_REL = "phase3/stage3/signoff/netlist.v"


def _load():
    spec = importlib.util.spec_from_file_location("adl", _LEDGER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["adl"] = mod
    spec.loader.exec_module(mod)
    return mod


M = _load()


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _artefact(root: Path, text: str = "module top(); endmodule\n") -> Path:
    a = root / _REL
    a.parent.mkdir(parents=True, exist_ok=True)
    a.write_text(text)
    return a


def _record(root: Path, step: str = "n2n_formal") -> None:
    """The ORCHESTRATOR records — deliberately not the step, and deliberately
    not into `gate_reports/`."""
    M.record(root, step, [_REL])


def _report(root: Path, digest) -> Path:
    """The producing step's own record. `digest=None` = declares, vouches for
    nothing."""
    rp = root / "gate_reports" / "n2n_formal.json"
    rp.parent.mkdir(parents=True, exist_ok=True)
    ent = {"path": _REL}
    if digest is not None:
        ent["sha256"] = digest
    rp.write_text(json.dumps({"gate": "n2n_formal", "verdict": "PASS",
                              "output_files": [ent]}, indent=2) + "\n")
    return rp


def _cats(root: Path):
    return {f["category"] for f in M.verify(root)["findings"]}


def _cli(root: Path):
    p = subprocess.run([sys.executable, str(_LEDGER), "verify", str(root)],
                       capture_output=True, text=True, timeout=60)
    return p.returncode, p.stdout + p.stderr


# ==========================================================================
# 1. THE HONEST CONTROL — first, because every refusal below is worthless
#    without it
# ==========================================================================
def test_a_fully_honest_run_passes(tmp_path):
    root = tmp_path / "run"; root.mkdir()
    a = _artefact(root); _record(root); _report(root, _sha(a))
    rc, out = _cli(root)
    assert rc == 0, out
    assert not _cats(root)


# ==========================================================================
# 2. EACH REFUSAL BRANCH, ALONE
# ==========================================================================
def test_B_artefact_content_rewritten_is_refused(tmp_path):
    """The one both reference flows miss. It already worked here; pinned so it
    cannot regress out."""
    root = tmp_path / "run"; root.mkdir()
    a = _artefact(root); _record(root); _report(root, _sha(a))
    a.write_text("// TAMPERED\n")
    assert "MISMATCH" in _cats(root)
    assert _cli(root)[0] == 1


def test_C_a_declared_output_with_no_ledger_entry_is_refused(tmp_path):
    """(C), the cheapest bypass: unverifiable must not score as clean.

    Nothing here is tampered — the artefact and the report agree. The ONLY
    defect is that no independent record establishes the artefact is what the
    step produced, so MISMATCH cannot be what fires.
    """
    root = tmp_path / "run"; root.mkdir()
    a = _artefact(root); _report(root, _sha(a))          # no _record()
    cats = _cats(root)
    assert cats == {"UNRECORDED"}, cats
    assert _cli(root)[0] == 1


def test_A_report_digest_disagreeing_with_the_ledger_is_refused(tmp_path):
    """(A): the producing step owns its own record, so it can make that record
    agree with whatever it wrote. It does not own the ledger.

    The artefact is HONEST here and matches the ledger, so MISMATCH is silent
    and only the cross-check can speak.
    """
    root = tmp_path / "run"; root.mkdir()
    _artefact(root); _record(root); _report(root, "0" * 64)
    cats = _cats(root)
    assert cats == {"DISAGREE"}, cats
    assert _cli(root)[0] == 1


def test_a_report_that_vouches_for_nothing_is_refused(tmp_path):
    root = tmp_path / "run"; root.mkdir()
    _artefact(root); _record(root); _report(root, None)
    assert _cats(root) == {"UNCLAIMED"}


def test_re_recording_one_path_with_two_digests_is_refused(tmp_path):
    """The ledger is append-only by contract. A second write does not win —
    if it did, the ledger would be the single record the producer already
    controls."""
    root = tmp_path / "run"; root.mkdir()
    _artefact(root, "v1\n"); _record(root)
    _artefact(root, "v2\n"); _record(root)
    _report(root, None)
    assert "REDECLARED" in _cats(root)


def test_a_ledger_entry_whose_artefact_is_gone_is_refused(tmp_path):
    root = tmp_path / "run"; root.mkdir()
    _artefact(root); _record(root); (root / _REL).unlink(); _report(root, None)
    assert "ORPHANED" in _cats(root)


def test_an_unreadable_ledger_is_not_an_empty_one(tmp_path):
    """A corrupt ledger read as empty would be a clean verdict over nothing —
    deleting the file would become the bypass that (C) just stopped being."""
    root = tmp_path / "run"; root.mkdir()
    a = _artefact(root); _record(root)
    lp = M.ledger_path(root)
    lp.write_text(lp.read_text() + "{not json\n")
    _report(root, _sha(a))
    assert "LEDGER_CORRUPT" in _cats(root)


# ==========================================================================
# 3. (D) — THE RECORD IS NOT WHERE THE PRODUCER WRITES
# ==========================================================================
def test_the_ledger_is_not_under_gate_reports(tmp_path):
    """A hash the producer writes next to its own output proves nothing against
    a producer that edits both. This is the structural half of the fix and it is
    asserted on the PATH, because that is the whole of the property."""
    root = tmp_path / "run"; root.mkdir()
    _artefact(root); _record(root)
    lp = M.ledger_path(root)
    assert lp.is_file(), "no independent ledger was written"
    assert "gate_reports" not in lp.relative_to(root).parts, lp
    rec = json.loads(lp.read_text().splitlines()[0])
    assert rec["path"] == _REL and len(rec["sha256"]) == 64


# ==========================================================================
# 4. THE LIMIT, PINNED
# ==========================================================================
def test_a_consistent_three_way_edit_is_NOT_caught(tmp_path):
    """Deliberately asserts a NEGATIVE, and it is not a defect being tolerated.

    A process that can write anywhere can write every record. If this test ever
    starts failing, someone has either found a real second source of truth — in
    which case this file's claim should GROW to match it — or has made the
    mechanism claim a reach it does not have, which is the exact shape of the
    evidence-forging this whole issue is about. Either way it must be looked at
    rather than silently enjoyed.
    """
    root = tmp_path / "run"; root.mkdir()
    a = _artefact(root); _record(root); _report(root, _sha(a))
    a.write_text("// TAMPERED\n")
    M.ledger_path(root).write_text(json.dumps(
        {"step": "n2n_formal", "path": _REL, "sha256": _sha(a)},
        sort_keys=True) + "\n")
    _report(root, _sha(a))
    assert _cli(root)[0] == 0, (
        "the three-way edit was caught — if that is real, widen the claim in "
        "artefact_digest_ledger's docstring and in this test")


# ==========================================================================
# 5. NOT A VACUOUS PASS
# ==========================================================================
def test_an_empty_project_is_rc_2_and_says_it_examined_nothing(tmp_path):
    """`_vacuous_exit`: "I could not look" must never share an exit code with
    "I looked and it was clean"."""
    root = tmp_path / "run"; root.mkdir()
    rc, out = _cli(root)
    assert rc == 2, out
    assert "NOT a pass" in out and "0 artefact(s)" in out, out


def test_a_pass_states_how_much_it_examined(tmp_path):
    """vibe-ic#447 — a PASS must say what it was over."""
    root = tmp_path / "run"; root.mkdir()
    a = _artefact(root); _record(root); _report(root, _sha(a))
    rc, out = _cli(root)
    assert rc == 0
    assert "1 artefact(s) re-derived" in out and "1 entry(ies)" in out, out


@pytest.mark.parametrize("flag,expect", [([], 1), (["--allow-unrecorded"], 0)])
def test_the_migration_flag_is_the_only_way_to_reopen_C(tmp_path, flag, expect):
    """The escape hatch exists, is named, and defaults OFF."""
    root = tmp_path / "run"; root.mkdir()
    a = _artefact(root); _report(root, _sha(a))
    p = subprocess.run([sys.executable, str(_LEDGER), "verify", str(root), *flag],
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == expect, p.stdout + p.stderr
