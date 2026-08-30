"""The post-layout LEC record must not claim a netlist it did not read.

MEASURED DEFECT (subservient x gf180mcuD, plugin v1.13.40, image 0.3.39)
-----------------------------------------------------------------------
`_emit_lec_post_layout` picks the gate netlist correctly — prefer the
post-route-repaired netlist, else the routed PnR one — but then wrote a FIXED
scope sentence that named the repaired netlist either way::

    reports/phase3/lec_post_layout.json
      "gate":  .../phase3/stage3/pnr/subservient_pnr.v          <- pre-repair
      "scope": "re-proves the FINAL routed/post-route repair netlist == ..."

The fallback arm was correct: post-route timing repair had not written its
netlist when the gate ran (lec_post_layout.json 03:31,
subservient_timing_repaired.v 03:33). The record was not.

The two netlists are NOT the same design::

    phase3/stage3/pnr/subservient_pnr.v                35054 cells  md5 cac77753
    phase3/stage3/postroute_timing_repair/
        subservient_timing_repaired.v                  35034 cells  md5 73b27420

Post-route repair removed 20 cells, and it is the repaired netlist that
carries the run's best timing number (-4.65 ns vs -5.98 ns). So the netlist a
reader would sign off on had NO equivalence evidence at all, and the LEC
record said it did.

Direction of the error: it OVER-claims. No verdict flips — the run was
UNPROVEN either way — but a scope wider than the measurement is precisely what
this gate exists to prevent, which makes it worse here than in a gate that
merely miscounts.

chip-AGNOSTIC: both arms are the flow's own; no design, PDK or vendor literal.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

_PROGRAMS_DIR = Path(__file__).resolve().parent.parent
if str(_PROGRAMS_DIR) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS_DIR))

import phase3_one_shot_runner as R  # noqa: E402

# `getattr`, not attribute access: against the PRE-FIX runner the helper does
# not exist, and a bare access raises at import time — a collection ERROR that
# names a missing attribute instead of the defect. Every test below then fails
# cleanly, saying what is actually wrong.
SCOPE = getattr(R, "lec_post_layout_scope", None)
_NO_HELPER = (
    "the runner derives no scope from the arm it took: `_emit_lec_post_layout` "
    "writes ONE literal scope sentence naming the post-route-repaired netlist "
    "whichever netlist it actually read."
)


def test_the_repaired_arm_says_repaired():
    assert SCOPE is not None, _NO_HELPER
    s = SCOPE("postroute_timing_repaired", "post_dft", "top")
    assert "post-route-repaired netlist" in s
    assert "NO post-route-repair netlist existed" not in s


def test_the_fallback_arm_does_not_claim_the_repaired_netlist():
    """THE REGRESSION. Fails against the fixed literal, which said
    "FINAL routed/post-route repair netlist" on this arm too."""
    s = SCOPE("pnr_routed", "post_dft", "top")
    assert "ROUTED PnR netlist" in s, s
    assert "post-route repair netlist ==" not in s, (
        "the fallback arm proved the routed PnR netlist; claiming the "
        f"post-route-repair one is a scope wider than the measurement: {s}"
    )
    assert "UNPROVEN by this record" in s, (
        "an over-claim is not fixed by going silent — the record must say "
        f"that a later repaired netlist is NOT vouched for: {s}"
    )
    assert "top_timing_repaired.v" in s, (
        "name the artefact that is left unproven, so a reader can go look "
        f"for it: {s}"
    )


def test_the_two_arms_are_not_the_same_sentence():
    """Negative control against a 'fix' that derives nothing.

    A helper that ignores `gate_kind` and returns one string would satisfy
    every substring assertion above that happened to be in it. The arms must
    DIFFER.
    """
    assert SCOPE is not None, _NO_HELPER
    assert (SCOPE("postroute_timing_repaired", "post_dft", "top")
            != SCOPE("pnr_routed", "post_dft", "top"))


def test_the_emitter_derives_the_scope_rather_than_asserting_one():
    """The helper is only worth testing if the record actually uses it.

    Pins that `_emit_lec_post_layout` calls it and carries no second, literal
    scope sentence that could drift away from the arm.
    """
    src = inspect.getsource(R._emit_lec_post_layout)
    assert '"scope": lec_post_layout_scope(' in src, (
        "the record must DERIVE its scope from the arm it took; a literal "
        "bound to the scope key claims the repaired netlist on both arms"
    )


def test_the_record_carries_the_arm_as_a_field():
    """A reader should not have to recognise a path to know which netlist was
    compared. `gate_kind` is the machine-readable half of the same fact."""
    src = inspect.getsource(R._emit_lec_post_layout)
    assert '"gate_kind": gate_kind' in src
    assert 'gate_kind = "postroute_timing_repaired"' in src or \
           '"postroute_timing_repaired")' in src
