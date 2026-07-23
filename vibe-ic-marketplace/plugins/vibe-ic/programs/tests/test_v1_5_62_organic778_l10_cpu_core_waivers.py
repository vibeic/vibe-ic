"""ORGANIC #778 companion — l10_tb_conformance_check CPU-core interface-class
waivers (subservient x sky130A / subservient x gf180mcuD, v1.5.60 fresh
flow_compliance_check runs — a processor_cpu-class reused-IP RISC-V core).

DEFECT: ALL 10 L10 `functional_vector` cases hard-FAILed Step 4 with zero
evidence. Investigation on the real subservient project showed the FAIL
class splits into three genuinely different dispositions:

  1. `reset_n_cycle_instruction` — a REAL, groundable boot-latency oracle
     (see `cpu_boot_latency_oracle_tb_gen.py` + its testbench_gen wiring) —
     tested separately, not here.
  2. `plugin_m_mul_div` / `plugin_zicsr_csr_access_timer_irq` /
     `plugin_c_16_bit_compressed` — each case's OWN stimulus text carries an
     explicit CONDITIONAL marker ("(若 Plugin 選 <token>)") referencing an
     OPTIONAL, Plugin-selectable ISA extension. This project's
     `declaration.json` (required by the L2 spec for exactly this decision)
     was never produced — so the gate cannot confirm the referenced feature
     was selected for this build. Demanding TB evidence for an unconfirmed-
     selected optional feature would either false-FAIL a legitimately
     unselected feature, or require FABRICATING a golden for hardware that
     may not exist (§4.05). FIX: `is_conditional_optional_case` +
     `conditional_feature_declared` WAIVE these as
     `cap:conditional_feature_undeclared` (NEW, distinct from the broader
     CPU-oracle gap — the root cause here is a MISSING DECLARATION).
  3. The remaining cases (`blinky_hex`, `hello_hex`, `rv32i_40`, `zifencei`,
     `reset_assert_sram`, `i_rst_glitch_instruction_fetch_race`) genuinely
     require a full instruction-set/program-level oracle this pass does not
     author. FIX: `is_functional_vector` + `cpu_oracle_anchor` WAIVE these as
     `cap:cpu_functional_oracle` when `sim/results.xml` carries that
     capability-gap token (mirrors ORGANIC #773's analog A/M-track waiver,
     auto-detected — no CLI flag needed).

chip-AGNOSTIC: the conditional-optional grammar is pure parenthetical-marker
regex (no chip/vendor/extension-name literal — the token is whatever the
design's own doc names); the CPU-oracle waiver is a KIND vocabulary + a
results.xml capability-gap token, mirroring #773's pattern exactly.

§4.05 NO-LEAK:
  - A conditional-optional case whose feature IS confirmed declared in
    declaration.json is NOT waived — it still requires TB evidence.
  - A genuine digital case (cmd_response, no conditional grammar, no
    functional_vector kind) with no evidence STILL FAILs regardless of any
    sibling waiver firing, and regardless of whether results.xml carries the
    CPU-oracle capability-gap token.
  - An UNANCHORED cpu-oracle waiver (no results.xml, or a results.xml
    without the exact token) does NOT waive a functional_vector case — it
    still FAILs.
"""
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "l10_tb_conformance_check.py"
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import l10_tb_conformance_check as gate  # noqa: E402


def _make_project(tmp_path, l10_cases, *, declaration=None,
                  cpu_oracle_anchor=True,
                  tb_text="module tb_dummy;\nendmodule\n"):
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    l10 = gd / "L10_TEST_CASES.json"
    l10.write_text(json.dumps({"test_cases": l10_cases}))

    sim = tmp_path / "phase2" / "stage1" / "sim"
    tb = sim / "tb"
    tb.mkdir(parents=True)
    (tb / "tb_dummy.v").write_text(tb_text)
    work = sim / "work"
    work.mkdir(parents=True)
    summary = work / "summary.txt"
    summary.write_text("")

    if cpu_oracle_anchor:
        (sim / "results.xml").write_text(
            "<results><verdict>CONNECTIVITY_PASS</verdict>"
            "<capability_gap>cap:cpu_functional_oracle</capability_gap>"
            "<functional_verified>false</functional_verified></results>")

    if declaration is not None:
        po = tmp_path / "plugin_output"
        po.mkdir(parents=True, exist_ok=True)
        (po / "declaration.json").write_text(json.dumps(declaration))

    return l10, tb, summary


# ---------------------------------------------------------------------------
# is_conditional_optional_case / conditional_feature_declared — unit level
# ---------------------------------------------------------------------------
def test_is_conditional_optional_case_extracts_token_chinese():
    case = {"stimulus": "(若 Plugin 選 M) Mul/Div 指令", "expected": "PASS"}
    assert gate.is_conditional_optional_case(case) == "M"


def test_is_conditional_optional_case_extracts_token_english():
    case = {"stimulus": "(if the plugin selects Zicsr) CSR access",
            "expected": "PASS"}
    assert gate.is_conditional_optional_case(case) == "Zicsr"


def test_is_conditional_optional_case_none_for_unconditional_text():
    case = {"stimulus": "整套 RV32I 指令(40+ 條)單元測試", "expected": "100% PASS"}
    assert gate.is_conditional_optional_case(case) is None


def test_conditional_feature_declared_true_when_present(tmp_path):
    (tmp_path / "plugin_output").mkdir(parents=True)
    (tmp_path / "plugin_output" / "declaration.json").write_text(
        json.dumps({"isa_extensions": ["M", "Zicsr"]}))
    assert gate.conditional_feature_declared(str(tmp_path), "M") is True
    assert gate.conditional_feature_declared(str(tmp_path), "C") is False


def test_conditional_feature_declared_false_when_no_declaration_file(tmp_path):
    assert gate.conditional_feature_declared(str(tmp_path), "M") is False


# ---------------------------------------------------------------------------
# FIX — conditional-optional case WAIVED when declaration.json absent
# ---------------------------------------------------------------------------
def test_conditional_optional_cases_waived_without_declaration(tmp_path):
    cases = [
        {"name": "plugin_m_mul_div", "kind": "functional_vector",
         "stimulus": "(若 Plugin 選 M) Mul/Div 指令", "expected": "PASS"},
        {"name": "plugin_zicsr_csr_access_timer_irq", "kind": "functional_vector",
         "stimulus": "(若 Plugin 選 Zicsr) CSR access + timer IRQ",
         "expected": "PASS"},
        {"name": "plugin_c_16_bit_compressed", "kind": "functional_vector",
         "stimulus": "(若 Plugin 選 C) 16-bit compressed 指令", "expected": "PASS"},
    ]
    l10, tb, summary = _make_project(tmp_path, cases, cpu_oracle_anchor=False)
    out = tmp_path / "out.json"
    rc = gate.main(["--l10", str(l10), "--tb-dir", str(tb),
                    "--summary", str(summary), "--out", str(out),
                    "--project", str(tmp_path)])
    assert rc == 3
    data = json.loads(out.read_text())
    assert data["waived"] == 3 and data["fail"] == 0
    for r in data["results"]:
        assert r["status"] == "waived"
        assert r["capability_gap"] == gate.CAP_CONDITIONAL_FEATURE_UNDECLARED


def test_conditional_optional_case_NOT_waived_when_declared(tmp_path):
    """§4.05 NO-LEAK: once declaration.json confirms the feature WAS
    selected, the case is no longer undecidable — it must still require
    real TB evidence (this fix waives the UNCONFIRMED case, never a
    confirmed-selected one)."""
    cases = [
        {"name": "plugin_m_mul_div", "kind": "functional_vector",
         "stimulus": "(若 Plugin 選 M) Mul/Div 指令", "expected": "PASS"},
    ]
    l10, tb, summary = _make_project(
        tmp_path, cases, cpu_oracle_anchor=False,
        declaration={"isa_extensions": ["M"]})
    out = tmp_path / "out.json"
    rc = gate.main(["--l10", str(l10), "--tb-dir", str(tb),
                    "--summary", str(summary), "--out", str(out),
                    "--project", str(tmp_path)])
    assert rc == 1, "a CONFIRMED-selected feature must still require TB evidence"
    data = json.loads(out.read_text())
    assert data["fail"] == 1 and data["waived"] == 0


# ---------------------------------------------------------------------------
# FIX — generic CPU functional-oracle waiver (mirrors #773, auto-detected)
# ---------------------------------------------------------------------------
def test_functional_vector_cases_waived_under_cpu_oracle_anchor(tmp_path):
    cases = [
        {"name": "blinky_hex", "kind": "functional_vector",
         "stimulus": "GPIO toggle", "expected": "I-mem fetch, GPIO write"},
        {"name": "rv32i_40", "kind": "functional_vector",
         "stimulus": "RV32I instruction suite", "expected": "100% PASS"},
    ]
    l10, tb, summary = _make_project(tmp_path, cases, cpu_oracle_anchor=True)
    out = tmp_path / "out.json"
    rc = gate.main(["--l10", str(l10), "--tb-dir", str(tb),
                    "--summary", str(summary), "--out", str(out),
                    "--project", str(tmp_path)])
    assert rc == 3
    data = json.loads(out.read_text())
    assert data["waived"] == 2 and data["fail"] == 0
    for r in data["results"]:
        assert r["capability_gap"] == gate.CAP_CPU_FUNCTIONAL_ORACLE


def test_functional_vector_case_with_real_evidence_not_waived(tmp_path):
    """A case whose id genuinely appears in the TB blob (a REAL oracle was
    authored — e.g. cpu_boot_latency_oracle_tb_gen's output) is credited as
    a real pass, never routed through the waiver at all."""
    cases = [
        {"name": "reset_n_cycle_instruction", "kind": "functional_vector",
         "stimulus": "Reset 解除後 N cycle 內取得第一條 instruction",
         "expected": "N <= 10 cycle"},
    ]
    l10, tb, summary = _make_project(
        tmp_path, cases, cpu_oracle_anchor=True,
        tb_text="module reset_n_cycle_instruction;\n"
                "  wire w;\n"
                "  subservient u_dut (.i_clk(w));\n"
                "// real oracle content (a live DUT instantiation, not a\n"
                "// vacuous placeholder), no ORACLE_NONE marker\n"
                "endmodule\n")
    out = tmp_path / "out.json"
    rc = gate.main(["--l10", str(l10), "--tb-dir", str(tb),
                    "--summary", str(summary), "--out", str(out),
                    "--project", str(tmp_path)])
    assert rc == 0
    data = json.loads(out.read_text())
    assert data["ok"] == 1 and data["waived"] == 0 and data["fail"] == 0


# ---------------------------------------------------------------------------
# §4.05 NO-LEAK — neither waiver may mask a genuine digital defect
# ---------------------------------------------------------------------------
def test_noleak_digital_cmd_response_still_fails_under_both_anchors(tmp_path):
    cases = [
        {"name": "plugin_m_mul_div", "kind": "functional_vector",
         "stimulus": "(若 Plugin 選 M) Mul/Div 指令", "expected": "PASS"},
        {"name": "GET_ID_DIGITAL", "category": "cmd_response", "opcode": "70"},
    ]
    l10, tb, summary = _make_project(tmp_path, cases, cpu_oracle_anchor=True)
    out = tmp_path / "out.json"
    rc = gate.main(["--l10", str(l10), "--tb-dir", str(tb),
                    "--summary", str(summary), "--out", str(out),
                    "--project", str(tmp_path)])
    assert rc == 1, "digital cmd_response with no evidence must STILL FAIL"
    data = json.loads(out.read_text())
    by_id = {r["id"]: r for r in data["results"]}
    assert by_id["GET_ID_DIGITAL"]["status"] == "fail"
    assert by_id["plugin_m_mul_div"]["status"] == "waived"
    assert data["fail"] == 1 and data["waived"] == 1


def test_noleak_functional_vector_unanchored_still_fails(tmp_path):
    """No results.xml at all (or none carrying the exact token) → the
    CPU-oracle waiver must NOT fire — a functional_vector case with no
    evidence still FAILs."""
    cases = [
        {"name": "rv32i_40", "kind": "functional_vector",
         "stimulus": "RV32I instruction suite", "expected": "100% PASS"},
    ]
    l10, tb, summary = _make_project(tmp_path, cases, cpu_oracle_anchor=False)
    out = tmp_path / "out.json"
    rc = gate.main(["--l10", str(l10), "--tb-dir", str(tb),
                    "--summary", str(summary), "--out", str(out),
                    "--project", str(tmp_path)])
    assert rc == 1
    data = json.loads(out.read_text())
    assert data["fail"] == 1 and data["waived"] == 0
