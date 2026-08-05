"""An UN-EXTRACTED L20 is UNKNOWN, not a declaration that no DFT is required.

`dft_atpg_coverage_check` may downgrade a below-floor stuck-at coverage FAIL to
INFORMATIONAL when the design's own L20 declares it needs no DFT. The predicate
that decided this read a THREE-valued producer state as two:

    NOT-RUN          the emitter's untouched skeleton
    RAN-AND-EMPTY    extraction ran and recorded no DFT
    RAN-AND-FOUND    extraction ran and recorded a topology

Only RAN-AND-EMPTY is a design saying "I need no DFT". Reading NOT-RUN the same
way turns the ABSENCE of a stated requirement into a DECLARATION that the
requirement is absent, and switches off a foundry sign-off floor on that basis.
`l_doc_consumer_contract.is_extraction_claimed` names this exact trap in its own
docstring.

THE INVARIANT, and why it is the right one to pin
-------------------------------------------------
`l20_dft_applicability` already fails safe for its other two uninformative
states — its docstring says "When L20 is absent or unparseable the floor
stands". An un-extracted skeleton carries no more information than an absent
file, so it must not buy a LOOSER verdict than deleting the file would.

Before the fix the gate was NON-MONOTONIC IN EVIDENCE: with the same measured
coverage, `rm generated_docs/L20_*.json` produced FAIL while leaving the empty
skeleton in place produced INFORMATIONAL (rc 0). Supplying strictly less
evidence made the gate STRICTER. `test_monotonic_*` pins that directly, and is
the test that fixes the DIRECTION of the repair: a fix that argued the opposite
way cannot satisfy it.

REVERSE CASES (must pass on BOTH trees)
---------------------------------------
The cheap way to make the forward case green is "always enforce the floor",
which would punish every design that legitimately has no DFT and would swallow
the real behaviour underneath. `test_reverse_not_applicable_*` is the case that
forbids it: the one remaining explicit, human-authored declaration must still
disable the floor. The other reverse cases pin that a declared DFT topology, a
comfortably-passing measurement, and an absent L20 all behave exactly as before.

chip-AGNOSTIC: fixtures are synthetic; no design, PDK, vendor or part appears.
"""
import json
import subprocess
import sys
from pathlib import Path

PROG_DIR = Path(__file__).parent.parent
SCRIPT = PROG_DIR / "dft_atpg_coverage_check.py"
assert SCRIPT.exists()

sys.path.insert(0, str(PROG_DIR))
import dft_atpg_coverage_check as chk  # noqa: E402


FLOOR = 95.0
BELOW_FLOOR_PCT = 24.45      # a real sub-floor measurement shape
ABOVE_FLOOR_PCT = 99.10


# ── fixtures ───────────────────────────────────────────────────────────

def _write_cov(project: Path, pct: float) -> Path:
    d = project / "reports" / "phase2" / "dft"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "coverage.json"
    p.write_text(json.dumps({
        "tool": "fault",
        "coverage_pct": pct,
        "faults_total": 3043,
        "faults_covered": int(round(3043 * pct / 100.0)),
        "target_pct": FLOOR,
        "coverage_measured": True,
        "stuck_at_ge_target": pct >= FLOOR,
    }, indent=2))
    return p


def _write_l20(project: Path, doc: dict) -> Path:
    d = project / "phase1" / "generated_docs"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "L20_DFT_SCAN_TOPOLOGY.json"
    p.write_text(json.dumps(doc, indent=2))
    return p


def _skeleton_l20() -> dict:
    """The emitter's untouched skeleton: APPLICABLE, never extracted, every
    field at its default. `dft_present: false` here is a DEFAULT, not a
    decision."""
    return {
        "doc_id": "L20",
        "doc_name": "L20_DFT_SCAN_TOPOLOGY",
        "applicability": "APPLICABLE",
        "fields": {
            "scan_chains": [],
            "test_compression": None,
            "bist_mbist": [],
            "jtag_tap": None,
            "dft_present": False,
            "notes": "Spec does not specify DFT/scan topology.",
        },
        "extraction_status": "NOT_YET_EXTRACTED",
        "extraction_evidence": {},
    }


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(project),
         "--foundry-floor", str(FLOOR)],
        capture_output=True, text=True)


def _report(project: Path):
    r = _run(project)
    return r, json.loads(r.stdout)


# ── FORWARD — fails against the byte-identical pre-fix file ────────────

def test_forward_unextracted_l20_does_not_disable_the_foundry_floor(tmp_path):
    """Sub-floor coverage + an UN-EXTRACTED L20 must FAIL.

    Pre-fix this returns rc 0 / verdict INFORMATIONAL / floor_enforced False,
    so this assertion fails on the VERDICT AND THE EXIT CODE — the substance —
    not on a symbol the fix introduces.
    """
    _write_cov(tmp_path, BELOW_FLOOR_PCT)
    _write_l20(tmp_path, _skeleton_l20())

    r, rep = _report(tmp_path)
    assert rep["verdict"] == "FAIL", rep
    assert rep["floor_enforced"] is True, rep
    assert r.returncode == 1, r.stdout + r.stderr
    # the measurement is still reported — degrade loudly, never silently
    assert abs(rep["measured_coverage_pct"] - BELOW_FLOOR_PCT) < 0.01, rep


def test_forward_reason_names_unknown_not_declared_absent(tmp_path):
    """The disclosure must say UNKNOWN, not 'declares NO DFT requirement'.

    A reader acting on the pre-fix wording would conclude the design had made a
    decision it never made, so the WORDING is part of the defect.
    """
    _write_cov(tmp_path, BELOW_FLOOR_PCT)
    _write_l20(tmp_path, _skeleton_l20())

    _, rep = _report(tmp_path)
    reason = (rep["l20_applicability"]["reason"] or "")
    assert "UNKNOWN" in reason, reason
    assert "declares NO DFT requirement" not in reason, reason
    assert rep["l20_applicability"]["asserts_dft"] is not False, rep


def test_monotonic_unextracted_l20_is_never_looser_than_no_l20(tmp_path):
    """THE DIRECTION-PINNING TEST. Same coverage, two evidence states.

    Deleting the L20 file supplies strictly LESS information. A gate may not
    become more lenient when given less. Pre-fix: no-L20 FAILs while
    skeleton-L20 returns INFORMATIONAL — the gate is non-monotonic and this
    fails. A repair arguing the opposite direction (loosen the no-L20 case)
    would also fail, because both sides are asserted FAIL explicitly.
    """
    no_l20 = tmp_path / "no_l20"
    skel = tmp_path / "skeleton_l20"
    for p in (no_l20, skel):
        p.mkdir()
        _write_cov(p, BELOW_FLOOR_PCT)
    _write_l20(skel, _skeleton_l20())

    r_none, rep_none = _report(no_l20)
    r_skel, rep_skel = _report(skel)

    assert rep_none["verdict"] == "FAIL", rep_none
    assert r_none.returncode == 1
    assert rep_skel["verdict"] == "FAIL", rep_skel
    assert r_skel.returncode == 1
    assert r_skel.returncode >= r_none.returncode


def test_forward_unit_applicability_returns_unknown_for_skeleton(tmp_path):
    """Same claim at the function boundary: NOT-RUN resolves to the
    conservative `asserts_dft=None`, which is the value the caller already
    treats as 'keep the floor'."""
    _write_l20(tmp_path, _skeleton_l20())
    out = chk.l20_dft_applicability(tmp_path)
    assert out["l20_present"] is True, out
    assert out["asserts_dft"] is None, out


# ── REVERSE — must pass on BOTH the pre-fix and post-fix trees ─────────

def test_reverse_not_applicable_l20_still_disables_the_floor(tmp_path):
    """LOAD-BEARING REVERSE CASE.

    `applicability: NOT_APPLICABLE` is an explicit, human-authored declaration
    that this design needs no DFT, and it is the remaining legitimate downgrade
    path. If the fix had degenerated into 'always enforce the floor' — the easy
    way to make the forward cases green — this test would fail. It must pass on
    both trees.
    """
    _write_cov(tmp_path, BELOW_FLOOR_PCT)
    doc = _skeleton_l20()
    doc["applicability"] = "NOT_APPLICABLE"
    _write_l20(tmp_path, doc)

    r, rep = _report(tmp_path)
    assert rep["verdict"] == "INFORMATIONAL", rep
    assert rep["floor_enforced"] is False, rep
    assert r.returncode == 0, r.stdout + r.stderr


def test_reverse_declared_scan_chain_below_floor_still_fails(tmp_path):
    """A design that DECLARES a scan chain keeps the floor. Unchanged."""
    _write_cov(tmp_path, BELOW_FLOOR_PCT)
    doc = _skeleton_l20()
    doc["extraction_status"] = "EXTRACTED"
    doc["fields"]["dft_present"] = True
    doc["fields"]["scan_chains"] = [{"name": "chain0", "length": 60}]
    _write_l20(tmp_path, doc)

    r, rep = _report(tmp_path)
    assert rep["verdict"] == "FAIL", rep
    assert rep["floor_enforced"] is True, rep
    assert r.returncode == 1


def test_reverse_declared_scan_chain_above_floor_still_passes(tmp_path):
    """A good measurement is still a PASS — the fix does not fail everything."""
    _write_cov(tmp_path, ABOVE_FLOOR_PCT)
    doc = _skeleton_l20()
    doc["extraction_status"] = "EXTRACTED"
    doc["fields"]["dft_present"] = True
    doc["fields"]["scan_chains"] = [{"name": "chain0", "length": 60}]
    _write_l20(tmp_path, doc)

    r, rep = _report(tmp_path)
    assert rep["verdict"] == "PASS", rep
    assert r.returncode == 0, r.stdout + r.stderr


def test_reverse_no_l20_at_all_still_keeps_the_floor(tmp_path):
    """The documented anchor — 'when L20 is absent the floor stands'. This is
    the behaviour the un-extracted case is now aligned WITH, so it must not
    itself have moved."""
    _write_cov(tmp_path, BELOW_FLOOR_PCT)

    r, rep = _report(tmp_path)
    assert rep["verdict"] == "FAIL", rep
    assert rep["floor_enforced"] is True, rep
    assert r.returncode == 1
    assert rep["l20_applicability"]["l20_present"] is False, rep


def test_reverse_unextracted_l20_above_floor_still_passes(tmp_path):
    """Enforcing the floor is not the same as failing. An un-extracted L20 with
    a comfortably passing measurement must still PASS — this pins that the fix
    enforces a floor rather than manufacturing a failure."""
    _write_cov(tmp_path, ABOVE_FLOOR_PCT)
    _write_l20(tmp_path, _skeleton_l20())

    r, rep = _report(tmp_path)
    assert rep["verdict"] == "PASS", rep
    assert r.returncode == 0, r.stdout + r.stderr
