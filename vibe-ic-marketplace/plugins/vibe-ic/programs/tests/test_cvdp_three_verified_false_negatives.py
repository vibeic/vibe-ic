"""Three checks that rejected work they should have passed.

Each one was found by scoring 302 authored CVDP completions through the
official harness and then reading the rejections, and each is pinned here by
the counter-example that motivated it — with the opposite tail asserted too,
because a guard that stops firing entirely is not a fix.

  1. `cvdp_gate.instantiated_module_names` called the keyword `endcase` an
     instantiated module (7 of 302 drafts).
  2. `score_one` set one of the harness's TWO container images, so an area-opt
     problem's synth subtest fell back to a gated image and its pull failure
     was recorded as a design FAIL (6 of 302, all with a clean functional half).
  3. `fsm_transition_completeness_check` read the `:` of a ternary as a case
     label, inventing an empty arm and reporting an inferred latch against a
     state whose real arm is complete.
"""
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[2]
PROGRAMS = PLUGIN / "programs"
BENCH = PLUGIN / "benchmark"
for p in (str(PROGRAMS), str(BENCH)):
    if p not in sys.path:
        sys.path.insert(0, p)


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ── 1. the end* keyword family ───────────────────────────────────────────────
_TWO_CASES = """\
module top (input [1:0] s, input [7:0] a, output reg [7:0] y);
  reg [7:0] t;
  always @(*) begin
    case (s)
      2'd0: t = a;
      default: t = 8'd0;
    endcase
    case ({s[1], s[0]})
      2'd3: y = t;
      default: y = 8'd1;
    endcase
  end
  real_sub u_sub (.a(a));
endmodule
"""


def test_endcase_is_not_an_instantiated_module():
    """THE REGRESSION. `_INSTANCE_RE` allows a newline between type and
    instance, so `endcase` + a following `case (...)` parsed as an instance of
    a module named `endcase`."""
    gate = _load(BENCH / "cvdp_gate.py", "gate_endcase")
    assert "endcase" not in gate.instantiated_module_names(_TWO_CASES)


def test_a_real_submodule_still_counts_as_instantiated():
    """The other tail: the check must not go blind."""
    gate = _load(BENCH / "cvdp_gate.py", "gate_endcase2")
    assert "real_sub" in gate.instantiated_module_names(_TWO_CASES)


def test_the_whole_end_family_is_listed_not_just_the_one_that_bit_us():
    gate = _load(BENCH / "cvdp_gate.py", "gate_endcase3")
    kw = gate._NON_INSTANCE_KEYWORDS
    for w in ("endcase", "endmodule", "endfunction", "endtask",
              "endinterface", "endclass"):
        assert w in kw, f"{w} missing from the non-instance keyword set"


# ── 2. the harness takes TWO images ──────────────────────────────────────────
def test_score_one_sets_the_synth_image_too():
    """`OSS_PNR_IMAGE` unset makes the harness fall back to the gated
    `nvidia/cvdp-sim:v1.0.0`; the pull is denied and the *_synth subtest is
    recorded as a failure OF THE DESIGN."""
    src = (BENCH / "score_one.py").read_text(encoding="utf-8")
    assert "OSS_PNR_IMAGE" in src, \
        "score_one must name the synth image, not only OSS_SIM_IMAGE"
    assert re.search(r'setdefault\(\s*["\']OSS_PNR_IMAGE["\']', src), \
        "it must DEFAULT the synth image, so an explicit env still wins"


def test_the_synth_image_default_does_not_override_an_explicit_choice():
    """`setdefault`, never `=`: a caller that names its own PNR image keeps it."""
    src = (BENCH / "score_one.py").read_text(encoding="utf-8")
    assert not re.search(r'env\[\s*["\']OSS_PNR_IMAGE["\']\s*\]\s*=', src)


# ── 3. a ternary ':' is not a case label ─────────────────────────────────────
_FSM = """\
module m(input clk, input start, input [7:0] count, output reg [1:0] q);
  localparam [1:0] IDLE=2'b00, LOAD=2'b01, COMPUTE=2'b10, COMPLETE=2'b11;
  localparam [7:0] LIMIT = 8'd9;
  reg [1:0] state, next_state;
  always @(*) begin
    case (state)
      IDLE     : next_state = start ? LOAD : IDLE;
      LOAD     : next_state = COMPUTE;
      COMPUTE  : next_state = (count < LIMIT) ? LOAD : COMPLETE;
      COMPLETE : next_state = IDLE;
    endcase
  end
  always @(posedge clk) state <= next_state;
  always @(*) q = state;
endmodule
"""

# the same machine with LOAD's arm genuinely empty — the true positive
_FSM_REAL_LATCH = _FSM.replace("      LOAD     : next_state = COMPUTE;\n",
                               "      LOAD     : ;\n")


def _latch_states(tmp_path, text, name):
    f = tmp_path / f"{name}.sv"
    f.write_text(text, encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "fsm_transition_completeness_check.py"),
         str(f)], capture_output=True, text=True, timeout=180)
    import json
    try:
        d = json.loads(r.stdout)
    except ValueError:  # pragma: no cover - the checker always emits JSON
        raise AssertionError(f"checker emitted no JSON: {r.stdout[:200]}")
    return [x.get("state") for x in d.get("findings", [])
            if x.get("rule") == "fsm-inferred-latch"]


def test_a_ternary_naming_two_states_is_not_a_case_arm(tmp_path):
    """THE REGRESSION. `? LOAD : COMPLETE` was read as an arm labelled LOAD
    whose body assigns nothing, so a complete FSM was reported as latching."""
    assert _latch_states(tmp_path, _FSM, "clean") == []


def test_a_genuinely_empty_arm_is_still_reported(tmp_path):
    """The other tail: the rule the checker exists for must survive."""
    assert _latch_states(tmp_path, _FSM_REAL_LATCH, "latch") == ["LOAD"]
