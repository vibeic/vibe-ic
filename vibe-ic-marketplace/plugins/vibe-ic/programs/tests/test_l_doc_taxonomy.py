"""Unit tests for `l_doc_taxonomy.py`."""
import importlib

import pytest

mod = importlib.import_module("l_doc_taxonomy")


class TestTaxonomyShape:
    def test_v1_has_14_entries(self):
        # L1..L13 + the L8 split (L8C + L8T) = 14
        assert len(mod.L_DOCS_V1) == 14

    def test_v2_protocol_ext_is_5(self):
        assert len(mod.L_DOCS_V2_PROTOCOL_EXT) == 5

    def test_v2_flow_ext_is_5(self):
        assert len(mod.L_DOCS_V2_FLOW_EXT) == 5

    def test_v2_completeness_ext_is_4(self):
        # #157 — L24-L27 completeness extensions
        assert len(mod.L_DOCS_V2_COMPLETENESS_EXT) == 4

    def test_v2_total_is_28(self):
        # v1 (14) + protocol ext (5) + flow ext (5) + completeness ext (4) = 28
        assert len(mod.L_DOCS_V2) == 14 + 5 + 5 + 4

    def test_codes_unique(self):
        codes = [s.code for s in mod.L_DOCS_V2]
        assert len(codes) == len(set(codes))

    def test_full_names_unique(self):
        names = [s.full_name for s in mod.L_DOCS_V2]
        assert len(names) == len(set(names))

    def test_l14_through_l18_present(self):
        codes = {s.code for s in mod.L_DOCS_V2}
        for c in ("L14", "L15", "L16", "L17", "L18"):
            assert c in codes

    def test_l19_through_l23_present(self):
        codes = {s.code for s in mod.L_DOCS_V2}
        for c in ("L19", "L20", "L21", "L22", "L23"):
            assert c in codes


class TestLookup:
    def test_by_code(self):
        s = mod.l_doc_spec("L1")
        assert s.full_name == "L1_DATASHEET"

    def test_by_full_name(self):
        s = mod.l_doc_spec("L1_DATASHEET")
        assert s.code == "L1"

    def test_l19_constraints_pdk(self):
        s = mod.l_doc_spec("L19")
        assert "PDK" in s.title or "Constraints" in s.title

    def test_l20_dft(self):
        s = mod.l_doc_spec("L20")
        assert "DFT" in s.title

    def test_l21_power(self):
        s = mod.l_doc_spec("L21")
        assert "Power" in s.title

    def test_unknown_raises(self):
        with pytest.raises(KeyError):
            mod.l_doc_spec("L99_UNKNOWN")


class TestApplicability:
    def test_bus_protocol_includes_l17(self):
        applicable = mod.applicable_l_docs("bus_interconnect_protocol")
        assert "L17" in applicable
        assert "L18" in applicable

    def test_bus_protocol_includes_l19_constraints(self):
        # Even bus protocols need PDK / floorplan constraints when impl'd
        assert "L19" in mod.applicable_l_docs("bus_interconnect_protocol")

    def test_bus_protocol_excludes_otp_and_analog(self):
        na = mod.not_applicable_l_docs("bus_interconnect_protocol")
        assert "L11" in na  # no OTP
        assert "L5" in na   # no analog
        assert "L13" in na  # no lab cal
        assert "L20" in na  # DFT is per-impl, not protocol-level
        assert "L21" in na  # power intent is per-impl

    def test_chip_otp_excludes_protocol_categories(self):
        na = mod.not_applicable_l_docs("chip_otp_centric")
        for c in ("L14", "L15", "L16", "L17", "L18"):
            assert c in na

    def test_chip_otp_includes_flow_categories(self):
        # Even an OTP chip needs PDK constraints + DFT + power
        a = mod.applicable_l_docs("chip_otp_centric")
        for c in ("L19", "L20", "L21", "L22"):
            assert c in a

    def test_unknown_ic_class_returns_all_except_opt_in(self):
        # #157 — the unknown/fallback applicable set is every code EXCEPT the
        # opt-in-only completeness codes (L26/L27), so a generic chip never
        # emits an empty MEMS / memory-module skeleton.
        applicable = mod.applicable_l_docs("unknown")
        assert applicable == set(mod.all_l_doc_codes()) - {"L26", "L27"}
        assert "L24" in applicable and "L25" in applicable
        assert "L26" not in applicable and "L27" not in applicable

    def test_cpu_includes_l15(self):
        # ISA opcodes go in L15
        assert "L15" in mod.applicable_l_docs("cpu_core_isa")

    def test_cpu_includes_l23_security(self):
        # CPUs are security-relevant
        assert "L23" in mod.applicable_l_docs("cpu_core_isa")

    def test_cpu_excludes_l17_bus_catalog(self):
        # CPUs don't have multi-channel external buses
        assert "L17" in mod.not_applicable_l_docs("cpu_core_isa")

    def test_analog_excludes_flow_categories(self):
        # Most flow categories don't apply to a pure analog block
        na = mod.not_applicable_l_docs("analog_block")
        assert "L20" in na  # no scan
        assert "L22" in na  # no vplan; uses L13 lab cal
        assert "L23" in na


class TestIsApplicable:
    def test_bus_l17_yes(self):
        assert mod.is_applicable("bus_interconnect_protocol", "L17")

    def test_bus_l11_no(self):
        assert not mod.is_applicable("bus_interconnect_protocol", "L11")

    def test_chip_l20_yes(self):
        # OTP chip → DFT applies
        assert mod.is_applicable("chip_otp_centric", "L20")

    def test_lookup_by_full_name(self):
        assert mod.is_applicable("bus_interconnect_protocol",
                                   "L17_CHANNEL_SIGNAL_CATALOG")

    def test_unknown_l_doc_raises(self):
        with pytest.raises(KeyError):
            mod.is_applicable("bus_interconnect_protocol", "L99")

    def test_unknown_ic_class_is_applicable_all_except_opt_in(self):
        # #157 — unknown is applicable for every code EXCEPT the opt-in-only
        # codes L26/L27.
        for code in mod.all_l_doc_codes():
            if code in ("L26", "L27"):
                assert not mod.is_applicable("unknown", code)
            else:
                assert mod.is_applicable("unknown", code)


class TestNaStub:
    def test_bus_l11_stub_contains_rationale(self):
        stub = mod.na_stub("bus_interconnect_protocol", "L11")
        assert stub["applicability"] == "N/A"
        assert stub["doc_id"] == "L11"
        assert "OTP" in stub["rationale"]

    def test_bus_l5_stub_mentions_analog(self):
        stub = mod.na_stub("bus_interconnect_protocol", "L5")
        assert "analog" in stub["rationale"].lower()

    def test_bus_l20_stub_mentions_implementation(self):
        # DFT scan is per-implementation, not protocol-level
        stub = mod.na_stub("bus_interconnect_protocol", "L20")
        assert "implementation" in stub["rationale"].lower() \
            or "impl" in stub["rationale"].lower()

    def test_stub_surfaces_ic_class(self):
        stub = mod.na_stub("bus_interconnect_protocol", "L11")
        assert stub["ic_class"] == "bus_interconnect_protocol"

    def test_stub_attributes_to_program(self):
        stub = mod.na_stub("bus_interconnect_protocol", "L11")
        # Version-agnostic: pin the program ATTRIBUTION, not a frozen version
        # string (the emitter bumps versions — e.g. v0.1.51 -> v0.2.14 when the
        # stub gained extraction_evidence:{} for the Wave-23 schema gate).
        assert "l_doc_taxonomy.na_stub" in stub["emitted_by"]

    def test_stub_carries_extraction_evidence(self):
        # v0.2.14: an N/A stub must carry a schema-valid (empty-dict-allowed)
        # extraction_evidence so extraction_evidence_schema_check does not
        # false-FAIL it as "field missing".
        stub = mod.na_stub("bus_interconnect_protocol", "L11")
        assert "extraction_evidence" in stub
        assert stub["extraction_evidence"] == {}

    def test_stub_for_unrecognised_ic_class_has_fallback_rationale(self):
        # Even for an unknown ic_class, na_stub must NOT crash —
        # return a generic rationale.
        stub = mod.na_stub("never-seen-class", "L11")
        assert stub["applicability"] == "N/A"
        assert stub["rationale"]


class TestApiSurface:
    def test_all_l_doc_codes_ordered(self):
        codes = mod.all_l_doc_codes()
        # L1 must come first, L27 last (#157 folded L24-L27 at the end)
        assert codes[0] == "L1"
        assert codes[-1] == "L27"

    def test_all_l_doc_full_names_match_codes(self):
        codes = mod.all_l_doc_codes()
        names = mod.all_l_doc_full_names()
        assert len(codes) == len(names)
        # Each pair must agree under lookup
        for c, n in zip(codes, names):
            assert mod.l_doc_spec(c).full_name == n


class TestIcClassCoverage:
    def test_every_ic_class_has_disjoint_applicable_and_not_applicable(self):
        for cls, entry in mod.IC_CLASS_APPLICABILITY.items():
            a = set(entry["applicable"])
            n = set(entry["not_applicable"])
            assert not (a & n), f"{cls}: overlap {a & n}"

    def test_every_ic_class_covers_l1_through_l23(self):
        all_codes = set(mod.all_l_doc_codes())
        for cls, entry in mod.IC_CLASS_APPLICABILITY.items():
            covered = set(entry["applicable"]) | set(entry["not_applicable"])
            missing = all_codes - covered
            assert not missing, f"{cls}: missing {missing}"

    def test_every_not_applicable_has_rationale(self):
        for cls, entry in mod.IC_CLASS_APPLICABILITY.items():
            rats = entry.get("rationale_not_applicable", {})
            for c in entry["not_applicable"]:
                assert c in rats, f"{cls}: no rationale for {c}"


# ---------------------------------------------------------------------------
# SoC multi-block support
# ---------------------------------------------------------------------------
class TestSoCComposition:
    def test_soc_top_level_includes_integration_and_power(self):
        a = mod.applicable_l_docs("soc_multi_block")
        # SoC top-level cares about die-scope integration + power intent +
        # verification plan
        for c in ("L1", "L9", "L18", "L21", "L22"):
            assert c in a

    def test_soc_excludes_per_sub_block_categories(self):
        # L3 (cmd protocol) is per-sub-block, not top-level
        na = mod.not_applicable_l_docs("soc_multi_block")
        assert "L3" in na
        assert "L5" in na  # analog is per-sub-block
        assert "L15" in na  # encoding tables per-sub-block

    def test_soc_applicable_per_sub_block(self):
        sub_blocks = [
            mod.SubBlock(block_name="cpu", ic_class="cpu_core_isa"),
            mod.SubBlock(block_name="ddr_ctrl", ic_class="memory_controller"),
            mod.SubBlock(block_name="ldo", ic_class="analog_block"),
        ]
        per_sb = mod.soc_applicable_per_sub_block(sub_blocks)
        # CPU sub-block applies L15
        assert "L15" in per_sb["cpu"]
        # LDO sub-block applies L5 (analog)
        assert "L5" in per_sb["ldo"]
        # DDR sub-block applies L17 (channel catalog)
        assert "L17" in per_sb["ddr_ctrl"]

    def test_soc_union_covers_each_sub_block(self):
        sub_blocks = [
            mod.SubBlock(block_name="cpu", ic_class="cpu_core_isa"),
            mod.SubBlock(block_name="ldo", ic_class="analog_block"),
        ]
        union = mod.soc_union_applicable(sub_blocks)
        # Union includes BOTH cpu-specific (L15) and analog-specific (L5)
        assert "L15" in union
        assert "L5" in union
        # And the SoC top-level entries
        assert "L9" in union

    def test_sub_block_as_dict_has_expected_keys(self):
        sb = mod.SubBlock(block_name="cpu", ic_class="cpu_core_isa")
        d = sb.as_dict()
        assert d["block_name"] == "cpu"
        assert d["ic_class"] == "cpu_core_isa"
        assert d["instances"] == 1

    def test_sub_block_instances_field(self):
        sb = mod.SubBlock(block_name="quad_cpu", ic_class="cpu_core_isa",
                            instances=4)
        assert sb.instances == 4


class TestDoctrineCompliance:
    def test_pure_module_no_io(self):
        # taxonomy lookup never touches the filesystem
        for c in mod.all_l_doc_codes():
            mod.l_doc_spec(c)

    def test_deterministic_repeat(self):
        for _ in range(5):
            assert mod.applicable_l_docs("bus_interconnect_protocol") \
                == mod.applicable_l_docs("bus_interconnect_protocol")

    def test_soc_composition_is_deterministic(self):
        sb1 = mod.SubBlock(block_name="cpu", ic_class="cpu_core_isa")
        sb2 = mod.SubBlock(block_name="cpu", ic_class="cpu_core_isa")
        # Same sub-blocks → same union
        assert mod.soc_union_applicable([sb1]) == mod.soc_union_applicable([sb2])
