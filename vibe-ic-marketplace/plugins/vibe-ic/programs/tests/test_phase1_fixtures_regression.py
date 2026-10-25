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


def _semantic_project(tmp_path, text, ports=()):
    """Stage ordinary input and final interface for late semantic emitters."""
    source = tmp_path / 'input/docs/contract.txt'
    source.parent.mkdir(parents=True)
    source.write_text(text)
    generated = tmp_path / 'phase1/generated_docs'
    generated.mkdir(parents=True)
    (generated / 'L9_INTEGRATION_SPEC.json').write_text(json.dumps({
        'top_ports': list(ports), 'ports': list(ports),
    }))
    return generated


def test_semantic_state_heading_catalog_from_intake(tmp_path):
    from programs import phase1_doc_one_shot_runner as producer
    from programs.tests._hostpaths import require_repo
    fixture = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic',
                           'programs', 'tests', 'fixtures', 'phase1_local',
                           'phase1_semantic_catalog_contract',
                           'state_heading_catalog.txt')
    result = producer.gen_l6_control_logic(tmp_path, {fixture.name: fixture.read_text()})
    actual = json.loads(result.path.read_text())
    names = {state['name'] for state in actual['fsm_states']}
    assert names == {'IDLE', 'S1', 'S2', 'S3', 'S4'}, actual
    assert actual['fsm_machines'][0]['state_count'] == 5, actual


@pytest.mark.parametrize('text,expected', [
    ('State machine has the following states:\n'
     'A0: Waiting for request.\nA1: Capturing data.\n'
     'Implementation:\nOP_ADD: Addition opcode.\n', {'A0', 'A1'}),
    ('The controller has an FSM.\nALU operation codes:\n'
     'A0: Addition opcode.\nA1: Subtraction opcode.\n', set()),
])
def test_semantic_state_heading_scope_is_finite(tmp_path, text, expected):
    from programs import phase1_doc_one_shot_runner as producer
    result = producer.gen_l6_control_logic(tmp_path, {'control.txt': text})
    actual = json.loads(result.path.read_text())
    assert {state['name'] for state in actual['fsm_states']} == expected, actual


def test_semantic_explicit_submodule_reaches_actual_consumer(tmp_path):
    from programs import phase1_doc_one_shot_runner as producer
    from programs import l9_submodule_conformance_check as consumer
    text = ('Module name:\n    NeutralTop\nInput ports:\n'
            '    sample_i: Input data signal.\nOutput ports:\n'
            '    sample_o: Output data signal.\nImplementation:\n'
            'The `select_pair` submodule is used to select between two inputs.\n')
    _semantic_project(tmp_path, text)
    producer.gen_l1_datasheet(tmp_path, {'contract.txt': text})
    producer.gen_l9_integration_spec(tmp_path, {'contract.txt': text}, {})
    rtl = tmp_path / 'phase2/stage1/rtl'
    rtl.mkdir(parents=True)
    top = rtl / 'top.v'
    top.write_text('module NeutralTop(input sample_i, output sample_o); '
                   'assign sample_o=sample_i; endmodule\n')
    missing, findings, census, _ = consumer.audit_report(tmp_path)
    assert missing == 'FAIL', (missing, census, findings)
    assert any(f.rule == 'SUBMODULE_FILE_MISSING' for f in findings), findings
    (rtl / 'child.v').write_text('module select_pair(input d, output q); '
                                'assign q=d; endmodule\n')
    unbound, findings, _, _ = consumer.audit_report(tmp_path)
    assert unbound == 'FAIL', findings
    assert any(f.rule == 'SUBMODULE_NOT_INSTANTIATED' for f in findings), findings
    top.write_text('module NeutralTop(input sample_i, output sample_o); '
                   'select_pair u_select(.d(sample_i),.q(sample_o)); endmodule\n')
    assert consumer.audit_report(tmp_path)[0] == 'PASS'


def test_semantic_submodule_mention_is_not_a_structure_requirement(tmp_path):
    from programs import phase1_doc_one_shot_runner as producer
    text = ('Module name:\nNeutralTop\n'
            'The library documentation mentions `select_pair` as an example.\n'
            'The `select_pair` submodule is not used in this design.\n')
    result = producer.gen_l9_integration_spec(tmp_path, {'overview.txt': text}, {})
    actual = json.loads(result.path.read_text())
    assert 'select_pair' not in {row['name'] for row in actual['submodules']}, actual


def test_semantic_primary_clock_uses_actual_input_identity(tmp_path):
    from programs import phase1_doc_one_shot_runner as producer
    ports = [{'name': 'sample_clock', 'direction': 'input', 'width': 1},
             {'name': 'shifted_clock', 'direction': 'output', 'width': 1}]
    _semantic_project(tmp_path, 'Input ports:\n'
                      'sample_clock: Input clock signal.\n', ports)
    domains = [{'name': 'clk', 'freq_mhz': 80,
                'extraction_strategy': 'clock_domain_doc_prose_fmax'}]
    producer._emit_typed_clock_domains(tmp_path, domains, [])
    assert [(d['name'], d['source_pin']) for d in domains] == [
        ('sample_clock', 'sample_clock')], domains
    assert domains[0]['period_ns'] == 12.5, domains


def test_semantic_primary_binding_reaches_every_existing_view(tmp_path):
    from programs import phase1_doc_one_shot_runner as producer
    generated = _semantic_project(tmp_path, 'Input ports:\n'
                      'sample_clock: Input clock signal.\n', [
                          {'name': 'sample_clock', 'direction': 'input', 'width': 1}])
    for layer in ('L8_RTL_CONSTANTS', 'L8_TIMING_WAVEFORM', 'L9_INTEGRATION_SPEC'):
        path = generated / (layer + '.json')
        data = json.loads(path.read_text()) if path.exists() else {}
        data['clock_domains'] = [{'name': 'clk', 'freq_mhz': 80,
            'extraction_strategy': 'clock_domain_doc_prose_fmax'}]
        path.write_text(json.dumps(data))
    producer._post_emit_typed_clock_domains(tmp_path)
    producer._post_emit_mirror_clock_resets_to_l9_v1_6_311(tmp_path)
    for layer in ('L8_RTL_CONSTANTS', 'L8_TIMING_WAVEFORM', 'L9_INTEGRATION_SPEC'):
        data = json.loads((generated / (layer + '.json')).read_text())
        assert [(d['name'], d['source_pin'], d['period_ns']) for d in
                data['clock_domains']] == [('sample_clock', 'sample_clock', 12.5)], data


def test_semantic_output_clock_does_not_become_primary_input(tmp_path):
    from programs import phase1_doc_one_shot_runner as producer
    _semantic_project(tmp_path, 'Output ports:\n'
                      'out_clk: Output clock signal.\n', [
                          {'name': 'out_clk', 'direction': 'output', 'width': 1}])
    domains = []
    producer._emit_typed_clock_domains(tmp_path, domains, [])
    assert domains == [], domains


def test_semantic_two_named_input_clocks_and_resets_stay_distinct(tmp_path):
    from programs import phase1_doc_one_shot_runner as producer
    text = ('Input ports:\n'
            'load_tick: Write clock signal.\n'
            'unload_tick: Read clock signal.\n'
            'load_reset: Write reset signal, active low.\n'
            'unload_reset: Read reset signal, active high.\n')
    ports = [{'name': name, 'direction': 'input', 'width': 1}
             for name in ('load_tick', 'unload_tick', 'load_reset', 'unload_reset')]
    generated = _semantic_project(tmp_path, text, ports)
    (generated / 'L8_RTL_CONSTANTS.json').write_text('{}')
    (generated / 'L8_TIMING_WAVEFORM.json').write_text('{}')
    producer._post_emit_typed_clock_domains(tmp_path)
    producer._post_emit_mirror_clock_resets_to_l9_v1_6_311(tmp_path)
    actual = json.loads((generated / 'L9_INTEGRATION_SPEC.json').read_text())
    domains = actual.get('clock_domains', [])
    assert {d['name'] for d in domains} == {'load_tick', 'unload_tick'}, actual
    assert all(d['freq_hz'] is None and d['period_ns'] is None for d in domains), actual
    assert {r['name']: r['polarity'] for r in actual.get('resets', [])} == {
        'load_reset': 'active_low', 'unload_reset': 'active_high'}, actual


@pytest.mark.parametrize('name,description,polarity', [
    ('rst', 'Active low reset signal.', 'active_low'),
    ('rst_n', 'Active high reset signal.', 'active_high'),
    ('clear_request', 'Write reset signal. Defined as 0 for reset and 1 for reset signal inactive.', 'active_low'),
])
def test_semantic_explicit_reset_level_overrides_name(tmp_path, name, description, polarity):
    from programs import phase1_doc_one_shot_runner as producer
    text = f'Input ports:\n{name}: {description}\n'
    generated = _semantic_project(tmp_path, text, [
        {'name': name, 'direction': 'input', 'width': 1}])
    producer._post_emit_mirror_clock_resets_to_l9_v1_6_311(tmp_path)
    actual = json.loads((generated / 'L9_INTEGRATION_SPEC.json').read_text())
    assert {r['name']: r['polarity'] for r in actual.get('resets', [])} == {
        name: polarity}, actual


def test_semantic_counter_named_clock_is_not_a_clock_view(tmp_path):
    from programs import phase1_doc_one_shot_runner as producer
    generated = _semantic_project(tmp_path, 'Output ports:\n'
                      'clock [7:0]: Eight-bit cycle counter data.\n', [
                          {'name': 'clock', 'direction': 'output', 'width': 8}])
    producer._post_emit_derive_l9_clocks_v1_6_323(tmp_path)
    actual = json.loads((generated / 'L9_INTEGRATION_SPEC.json').read_text())
    assert actual.get('clocks', []) == [], actual


@pytest.mark.parametrize('constant,expected_hz', [
    ({'name': 'DIV_CLK_FREQ_MHZ', 'value': 25, 'unit': 'MHz',
      'source': 'input/docs/clocking.txt: div_clk output'}, None),
    ({'name': 'REF_TICK_FREQ_MHZ', 'value': 80, 'unit': 'MHz',
      'source_pin': 'ref_tick'}, 80_000_000),
    ({'name': 'PRIMARY_CLK_FREQ_MHZ', 'value': 40, 'unit': 'MHz'}, 40_000_000),
    ({'name': 'PRIMARY_CLK_FREQ_MHZ', 'value': 25, 'unit': 'MHz',
      'source_pin': 'div_clk'}, None),
])
def test_review_followup_clock_rate_stays_with_its_source(tmp_path, constant, expected_hz):
    from programs import phase1_doc_one_shot_runner as producer
    from programs import sdc_gen as consumer
    text = ('Input ports:\nref_tick: Input clock signal.\n'
            'Output ports:\ndiv_clk: Output clock signal.\n')
    _semantic_project(tmp_path, text, [
        {'name': 'ref_tick', 'direction': 'input', 'width': 1},
        {'name': 'div_clk', 'direction': 'output', 'width': 1}])
    domains = []
    producer._emit_typed_clock_domains(tmp_path, domains, [constant])
    assert [(d['name'], d['freq_hz']) for d in domains] == [
        ('ref_tick', expected_hz)], domains
    expected_mhz = expected_hz / 1_000_000 if expected_hz else None
    assert consumer._clock_mhz_from_l8_domains({'clock_domains': domains}) == expected_mhz


@pytest.mark.parametrize('suffix,role,verdict,rule', [
    ('is used to select the sample.', 'required', 'FAIL', 'SUBMODULE_FILE_MISSING'),
    ('is not used.', None, 'VACUOUS_PASS', None),
    ('is used optionally.', 'optional', 'VACUOUS_PASS', None),
    ('is used only when checksum mode is enabled.', 'conditional', 'FAIL',
     'SUBMODULE_CONDITION_UNRESOLVED'),
    ('is used only when top_module = NeutralTop.', 'conditional', 'FAIL',
     'SUBMODULE_FILE_MISSING'),
    ('is used only when top_module = OtherTop.', 'conditional', 'VACUOUS_PASS', None),
])
def test_review_followup_submodule_qualifier_reaches_actual_consumer(
        tmp_path, suffix, role, verdict, rule):
    from programs import phase1_doc_one_shot_runner as producer
    from programs import l9_submodule_conformance_check as consumer
    declaration = 'The "filter_cell" submodule ' + suffix
    text = ('Module name:\nNeutralTop\nInput ports:\n'
            'sample_i: Input data signal.\nOutput ports:\n'
            'sample_o: Output data signal.\nImplementation:\n' + declaration + '\n')
    _semantic_project(tmp_path, text)
    producer.gen_l1_datasheet(tmp_path, {'contract.txt': text})
    result = producer.gen_l9_integration_spec(tmp_path, {'contract.txt': text}, {})
    doc = json.loads(result.path.read_text())
    rtl = tmp_path / 'phase2/stage1/rtl'
    rtl.mkdir(parents=True)
    (rtl / 'top.v').write_text('module NeutralTop(input sample_i, output sample_o); '
                              'assign sample_o=sample_i; endmodule\n')
    actual, findings, census, _ = consumer.audit_report(tmp_path)
    assert actual == verdict, (actual, findings, census, doc['submodules'])
    if rule:
        assert rule in {f.rule for f in findings}, findings
    if role is None:
        assert doc['submodules'] == []
    else:
        entry = next(row for row in doc['submodules'] if row['name'] == 'filter_cell')
        assert entry.get('implementation_requirement', 'required') == role, entry
        if role == 'conditional':
            assert entry['requirement_evidence'][0]['evidence'] == declaration

from programs.phase1_one_shot_runner import _ic_name_from_docs


def test_memory_profile_public_prose_explicit_array(tmp_path):
    """#3581: exercise the intake's real public bytes through ordinary L9."""
    from programs import phase1_doc_one_shot_runner as producer
    from _hostpaths import require_repo
    fixture = require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "programs", "tests",
        "fixtures", "phase1_local", "memory_profile_public_prose",
        "memory_geometry.txt")
    result = producer.gen_l9_integration_spec(
        tmp_path, {fixture.name: fixture.read_text()}, {})
    doc = json.loads(Path(result.path).read_text())
    geometry = [(m.get("width"), m.get("depth")) for m in doc["memories"]]
    assert geometry == [(16, 256)], doc
    assert not doc["memory_candidates"], doc


def test_memory_profile_public_prose_conflicting_geometry(tmp_path):
    from programs import phase1_doc_one_shot_runner as producer
    body = ("Implement a dual-port RAM with a depth of 12 and a bit width of 5 bits.\n"
            "WIDTH = 5;\nDEPTH = 12;\n"
            "RAM Array: reg [DEPTH - 1 : 0] bank [2**WIDTH-1:0];\n")
    result = producer.gen_l9_integration_spec(tmp_path, {"array.md": body}, {})
    memories = json.loads(Path(result.path).read_text())["memories"]
    assert len(memories) == 1, memories
    row = memories[0]
    assert (row.get("width"), row.get("depth")) == (None, None), row
    assert row.get("geometry_status") == "SOURCE_CONFLICT", row
    assert {(v["width"], v["depth"]) for v in row["geometry_claims"]} == {(5, 12), (12, 32)}
    assert all(v["source_text"] in body for v in row["geometry_claims"])
    assert row["low_confidence"] is True


def test_memory_profile_public_prose_array_control(tmp_path):
    from programs import phase1_doc_one_shot_runner as producer
    body = "A ROM stores lookup data.\nMemory Array:\nreg [11:0] values [47:0];"
    result = producer.gen_l9_integration_spec(tmp_path, {"array.md": body}, {})
    rows = json.loads(Path(result.path).read_text())["memories"]
    assert [(m.get("width"), m.get("depth")) for m in rows] == [(12, 48)], rows


@pytest.mark.parametrize("description, expected", [
    ("Implement an ALU for a 32-bit MIPS-ISA CPU.", "digital_arithmetic_primitive"),
    ("Implement an arithmetic logic unit for a RISC-V processor.", "digital_arithmetic_primitive"),
    ("Implement a RISC-V CPU with an ALU, instruction fetch and program counter.", "processor_cpu"),
])
def test_memory_profile_public_prose_primary_subject(tmp_path, description, expected):
    from programs.ic_class_profile import infer_ic_class_uncached
    gd = tmp_path / "phase1/generated_docs"
    gd.mkdir(parents=True)
    (gd / "L1_DATASHEET.json").write_text(json.dumps({"description": description}))
    (gd / "L2_FRS.json").write_text("{}")
    assert infer_ic_class_uncached(tmp_path)["ic_class"] == expected


def test_memory_profile_public_prose_temporal_in(tmp_path):
    from programs import phase1_doc_one_shot_runner as producer
    body = ("The waveform keeps 31 in that clock cycle.\n"
            "The waveform keeps 0 in that clock cycle.\n"
            "Package width is 2 in; package height is 4mm.\n")
    producer.gen_l1_datasheet(tmp_path, {"notes.md": body})
    producer._harvest_vendor_short_literals(tmp_path, {"notes.md": body})
    doc = json.loads((tmp_path / "phase1/generated_docs/L1_DATASHEET.json").read_text())
    dimensions = {r["literal"] for r in doc.get("vendor_short_literals", [])
                  if r["kind"] == "dimension"}
    assert dimensions == {"2in", "4mm"}, dimensions
    producer._harvest_vendor_short_literals(
        tmp_path, {"notes.md": "The waveform keeps 31 in that clock cycle."})
    doc = json.loads((tmp_path / "phase1/generated_docs/L1_DATASHEET.json").read_text())
    assert doc.get("vendor_short_literals") == [], doc


def test_memory_profile_public_prose_multiple_arrays_are_not_a_conflict(tmp_path):
    from programs import phase1_doc_one_shot_runner as producer
    body = ("reg [7:0] first [0:15]: ROM data storage.\n"
            "reg [15:0] second [0:31]: ROM metadata storage.\n")
    result = producer.gen_l9_integration_spec(tmp_path, {"arrays.md": body}, {})
    rows = json.loads(Path(result.path).read_text())["memories"]
    assert rows and all(r["geometry_status"] == "UNRESOLVED" for r in rows), rows
    assert all(r["width"] is None and r["depth"] is None for r in rows), rows
    assert {c["source_text"] for r in rows for c in r["geometry_claims"]} == {
        "reg [7:0] first [0:15]", "reg [15:0] second [0:31]"}


@pytest.mark.parametrize("separator", [";", "；"])
def test_memory_profile_followup_independent_processor_clause(tmp_path, separator):
    from programs.ic_class_profile import infer_ic_class_uncached
    gd = tmp_path / "phase1/generated_docs"
    gd.mkdir(parents=True)
    description = ("Implement an ALU for a RISC-V processor" + separator +
                   " additionally implement a CPU with instruction fetch and a program counter.")
    (gd / "L1_DATASHEET.json").write_text(json.dumps({"description": description}))
    (gd / "L2_FRS.json").write_text("{}")
    assert infer_ic_class_uncached(tmp_path)["ic_class"] == "processor_cpu"


def test_memory_profile_followup_negated_array(tmp_path):
    from programs import phase1_doc_one_shot_runner as producer
    body = "Implement a ROM.\nDo not use reg [15:0] obsolete [0:31];\n"
    result = producer.gen_l9_integration_spec(tmp_path, {"array.md": body}, {})
    assert json.loads(Path(result.path).read_text())["memories"] == []
    result = producer.gen_l9_integration_spec(
        tmp_path, {"array.md": body.replace("Do not use", "Use")}, {})
    rows = json.loads(Path(result.path).read_text())["memories"]
    assert [(m["width"], m["depth"]) for m in rows] == [(16, 32)]


@pytest.mark.parametrize("local_parameters", [False, True])
def test_memory_profile_followup_module_parameter_scope(tmp_path, local_parameters):
    from programs import phase1_doc_one_shot_runner as producer
    body = ("module unrelated;\nparameter WIDTH = 9;\nparameter DEPTH = 13;\nendmodule\n"
            "module storage;\n// ROM lookup storage\n")
    if local_parameters:
        body += "parameter WIDTH = 5;\nparameter DEPTH = 11;\n"
    body += "reg [WIDTH-1:0] values [0:DEPTH-1];\nendmodule\n"
    result = producer.gen_l9_integration_spec(tmp_path, {"array.md": body}, {})
    rows = json.loads(Path(result.path).read_text())["memories"]
    assert len(rows) == 1, rows
    if local_parameters:
        assert (rows[0]["width"], rows[0]["depth"]) == (5, 11), rows
        assert rows[0]["low_confidence"] is False
    else:
        assert (rows[0]["width"], rows[0]["depth"]) == (None, None), rows
        assert rows[0]["geometry_status"] == "UNRESOLVED", rows
        assert rows[0]["low_confidence"] is True


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
    "neutral_physical_signoff_list": "NeutralCore",
    "neutral_pvt_supply_rail": "NeutralCore",
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


def test_neutral_physical_signoff_list(tmp_path):
    """#3279: physical signoff obligations do not declare an analog circuit."""
    from programs import phase1_doc_one_shot_runner as D
    docs = _load_fixture("neutral_physical_signoff_list")
    result = D.gen_l5_adi_spec(tmp_path, docs)
    payload = json.loads(Path(result.path).read_text())
    assert payload["analog_blocks"] == []
    assert payload["analog_blocks_detected"] is False


def test_neutral_io_analysis_prose(tmp_path):
    """#3289: implementation prose under an I/O heading declares no pins."""
    from programs import phase1_doc_one_shot_runner as producer
    emitted = producer.gen_l1_datasheet(tmp_path, _load_fixture("neutral_io_analysis_prose"))
    assert json.loads(Path(emitted.path).read_text())["pin_table"] == []


def test_neutral_port_fields_reach_l1_and_every_l9_alias(tmp_path):
    """The ordinary producer must publish the interface, not just raw notes."""
    import subprocess
    import sys
    from programs import phase1_doc_one_shot_runner as producer

    source = tmp_path / "input/docs/design_description.txt"
    source.parent.mkdir(parents=True)
    source.write_text(_load_fixture("neutral_port_fields")[source.name])
    run = subprocess.run([sys.executable, producer.__file__, str(tmp_path)],
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    generated = tmp_path / "phase1/generated_docs"
    l1 = json.loads((generated / "L1_DATASHEET.json").read_text())
    l9 = json.loads((generated / "L9_INTEGRATION_SPEC.json").read_text())
    expected = {"a": ("input", 16), "b": ("input", 16),
                "Cin": ("input", 1), "y": ("output", 16),
                "Co": ("output", 1)}
    for rows in [l1["pin_table"], *(l9[key] for key in
                                   ("ports", "top_ports", "top_module_pins"))]:
        assert {row["name"]: ({"in": "input", "out": "output"}.get(
                    row["mode"], row["mode"]), row["width"])
                for row in rows} == expected


def test_neutral_pvt_supply_rail(tmp_path):
    """#3283: a native supply table is not a missing regulator circuit."""
    from programs import phase1_doc_one_shot_runner as producer
    import subprocess
    import sys
    source = tmp_path / "input/docs/pvt_supply_rail.md"
    source.parent.mkdir(parents=True)
    text = _load_fixture("neutral_pvt_supply_rail")["pvt_supply_rail.md"]
    source.write_text(text)
    emitted = producer.gen_l5_adi_spec(tmp_path, {source.name: text})
    assert json.loads(emitted.path.read_text())["analog_blocks"] == []
    gate = Path(producer.__file__).with_name("analog_content_detected_must_emit_l5_check.py")
    result = subprocess.run([sys.executable, str(gate), str(tmp_path)], capture_output=True, text=True)
    assert result.returncode == 2, result.stdout + result.stderr


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





def test_neutral_wrapped_block_latency():
    from programs.crypto_arch_extractor import extract_crypto_arch
    source = _load_fixture("neutral_wrapped_block_latency")
    actual = extract_crypto_arch("\n".join(source.values()))
    assert "latency_cycles_per_block" not in actual, actual
    assert "latency_cycles_per_block_evidence" not in actual, actual


def test_neutral_functional_preamble_reaches_l2(tmp_path):
    import json
    from programs import phase1_doc_one_shot_runner as producer
    source = _load_fixture("neutral_functional_preamble")
    docs = tmp_path / "input/docs"
    docs.mkdir(parents=True)
    for filename, text in source.items():
        (docs / filename).write_text(text)
    producer.gen_l2_frs(tmp_path, source)
    actual = json.loads((tmp_path / "phase1/generated_docs/L2_FRS.json").read_text())
    sentence = "The cipher can either encrypt or decrypt, but not both at the same time."
    content = "\n".join(row.get("content", "") for row in actual["frs_sections"])
    assert sentence in content, actual["frs_sections"]


@pytest.mark.parametrize('is_spi', [False, True])
@pytest.mark.parametrize('filename,field,unsupported', [
    ('L10_TEST_CASES.json', 'test_cases_present', 'waveform figures'),
    ('L20_DFT_SCAN_TOPOLOGY.json', 'notes', 'The register state of this design'),
    ('L22_VERIFICATION_PLAN.json', 'notes', "the spec's functional and waveform descriptions"),
])
def test_plain_design_source_provenance_does_not_invent_source_facts(
        tmp_path, is_spi, filename, field, unsupported):
    from programs import spi_protocol_synth as producer
    source = _load_fixture('plain_design_source_provenance')
    assert all('waveform' not in text.lower() for text in source.values())
    generated = tmp_path / 'phase1/generated_docs'
    generated.mkdir(parents=True)
    for name in ('L10_TEST_CASES.json', 'L20_DFT_SCAN_TOPOLOGY.json',
                 'L22_VERIFICATION_PLAN.json'):
        (generated / name).write_text(json.dumps({'test_cases': [], 'fields': {}}))
    producer.apply_spi_synth(generated, is_spi, None)
    document = json.loads((generated / filename).read_text())
    actual = document.get('fields', {}).get(field, document.get(field))
    print({'produced_field': field, 'actual': actual, 'is_spi': is_spi})
    assert isinstance(actual, str) and actual, actual
    assert unsupported not in actual, actual
    assert 'NOT_MEASURED' in actual, actual


@pytest.mark.parametrize('is_spi', [False, True])
def test_plain_design_source_provenance_preserves_existing_source_records(tmp_path, is_spi):
    from programs import spi_protocol_synth as producer
    generated = tmp_path / 'phase1/generated_docs'
    generated.mkdir(parents=True)
    l10 = {'test_cases': [{'id': 'input_case', 'expected': 'output matches input'}],
           'test_cases_present': 'present', 'notes': 'Source supplied a test plan.'}
    l20 = {'fields': {'dft_present': True, 'notes': 'Source declares a scan chain.'}}
    l22 = {'fields': {'verification_plan_present': 'present',
                      'notes': 'Source supplies a formal verification plan.',
                      'coverage_goals': [{'metric': 'source criterion'}]}}
    for name, body in [('L10_TEST_CASES.json', l10), ('L20_DFT_SCAN_TOPOLOGY.json', l20),
                       ('L22_VERIFICATION_PLAN.json', l22)]:
        (generated / name).write_text(json.dumps(body))
    producer.apply_spi_synth(generated, is_spi, None)
    actual10 = json.loads((generated / 'L10_TEST_CASES.json').read_text())
    actual20 = json.loads((generated / 'L20_DFT_SCAN_TOPOLOGY.json').read_text())
    actual22 = json.loads((generated / 'L22_VERIFICATION_PLAN.json').read_text())
    assert actual10['test_cases'] == l10['test_cases']
    assert actual10['test_cases_present'] == 'present'
    assert actual20['fields'] == l20['fields']
    assert actual22['fields']['notes'] == l22['fields']['notes']
    assert actual22['fields']['verification_plan_present'] == 'present'
