"""Unit tests for `phase1_post_process.py`."""
import importlib
import json

import pytest

from _shipped_version import shipped_plugin_version  # noqa: E402  (#800)
mod = importlib.import_module("phase1_post_process")


class TestHallucScrub:
    def test_arm_license_clause_scrubbed(self):
        doc = {"ic_name": "SUCH ARM TECHNOLOGY", "fields": {"x": 1}}
        log = mod.scrub_l_doc(doc, "L1_DATASHEET")
        assert len(log) == 1
        assert doc["ic_name"] == "UNKNOWN_IC"
        assert "license clause" in log[0].why

    def test_use_or_implementation_scrubbed(self):
        doc = {"ic_name": "USE OR IMPLEMENTATION OF SOMETHING"}
        log = mod.scrub_l_doc(doc, "L1_DATASHEET")
        assert doc["ic_name"] == "UNKNOWN_IC"
        assert any("license" in s.why.lower() for s in log)

    def test_legitimate_ic_name_not_scrubbed(self):
        doc = {"ic_name": "AMBA AXI Protocol Specification"}
        log = mod.scrub_l_doc(doc, "L1_DATASHEET")
        assert log == []
        assert doc["ic_name"] == "AMBA AXI Protocol Specification"

    # #454 follow-up — the hard-coded hex VALUE blocklist is GONE. It used
    # to delete `0x16 / 0x17 / 0x23 / 0x24 / 0x47 / 0x48 / 0x55 / 0x56` out
    # of ANY design's command table because a bus-figure bit-position axis
    # had once been scraped at those offsets. A named command carrying one
    # of those encodings is ordinary, and the artefact is now refused at
    # source on the row's SHAPE
    # (`phase1_doc_one_shot_runner._i454_bit_position_ruler_row`).
    @pytest.mark.parametrize("hex_value", [
        "0x16", "0x17", "0x23", "0x24", "0x47", "0x48", "0x55", "0x56",
    ])
    def test_named_command_at_a_formerly_blocklisted_encoding_survives(
            self, hex_value):
        doc = {"opcodes": [{"hex": hex_value, "name": "VOUT_MAX"}],
               "no_opcodes_in_input": False,
               "placeholder_opcode_count": 0}
        log = mod.scrub_l_doc(doc, "L3_CMD_PROTOCOL")
        assert log == [], f"{hex_value} was scrubbed: {log}"
        assert doc["opcodes"] == [{"hex": hex_value, "name": "VOUT_MAX"}]
        assert doc["no_opcodes_in_input"] is False

    def test_no_scrub_pattern_keys_on_a_list_of_encodings(self):
        """A scrub pattern may key on a value that is never legitimate for
        the field. It may NOT key on an alternation of hex encodings: an
        encoding is data, and the same encoding is genuine in the next
        design. This is the invariant the removed blocklist violated."""
        for pat in mod.HALLUC_PATTERNS:
            src = pat.value_pattern.pattern
            assert "0x" not in src.lower(), (
                f"scrub pattern {pat.name!r} keys on hex encodings "
                f"({src!r}); an encoding blocklist deletes genuine data. "
                "Refuse the row at source on its shape instead.")

    def test_refusal_audit_trail_is_not_overwritten_by_a_scrub(self):
        """The emitter's honest-uncertainty record carries a bare `hex`
        leaf. The removed blocklist matched the bare key `hex` ANYWHERE in
        the document, so it overwrote the very audit trail that records why
        a row was refused. Nothing may do that."""
        doc = {
            "opcodes": [],
            "no_opcodes_in_input": True,
            "non_command_row_refusal_count": 3,
            "non_command_row_refusals": [
                {"hex": "0x17", "reason": "signal_name_notation"},
                {"hex": "0x23", "reason": "signal_name_notation"},
                {"hex": "0x24", "reason": "bit_position_ruler_row"},
            ],
        }
        log = mod.scrub_l_doc(doc, "L3_CMD_PROTOCOL")
        assert log == []
        assert [r["hex"] for r in doc["non_command_row_refusals"]] == [
            "0x17", "0x23", "0x24"]

    def test_legitimate_opcode_not_scrubbed(self):
        doc = {"opcodes": [{"hex": "0xAB", "name": "WRITE_REG"}]}
        log = mod.scrub_l_doc(doc, "L3_CMD_PROTOCOL")
        assert log == []
        assert doc["opcodes"][0]["hex"] == "0xAB"

    def test_drop_scrubbed_opcode_zombie_recomputes_flags(self):
        # The zombie drop is sentinel-driven and stays general: an entry
        # whose `hex` is the scrub sentinel carries no encoding, so it must
        # leave `opcodes` and the sibling flags must be recomputed.
        # (Driven through the sentinel directly — #454 follow-up removed the
        # hex-value blocklist that used to produce it.)
        doc = {
            "opcodes": [{"hex": "<HALLUCINATION_SCRUBBED>",
                         "name": "OPCODE_NAME_UNKNOWN"},
                        {"hex": "<HALLUCINATION_SCRUBBED>",
                         "name": "OPCODE_NAME_UNKNOWN"}],
            "no_opcodes_in_input": False,
            "placeholder_opcode_count": 2,
            "no_opcode_names_in_input": True,
        }
        mod.scrub_l_doc(doc, "L3_CMD_PROTOCOL")
        assert doc["opcodes"] == []
        assert doc["no_opcodes_in_input"] is True
        assert doc["placeholder_opcode_count"] == 0
        assert doc["no_opcode_names_in_input"] is False

    def test_drop_scrubbed_keeps_real_opcodes(self):
        # Mixed list: one real opcode + one scrubbed zombie. Only the
        # zombie is dropped; the real opcode and its flags survive.
        doc = {
            "opcodes": [{"hex": "0xAB", "name": "WRITE_REG"},
                        {"hex": "<HALLUCINATION_SCRUBBED>", "name": "OPCODE_NAME_UNKNOWN"}],
            "no_opcodes_in_input": False,
            "placeholder_opcode_count": 1,
        }
        mod.scrub_l_doc(doc, "L3_CMD_PROTOCOL")
        assert len(doc["opcodes"]) == 1
        assert doc["opcodes"][0]["name"] == "WRITE_REG"
        assert doc["no_opcodes_in_input"] is False
        assert doc["placeholder_opcode_count"] == 0

    def test_scrub_log_records_provenance(self):
        doc = {"ic_name": "SUCH ARM TECHNOLOGY"}
        log = mod.scrub_l_doc(doc, "L1_DATASHEET")
        entry = log[0]
        assert entry.l_doc == "L1_DATASHEET"
        assert entry.old_value == "SUCH ARM TECHNOLOGY"
        assert entry.new_value == "UNKNOWN_IC"

    def test_nested_doc_scrubbed(self):
        doc = {"meta": {"summary": {"ic_name": "SUCH ARM TECHNOLOGY"}}}
        log = mod.scrub_l_doc(doc, "L1_DATASHEET")
        assert doc["meta"]["summary"]["ic_name"] == "UNKNOWN_IC"
        assert len(log) == 1


class TestSkeletonEmission:
    def test_l14_skeleton_has_versions_bucket(self):
        sk = mod.emit_l_doc_skeleton("L14", "bus_interconnect_protocol")
        assert sk["doc_id"] == "L14"
        assert "versions" in sk["fields"]
        assert sk["fields"]["versions"] == []

    def test_l15_skeleton_has_tables_bucket(self):
        sk = mod.emit_l_doc_skeleton("L15", "bus_interconnect_protocol")
        assert sk["fields"]["tables"] == []

    def test_l17_skeleton_has_channels(self):
        sk = mod.emit_l_doc_skeleton("L17", "bus_interconnect_protocol")
        assert "channels" in sk["fields"]
        assert "dependency_graph" in sk["fields"]

    def test_l19_skeleton_has_pdk_target(self):
        sk = mod.emit_l_doc_skeleton("L19", "chip_otp_centric")
        assert "pdk_target" in sk["fields"]

    def test_l21_skeleton_has_power_domains(self):
        sk = mod.emit_l_doc_skeleton("L21", "chip_otp_centric")
        assert "power_domains" in sk["fields"]

    def test_l23_skeleton_has_attack_surface(self):
        sk = mod.emit_l_doc_skeleton("L23", "cpu_core_isa")
        assert "attack_surface" in sk["fields"]

    def test_extraction_status_not_yet_extracted(self):
        sk = mod.emit_l_doc_skeleton("L14", "bus_interconnect_protocol")
        assert sk["extraction_status"] == "NOT_YET_EXTRACTED"

    def test_extraction_hints_not_empty(self):
        for code in ("L14", "L15", "L16", "L17", "L18",
                     "L19", "L20", "L21", "L22", "L23"):
            sk = mod.emit_l_doc_skeleton(code, "chip_otp_centric")
            assert len(sk["extraction_hints"]) > 0

    def test_skeleton_attribution(self):
        sk = mod.emit_l_doc_skeleton("L14", "bus_interconnect_protocol")
        assert sk["emitted_by"] == (
            "phase1_post_process.emit_l_doc_skeleton "
            f"v{shipped_plugin_version()}")


class TestPostProcessIntegration:
    def _setup_project(self, tmp_path):
        """Create a phase1/generated_docs/ with one hallucinated L1
        and an existing L11 (which is N/A for bus protocol)."""
        docs = tmp_path / "phase1" / "generated_docs"
        docs.mkdir(parents=True)
        (docs / "L1_DATASHEET.json").write_text(json.dumps({
            "ic_name": "SUCH ARM TECHNOLOGY",
            "fields": {"meaningful": True},
        }))
        (docs / "L11_OTP_CONTENT.json").write_text(json.dumps({
            "fields": {"fuse_count": 999},
        }))
        return tmp_path

    def test_scrubs_l1_keeps_other_content(self, tmp_path):
        proj = self._setup_project(tmp_path)
        rep = mod.post_process(proj, "bus_interconnect_protocol")
        # Scrubbed
        assert rep.scrubbed_count >= 1
        # L1 content survived except the scrubbed ic_name
        l1 = json.loads((proj / "phase1/generated_docs/L1_DATASHEET.json")
                          .read_text())
        assert l1["ic_name"] == "UNKNOWN_IC"
        assert l1["fields"]["meaningful"] is True

    def test_na_stub_for_l11_on_bus_protocol(self, tmp_path):
        proj = self._setup_project(tmp_path)
        rep = mod.post_process(proj, "bus_interconnect_protocol")
        l11 = json.loads((proj / "phase1/generated_docs/L11_OTP_CONTENT.json")
                          .read_text())
        assert l11["applicability"] == "N/A"
        assert "OTP" in l11["rationale"]
        assert "L11" in rep.na_stubs_emitted

    def test_skeleton_emitted_for_l14_on_bus_protocol(self, tmp_path):
        proj = self._setup_project(tmp_path)
        rep = mod.post_process(proj, "bus_interconnect_protocol")
        l14 = json.loads(
            (proj / "phase1/generated_docs/L14_PROTOCOL_VERSIONING.json")
            .read_text())
        assert l14["applicability"] == "APPLICABLE"
        assert l14["extraction_status"] == "NOT_YET_EXTRACTED"
        assert "L14" in rep.skeleton_emitted

    def test_legitimate_l11_preserved_on_otp_chip(self, tmp_path):
        # For chip_otp_centric, L11 IS applicable — pre-existing content
        # must be preserved (and scrubbed only if it matches a halluc
        # pattern, which a fuse_count integer does not).
        proj = self._setup_project(tmp_path)
        rep = mod.post_process(proj, "chip_otp_centric")
        l11 = json.loads((proj / "phase1/generated_docs/L11_OTP_CONTENT.json")
                          .read_text())
        # NOT an na_stub — original content survives
        assert l11.get("applicability") != "N/A"
        assert l11["fields"]["fuse_count"] == 999

    def test_verdict_warn_when_scrubbed(self, tmp_path):
        proj = self._setup_project(tmp_path)
        rep = mod.post_process(proj, "bus_interconnect_protocol")
        assert rep.verdict == "WARN"

    def test_verdict_pass_when_clean(self, tmp_path):
        proj = tmp_path
        (proj / "phase1" / "generated_docs").mkdir(parents=True)
        (proj / "phase1" / "generated_docs" / "L1_DATASHEET.json"
            ).write_text(json.dumps({"ic_name": "real_chip_name"}))
        rep = mod.post_process(proj, "chip_otp_centric")
        # No hallucinations, applicable everywhere → PASS
        assert rep.verdict == "PASS"


class TestDoctrineCompliance:
    def test_scrub_log_attributes_pattern_name(self):
        doc = {"ic_name": "SUCH ARM TECHNOLOGY"}
        log = mod.scrub_l_doc(doc, "L1_DATASHEET")
        assert log[0].pattern_name == "ic_name_from_license_clause"

    def test_scrub_is_idempotent(self):
        doc = {"ic_name": "SUCH ARM TECHNOLOGY"}
        log1 = mod.scrub_l_doc(doc, "L1_DATASHEET")
        log2 = mod.scrub_l_doc(doc, "L1_DATASHEET")
        # First call scrubs; second call finds nothing to scrub
        assert len(log1) == 1
        assert len(log2) == 0
        assert doc["ic_name"] == "UNKNOWN_IC"

    def test_post_process_result_dict_carries_emitted_by(self):
        rep = mod.PostProcessResult(
            project_dir="/x", ic_class="cpu_core_isa",
            scrubbed_count=0, scrub_log=[], skeleton_emitted=[],
            na_stubs_emitted=[], verdict="PASS")
        d = rep.as_dict()
        assert d["emitted_by"] == \
            f"phase1_post_process v{shipped_plugin_version()}"


class TestL19StagedSdcPath:
    """stamp2 / l_doc_field_producer_check — `sdc_constraints_path` was a key
    the skeleton emitter wrote and nothing ever populated, while the staged
    ground truth (`sdc_constraints.collect_sdc_files`) was already on disk at
    emit time. The producer now records the design's OWN staged file; it
    still never invents one."""

    def _proj(self, tmp_path, *rel_sdcs):
        proj = tmp_path / "proj"
        for rel in rel_sdcs:
            f = proj / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("create_clock -name clk -period 10 [get_ports clk]\n")
        proj.mkdir(parents=True, exist_ok=True)
        return proj

    def test_staged_sdc_is_recorded_project_relative(self, tmp_path):
        proj = self._proj(tmp_path, "input/constraints/design.sdc")
        sk = mod.emit_l_doc_skeleton("L19", "unknown", project_dir=proj)
        assert sk["fields"]["sdc_constraints_path"] == \
            "input/constraints/design.sdc"
        # The produced value must be resolvable exactly the way the L19-4
        # advisory resolves it — `project / path` exists.
        assert (proj / sk["fields"]["sdc_constraints_path"]).is_file()

    def test_no_staged_sdc_keeps_the_honest_null(self, tmp_path):
        proj = self._proj(tmp_path)
        sk = mod.emit_l_doc_skeleton("L19", "unknown", project_dir=proj)
        assert sk["fields"]["sdc_constraints_path"] is None

    def test_priority_order_matches_the_consumer(self, tmp_path):
        # input/constraints/ outranks input/reference_flow/ — the same
        # order `sdc_constraints.collect_sdc_files` hands phase3 synth.
        proj = self._proj(tmp_path,
                          "input/reference_flow/ref.sdc",
                          "input/constraints/design.sdc")
        sk = mod.emit_l_doc_skeleton("L19", "unknown", project_dir=proj)
        assert sk["fields"]["sdc_constraints_path"] == \
            "input/constraints/design.sdc"

    def test_no_project_dir_is_unchanged(self):
        sk = mod.emit_l_doc_skeleton("L19", "unknown")
        assert sk["fields"]["sdc_constraints_path"] is None
