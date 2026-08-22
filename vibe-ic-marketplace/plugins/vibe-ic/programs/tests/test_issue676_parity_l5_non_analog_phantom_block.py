"""ORGANIC #676 PARITY — `l_doc_structured_field_count_check` layer 5 hard-FAILs
a POSITIVELY non-analog IC over a PHANTOM `low_confidence` analog block.

OBSERVED (measured on a real pure-digital project):

    l_doc_structured_field_count_check . → exit 1
    L5_ADI_SPEC.json: L5 adi_spec must carry ≥3 typed analog blocks
                      (or set `no_analog: true`); have 1.

The single block was `{"type": "esd", "spec": null, "low_confidence": true}` —
fabricated by the Phase-1 keyword harvester from an analog token that occurred
in the input docs ONLY inside statements asserting its ABSENCE. Meanwhile the
same project's `reports/ic_class.json` carried `has_analog: false`, the
registry marked the detected class `analog_applicable: false`, and nine sibling
analog gates in the same P0 run SKIPped as `N/A … This IC has no analog
content`. Four components said "no analog"; this gate sided with the phantom.

The floor was therefore UNSATISFIABLE for such a design: ≥3 typed analog blocks
is impossible for a design with no analog, and the `no_analog: true` escape was
unavailable precisely BECAUSE the harvester had written `no_analog: false` off
the phantom hit.

ORGANIC #676 already settled this exact question for the 3 analog P0 gates
(`_analog_a_check_common._ic_class_says_non_analog` + `_all_blocks_low_
confidence`), for the same reason and against the same phantom shape (there the
keyword was "POR"). This L5 floor is a FOURTH gate in that family that never
received the predicate: its only escapes were the doc's own `no_analog` flag and
#634's `sparse_analog_block_set` (which means SPARSE analog, not NO analog) —
neither keyed on `analog_applicable`.

FIX: `_class_non_analog_phantom_only(ic_class, blocks)` — the floor is N/A only
when the registry marks the class `analog_applicable is False` AND every
declared block is `low_confidence: true`.

POSITIVE (FAILS against the byte-identical pre-fix file, PASSES after):
  a non-analog class carrying one phantom low_confidence block now passes L5.

NEGATIVE / no-leak controls (the load-bearing half — these pass BOTH before and
after, so the fix cannot have been "tighten the filter until the count is zero",
which would swallow the real defect underneath):
  - an ANALOG class (analog_applicable true) with the same phantom block still
    FAILs — the relaxation is not global;
  - a non-analog class with a SPEC-BACKED (high-confidence) block still FAILs —
    a genuine class/doc contradiction stays visible;
  - a non-analog class with a MIXED set (one phantom + one spec-backed) still
    FAILs;
  - an EMPTY block list still FAILs — the honest `no_analog: true` declaration
    is still required, so an under-populated doc can never ride this to a pass;
  - the fail-closed classes (bare_fpga / unknown_protocol_class) still FAIL;
  - the pre-existing `no_analog: true` escape still PASSES;
  - #634's `sparse_analog_block_set` ≥2 floor is unchanged.

chip-AGNOSTIC: a registry semantic flag + the per-block confidence tag. No chip,
vendor, PDK, process-node or part-number literal appears in the decision or in
this test.
"""
import json
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import l_doc_structured_field_count_check as C  # noqa: E402

_REGISTRY = json.loads(
    (PLUGIN / "programs" / "ic_class_registry.json").read_text())
_CLASSES = _REGISTRY["classes"]

# Fail-closed classes are excluded from the relaxation by construction.
_FAIL_CLOSED = set(C._NO_PROTOCOL_FAIL_CLOSED)
_NON_ANALOG = [e["name"] for e in _CLASSES
               if e.get("analog_applicable") is False
               and e["name"] not in _FAIL_CLOSED]
_ANALOG = [e["name"] for e in _CLASSES
           if e.get("analog_applicable") is True]

# The observed shape: one keyword-harvested block, no spec, low confidence.
PHANTOM = {"analog_blocks": [
    {"name": "esd", "type": "esd", "spec": None, "low_confidence": True}],
    "no_analog": False}
SPEC_BACKED = {"analog_blocks": [
    {"name": "ldo", "type": "ldo", "spec": {"vout": 1.8},
     "low_confidence": False}],
    "no_analog": False}
MIXED = {"analog_blocks": [
    {"name": "esd", "type": "esd", "spec": None, "low_confidence": True},
    {"name": "ldo", "type": "ldo", "spec": {"vout": 1.8},
     "low_confidence": False}],
    "no_analog": False}
EMPTY = {"analog_blocks": [], "no_analog": False}


# ── POSITIVE — fails against the pre-fix file, passes after ──────────────
def test_non_analog_class_with_phantom_block_passes_l5():
    """The observed defect. Pre-fix this returns (False, '…have 1.')."""
    assert _NON_ANALOG, "registry must carry non-analog classes"
    for cls in _NON_ANALOG:
        ok, reason = C._check_l_doc(5, dict(PHANTOM), ic_class=cls)
        assert ok, (
            f"{cls} is registry analog_applicable=false and its only block is "
            f"a phantom low_confidence keyword hit; L5 must be N/A — got "
            f"{reason!r}")


def test_predicate_true_for_exactly_the_non_analog_classes():
    for cls in _NON_ANALOG:
        assert C._class_non_analog_phantom_only(
            cls, PHANTOM["analog_blocks"]) is True, cls


# ── NEGATIVE no-leak — must hold BOTH before and after the fix ───────────
# NOTE: every control below exercises ONLY `_check_l_doc` — the behaviour that
# exists in BOTH the pre-fix and post-fix file — so each one genuinely passes
# both ways. A control that referenced the new helper would fail pre-fix with
# AttributeError and would prove nothing.
def test_analog_class_with_phantom_block_still_fails():
    """The relaxation must not be global: a real analog class keeps the floor."""
    assert _ANALOG, "registry must carry analog classes"
    for cls in _ANALOG:
        ok, _ = C._check_l_doc(5, dict(PHANTOM), ic_class=cls)
        assert not ok, (
            f"{cls} is analog_applicable=true — the ≥3 floor must survive")


def test_non_analog_class_with_spec_backed_block_still_fails():
    """A high-confidence block on a non-analog class is a real contradiction
    and must stay visible. This is the control that catches a fix which
    relaxed on class alone."""
    for cls in _NON_ANALOG:
        ok, _ = C._check_l_doc(5, dict(SPEC_BACKED), ic_class=cls)
        assert not ok, (
            f"{cls} carries a SPEC-BACKED analog block — not a phantom; the "
            f"floor must still apply")


def test_non_analog_class_with_mixed_blocks_still_fails():
    for cls in _NON_ANALOG:
        ok, _ = C._check_l_doc(5, dict(MIXED), ic_class=cls)
        assert not ok, f"{cls}: one spec-backed block disqualifies the escape"


def test_empty_block_list_still_fails_everywhere():
    """The escape never converts an under-populated doc into a pass — the
    honest `no_analog: true` declaration is still required."""
    for cls in _NON_ANALOG + _ANALOG:
        ok, _ = C._check_l_doc(5, dict(EMPTY), ic_class=cls)
        assert not ok, f"{cls}: an EMPTY L5 must still FAIL"


def test_fail_closed_classes_still_fail():
    for cls in sorted(_FAIL_CLOSED):
        ok, _ = C._check_l_doc(5, dict(PHANTOM), ic_class=cls)
        assert not ok, f"{cls} is fail-closed and must keep the floor"


def test_unregistered_class_fails_closed():
    """An unknown class name must never ride the escape."""
    for cls in ("", "not_a_registered_class"):
        ok, _ = C._check_l_doc(5, dict(PHANTOM), ic_class=cls)
        assert not ok, f"{cls!r}: unregistered classes must fail closed"


def test_no_analog_true_escape_unchanged():
    for cls in _NON_ANALOG + _ANALOG:
        ok, _ = C._check_l_doc(5, {"no_analog": True}, ic_class=cls)
        assert ok, f"{cls}: the pre-existing no_analog escape must survive"


def test_issue634_sparse_analog_floor_unchanged():
    """#634's ≥2 floor for sparse_analog_block_set classes is untouched."""
    sparse = [e["name"] for e in _CLASSES
              if e.get("sparse_analog_block_set") is True]
    for cls in sparse:
        two = {"analog_blocks": [
            {"name": "modulator", "type": "modulator",
             "spec": {"osr": 64}, "low_confidence": False},
            {"name": "ref", "type": "reference",
             "spec": {"vref": 1.2}, "low_confidence": False}],
            "no_analog": False}
        ok, _ = C._check_l_doc(5, two, ic_class=cls)
        assert ok, f"{cls}: #634 relaxed floor (≥2 spec-backed) must still pass"
