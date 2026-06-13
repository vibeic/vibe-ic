"""Unit tests for `lvs_netgen_setup_emit.py`.

Pin the deterministic shape of the supplementary Netgen LVS setup TCL
so any regression on rules 1-5 is caught by pytest, not by re-running
a full silicon LVS sign-off.

Each test is a single fact about the emitter; together they fix the
contract surfaced by the spm pilot Tier 4.5 closure work.
"""
import importlib

import pytest

mod = importlib.import_module("lvs_netgen_setup_emit")


class TestPdkNormalize:
    def test_sky130_canonical(self):
        assert mod._normalize_pdk("sky130A") == "sky130A"

    def test_sky130_lowercase(self):
        assert mod._normalize_pdk("sky130a") == "sky130A"

    def test_sky130_loose(self):
        assert mod._normalize_pdk("sky130") == "sky130A"

    def test_skywater_alias(self):
        assert mod._normalize_pdk("SkyWater") == "sky130A"

    def test_gf180_c(self):
        assert mod._normalize_pdk("gf180mcuC") == "gf180mcuC"

    def test_gf180_d(self):
        assert mod._normalize_pdk("gf180mcuD") == "gf180mcuD"

    def test_gf180_short(self):
        assert mod._normalize_pdk("gf180") == "gf180mcuC"

    def test_unknown_returns_empty(self):
        assert mod._normalize_pdk("intel18A") == ""

    def test_empty_input(self):
        assert mod._normalize_pdk("") == ""
        assert mod._normalize_pdk(None) == ""


class TestRule1GlobalPowerNets:
    def test_sky130_has_vccd1_vssd1(self):
        tcl = mod.build_supplementary_setup_tcl("sky130A")
        assert "global vccd1" in tcl
        assert "global vssd1" in tcl

    def test_sky130_has_VPWR_VGND_VPB_VNB(self):
        # Std-cell Liberty convention pin names — these are the ones that
        # Magic ext2spice surfaces per-cell flat unless globalised.
        tcl = mod.build_supplementary_setup_tcl("sky130A")
        for name in ("VPWR", "VGND", "VPB", "VNB"):
            assert f"global {name}" in tcl, f"missing global {name}"

    def test_sky130_has_analog_and_io_domains(self):
        tcl = mod.build_supplementary_setup_tcl("sky130A")
        for name in ("vdda1", "vssa1", "vddio", "vssio"):
            assert f"global {name}" in tcl

    def test_gf180_single_domain(self):
        tcl = mod.build_supplementary_setup_tcl("gf180mcuC")
        for name in ("VDD", "VSS", "VPWR", "VGND"):
            assert f"global {name}" in tcl
        # gf180 should NOT carry sky130-specific net names
        assert "global vccd1" not in tcl

    def test_extra_power_nets_appended(self):
        opts = mod.LvsSetupOptions(extra_power_nets=["VBN_REF", "VBP_REF"])
        tcl = mod.build_supplementary_setup_tcl("sky130A", opts)
        assert "global VBN_REF" in tcl
        assert "global VBP_REF" in tcl

    def test_extra_power_nets_deduped_with_defaults(self):
        # Asking for VPWR (already in defaults) must not double-emit.
        opts = mod.LvsSetupOptions(extra_power_nets=["VPWR"])
        tcl = mod.build_supplementary_setup_tcl("sky130A", opts)
        assert tcl.count("global VPWR") == 1


class TestRule2StdcellEquate:
    def test_default_emits_audit_comment_not_explicit_equate(self):
        # The foundry setup already does the wildcard equate; we must
        # NOT re-emit `equate classes ...` (which would cause Netgen
        # to warn about duplicate definitions).
        tcl = mod.build_supplementary_setup_tcl("sky130A")
        assert "equate classes" not in tcl
        # but we DO leave an audit comment so a reviewer sees the
        # rule was considered
        assert "foundry sky130A_setup.tcl wildcard" in tcl

    def test_opt_out_still_emits_comment(self):
        opts = mod.LvsSetupOptions(equate_stdcell_lib_to_short_name=False)
        tcl = mod.build_supplementary_setup_tcl("sky130A", opts)
        assert "trust the foundry setup" in tcl
        # still no explicit equate
        assert "equate classes" not in tcl


class TestRule3MosPermute:
    def test_no_duplicate_permute_default(self):
        # Foundry setup already has `permute default`; we never re-emit
        # one (it'd be a no-op but a noisy one in the log).
        tcl = mod.build_supplementary_setup_tcl("sky130A")
        assert "permute default" not in tcl


class TestRule4FlattenDirectives:
    def test_default_does_not_emit_flatten(self):
        tcl = mod.build_supplementary_setup_tcl("sky130A")
        assert "flatten class" not in tcl

    def test_opt_in_emits_both_sides(self):
        opts = mod.LvsSetupOptions(
            flatten_top_circuits=("chip_top", "chip_top"))
        tcl = mod.build_supplementary_setup_tcl("sky130A", opts)
        assert "flatten class \"-circuit1 chip_top\"" in tcl
        assert "flatten class \"-circuit2 chip_top\"" in tcl

    def test_opt_in_different_names_on_each_side(self):
        # Magic ext2spice top circuit and Yosys flatten top can differ.
        opts = mod.LvsSetupOptions(
            flatten_top_circuits=("user_project_wrapper", "wrapper_top"))
        tcl = mod.build_supplementary_setup_tcl("sky130A", opts)
        assert "circuit1 user_project_wrapper" in tcl
        assert "circuit2 wrapper_top" in tcl

    def test_half_pair_emits_no_flatten(self):
        # Either both sides specified or neither — avoid asymmetric flatten.
        opts = mod.LvsSetupOptions(flatten_top_circuits=("chip_top", ""))
        tcl = mod.build_supplementary_setup_tcl("sky130A", opts)
        assert "flatten class" not in tcl


class TestRule5TapFillIgnoreComment:
    def test_audit_comment_about_magic_ext_use_gds(self):
        # We rely on foundry setup's MAGIC_EXT_USE_GDS-gated `ignore
        # class` for tap/fill/decap. Surface that as an audit-trail
        # comment so a future debugger knows to set the env var.
        tcl = mod.build_supplementary_setup_tcl("sky130A")
        assert "MAGIC_EXT_USE_GDS" in tcl


class TestAuditComments:
    def test_off_by_default(self):
        tcl = mod.build_supplementary_setup_tcl("sky130A")
        assert "LVS_SETUP_APPLIED" not in tcl

    def test_on_when_requested(self):
        opts = mod.LvsSetupOptions(audit_comments=True)
        tcl = mod.build_supplementary_setup_tcl("sky130A", opts)
        assert "LVS_SETUP_APPLIED" in tcl

    def test_audit_count_matches_globals(self):
        opts = mod.LvsSetupOptions(audit_comments=True)
        tcl = mod.build_supplementary_setup_tcl("sky130A", opts)
        # The audit comment surfaces a count = len(default_power_nets)
        # for sky130A (14 names).
        assert "14 global" in tcl

    def test_flatten_audit_surfaces_top_names(self):
        opts = mod.LvsSetupOptions(
            flatten_top_circuits=("chip_top", "chip_top"),
            audit_comments=True)
        tcl = mod.build_supplementary_setup_tcl("sky130A", opts)
        assert "LVS_SETUP_APPLIED: flatten chip_top/chip_top" in tcl


class TestUnknownPdk:
    def test_unknown_emits_skipped_with_pdk_name(self):
        tcl = mod.build_supplementary_setup_tcl("intel18A")
        assert "LVS_SETUP_SKIPPED" in tcl
        assert "intel18A" in tcl
        # MUST NOT silently emit a half-config that looks like sky130
        assert "global vccd1" not in tcl

    def test_unknown_does_not_emit_global_directives(self):
        tcl = mod.build_supplementary_setup_tcl("foundry-x-72nm")
        assert "global " not in tcl  # no `global VPWR` etc.
        # But the header comment is still emitted so the file is
        # syntactically valid Tcl that does nothing.
        assert "#---" in tcl


class TestEmitterShape:
    def test_returns_non_empty_string(self):
        assert mod.build_supplementary_setup_tcl("sky130A").strip()

    def test_starts_with_comment_block(self):
        tcl = mod.build_supplementary_setup_tcl("sky130A")
        assert tcl.lstrip().startswith("#---")

    def test_attributes_to_program(self):
        # Future debugger needs to know where this file came from.
        tcl = mod.build_supplementary_setup_tcl("sky130A")
        assert "lvs_netgen_setup_emit.py" in tcl

    def test_references_pilot_writeup(self):
        # Cross-link to the empirical evidence file.
        tcl = mod.build_supplementary_setup_tcl("sky130A")
        assert "RESULT_tier4_5_lvs_attempts.md" in tcl
