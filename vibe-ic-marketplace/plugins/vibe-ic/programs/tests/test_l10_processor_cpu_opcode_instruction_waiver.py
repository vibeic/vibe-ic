"""processor_cpu opcode-instruction oracle waiver — internal-vocabulary
reconciliation for the l10_tb_conformance_check `cap:cpu_functional_oracle`
waiver.

DEFECT (chip-AGNOSTIC, verified on ibex x sky130A, ic_class=processor_cpu):
the `cap:cpu_functional_oracle` waiver — which exists, is anchored by the
runner's `sim/results.xml` capability-gap token, and books CPU instruction
cases as WAIVED-DEFERRED — was STRUCTURALLY UNREACHABLE for every real CPU
core. Its match side (`is_functional_vector`) only recognises
`kind in {functional_vector, functional, functional_test, instruction_test,
cpu_functional}`, but Phase 1's `gen_l10_test_cases` renders a CPU core's L3
opcodes as command-response cases with `kind in {happy_path, pre_wake_false,
addr_max, len_max}`. The two internal vocabularies never met, so all L10 cases
hard-FAILed Step 4 by construction, independent of RTL quality.

FIX: `is_cpu_instruction_oracle_case` reconciles the vocabularies on the MATCH
side, deliberately NARROWER than `is_functional_vector` — four independent
gates (ic_class==processor_cpu AND opcode-instruction kind AND no explicit
digital cmd_response category AND a structured opcode signal), plus the
caller's anchor gate.

§4.05 NO-LEAK — the BIDIRECTIONAL negative control:
  * FORWARD: the intended processor_cpu opcode case is now WAIVED-DEFERRED
    where it previously FAILed.
  * REVERSE: a non-processor_cpu opcode happy-path with no evidence STILL
    FAILs (ic_class gate); an unanchored processor_cpu case STILL FAILs
    (anchor gate); an explicit-cmd_response digital case STILL FAILs (no-leak
    exclusion); a missing ic_class.json fails CLOSED.
"""
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "l10_tb_conformance_check.py"
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import l10_tb_conformance_check as gate  # noqa: E402


def _make_project(tmp_path, l10_cases, *, ic_class="processor_cpu",
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

    if ic_class is not None:
        rep = tmp_path / "reports"
        rep.mkdir(parents=True, exist_ok=True)
        (rep / "ic_class.json").write_text(json.dumps({"ic_class": ic_class}))

    return l10, tb, summary


# The exact shape Phase 1's gen_l10_test_cases emits for a CPU core's L3
# opcodes (see phase1_doc_one_shot_runner.gen_l10_test_cases): a per-opcode
# happy_path case + a pre_wake_false negative, each carrying opcode_hex.
def _ibex_like_cases():
    return [
        {"name": "send_opcode_load_happy", "kind": "happy_path",
         "stimulus": "host sends 0x03",
         "expected": "DUT replies per response_payload_template",
         "opcode_hex": "0x03"},
        {"name": "send_opcode_load_no_wake", "kind": "pre_wake_false",
         "stimulus": "host sends 0x03 immediately after POR",
         "expected": "DUT silent (no response frame)",
         "opcode_hex": "0x03"},
    ]


def _run(tmp_path, l10, tb, summary):
    out = tmp_path / "out.json"
    rc = gate.main(["--l10", str(l10), "--tb-dir", str(tb),
                    "--summary", str(summary), "--out", str(out),
                    "--project", str(tmp_path)])
    return rc, json.loads(out.read_text())


# ---------------------------------------------------------------------------
# Unit level — is_cpu_instruction_oracle_case bidirectional
# ---------------------------------------------------------------------------
def test_predicate_fires_for_processor_cpu_opcode_kinds():
    for kind in ("happy_path", "pre_wake_false", "addr_max", "len_max"):
        c = {"kind": kind, "opcode_hex": "0x03"}
        assert gate.is_cpu_instruction_oracle_case(c, "processor_cpu") is True


def test_predicate_inert_for_non_processor_cpu_class():
    c = {"kind": "happy_path", "opcode_hex": "0x03"}
    for other in ("digital_cmd_driven", "unknown_protocol_class",
                  "digital_arithmetic_primitive", ""):
        assert gate.is_cpu_instruction_oracle_case(c, other) is False


def test_predicate_excludes_explicit_cmd_response_category():
    # §4.05 NO-LEAK — a genuine digital command must never be masked.
    c = {"category": "cmd_response", "opcode": "70"}
    assert gate.is_cpu_instruction_oracle_case(c, "processor_cpu") is False


def test_predicate_requires_opcode_signal():
    # A bare happy_path with no structured instruction signal is not an
    # instruction-execution case.
    c = {"kind": "happy_path"}
    assert gate.is_cpu_instruction_oracle_case(c, "processor_cpu") is False


# ---------------------------------------------------------------------------
# FORWARD — the intended case is now WAIVED-DEFERRED (was FAIL pre-fix)
# ---------------------------------------------------------------------------
def test_forward_processor_cpu_opcode_cases_waived_under_anchor(tmp_path):
    l10, tb, summary = _make_project(tmp_path, _ibex_like_cases(),
                                     ic_class="processor_cpu",
                                     cpu_oracle_anchor=True)
    rc, data = _run(tmp_path, l10, tb, summary)
    assert rc == 3, "processor_cpu opcode cases must be WAIVED-DEFERRED (rc=3)"
    assert data["fail"] == 0 and data["waived"] == 2 and data["ok"] == 0
    for r in data["results"]:
        assert r["status"] == "waived"
        assert r["capability_gap"] == "cap:cpu_functional_oracle"


# ---------------------------------------------------------------------------
# REVERSE (the bidirectional negative control the acceptance bar names)
# ---------------------------------------------------------------------------
def test_reverse_non_processor_cpu_opcode_happy_still_fails(tmp_path):
    """A non-processor_cpu opcode happy-path with no evidence MUST still FAIL,
    even with the cap:cpu_functional_oracle anchor present."""
    l10, tb, summary = _make_project(tmp_path, _ibex_like_cases(),
                                     ic_class="digital_cmd_driven",
                                     cpu_oracle_anchor=True)
    rc, data = _run(tmp_path, l10, tb, summary)
    assert rc == 1, "non-processor_cpu opcode happy-path must STILL FAIL"
    assert data["fail"] == 2 and data["waived"] == 0


def test_reverse_processor_cpu_unanchored_still_fails(tmp_path):
    """processor_cpu but NO runner capability-gap declaration → the waiver has
    no anchor and every case STILL FAILs."""
    l10, tb, summary = _make_project(tmp_path, _ibex_like_cases(),
                                     ic_class="processor_cpu",
                                     cpu_oracle_anchor=False)
    rc, data = _run(tmp_path, l10, tb, summary)
    assert rc == 1
    assert data["fail"] == 2 and data["waived"] == 0


def test_reverse_missing_ic_class_fails_closed(tmp_path):
    """No reports/ic_class.json → ic_class resolves to '' → the processor_cpu
    path stays inert and cases STILL FAIL (fails CLOSED)."""
    l10, tb, summary = _make_project(tmp_path, _ibex_like_cases(),
                                     ic_class=None, cpu_oracle_anchor=True)
    rc, data = _run(tmp_path, l10, tb, summary)
    assert rc == 1
    assert data["fail"] == 2 and data["waived"] == 0


def test_noleak_explicit_cmd_response_still_fails_under_processor_cpu(tmp_path):
    """Even for a processor_cpu under the anchor, an EXPLICITLY-categorised
    digital cmd_response case (a real command the TB must exercise) STILL
    FAILs — it is never masked by the CPU instruction-oracle waiver."""
    cases = [
        {"name": "send_opcode_load_happy", "kind": "happy_path",
         "opcode_hex": "0x03"},                         # waivable CPU insn
        {"name": "GET_ID_DIGITAL", "category": "cmd_response",
         "opcode": "70"},                               # genuine digital cmd
    ]
    l10, tb, summary = _make_project(tmp_path, cases,
                                     ic_class="processor_cpu",
                                     cpu_oracle_anchor=True)
    rc, data = _run(tmp_path, l10, tb, summary)
    assert rc == 1, "a genuine digital cmd_response with no evidence must FAIL"
    by_id = {r["id"]: r for r in data["results"]}
    assert by_id["GET_ID_DIGITAL"]["status"] == "fail"
    assert by_id["send_opcode_load_happy"]["status"] == "waived"
    assert data["fail"] == 1 and data["waived"] == 1


def test_opcode_case_with_real_evidence_not_waived(tmp_path):
    """A processor_cpu opcode case whose id IS traced by a live testbench is a
    genuine PASS — evidence supersedes the deferral, it is NOT waived."""
    cases = [{"name": "send_opcode_load_happy", "kind": "happy_path",
              "opcode_hex": "0x03"}]
    tb_text = ("module tb;\n  dut u(.clk(clk));\n"
               "  // [TB send_opcode_load_happy] PASS\n"
               "  initial $display(\"send_opcode_load_happy\");\nendmodule\n")
    l10, tb, summary = _make_project(tmp_path, cases,
                                     ic_class="processor_cpu",
                                     cpu_oracle_anchor=True, tb_text=tb_text)
    rc, data = _run(tmp_path, l10, tb, summary)
    assert data["results"][0]["status"] == "pass"
    assert data["ok"] == 1 and data["waived"] == 0 and data["fail"] == 0
    assert rc == 0
