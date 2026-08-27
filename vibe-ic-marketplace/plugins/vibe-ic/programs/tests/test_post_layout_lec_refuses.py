"""The post-layout equivalence proof was computed, written down, and ignored.

`phase3_one_shot_runner._emit_lec_post_layout` runs a real Yosys equivalence
between the FINAL routed/repaired netlist and the synth/RTL reference, and returns
the verdict. The call site assigned that return value to a local nothing read.
The ONLY way the step could fail was the emitter RAISING, so the two outcomes
the proof exists to catch — the routed netlist is NOT equivalent, and
equivalence could not be PROVEN — both left the flow at PASS, with the finding
parked in `reports/phase3/lec_post_layout.json` that no runner step consumed.

The reference flow refuses here. OpenROAD-flow-scripts runs `run_lec_test`
after `repair_timing` mutates the netlist inside CTS and the stage dies on a
difference (`flow/scripts/lec_check.tcl`: `error "Repair timing output failed
lec test"`). A logic-changing repair cannot leave the CTS stage there.

MEASURED, with the real tools in the container, on a netlist pair that differs
only in what a post-CTS repair did to it (Liberty + gold + gate all written for
this test; no chip, PDK or vendor literal):

  gold  : AND2 -> DFF
  gate  : the same design after CTS inserted a clock buffer  -> yosys
          PROVEN_EQUIVALENT, total=2 proven=2 unproven=0, gate result PASS
  gate' : the same, plus a repair that swapped that AND2 for an OR2 -> yosys
          UNPROVEN, total=2 proven=1 unproven=1, gate result FAIL

Driving the REAL `step_canonicalize_artefacts` with each artefact:

  pre-fix  clean PASS    mutated PASS   <- the mutation ships
  post-fix clean PASS    mutated FAIL

POSITIVE (must not turn a converged run red):
  - a PROVEN_EQUIVALENT artefact raises no refusal;
  - an ABSENT artefact raises no refusal (not placed-and-routed / honest SKIP);
  - a SKIP artefact raises no refusal.

NEGATIVE no-leak — each must produce a refusal:
  - NON_EQUIVALENT (the routed logic differs);
  - UNPROVEN (the proof did not close) — §4.05: a non-proof is not a pass;
  - VACUOUS (equivalent==true over 0 compared points);
  - RUN_ERROR (yosys produced no parseable verdict);
  - an artefact that is PRESENT but cannot be evaluated — an equivalence proof
    nobody can check is not an equivalence proof.

FRESHNESS: the refusal is evaluated OUTSIDE the `_signoff_regen` guard, so the
SECOND run of a non-equivalent design — which correctly reuses the still-fresh
artefact instead of re-emitting it — refuses too.

chip-AGNOSTIC: verdict vocabulary only; no chip, PDK, library or design literal.
"""
import json
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import phase3_one_shot_runner as R  # noqa: E402

LEC_REL = "reports/phase3/lec_post_layout.json"


def _write(project: Path, doc) -> Path:
    p = project / LEC_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=2) + "\n")
    return p


def _proven(**over):
    doc = {"tool": "yosys-equiv", "top": "top", "skipped": False,
           "verdict": "PROVEN_EQUIVALENT", "equivalent": True,
           "total_points": 2, "proven_points": 2, "unproven_points": 0,
           "non_equivalent_points": 0}
    doc.update(over)
    return doc


# --------------------------------------------------------------- POSITIVE ---

def test_a_real_proof_raises_no_refusal(tmp_path):
    _write(tmp_path, _proven())
    assert R._lec_post_layout_refusal(tmp_path) is None


def test_an_absent_artefact_raises_no_refusal(tmp_path):
    """Not placed-and-routed is an honest not-applicable, never a refusal."""
    assert R._lec_post_layout_refusal(tmp_path) is None


def test_an_honest_skip_raises_no_refusal(tmp_path):
    _write(tmp_path, {"tool": "yosys-equiv", "top": "top", "verdict": "SKIP",
                      "skipped": True,
                      "skip_reason": "no routed/repaired netlist"})
    assert R._lec_post_layout_refusal(tmp_path) is None


# ------------------------------------------------------- NEGATIVE no-leak ---

def test_non_equivalent_routed_logic_refuses(tmp_path):
    """The routed netlist computes something else. A real silicon bug."""
    _write(tmp_path, _proven(verdict="NON_EQUIVALENT", equivalent=False,
                             proven_points=1, non_equivalent_points=1))
    r = R._lec_post_layout_refusal(tmp_path)
    assert r and "NON_EQUIVALENT" in r


def test_an_unproven_proof_refuses(tmp_path):
    """The shape the container actually produced for a post-CTS AND2->OR2
    swap: 2 points, 1 proven, 1 unproven. §4.05 — not a pass."""
    _write(tmp_path, _proven(verdict="UNPROVEN", proven_points=1,
                             unproven_points=1))
    r = R._lec_post_layout_refusal(tmp_path)
    assert r and "UNPROVEN" in r


def test_a_vacuous_proof_refuses(tmp_path):
    """`equivalent: true` over ZERO compared points proves nothing."""
    _write(tmp_path, _proven(verdict="VACUOUS", total_points=0,
                             proven_points=0))
    r = R._lec_post_layout_refusal(tmp_path)
    assert r and "VACUOUS" in r


def test_a_run_error_refuses(tmp_path):
    _write(tmp_path, _proven(verdict="RUN_ERROR", equivalent=None,
                             total_points=None, proven_points=None,
                             unproven_points=None))
    r = R._lec_post_layout_refusal(tmp_path)
    assert r and "RUN_ERROR" in r


def test_an_unparseable_artefact_refuses(tmp_path):
    """A proof that cannot be READ is not a proof."""
    p = tmp_path / LEC_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json")
    assert R._lec_post_layout_refusal(tmp_path) is not None


def test_a_present_artefact_with_no_evaluator_refuses(tmp_path, monkeypatch):
    """If the authority module cannot be loaded, a PRESENT artefact must not be
    read as clean — the demotion this closes is exactly 'nobody checked it'."""
    _write(tmp_path, _proven())
    monkeypatch.setattr(R, "_lec_post_layout_module", lambda: None)
    r = R._lec_post_layout_refusal(tmp_path)
    assert r and "NOT ENFORCEABLE" in r


def test_no_evaluator_and_no_artefact_makes_no_claim(tmp_path, monkeypatch):
    """The other direction: nothing to enforce is not a manufactured failure."""
    monkeypatch.setattr(R, "_lec_post_layout_module", lambda: None)
    assert R._lec_post_layout_refusal(tmp_path) is None


# ------------------------------------------------- the refusal REACHES the ---
# ------------------------------------------------- step verdict, not a note --

def _pdk():
    n = Path("/nonexistent")
    return R.PdkConfig(name="democells", liberty=n / "x.lib",
                       tech_lef=n / "t.lef", cell_lef=n / "c.lef",
                       cell_gds=n / "c.gds", site="unitsite",
                       drc_deck=n / "d.lydrc")


def test_a_failed_proof_makes_the_step_fail(tmp_path):
    """Not a note, not a warning: `step_canonicalize_artefacts` FAILs, and a
    FAIL step is what makes `phase3_one_shot_runner.main` exit non-zero."""
    _write(tmp_path, _proven(verdict="UNPROVEN", proven_points=1,
                             unproven_points=1))
    res = R.step_canonicalize_artefacts(tmp_path, "top", _pdk(), "vibeic-eda")
    assert res.status == "FAIL"
    assert "post-layout LEC FAILED" in res.detail
    # ... and the chain from there to the process exit code: `main` returns 0
    # only for a PASS-family headline, and `_aggregate_verdict` puts any FAIL
    # step in the non-green bucket.
    assert R._aggregate_verdict([res]) == "FAIL"


def test_a_real_proof_leaves_the_step_alone(tmp_path):
    """The positive control on the same code path — the guard must discriminate,
    not just refuse."""
    _write(tmp_path, _proven())
    res = R.step_canonicalize_artefacts(tmp_path, "top", _pdk(), "vibeic-eda")
    assert res.status == "PASS"
    assert "post-layout LEC FAILED" not in res.detail
    assert R._aggregate_verdict([res]) == "PASS"
