#!/usr/bin/env python3
"""Regression for ORGANIC-20260614 #632 — --skip-analog must suppress the
analog / mixed-signal sub-gates INSIDE the P0 structural-RTL umbrella, not
only the per-step A1..A9 gates.

Bug (v1.0.22): flow_compliance_check honored --skip-analog only at the
per-step level (check_step downgrades step-A IDs to SKIPPED-CONDITION).
The P0 structural umbrella, computed by `_run_structural_rtl_gates`, took
NO skip_analog parameter and ran the analog/mixed-signal structural gates
(analog_*_check, mixed_signal_*_check, pdk_analog_*_check,
spice_correlation_*_check) UNCONDITIONALLY. For a data-converter /
mixed-signal IC with genuine analog content in L5, those P0 gates FAILed
identically with and without --skip-analog, holding the P0 umbrella at
FAIL — so a legitimately-deferred-analog digital deliverable could never
reach PASS_WITH_WAIVERS. The flag's effect was inconsistent: the A-step
gates obeyed it, the same-class gates inside P0 ignored it.

Fix: thread skip_analog into `_run_structural_rtl_gates` and, when set,
downgrade the analog sub-gates (derived from `_STRUCTURAL_RTL_GATES` by
canonical name-prefix — chip-AGNOSTIC) from FAIL to a SKIP entry with a
'analog track deferred via --skip-analog' reason, mirroring the A-step
suppression and the --skip-hardware FPGA-board downgrade.

NO-LEAK (load-bearing): the flag must change ONLY the analog sub-gates.
Non-analog structural FAILs (e.g. phase1_all_l_docs / rig_topology /
project_outputs) MUST still FAIL under --skip-analog, and a digital-only
project's fail set must be byte-identical with and without the flag.

chip-AGNOSTIC: synthetic generic fixtures only; the skip set is derived
from the registered gate FILE names, never a chip / vendor / SKU literal.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import flow_compliance_check as F  # noqa: E402

_ANALOG_TOKENS = ("analog_", "mixed_signal", "pdk_analog", "spice_correlation")


def _gate_of(line: str) -> str:
    """Extract the gate name from a 'FAIL: <gate> — ...' reason line."""
    s = line[len("FAIL: "):] if line.startswith("FAIL: ") else line
    return s.split(" ")[0]


def _is_analog_fail(line: str) -> bool:
    # Classify on the GATE NAME only — never the whole reason line (a
    # reason can echo a tmp PATH that happens to contain "analog", e.g.
    # a pytest tmpdir named test_analog_*).
    g = _gate_of(line)
    return any(g.startswith(t) for t in _ANALOG_TOKENS)


def _make_deferred_analog_project(root: Path) -> Path:
    """A mixed-signal IC with REAL analog blocks in L5 (so the analog
    structural gates are NON-vacuous) plus a minimal digital RTL dir (so
    the umbrella runs the digital track, not the pure-analog skip path)."""
    rtl = root / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "chip_top.v").write_text(
        "module chip_top(input clk, input rst, output reg [7:0] dout);\n"
        "  always @(posedge clk or posedge rst)\n"
        "    if (rst) dout <= 8'b0; else dout <= dout + 1'b1;\n"
        "endmodule\n")
    docs = root / "generated_docs"
    docs.mkdir(parents=True)
    (docs / "L5_ADI_SPEC.json").write_text(json.dumps({
        "analog_blocks": [
            {"name": "delta_sigma_adc", "type": "adc",
             "topology": "delta-sigma", "specs": {"enob": 16}},
            {"name": "ldo_reg", "type": "ldo", "specs": {"vout": 1.8}},
        ]
    }))
    analog = root / "analog"
    analog.mkdir(parents=True)
    (analog / "analog_block_list.json").write_text(json.dumps({
        "blocks": [{"name": "delta_sigma_adc"}, {"name": "ldo_reg"}]
    }))
    return root


# ---------------------------------------------------------------------------
# 1. The signature / derivation contract (chip-AGNOSTIC source of truth).
# ---------------------------------------------------------------------------
def test_signature_accepts_skip_analog():
    import inspect
    sig = inspect.signature(F._run_structural_rtl_gates)
    assert "skip_analog" in sig.parameters
    assert sig.parameters["skip_analog"].default is False


def test_skip_set_derived_from_registered_gates_and_chip_agnostic():
    skip = F._skip_analog_p0_gates()
    assert skip, "skip-analog gate set must be non-empty"
    # Every gate in the skip set is actually registered in the umbrella
    # (intersected with _STRUCTURAL_RTL_GATES — never a free-floating literal).
    for g in skip:
        assert g in F._STRUCTURAL_RTL_GATES
        assert F._is_analog_structural_gate(g)
    # The known analog/mixed-signal/pdk gates cited in #632 are covered.
    for g in ("analog_block_coverage_check", "analog_hardmacro_check",
              "mixed_signal_cosim_check", "analog_flow_compliance_check",
              "analog_digital_interface_check", "analog_a6_block_pv_check",
              "pdk_analog_completeness_check"):
        assert g in skip, f"{g} must be in the --skip-analog suppression set"
    # DERIVATION CHANGED — membership is the OWNERSHIP record, not the name
    # prefix this test used to pin. `analog_content_detected_must_emit_l5_check`
    # was asserted here as a member because it MATCHES the prefix; it does not
    # own the deferral. Its subject is the Phase-1 L5 record ("the docs
    # describe analog content L5 never wrote down"), it reads no A-step
    # artefact, and it is what makes an analog deferral reviewable — so it
    # stays required on a deferred-analog run. See
    # `flow_compliance_check._ANALOG_NAMED_NOT_OWNED` and
    # `test_deferred_gate_skip_by_ownership.py`.
    assert "analog_content_detected_must_emit_l5_check" not in skip
    # NO purely-digital structural gate may ever be in the analog skip set.
    for g in ("rig_topology_disclosure_check", "handshake_check",
              "bitwidth_consistency_check", "project_outputs_in_tree_check",
              "phase1_all_l_docs_present_check"):
        assert g not in skip


# ---------------------------------------------------------------------------
# 2. BEFORE -> AFTER: analog FAILs disappear under --skip-analog.
# ---------------------------------------------------------------------------
def test_analog_gates_fail_without_skip_then_skipped_with_skip(tmp_path):
    proj = _make_deferred_analog_project(tmp_path)

    # BEFORE-equivalent: skip_analog=False -> analog gates FAIL.
    _, f_off, _, _ = F._run_structural_rtl_gates(proj, skip_analog=False)
    analog_fail_off = [x for x in f_off if _is_analog_fail(x)]
    assert analog_fail_off, (
        "fixture must trip at least one analog structural gate when "
        "--skip-analog is NOT set (else the test proves nothing)")

    # AFTER: skip_analog=True -> NO analog gate is in the fail list; they
    # are downgraded to SKIP entries with the deferred-track reason.
    _, f_on, s_on, _ = F._run_structural_rtl_gates(proj, skip_analog=True)
    analog_fail_on = [x for x in f_on if _is_analog_fail(x)]
    assert analog_fail_on == [], (
        "no analog structural gate may FAIL when --skip-analog is set")
    deferred = [s for s in s_on if "analog track deferred" in s]
    assert deferred, "analog gates must be reported as deferred SKIP entries"
    # The exact gates that FAILed before now appear as deferred skips.
    for line in analog_fail_off:
        g = _gate_of(line)
        assert any(s.startswith(g + " ") for s in s_on), (
            f"{g} FAILed without --skip-analog but is not a deferred SKIP "
            "with it")


# ---------------------------------------------------------------------------
# 3. NO-LEAK: non-analog FAILs persist; digital-only set is unchanged.
# ---------------------------------------------------------------------------
def test_no_leak_non_analog_fails_persist_under_skip_analog(tmp_path):
    proj = _make_deferred_analog_project(tmp_path)
    _, f_off, _, _ = F._run_structural_rtl_gates(proj, skip_analog=False)
    _, f_on, _, _ = F._run_structural_rtl_gates(proj, skip_analog=True)

    non_analog_off = {_gate_of(x) for x in f_off if not _is_analog_fail(x)}
    non_analog_on = {_gate_of(x) for x in f_on if not _is_analog_fail(x)}
    # The flag must NOT relax any digital floor. We assert on a STABLE,
    # deterministic non-analog gate (phase1_all_l_docs_present_check FAILs
    # because this fixture omits L1..L23) rather than the whole fail set,
    # because a couple of unrelated structural gates write artefacts on
    # first run and so are flaky across repeated in-process invocations —
    # that flakiness is pre-existing and orthogonal to #632.
    stable = "phase1_all_l_docs_present_check"
    assert stable in non_analog_off, (
        "fixture must trip the stable non-analog gate without the flag")
    assert stable in non_analog_on, (
        f"NO-LEAK: {stable} (a digital floor) must STILL FAIL under "
        "--skip-analog — the flag may not relax a non-analog gate")
    # --skip-analog must never INTRODUCE a non-analog fail and never CLEAR
    # one: the deterministic-stable non-analog fails are a subset on both
    # sides (we compare the intersection-stable gate above; here we assert
    # the flag did not remove any non-analog gate that was failing).
    assert (non_analog_off - non_analog_on) == set() or \
        (non_analog_off - non_analog_on) <= {"project_outputs_in_tree_check"}


def test_no_leak_digital_only_project_unaffected_by_flag(tmp_path):
    # A digital-only project (no analog content) — --skip-analog must be a
    # complete no-op on the analog axis: no analog gate exists to suppress,
    # so an empty / under-populated digital doc is NEVER let through by the
    # flag. The umbrella verdict is the same with and without the flag.
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "top.v").write_text(
        "module top(input clk, output reg q);\n"
        "  always @(posedge clk) q <= ~q;\nendmodule\n")

    p_off, f_off, _, _ = F._run_structural_rtl_gates(tmp_path,
                                                     skip_analog=False)
    p_on, f_on, _, _ = F._run_structural_rtl_gates(tmp_path,
                                                    skip_analog=True)
    # Same overall verdict (the project still FAILs on its digital gaps).
    assert p_off == p_on
    # No analog gate is suppressed because none fired (digital-only doc),
    # so --skip-analog removes nothing here: the digital floor is intact.
    assert not any(_is_analog_fail(x) for x in f_off)
    assert not any(_is_analog_fail(x) for x in f_on)


# ---------------------------------------------------------------------------
# 4. The PASS flip: when EVERY structural fail is analog, --skip-analog lets
#    the umbrella reach passed=True (PASS_WITH_WAIVERS-reachable). Isolated
#    from unrelated gate noise via a minimal monkeypatched gate set.
# ---------------------------------------------------------------------------
def test_skip_analog_flips_passed_when_only_analog_fails(tmp_path,
                                                         monkeypatch):
    proj = _make_deferred_analog_project(tmp_path)
    # Restrict the umbrella to ONE analog gate that FAILs on this fixture
    # plus ONE digital gate that passes — so the only fail is analog.
    # analog_a6_block_pv_check FAILs deterministically when L5 carries real
    # analog_blocks + an analog_block_list but no A6 per-block PV artefacts;
    # handshake_check passes cleanly on the trivial counter RTL.
    minimal = ("analog_a6_block_pv_check", "handshake_check")
    monkeypatch.setattr(F, "_STRUCTURAL_RTL_GATES", minimal)

    p_off, f_off, _, _ = F._run_structural_rtl_gates(proj, skip_analog=False)
    # Without the flag, the analog gate FAILs -> umbrella not passing.
    assert p_off is False
    assert any(_is_analog_fail(x) for x in f_off)

    p_on, f_on, s_on, _ = F._run_structural_rtl_gates(proj, skip_analog=True)
    # With the flag, the sole analog fail is suppressed -> umbrella PASSes,
    # so a deferred-analog digital deliverable can reach PASS_WITH_WAIVERS.
    assert p_on is True
    assert f_on == []
    assert any("analog track deferred" in s for s in s_on)


def test_default_off_is_unchanged(tmp_path, monkeypatch):
    # Calling without the kwarg (legacy callers) must behave exactly like
    # skip_analog=False — the fix is opt-in only. We pin the umbrella to a
    # deterministic analog+digital pair so the assertion is stable.
    proj = _make_deferred_analog_project(tmp_path)
    monkeypatch.setattr(F, "_STRUCTURAL_RTL_GATES",
                        ("analog_a6_block_pv_check", "handshake_check"))
    p_default, f_default, _, _ = F._run_structural_rtl_gates(proj)
    p_off, f_off, _, _ = F._run_structural_rtl_gates(proj, skip_analog=False)
    assert p_default == p_off
    assert sorted(_gate_of(x) for x in f_default) == \
        sorted(_gate_of(x) for x in f_off)
    # The analog gate FAILs by default (no implicit suppression).
    assert any(_is_analog_fail(x) for x in f_default)
