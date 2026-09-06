#!/usr/bin/env python3
"""A wrapper default selected a variant the design had deliberately removed.

MEASURED DEFECT
===============
`_autoemit_chip_top_wrapper` copies the DUT's ``#(parameter ...)`` header
verbatim. A security-hardened IP ships several implementation variants of one
block behind a compile-time parameter, and a staging convention may EXCLUDE one
by renaming its file ``<module>.sv.unused-<why>-excluded`` so no RTL glob picks
it up. When the copied default names exactly that variant, the wrapper cannot
elaborate at all — and the flow discovered it several steps later as a raw

    ERROR: Module `\\aes_sbox_dom' referenced in module
    `$paramod\\aes_sbox\\SecSBoxImpl=...' ... is not part of the design

which reads as a synthesis failure and was triaged as one. One unset parameter,
five red steps (l10_unit_tb_run, step4_functional_evidence, yosys_synth,
verilator_coverage, reference_tb) and a BLOCKED dft_lec_chain.

THE LINE THIS MUST NOT CROSS
============================
#586 refuses to pick a variant for the operator, and that refusal survives: a
FREE CHOICE must be DECLARED. The emitter resolves ONLY when the design input
declared something that decides it, and the value is then derived from the
RTL's OWN guard structure — never invented. In every other case it REFUSES BY
NAME, at emission, before a tool is started.

Both directions are pinned below, plus the two controls that must be NO-OPS
byte for byte, plus the two mutations that must re-redden.
"""
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import design_one_shot_runner as D  # noqa: E402

WRAPPER_BLOCK = """#(
  parameter bit          SecMasking  = 0,
  parameter sbox_impl_e  SecSBoxImpl = SBoxImplDom
)"""

# A three-variant block behind one selector, with the design's OWN derivation
# (`Masked`) and its OWN default (`VariantLut`). Deliberately NOT the shape of
# any one vendor's file: what is pinned is the STRUCTURE, not a vocabulary.
SBOX_SV = """
module thing_sbox #(
  parameter sbox_impl_e SecSBoxImpl = SBoxImplLut
) (input logic a, output logic b);

  localparam bit Masked = (SecSBoxImpl == SBoxImplCanrightMasked ||
                           SecSBoxImpl == SBoxImplCanrightMaskedNoreuse ||
                           SecSBoxImpl == SBoxImplDom) ? 1'b1 : 1'b0;

  if (!Masked) begin : gen_unmasked
    if (SecSBoxImpl == SBoxImplCanright) begin : gen_canright
      thing_sbox_canright u_sbox (.a(a), .b(b));
    end else begin : gen_lut
      thing_sbox_lut u_sbox (.a(a), .b(b));
    end
  end else begin : gen_masked
    if (SecSBoxImpl == SBoxImplDom) begin : gen_dom
      thing_sbox_dom u_sbox (.a(a), .b(b));
    end else if (SecSBoxImpl == SBoxImplCanrightMaskedNoreuse) begin :
        gen_canright_masked_noreuse
      thing_sbox_canright_masked_noreuse u_sbox (.a(a), .b(b));
    end else begin : gen_canright_masked
      thing_sbox_canright_masked u_sbox (.a(a), .b(b));
    end
  end
endmodule
"""

# The DEFECT NEEDS TWO MODULES, and a fixture with one is vacuous — measured:
# an earlier version of the A/B below wrapped `thing_sbox` itself, whose own
# default is already the in-closure variant, so it PASSED on the pre-fix tree
# and observed nothing. The integration top declares the EXCLUDED variant; the
# module that consumes the parameter declares an in-closure one. That gap is
# the defect, and only a two-module fixture has it.
THING_TOP = """
module thing_top #(
  parameter bit         SecMasking  = 1,
  parameter sbox_impl_e SecSBoxImpl = SBoxImplDom
) (input logic a, output logic b);
  thing_sbox #(.SecSBoxImpl(SecSBoxImpl)) u_sbox (.a(a), .b(b));
endmodule
"""

LEAVES = ("thing_sbox_lut", "thing_sbox_canright",
          "thing_sbox_canright_masked",
          "thing_sbox_canright_masked_noreuse")


def _project(exclude_dom=True, ship_dom=False):
    root = Path(tempfile.mkdtemp(prefix="excl_variant_"))
    rtl = root / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (root / "input").mkdir()
    (rtl / "thing_sbox.sv").write_text(SBOX_SV)
    (rtl / "thing_top.sv").write_text(THING_TOP)
    for leaf in LEAVES:
        (rtl / f"{leaf}.sv").write_text(
            f"module {leaf} (input logic a, output logic b);\n"
            f"  assign b = a;\nendmodule\n")
    if exclude_dom:
        (root / "input" / "thing_sbox_dom.sv.unused-masked-scan-excluded"
         ).write_text("module thing_sbox_dom (input logic a, output logic b);"
                      "\n  assign b = a;\nendmodule\n")
    if ship_dom:
        (rtl / "thing_sbox_dom.sv").write_text(
            "module thing_sbox_dom (input logic a, output logic b);\n"
            "  assign b = a;\nendmodule\n")
    return root, rtl


def _value(block, name):
    m = re.search(r"\b" + name + r"\s*=\s*([^,;)\n]+)", block)
    return m.group(1).strip() if m else None


def test_declared_masking_off_derives_the_unmasked_in_closure_variant():
    """DIRECTION 1 — the input DECLARED it, so the flow derives it."""
    root, rtl = _project()
    block, resolved, refusals = D._chip_top_resolve_excluded_variant_params(
        root, rtl, WRAPPER_BLOCK, {"SecMasking": "0"})
    assert refusals == []
    assert "SecSBoxImpl" in resolved
    assert resolved["SecSBoxImpl"]["value"] == "SBoxImplLut"
    assert _value(block, "SecSBoxImpl") == "SBoxImplLut"
    # The provenance is the point: a reader must be able to re-derive it.
    d = resolved["SecSBoxImpl"]["derivation"]
    assert d["declared_parameter"] == "SecMasking"
    assert d["declared_value"] == "0"
    assert d["rtl_predicate"] == "Masked"
    assert "SBoxImplDom" in d["rtl_predicate_true_for"]
    assert resolved["SecSBoxImpl"]["excluded_modules"] == ["thing_sbox_dom"]
    shutil.rmtree(root, ignore_errors=True)


def test_undeclared_is_refused_by_name_and_nothing_is_picked():
    """DIRECTION 2 — nothing declared, so the choice is FREE and REFUSED."""
    root, rtl = _project()
    block, resolved, refusals = D._chip_top_resolve_excluded_variant_params(
        root, rtl, WRAPPER_BLOCK, {})
    assert resolved == {}
    assert [r["reason"] for r in refusals] == ["UNDECLARED_FREE_CHOICE"]
    r = refusals[0]
    assert r["parameter"] == "SecSBoxImpl"
    assert r["excluded_modules"] == ["thing_sbox_dom"]
    assert r["excluded_files"] == [
        "input/thing_sbox_dom.sv.unused-masked-scan-excluded"]
    # The wrapper is NOT rewritten on a refusal.
    assert block == WRAPPER_BLOCK
    shutil.rmtree(root, ignore_errors=True)


def test_a_refusal_reaches_the_step_that_would_have_run_yosys():
    """The refusal is a FAIL the flow states, not a note nobody reads."""
    root, rtl = _project()
    assert D._chip_top_param_refusals(rtl, "chip_top") == []
    (rtl / ".chip_top__param_resolution.json").write_text(
        '{"resolved": {}, "refusals": [{"parameter": "SecSBoxImpl", '
        '"reason": "UNDECLARED_FREE_CHOICE", "message": "x"}]}')
    got = D._chip_top_param_refusals(rtl, "chip_top")
    assert [g["parameter"] for g in got] == ["SecSBoxImpl"]
    shutil.rmtree(root, ignore_errors=True)


def test_control_a_cell_that_ships_the_variant_keeps_its_default():
    """CONTROL — nothing is excluded, so nothing is resolved and the copied
    block comes back BYTE-IDENTICAL."""
    root, rtl = _project(exclude_dom=False, ship_dom=True)
    block, resolved, refusals = D._chip_top_resolve_excluded_variant_params(
        root, rtl, WRAPPER_BLOCK, {"SecMasking": "0"})
    assert (resolved, refusals) == ({}, [])
    assert block == WRAPPER_BLOCK
    shutil.rmtree(root, ignore_errors=True)


def test_control_a_design_with_no_exclusion_marker_at_all():
    """CONTROL — the whole mechanism is a no-op on every ordinary design."""
    root, rtl = _project(exclude_dom=False)
    block, resolved, refusals = D._chip_top_resolve_excluded_variant_params(
        root, rtl, WRAPPER_BLOCK, {"SecMasking": "0"})
    assert (resolved, refusals) == ({}, [])
    assert block == WRAPPER_BLOCK
    shutil.rmtree(root, ignore_errors=True)


def test_mutation_an_unreadable_guard_refuses_instead_of_passing_it_on():
    """MUTATION — the derivation can no longer be read. UNKNOWN is not SAFE:
    skipping here is exactly how the abort reached yosys in the first place."""
    root, rtl = _project()
    p = rtl / "thing_sbox.sv"
    p.write_text(re.sub(r"localparam bit Masked = [^;]+;",
                        "localparam bit Masked = SomeOtherKnob;",
                        p.read_text(), flags=re.S))
    block, resolved, refusals = D._chip_top_resolve_excluded_variant_params(
        root, rtl, WRAPPER_BLOCK, {"SecMasking": "0"})
    assert resolved == {}
    assert [r["reason"] for r in refusals] == ["UNREADABLE_GUARD"]
    assert block == WRAPPER_BLOCK
    shutil.rmtree(root, ignore_errors=True)


def test_mutation_the_declared_value_decides_and_an_unnameable_arm_refuses():
    """MUTATION — flip the DECLARED value. The answer must follow it, and
    where the surviving arm cannot be NAMED the flow must refuse rather than
    choose out of a set it can only partly spell."""
    root, rtl = _project()
    block, resolved, refusals = D._chip_top_resolve_excluded_variant_params(
        root, rtl, WRAPPER_BLOCK, {"SecMasking": "1"})
    assert resolved == {}
    assert [r["reason"] for r in refusals] == ["INCOMPLETE_CANDIDATE_SET"]
    assert refusals[0]["unnameable_in_closure_variants"] == [
        "thing_sbox_canright_masked"]
    assert block == WRAPPER_BLOCK
    shutil.rmtree(root, ignore_errors=True)


def test_mutation_no_in_closure_variant_matches_the_declaration():
    """MUTATION — declare masking ON while EVERY masked variant is out of the
    closure. There is nothing consistent to choose, and the flow says so by
    name rather than falling back to something unmasked."""
    root, rtl = _project()
    for leaf in ("thing_sbox_canright_masked",
                 "thing_sbox_canright_masked_noreuse"):
        (rtl / f"{leaf}.sv").rename(
            root / "input" / f"{leaf}.sv.unused-masked-scan-excluded")
    block, resolved, refusals = D._chip_top_resolve_excluded_variant_params(
        root, rtl, WRAPPER_BLOCK, {"SecMasking": "1"})
    assert resolved == {}
    assert [r["reason"] for r in refusals] == ["NO_VARIANT_MATCHES_DECLARATION"]
    assert block == WRAPPER_BLOCK
    shutil.rmtree(root, ignore_errors=True)


def test_end_to_end_the_emitted_wrapper_carries_the_derived_value():
    """The A/B THE PRE-FIX TREE CAN ALSO RUN.

    Every other test here calls a function that does not exist before the fix,
    so on the old tree they ERROR rather than observe. This one goes through
    `_autoemit_chip_top_wrapper`, which exists on both sides, and reads the
    emitted file. On the pre-fix tree that wrapper carries the EXCLUDED
    variant; here it must carry the derived one. That is the defect, stated so
    both trees can answer it.
    """
    root, rtl = _project()
    gd = root / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L8_RTL_CONSTANTS.json").write_text(
        '{"parameters": [{"name": "SecMasking", "value": "0",'
        ' "override": true}]}')
    (gd / "L9_INTEGRATION_SPEC.json").write_text('{"top_module": "thing_top"}')
    out = D._autoemit_chip_top_wrapper(root, rtl, "chip_top")
    assert out is not None, "no wrapper emitted"
    text = out.read_text()
    assert "SBoxImplLut" in text
    assert "SBoxImplDom" not in text
    shutil.rmtree(root, ignore_errors=True)


def test_the_step_refuses_by_name_whatever_the_sidecar_is_called():
    """MEASURED HOLE IN THE WIRING ITSELF.

    The wrapper is emitted by whichever step gets there first: the reused-IP
    CONSUME step names it ``chip_top``, and `step_yosys_synth` may then
    re-resolve its own top to the instantiation-graph root and look up a
    differently-named sidecar. A refusal filed under one name and looked up
    under another is a refusal nobody makes — the step ran yosys anyway and
    the abort came back as a synthesis failure, which is the whole defect.

    So the reader takes EVERY sidecar in rtl/, and the control below is the
    half that must stay silent.
    """
    sidecar = ('{"resolved": {}, "refusals": [{"parameter": "SecSBoxImpl",'
               ' "reason": "UNDECLARED_FREE_CHOICE",'
               ' "message": "DECLARE SecSBoxImpl in the design input."}]}')
    for name in (".chip_top__param_resolution.json",
                 ".thing_top__param_resolution.json"):
        root, rtl = _project()
        (rtl / name).write_text(sidecar)
        res = D.step_yosys_synth(root, "chip_top", container="no-such-container")
        assert res.status == "FAIL"
        assert "PARAMETER UNRESOLVED (SecSBoxImpl)" in res.detail
        assert "before yosys" in res.detail
        shutil.rmtree(root, ignore_errors=True)
    # CONTROL — no sidecar, no refusal. The step fails for its own reasons and
    # says nothing about a parameter.
    root, rtl = _project()
    res = D.step_yosys_synth(root, "chip_top", container="no-such-container")
    assert "PARAMETER UNRESOLVED" not in (res.detail or "")
    shutil.rmtree(root, ignore_errors=True)
