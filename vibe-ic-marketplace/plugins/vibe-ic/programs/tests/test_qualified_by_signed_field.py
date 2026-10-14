#!/usr/bin/env python3
"""R-0929-X-QUALIFIED-4 — the reset oracle reads a qualifier ONLY from the
D1-signed structured `qualified_by` field; it never parses a description.

Two oracle-side prose readers produced false PASSes (3, then 23 more in
review_wave58/XQROLES_review.json). The fact now lives on the L9 port row of a
data output as {port, active_level high|low, basis [{file, line, quote}]} and
is trusted only when (1) it is well formed, (2) every quotation is verbatim on
its line of a design-input file, (3) the D1 receipt is valid for the current
bytes AND the signed expectations carry exactly this fact, and (4) the strict
rules hold (multi-bit output, 1-bit qualifier, never clock or reset). Each
refusal is pinned here with its known positive; the iverilog arms show a
signed field exempts, an unsigned one does not, and a signed one never exempts
a cycle where the qualifier is asserted. chip-AGNOSTIC synthetic fixtures.
"""
from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _qualified_by as qb  # noqa: E402
import reset_invariant_oracle_tb_gen as riv  # noqa: E402
from _ai_judgement_fixture import sign  # noqa: E402
from _qualified_by_fixture import (INPUT_DOC, sign_field, stage_field,  # noqa: E402
                                   write_expectation)

_IN = [("clk", ""), ("rst_n", ""), ("d", "[7:0]")]
_OUT = [("o_data", "[7:0]"), ("o_we", ""), ("o_cyc", ""), ("o_flag", "")]
_EXCL = ("clk", "rst_n")


_NATIVE_DOC = """# Neutral write interface

module widget(input clk_i, input rst_i, output [7:0] payload_o, output commit_o, output status_o);

| Name | Width | Direction | Description |
| --- | --- | --- | --- |
| clk_i | 1-bit | input | clock |
| rst_i | 1-bit | input | active-high synchronous reset |
| payload_o | 8-bit | output | write data on the storage channel |
| commit_o | 1-bit | output | write enable on the storage channel |
| status_o | 1-bit | output | status |
The designer chooses this storage protocol and its write-enable active level.
"""


def _native_qualified_project(tmp_path, level="high"):
    import phase1_doc_one_shot_runner as docs
    p = tmp_path / "native"
    source = p / "input/docs/interface.md"
    source.parent.mkdir(parents=True)
    source.write_text(_NATIVE_DOC)
    extracted = {source.name: source.read_text()}
    docs.gen_l1_datasheet(p, extracted)
    result = docs.gen_l9_integration_spec(p, extracted, {})
    contract = docs.qualified_output_input_contract(p, json.loads(result.path.read_text()))
    lines = _NATIVE_DOC.splitlines()
    basis = [{"file": "input/docs/interface.md", "line": i + 1, "quote": line}
             for i, line in enumerate(lines) if "| payload_o |" in line or "| commit_o |" in line]
    polarity_basis = [{"file": "input/docs/interface.md", "line": len(lines), "quote": lines[-1]}]
    contract["qualifiers"] = [{"output": "payload_o", "port": "commit_o",
                               "active_level": level, "output_role": "write_data",
                               "qualifier_role": "write_enable", "channel": "storage",
                               "basis": basis, "polarity": {
                                   "kind": "designer_choice", "decision": f"commit_o active {level}",
                                   "basis": polarity_basis}}]
    author = p / docs.QUALIFIED_OUTPUT_INPUT
    author.parent.mkdir(parents=True)
    author.write_text(json.dumps(contract))
    return p, extracted, result.path, author, contract


def _native_qualified_expectation(contract):
    row = contract["qualifiers"][0]
    return {"id": f"qualified_by:{row['output']}", "layer": "L9_INTEGRATION_SPEC",
            "field_path": "top_ports", "requirement": "independently reviewed write-data validity",
            "basis": row["basis"], "expected_tokens": [row["output"], row["port"], row["active_level"]],
            "qualified_by": {key: row[key] for key in ("output", "port", "active_level")}}


@pytest.mark.parametrize("level", ["high", "low"])
def test_native_qualified_input_normal_producer_and_independent_consumer(tmp_path, level):
    import phase1_doc_one_shot_runner as docs
    import phase1_expert_parse_track as expert
    p, extracted, l9, author, contract = _native_qualified_project(tmp_path, level)
    author_bytes = author.read_bytes()
    docs.gen_l9_integration_spec(p, extracted, {})
    emitted = json.loads(l9.read_text())
    expected = {key: contract["qualifiers"][0][key] for key in ("port", "active_level", "basis")}
    for key in ("ports", "top_ports", "top_module_pins"):
        fields = {r["name"]: r["qualified_by"] for r in emitted[key] if "qualified_by" in r}
        assert fields == {"payload_o": expected}
    assert author.read_bytes() == author_bytes
    assert emitted["qualified_output_authoring"]["review"] == "PENDING_INDEPENDENT_D1"
    answer = _native_qualified_expectation(contract)
    comparison = expert.converge_ai_expectation(p, answer)
    assert comparison["usable"] and comparison["met"]
    assert comparison["scope"] == "exact_qualified_output_relation"
    # The native writer/reader cannot credit or sign its own relation.
    found, ignored = qb.trusted_qualifiers(p, [("payload_o", "[7:0]"), ("commit_o", "")], [])
    assert found == {} and "not signed by the D1" in ignored["payload_o"]
    assert not list(p.rglob("SIG*"))
    schema = expert.authoring_schema(p)
    assert schema["qualified_output_expectation"]["input"] == docs.QUALIFIED_OUTPUT_INPUT


@pytest.mark.parametrize("mutation,reason", [
    ("stale_input", "input_files"), ("stale_roster", "interface"),
    ("duplicate_output", "duplicate output"), ("unknown_field", "unknown field"),
    ("missing_polarity", "malformed qualifier"), ("bad_polarity", "explicit polarity"),
    ("bad_level", "active_level"), ("one_bit_data", "multi-bit"),
    ("input_qualifier", "one-bit"), ("multi_bit_qualifier", "one-bit"),
    ("foreign_quote", "design-input"), ("false_quote", "not on"),
    ("bool_line", "types"), ("status_role", "write-data"),
    ("empty_channel", "same-channel"), ("duplicate_json_key", "duplicate JSON key"),
])
def test_native_qualified_input_refusal_preserves_previous_l9(tmp_path, mutation, reason):
    import copy
    import phase1_doc_one_shot_runner as docs
    p, extracted, l9, author, original = _native_qualified_project(tmp_path)
    data = copy.deepcopy(original)
    row = data["qualifiers"][0]
    if mutation == "stale_input": data["input_files"]["input/docs/interface.md"] = "0" * 64
    elif mutation == "stale_roster": data["interface"][0]["width"] = 2
    elif mutation == "duplicate_output": data["qualifiers"].append(copy.deepcopy(row))
    elif mutation == "unknown_field": row["PASS"] = True
    elif mutation == "missing_polarity": del row["polarity"]
    elif mutation == "bad_polarity": row["polarity"]["kind"] = "inferred_from_name"
    elif mutation == "bad_level": row["active_level"] = "active_high"
    elif mutation == "one_bit_data": row["output"] = "status_o"
    elif mutation == "input_qualifier": row["port"] = "clk_i"
    elif mutation == "multi_bit_qualifier": row["port"] = "payload_o"
    elif mutation == "foreign_quote": row["basis"][0]["file"] = "reports/golden.txt"
    elif mutation == "false_quote": row["basis"][0]["quote"] = "payload_o data unrelated to source"
    elif mutation == "bool_line": row["basis"][0]["line"] = True
    elif mutation == "status_role": row["output_role"] = "status"
    elif mutation == "empty_channel": row["channel"] = ""
    raw = json.dumps(data)
    if mutation == "duplicate_json_key": raw = raw[:-1] + ', "schema": "forged"}'
    author.write_text(raw)
    before = l9.read_bytes()
    with pytest.raises(ValueError, match=reason):
        docs.gen_l9_integration_spec(p, extracted, {})
    assert l9.read_bytes() == before
    assert qb.declared_fields(p) == {}


def test_native_qualified_input_describe_cli_is_read_only(tmp_path):
    p, _extracted, l9, author, _contract = _native_qualified_project(tmp_path)
    before = {l9: l9.read_bytes(), author: author.read_bytes()}
    result = subprocess.run([sys.executable, str(PROGRAMS / "phase1_doc_one_shot_runner.py"),
                             str(p), "--describe-qualified-output-input"],
                            text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    contract = json.loads(result.stdout)
    assert contract["qualifiers"] == []
    assert len(contract["interface"]) == 5
    assert all(path.read_bytes() == raw for path, raw in before.items())


@pytest.mark.parametrize("mutation,usable", [("different_level", True), ("foreign_basis", False),
                                           ("bad_id", False), ("missing_fact", False)])
def test_native_qualified_expectation_is_exact_not_a_token_coincidence(tmp_path, mutation, usable):
    import phase1_doc_one_shot_runner as docs
    import phase1_expert_parse_track as expert
    p, extracted, l9, _author, contract = _native_qualified_project(tmp_path)
    docs.gen_l9_integration_spec(p, extracted, {})
    answer = _native_qualified_expectation(contract)
    if mutation == "different_level": answer["qualified_by"]["active_level"] = "low"
    elif mutation == "foreign_basis": answer["basis"][0]["file"] = "reports/golden.txt"
    elif mutation == "bad_id": answer["id"] = "qualified_by:other_o"
    elif mutation == "missing_fact": del answer["qualified_by"]
    # Scattered tokens and an author's claimed met=True cannot satisfy a pair.
    answer["expected_tokens"] = ["payload_o", "commit_o", "high"]
    answer["met"] = True
    result = expert.converge_ai_expectation(p, answer)
    assert result["usable"] is usable
    assert result["met"] is False


def test_native_qualified_expectation_refuses_conflicting_alias(tmp_path):
    import phase1_doc_one_shot_runner as docs
    import phase1_expert_parse_track as expert
    p, extracted, l9, _author, contract = _native_qualified_project(tmp_path)
    docs.gen_l9_integration_spec(p, extracted, {})
    emitted = json.loads(l9.read_text())
    row = next(r for r in emitted["ports"] if r["name"] == "payload_o")
    row["qualified_by"]["active_level"] = "low"
    l9.write_text(json.dumps(emitted))
    result = expert.converge_ai_expectation(p, _native_qualified_expectation(contract))
    assert result["usable"] and not result["met"]
    assert "aliases disagree" in result["observed"]


def test_native_qualified_author_input_is_current_d1_evidence_without_signing(tmp_path):
    import phase1_doc_one_shot_runner as docs
    import ai_signed_judgement as judgement
    p, extracted, l9, author, contract = _native_qualified_project(tmp_path)
    docs.gen_l9_integration_spec(p, extracted, {})
    assert author in judgement.evidence(p, "D1")
    old_l9, old_digest = l9.read_bytes(), judgement.evidence_sha256(p, "D1")
    contract["qualifiers"][0]["active_level"] = "low"
    author.write_text(json.dumps(contract))
    assert judgement.evidence_sha256(p, "D1") != old_digest
    assert l9.read_bytes() == old_l9
    assert not list(p.rglob("SIG*"))


def test_native_qualified_absent_input_keeps_strict_unsigned_outputs(tmp_path):
    import phase1_doc_one_shot_runner as docs
    p, extracted, l9, author, _contract = _native_qualified_project(tmp_path)
    author.unlink()
    docs.gen_l9_integration_spec(p, extracted, {})
    assert qb.declared_fields(p) == {}
    assert "qualified_output_authoring" not in json.loads(l9.read_text())


@pytest.mark.parametrize("initially_present,change", [(False, "create"), (True, "change"), (True, "delete")])
def test_native_qualified_phase1_reuse_detects_author_choice_change(tmp_path, initially_present, change):
    import phase1_doc_one_shot_runner as docs
    import _phase1_producer_identity as identity
    p, extracted, l9, author, contract = _native_qualified_project(tmp_path)
    if not initially_present:
        author.unlink()
    before = identity.input_tree_snapshot(p)
    recorder = identity.ProducerRecorder()
    with recorder:
        docs.gen_l1_datasheet(p, extracted)
        docs.gen_l9_integration_spec(p, extracted, {})
    identity.stamp(p, recorder, input_before=before, knobs={"mode": "docs"})
    assert identity.assess(p, PROGRAMS)["state"] == identity.REUSE
    unrelated = p / "plugin_input/unrelated.json"
    unrelated.write_text('{"value":1}')
    assert identity.assess(p, PROGRAMS)["state"] == identity.REUSE
    old_l9 = l9.read_bytes()
    if change == "delete":
        author.unlink()
    else:
        contract["qualifiers"][0]["active_level"] = "low"
        author.write_text(json.dumps(contract))
    decision = identity.assess(p, PROGRAMS)
    assert decision["state"] == identity.REGENERATE
    assert decision["reason"] == identity.DESIGN_INPUT_CHANGED
    assert l9.read_bytes() == old_l9


@pytest.mark.parametrize("change", ["different_level", "delete", "malformed", "stale_roster"])
def test_native_qualified_normal_refresh_reconsumes_author_authority(tmp_path, change):
    import phase1_doc_one_shot_runner as docs
    import _staged_top_module as selected
    p, extracted, l9, author, contract = _native_qualified_project(tmp_path)
    docs.gen_l9_integration_spec(p, extracted, {})
    before = l9.read_bytes()
    if change == "delete": author.unlink()
    elif change == "malformed": author.write_text('{')
    elif change == "stale_roster":
        contract["interface"][0]["width"] = 2
        author.write_text(json.dumps(contract))
    else:
        contract["qualifiers"][0]["active_level"] = "low"
        author.write_text(json.dumps(contract))
    if change == "different_level":
        refreshed = selected.refresh_selected_interface(p, l9, json.loads(before), include_synthesis_handoff=True)
        for key in ("ports", "top_ports", "top_module_pins"):
            assert next(r for r in refreshed[key] if r["name"] == "payload_o")["qualified_by"]["active_level"] == "low"
        stable = l9.read_bytes()
        selected.refresh_selected_interface(p, l9, json.loads(stable), include_synthesis_handoff=True)
        assert l9.read_bytes() == stable
    else:
        with pytest.raises(ValueError):
            selected.refresh_selected_interface(p, l9, json.loads(before), include_synthesis_handoff=True)
        assert l9.read_bytes() == before


def _proj(tmp_path):
    p = tmp_path / "proj"
    (p / "phase1/generated_docs").mkdir(parents=True)
    (p / "phase1/generated_docs/L9_INTEGRATION_SPEC.json").write_text(
        json.dumps({"top_ports": [
            {"name": "o_data", "direction": "output", "width": 8,
             "description": "write data"},
            {"name": "o_we", "direction": "output", "width": 1,
             "description": "write enable"}]}))
    return p


def _trusted(p):
    return qb.trusted_qualifiers(p, _OUT, _IN, excluded=_EXCL)


def test_a_signed_field_is_trusted_and_cites_its_basis(tmp_path):
    p = _proj(tmp_path)
    sign_field(p, "o_data", "o_we", "high")
    found, ignored = _trusted(p)
    assert ignored == {}
    (row,) = found["o_data"]
    assert row["qualifier"] == "o_we" and row["active"] == "1"
    assert row["basis"] == "signed_field"
    assert f"{INPUT_DOC}:5" in row["evidence"] and "D1-signed" in row["evidence"]
    assert riv.declared_output_qualifiers(p, _OUT, _IN) == found


def test_active_low_is_the_declared_level(tmp_path):
    p = _proj(tmp_path)
    sign_field(p, "o_data", "o_we", "low")
    assert _trusted(p)[0]["o_data"][0]["active"] == "0"


def test_no_d1_receipt_means_ignored(tmp_path):
    p = _proj(tmp_path)
    stage_field(p, "o_data", "o_we", "high")
    write_expectation(p, "o_data", "o_we", "high")
    found, ignored = _trusted(p)
    assert found == {} and "not signed by the D1" in ignored["o_data"]


def test_a_stale_receipt_means_ignored(tmp_path):
    p = _proj(tmp_path)
    sign_field(p, "o_data", "o_we", "high")
    l9 = p / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    doc = json.loads(l9.read_text())
    doc["top_ports"][0]["qualified_by"]["active_level"] = "low"   # edited after
    l9.write_text(json.dumps(doc))
    found, ignored = _trusted(p)
    assert found == {} and "not signed" in ignored["o_data"]


def test_a_receipt_without_the_matching_expectation_means_ignored(tmp_path):
    p = _proj(tmp_path)
    stage_field(p, "o_data", "o_we", "high")
    write_expectation(p, "o_data", "o_we", "low")      # the expert said low
    sign(p, "D1")
    found, ignored = _trusted(p)
    assert found == {} and "carry no 'qualified_by:o_data' fact" in \
        ignored["o_data"]
    q = _proj(tmp_path / "b")
    stage_field(q, "o_data", "o_we", "high")
    sign(q, "D1")                                        # no expectation at all
    assert _trusted(q)[0] == {}


@pytest.mark.parametrize("basis,why", [
    ([], "non-empty"),
    ([{"file": INPUT_DOC, "line": 5, "quote": "write enable"}], "is not on"),
    ([{"file": INPUT_DOC, "line": 99, "quote": "write data"}], "is not on"),
    ([{"file": "reports/golden.txt", "line": 1, "quote": "golden text"}],
     "not a design-input file"),
    ([{"file": INPUT_DOC, "line": "5", "quote": "write data"}], "integer line"),
])
def test_a_basis_must_quote_the_design_input_verbatim(tmp_path, basis, why):
    p = _proj(tmp_path)
    sign_field(p, "o_data", "o_we", "high", basis=basis)
    found, ignored = _trusted(p)
    assert found == {} and why in ignored["o_data"]


@pytest.mark.parametrize("output,port,level,width,why", [
    ("o_flag", "o_we", "high", 1, "not a multi-bit data output"),
    ("o_data", "d", "high", 8, "not a 1-bit OUTPUT"),
    ("o_data", "rst_n", "high", 8, "not a 1-bit OUTPUT"),
    ("o_data", "clk", "high", 8, "not a 1-bit OUTPUT"),
    ("o_data", "o_data", "high", 8, "not a 1-bit OUTPUT"),
    ("o_data", "o_we", "asserted", 8, "exactly 'high' or 'low'"),
])
def test_the_strict_rules_still_bind_a_signed_field(tmp_path, output, port,
                                                    level, width, why):
    p = _proj(tmp_path)
    sign_field(p, output, port, level, row_width=width)
    found, ignored = _trusted(p)
    assert output not in found and why in ignored[output]


def test_the_oracle_never_reads_a_description(tmp_path):
    """The XQROLES classes (low-active spellings, flags, cross-channel pairs,
    高態有效) are all prose: with no signed field, none of them exempts."""
    p = _proj(tmp_path)
    l9 = p / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    l9.write_text(json.dumps({
        "top_ports": [
            {"name": "o_data", "direction": "output", "width": 8,
             "description": "write data, valid when o_we = 1"},
            {"name": "o_we", "direction": "output", "width": 1,
             "description": "write enable, low active"}],
        "integration": {"external_interface": [{
            "source": INPUT_DOC, "heading": "Write port",
            "evidence": ("| Sub-port | 描述 |\n|---|---|\n"
                         "| `o_data` | write data |\n"
                         "| `o_we` | write enable |\n")}]}}))
    assert riv.declared_output_qualifiers(p, _OUT, _IN) == {}


# ── iverilog: signed exempts, unsigned does not, asserted never ────────────
_CASE = {"name": "rst_glitch", "stimulus": "rst_n glitch 不應導致 bus race",
         "expected": "holds"}


def _simulate(p, tmp_path, we_value):
    path = os.pathsep.join(("/foss/tools/bin", os.environ.get("PATH", "")))
    for tool in ("iverilog", "vvp"):
        if shutil.which(tool, path=path) is None:
            pytest.fail(f"{tool}: command not found — this arm simulates the "
                        f"generated testbench and this host has no {tool}")
    import testbench_gen as tbg
    ports = ([("input", w, n) for n, w in _IN]
             + [("output", w, n) for n, w in _OUT])
    tb = tbg._emit_case_reset_invariant_oracle(p, _CASE, "dut", ports,
                                               tmp_path, {})
    assert tb is not None
    decl = ["input clk", "input rst_n", "input [7:0] d"] + [
        f"output reg {w} {n}".replace("  ", " ") for n, w in _OUT]
    (tmp_path / "dut.v").write_text(
        f"module dut({', '.join(decl)});\n  always @(posedge clk) if (!rst_n) "
        f"begin o_we <= {we_value}; o_cyc <= 0; o_flag <= 0; end\nendmodule\n")
    env = dict(os.environ, PATH=path)
    b = subprocess.run(["iverilog", "-g2012", "-s", _CASE["name"], "-o",
                        str(tmp_path / "s.vvp"), str(tmp_path / "dut.v"),
                        str(tb)], capture_output=True, text=True, env=env)
    assert b.returncode == 0, b.stderr
    r = subprocess.run(["vvp", "-n", str(tmp_path / "s.vvp")],
                       capture_output=True, text=True, env=env)
    fsf = importlib.import_module("full_stack_functional_tb")
    return fsf.score_transcript(_CASE["name"], r.returncode,
                                r.stdout + r.stderr)["state"], r.stdout


def test_a_signed_field_exempts_in_simulation(tmp_path):
    p = _proj(tmp_path)
    sign_field(p, "o_data", "o_we", "high")
    state, out = _simulate(p, tmp_path, 0)
    assert state == "passed", out
    assert out.count("X_EXEMPT") == 8 and "D1-signed" in out


def test_an_unsigned_field_does_not_exempt_in_simulation(tmp_path):
    p = _proj(tmp_path)
    stage_field(p, "o_data", "o_we", "high")
    write_expectation(p, "o_data", "o_we", "high")
    state, out = _simulate(p, tmp_path, 0)
    assert state == "failed" and "X_EXEMPT" not in out


def test_a_signed_field_never_exempts_an_asserted_qualifier(tmp_path):
    p = _proj(tmp_path)
    sign_field(p, "o_data", "o_we", "low")      # active low, driven 0 = asserted
    state, out = _simulate(p, tmp_path, 0)
    assert state == "failed" and "X_EXEMPT" not in out
    assert "while a declared qualifier is asserted or unknown" in out


# ── review wave58 XQ4 (integrity): the expectations file, §4.05, minors ────
def test_a_design_input_file_named_like_the_expert_pack_cannot_speak_for_it(
        tmp_path):
    """MAJOR 1: the signed fact is read from the expert pack's exact path —
    a design-input file of the same name does not stand in for it."""
    p = _proj(tmp_path)
    stage_field(p, "o_data", "o_we", "high")
    write_expectation(p, "o_data", "o_we", "low")       # the expert: low
    shadow = p / "input/docs/l_doc_expectations.json"
    shadow.write_text(json.dumps({"expectations": [{
        "id": "qualified_by:o_data", "layer": "L9_INTEGRATION_SPEC",
        "qualified_by": {"output": "o_data", "port": "o_we",
                         "active_level": "high"}}]}))
    sign(p, "D1")
    found, ignored = _trusted(p)
    assert found == {} and "'active_level': 'low'" in ignored["o_data"]


def test_the_expert_pack_must_be_in_the_signed_evidence(tmp_path):
    p = _proj(tmp_path)
    stage_field(p, "o_data", "o_we", "high")
    (p / "input/docs/l_doc_expectations.json").write_text(json.dumps(
        {"expectations": [{"id": "qualified_by:o_data",
                           "layer": "L9_INTEGRATION_SPEC",
                           "qualified_by": {"output": "o_data", "port": "o_we",
                                            "active_level": "high"}}]}))
    sign(p, "D1")                                     # no expert pack at all
    found, ignored = _trusted(p)
    assert found == {} and qb.EXPECTATIONS_REL in ignored["o_data"]


@pytest.mark.parametrize("rel", [
    "input/docs/golden/L3.md", "input/docs/oracle/L3.md",
    "phase1/input_doc/score/L3.md", "input/docs/L3_ref.md",
    "input/docs/verified_dut.md",
])
def test_a_basis_in_a_4_05_oracle_file_is_refused(tmp_path, rel):
    """MAJOR 2: a file §4.05 puts out of scope is not design input, even
    under input/docs or phase1/input_doc."""
    p = _proj(tmp_path)
    lines = ["| `o_data` | 8-bit | output | write data |",
             "| `o_we` | 1-bit | output | write enable |"]
    f = p / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("\n".join(lines) + "\n")
    basis = [{"file": rel, "line": 1, "quote": lines[0]},
             {"file": rel, "line": 2, "quote": lines[1]}]
    sign_field(p, "o_data", "o_we", "high", basis=basis)
    found, ignored = _trusted(p)
    assert found == {} and "not a design-input file" in ignored["o_data"]


def test_a_basis_through_a_symlink_out_of_the_input_is_refused(tmp_path):
    p = _proj(tmp_path)
    outside = tmp_path / "elsewhere.md"
    lines = ["| `o_data` | 8-bit | output | write data |",
             "| `o_we` | 1-bit | output | write enable |"]
    outside.write_text("\n".join(lines) + "\n")
    link = p / "input/docs/linked.md"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside)
    basis = [{"file": "input/docs/linked.md", "line": 1, "quote": lines[0]},
             {"file": "input/docs/linked.md", "line": 2, "quote": lines[1]}]
    sign_field(p, "o_data", "o_we", "high", basis=basis)
    found, ignored = _trusted(p)
    assert found == {} and "not a design-input file" in ignored["o_data"]


def test_the_quotes_must_name_both_ports_and_not_be_trivial(tmp_path):
    p = _proj(tmp_path)
    lines = ["| `o_data` | 8-bit | output | write data |",
             "| `o_we` | 1-bit | output | write enable |"]
    only_data = [{"file": INPUT_DOC, "line": 5, "quote": lines[0]}]
    sign_field(p, "o_data", "o_we", "high", quote_lines=lines,
               basis=only_data)
    found, ignored = _trusted(p)
    assert found == {} and "never name 'o_we'" in ignored["o_data"]
    q = _proj(tmp_path / "b")
    tiny = [{"file": INPUT_DOC, "line": 5, "quote": "o"}]
    sign_field(q, "o_data", "o_we", "high", quote_lines=lines, basis=tiny)
    found, ignored = _trusted(q)
    assert found == {} and "shorter than" in ignored["o_data"]


def test_zero_zero_is_one_bit_and_input_strobes_are_refused(tmp_path):
    p = _proj(tmp_path)
    outs = [("o_data", "[7:0]"), ("o_we", "[0:0]"), ("o_flag", "[0:0]")]
    sign_field(p, "o_data", "o_we", "high")
    assert qb.trusted_qualifiers(p, outs, _IN)[0]["o_data"][0][
        "qualifier"] == "o_we"                         # [0:0] is 1-bit
    q = _proj(tmp_path / "b")
    sign_field(q, "o_flag", "o_we", "high", row_width=1)
    assert "o_flag" in qb.trusted_qualifiers(q, outs, _IN)[1]   # [0:0] output
    r = _proj(tmp_path / "c")
    ins = _IN + [("i_stb", "")]
    sign_field(r, "o_data", "i_stb", "high",
               quote_lines=["| `o_data` | 8-bit | output | data |",
                            "| `i_stb` | 1-bit | input | strobe |"])
    found, ignored = qb.trusted_qualifiers(r, _OUT, ins)
    assert found == {} and "an input is held by the testbench" in \
        ignored["o_data"]


def test_the_tb_fail_text_carries_the_refusal_and_every_basis_is_cited(
        tmp_path):
    p = _proj(tmp_path)
    stage_field(p, "o_data", "o_we", "high")          # unsigned
    ins, outs = _IN, _OUT
    q, why = riv.declared_output_qualifiers_and_refusals(p, outs, ins)
    tb = riv.emit_case_oracle_from_ports(_CASE, "dut", ins, outs, [],
                                         qualifiers=q, refusals=why)
    assert "qualified_by ignored: not signed by the D1" in tb
    s = _proj(tmp_path / "s")
    lines = ["| `o_data` | 8-bit | output | write data |",
             "| `o_we` | 1-bit | output | write enable |",
             "| `o_cyc` | 1-bit | output | cycle; o_data and o_we one port |",
             "| `o_flag` | 1-bit | output | o_data o_we group heading |"]
    sign_field(s, "o_data", "o_we", "high", quote_lines=lines)
    q, why = riv.declared_output_qualifiers_and_refusals(s, outs, ins)
    tb = riv.emit_case_oracle_from_ports(_CASE, "dut", ins, outs, [],
                                         qualifiers=q, refusals=why)
    for i in range(4):                                # all four, none cut
        assert f"basis {INPUT_DOC}:{5 + i} " in tb


@pytest.mark.parametrize("link,target_rel", [
    ("input/docs/link.md", "golden/expected_trace.txt"),
    ("phase1/input_doc/x.md", "../../input/docs/golden/expected_trace.txt"),
])
def test_a_symlink_inside_the_input_to_an_oracle_is_refused(tmp_path, link,
                                                            target_rel):
    """review wave58 XQ4 final: the link's own path is in scope, its TARGET
    is a §4.05 oracle inside the same roots — the target decides."""
    p = _proj(tmp_path)
    lines = ["| `o_data` | 8-bit | output | write data |",
             "| `o_we` | 1-bit | output | write enable |"]
    oracle = p / "input/docs/golden/expected_trace.txt"
    oracle.parent.mkdir(parents=True, exist_ok=True)
    oracle.write_text("\n".join(lines) + "\n")
    lp = p / link
    lp.parent.mkdir(parents=True, exist_ok=True)
    lp.symlink_to(target_rel)
    assert lp.resolve() == oracle.resolve()
    basis = [{"file": link, "line": 1, "quote": lines[0]},
             {"file": link, "line": 2, "quote": lines[1]}]
    sign_field(p, "o_data", "o_we", "high", basis=basis)
    found, ignored = _trusted(p)
    assert found == {} and "not a design-input file" in ignored["o_data"]
