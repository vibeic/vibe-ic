"""tests/test_phase1_fixtures_regression.py — v1.6.62

Regression fixture suite for the 11-project picker benchmark cited
across the issue-#5 verifier follow-ups.

The verifier's recommendation in the v1.6.61 follow-up was:

    > Suggest committing the 11-project benchmark inputs as fixtures
    > so any future picker change must keep all eleven outputs stable.

This test reads each fixture under `tests/phase1_fixtures/<project>/`
and asserts the picker returns the expected IC name. Future picker
changes must keep ALL eleven outputs stable; a regression here means
the picker thrashed on a real-input case the verifier signed off on.

**Provenance:** the verbatim README text for chacha, taxi,
liteiclink and litescope was lifted from the verifier's
v1.6.60-follow-up issue comment. The other seven fixtures
(aes, sha1, sha256, litedram, litesata, litesdcard, benchmark_a) carry
representative READMEs that mirror the corresponding open-source
project's first-paragraph form and the verifier's expected outputs;
they are intentionally minimal so any future picker behaviour change
that breaks them will surface immediately.

If the upstream README format changes for any of these projects,
update the fixture file (NOT the assertion) — the picker's expected
output is what this test pins.
"""
from __future__ import annotations

from pathlib import Path
import json

import pytest

from programs.phase1_one_shot_runner import _ic_name_from_docs


_FIXTURE_DIR = Path(__file__).parent / "phase1_fixtures"


# Expected pick per fixture project. These are the names the verifier
# agent confirmed as correct in the issue-#5 v1.6.61 follow-up
# scorecard ("10 of 11 returned the IP-name a human reviewer would
# have picked"). The taxi case is now also fixed by v1.6.62's tier
# reorder (Tier 3 H1 above Tier 3.5 subject), so all 11 are pinned.
_EXPECTED: dict[str, str] = {
    "aes":         "AES",
    "chacha":      "ChaCha",
    "sha1":        "SHA-1",
    "sha256":      "SHA-256",
    "litedram":    "LiteDRAM",
    "litesata":    "LiteSATA",
    "litesdcard":  "LiteSDCard",
    "liteiclink":  "LiteICLink",
    "litescope":   "LiteScope",
    "taxi":        "Taxi Transport Library",
    "benchmark_a":      "EXAMPLE_CHIP",
    "neutral_bound_type_width": "NeutralCore",
    # #3106: the native intake project's identity is also pinned.
    "subservient_l2_section_tail": "subservient",
    "neutral_many_sections": "NeutralCore",
    "neutral_security": "NeutralCore",
}


def _load_fixture(project: str) -> dict[str, str]:
    """Read every file under `tests/phase1_fixtures/<project>/` into
    a `{filename: text}` dict, matching what the real
    `phase1_one_shot_runner` extractor passes to
    `_ic_name_from_docs`."""
    pdir = _FIXTURE_DIR / project
    if not pdir.is_dir():
        pdir = Path(__file__).parent / "fixtures" / "phase1_local" / project
    if not pdir.is_dir():
        raise FileNotFoundError(f"missing fixture dir: {pdir}")
    out: dict[str, str] = {}
    for fp in sorted(pdir.iterdir()):
        if fp.is_file():
            out[fp.name] = fp.read_text(encoding="utf-8")
    if not out:
        raise FileNotFoundError(f"empty fixture dir: {pdir}")
    return out


@pytest.mark.parametrize("project,expected", sorted(_EXPECTED.items()))
def test_phase1_picker_matches_verifier_benchmark(
        project: str, expected: str) -> None:
    """Per-project regression: picker output on the committed fixture
    must equal the verifier-blessed expected name."""
    extracted = _load_fixture(project)
    actual = _ic_name_from_docs(extracted)
    assert actual == expected, (
        f"phase1 picker regression on fixture {project!r}: "
        f"expected {expected!r}, got {actual!r}. "
        f"If upstream README changed, update the fixture; otherwise "
        f"investigate the picker change that flipped this result."
    )


def test_phase1_picker_returns_distinct_names_for_11_projects() -> None:
    """Aggregate guard: the 11 fixtures must not all collapse to the
    same value. This catches a degenerate picker that returns
    `UNKNOWN_IC` for everything."""
    results = {p: _ic_name_from_docs(_load_fixture(p))
               for p in _EXPECTED}
    distinct = set(results.values())
    assert len(distinct) >= 10, (
        f"phase1 picker collapsed: only {len(distinct)} distinct "
        f"results across 11 fixtures: {results}"
    )
    # No fixture should silently return UNKNOWN_IC.
    unknowns = [p for p, n in results.items() if n == "UNKNOWN_IC"]
    assert not unknowns, (
        f"phase1 picker returned UNKNOWN_IC for: {unknowns}. "
        f"Every fixture should have a deterministic non-junk pick."
    )


def test_phase1_picker_no_fpga_board_in_results() -> None:
    """Aggregate guard: NO fixture should return an FPGA / silicon
    part-number SKU. Catches regressions of the v1.6.58 VCU1525 and
    v1.6.60 XCVU095 cases."""
    from programs.phase1_one_shot_runner import _is_fpga_board_name
    bad: dict[str, str] = {}
    for p in _EXPECTED:
        actual = _ic_name_from_docs(_load_fixture(p))
        # Single-token check (multi-word names won't board-match).
        first = actual.split()[0] if actual else ""
        if _is_fpga_board_name(first):
            bad[p] = actual
    assert not bad, (
        f"phase1 picker returned FPGA board name(s): {bad}. "
        f"This is the v1.6.58/v1.6.60 regression class; "
        f"check `_FPGA_BOARD_RE` coverage."
    )


def _field_doc(tmp_path: Path, layer: str, text: str) -> dict:
    from programs import phase1_doc_one_shot_runner as producer
    if layer == "L2":
        result = producer.gen_l2_frs(tmp_path, {"command_protocol.md": text})
    else:
        result = producer.gen_l7_test_debug(tmp_path, {"verification_plan.md": text})
    return json.loads(result.path.read_text())


def test_conditional_obligation_clauses_from_intake_reach_l9(tmp_path):
    """The native intake fixture must exercise its actual L9 field owner."""
    from programs.tests._hostpaths import require_repo
    from programs import l9_l19_contract_carrythrough as carry
    root = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "programs",
                        "tests", "fixtures", "phase1_local",
                        "conditional_obligation_clauses")
    text = (root / "L8_submodule_integration.md").read_text()
    docs = tmp_path / "input/docs"
    docs.mkdir(parents=True)
    (docs / "L8_submodule.md").write_text("layer: L8\n" + text)
    constraints = (root / "L9_constraints_floorplan.md").read_text()
    (docs / "L9_constraints.md").write_text("layer: L9\n" + constraints)
    generated = tmp_path / "phase1/generated_docs"
    generated.mkdir(parents=True)
    for name in ("L9_INTEGRATION_SPEC.json", "L19_CONSTRAINTS_PDK.json"):
        (generated / name).write_text("{}\n")
    carry.run(tmp_path)
    l9 = json.loads((generated / "L9_INTEGRATION_SPEC.json").read_text())
    actual = "\n".join(s["evidence"] for s in
                       l9.get("integration", {}).get("architecture", []))
    assert text.strip() in actual, actual
    l19 = json.loads((generated / "L19_CONSTRAINTS_PDK.json").read_text())
    io_delay = l19["constraints"]["io_delay"]
    assert constraints.strip() in io_delay["evidence"], io_delay
    assert io_delay["default_fraction_percent"] == 20
    assert io_delay["override_allowed"] is True
    assert io_delay["override_requires_declaration"] is True


@pytest.mark.parametrize("project,layer,field,expected", [
    ("negated_chip_protocol", "L2", "protocol_overview", None),
    ("physical_signoff_rows", "L7", "debug_registers", []),
])
def test_phase1_local_field_intake(project, layer, field, expected, tmp_path):
    from programs.tests._hostpaths import require_repo
    root = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "programs",
                        "tests", "fixtures", "phase1_local", project)
    text = "\n".join(p.read_text() for p in sorted(root.glob("*.md")))
    doc = _field_doc(tmp_path, layer, text)
    assert doc[field] == expected, doc[field]


@pytest.mark.parametrize("text,wire_count", [
    ("A chip implements the SPI command protocol.\n", 4),
    ("The chip implements a dedicated SPI command controller and firmware bit-banging supplies a UART GPIO output.\n", 4),
    ("The chip implements a UART hardware controller command interface with a firmware bit-banging diagnostic mode.\n", 2),
    ("A dedicated SPI hardware controller implements the chip's command interface with a firmware bit-banging diagnostic mode.\n", 4),
    ("The SPI hardware command controller is implemented in the chip and firmware bit-banging supplies a UART GPIO output.\n", 4),
    ("The chip's dedicated SPI hardware controller accepts command transfers while firmware bit-banging supplies a UART GPIO output.\n", 4),
    ("The SPI command controller is implemented in the chip and firmware bit-banging supplies a UART GPIO output.\n", 4),
    ("The chip's UART hardware controller accepts command transfers while firmware bit-banging supplies an SPI GPIO output.\n", 2),
    ("The UART hardware command controller is implemented in the chip and firmware bit-banging supplies an SPI GPIO output.\n", 2),
    ("Firmware emulates a dedicated SPI controller and the chip's UART hardware controller accepts command transfers.\n", 2),
    ("A dedicated UART hardware controller implements the chip's command interface with firmware bit-banging on an SPI GPIO output.\n", 2),
    ("A purely digital SPI slave interface accepts commands.\n", 4),
    ("Firmware may bit-bang GPIO as UART, but the chip has a dedicated SPI controller with four wires.\n", 4),
    ("The UART hardware controller command interface drives GPIO output pins.\n", 2),
    ("Firmware bit-banging GPIO simulates SPI, but the UART hardware controller command interface accepts commands.\n", 2),
    ("Firmware bit-banging GPIO simulates SPI; the UART hardware controller command interface accepts commands.\n", 2),
    ("No SPI command interface.\nA UART slave interface accepts commands.\n", 2),
    ("No SPI interface, but the UART slave interface accepts commands.\n", 2),
    ("**Absent**:\n- SPI command interface\n\n**Implemented**:\n"
     "- UART slave interface accepts commands\n", 2),
    ("A chip has no UART interface.\nThe SPI command protocol transmits MSB-first.\n", 4),
])
def test_l2_positive_protocol_declarations_survive_negated_neighbors(
        text, wire_count, tmp_path):
    doc = _field_doc(tmp_path, "L2", text)
    assert (doc["protocol_overview"] or {}).get("wire_count") == wire_count, doc


@pytest.mark.parametrize("text", [
    "No SPI command interface is implemented.\n",
    "Firmware emulates a dedicated SPI command controller.\n",
    "Firmware emulates the chip's dedicated SPI command controller.\n",
    "Firmware emulation models a dedicated SPI hardware command controller.\n",
    "Firmware emulation models the chip's dedicated SPI hardware command controller.\n",
    "Firmware emulates a dedicated SPI command controller and a dedicated UART hardware controller.\n",
    "The SPI hardware command controller is emulated by firmware.\n",
    "A dedicated SPI hardware controller emulated by firmware accepts commands.\n",
    "The SPI hardware controller is firmware-emulated and accepts commands.\n",
    "Firmware bit-bangs a dedicated SPI command interface.\n",
    "A software-emulated dedicated UART hardware controller accepts commands.\n",
    "No dedicated SPI hardware controller command interface is implemented while firmware bit-banging drives UART GPIO output.\n",
    "The chip does not provide an I2C slave interface.\n",
    "**Not implemented**:\n- SPI command interface\n- UART command interface\n",
    "A GPIO output supplies UART tx by firmware bit-banging; this is an application.\n",
    "Firmware may bit-bang GPIO as UART.\n",
    "A GPIO output supports a serial UART pattern.\n",
    "| Output | Function |\n|---|---|\n| output_bit | GPIO output may act as UART tx |\n",
    "A GPIO output uses firmware bit-banged UART tx.\n",
    "The SRAM bus protocol name (Wishbone-classic / generic / custom) is unspecified.\n",
    "No half-duplex single-wire command protocol is present.\n",
])
def test_l2_negative_or_emulated_protocol_mentions_are_not_hardware(text, tmp_path):
    doc = _field_doc(tmp_path, "L2", text)
    assert doc["protocol_overview"] is None, doc["protocol_overview"]
    assert doc["no_protocol_overview_in_input"] is True, doc


def test_l2_memory_macro_is_not_an_ethernet_mac_protocol(tmp_path):
    from programs import phase1_doc_one_shot_runner as producer
    result = producer.gen_l2_frs(tmp_path, {
        "architecture.md": "A memory interface uses SRAM macro cells.\n"})
    doc = json.loads(result.path.read_text())
    assert doc["protocol_overview"] is None, doc["protocol_overview"]
    assert doc["no_protocol_overview_in_input"] is True, doc


@pytest.mark.parametrize("heading,row,names", [
    ("Debug registers", "| DBG_CTRL | Debug control |", ["DBG_CTRL"]),
    ("No debug registers", "| DBG_CTRL | Debug control |", []),
    ("沒有 debug registers", "| DBG_CTRL | Debug control |", []),
    ("Debug registers", "| CONFIG | Mode selector |", ["CONFIG"]),
    ("Purely digital debug registers", "| CONFIG | Mode selector |", ["CONFIG"]),
    ("Parameters", "| DmBaseAddr | Debug module base address register |", ["DmBaseAddr"]),
    ("Debug registers", "| DBG_CTRL | 0 | Control register, read/write |", ["DBG_CTRL"]),
    ("Physical Verification", "| RULE_CHECK | 100% clean |", []),
    ("Physical Verification", "| RuleCount | 42 | physical signoff requirement |", []),
    ("Verification statistics", "| COVERAGE | 100 |", []),
    ("Requirements", "| CHECK_A | clean |", []),
])
def test_l7_table_role_keeps_registers_and_rejects_verification_rows(
        heading, row, names, tmp_path):
    text = f"# Verification\n## {heading}\n| Name | Description |\n|---|---|\n{row}\n"
    doc = _field_doc(tmp_path, "L7", text)
    assert [r["name"] for r in doc["debug_registers"]] == names, doc["debug_registers"]


@pytest.mark.parametrize("text,names", [
    ("# Verification\n## Debug registers\n### Control\n"
     "| Name | Description |\n|---|---|\n| DBG_CTRL | Mode selector |\n",
     ["DBG_CTRL"]),
    ("# Verification\n## Debug registers\n### Coverage counters\n"
     "| Name | Value | Description |\n|---|---|---|\n"
     "| EVENT_COUNT | 0x200 | Read/write register counting observed events |\n",
     ["EVENT_COUNT"]),
    ("# Verification\n## Debug registers\n### Control registers\n"
     "| Name | Description |\n|---|---|\n| DBG_CTRL | Mode selector |\n",
     ["DBG_CTRL"]),
    ("# Verification\n## Debug registers\n### No debug registers\n"
     "| Name | Description |\n|---|---|\n| DBG_CTRL | Read/write control register |\n",
     []),
    ("# Verification\n## Debug registers\n### Physical Verification\n"
     "| Name | Description |\n|---|---|\n| DBG_CTRL | Read/write register check |\n",
     []),
    ("# Verification\n## Debug registers\n### No debug registers\n#### Control\n"
     "| Name | Description |\n|---|---|\n| DBG_CTRL | Read/write control register |\n",
     []),
    ("# Verification\n## Debug registers\n### Physical Verification\n"
     "| Name | Description |\n|---|---|\n| RULE_CHECK | Register layout check |\n"
     "### Control\n| Name | Description |\n|---|---|\n| CONFIG | Mode selector |\n",
     ["CONFIG"]),
    ("# Verification\n## Debug registers\n| Name | Description |\n|---|---|\n"
     "| DBG_CTRL | Mode selector |\n## Physical Verification\n### Control\n"
     "| Name | Description |\n|---|---|\n| RULE_CHECK | Read/write register check |\n",
     ["DBG_CTRL"]),
    ("# Verification\n## Debug registers\n| Name | Description |\n|---|---|\n"
     "| DBG_CTRL | Mode selector |\n## Requirements\n### Control\n"
     "| Name | Description |\n|---|---|\n| CHECK_A | Clean |\n",
     ["DBG_CTRL"]),
    ("# Verification\n## Parameters\nGeneral parameters.\n## Debug registers\n"
     "| Name | Description |\n|---|---|\n| CONFIG | Mode selector |\n"
     "## Parameters\n| Name | Description |\n|---|---|\n| CHECK_A | Clean |\n",
     ["CONFIG"]),
    ("# Verification\n## Debug registers\n| Name | Description |\n|---|---|\n"
     "| DBG_CTRL | Mode selector |\n## No debug registers\n"
     "| Name | Description |\n|---|---|\n| ABSENT_CTRL | Read/write register |\n"
     "## Debug registers\n| Name | Description |\n|---|---|\n| CONFIG | Mode selector |\n",
     ["DBG_CTRL", "CONFIG"]),
    ("# Verification\n## Coverage counters\n| Name | Description |\n|---|---|\n"
     "| EVENT_COUNT | Number of observed events |\n", []),
    ("Verification\n=============\nDebug registers\n---------------\n"
     "Control\n~~~~~~~\n| Name | Description |\n|---|---|\n| DBG_CTRL | Mode selector |\n",
     ["DBG_CTRL"]),
    ("= Verification\n== Debug registers\n=== Control\n"
     "| Name | Description |\n|---|---|\n| DBG_CTRL | Mode selector |\n",
     ["DBG_CTRL"]),
    ("1 Verification\n1.1 Debug registers\n1.1.1 Control\n"
     "| Name | Description |\n|---|---|\n| DBG_CTRL | Mode selector |\n",
     ["DBG_CTRL"]),
])
def test_l7_register_role_obeys_heading_ancestry_and_sibling_boundaries(
        text, names, tmp_path):
    doc = _field_doc(tmp_path, "L7", text)
    assert [r["name"] for r in doc["debug_registers"]] == names, doc["debug_registers"]


def test_subservient_l2_section_tail_from_native_intake(tmp_path):
    """#3106's emitted INPUT must survive the public semantic producer."""
    from programs.tests._hostpaths import require_repo
    from programs import phase1_doc_one_shot_runner as producer
    fixture = require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "programs", "tests",
        "fixtures", "phase1_local", "subservient_l2_section_tail",
        "L1_product_metadata.md")
    text = fixture.read_text()
    # Input-derived section bounds, independent of the slicing helper being
    # repaired. This exact row is the public issue's immutable expectation.
    expected = text.split("## Tapeout 目標\n", 1)[1].split(
        "## 量產 (Production-readiness) 期望", 1)[0].strip("\n")
    result = producer.gen_l2_frs(tmp_path, {fixture.name: text})
    doc = json.loads(result.path.read_text())
    actual = next(row for row in doc["frs_sections"]
                  if row["title"] == "Tapeout 目標")
    assert actual == {
        "section": "h2", "title": "Tapeout 目標", "content": expected,
        "evidence": "input/docs/L1_product_metadata.md",
        "heading_shape": "md_atx",
    }, actual


@pytest.mark.parametrize("heading,next_heading,shape", [
    ("## Functional Requirements\n", "## Following Section\n", "md_atx"),
    ("Functional Requirements\n-----------------------\n",
     "Following Section\n-----------------\n", "rst_underline"),
    ("== Functional Requirements\n", "== Following Section\n", "adoc"),
    ("1.1 Functional Requirements\n", "1.2 Following Section\n", "numbered"),
])
@pytest.mark.parametrize("body_chars", [1200, 20000])
def test_l2_semantic_section_body_is_complete(
        heading, next_heading, shape, body_chars, tmp_path):
    """Long requirements are data, across each supported heading shape."""
    from programs import phase1_doc_one_shot_runner as producer
    prose = ("functional requirements retain arbitration and ordering. " *
             (body_chars // 40))[:body_chars]
    body = prose + "\n\nterminal_constraint = 97"
    text = heading + "\n" + body + "\n\n" + next_heading + "next_body_only\n"
    result = producer.gen_l2_frs(tmp_path, {"specification.rst": text})
    rows = json.loads(result.path.read_text())["frs_sections"]
    row = next(r for r in rows if r["title"] == "Functional Requirements")
    assert row["content"] == body, row
    assert row["heading_shape"] == shape, row
    assert "next_body_only" not in row["content"]
    following = next(r for r in rows if r["title"] == "Following Section")
    assert following["content"] == "next_body_only", following


@pytest.mark.parametrize("body", ["", "short_requirement = 3"])
def test_l2_semantic_section_short_or_empty_body_keeps_boundaries(body, tmp_path):
    from programs import phase1_doc_one_shot_runner as producer
    result = producer.gen_l2_frs(tmp_path, {"specification.md":
        "## Requirements\n\n" + body + "\n\n## Following Section\nother\n"})
    rows = json.loads(result.path.read_text())["frs_sections"]
    row = next(r for r in rows if r["title"] == "Requirements")
    assert row["content"] == body, row


@pytest.mark.parametrize("cap", [None, 17, 800])
def test_section_body_preview_cap_remains_explicit(cap):
    from programs import phase1_doc_one_shot_runner as producer
    body = "requirement data with internal spaces. " * 100
    text = "\n\n" + body + "\n\n"
    kwargs = {} if cap is None else {"max_chars": cap}
    actual = producer._v1_6_357_slice_section_body(text, 0, None, **kwargs)
    limit = 800 if cap is None else cap
    assert actual == body[:limit] + "…"


def test_l2_complete_body_reaches_expert_but_missing_tail_is_rejected(tmp_path):
    """Actual expert consumer must distinguish good producer data from loss."""
    from programs import phase1_doc_one_shot_runner as producer
    from programs import phase1_expert_parse_track as expert
    body = "arbitration rules remain sequential. " * 100
    tail = "terminal_constraint = 97"
    result = producer.gen_l2_frs(tmp_path, {"specification.md":
        "## Requirements\n\n" + body + "\n" + tail + "\n"})
    expectation = {"id": "terminal_requirement_retained", "layer": "L2_FRS",
                   "field_path": "frs_sections.content",
                   "requirement": "The input's final constraint is preserved.",
                   "evidence": ["specification.md: terminal_constraint = 97"],
                   "expected_tokens": [tail]}
    good = expert.converge_ai_expectation(tmp_path, expectation)
    assert good["usable"] and good["met"], good
    assert good["scope"] == "field_path", good
    # Deliberately damage only this neutral raw fixture, not the real project
    # or producer. A successful negative requires the actual consumer to fail.
    doc = json.loads(result.path.read_text())
    doc["frs_sections"][0]["content"] = body[:800] + "…"
    result.path.write_text(json.dumps(doc))
    bad = expert.converge_ai_expectation(tmp_path, expectation)
    assert bad["usable"] and bad["met"] is False, bad
    assert bad["missing_tokens"] == [tail], bad


@pytest.mark.parametrize("library", [False, True])
def test_neutral_many_sections_from_native_intake(tmp_path, library):
    from programs import phase1_doc_one_shot_runner as producer
    text = _load_fixture("neutral_many_sections")["neutral_many_sections.md"]
    if library:
        text += "\nThis transport library supports AXI, APB, UART and I2C.\n"
    result = producer.gen_l2_frs(tmp_path, {"neutral_many_sections.md": text})
    rows = json.loads(result.path.read_text())["frs_sections"]
    assert len(rows) == 70, rows[-1]
    assert rows[-1]["title"] == "Functional requirement 69"
    assert "marker_69" in rows[-1]["content"]


def test_neutral_security_from_native_intake(tmp_path):
    from programs.phase1_post_process import emit_l_doc_skeleton
    text = _load_fixture("neutral_security")["neutral_security.md"]
    docs = tmp_path / "input/docs"
    docs.mkdir(parents=True)
    (docs / "neutral_security.md").write_text(text)
    doc = emit_l_doc_skeleton("L23", "crypto_accelerator", project_dir=tmp_path)
    # The existing empty list is the observed wrong value, before testing any
    # newly populated field or helper. This must bite on the unmodified base.
    assert len(doc["fields"]["side_channel_mitigation"]) == 1, doc["fields"]
    assert bool(doc["fields"]["key_handling"]) is True, doc["fields"]
    records = doc["fields"]["side_channel_mitigation"]
    assert "first-order masking" in json.dumps(records)
    assert "neutral_security.md" in json.dumps(records)


def test_l23_source_records_reach_canonical_writer_and_typed_consumer(tmp_path):
    from programs import phase1_doc_one_shot_runner as producer
    from programs import l23_security_requirements_typed_check as consumer
    from programs import spi_protocol_synth
    docs = tmp_path / "input/docs"
    docs.mkdir(parents=True)
    text = _load_fixture("neutral_security")["neutral_security.md"]
    (docs / "neutral_security.md").write_text(text)
    # A persisted class is the standard upstream precondition of this writer.
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "ic_class.json").write_text(json.dumps({
        "ic_class": "crypto_accelerator"}))
    producer._emit_l19_to_l23_skeletons(tmp_path)
    generated = tmp_path / "phase1/generated_docs"
    spi_protocol_synth._apply_universal(generated)
    path = generated / "L23_SECURITY_REQUIREMENTS.json"
    doc = json.loads(path.read_text())
    assert doc["fields"]["security_requirements_present"] is True
    assert doc["extraction_status"] == "PARTIALLY_EXTRACTED"
    assert "input/docs/neutral_security.md" in doc["source_documents"]
    assert "does not specify" not in doc["fields"]["notes"]
    assert consumer.inspect(tmp_path)["verdict"] == "PASS"
    # The existing consumer must reject a record whose source was gutted.
    for key in ("key_handling", "attack_surface", "side_channel_mitigation"):
        for record in doc["fields"][key]:
            record.pop("evidence")
            record.pop("source")
    path.write_text(json.dumps(doc))
    result = consumer.inspect(tmp_path)
    assert result["verdict"] == "FAIL", result
    assert result["blocking_findings"][0]["id"] == "VACUOUS_SECURITY_ASSERTION"


def test_l23_no_security_source_does_not_gain_security_records(tmp_path):
    from programs.phase1_post_process import emit_l_doc_skeleton
    from programs import l23_security_requirements_typed_check as consumer
    docs = tmp_path / "input/docs"
    docs.mkdir(parents=True)
    source = docs / "neutral_security.md"
    source.write_text(_load_fixture("neutral_security")["neutral_security.md"])
    populated = emit_l_doc_skeleton("L23", project_dir=tmp_path)
    assert populated["fields"]["security_requirements_present"] is True
    # Replacing the source must remove the previously extracted facts.
    source.write_text("## Operating requirements\n"
                      "The unit shall complete a transaction within four cycles.\n"
                      "| alert_o | output | Detect tampering / attack. |\n")
    doc = emit_l_doc_skeleton("L23", project_dir=tmp_path)
    assert doc["fields"]["key_handling"] == {}
    assert doc["fields"]["side_channel_mitigation"] == []
    assert doc["fields"]["attack_surface"] == []
    assert doc["extraction_status"] == "NOT_YET_EXTRACTED"
    generated = tmp_path / "phase1/generated_docs"
    generated.mkdir(parents=True)
    (generated / "L23_SECURITY_REQUIREMENTS.json").write_text(json.dumps(doc))
    assert consumer.inspect(tmp_path)["verdict"] == "SKIP"


@pytest.mark.parametrize("heading,next_heading", [
    ("## Side-channel countermeasures", "## Operating requirements"),
    ("Side-channel countermeasures\n----------------------------",
     "Operating requirements\n----------------------"),
    ("== Side-channel countermeasures", "== Operating requirements"),
    ("1.1 Side-channel countermeasures", "1.2 Operating requirements"),
])
def test_l23_preserves_source_options_and_negations_at_section_boundary(
        tmp_path, heading, next_heading):
    from programs.phase1_post_process import emit_l_doc_skeleton
    docs = tmp_path / "input/docs"
    docs.mkdir(parents=True)
    body = ("The unit may disable masking at compile time.\n"
            "This mode does not protect against higher-order attacks.")
    (docs / "specification.md").write_text(
        heading + "\n\n" + body + "\n\n" + next_heading +
        "\n\nThis unrelated control uses a key to select an operation.\n")
    doc = emit_l_doc_skeleton("L23", project_dir=tmp_path)
    records = doc["fields"]["side_channel_mitigation"]
    assert len(records) == 1, records
    assert records[0]["description"] == body
    assert doc["fields"]["key_handling"] == []
    assert doc["fields"]["secure_boot"] is False


def test_l23_fenced_documentation_does_not_declare_security(tmp_path):
    from programs.phase1_post_process import emit_l_doc_skeleton
    docs = tmp_path / "input/docs"
    docs.mkdir(parents=True)
    (docs / "examples.md").write_text(
        "# Documentation example\n```markdown\n"
        "## Side-channel countermeasures\n"
        "The unit shall use masking.\n```\n")
    doc = emit_l_doc_skeleton("L23", project_dir=tmp_path)
    assert doc["fields"]["side_channel_mitigation"] == [], doc["fields"]
    assert doc["fields"].get("security_requirements_present", False) is False


# #3234: literal defaults must enter the selected module namespace before
# the existing flat L8-to-L9 mirror; no source confidence is promoted.
def _l8_literal_owner_emit(tmp_path, text):
    from programs import phase1_doc_one_shot_runner as D
    docs = {"literal_parameters.md": text}
    D.gen_l8_timing_waveform(tmp_path, docs)
    D.gen_l9_integration_spec(tmp_path, docs, {})
    D._post_emit_mirror_parameters_to_l9_v1_6_327(tmp_path)
    generated = tmp_path / "phase1/generated_docs"
    return [json.loads((generated / name).read_text()) for name in
            ("L8_RTL_CONSTANTS.json", "L9_INTEGRATION_SPEC.json")]


@pytest.mark.parametrize("filename, expected", [
    ("literal_parameters.md", {"TAG_BITS": "80", "DIGEST_BITS": "224"}),
    ("03-declared-rtl-widths.md", {"TAG_BITS": "80", "DIGEST_BITS": "224"}),
    ("04-headed-named-widths.md", {"PACKET_WIDTH_BITS": "72", "SAMPLE_WIDTH_BITS": "24"}),
    ("05-header-table-widths.md", {"HEADER_BITS": "40", "TRAILER_BITS": "12"}),
])
def test_l8_literal_parameter_owner_keeps_declared_names_and_values(tmp_path, filename, expected):
    fixture = Path(__file__).parent / "fixtures/phase1_local/l8_literal_parameter_owner" / filename
    for doc in _l8_literal_owner_emit(tmp_path, fixture.read_text()):
        assert {p["name"]: str(p["default"]) for p in doc["parameters"]} == expected


@pytest.mark.parametrize("sibling_first", [True, False])
def test_l8_literal_parameter_owner_does_not_borrow_sibling_defaults(tmp_path, sibling_first):
    fixture = Path(__file__).parent / "fixtures/phase1_local/l8_literal_parameter_owner/modules.md"
    text = fixture.read_text()
    if not sibling_first:
        preamble, remainder = text.split("## Sibling module trace_aux", 1)
        sibling, top = remainder.split("## Selected top module frame_top", 1)
        text = preamble + "## Selected top module frame_top" + top + "\n## Sibling module trace_aux" + sibling
    l8, l9 = _l8_literal_owner_emit(tmp_path, text)
    assert l9["top_module"] == "frame_top"
    for doc in (l9, l8):
        actual = {p["name"]: str(p["default"]) for p in doc["parameters"]}
        assert actual.get("DATA_BITS") == "20"
        assert set(actual) == {"DATA_BITS"}
        assert all(p["module_owner"] == "frame_top" for p in doc["parameters"])


def test_l8_literal_parameter_owner_multiple_modules_need_source_authority(tmp_path):
    fixture = Path(__file__).parent / "fixtures/phase1_local/l8_literal_parameter_owner/modules.md"
    text = fixture.read_text().replace("The selected top module is `frame_top`.\n", "")
    with pytest.raises(ValueError, match="L8_PARAMETER_OWNER_UNRESOLVED"):
        _l8_literal_owner_emit(tmp_path, text)


def test_l8_literal_parameter_owner_ignores_commented_declarations(tmp_path):
    text = "```systemverilog\n// parameter integer UNRELATED = 99;\n/* localparam integer OTHER = 17; */\n```\nmodule documentation_only #(\n"
    for doc in _l8_literal_owner_emit(tmp_path, text):
        assert doc.get("parameters", []) == []
