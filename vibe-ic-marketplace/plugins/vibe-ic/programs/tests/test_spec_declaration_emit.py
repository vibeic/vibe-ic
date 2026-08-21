"""test_spec_declaration_emit.py — the FREE-CHOICE declaration emitter.

WHAT THESE TESTS ARE FOR
------------------------
`spec_declaration_emit` exists to stop a load-bearing DESIGNER CHOICE from
being carried in prose.  A test suite for it therefore has to prove three
things that a shape-only suite would miss:

  1. The field list is read out of the PROJECT'S OWN SPEC, not baked into the
     program.  Proven by running two projects whose specs enumerate DIFFERENT
     fields and asserting each project gets its own list — a hard-coded table
     cannot satisfy both.
  2. The emitter can REFUSE.  An undetermined REQUIRED field must produce
     rc==1 naming the field and NO file, and the downstream
     `spec_required_artifact_check` must still FAIL.  A program that always
     writes something would turn that gate green against a value nobody chose.
  3. The refusal is not indiscriminate.  The same project with the choices
     declared emits, and the gate PASSes.

Every test drives the real program (subprocess or direct call), so deleting
`spec_declaration_emit.py` fails the file rather than leaving it green.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS_DIR = Path(__file__).resolve().parents[1]
EMITTER = PROGRAMS_DIR / "spec_declaration_emit.py"
GATE = PROGRAMS_DIR / "spec_required_artifact_check.py"

sys.path.insert(0, str(PROGRAMS_DIR))


# --------------------------------------------------------------------------- #
# Fixtures — synthetic projects.  No design name, no PDK, no real cell.
# --------------------------------------------------------------------------- #

DECL_PATH = "plugin_output/declaration.json"

ZH_CONTRACT = """# L7 — verification plan

## 7.0 Plugin declaration requirements

Plugin 在開始 RTL 設計前,**必須**於 `{path}` 聲明下列項目:

| 欄位 | 必填 | 範例值 | 說明 |
|---|---|---|---|
| `bit_order` | ✅ | `"LSB_first"` / `"MSB_first"` | serial bit order |
| `latency_cycles` | ✅ | integer | cycles from reset release |
| `flavour_note` | ⚠️ 資訊性 | `"informational_only"` | not a sign-off condition |
"""

EN_CONTRACT = """# L7 — verification plan

## 7.0 Declaration

The Plugin MUST declare `{path}` before authoring:

| Field | Required | Example |
|---|---|---|
| `handshake_style` | Yes | `"valid_ready"` |
| `endianness` | Yes | `"little"` |
| `pipeline_note` | optional | `"two_stage"` |
"""

NO_TABLE_CONTRACT = """# L7

The Plugin MUST produce `reports/summary.json` at the end of the run.

Some following prose that is not a table at all.
"""

NO_REQUIRED_COLUMN_CONTRACT = """# L7

Plugin **必須**於 `{path}` 聲明:

| 欄位 | 範例值 |
|---|---|
| `frame_polarity` | `"active_high"` |
"""

ODD_MARKER_CONTRACT = """# L7

Plugin **必須**於 `{path}` 聲明:

| 欄位 | 必填 | 範例值 |
|---|---|---|
| `sample_edge` | ¿ | `"rising"` |
"""

# Every row informational: the spec demands a declaration whose table asks for
# nothing mandatory.  Used by the "an empty declaration is not a declaration"
# tests.
ALL_INFORMATIONAL_CONTRACT = """# L7

The Plugin MUST declare `{path}` before authoring:

| Field | Required | Example |
|---|---|---|
| `flavour_note` | informational | `"any"` |
| `vendor_note` | optional | `"any"` |
"""

# `bit_order` informational, `latency_cycles` REQUIRED — lets the emitter emit
# a declaration that legitimately LACKS bit_order, which is what the consumer
# must defer on.
OPTIONAL_BIT_ORDER_CONTRACT = """# L7

The Plugin MUST declare `{path}` before authoring:

| Field | Required | Example |
|---|---|---|
| `bit_order` | optional | `"LSB_first"` |
| `latency_cycles` | Yes | `3` |
"""

TRAVERSING_PATH_CONTRACT = """# L7

The Plugin MUST declare `../../escaped/decl.json` before authoring:

| Field | Required | Example |
|---|---|---|
| `a_choice` | Yes | `"x"` |
"""


def _make_project(tmp_path: Path, doc_body: str, name: str = "proj") -> Path:
    project = tmp_path / name
    docs = project / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "L7_verification_plan.md").write_text(
        doc_body.format(path=DECL_PATH), encoding="utf-8")
    return project


def _run_emit(project: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(EMITTER), str(project), *args],
        capture_output=True, text=True)


def _run_gate(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GATE), str(project)],
        capture_output=True, text=True)


def _declaration(project: Path) -> dict:
    return json.loads((project / DECL_PATH).read_text())


def _provenance(project: Path) -> dict:
    p = project / DECL_PATH
    return json.loads(p.with_name(p.stem + ".provenance.json").read_text())


# --------------------------------------------------------------------------- #
# 1. The field list comes from the SPEC, not from this program
# --------------------------------------------------------------------------- #

def test_field_list_is_read_from_each_project_own_spec(tmp_path):
    """Two projects, two different spec tables, two different field lists.

    A hard-coded field list (which is what a per-design emitter is) cannot
    produce both answers, so this is the test that separates a CAPABILITY from
    a patch named after the design it was written against.
    """
    import spec_declaration_emit as sde

    zh = _make_project(tmp_path, ZH_CONTRACT, "zh")
    en = _make_project(tmp_path, EN_CONTRACT, "en")

    zh_fields = [f["name"] for c in sde.extract_contracts(zh) for f in c["fields"]]
    en_fields = [f["name"] for c in sde.extract_contracts(en) for f in c["fields"]]

    assert zh_fields == ["bit_order", "latency_cycles", "flavour_note"], zh_fields
    assert en_fields == ["handshake_style", "endianness", "pipeline_note"], en_fields
    assert not set(zh_fields) & set(en_fields)


def test_required_tier_comes_from_the_spec_marker(tmp_path):
    import spec_declaration_emit as sde

    zh = _make_project(tmp_path, ZH_CONTRACT, "zh")
    fields = {f["name"]: f for c in sde.extract_contracts(zh) for f in c["fields"]}
    assert fields["bit_order"]["required"] is True
    assert fields["latency_cycles"]["required"] is True
    # "⚠️ 資訊性" — informational, explicitly NOT a sign-off condition.
    assert fields["flavour_note"]["required"] is False
    assert all(f["required_marker_recognized"] for f in fields.values())

    en = _make_project(tmp_path, EN_CONTRACT, "en")
    en_fields = {f["name"]: f for c in sde.extract_contracts(en) for f in c["fields"]}
    assert en_fields["handshake_style"]["required"] is True
    assert en_fields["pipeline_note"]["required"] is False


def test_unreadable_required_marker_is_assumed_required_and_disclosed(tmp_path):
    """An unreadable marker is not a licence to skip the field."""
    import spec_declaration_emit as sde

    p = _make_project(tmp_path, ODD_MARKER_CONTRACT, "odd")
    fields = {f["name"]: f for c in sde.extract_contracts(p) for f in c["fields"]}
    assert fields["sample_edge"]["required"] is True
    assert fields["sample_edge"]["required_marker_recognized"] is False

    r = _run_emit(p)
    assert r.returncode == 1
    assert "sample_edge" in r.stderr
    assert "not recognized" in r.stderr


def test_contradictory_required_marker_resolves_required_and_discloses(tmp_path):
    import spec_declaration_emit as sde

    assert sde._classify_required("✅") == (True, True)
    assert sde._classify_required("⚠️ 資訊性") == (False, True)
    assert sde._classify_required("") == (True, False)
    # "not required" trips BOTH vocabularies — fail closed, but never claim the
    # marker was understood.
    assert sde._classify_required("not required") == (True, False)


def test_missing_required_column_makes_every_field_required(tmp_path):
    import spec_declaration_emit as sde

    p = _make_project(tmp_path, NO_REQUIRED_COLUMN_CONTRACT, "nocol")
    contracts = sde.extract_contracts(p)
    assert contracts and contracts[0]["required_column"] is None
    assert contracts[0]["fields"][0]["required"] is True
    assert contracts[0]["fields"][0]["required_marker_recognized"] is False


def test_must_emit_without_a_field_table_is_not_a_declaration_contract(tmp_path):
    """`MUST produce <file>` alone is a required artifact, not a contract.

    Claiming it as one would make this program try to author every report the
    spec asks for.
    """
    import spec_declaration_emit as sde

    p = tmp_path / "notable"
    docs = p / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "L7.md").write_text(NO_TABLE_CONTRACT, encoding="utf-8")
    assert sde.extract_contracts(p) == []

    r = _run_emit(p)
    assert r.returncode == 3, r.stderr
    assert "NO_CONTRACT" in r.stderr


# --------------------------------------------------------------------------- #
# 2. FALSIFIABILITY — the emitter can refuse, and the gate stays red
# --------------------------------------------------------------------------- #

def test_undetermined_required_field_refuses_names_it_and_writes_nothing(tmp_path):
    p = _make_project(tmp_path, ZH_CONTRACT, "refuse")

    r = _run_emit(p, "--set", "latency_cycles=3")
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    assert "spec_declaration_emit: UNDETERMINED" in r.stderr
    assert "bit_order" in r.stderr
    # The one that WAS supplied must not be reported as missing.
    assert "- latency_cycles:" not in r.stderr
    assert not (p / DECL_PATH).exists(), "a refusal must write no declaration"

    gate = _run_gate(p)
    assert gate.returncode == 1, "the required-artifact gate must stay FAIL"
    assert "FAIL" in gate.stdout


def test_spec_example_value_is_never_adopted_as_the_choice(tmp_path):
    """The example column offers `"LSB_first"` / `"MSB_first"`.

    An emitter that picked one would produce a green run whose bit order was
    chosen by the document author rather than by the designer.
    """
    p = _make_project(tmp_path, ZH_CONTRACT, "noexample")
    r = _run_emit(p, "--set", "latency_cycles=3")
    assert r.returncode == 1
    assert not (p / DECL_PATH).exists()
    # The examples are SHOWN to the operator, never consumed as a value.
    assert "LSB_first" in r.stderr


def test_contract_mode_cannot_turn_the_gate_green(tmp_path):
    """--contract writes OUTSIDE the spec-declared path, by construction."""
    p = _make_project(tmp_path, ZH_CONTRACT, "contractmode")
    r = _run_emit(p, "--contract")
    assert r.returncode == 0
    assert (p / "phase2" / "stage1" / "declaration_contract.json").is_file()
    assert not (p / DECL_PATH).exists()
    assert _run_gate(p).returncode == 1


# --------------------------------------------------------------------------- #
# 3. NO FALSE ALARM — declared choices emit, and the gate goes green
# --------------------------------------------------------------------------- #

def test_all_required_declared_emits_and_the_gate_passes(tmp_path):
    p = _make_project(tmp_path, ZH_CONTRACT, "ok")
    assert _run_gate(p).returncode == 1, "precondition: gate FAILs before emit"

    r = _run_emit(p, "--set", "bit_order=MSB_first", "--set", "latency_cycles=3")
    assert r.returncode == 0, (r.stdout, r.stderr)

    d = _declaration(p)
    assert d["bit_order"] == "MSB_first"
    assert d["latency_cycles"] == 3 and isinstance(d["latency_cycles"], int)

    gate = _run_gate(p)
    assert gate.returncode == 0, gate.stdout
    assert "PASS" in gate.stdout


def test_undetermined_informational_field_is_omitted_not_defaulted(tmp_path):
    p = _make_project(tmp_path, ZH_CONTRACT, "info")
    r = _run_emit(p, "--set", "bit_order=MSB_first", "--set", "latency_cycles=3")
    assert r.returncode == 0

    d = _declaration(p)
    # OMITTED — not "undetermined", not "", not a guess. Every consumer in this
    # repo resolves a missing key to "cannot pair"; a placeholder would have to
    # be special-cased by each of them.
    assert "flavour_note" not in d
    prov = _provenance(p)
    assert prov["fields"]["flavour_note"]["status"] == "undetermined"
    assert prov["undetermined_informational"] == ["flavour_note"]


def test_explicit_null_states_undetermined_out_loud(tmp_path):
    """`--set <field>=null` is how the schema says UNDETERMINED.

    It must never become the VALUE `None` — a key whose value means "no
    answer" is the placeholder this program exists to avoid.
    """
    p = _make_project(tmp_path, ZH_CONTRACT, "explicitnull")

    # On a REQUIRED field an explicit abstention still refuses.
    r = _run_emit(p, "--set", "bit_order=null", "--set", "latency_cycles=3")
    assert r.returncode == 1
    assert "bit_order" in r.stderr and "explicitly declared this field" in r.stderr
    assert not (p / DECL_PATH).exists()

    # On an INFORMATIONAL field it emits, omitting the key.
    r = _run_emit(p, "--set", "bit_order=MSB_first", "--set", "latency_cycles=3",
                  "--set", "flavour_note=null")
    assert r.returncode == 0
    d = _declaration(p)
    assert "flavour_note" not in d
    assert _provenance(p)["fields"]["flavour_note"]["status"] == "undetermined"


def test_rerunning_the_emitter_does_not_discard_an_earlier_choice(tmp_path):
    """A second run with fewer --set flags must not silently drop a field."""
    p = _make_project(tmp_path, ZH_CONTRACT, "idempotent")
    assert _run_emit(p, "--set", "bit_order=MSB_first",
                     "--set", "latency_cycles=3",
                     "--set", "flavour_note=some_note").returncode == 0
    assert _declaration(p)["flavour_note"] == "some_note"

    r = _run_emit(p)          # no flags at all
    assert r.returncode == 0, (r.stdout, r.stderr)
    d = _declaration(p)
    assert d["bit_order"] == "MSB_first"
    assert d["latency_cycles"] == 3
    assert d["flavour_note"] == "some_note"
    prov = _provenance(p)
    # The value came back out of the declaration file, but its PROVENANCE is
    # carried from the previous run's sidecar rather than re-derived — see
    # test_rerun_does_not_launder_the_recovered_from_prose_stamp for why
    # re-deriving it was a laundering channel.
    assert prov["fields"]["bit_order"]["provenance"] == "author_declared"
    assert prov["fields"]["bit_order"]["carried_from_declaration_file"] is True
    assert prov["fields"]["bit_order"]["provenance_verified"] is True


def test_code_assignments_are_not_read_as_a_declaration(tmp_path):
    """`parameter <field> = N` in CODE is inference, not a declaration.

    Accepting it would be indistinguishable in the output from a choice the
    designer actually stated — and inferring a free choice from the artifact is
    the failure mode this program retires.
    """
    p = _make_project(tmp_path, ZH_CONTRACT, "codeassign")
    rtl = p / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "dut.v").write_text(
        "module dut #(parameter latency_cycles = 7) (input clk);\n"
        "  localparam bit_order = 1;\n"
        "endmodule\n")

    r = _run_emit(p, "--from-rtl-declaration")
    assert r.returncode == 1
    assert "bit_order" in r.stderr and "latency_cycles" in r.stderr
    assert not (p / DECL_PATH).exists()


def test_emit_preserves_keys_a_prior_step_merged_in(tmp_path):
    """A prior step merges catalog/IP keys into the declaration; clobbering
    them would be a regression introduced by this program."""
    p = _make_project(tmp_path, ZH_CONTRACT, "merge")
    out = p / DECL_PATH
    out.parent.mkdir(parents=True)
    out.write_text(json.dumps({"ip_catalog_used": ["some_ip"]}))

    r = _run_emit(p, "--set", "bit_order=MSB_first", "--set", "latency_cycles=3")
    assert r.returncode == 0
    d = _declaration(p)
    assert d["ip_catalog_used"] == ["some_ip"]
    assert d["bit_order"] == "MSB_first"
    assert _provenance(p)["preserved_foreign_keys"] == ["ip_catalog_used"]


# --------------------------------------------------------------------------- #
# 4. Prose recovery is opt-in and stamped
# --------------------------------------------------------------------------- #

RTL_WITH_DECLARED_CHOICES = """//---------------------------------------------------------------
// DECLARED CHOICES (the spec leaves these to the implementer):
//   bit_order      = MSB_first
//   latency_cycles = 4
//---------------------------------------------------------------
module dut (input clk, input rst, output reg q);
  always @(posedge clk) q <= 1'b0;
endmodule
"""


def _add_rtl(project: Path) -> None:
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "dut.v").write_text(RTL_WITH_DECLARED_CHOICES)


def test_rtl_header_recovery_is_opt_in(tmp_path):
    """Without the flag the header comment is invisible — that is the point.

    The default path never reconstructs a free choice from prose; the flag is
    a disclosed legacy escape hatch for designs whose RTL was written before
    the declaration existed.
    """
    p = _make_project(tmp_path, ZH_CONTRACT, "optin")
    _add_rtl(p)

    r = _run_emit(p)
    assert r.returncode == 1
    assert "bit_order" in r.stderr
    assert not (p / DECL_PATH).exists()


def test_rtl_header_recovery_is_stamped_as_recovered_from_prose(tmp_path):
    p = _make_project(tmp_path, ZH_CONTRACT, "recovered")
    _add_rtl(p)

    r = _run_emit(p, "--from-rtl-declaration")
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "RECOVERED FROM PROSE" in r.stdout

    d = _declaration(p)
    assert d["bit_order"] == "MSB_first"
    assert d["latency_cycles"] == 4
    prov = _provenance(p)
    assert sorted(prov["recovered_from_prose"]) == ["bit_order", "latency_cycles"]
    assert prov["fields"]["bit_order"]["provenance"] == "rtl_header_declaration"


def test_author_declaration_beats_the_rtl_header(tmp_path):
    p = _make_project(tmp_path, ZH_CONTRACT, "priority")
    _add_rtl(p)
    r = _run_emit(p, "--from-rtl-declaration", "--set", "bit_order=LSB_first")
    assert r.returncode == 0
    assert _declaration(p)["bit_order"] == "LSB_first"
    prov = _provenance(p)
    assert prov["fields"]["bit_order"]["provenance"] == "author_declared"
    assert prov["recovered_from_prose"] == ["latency_cycles"]


# --------------------------------------------------------------------------- #
# 4a. "COMMENT" MEANS WHAT A LEXER MEANS — code is never read
#
# The predecessor test below (`test_code_assignments_are_not_read_as_a_
# declaration`) only fed BARE `parameter x = 7;` lines, which a line-prefix
# test already rejected — it measured an adjacent quantity and passed while
# the program read code.  These drive the shapes that actually got through.
# --------------------------------------------------------------------------- #

CODE_BEHIND_A_COMMENT_TOKEN = """module dut;
/* verilator lint_off WIDTH */ localparam bit_order = 1;
/* synthesis keep */ parameter latency_cycles = 8;
*/ parameter flavour_note = 4660;
endmodule
"""


@pytest.mark.parametrize("label,body", [
    # An ENTIRE LINE was classified as a comment because it merely STARTED
    # with a comment token, so the CODE after `*/` was scraped into the
    # declaration and stamped `rtl_header_declaration`.
    ("inline_pragma_then_code", CODE_BEHIND_A_COMMENT_TOKEN),
    # Commented-out code is still code — a disabled `localparam` is not a
    # designer stating a choice.
    ("commented_out_code",
     "module dut;\n// localparam bit_order = 1;\n"
     "//parameter latency_cycles = 7;\nendmodule\n"),
    # Prose that MENTIONS the field is not a declaration of it.
    ("prose_mentioning_the_field",
     "module dut;\n// never set bit_order = MSB_first here\n"
     "// TODO decide latency_cycles = 4 later\nendmodule\n"),
    # A trailing comment annotates the CODE on its line; the declaration block
    # the flag exists to read is code-free.
    ("trailing_comment_on_code",
     "module dut;\nlocalparam w = 1; // bit_order = MSB_first\n"
     "localparam v = 2; // latency_cycles = 4\nendmodule\n"),
    # A `//` inside a string literal opens no comment.
    ("string_literal",
     'module dut;\ninitial $display("bit_order = MSB_first");\n'
     'initial $display("latency_cycles = 4");\nendmodule\n'),
])
def test_code_is_never_read_as_a_declaration(tmp_path, label, body):
    p = _make_project(tmp_path, ZH_CONTRACT, "code_" + label)
    rtl = p / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "dut.v").write_text(body)

    r = _run_emit(p, "--from-rtl-declaration")
    assert r.returncode == 1, (label, r.returncode, r.stdout, r.stderr)
    assert "bit_order" in r.stderr and "latency_cycles" in r.stderr
    assert not (p / DECL_PATH).exists(), (
        "%s: a value inferred from CODE satisfied a REQUIRED free choice"
        % label)
    # And the gate it would have flipped stays red.
    assert _run_gate(p).returncode == 1


REAL_DECLARATION_BLOCK_FORMS = """/*
 * DECLARED CHOICES
 *   bit_order = MSB_first
 */
//   latency_cycles      = 4   (chosen to match L3)
module dut (input clk);
endmodule
"""


def test_a_real_declaration_block_is_still_read(tmp_path):
    """NO FALSE ALARM: the tightening above must not break the legacy path.

    Banner decoration, the `*` column of a block comment, extra whitespace and
    a trailing parenthetical are all forms a designer actually writes.
    """
    p = _make_project(tmp_path, ZH_CONTRACT, "realblock")
    rtl = p / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "dut.v").write_text(REAL_DECLARATION_BLOCK_FORMS)

    r = _run_emit(p, "--from-rtl-declaration")
    assert r.returncode == 0, (r.stdout, r.stderr)
    d = _declaration(p)
    assert d["bit_order"] == "MSB_first"
    assert d["latency_cycles"] == 4
    assert sorted(_provenance(p)["recovered_from_prose"]) == [
        "bit_order", "latency_cycles"]


def test_refused_rtl_candidates_are_reported_not_silently_dropped(tmp_path):
    p = _make_project(tmp_path, ZH_CONTRACT, "refusedreport")
    rtl = p / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "dut.v").write_text(
        "module dut;\n// localparam bit_order = 1;\n"
        "// latency_cycles = 4\nendmodule\n")

    r = _run_emit(p, "--from-rtl-declaration")
    assert r.returncode == 1
    assert "commented-out code" in r.stderr, r.stderr
    scan = None
    # The refusal writes no sidecar, so re-run with the field declared and
    # read the scan record from there.
    r2 = _run_emit(p, "--from-rtl-declaration", "--set", "bit_order=LSB_first")
    assert r2.returncode == 0
    scan = _provenance(p)["rtl_declaration_scan"]
    assert scan["enabled"] is True
    assert scan["accepted"] == ["latency_cycles"]
    assert any(x["field"] == "bit_order" and "commented-out" in x["reason"]
               for x in scan["rejected"]), scan["rejected"]


# --------------------------------------------------------------------------- #
# 4b. PROVENANCE IS CARRIED, NOT RECOMPUTED
#
# The declaration file is a resolution SOURCE and a file this program wrote.
# Re-deriving provenance from "where did I read it this time" relabelled every
# prose-recovered field `existing_declaration` on the second, byte-identical
# run and emptied `recovered_from_prose` — one idempotent re-run destroyed the
# only marker that says these values were scraped rather than declared.
# --------------------------------------------------------------------------- #

def _stamp(project: Path) -> tuple:
    prov = _provenance(project)
    return (
        {k: (v.get("provenance"), v.get("recovered_from_prose"))
         for k, v in prov["fields"].items() if v["status"] == "determined"},
        sorted(prov["recovered_from_prose"]),
    )


def test_rerun_does_not_launder_the_recovered_from_prose_stamp(tmp_path):
    p = _make_project(tmp_path, ZH_CONTRACT, "launder")
    _add_rtl(p)

    assert _run_emit(p, "--from-rtl-declaration").returncode == 0
    first_fields, first_list = _stamp(p)
    assert first_list == ["bit_order", "latency_cycles"]
    assert first_fields["bit_order"] == ("rtl_header_declaration", True)

    # RUN 2: byte-identical command, nothing else changed.
    assert _run_emit(p, "--from-rtl-declaration").returncode == 0
    second_fields, second_list = _stamp(p)
    assert second_list == first_list, "an idempotent re-run erased the debt marker"
    assert second_fields == first_fields

    # RUN 3: the opt-in flag dropped entirely.  The flag governs whether NEW
    # values may be recovered; it does not bleach values already recovered.
    assert _run_emit(p).returncode == 0
    third_fields, third_list = _stamp(p)
    assert third_list == first_list
    assert third_fields["bit_order"] == ("rtl_header_declaration", True)
    assert _provenance(p)["fields"]["bit_order"][
        "carried_from_declaration_file"] is True


def test_declaring_the_field_is_what_retires_the_stamp(tmp_path):
    """NO FALSE ALARM: the debt marker is not permanent, it is EARNED off.

    An author who actually declares the field has done the remediation the
    stamp asks for, and that field stops being marked recovered.
    """
    p = _make_project(tmp_path, ZH_CONTRACT, "retire")
    _add_rtl(p)
    assert _run_emit(p, "--from-rtl-declaration").returncode == 0
    assert sorted(_provenance(p)["recovered_from_prose"]) == [
        "bit_order", "latency_cycles"]

    assert _run_emit(p, "--set", "bit_order=LSB_first").returncode == 0
    prov = _provenance(p)
    assert prov["recovered_from_prose"] == ["latency_cycles"]
    assert prov["fields"]["bit_order"]["provenance"] == "author_declared"
    assert prov["fields"]["bit_order"]["recovered_from_prose"] is False


def test_deleting_the_sidecar_does_not_produce_a_clean_declaration(tmp_path):
    """The other route to laundering: remove the record, re-run, look clean.

    A value in the declaration file with no matching provenance record is
    UNVERIFIED — reported, not promoted.  It is not refused, because a
    hand-authored declaration is legitimate and refusing it would trade this
    false-clean for a false alarm.
    """
    p = _make_project(tmp_path, ZH_CONTRACT, "nosidecar")
    _add_rtl(p)
    assert _run_emit(p, "--from-rtl-declaration").returncode == 0
    sidecar = (p / DECL_PATH).with_name("declaration.provenance.json")
    sidecar.unlink()

    r = _run_emit(p)
    assert r.returncode == 0
    assert "PROVENANCE UNVERIFIED" in r.stdout, r.stdout
    prov = _provenance(p)
    assert sorted(prov["existing_without_recorded_provenance"]) == [
        "bit_order", "latency_cycles"]
    assert prov["fields"]["bit_order"]["provenance_verified"] is False

    # ...and --verify surfaces it too, so a flow can act on it.
    v = _run_emit(p, "--verify")
    assert "PROVENANCE UNVERIFIED" in (v.stdout + v.stderr)


def test_editing_the_declaration_invalidates_its_carried_provenance(tmp_path):
    """Keeping the sidecar is not enough — the RECORD must match the VALUE.

    Otherwise a value edited in place inherits the previous run's clean
    provenance and reads as though someone had declared it.
    """
    p = _make_project(tmp_path, ZH_CONTRACT, "edited")
    _add_rtl(p)
    assert _run_emit(p, "--from-rtl-declaration").returncode == 0
    v = _run_emit(p, "--verify")
    assert v.returncode == 0
    assert "PROVENANCE UNVERIFIED" not in (v.stdout + v.stderr)

    out = p / DECL_PATH
    edited = json.loads(out.read_text())
    edited["bit_order"] = "LSB_first"        # silently flipped
    out.write_text(json.dumps(edited))

    v = _run_emit(p, "--verify")
    assert "PROVENANCE UNVERIFIED" in (v.stdout + v.stderr)
    assert "bit_order" in (v.stdout + v.stderr)
    report = json.loads(
        (p / "reports" / "phase2" / "gates"
         / "spec_declaration_verify.json").read_text())
    assert report["provenance_unverified"] == ["bit_order"]

    # The emitter agrees: the edited value no longer carries the old stamp.
    assert _run_emit(p).returncode == 0
    assert _provenance(p)["fields"]["bit_order"]["provenance_verified"] is False


# --------------------------------------------------------------------------- #
# 4c. AN EMPTY DECLARATION IS NOT A DECLARATION
# --------------------------------------------------------------------------- #

def test_all_informational_and_undetermined_writes_nothing(tmp_path):
    """`{}` is 3 bytes, and the presence gate scores `st_size > 0`.

    Writing it turned `spec_required_artifact_check` green on an artifact this
    run created during the same run purely to satisfy it, while declaring
    nothing at all.  The honest outcome is to write nothing and say why.
    """
    p = _make_project(tmp_path, ALL_INFORMATIONAL_CONTRACT, "vacuous")

    r = _run_emit(p)
    assert r.returncode == 4, (r.returncode, r.stdout, r.stderr)
    assert "NOTHING_TO_DECLARE" in r.stderr
    assert not (p / DECL_PATH).exists()
    assert _run_gate(p).returncode == 1, (
        "the presence gate must report the artifact as absent, not green on {}")


def test_one_informational_field_declared_still_emits(tmp_path):
    """NO FALSE ALARM: an all-informational contract is emittable.

    The refusal is about SUBSTANCE, not about required-ness — declare one
    field and the declaration is real.
    """
    p = _make_project(tmp_path, ALL_INFORMATIONAL_CONTRACT, "vacuousok")
    r = _run_emit(p, "--set", "flavour_note=vanilla")
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert _declaration(p) == {"flavour_note": "vanilla"}
    assert _run_gate(p).returncode == 0
    assert _run_emit(p, "--verify").returncode == 0


def test_verify_fails_an_empty_declaration_the_presence_gate_passes(tmp_path):
    """The substance check the presence gate cannot make.

    `spec_required_artifact_check` is NOT modified to close this: it answers
    "does the declared artifact exist and is it non-empty", and that is the
    right question for it to answer.  `--verify` answers the different one.
    """
    # (i) a contract WITH required fields: `{}` fails as missing-required.
    p = _make_project(tmp_path, ZH_CONTRACT, "verifyempty")
    out = p / DECL_PATH
    out.parent.mkdir(parents=True)
    out.write_text("{}")

    assert _run_gate(p).returncode == 0, "precondition: 3 bytes passes presence"
    r = _run_emit(p, "--verify")
    assert r.returncode == 1, (r.stdout, r.stderr)
    assert "bit_order" in r.stderr and "latency_cycles" in r.stderr
    # ...and --verify wrote no declaration of its own.
    assert json.loads(out.read_text()) == {}

    # (ii) the all-informational contract, where there is no required field to
    # miss.  This is the exact shape the emitter now refuses to create, so it
    # can only arise from a hand-planted file — and it must still not pass.
    q = _make_project(tmp_path, ALL_INFORMATIONAL_CONTRACT, "verifyvacuous")
    qout = q / DECL_PATH
    qout.parent.mkdir(parents=True)
    qout.write_text("{}")
    assert _run_gate(q).returncode == 0, "precondition: 3 bytes passes presence"
    r = _run_emit(q, "--verify")
    assert r.returncode == 1, (r.stdout, r.stderr)
    assert "FAIL_VACUOUS" in r.stderr


def test_verify_fails_a_missing_required_field_and_passes_a_real_one(tmp_path):
    p = _make_project(tmp_path, ZH_CONTRACT, "verifyboth")
    out = p / DECL_PATH
    out.parent.mkdir(parents=True)

    out.write_text(json.dumps({"bit_order": "MSB_first"}))
    r = _run_emit(p, "--verify")
    assert r.returncode == 1
    assert "latency_cycles" in r.stderr

    out.write_text(json.dumps({"bit_order": "MSB_first", "latency_cycles": 3}))
    r = _run_emit(p, "--verify")
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "PASS" in r.stdout

    # A placeholder passes presence and byte count; it must not pass substance.
    out.write_text(json.dumps({"bit_order": "TBD", "latency_cycles": 3}))
    assert _run_gate(p).returncode == 0
    assert _run_emit(p, "--verify").returncode == 1


def test_verify_never_creates_the_artifact_it_asserts_on(tmp_path):
    p = _make_project(tmp_path, ZH_CONTRACT, "verifynocreate")
    r = _run_emit(p, "--verify")
    assert r.returncode == 1
    assert "FAIL_ABSENT" in r.stderr
    assert not (p / DECL_PATH).exists()


# --------------------------------------------------------------------------- #
# 4d. A SUPPLIED VALUE IS NOT AUTOMATICALLY A CHOICE
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("value", ["", "   ", "TBD", "tbd", "<fill-me>",
                                   "{{value}}", "${VALUE}", "TODO", "FIXME",
                                   "placeholder", "unspecified"])
def test_a_placeholder_does_not_satisfy_a_required_field(tmp_path, value):
    p = _make_project(tmp_path, ZH_CONTRACT, "ph")
    r = _run_emit(p, "--set", "bit_order=" + value, "--set", "latency_cycles=3")
    assert r.returncode == 1, (value, r.stdout, r.stderr)
    assert "bit_order" in r.stderr
    assert not (p / DECL_PATH).exists()


def test_placeholders_are_refused_through_from_json_too(tmp_path):
    p = _make_project(tmp_path, ZH_CONTRACT, "phjson")
    vals = tmp_path / "vals.json"
    vals.write_text(json.dumps({"bit_order": "TBD", "latency_cycles": ""}))
    r = _run_emit(p, "--from-json", str(vals))
    assert r.returncode == 1
    assert "bit_order" in r.stderr and "latency_cycles" in r.stderr
    assert not (p / DECL_PATH).exists()


@pytest.mark.parametrize("value,expected", [
    ("none", "none"),          # no parity / no flow control IS a choice
    ("n/a", "n/a"),
    ("null_terminated", "null_terminated"),
    ("0", 0),
    ("false", False),
    ("-", "-"),                # a delimiter character IS a choice
    ("_", "_"),
])
def test_values_that_only_look_empty_are_accepted(tmp_path, value, expected):
    """NO FALSE ALARM: the placeholder vocabulary must stay conservative.

    Every token here is a legitimate interface choice in some design, so
    rejecting it would trade the false-clean above for a false alarm on a
    correct one.
    """
    p = _make_project(tmp_path, ZH_CONTRACT, "notph")
    r = _run_emit(p, "--set", "bit_order=" + value, "--set", "latency_cycles=3")
    assert r.returncode == 0, (value, r.stdout, r.stderr)
    assert _declaration(p)["bit_order"] == expected


def test_a_placeholder_already_in_the_file_is_caught_on_rerun(tmp_path):
    p = _make_project(tmp_path, ZH_CONTRACT, "phexisting")
    out = p / DECL_PATH
    out.parent.mkdir(parents=True)
    out.write_text(json.dumps({"bit_order": "TBD", "latency_cycles": 3}))

    r = _run_emit(p)
    assert r.returncode == 1
    assert "bit_order" in r.stderr
    # The bad file is left exactly as it was — a refusal writes nothing.
    assert json.loads(out.read_text()) == {"bit_order": "TBD",
                                           "latency_cycles": 3}


# --------------------------------------------------------------------------- #
# 4e. NOTHING IS WRITTEN OUTSIDE THE PROJECT
# --------------------------------------------------------------------------- #

def test_a_traversing_artifact_path_is_refused(tmp_path):
    """The artifact path comes out of a DOCUMENT, so it is untrusted input."""
    import spec_declaration_emit as sde

    p = _make_project(tmp_path, TRAVERSING_PATH_CONTRACT, "traverse")
    rejected: list = []
    assert sde.extract_contracts(p, rejected) == []
    assert rejected and rejected[0]["artifact_path"] == "../../escaped/decl.json"

    r = _run_emit(p, "--set", "a_choice=x")
    assert r.returncode == 3, (r.returncode, r.stdout, r.stderr)
    assert "REJECTED CLAUSE" in r.stderr
    assert not (tmp_path.parent / "escaped").exists()
    assert not (tmp_path / "escaped").exists()


# --------------------------------------------------------------------------- #
# 5. WIRING — the contract reaches the author at the RTL handoff
# --------------------------------------------------------------------------- #

def test_authoring_handoff_stages_the_declaration_contract(tmp_path):
    """The knowledge an author receives must depend on the fact that it is
    authoring.  This is the same seam the lesson digests use, so all three
    WAIVE branches get the contract for free.

    Imported HARD, never importorskip: a skip here would let "the emitter was
    deleted" masquerade as "the wiring test did not apply".
    """
    import design_one_shot_runner as runner

    p = _make_project(tmp_path, ZH_CONTRACT, "handoff")
    hint, extras = runner._stage_author_knowledge_digests(p)

    assert "declaration_contract" in extras, (
        "the RTL-authoring handoff did not stage the spec's free-choice "
        "declaration contract")
    assert extras["declaration_field_count"] == 3
    assert extras["declaration_required_count"] == 2
    assert Path(extras["declaration_contract"]).is_file()
    assert "DECLARE YOUR FREE CHOICES FIRST" in hint
    # It must NOT have authored the declaration itself.
    assert not (p / DECL_PATH).exists()


def test_authoring_handoff_is_silent_when_the_spec_has_no_contract(tmp_path):
    import design_one_shot_runner as runner

    p = tmp_path / "nodecl"
    docs = p / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "L7.md").write_text(NO_TABLE_CONTRACT, encoding="utf-8")

    hint, extras = runner._stage_author_knowledge_digests(p)
    assert "declaration_contract" not in extras
    assert "DECLARE YOUR FREE CHOICES FIRST" not in hint


# --------------------------------------------------------------------------- #
# 6. The consumer really does defer on an absent choice
# --------------------------------------------------------------------------- #

def test_consumer_defers_when_a_choice_is_absent_and_pairs_when_present(tmp_path):
    """Closes the loop the declaration exists for: the comparison procedure
    must pair from the DECLARATION, and must refuse to pair without it.

    Both declarations are produced by the REAL emitter, not hand-written.
    Hand-writing them made this the one test in the file that stayed green
    with `spec_declaration_emit.py` deleted — a consumer-side assertion that
    measured nothing about the program the file is named after.  `import`, not
    `importorskip`, for the same reason: a skip would let "the module is gone"
    masquerade as "this test did not apply".
    """
    import arith_oracle_tb_gen as gen

    # A spec whose `bit_order` is informational, so the emitter legitimately
    # emits a declaration WITHOUT it — the state the consumer must defer on.
    absent = _make_project(tmp_path, OPTIONAL_BIT_ORDER_CONTRACT, "consumer_no")
    r = _run_emit(absent, "--set", "latency_cycles=3")
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "bit_order" not in _declaration(absent)
    assert gen.read_declared_conventions(absent, []) is None, (
        "an absent bit_order must read as 'cannot pair', never as a default")

    present = _make_project(tmp_path, ZH_CONTRACT, "consumer_yes")
    r = _run_emit(present, "--set", "bit_order=MSB_first",
                  "--set", "latency_cycles=3")
    assert r.returncode == 0, (r.stdout, r.stderr)
    conv = gen.read_declared_conventions(present, [])
    assert conv is not None and conv["bit_order"] == "MSB" and conv["latency"] == 3


# --------------------------------------------------------------------------- #
# Round 3 — the laundering routes that survived round 2
#
# Every test below has a measured tripping input and a paired control.  The
# shape they all attack is the same one: a guard that fires on the FIRST
# offending run and forgets on the second, or a guard whose comparison is
# looser than the thing it claims to compare.
# --------------------------------------------------------------------------- #

def test_the_unverified_mark_survives_repeated_reruns(tmp_path):
    """Deleting the sidecar must not launder a field on the run AFTER next.

    Round 2 stopped one run too early.  The unverified fallback writes a
    sidecar record saying `status: determined` for a value nothing accounts
    for; a carry predicate that only checks "does the record match the file"
    is then satisfied by the record THIS PROGRAM wrote about its own doubt,
    and re-run 2 stamped the field `provenance_verified: True` with the
    warning gone.  The doubt has to be STICKY.
    """
    p = _make_project(tmp_path, ZH_CONTRACT, "sticky")
    _add_rtl(p)
    assert _run_emit(p, "--from-rtl-declaration").returncode == 0
    (p / DECL_PATH).with_name("declaration.provenance.json").unlink()

    for run in range(1, 4):          # three consecutive identical re-runs
        r = _run_emit(p)
        assert r.returncode == 0, (run, r.stdout, r.stderr)
        assert "PROVENANCE UNVERIFIED" in r.stdout, (run, r.stdout)
        prov = _provenance(p)
        assert sorted(prov["existing_without_recorded_provenance"]) == [
            "bit_order", "latency_cycles"], (run, prov)
        assert prov["fields"]["bit_order"]["provenance_verified"] is False, run
        v = _run_emit(p, "--verify")
        assert "PROVENANCE UNVERIFIED" in (v.stdout + v.stderr), run

    # ...and DECLARING the field is what clears it, so the mark is earned off
    # rather than permanent (the false-alarm direction).
    assert _run_emit(p, "--set", "bit_order=LSB_first").returncode == 0
    prov = _provenance(p)
    assert prov["fields"]["bit_order"]["provenance_verified"] is not False
    assert prov["existing_without_recorded_provenance"] == ["latency_cycles"]


def test_an_edited_declaration_stays_unverified_on_every_later_rerun(tmp_path):
    """The same one-run-too-early hole on the edit-in-place route."""
    p = _make_project(tmp_path, ZH_CONTRACT, "editedsticky")
    _add_rtl(p)
    assert _run_emit(p, "--from-rtl-declaration").returncode == 0
    out = p / DECL_PATH
    edited = json.loads(out.read_text())
    edited["bit_order"] = "LSB_first"
    out.write_text(json.dumps(edited))

    for run in range(1, 4):
        r = _run_emit(p)
        assert r.returncode == 0, run
        assert "PROVENANCE UNVERIFIED" in r.stdout, (run, r.stdout)
        assert _provenance(p)["fields"]["bit_order"][
            "provenance_verified"] is False, run


@pytest.mark.parametrize("planted,label", [
    ({"bit_order": None, "latency_cycles": None}, "every required field null"),
    ({"bit_order": "MSB_first", "latency_cycles": None}, "one required null"),
])
def test_json_null_does_not_satisfy_a_required_field(tmp_path, planted, label):
    """`null` is refused at the --set door; it must be refused at this one too.

    An all-null declaration passed emit, passed the presence gate, and passed
    `--verify`, which printed "declared with a real value" about a file in
    which no value existed.
    """
    p = _make_project(tmp_path, ZH_CONTRACT, "nulls")
    (p / "plugin_output").mkdir(parents=True)
    (p / DECL_PATH).write_text(json.dumps(planted))

    r = _run_emit(p)
    assert r.returncode == 1, (label, r.stdout, r.stderr)
    assert "null" in r.stderr, r.stderr
    # The bad file is left exactly as found rather than rewritten.
    assert json.loads((p / DECL_PATH).read_text()) == planted

    v = _run_emit(p, "--verify")
    assert v.returncode == 1, (label, v.stdout, v.stderr)
    report = json.loads(
        (p / "reports" / "phase2" / "gates"
         / "spec_declaration_verify.json").read_text())
    assert report["verdict"].startswith("FAIL")
    assert [e["field"] for e in report["placeholder_required"]]

    # The presence gate still PASSES on the same bytes — the two checks are
    # provably measuring different quantities.
    assert _run_gate(p).returncode == 0


def test_null_is_refused_through_every_door(tmp_path):
    """--set, --from-json and the declaration file must all say the same thing."""
    p = _make_project(tmp_path, ZH_CONTRACT, "nulldoors")
    r = _run_emit(p, "--set", "bit_order=null", "--set", "latency_cycles=null")
    assert r.returncode == 1

    src = tmp_path / "vals.json"
    src.write_text(json.dumps({"bit_order": None, "latency_cycles": None}))
    r = _run_emit(p, "--from-json", str(src))
    assert r.returncode == 1, (r.stdout, r.stderr)
    assert not (p / DECL_PATH).exists()


def test_an_empty_container_is_still_a_declaration(tmp_path):
    """The false-alarm control for the null fix.

    `[]` and `{}` and `0` and `false` are choices a designer can legitimately
    have made (no optional extensions, count zero, active-low).  Only `null`
    — the spelling that MEANS "no answer" — is refused.
    """
    p = _make_project(tmp_path, ZH_CONTRACT, "containers")
    (p / "plugin_output").mkdir(parents=True)
    (p / DECL_PATH).write_text(
        json.dumps({"bit_order": [], "latency_cycles": 0}))
    assert _run_emit(p).returncode == 0
    assert _run_emit(p, "--verify").returncode == 0
    assert _run_gate(p).returncode == 0

    p2 = _make_project(tmp_path, ZH_CONTRACT, "containers2")
    (p2 / "plugin_output").mkdir(parents=True)
    (p2 / DECL_PATH).write_text(
        json.dumps({"bit_order": {}, "latency_cycles": False}))
    assert _run_emit(p2).returncode == 0
    assert _run_emit(p2, "--verify").returncode == 0


@pytest.mark.parametrize("declared,edited", [
    (1, True),          # 1 == True in Python
    (0, False),         # 0 == False in Python
    (1, 1.0),           # 1 == 1.0 in Python
])
def test_a_type_coerced_edit_does_not_inherit_the_old_stamp(
        tmp_path, declared, edited):
    """`record['value'] == existing[name]` is not "the same declared value".

    Editing `latency_cycles: 1` to `true` slipped past the value-match guard
    in ONE run and was stamped verified, with the boolean written back into
    the declaration for a consumer that expects an integer.
    """
    p = _make_project(tmp_path, ZH_CONTRACT, "coerce_%s" % type(edited).__name__)
    assert _run_emit(p, "--set", "bit_order=MSB_first",
                     "--set", "latency_cycles=%s" % declared).returncode == 0
    out = p / DECL_PATH
    doc = json.loads(out.read_text())
    doc["latency_cycles"] = edited
    out.write_text(json.dumps(doc))

    r = _run_emit(p)
    assert r.returncode == 0
    assert "PROVENANCE UNVERIFIED" in r.stdout, r.stdout
    prov = _provenance(p)
    assert prov["fields"]["latency_cycles"]["provenance_verified"] is False
    assert prov["existing_without_recorded_provenance"] == ["latency_cycles"]

    v = _run_emit(p, "--verify")
    report = json.loads(
        (p / "reports" / "phase2" / "gates"
         / "spec_declaration_verify.json").read_text())
    assert "latency_cycles" in report["provenance_unverified"], report


def test_an_unedited_value_keeps_its_stamp(tmp_path):
    """The false-alarm control for the type-strict comparison."""
    p = _make_project(tmp_path, ZH_CONTRACT, "notedited")
    assert _run_emit(p, "--set", "bit_order=MSB_first",
                     "--set", "latency_cycles=1").returncode == 0
    for _ in range(3):
        r = _run_emit(p)
        assert r.returncode == 0
        assert "PROVENANCE UNVERIFIED" not in r.stdout, r.stdout
        prov = _provenance(p)
        assert prov["fields"]["latency_cycles"]["provenance_verified"] is True
        assert prov["existing_without_recorded_provenance"] == []


def test_a_carried_rtl_stamp_that_its_source_contradicts_is_not_verified(
        tmp_path):
    """A stamp naming a file the file itself no longer supports.

    The declaration file outranks the RTL comment, so the value is kept — but
    the only evidence for the `rtl_header_declaration` stamp is the sidecar
    this program wrote, and the file it names now says something else.
    """
    p = _make_project(tmp_path, ZH_CONTRACT, "diverged")
    _add_rtl(p)
    assert _run_emit(p, "--from-rtl-declaration").returncode == 0
    assert _provenance(p)["fields"]["bit_order"]["provenance_verified"] is True

    rtl = p / "phase2" / "stage1" / "rtl" / "dut.v"
    rtl.write_text(RTL_WITH_DECLARED_CHOICES.replace("MSB_first", "LSB_first"))

    r = _run_emit(p, "--from-rtl-declaration")
    assert r.returncode == 0
    assert "PROVENANCE UNVERIFIED" in r.stdout, r.stdout
    assert "LSB_first" in r.stdout, r.stdout
    prov = _provenance(p)["fields"]["bit_order"]
    assert prov["provenance_verified"] is False
    assert prov["provenance_diverged"] is True
    # The value itself is untouched: the declaration file is the stronger tier.
    assert _declaration(p)["bit_order"] == "MSB_first"


def test_an_unchanged_rtl_block_keeps_its_stamp(tmp_path):
    """The false-alarm control for the divergence check."""
    p = _make_project(tmp_path, ZH_CONTRACT, "notdiverged")
    _add_rtl(p)
    for _ in range(3):
        r = _run_emit(p, "--from-rtl-declaration")
        assert r.returncode == 0
        assert "PROVENANCE UNVERIFIED" not in r.stdout, r.stdout
        prov = _provenance(p)["fields"]["bit_order"]
        assert prov["provenance_verified"] is True
        assert prov.get("provenance_diverged") is None
        assert _provenance(p)["recovered_from_prose"] == [
            "bit_order", "latency_cycles"]


@pytest.mark.parametrize("literal", ["1'b0", "3'd5", "4'h1_F", "8'hFF"])
def test_a_verilog_sized_literal_is_refused_not_truncated(tmp_path, literal):
    """The bare-token value class stopped at the apostrophe.

    `1'b0` was read as 1, `3'd5` as 3 and `4'h1_F` as 4 — neither the
    designer's token nor its numeric meaning — and stamped as a full
    `rtl_header_declaration` with nothing in the report to say so.
    """
    p = _make_project(tmp_path, ZH_CONTRACT, "sized_%s" % literal[0] + literal[-1])
    rtl = p / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "dut.v").write_text(
        "//   bit_order = MSB_first\n//   latency_cycles = %s\n" % literal)

    r = _run_emit(p, "--from-rtl-declaration")
    assert r.returncode == 1, (r.stdout, r.stderr)
    assert not (p / DECL_PATH).exists()
    assert "sized literal" in (r.stdout + r.stderr), (r.stdout, r.stderr)
    assert _run_gate(p).returncode == 1


def test_ordinary_rtl_values_are_still_read(tmp_path):
    """The false-alarm control for the sized-literal refusal.

    Includes the shapes the real cells use: a bare token followed by a comma
    and a parenthetical, and a plain decimal.
    """
    p = _make_project(tmp_path, ZH_CONTRACT, "plainvals")
    rtl = p / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "dut.v").write_text(
        "//   bit_order      = LSB_first   (y[0] first, p[0] first)\n"
        "//   latency_cycles = 2           (two cycles later)\n")
    r = _run_emit(p, "--from-rtl-declaration")
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert _declaration(p) == {"bit_order": "LSB_first", "latency_cycles": 2}


def test_stripping_the_verified_flag_from_a_schema2_sidecar_is_not_clean(
        tmp_path):
    """Dropping one KEY must not be cheaper than editing the value.

    Schema 2 writes `provenance_verified` on every determined field, so a
    schema-2 record missing it has been edited; reading the omission as
    "nothing said it was doubtful" would hand back the laundering route the
    sticky mark closes.
    """
    p = _make_project(tmp_path, ZH_CONTRACT, "keystrip")
    _add_rtl(p)
    assert _run_emit(p, "--from-rtl-declaration").returncode == 0
    sidecar = (p / DECL_PATH).with_name("declaration.provenance.json")
    sidecar.unlink()
    assert "PROVENANCE UNVERIFIED" in _run_emit(p).stdout

    doc = json.loads(sidecar.read_text())
    assert doc["schema_version"] == 2
    for rec in doc["fields"].values():
        rec.pop("provenance_verified", None)
    sidecar.write_text(json.dumps(doc))

    r = _run_emit(p)
    assert "PROVENANCE UNVERIFIED" in r.stdout, r.stdout
    assert _provenance(p)["fields"]["bit_order"]["provenance_verified"] is False


def test_a_schema1_sidecar_is_carried_without_a_false_alarm(tmp_path):
    """The paired control: records written before this seam existed.

    Schema 1 has no `provenance_verified` key anywhere and never encoded
    doubt, so treating its absence as doubt would fire on every declaration
    already on disk — including the prose-recovery stamp, which must survive.
    """
    p = _make_project(tmp_path, ZH_CONTRACT, "schema1")
    _add_rtl(p)
    assert _run_emit(p, "--from-rtl-declaration").returncode == 0
    sidecar = (p / DECL_PATH).with_name("declaration.provenance.json")
    doc = json.loads(sidecar.read_text())
    doc["schema_version"] = 1
    for rec in doc["fields"].values():
        rec.pop("provenance_verified", None)
        rec.pop("carried_from_declaration_file", None)
    sidecar.write_text(json.dumps(doc))

    r = _run_emit(p)
    assert r.returncode == 0
    assert "PROVENANCE UNVERIFIED" not in r.stdout, r.stdout
    prov = _provenance(p)
    assert prov["recovered_from_prose"] == ["bit_order", "latency_cycles"]
    assert prov["fields"]["bit_order"]["provenance"] == "rtl_header_declaration"


# ---------------------------------------------------------------------------
# The SAME generator writes two spellings of the DECLARED CHOICES block, and
# this reader accepted only one.  A design that had declared all of its free
# choices was reported as having declared none — the reader's failure to parse
# published as the designer's failure to declare.  Measured across the tracked
# spm variants: some write `field = value`, one aligns the value in a column.
# ---------------------------------------------------------------------------

RTL_ALIGNED_COLUMN = """\
// spm - bit-serial multiplier
//
// DECLARED CHOICES (L7 7.0 - mirrored in the declaration)
//   bit_order            MSB_first     y is streamed MSB-first
//   latency_cycles       4             y[i] sampled at edge t
//
// ALGORITHM  (the recurrence below is the choice made here)
//   acc = acc + x when y_t is set; the shift is what makes it serial
//   latency_cycles       999           THIS prose must not be read
module dut (input clk, input rst, output reg q);
  always @(posedge clk) q <= 1'b0;
endmodule
"""


def _emit_with_rtl(tmp_path, rtl_text):
    project = _make_project(tmp_path, ZH_CONTRACT)
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "dut.v").write_text(rtl_text)
    return project, _run_emit(project, "--from-rtl-declaration")


def test_an_aligned_column_block_is_read_like_the_equals_form(tmp_path):
    """The column layout is a declaration, not prose."""
    project, r = _emit_with_rtl(tmp_path, RTL_ALIGNED_COLUMN)
    assert r.returncode == 0, r.stderr
    decl = _declaration(project)
    assert decl["bit_order"] == "MSB_first"
    assert decl["latency_cycles"] == 4


def test_the_aligned_form_is_confined_to_the_declared_choices_block(tmp_path):
    """`latency_cycles 999` in the ALGORITHM prose must not be read.

    The block anchor is what makes the column gap safe: without it, any comment
    with two spaces after a field name would become a declaration.
    """
    project, r = _emit_with_rtl(tmp_path, RTL_ALIGNED_COLUMN)
    assert r.returncode == 0, r.stderr
    assert _declaration(project)["latency_cycles"] == 4, "read the prose line"


def test_prose_spacing_is_still_not_a_declaration(tmp_path):
    """One space is prose; a column is a layout.  The gap is the discriminator."""
    text = RTL_ALIGNED_COLUMN.replace(
        "//   bit_order            MSB_first     y is streamed MSB-first",
        "//   bit_order is MSB_first as discussed")
    _project, r = _emit_with_rtl(tmp_path, text)
    assert r.returncode == 1, "single-space prose was accepted as a declaration"


def test_a_near_miss_is_named_rather_than_reported_as_absent(tmp_path):
    """"I did not find it" and "I found it and could not read it" differ.

    Reporting the second as the first is what led a reader to conclude a design
    had never declared its free choices at all.
    """
    text = RTL_ALIGNED_COLUMN.replace(
        "//   bit_order            MSB_first     y is streamed MSB-first",
        "//   bit_order is MSB_first as discussed")
    _project, r = _emit_with_rtl(tmp_path, text)
    assert r.returncode == 1
    assert "NOT read from" in r.stderr, r.stderr
    assert "bit_order" in r.stderr
    assert "dut.v:" in r.stderr, "the near miss must carry file:line"
    assert "DECLARED CHOICES" in r.stderr, "must say what form would be read"


def test_the_block_closes_at_the_next_heading(tmp_path):
    """A block running to end-of-comments would put every paragraph in scope."""
    sys.path.insert(0, str(PROGRAMS_DIR))
    import spec_declaration_emit as M
    scanned = M._scan_declaration_lines(RTL_ALIGNED_COLUMN)
    inside = M._declaration_block_lines(scanned)
    bodies = {ln: t.strip() for ln, t in scanned}
    assert inside, "the block was not detected at all"
    for ln in inside:
        assert "acc = acc + x" not in bodies[ln], "ALGORITHM prose is in scope"
        assert "999" not in bodies[ln], "the prose latency line is in scope"
    assert any("bit_order" in bodies[ln] for ln in inside)
