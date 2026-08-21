"""vibe-ic#1116 — an artefact whose provenance can be CHECKED, not assumed.

#1116 ran four tampering methods against LibreLane 3.0.8 and ORFS; all four
succeeded. The narrower question that decides what we build is whether OUR
`provenance.jsonl` is better. Measured, it is better against one attacker and
not the other:

    honest artefact                  -> audit PASS
    edit the ARTEFACT only           -> audit FAIL   (caught)
    edit the artefact AND the record -> audit PASS   (NOT caught)

`provenance_logger.py`'s docstring claims the second needs a hash collision. It
does not: an adversary that writes the artefact FIRST and then records ITS hash
controls both sides, and `provenance.jsonl` lives inside the run directory the
step writes. That is #1116 requirement 3.

WHAT THESE TESTS PIN
====================
The three tiers, and — the deliverable #1116 names — that the COORDINATED edit
is refused. `test_the_coordinated_edit_is_internally_consistent` asserts the
attack really is invisible to a self-consistency check, so the anchored test
below it cannot pass for the wrong reason.

They also pin the HONEST LIMIT: with the anchor inside the run directory the
guarantee degrades to the pre-#1116 one, and the tool must SAY so. A security
claim whose boundary is not stated is the shape this repo removes.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
sys.path.insert(0, str(_PROGRAMS))

import artefact_digest_ledger as L  # noqa: E402

GATE = _PROGRAMS / "artefact_digest_ledger.py"
HONEST = "DESIGN honest ;\nVIOLATIONS 42 ;\n"
FORGED = "DESIGN tampered ;\nVIOLATIONS 0 ;\n"


def _run(*args):
    p = subprocess.run([sys.executable, str(GATE), *map(str, args)],
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


@pytest.fixture
def lab(tmp_path):
    """A recorded run: one artefact, digest appended, head anchored OUTSIDE."""
    run = tmp_path / "run"
    run.mkdir()
    anchor = tmp_path / "anchor.json"          # deliberately outside `run`
    (run / "routed.def").write_text(HONEST)
    rc, out = _run("append", run, "--step", "Magic.DRC",
                   "--output", "routed.def", "--anchor", anchor)
    assert rc == L.RC_PASS, out
    return run, anchor


def _coordinated_edit(run: Path) -> str:
    """Rewrite the artefact AND every digest/chain value. No collision needed."""
    ledger = run / L.LEDGER_NAME
    entries = L.read_ledger(ledger)
    (run / "routed.def").write_text(FORGED)
    head = hashlib.sha256(L.GENESIS.encode()).hexdigest()
    rebuilt = []
    for e in entries:
        e = dict(e)
        e["digest"] = L.sha256_file(run / e["path"])
        head = L.chain_next(head, e)
        e["chain"] = head
        rebuilt.append(e)
    ledger.write_text("".join(json.dumps(e, separators=(",", ":")) + "\n"
                              for e in rebuilt), encoding="utf-8")
    return head


# ── the three tiers ─────────────────────────────────────────────────────────

def test_an_honest_run_passes(lab):
    run, anchor = lab
    rc, out = _run("verify", run, "--anchor", anchor)
    assert rc == L.RC_PASS, out


def test_editing_only_the_artefact_is_refused(lab):
    """#1116 method (B): rewrite the artefact's CONTENT."""
    run, anchor = lab
    (run / "routed.def").write_text(FORGED)
    rc, out = _run("verify", run, "--anchor", anchor)
    assert rc == L.RC_FAIL, out
    assert "CONTENT CHANGED" in out, out


def test_a_missing_artefact_is_refused(lab):
    run, anchor = lab
    (run / "routed.def").unlink()
    rc, out = _run("verify", run, "--anchor", anchor)
    assert rc == L.RC_FAIL, out
    assert "GONE" in out, out


# ── the deliverable: the attack the existing machinery does not catch ───────

def test_the_coordinated_edit_is_internally_consistent(lab):
    """The attack must be INVISIBLE to a self-consistency check.

    Without this, the anchored test below could pass because the attack was
    clumsy rather than because the anchor caught it.
    """
    run, _anchor = lab
    _coordinated_edit(run)
    entries = L.read_ledger(run / L.LEDGER_NAME)
    assert all(e["digest"] == L.sha256_file(run / e["path"]) for e in entries), (
        "the forged ledger does not even agree with its own files")
    assert L.derive_head(entries) == entries[-1]["chain"], (
        "the forged chain does not re-derive — the attack is detectable "
        "without the anchor, so the next test proves nothing")


def test_the_coordinated_edit_is_refused_by_the_anchor(lab):
    """#1116's red arm: artefact AND record rewritten together, still refused."""
    run, anchor = lab
    forged_head = _coordinated_edit(run)
    rc, out = _run("verify", run, "--anchor", anchor)
    assert rc == L.RC_FAIL, out
    assert "ANCHOR MISMATCH" in out, out
    assert forged_head[:16] in out, out


def test_deleting_an_entry_is_refused(lab):
    """Truncating the ledger changes the head just as rewriting it does."""
    run, anchor = lab
    (run / "routed.def").write_text(FORGED)
    (run / L.LEDGER_NAME).write_text("")
    rc, out = _run("verify", run, "--anchor", anchor)
    assert rc == L.RC_VACUOUS, out
    assert "nothing was recorded" in out, out


# ── the honest limit, stated rather than hidden ─────────────────────────────

def test_an_anchor_inside_the_run_dir_is_disclosed(tmp_path):
    """If the anchor is in reach, the guarantee degrades and it must SAY so."""
    run = tmp_path / "run"
    run.mkdir()
    inside = run / "anchor.json"
    (run / "routed.def").write_text(HONEST)
    _run("append", run, "--step", "S", "--output", "routed.def", "--anchor", inside)
    rc, out = _run("verify", run, "--anchor", inside)
    assert rc == L.RC_PASS, out
    assert "INSIDE the run directory" in out, (
        f"the degraded trust boundary was not disclosed:\n{out}")


def test_a_missing_anchor_is_a_finding_not_a_pass(lab):
    run, anchor = lab
    anchor.unlink()
    rc, out = _run("verify", run, "--anchor", anchor)
    assert rc == L.RC_FAIL, out
    assert "unattested" in out, out


def test_no_ledger_is_vacuous_not_a_pass(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    rc, out = _run("verify", run, "--anchor", tmp_path / "a.json")
    assert rc == L.RC_VACUOUS, out
    assert "NOT a pass" in out, out


# ── paired guard: a mutant that always answers must kill a test ─────────────

def test_a_verifier_that_always_passes_is_killed(lab, monkeypatch):
    """If `verify` were replaced by one that always says PASS, the tier tests
    above must die. Asserted here so this file cannot degrade into a ban."""
    run, anchor = lab
    (run / "routed.def").write_text(FORGED)
    real = L.verify(run, anchor)
    assert real["verdict"] == "FAIL", real

    monkeypatch.setattr(L, "verify",
                        lambda *_a, **_k: {"verdict": "PASS", "findings": [],
                                           "entries": 1,
                                           "anchor_inside_run_dir": False})
    always = L.verify(run, anchor)
    assert always["verdict"] == "PASS"
    assert always["verdict"] != real["verdict"], (
        "an always-PASS mutant is indistinguishable from the real verifier, so "
        "these tests would not notice the check being removed")
