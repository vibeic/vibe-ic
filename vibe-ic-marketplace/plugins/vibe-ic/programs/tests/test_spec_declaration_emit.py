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
    assert prov["fields"]["bit_order"]["provenance"] == "existing_declaration"


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
    must pair from the DECLARATION, and must refuse to pair without it."""
    gen = pytest.importorskip("arith_oracle_tb_gen")

    p = _make_project(tmp_path, ZH_CONTRACT, "consumer")
    out = p / DECL_PATH
    out.parent.mkdir(parents=True)

    out.write_text(json.dumps({"latency_cycles": 3}))
    assert gen.read_declared_conventions(p, []) is None, (
        "an absent bit_order must read as 'cannot pair', never as a default")

    out.write_text(json.dumps({"bit_order": "MSB_first", "latency_cycles": 3}))
    conv = gen.read_declared_conventions(p, [])
    assert conv is not None and conv["bit_order"] == "MSB" and conv["latency"] == 3
