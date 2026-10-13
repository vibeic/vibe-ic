"""The formal expert receipt must refer to an executable assertion."""

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import formal_harness_gen as harness_gen  # noqa: E402
import formal_proof_evidence_check as evidence_check  # noqa: E402


def test_read_slang_immediate_assert_can_close_exact_obligation(tmp_path):
    request = [{"id": "L6.fsm_state.IDLE", "status": "UNAUTHORED"}]
    request_text = json.dumps({"fallback_skill": "formal-verify",
                               "unresolved_obligations": request})
    (tmp_path / harness_gen.AUTHORING_REQUEST).write_text(request_text)
    receipt = {
        "request_sha256": hashlib.sha256(request_text.encode()).hexdigest(),
        "invocation_status": "INVOKED",
        "dispositions": [{"id": request[0]["id"], "status": "AUTHORED",
                          "property": "p_idle_transition"}],
    }
    (tmp_path / "formal_expert_review.json").write_text(json.dumps(receipt))
    (tmp_path / "formal_expert_properties.svh").write_text(
        "always @(posedge clk_i) if (rst_ni)\n"
        "  p_idle_transition: assert (state == IDLE);\n")
    closed = harness_gen._expert_closed_obligations(
        tmp_path, request, 'module formal_top; `include "formal_expert_properties.svh"\n')
    assert [row["id"] for row in closed] == ["L6.fsm_state.IDLE"]
    assert closed[0]["property"] == "p_idle_transition"


def test_label_without_assert_does_not_close_obligation(tmp_path):
    request = [{"id": "L6.fsm_state.IDLE", "status": "UNAUTHORED"}]
    (tmp_path / "formal_expert_review.json").write_text(json.dumps({
        "invocation_status": "INVOKED",
        "dispositions": [{"id": request[0]["id"], "status": "AUTHORED",
                          "property": "p_idle_transition"}],
    }))
    (tmp_path / "formal_expert_properties.svh").write_text(
        "p_idle_transition: cover (state == IDLE);\n")
    assert harness_gen._expert_closed_obligations(tmp_path, request, "") == []


def test_reset_binding_accepts_only_reset_guarded_immediate_assert():
    # The landed AES45 contract credits a reset assertion only when it checks
    # a DUT output the harness connects directly (`.state(state)`), so the
    # fixture carries that DUT instance; the assertion itself is unchanged.
    harness = (
        "aes_core dut (.state(state));\n"
        "always @(posedge clk_i) if (f_past_valid && rst_active)\n"
        "  a_reset: assert (state == 0);\n"
        "always @(posedge clk_i) if (f_past_valid)\n"
        "  a_unrelated: assert (state != 3);\n"
    )
    assert evidence_check._reset_guarded_properties(harness) == ["a_reset"]
