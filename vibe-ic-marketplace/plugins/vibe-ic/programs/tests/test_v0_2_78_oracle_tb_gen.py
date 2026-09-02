"""v0.2.78 — #439: per-IC oracle TB generation is a first-class
contract (mirror of rtl_gen → spec-to-rtl).

The audited gap: only the AID class had a real reference TB; other
classes shipped a connectivity skeleton (0 golden compares,
functional_verified=false) that step_reference_tb reported as PASS —
3 of 4 campaign ICs had ZERO functional verification.

Pins:
  * registry: every digital class carries tb_gen/tb_fallback_skill
    (oracle_tb_gen.py / a shipped TB-authoring skill); pure-analog
    gets null;
  * oracle_tb_gen emits a runnable oracle TB from concrete L10 golden
    vectors (verified end-to-end with iverilog when available: correct
    DUT → all vectors PASS; wrong DUT → mismatch detected);
  * no concrete vectors → exit 2 + a fallback direction that routes at a
    skill the tree ships;
  * step_reference_tb: skeleton-completion is WAIVED (connectivity
    only), never PASS — source pin; oracle PASS path requires
    ORACLE_TB_DONE with all goldens matched.

chip-AGNOSTIC: synthetic generic fixtures.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from _source_pin import func_src, if_block_src

import pytest

from _skill_routes import assert_route_ships

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import oracle_tb_gen as OTG  # noqa: E402

PLUGIN = Path(__file__).resolve().parent.parent.parent
_P2_SRC = (PLUGIN / "programs" / "design_one_shot_runner.py").read_text()
_REG = json.loads((PLUGIN / "programs" / "ic_class_registry.json").read_text())


def _proj(tmp_path, expected_out=1):
    gen = tmp_path / "phase1" / "generated_docs"
    gen.mkdir(parents=True)
    (gen / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "fields": {"top_module": "inv_top", "top_ports": [
            {"name": "clk", "dir": "input", "width": 1},
            {"name": "rst_n", "dir": "input", "width": 1},
            {"name": "a", "dir": "input", "width": 1},
            {"name": "y", "dir": "output", "width": 1},
        ]}}))
    (gen / "L10_TEST_CASES.json").write_text(json.dumps({
        "test_cases": [
            {"name": "drive0", "inputs": {"a": 0},
             "expected": {"y": 1 if expected_out else 0}},
            {"name": "drive1", "inputs": {"a": 1},
             "expected": {"y": 0 if expected_out else 1}},
            {"name": "prose_only", "desc": "no concrete vector"},
        ]}))
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "inv_top.v").write_text(
        "module inv_top(input clk, input rst_n, input a, output y);\n"
        "  assign y = ~a;\nendmodule\n")
    return tmp_path


# ── registry contract ───────────────────────────────────────────────────────

def test_registry_tb_gen_contract():
    _routed = set()
    for c in _REG["classes"]:
        assert "tb_gen" in c and "tb_fallback_skill" in c, c["name"]
        if c.get("rtl_gen") is None and c.get("fallback_skill") is None:
            assert c["tb_fallback_skill"] is None  # analog A-track
        elif not c.get("reference_tb"):
            assert c["tb_gen"] == "oracle_tb_gen.py", c["name"]
            # PROPERTY, not literal. This line pinned "testbench-author" and
            # was green through every release in which no such skill shipped:
            # a string is always equal to itself, so pinning the NAME of a
            # route can never tell you whether the route LEADS anywhere.
            assert_route_ships(
                c["tb_fallback_skill"],
                f"registry class {c['name']}.tb_fallback_skill")
            _routed.add(c["tb_fallback_skill"])
    # The old literal also encoded "every such class routes at the SAME skill".
    # Keep that invariant without naming the skill.
    assert len(_routed) == 1, f"classes route TB authoring at {sorted(_routed)}"


# ── generator ───────────────────────────────────────────────────────────────

def test_emits_oracle_tb_from_concrete_vectors(tmp_path):
    p = _proj(tmp_path)
    rep, rc = OTG.generate(p)
    assert rc == 0 and rep["vector_count"] == 2
    tb = p / "phase2/stage1/sim_full_stack/tb_inv_top_oracle.v"
    assert tb.is_file()
    body = tb.read_text()
    assert "ORACLE_TB_DONE" in body and "y === 1" in body


def test_no_concrete_vectors_fallback_direction(tmp_path):
    gen = tmp_path / "phase1" / "generated_docs"
    gen.mkdir(parents=True)
    (gen / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "fields": {"top_module": "t", "top_ports": [
            {"name": "clk", "dir": "input", "width": 1}]}}))
    (gen / "L10_TEST_CASES.json").write_text(json.dumps({
        "test_cases": [{"name": "x", "desc": "prose only"}]}))
    rep, rc = OTG.generate(tmp_path)
    assert rc == 2
    assert rep["verdict"] == "SKIPPED-CONDITION"
    assert_route_ships(rep["fallback_skill"],
                       "oracle_tb_gen SKIPPED-CONDITION report")


@pytest.mark.skipif(shutil.which("iverilog") is None,
                    reason="iverilog not available")
def test_oracle_tb_runs_and_matches_goldens(tmp_path):
    p = _proj(tmp_path)
    OTG.generate(p)
    tb = p / "phase2/stage1/sim_full_stack/tb_inv_top_oracle.v"
    rtl = p / "phase2/stage1/rtl/inv_top.v"
    vvp = tmp_path / "o.vvp"
    assert subprocess.run(["iverilog", "-g2012", "-o", str(vvp),
                           str(tb), str(rtl)]).returncode == 0
    out = subprocess.run(["vvp", str(vvp)], capture_output=True,
                         text=True).stdout
    assert "ORACLE_TB_DONE pass=2/2" in out


@pytest.mark.skipif(shutil.which("iverilog") is None,
                    reason="iverilog not available")
def test_oracle_tb_catches_wrong_dut(tmp_path):
    p = _proj(tmp_path)
    OTG.generate(p)
    # break the DUT: buffer instead of inverter
    (p / "phase2/stage1/rtl/inv_top.v").write_text(
        "module inv_top(input clk, input rst_n, input a, output y);\n"
        "  assign y = a;\nendmodule\n")
    tb = p / "phase2/stage1/sim_full_stack/tb_inv_top_oracle.v"
    rtl = p / "phase2/stage1/rtl/inv_top.v"
    vvp = tmp_path / "o.vvp"
    subprocess.run(["iverilog", "-g2012", "-o", str(vvp), str(tb), str(rtl)])
    out = subprocess.run(["vvp", str(vvp)], capture_output=True,
                         text=True).stdout
    assert "ORACLE_TB_DONE pass=0/2" in out
    assert "FAIL" in out


# ── runner source pins ──────────────────────────────────────────────────────

#: The verdicts that DISCLOSE an unverified skeleton. `PASS` is deliberately
#: absent: #439 exists because skeleton completion used to be reported as PASS
#: and 3 of 4 campaign ICs shipped with zero functional verification. A future
#: author may sharpen WAIVED into a stricter word (cbe6154a6 did exactly that,
#: WAIVED -> INCOMPLETE, for #1975) without this pin objecting; making it PASS
#: again, or dropping the verdict entirely, must turn this test red.
_SKELETON_DISCLOSURE_VERDICTS = {"WAIVED", "INCOMPLETE"}


def test_skeleton_completion_is_waived_not_pass():
    # Anchored on the `if` that OWNS the verdict, not on the first textual
    # occurrence of its marker. The old `_P2_SRC.index(...)` + 3800-char window
    # bound to a COMMENT quoting the same token in step_full_stack_tb_gen
    # (e5d569ace7), ~97,000 chars away, and the pin failed against correct
    # code; widening it would have reached the neighbouring `iverilog
    # unavailable` return, whose own `"reference_tb", "WAIVED"` literal would
    # have satisfied this assertion on a tree where the pinned branch said
    # PASS. See _source_pin.if_block_src.
    block = if_block_src(_P2_SRC, "_reference_tb_generic_full_stack",
                         '"FULL_STACK_TB_DONE" in out')
    _v = re.search(r'StepResult\(\s*"reference_tb",\s*"([A-Z_]+)"', block)
    assert _v, ("the skeleton-completion branch no longer returns a named "
                "reference_tb verdict")
    assert _v.group(1) in _SKELETON_DISCLOSURE_VERDICTS, (
        f"skeleton completion reports {_v.group(1)!r}; connectivity-only "
        f"completion with 0 golden compares is never a functional PASS (#439)")
    assert '"functional_verified": False' in block, (
        "the disclosure must still say functional_verified=False")
    # The return must still hand the agent a route, and that route must
    # lead to a skill that ships -- pinning the literal here is what let the
    # runner waive at a non-existent skill without this test noticing.
    _m = re.search(r'"fallback_skill":\s*"([A-Za-z0-9\-_]+)"', block)
    assert _m, "the skeleton-completion return no longer names a fallback skill"
    assert_route_ships(_m.group(1),
                       "design_one_shot_runner skeleton-completion return")
    assert "#439" in block


def test_runner_tries_oracle_before_skeleton():
    i = _P2_SRC.index("oracle_tbs = sorted(sim_dir.glob")
    # Window widened (#745): the arithmetic closed-form oracle generator
    # (arith_oracle_tb_gen) is now tried first, so the deterministic-replay
    # oracle_tb_gen import + the _run_oracle_tb call legitimately sit further
    # down the same routing region. Both must still precede the skeleton path.
    window = _P2_SRC[i - 1200:i + 2600]
    assert "_run_oracle_tb" in window
    assert "import oracle_tb_gen" in window
    # the closed-form arithmetic oracle is tried BEFORE the replay oracle
    assert "import arith_oracle_tb_gen" in window
    assert (window.index("import arith_oracle_tb_gen")
            < window.index("import oracle_tb_gen"))


def test_oracle_pass_requires_all_goldens():
    # (was a hand-widened 6000-char window, re-widened whenever the function
    #  grew; func_src covers the whole function and needs no maintenance.)
    window = func_src(_P2_SRC, "_run_oracle_tb")
    assert "ORACLE_TB_DONE pass=" in window
    assert "n_total > 0 and n_pass == n_total" in window
