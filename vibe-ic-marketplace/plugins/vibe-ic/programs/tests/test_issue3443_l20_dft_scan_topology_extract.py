from pathlib import Path

import l20_dft_scan_topology_extract as extract
import phase1_post_process as post


GOOD = """# Implementation decisions

## DFT / Scan Topology

| Chain | Length | Scan In | Scan Out | Clock | Shift Frequency MHz |
|---|---:|---|---|---|---:|
| chain_0 | 21,406 | sin | sout | clk_i | 10 |
"""


def _project(tmp_path: Path, text: str = GOOD) -> Path:
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "implementation_dft_decisions.md").write_text(text)
    return tmp_path


def test_positive_control_extracts_a_source_cited_typed_chain(tmp_path):
    project = _project(tmp_path)
    result = extract.extract_dft_scan_topology(project)
    assert result["fields"] == {
        "dft_present": True,
        "scan_chains": [{
            "name": "chain_0", "length": 21406, "scan_in": "sin",
            "scan_out": "sout", "clock": "clk_i", "frequency_mhz": 10.0,
        }],
    }
    assert result["source_documents"] == [
        "input/docs/implementation_dft_decisions.md"]
    assert result["extraction_evidence"]["scan_chains"][0]["line"] == 7

    emitted = post.emit_l_doc_skeleton("L20", "crypto_accelerator", project)
    assert emitted["extraction_status"] == "EXTRACTED"
    assert emitted["fields"]["scan_chains"] == result["fields"]["scan_chains"]
    assert emitted["source_documents"] == result["source_documents"]


def test_reverse_control_unscoped_table_does_not_authorize_dft(tmp_path):
    project = _project(tmp_path, GOOD.replace("## DFT / Scan Topology",
                                              "## Interface pins"))
    assert extract.extract_dft_scan_topology(project) is None
    emitted = post.emit_l_doc_skeleton("L20", "crypto_accelerator", project)
    assert emitted["extraction_status"] == "NOT_YET_EXTRACTED"
    assert emitted["fields"]["scan_chains"] == []


def test_reverse_control_partial_row_is_refused_without_partial_output(tmp_path):
    bad = GOOD.replace("| chain_0 | 21,406 | sin | sout | clk_i | 10 |",
                       "| chain_0 | TBD | sin | sout | clk_i | 10 |")
    project = _project(tmp_path, bad)
    try:
        extract.extract_dft_scan_topology(project)
    except ValueError as exc:
        assert "positive length" in str(exc)
    else:
        raise AssertionError("partial topology was accepted")


def test_reverse_control_fenced_example_is_not_design_authority(tmp_path):
    fence = chr(96) * 3
    project = _project(tmp_path, "# DFT\n\n" + fence + "markdown\n"
                       + GOOD + "\n" + fence + "\n")
    assert extract.extract_dft_scan_topology(project) is None


def test_reverse_control_duplicate_chain_names_are_refused(tmp_path):
    duplicate = GOOD.rstrip() + (
        "\n| chain_0 | 8 | sin2 | sout2 | clk_i | 10 |\n")
    project = _project(tmp_path, duplicate)
    try:
        extract.extract_dft_scan_topology(project)
    except ValueError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("duplicate chain identity was accepted")


def test_front_door_normalized_mirror_is_deduplicated_to_pristine_source(
        tmp_path):
    project = _project(tmp_path)
    mirror = project / "phase1" / "input_doc"
    mirror.mkdir(parents=True)
    (mirror / "implementation_dft_decisions.txt").write_text(GOOD)
    result = extract.extract_dft_scan_topology(project)
    assert len(result["fields"]["scan_chains"]) == 1
    assert result["source_documents"] == [
        "input/docs/implementation_dft_decisions.md"]


def test_different_documents_declaring_same_chain_remain_a_conflict(tmp_path):
    project = _project(tmp_path)
    (project / "input" / "docs" / "other.md").write_text(
        GOOD.replace("# Implementation decisions", "# Separate authority"))
    try:
        extract.extract_dft_scan_topology(project)
    except ValueError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("independent duplicate declarations were accepted")
