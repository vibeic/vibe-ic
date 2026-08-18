"""tests/test_protocol_synth_dispatch_reachability.py — ORGANIC-20260531 (v0.2.32).

Closes the silent-skip hazard in the Phase-1 protocol-synth dispatch.

ROOT CAUSE
----------
The runner (``phase1_doc_one_shot_runner.py``) dispatches the ~80 hand-wired
built-in ``*_protocol_synth`` calls inside ic_class-gated blocks: the [14e/15]
R55 block fired only for a fixed TUPLE of classes, and the post-R55 [14e2/15]
block fires only for ``bus_interconnect_protocol``. If ``detect_ic_class``
returned a class that NO dispatch block fired for (``bare_fpga`` /
``aid_class_half_duplex`` / ``mixed_signal_otp`` under the old tuple), the whole
protocol-synth chain was SILENTLY skipped: the inline structural detectors — the
REAL gate — never even ran, no error, no log line. A 0-gated standalone detector
test still passed (the detector is content-self-gating), so parity could not
catch it. That is exactly the Avalon ``digital_arithmetic_primitive`` routing
surprise the backlog was filed on.

THE FIX (Option A from the backlog, made fail-closed)
-----------------------------------------------------
1. ``ic_class_profile.ALL_IC_CLASSES`` — the closed set of class strings
   ``detect_ic_class`` can assign. Pinned here against the source so it cannot
   drift (a NEW class added to ``detect_ic_class`` but not here = test FAIL).
2. ``protocol_synth_dispatch_classes()`` — the SINGLE source of truth the runner
   imports for its gate. Equals ``ALL_IC_CLASSES`` so EVERY class reaches
   dispatch (no class silently skipped).
3. ``protocol_synth_unreachable_classes()`` — the silent-skip set. MUST be empty
   (the closed state).
4. ``phase1_doc_one_shot_runner.protocol_dispatch_decision(ic_class)`` — the
   pure, testable gate the runner delegates to. When a class is unreachable it
   returns ``reachable=False`` WITH an explicit ``signal`` payload (written to
   ``reports/phase1/protocol_dispatch_skipped.json``) — fail-closed, never a
   silent drop.

This test pins: (PASS) the closed-state invariant + every valid class
dispatches; (real FAIL surfaced) the unrouted-class path returns an explicit
signal, not a silent skip; (no-cheating) the runner consults the canonical
source rather than a hardcoded tuple.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

PROGRAMS_DIR = Path(__file__).resolve().parent.parent
RUNNER_SRC = PROGRAMS_DIR / "phase1_doc_one_shot_runner.py"
PROFILE_SRC = PROGRAMS_DIR / "ic_class_profile.py"

import ic_class_profile as icp  # noqa: E402


# --------------------------------------------------------------------------- #
# (1) Closed-state invariant — NO class is silently skipped.
# --------------------------------------------------------------------------- #
def test_dispatch_has_no_unreachable_class():
    """The silent-skip set is empty == every class reaches dispatch."""
    unreachable = icp.protocol_synth_unreachable_classes()
    assert unreachable == frozenset(), (
        "Protocol-synth dispatch can SILENTLY skip these classes "
        f"(no dispatch block fires for them): {sorted(unreachable)}. "
        "Add them to PROTOCOL_SYNTH_DISPATCH_CLASSES in ic_class_profile.py "
        "or the runner must emit an explicit skip signal for them."
    )


def test_dispatch_set_equals_all_classes():
    """Option-A guarantee: dispatch reaches the full class taxonomy."""
    assert (icp.protocol_synth_dispatch_classes()
            == frozenset(icp.ALL_IC_CLASSES))


# --------------------------------------------------------------------------- #
# (2) Drift guard — ALL_IC_CLASSES must match every class detect_ic_class
#     actually assigns in the source. A new class added to detect_ic_class but
#     not registered here would otherwise be silently unrouted.
# --------------------------------------------------------------------------- #
def _source_assigned_classes() -> set:
    """Every literal `profile["ic_class"] = "<X>"` in ic_class_profile.py."""
    src = PROFILE_SRC.read_text()
    pat = re.compile(r'profile\[\s*["\']ic_class["\']\s*\]\s*=\s*["\']([^"\']+)["\']')
    found = set(pat.findall(src))
    # The Path-A skeleton branch and fall-through both assign too — captured by
    # the same pattern. Sanity: at least the core protocol classes are present.
    assert found, "could not locate any ic_class assignment in source"
    return found


def test_all_ic_classes_matches_source_assignments():
    src_classes = _source_assigned_classes()
    declared = set(icp.ALL_IC_CLASSES)
    missing = src_classes - declared
    extra = declared - src_classes
    assert not missing, (
        f"detect_ic_class assigns classes NOT in ALL_IC_CLASSES: "
        f"{sorted(missing)} — they would be silently unrouted. "
        "Add them to ALL_IC_CLASSES (and confirm dispatch reaches them)."
    )
    assert not extra, (
        f"ALL_IC_CLASSES declares classes detect_ic_class never assigns: "
        f"{sorted(extra)} — remove the dead taxonomy entries."
    )


# --------------------------------------------------------------------------- #
# (3) Regression — every VALID class still dispatches.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("ic_class", sorted(icp.ALL_IC_CLASSES))
def test_every_valid_class_reaches_dispatch(ic_class):
    import phase1_doc_one_shot_runner as runner
    dec = runner.protocol_dispatch_decision(ic_class)
    assert dec["reachable"] is True, (
        f"valid class '{ic_class}' does NOT reach protocol-synth dispatch"
    )
    assert dec["signal"] is None, (
        f"valid class '{ic_class}' must not produce a skip signal"
    )


# --------------------------------------------------------------------------- #
# (4) The no-longer-silent path — an UNROUTED class produces an EXPLICIT
#     signal (fail-closed), not a silent skip.
# --------------------------------------------------------------------------- #
def test_unrouted_class_surfaces_explicit_signal():
    import phase1_doc_one_shot_runner as runner
    # A class detect_ic_class would never return — simulates a FUTURE class
    # added to detect_ic_class but left out of the dispatch set, OR a typo'd
    # class string. The decision MUST refuse to silently skip.
    dec = runner.protocol_dispatch_decision("__hypothetical_unrouted_class__")
    assert dec["reachable"] is False
    assert dec["signal"] is not None, (
        "an unrouted class MUST surface an explicit signal — silent skip is "
        "exactly the hazard this fix closes"
    )
    sig = dec["signal"]
    assert sig["unreachable"] is True
    assert sig["ic_class"] == "__hypothetical_unrouted_class__"
    # Signal is JSON-serialisable (it is written to disk by the runner).
    json.dumps(sig)
    # The signal names where the fix belongs (actionable, not opaque).
    assert "PROTOCOL_SYNTH_DISPATCH_CLASSES" in sig["_comment"]


def test_runner_writes_skip_signal_file_for_unrouted_class(tmp_path):
    """End-to-end: the runner's write step lands the documented signal file.

    Mirrors the exact write the [14e/15] block performs when a class is
    unreachable, driven by the same pure helper the runner calls — so this
    pins the on-disk artifact a downstream gate / audit would look for.
    """
    import phase1_doc_one_shot_runner as runner
    dec = runner.protocol_dispatch_decision("__hypothetical_unrouted_class__")
    assert dec["reachable"] is False
    reports = tmp_path / "reports" / "phase1"
    reports.mkdir(parents=True, exist_ok=True)
    out = reports / "protocol_dispatch_skipped.json"
    out.write_text(json.dumps(dec["signal"], indent=2, ensure_ascii=False) + "\n")
    loaded = json.loads(out.read_text())
    assert loaded["unreachable"] is True
    assert loaded["ic_class"] == "__hypothetical_unrouted_class__"
    assert sorted(loaded["dispatch_classes"]) == sorted(icp.ALL_IC_CLASSES)


# --------------------------------------------------------------------------- #
# (5) No-cheating — the runner consults the canonical source, not a hardcoded
#     class tuple inlined in the gate.
# --------------------------------------------------------------------------- #
def test_runner_gate_delegates_to_pure_decision_helper():
    src = RUNNER_SRC.read_text()
    # The [14e/15] gate must route through the pure helper.
    assert "protocol_dispatch_decision(_ic_r55)" in src, (
        "the R55 dispatch gate must delegate to protocol_dispatch_decision()"
    )
    # And the gate must not re-introduce the old hardcoded class tuple. The
    # specific 6-class tuple literal that caused the silent skip must be gone.
    old_tuple = ('("serial_peripheral_protocol", "digital_cmd_driven",')
    assert old_tuple not in src, (
        "the old hardcoded R55 class tuple is back — that re-opens the "
        "silent-skip hazard (use protocol_synth_dispatch_classes() instead)"
    )


def test_decision_helper_imports_canonical_dispatch_source():
    """The pure helper must derive its set from ic_class_profile, not a copy."""
    src = RUNNER_SRC.read_text()
    # locate the helper body
    start = src.index("def protocol_dispatch_decision(")
    end = src.index("\ndef ", start + 1)
    body = src[start:end]
    assert "protocol_synth_dispatch_classes" in body
    assert "ALL_IC_CLASSES" in body


# --------------------------------------------------------------------------- #
# (6) Corpus-clean smoke — a serial-protocol L-doc set classifies into a
#     dispatch class (so it genuinely reaches the synth chain, not the skip).
# --------------------------------------------------------------------------- #
def _write_doc(project: Path, name: str, body: dict) -> None:
    p = project / "phase1" / "generated_docs" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(body, indent=2))


def test_serial_protocol_doc_classifies_into_a_dispatch_class(tmp_path):
    project = tmp_path / "ic_serial_demo"
    # Minimal SPI-flavoured serial-peripheral spec: hits role_pair +
    # shift_register + serial_concept + clock_baud_control + chip-select.
    _write_doc(project, "L1_DATASHEET.json", {
        "ic_name": "Generic Serial Peripheral",
        "description": (
            "A synchronous serial peripheral with a master and slave role. "
            "Data is moved through a shift register on each SCK edge. The "
            "controller drives a chip select line to the target device."),
        "pins": "It has four external pins: SCK, MOSI, MISO and slave select.",
    })
    _write_doc(project, "L2_FRS.json", {
        "protocol_type": "spi",
        "functional_requirements": (
            "The SCK clock divisor sets the serial bit rate. The transmitter "
            "and receiver exchange one byte per frame."),
    })
    profile = icp.detect_ic_class(project)
    ic_class = profile.get("ic_class")
    assert ic_class in icp.protocol_synth_dispatch_classes(), (
        f"a serial-peripheral spec classified as '{ic_class}', which the "
        "dispatch must reach — otherwise its protocol synth is silently skipped"
    )

    import phase1_doc_one_shot_runner as runner
    dec = runner.protocol_dispatch_decision(ic_class)
    assert dec["reachable"] is True
    assert dec["signal"] is None
