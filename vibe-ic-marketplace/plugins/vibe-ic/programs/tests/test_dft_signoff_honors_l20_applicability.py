"""The DFT sign-off gate and the ATPG coverage gate must AGREE on one tree.

Both gates key on the design's OWN L20 applicability. `dft_atpg_coverage_check`
downgrades a below-floor stuck-at FAIL to INFORMATIONAL when L20 declares no DFT
(pinned in test_issue603_gate_l20_applicability). `dft_signoff_check` DELEGATES
its stuck-at dimension to that same gate — it re-derives nothing — but it used to
accept only a literal ``"PASS"``, so it read the coverage gate's own
INFORMATIONAL disposition as a failure. The two gates then reached OPPOSITE
verdicts about one tree: coverage gate INFORMATIONAL (rc 0), sign-off FAIL (rc 1).

The invariant these tests establish (stronger than the one-line fix): a coverage
gate stuck-at verdict is classified blocking / non-blocking in exactly ONE place —
``dft_atpg_coverage_check.stuck_at_signoff_passes`` / ``NON_BLOCKING_STUCK_AT_-
VERDICTS`` — consulted by BOTH the coverage gate's own rc mapping AND the sign-off
aggregate. So the two cannot drift into disagreeing about the same recorded
verdict; a change that reintroduces the drift fails a test here.

Direction is preserved — INFORMATIONAL is NOT a blanket pass:
  * L20 DECLARES DFT + below floor     -> FAIL in BOTH gates (floor governs)
  * L20 declares NO DFT + below floor  -> INFORMATIONAL, non-blocking in BOTH
  * L20 DECLARES DFT + meets floor     -> PASS in BOTH

Fixtures are synthesized neutral data (invented design ``quill_ecc_engine``,
invented coverage numbers); no design / PDK / vendor literal appears.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _PROGRAMS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# Order matters: the sign-off gate imports the coverage gate as ``_sa``. Loading
# the coverage gate first registers it in sys.modules so the sign-off gate binds
# to THIS object — the same ``stuck_at_signoff_passes`` both sides must share.
SA = _load("dft_atpg_coverage_check")
SIGN = _load("dft_signoff_check")


def _tree(tmp_path, *, l20_asserts_dft, stuck_pct):
    """A synthetic project where stuck-at is the SOLE blocking dimension.

    transition PASSes (96% >= 90% target) and bsdl is a bare core (N/A -> SKIP),
    so the aggregate sign-off verdict turns only on how the stuck-at disposition
    is classified. ``l20_asserts_dft`` toggles whether the design's own L20
    declares a DFT topology; ``stuck_pct`` is the measured stuck-at coverage.
    """
    dft = tmp_path / "reports" / "phase2" / "dft"
    dft.mkdir(parents=True)
    (dft / "coverage.json").write_text(json.dumps({
        "tool": "fault",
        "stuck_at_coverage_percent": stuck_pct,
        "stuck_at_target": 50.0,          # lenient written target; floor clamps to 95
        "faults_total": 4096,
        "transition": {"coverage_pct": 96.0, "target_pct": 90.0},
    }))
    # bare core -> boundary scan N/A -> SKIP (a non-blocking honest N/A).
    (dft / "bsdl_plan.json").write_text(json.dumps(
        {"verdict": "N_A", "padded": False}))

    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    if l20_asserts_dft:
        fields = {"dft_present": True,
                  "scan_chains": [{"name": "sc0", "length": 40, "scan_in": "si",
                                   "scan_out": "so", "clock": "clk"}]}
        applic = "APPLICABLE"
    else:
        fields = {"dft_present": False, "scan_chains": [], "jtag_tap": None,
                  "test_compression": None, "bist_mbist": []}
        # DECLARES no DFT, and now says so the only way a layer can: an
        # explicit NOT_APPLICABLE. This fixture used to express "declares no
        # DFT" as APPLICABLE + NOT_YET_EXTRACTED + all-default fields — i.e.
        # the emitter's untouched SKELETON, which declares nothing at all. The
        # gate used to read that skeleton as a declaration, and that conflation
        # is the defect fixed in `l20_dft_applicability` (see
        # test_dft_floor_unextracted_l20_is_unknown.py). Switching the fixture
        # to a real declaration keeps EVERY invariant this file exists to pin —
        # the two gates still see one INFORMATIONAL tree and must still agree —
        # while making the docstring's "declares no DFT" literally true.
        applic = "NOT_APPLICABLE"
    (gd / "L20_DFT_SCAN_TOPOLOGY.json").write_text(json.dumps({
        "doc_id": "L20", "applicability": applic, "fields": fields,
        "extraction_status": "NOT_YET_EXTRACTED", "extraction_evidence": {},
    }))
    return tmp_path


# ── the reproduction: same tree, the two gates must AGREE ────────────────────

def test_no_dft_informational_agrees_across_both_gates(tmp_path):
    """The measured pre-fix disagreement, now an equality. A design whose own
    L20 declares no DFT, sitting below the floor: the coverage gate reports
    INFORMATIONAL (non-blocking) and the sign-off aggregate must not FAIL on a
    disposition the coverage gate has already, deliberately, blessed."""
    proj = _tree(tmp_path, l20_asserts_dft=False, stuck_pct=42.7)

    cov = SA.audit(proj)
    assert cov["verdict"] == "INFORMATIONAL"
    assert cov["floor_enforced"] is False

    sign = SIGN.audit(proj)
    # DELEGATION, not re-derivation: the sign-off gate sees the SAME disposition.
    assert sign["stuck_at"]["status"] == "INFORMATIONAL"
    assert sign["transition"]["status"] == "PASS"
    assert sign["bsdl"]["status"] == "SKIP"
    assert sign["verdict"] == "PASS"          # RED pre-fix (was FAIL)


def test_cli_rc_agree_on_informational_tree(tmp_path):
    """End-to-end at the exit-code level: both gates return the SAME rc."""
    proj = _tree(tmp_path, l20_asserts_dft=False, stuck_pct=42.7)
    assert SA.main([str(proj)]) == 0
    assert SIGN.main([str(proj)]) == 0        # RED pre-fix (was 1)


# ── direction control: INFORMATIONAL is NOT a blanket pass ───────────────────

def test_dft_declaring_below_floor_fails_both_gates(tmp_path):
    """The load-bearing control. A design that DECLARES DFT and sits below the
    floor is held to the floor by BOTH gates — the fix never relaxes this."""
    proj = _tree(tmp_path, l20_asserts_dft=True, stuck_pct=42.7)

    cov = SA.audit(proj)
    assert cov["verdict"] == "FAIL"
    assert cov["floor_enforced"] is True

    sign = SIGN.audit(proj)
    assert sign["stuck_at"]["status"] == "FAIL"
    assert sign["verdict"] == "FAIL"

    assert SA.main([str(proj)]) == 1
    assert SIGN.main([str(proj)]) == 1


def test_dft_declaring_meets_floor_passes_both_gates(tmp_path):
    proj = _tree(tmp_path, l20_asserts_dft=True, stuck_pct=97.5)
    assert SA.audit(proj)["verdict"] == "PASS"
    assert SIGN.audit(proj)["verdict"] == "PASS"


# ── the anti-drift invariant, over the full stuck-at verdict vocabulary ──────

@pytest.mark.parametrize("asserts_dft, stuck_pct, expected_cov_verdict", [
    (True, 97.5, "PASS"),
    (True, 42.7, "FAIL"),
    (False, 42.7, "INFORMATIONAL"),
])
def test_signoff_matches_coverage_gate_nonblocking_classification(
        tmp_path, asserts_dft, stuck_pct, expected_cov_verdict):
    """For EVERY stuck-at verdict the coverage gate can emit, the sign-off
    aggregate PASSes on the stuck-at dimension IFF the SHARED predicate calls it
    non-blocking. The two gates read the same predicate, so they cannot classify
    the same verdict differently."""
    proj = _tree(tmp_path, l20_asserts_dft=asserts_dft, stuck_pct=stuck_pct)

    cov_verdict = SA.audit(proj)["verdict"]
    assert cov_verdict == expected_cov_verdict

    signoff = SIGN.audit(proj)
    assert signoff["stuck_at"]["status"] == cov_verdict      # delegation
    assert (signoff["verdict"] == "PASS") == SA.stuck_at_signoff_passes(cov_verdict)


# ── the shared predicate itself ──────────────────────────────────────────────

def test_shared_predicate_classifies_the_verdict_vocabulary():
    assert SA.stuck_at_signoff_passes("PASS") is True
    assert SA.stuck_at_signoff_passes("INFORMATIONAL") is True
    assert SA.stuck_at_signoff_passes("informational") is True   # case-insensitive
    assert SA.stuck_at_signoff_passes("FAIL") is False
    # audit() never emits SKIPPED-CONDITION (main() handles disclosed-skip before
    # audit is reached); it must NOT vacuously pass through this predicate.
    assert SA.stuck_at_signoff_passes("SKIPPED-CONDITION") is False
    assert SA.stuck_at_signoff_passes(None) is False


def test_nonblocking_vocabulary_is_pinned_tripwire():
    """TRIPWIRE. Widening the set of non-blocking stuck-at dispositions MUST be
    accompanied by a new same-tree cross-gate agreement case above proving BOTH
    gates honor the new disposition — otherwise the two can silently disagree
    again. This pin makes that edit conscious."""
    assert SA.NON_BLOCKING_STUCK_AT_VERDICTS == frozenset({"PASS", "INFORMATIONAL"})


# ── degrade loudly: the aggregate discloses WHY it accepted stuck-at ─────────

def test_signoff_record_discloses_l20_basis_loudly(tmp_path):
    """The aggregate must not accept a non-PASS stuck-at silently. The L20
    applicability that drove the non-blocking acceptance is carried in the
    record, so a reader can see the floor was reported, not enforced."""
    proj = _tree(tmp_path, l20_asserts_dft=False, stuck_pct=42.7)
    sa = SIGN.audit(proj)["stuck_at"]
    assert sa["status"] == "INFORMATIONAL"
    assert sa["floor_enforced"] is False
    assert sa["l20_applicability"]["asserts_dft"] is False
    # The record must NAME the L20 basis it accepted on. The literal wording
    # follows the declaration channel — this tree now declares via
    # `applicability: NOT_APPLICABLE` (see `_tree`) — so assert the substance:
    # the reasons say L20, say the floor was reported not enforced, and carry
    # the measured number that was let through.
    joined = " ".join(sa["reasons"])
    assert "L20" in joined, joined
    assert "not gated" in joined or "INFORMATIONAL" in joined, joined
    assert "42.7" in joined, joined
