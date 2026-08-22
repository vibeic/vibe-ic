"""Unit tests for `phase1_protocol_spec_extract.py`."""
import importlib
import json

from _shipped_version import shipped_plugin_version  # noqa: E402  (#800)
mod = importlib.import_module("phase1_protocol_spec_extract")


class TestL14Versioning:
    def test_amba_axi_version_history_rows(self):
        text = (
            "    Release Information\n"
            "\n"
            "        16 June 2003       A     Non-Confidential   First release\n"
            "        19 March 2004      B     Non-Confidential   First release of AXI specification v1.0\n"
            "        28 October 2011    D     Non-Confidential   First release of AMBA AXI and ACE Protocol Specification\n"
            "        21 December 2017   F.b   Non-Confidential   EAC-1 release\n"
        )
        out = mod.extract_l14_versioning(text)
        assert out["extraction_status"] == "EXTRACTED"
        v = out["fields"]["versions"]
        assert len(v) == 4
        assert v[0]["issue"] == "A"
        assert v[-1]["issue"] == "F.b"

    def test_no_version_rows_returns_nothing(self):
        out = mod.extract_l14_versioning("Just prose, no version table.")
        assert out["extraction_status"] == "EXTRACTION_FOUND_NOTHING"
        assert out["fields"]["versions"] == []

    def test_deprecated_feature_captured(self):
        text = ("WID is deprecated in AXI4. The feature is no longer "
                 "supported beyond version C.\n")
        out = mod.extract_l14_versioning(text)
        deps = out["fields"]["deprecated_features"]
        assert any(d["feature"].lower() == "wid" for d in deps)


class TestL15EncodingTables:
    def test_amba_axi_table_header_captured(self):
        text = (
            "Table A2-1 Global signals\n"
            "ACLK     Clock\n"
            "ARESETn  Reset\n"
            "\n"
            "Table A2-2 Write address channel signals\n"
            "AWID     Master Tag\n"
        )
        out = mod.extract_l15_encoding_tables(text)
        assert out["extraction_status"] == "EXTRACTED"
        tables = out["fields"]["tables"]
        assert len(tables) == 2
        assert tables[0]["table_id"] == "Table A2-1"
        assert tables[0]["name"] == "Global signals"
        assert "ACLK" in tables[0]["rows"][0]

    def test_no_table_headers_returns_nothing(self):
        out = mod.extract_l15_encoding_tables("Just paragraphs.")
        assert out["extraction_status"] == "EXTRACTION_FOUND_NOTHING"
        assert out["fields"]["tables"] == []


class TestL16Compliance:
    def test_must_sentence_captured(self):
        text = ("A master interface must drive ARVALID LOW until "
                 "reset is deasserted.\n")
        out = mod.extract_l16_compliance(text)
        assert out["fields"]["properties"]
        assert any("must" == p["anchor_token"]
                   for p in out["fields"]["properties"])

    def test_shall_sentence_captured(self):
        text = "The interconnect shall propagate AxID across the fabric.\n"
        out = mod.extract_l16_compliance(text)
        assert any(p["anchor_token"] == "shall"
                   for p in out["fields"]["properties"])

    def test_scope_classification(self):
        text = ("The write response, BRESP, must be signaled only after "
                 "the last data transfer of a write transaction.\n")
        out = mod.extract_l16_compliance(text)
        # Should classify into B_channel
        props = out["fields"]["properties"]
        assert any(p["scope"] == "B_channel" for p in props)


class TestL17Channels:
    def test_amba_axi_signal_rows_grouped_by_channel(self):
        text = (
            "    AWADDR    Master    The address of the first transfer.\n"
            "    AWLEN     Master    Length, the exact number of transfers.\n"
            "    WVALID    Master    Indicates write data signals are valid.\n"
            "    BVALID    Slave     Indicates write response signals are valid.\n"
            "    ARVALID   Master    Indicates read address signals are valid.\n"
            "    RVALID    Slave     Indicates read data signals are valid.\n"
        )
        out = mod.extract_l17_channels(text)
        channels = {c["name"]: c for c in out["fields"]["channels"]}
        assert "AW" in channels
        assert "B" in channels
        # AW has both AWADDR and AWLEN
        aw_sigs = channels["AW"]["signals"]
        assert len(aw_sigs) == 2
        assert any(s["name"] == "AWADDR" for s in aw_sigs)

    def test_dependency_graph_emitted(self):
        out = mod.extract_l17_channels("AWADDR    Master    address\n")
        assert "dependency_graph" in out["fields"]

    def test_unknown_prefix_signal_ignored(self):
        # X-prefix doesn't match a channel — ignored
        text = "XVALID    Master    some signal\n"
        out = mod.extract_l17_channels(text)
        assert all(
            c["name"] in ("AW", "W", "B", "AR", "R")
            for c in out["fields"]["channels"]
        )


class TestL18Interconnect:
    def test_default_signal_value_captured(self):
        text = "AWBURST defaults to INCR if not driven by the master.\n"
        out = mod.extract_l18_interconnect(text)
        assert "AWBURST" in out["fields"]["default_signal_values"]

    def test_interconnect_rule_captured(self):
        text = ("The interconnect must propagate the BRESP value back "
                 "to the originating master.\n")
        out = mod.extract_l18_interconnect(text)
        assert out["fields"]["interconnect_rules"]

    # v0.1.51 iter6 enhancements
    def test_table_style_default_captured(self):
        # AXI A9-1..A9-4 style: SIGNAL DIRECTION REQUIRED? DEFAULT
        text = (
            "    AWID      Output    Optional    All zeros\n"
            "    AWADDR    Output    Required    -\n"
            "    AWREGION  Output    Optional    All zeros\n"
            "    AWLEN     Output    Optional    All zeros, Length 1\n"
            "    WSTRB     Output    Optional    All ones\n"
        )
        out = mod.extract_l18_interconnect(text)
        defaults = out["fields"]["default_signal_values"]
        assert "AWID" in defaults
        assert "AWADDR" in defaults
        assert "AWREGION" in defaults
        assert "WSTRB" in defaults
        # "-" should be normalized to "Required (no default)"
        assert "Required" in defaults["AWADDR"]

    def test_typical_topologies_captured(self):
        text = (
            "Shared address and data buses are used for the simplest "
            "AXI fabric topology.\n"
            "Multilayer interconnect uses a crossbar to permit parallel "
            "transactions.\n"
        )
        out = mod.extract_l18_interconnect(text)
        assert out["fields"]["typical_topologies"]
        # both lines should be captured
        assert len(out["fields"]["typical_topologies"]) >= 2

    def test_multi_copy_atomicity_captured(self):
        text = (
            "Multi_Copy_Atomicity is mandatory from Issue G of the "
            "specification. All observers must see writes in a "
            "consistent order.\n"
        )
        out = mod.extract_l18_interconnect(text)
        mca = out["fields"]["multi_copy_atomicity"]
        assert mca
        assert "Issue G" in mca["required_from"]

    def test_axprot_polarity_captured(self):
        text = (
            "AxPROT[1] = 0 indicates Secure access; AxPROT[1] = 1 "
            "indicates Non-secure access.\n"
        )
        out = mod.extract_l18_interconnect(text)
        pol = out["fields"]["axprot_polarity"]
        assert pol is not None
        assert "Non-secure" in pol["polarity"] or "Secure" in pol["polarity"]


class TestL15TighterFilter:
    """v0.1.51 iter6: L15 must drop non-encoding tables."""

    def test_table_without_encoding_rows_dropped(self):
        text = (
            "Table A1-1 Document conventions\n"
            "This section uses italic font for hyperlinks.\n"
            "Bold font is used for emphasis.\n"
            "\n"
        )
        out = mod.extract_l15_encoding_tables(text)
        # Title has no encoding keyword AND body has no binary row
        # → table should be dropped
        assert all(t["name"] != "Document conventions"
                   for t in out["fields"]["tables"])

    def test_table_with_encoding_row_kept(self):
        text = (
            "Table A3-3 Burst type encoding\n"
            "2'b00     FIXED     fixed-address burst\n"
            "2'b01     INCR      incrementing burst\n"
        )
        out = mod.extract_l15_encoding_tables(text)
        names = [t["name"] for t in out["fields"]["tables"]]
        assert "Burst type encoding" in names

    def test_title_keyword_keeps_table(self):
        # Even if rows don't contain binary, if the title has "encoding"
        # / "signals" / "value" we keep the table.
        text = (
            "Table A2-2 Write address channel signals\n"
            "AWID    Master   Tag\n"
            "AWADDR  Master   Address\n"
        )
        out = mod.extract_l15_encoding_tables(text)
        names = [t["name"] for t in out["fields"]["tables"]]
        assert "Write address channel signals" in names


class TestL17ChannelEnhancements:
    """v0.1.51 iter6: L17 must surface global_signals + channel_counts
    + handshake_pairs + AXI3/AXI4 dependency_graph."""

    def test_global_signals_captured(self):
        text = (
            "ACLK      Global    Clock source.\n"
            "ARESETn   Global    Asynchronous reset, active low.\n"
            "AWADDR    Master    Address of the first transfer.\n"
        )
        out = mod.extract_l17_channels(text)
        gs = out["fields"]["global_signals"]
        names = [g["name"] for g in gs]
        assert "ACLK" in names
        assert "ARESETn" in names

    def test_channel_counts_summary(self):
        text = (
            "AWADDR     Master    Write address.\n"
            "AWLEN      Master    Burst length field.\n"
            "WVALID     Master    Write data is valid.\n"
            "BVALID     Slave     Write response is valid.\n"
        )
        out = mod.extract_l17_channels(text)
        cc = out["fields"]["channel_counts"]
        assert cc["channels"] == 3
        assert cc["total_signals_excluding_global"] == 4

    def test_handshake_pairs_inferred(self):
        text = (
            "AWVALID    Master    Address valid.\n"
            "AWREADY    Slave     Address ready.\n"
            "WVALID     Master    Data valid.\n"
            "WREADY     Slave     Data ready.\n"
        )
        out = mod.extract_l17_channels(text)
        pairs = out["fields"]["handshake_pairs"]
        assert "AW" in pairs
        assert pairs["AW"]["valid"] == "AWVALID"
        assert pairs["AW"]["ready"] == "AWREADY"

    def test_dependency_graph_mentions_axi3_and_axi4(self):
        # Text contains both markers → both deps captured
        text = (
            "ARVALID    Master    Read address valid.\n"
            "ARREADY    Slave     Read address ready.\n"
            "The AXI3 protocol allows BVALID independent of AW handshake.\n"
            "The AXI4 protocol tightens BVALID to wait for AW.\n"
        )
        out = mod.extract_l17_channels(text)
        dep = out["fields"]["dependency_graph"]
        assert "common_rule" in dep
        assert "AXI3_write" in dep
        assert "AXI4_write" in dep
        assert "AXI_read" in dep


class TestDriver:
    def test_skips_na_stub(self, tmp_path):
        docs = tmp_path / "phase1" / "generated_docs"
        docs.mkdir(parents=True)
        # Pre-create an N/A stub at L14
        (docs / "L14_PROTOCOL_VERSIONING.json").write_text(
            json.dumps({"applicability": "N/A"}))
        # Source has a valid version row, but extractor should NOT
        # overwrite the N/A stub.
        text = "16 June 2003       A     Non-Confidential   First release\n"
        status = mod.fill_skeletons(tmp_path, text)
        assert status["L14"] == "SKIPPED_NOT_APPLICABLE"

    def test_fills_skeleton(self, tmp_path):
        docs = tmp_path / "phase1" / "generated_docs"
        docs.mkdir(parents=True)
        (docs / "L14_PROTOCOL_VERSIONING.json").write_text(
            json.dumps({"applicability": "APPLICABLE", "fields": {}}))
        text = "16 June 2003       A     Non-Confidential   First release\n"
        status = mod.fill_skeletons(tmp_path, text)
        assert status["L14"] == "EXTRACTED"
        # Now reload and verify
        out = json.loads(
            (docs / "L14_PROTOCOL_VERSIONING.json").read_text())
        assert len(out["fields"]["versions"]) == 1

    def test_extractor_attribution(self, tmp_path):
        docs = tmp_path / "phase1" / "generated_docs"
        docs.mkdir(parents=True)
        (docs / "L14_PROTOCOL_VERSIONING.json").write_text(
            json.dumps({"applicability": "APPLICABLE"}))
        text = "16 June 2003       A     Non-Confidential   First release\n"
        mod.fill_skeletons(tmp_path, text)
        out = json.loads(
            (docs / "L14_PROTOCOL_VERSIONING.json").read_text())
        assert out["extracted_by"] == (
            "phase1_protocol_spec_extract.extract_l14_* "
            f"v{shipped_plugin_version()}")
