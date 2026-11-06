"""The declared reset policy owns the expected first-edge memory commit."""
import json
import subprocess

import pytest

import reset_invariant_oracle_tb_gen as R
import testbench_gen as T
from test_r48_the_reset_invariants_get_a_real_oracle import prepare, CASE, DEBT

COMPLETE = "complete_issued_transaction_then_block"
STRICT = "block_first_and_held_sampled_edges"


def generate(project, policy, mutation=None):
    rtl = prepare(project, good=mutation == "cancel")
    declaration = project / "plugin_output/declaration.json"
    choice = json.loads(declaration.read_text())
    choice.update(reset_write_policy=policy, reset_write_policy_source="provided reset contract")
    declaration.write_text(json.dumps(choice))
    case = dict(CASE, stimulus="Reset assert retains external byte memory content.",
                expected="Follow the declared in-flight-write policy, then freeze memory.")
    (project / "phase1/generated_docs/L10_TEST_CASES.json").write_text(
        json.dumps({"test_cases": [case, DEBT]}))
    text = rtl.read_text()
    if mutation == "corrupt-first":
        text = text.replace("output reg [7:0] o_store_wdata", "output wire [7:0] o_store_wdata")
        text = text.replace("o_store_wdata <=", "queued_data <=")
        text = text.replace(" reg [3:0] phase;", " reg [3:0] phase; reg [7:0] queued_data;\n"
                            " assign o_store_wdata = i_rst ? 8'h00 : queued_data;")
    elif mutation == "held":
        text = text.replace("o_store_we <= 0;", "if (phase != 3) o_store_we <= 0;", 1)
    rtl.write_text(text)
    report = {}
    assert T.emit_unit_tbs(project, top="sample_store", report=report,
                          scaffold=False, case_stated=True) == 1
    return rtl, T._pl.sim_dir(project) / "tb" / (CASE["name"] + ".v"), report


@pytest.mark.parametrize("policy,mutation,passes", [
    (COMPLETE, None, True),
    (STRICT, None, False),
    (COMPLETE, "cancel", False),
    (COMPLETE, "corrupt-first", False),
    (COMPLETE, "held", False),
])
def test_native_memory_commit_matches_the_declared_policy(tmp_path, policy, mutation, passes):
    rtl, bench, report = generate(tmp_path, policy, mutation)
    binary = tmp_path / "case.vvp"
    compile_result = subprocess.run(["iverilog", "-g2012", "-s", CASE["name"],
        "-o", str(binary), str(rtl), str(bench)], capture_output=True, text=True)
    assert compile_result.returncode == 0, compile_result.stderr
    run = subprocess.run(["vvp", str(binary)], capture_output=True, text=True)
    (tmp_path / "native.log").write_text(run.stdout + run.stderr)
    assert (run.returncode == 0) is passes, run.stdout + run.stderr
    memory = report["reset_invariant_cases"][0]["retention_memory"]
    measured = R.retention_measurement(run.stdout, memory)
    assert measured["complete"] is True
    assert measured["changed"] is not passes
    if passes:
        assert memory["reset_write_policy"] == COMPLETE
        assert memory["reset_write_policy_source"] == "provided reset contract"
        assert "PASS" in run.stdout


def test_unknown_policy_does_not_guess_from_the_rtl(tmp_path):
    _rtl, _bench, report = generate(tmp_path, "guess_from_behavior")
    row = report["reset_invariant_cases"][0]
    assert row["retention_memory"] is None
    assert "NOT_MEASURED" in row["retention_basis"]


@pytest.mark.parametrize("policy,actual,post_we,changed", [
    (COMPLETE, "a5b63cd8e9fa0b1c", "0", False),
    (STRICT, "a5b63cd8e9fa0b1c", "0", True),
    (COMPLETE, "a5b6c7d8e9fa0b1c", "0", True),
    (COMPLETE, "a5b600d8e9fa0b1c", "0", True),
    (COMPLETE, "a5b63cd8e9fa0b1c", "1", True),
])
def test_decoder_uses_the_prior_transaction_and_policy(policy, actual, post_we, changed):
    before = "a5b6c7d8e9fa0b1c"
    lines = [f"RESET_RETENTION BASELINE arm={arm} bytes={before}" for arm in (0, 1)]
    lines.append("RESET_RETENTION PENDING address=2 before=c7 data=3c")
    for arm in (0, 1):
        for edge in range(R.RETENTION_EDGES):
            data = actual if arm == 1 else before
            we = post_we if arm == 1 and edge == 0 else "0"
            lines.append(f"RESET_RETENTION SAMPLE arm={arm} edge={edge} bytes={data} post_edge_we={we}")
    measured = R.retention_measurement("\n".join(lines),
                                     {"depth": 8, "reset_write_policy": policy})
    assert measured["complete"] is True
    assert measured["changed"] is changed
