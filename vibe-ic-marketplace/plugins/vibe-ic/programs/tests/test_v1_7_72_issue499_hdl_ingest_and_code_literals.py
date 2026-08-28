"""tests/test_v1_7_72_issue499_hdl_ingest_and_code_literals.py — v1.7.72

Regression cover for GitHub issue #499 — five defects that together made
Phase 1 unable to pass a design from its own inputs, and one of which
made a dropped document look like a clean result.

  D1  `extract_one()` had no `.sv` / `.v` / `.svh` / `.vh` branch, so an
      HDL package a design staged as its stated ground truth converted
      to the empty string. A `typedef enum` harvester then has to READ
      what arrives.
  D2  the field-encoding lifter could not see the Verilog-literal form
      (`2'b01`) that the CONSUMING GATE's own regex finds in the very
      description the lifter walked past.
  D3  RST grid-table continuation rows were dropped, truncating a field
      description mid-clause.
  D4  Phase-1 coverage was computed only over documents that extracted,
      so a dropped document could not lower it — `254/254 = 100.0%`.
  D5  (found by measuring D1, not filed) the RTL-as-oracle guard's
      `\\.sv$` clause could not tell the IP's own generated RTL from an
      HDL document the design itself staged, and aborted the run.

Every test drives a real entry point and reads an observable result:
the converters, the shared reader both sides import, the gates'
executables, and the emitted report files. None asserts on source text.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import _code_literal as CL
import _hdl_enum as HE
import _input_ingest as II
import l4_regmap_enumerated_values_typed_check as L4GATE
from programs.phase1_one_shot_runner import (  # noqa: F401
    extract_one,
    extract_text_pipeline,
)
import phase1_doc_one_shot_runner as RUNNER

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_PROGRAMS = Path(RUNNER.__file__).resolve().parent


# ═══════════════════════════════════════════════════════════════════════
# D1 — the HDL converter branch
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("suffix", [".sv", ".v", ".svh", ".vh"])
def test_hdl_source_is_ingested_not_dropped(tmp_path: Path,
                                            suffix: str) -> None:
    """The defect verbatim: a 0-character return for a non-empty file."""
    f = tmp_path / f"pkg{suffix}"
    body = "package p;\n  localparam int W = 8;\nendpackage\n"
    f.write_text(body, encoding="utf-8")
    assert extract_one(f) != ""
    assert "localparam int W = 8" in extract_one(f)


def test_hdl_document_reaches_the_extracted_map(tmp_path: Path) -> None:
    """End-to-end through the ingester, and OFF the skip log."""
    proj = tmp_path / "proj"
    docs = proj / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "overview.md").write_text("# Part\nprose\n", encoding="utf-8")
    (docs / "types.sv").write_text(
        "package t;\n  typedef enum logic [1:0] {\n"
        "    A = 2'b00,\n    B = 2'b01\n  } mode_state_e;\nendpackage\n",
        encoding="utf-8")

    out = extract_text_pipeline(proj)
    assert any(k.endswith("types.sv") for k in out), list(out)

    skipped = II.read_skip_log(proj)
    assert skipped is not None
    assert [e["path"] for e in skipped["skipped"]] == []
    assert skipped["total_visited"] == skipped["total_extracted"] == 2


# ═══════════════════════════════════════════════════════════════════════
# D1b — the harvester, and its refusal to invent
# ═══════════════════════════════════════════════════════════════════════

def test_typedef_enum_members_and_widths_are_read() -> None:
    enums = HE.parse_typedef_enums(
        "typedef enum logic [6:0] {\n"
        "  OP_LOAD  = 7'h03,  // load\n"
        "  OP_STORE = 7'h23\n"
        "} opcode_e;\n")
    assert len(enums) == 1
    e = enums[0]
    assert e["type_name"] == "opcode_e"
    assert e["declared_width"] == 7
    assert e["enum_role"] == HE.ROLE_OPCODE
    assert [(m["name"], m["value"]) for m in e["members"]] == [
        ("OP_LOAD", 3), ("OP_STORE", 35)]


def test_no_typedef_enum_yields_nothing() -> None:
    """A file with no enum invents none."""
    assert HE.parse_typedef_enums(
        "module m(input clk);\n  always_ff @(posedge clk) q <= d;\n"
        "endmodule\n") == []
    assert HE.parse_typedef_enums("") == []


def test_valueless_enum_carries_names_without_inventing_encodings() -> None:
    """SystemVerilog's implicit numbering is a language default, not a
    statement the document made — it must not appear as one."""
    e = HE.parse_typedef_enums(
        "typedef enum logic [3:0] {\n  RESET,\n  BOOT,\n  RUN\n"
        "} ctrl_fsm_e;\n")[0]
    assert [m["name"] for m in e["members"]] == ["RESET", "BOOT", "RUN"]
    assert all(m["value"] is None and m["literal"] is None
               for m in e["members"])


def test_unknown_bits_are_not_an_encoding() -> None:
    e = HE.parse_typedef_enums(
        "typedef enum logic [3:0] { A = 4'bxx01 } s_e;")[0]
    assert e["members"][0]["value"] is None


def test_enum_role_is_by_whole_segment_not_substring() -> None:
    """`wb_instr_type_e` is an instruction-CLASS encoding, not an opcode
    table. A substring match on "instr" would route it into L3.opcodes
    and fabricate entries the gates would then bless."""
    assert HE.classify_enum_role("ctrl_fsm_e") == HE.ROLE_FSM_STATE
    assert HE.classify_enum_role("mainFsmState_t") == HE.ROLE_FSM_STATE
    assert HE.classify_enum_role("opcode_e") == HE.ROLE_OPCODE
    assert HE.classify_enum_role("cmd_e") == HE.ROLE_OPCODE
    assert HE.classify_enum_role("wb_instr_type_e") is None
    assert HE.classify_enum_role("alu_op_e") is None
    assert HE.classify_enum_role("csr_num_e") is None


def test_harvest_only_reads_hdl_documents() -> None:
    """A `typedef enum` quoted inside a datasheet is illustration, not a
    declaration the design makes."""
    src = "typedef enum logic [1:0] { A = 2'b00, B = 2'b01 } state_e;"
    assert HE.harvest_enums({"spec.md": src}) == []
    assert len(HE.harvest_enums({"pkg.sv": src})) == 1


# ═══════════════════════════════════════════════════════════════════════
# D2 — one code-literal reader for extractor and detector
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("tok,expected", [
    ("2'b01", (2, 1)),
    ("7'h03", (7, 3)),
    ("6'b0", (6, 0)),
    ("12'd5", (12, 5)),
    ("3'o7", (3, 7)),
    ("0x3", (None, 3)),
    ("0b01", (2, 1)),
    ("01", (2, 1)),
    ("4'bxx", None),
    ("2'b1z", None),
    ("hello", None),
])
def test_code_literal_parse(tok, expected) -> None:
    assert CL.parse_code_literal(tok) == expected


def test_binary_rendering_refuses_to_reshape() -> None:
    """A constant stated at six bits is not a thirty-bit encoding."""
    assert CL.to_binary_pattern("2'b01", 2) == "01"
    assert CL.to_binary_pattern("6'b0", 30) is None      # width mismatch
    assert CL.to_binary_pattern("0x3", 2) == "11"        # width-less, fits
    assert CL.to_binary_pattern("0x9", 2) is None        # does not fit
    assert CL.natural_binary_pattern("6'b0") == (6, "000000")
    assert CL.natural_binary_pattern("0x3") is None      # no natural width


def test_sentence_split_survives_abbreviations() -> None:
    got = CL.split_sentences(
        "Aligned to 256 bytes, i.e., ``r[7:2]`` is set to 6'b0. "
        "Always 2'b01 to indicate vectored handling.")
    assert len(got) == 2
    assert got[0].endswith("6'b0.")


def test_gate_and_lifter_share_one_reader() -> None:
    """The anti-drift property, asserted as identity rather than as two
    regexes that happen to agree today (#497 shipped that failure)."""
    assert L4GATE._CODE_LITERAL_RE is CL.CODE_LITERAL_RE
    assert RUNNER._CODE_LITERAL_RE is CL.CODE_LITERAL_RE
    field = {"field_name": "MODE", "bits": "1:0",
             "description": "Always set to 2'b01 to indicate vectored "
                            "interrupt handling (read-only)."}
    assert L4GATE._declared_codes(field) == CL.declared_codes(field)
    assert L4GATE._field_text(field) == CL.field_text(field)


def test_lifter_binds_the_literal_the_gate_requires() -> None:
    """The defect's exact shape: the gate saw one declared code and the
    layer carried zero bindings."""
    field = {"field_name": "MODE", "bits": "1:0",
             "description": "Always set to 2'b01 to indicate vectored "
                            "interrupt handling (read-only)."}
    assert L4GATE._declared_codes(field) == ["2'b01"]
    assert L4GATE._binding_entries(field) == 0          # before

    RUNNER._v1_6_512_lift_field_encoding(field, field["description"])

    assert L4GATE._binding_entries(field) >= len(L4GATE._declared_codes(field))
    entry = field["encoding"][0]
    assert entry["pattern"] == "01"
    assert entry["code"] == "2'b01"
    assert "vectored interrupt handling" in entry["meaning"]


def test_narrower_literal_keeps_its_own_width_and_names_its_slice() -> None:
    """`mtvec[7:2] is always set to 6'b0` constrains six bits. Rendering
    it at the enclosing field's width would claim the whole field is
    zero."""
    field = {"field_name": "BASE", "bits": "31:2",
             "description": "The trap-vector base address, always aligned "
                            "to 256 bytes, i.e., ``mtvec[7:2]`` is always "
                            "set to 6'b0."}
    RUNNER._v1_6_512_lift_field_encoding(field, field["description"])
    entry = field["encoding"][0]
    assert entry["pattern"] == "000000"
    assert entry["pattern_width"] == 6
    assert entry["applies_to_bits"] == "7:2"
    assert L4GATE._binding_entries(field) >= 1


def test_lifter_declines_a_multi_code_sentence() -> None:
    """Two codes in one sentence is an enumeration; binding both to the
    same whole-sentence meaning would be worse than not binding them.
    The earlier tiers own that shape and carry a per-code mnemonic."""
    field = {"field_name": "SEL", "bits": "1:0",
             "description": "Set 2'b00 for slow and 2'b11 for fast."}
    n = RUNNER._v1_7_72_lift_code_literal_encoding(field, 2, [], set())
    assert n == 0


def test_lifter_reaches_a_field_with_no_mention_anchor() -> None:
    """Through the entry point the RUNNER calls, not the helper.

    Every pre-existing sweep invokes the per-field lifter only from
    inside a window anchored on a field-name or register-name mention.
    A field whose names appear nowhere in the corpus text was therefore
    offered to NO tier — including the code-literal tier, which needs no
    window because it reads the field's own description. Measured before
    this was wired: ONE binding across 106 corpus doc-sets through the
    window loops, twenty when the fields' own text was handed over."""
    registers = [{
        "name": "ZZZ_UNMENTIONED_REG",
        "fields": [{
            "field_name": "QQQ_UNMENTIONED_FIELD",
            "bits": "1:0",
            "description": "Always set to 2'b01 to indicate vectored "
                           "interrupt handling.",
        }],
    }]
    # The corpus text mentions neither name.
    extracted = {"other.txt": "Unrelated prose about something else.\n"}
    n = RUNNER._v1_6_512_lift_encoding_for_registers(registers, extracted)
    assert n >= 1
    fld = registers[0]["fields"][0]
    assert L4GATE._binding_entries(fld) >= 1
    assert fld["encoding"][0]["code"] == "2'b01"


def test_lifter_is_idempotent() -> None:
    field = {"field_name": "MODE", "bits": "1:0",
             "description": "Always set to 2'b01 to indicate vectored "
                            "interrupt handling."}
    RUNNER._v1_6_512_lift_field_encoding(field, field["description"])
    first = json.dumps(field["encoding"], sort_keys=True)
    RUNNER._v1_6_512_lift_field_encoding(field, field["description"])
    assert json.dumps(field["encoding"], sort_keys=True) == first


def test_wide_field_reserved_guard_still_gates_only_the_decimal_tier() -> None:
    """The guard's own comment scopes it to the decimal walker; it was
    written as an early `return` and gated everything after it too."""
    field = {"field_name": "PAD", "bits": "31:0",
             "description": "Counter index 2 = Foo in an unrelated table."}
    RUNNER._v1_6_512_lift_field_encoding(field, field["description"])
    # No 32-bit zero-padded decimal attribution.
    decimal_tier = "field_encoding_decimal_v1_6_517"
    for e in field.get("encoding") or []:
        assert e.get("extraction_strategy") != decimal_tier


# ═══════════════════════════════════════════════════════════════════════
# D3 — RST grid continuation rows
# ═══════════════════════════════════════════════════════════════════════

_GRID = """\
+-------+------------------------------------------------------------+
| Bit#  | Interrupt                                                  |
+-------+------------------------------------------------------------+
| 31:2  | **BASE:** The base address, always aligned to 256 bytes,   |
|       | i.e., ``reg[7:2]`` is always set to 6'b0.                  |
+-------+------------------------------------------------------------+
| 1:0   | **MODE:** Always set to 2'b01 to indicate vectored mode.   |
+-------+------------------------------------------------------------+
"""


def test_continuation_row_is_not_truncated() -> None:
    fields = RUNNER._parse_csr_2col_grid(_GRID)
    base = next(f for f in fields if f["field_name"] == "BASE")
    assert "6'b0" in base["description"]
    assert not base["description"].rstrip().endswith("i.e.,")


def test_unwrapped_grid_is_unchanged_by_the_join() -> None:
    """A table whose rows never wrap must parse exactly as before: the
    join must not merge two independent logical rows."""
    flat = "\n".join(
        ln for ln in _GRID.splitlines()
        if not ln.startswith("|       |"))
    fields = RUNNER._parse_csr_2col_grid(flat)
    assert [f["field_name"] for f in fields] == ["BASE", "MODE"]
    assert fields[0]["description"] == (
        "The base address, always aligned to 256 bytes,")
    assert fields[1]["description"] == (
        "Always set to 2'b01 to indicate vectored mode.")


@pytest.mark.parametrize("text", [
    # Prose.
    "Intro paragraph.\n\nAnother line.\n",
    # A MARKDOWN pipe table. It has no `+---+` separator, so its rows
    # are not RST grid rows. Probing the join with this before trusting
    # it caught the function collapsing all three rows into one.
    "| Bits | Name |\n|------|------|\n| 1:0  | MODE |\n",
    # Ragged cell counts inside a grid — not a continuation.
    "+--+--+\n| a | b |\n| c |\n+--+--+\n",
    # A row missing its trailing pipe.
    "+--+--+\n| a | b\n+--+--+\n",
    # A well-formed grid whose rows do not wrap.
    "+--+--+\n| a | b |\n+--+--+\n",
])
def test_join_is_a_no_op_on_everything_that_does_not_wrap(text) -> None:
    """Byte-identical, including the trailing newline."""
    assert RUNNER._v1_7_72_join_rst_grid_rows(text) == text


def test_join_merges_only_a_genuine_continuation() -> None:
    wrapped = ("+--+--+\n"
               "| 1:0 | MODE: set to |\n"
               "|     | 2'b01 always. |\n"
               "+--+--+\n")
    assert RUNNER._v1_7_72_join_rst_grid_rows(wrapped) == (
        "+--+--+\n| 1:0 | MODE: set to 2'b01 always. |\n+--+--+\n")


# ═══════════════════════════════════════════════════════════════════════
# D4 + the vacuous-pass defect — a dropped document cannot read as a
# clean result. GENERAL: no ibex shape, no `.sv`, an invented extension.
# ═══════════════════════════════════════════════════════════════════════

def _project_with_unreadable_document(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    docs = proj / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "spec.md").write_text(
        "# Widget\n\nA widget with a status register.\n", encoding="utf-8")
    (docs / "commands.qqq").write_text(
        "CMD_READ = 8'h01\nCMD_WRITE = 8'h02\n", encoding="utf-8")
    return proj


def _run(prog: str, *args: str) -> subprocess.CompletedProcess:
    return _pr.run(
        [sys.executable, str(_PROGRAMS / prog), *args],
        capture_output=True, text=True)


@pytest.fixture(scope="module")
def dropped_doc_project(tmp_path_factory) -> Path:
    proj = _project_with_unreadable_document(
        tmp_path_factory.mktemp("dropped"))
    _run("phase1_one_shot_runner.py", str(proj), "--ic-name", "widget")
    return proj


def test_ingester_records_the_drop(dropped_doc_project: Path) -> None:
    unread = II.unread_input_documents(dropped_doc_project)
    assert [e["path"] for e in unread] == ["input/docs/commands.qqq"]
    assert II.input_fully_read(dropped_doc_project) is False


@pytest.mark.parametrize("gate", [
    "l3_opcode_name_coverage_check",
    "l3_opcode_dispatch_key_actionable_check",
])
def test_dropped_document_cannot_produce_a_vacuous_pass(
        dropped_doc_project: Path, gate: str) -> None:
    """THE general defect. Both gates certified "no command protocol in
    input" over input one of whose documents was never read."""
    r = _run(f"{gate}.py", str(dropped_doc_project))
    combined = (r.stdout or "") + (r.stderr or "")
    assert "VACUOUS_PASS" not in combined, combined
    assert "NOT_CHECKED" in combined, combined
    assert r.returncode == 2, combined
    assert "commands.qqq" in combined


@pytest.mark.parametrize("gate", [
    "l3_opcode_name_coverage_check",
    "l3_opcode_dispatch_key_actionable_check",
])
def test_vacuous_pass_survives_when_the_input_was_fully_read(
        tmp_path: Path, gate: str) -> None:
    """The escape is honest and must stay available: a design whose
    input really has no command protocol still gets VACUOUS_PASS."""
    proj = tmp_path / "clean"
    docs = proj / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "spec.md").write_text(
        "# Widget\n\nA widget with a status register.\n", encoding="utf-8")
    _run("phase1_one_shot_runner.py", str(proj), "--ic-name", "widget")
    assert II.input_fully_read(proj) is True

    r = _run(f"{gate}.py", str(proj))
    combined = (r.stdout or "") + (r.stderr or "")
    assert "VACUOUS_PASS" in combined, combined
    assert r.returncode == 0, combined


def test_coverage_report_counts_the_unread_document(
        dropped_doc_project: Path) -> None:
    """`254/254 = 100.0%` while a ground-truth document contributed
    nothing was the shape. The ratio may still read 100 — it measures
    what extracted — but the census beside it must not."""
    js = json.loads(
        (dropped_doc_project / "reports" / "phase1"
         / "extraction_coverage_report.json").read_text())
    overall = js["overall"]
    assert overall["input_documents_visited"] == 2
    assert overall["input_documents_extracted"] == 1
    assert overall["input_documents_unread"] == 1
    assert overall["status"] == "FAIL_INPUT_NOT_FULLY_READ"
    assert [d["path"] for d in js["unread_input_documents"]] == [
        "input/docs/commands.qqq"]

    md = (dropped_doc_project / "reports" / "phase1"
          / "extraction_coverage_report.md").read_text()
    assert "1 UNREAD" in md
    assert "commands.qqq" in md


def test_coverage_gate_blocks_on_a_converter_gap(
        dropped_doc_project: Path) -> None:
    r = _run("phase1_coverage_report_present_check.py",
             str(dropped_doc_project))
    combined = (r.stdout or "") + (r.stderr or "")
    assert r.returncode == 1, combined
    assert "UNREAD" in combined and "commands.qqq" in combined


def test_a_binary_archive_is_not_an_unread_document() -> None:
    """A `.zip` in input/docs is not a document Phase 1 ever meant to
    read; treating it as one would fail every project that ships one."""
    assert II.classify_skip_reason(
        "binary/archive extension '.zip' — not ingested by phase1"
    ) == II.CLASS_DELIBERATE
    assert II.classify_skip_reason(
        "converter for extension '.sv' returned empty") == II.CLASS_UNREAD


def test_a_missing_external_decoder_is_not_a_converter_gap() -> None:
    """A decoder absent from THIS machine blocks an absence claim but is
    not the plugin's defect and must not hard-fail a user's run."""
    tooling = ("legacy binary .doc could not be decoded "
               "(antiword/catdoc/libreoffice unavailable)")
    assert II.classify_skip_reason(tooling) == II.CLASS_UNREAD
    assert II.is_converter_gap(tooling) is False
    assert II.is_converter_gap(
        "converter for extension '.qqq' returned empty") is True


# ═══════════════════════════════════════════════════════════════════════
# D5 — the RTL-as-oracle guard, found by measuring D1
# ═══════════════════════════════════════════════════════════════════════

def test_staged_input_document_is_not_an_oracle_leak(tmp_path: Path) -> None:
    """`input/docs/pkg.sv` is a design INPUT. The guard's `\\.sv$` clause
    could not tell it from the IP's generated RTL and aborted the run."""
    proj = tmp_path / "proj"
    docs = proj / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "pkg.sv").write_text("package p; endpackage\n", encoding="utf-8")
    staged = RUNNER._v1_7_72_staged_input_doc_names(proj)

    doc = {"fsm_tokens": [{"source": "pkg.sv"}],
           "extraction_evidence": {"a": [{"source": "input/docs/pkg.sv"}]}}
    assert RUNNER._assert_no_rtl_oracle_leak_in_l_doc(
        doc, "L6.json", staged_input_docs=staged) == []


def test_generated_rtl_is_still_an_oracle_leak(tmp_path: Path) -> None:
    """The rule this guard exists for is untouched — including when a
    same-named file happens to be staged."""
    proj = tmp_path / "proj"
    docs = proj / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "core.sv").write_text("package p; endpackage\n", encoding="utf-8")
    staged = RUNNER._v1_7_72_staged_input_doc_names(proj)

    for leaked in ("phase2/stage1/rtl/core.sv",
                   "verilog/rtl/core.sv",
                   "harvested from core.sv"):
        doc = {"evidence": [leaked]}
        assert RUNNER._assert_no_rtl_oracle_leak_in_l_doc(
            doc, "L6.json", staged_input_docs=staged), leaked


def test_unstaged_hdl_citation_is_still_a_leak(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    (proj / "input" / "docs").mkdir(parents=True)
    staged = RUNNER._v1_7_72_staged_input_doc_names(proj)
    doc = {"source": "some_generated_module.sv"}
    assert RUNNER._assert_no_rtl_oracle_leak_in_l_doc(
        doc, "L6.json", staged_input_docs=staged)


# ═══════════════════════════════════════════════════════════════════════
# End-to-end: a staged HDL package populates the layers, and a staged
# HDL package with nothing in it populates nothing.
# ═══════════════════════════════════════════════════════════════════════

def _phase1(proj: Path) -> None:
    _run("phase1_one_shot_runner.py", str(proj), "--ic-name", "widget")


def _l(proj: Path, name: str) -> dict:
    return json.loads(
        (proj / "phase1" / "generated_docs" / name).read_text())


def test_staged_enums_populate_l3_and_l6(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    docs = proj / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "spec.md").write_text(
        "# Widget\n\nA command-driven widget.\n", encoding="utf-8")
    (docs / "pkg.sv").write_text(
        "package w;\n"
        "  typedef enum logic [7:0] {\n"
        "    CMD_READ  = 8'h01,\n"
        "    CMD_WRITE = 8'h02\n"
        "  } cmd_e;\n"
        "  typedef enum logic [1:0] {\n"
        "    RESET,\n    ACTIVE,\n    HALT\n"
        "  } ctrl_fsm_e;\n"
        "endpackage\n", encoding="utf-8")
    _phase1(proj)

    ops = _l(proj, "L3_CMD_PROTOCOL.json")["opcodes"]
    assert {o["name"] for o in ops} >= {"CMD_READ", "CMD_WRITE"}
    assert {o["hex"] for o in ops} >= {"0x01", "0x02"}

    states = _l(proj, "L6_CONTROL_LOGIC.json")["fsm_states"]
    names = {s["name"] for s in states}
    assert {"RESET", "ACTIVE", "HALT"} <= names
    # No encodings invented for a valueless enum.
    for s in states:
        if s.get("name") in {"RESET", "ACTIVE", "HALT"}:
            assert "encoding" not in s


def test_hdl_without_enums_adds_nothing(tmp_path: Path) -> None:
    """The refusal half, end to end: an HDL document that declares no
    enum must not produce a single opcode or state."""
    proj = tmp_path / "proj"
    docs = proj / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "spec.md").write_text(
        "# Widget\n\nA widget.\n", encoding="utf-8")
    (docs / "mod.sv").write_text(
        "module widget(input logic clk, output logic q);\n"
        "  always_ff @(posedge clk) q <= ~q;\n"
        "endmodule\n", encoding="utf-8")
    _phase1(proj)

    l3 = _l(proj, "L3_CMD_PROTOCOL.json")
    assert [o for o in l3["opcodes"]
            if (o or {}).get("extraction_strategy", "").startswith(
                "hdl_typedef_enum")] == []
    l6 = _l(proj, "L6_CONTROL_LOGIC.json")
    assert [s for s in l6["fsm_states"]
            if (s or {}).get("extraction_strategy", "").startswith(
                "hdl_typedef_enum")] == []
