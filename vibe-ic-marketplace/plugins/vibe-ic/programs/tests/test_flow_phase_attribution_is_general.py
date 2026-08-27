#!/usr/bin/env python3
"""The four-phase attribution is GENERAL — reachable from a plain design.

Routing, solving, verifying and repairing are what the flow does to ANY design.
The attribution of those four phases was first written inside a benchmark
dispatcher's per-problem loop, where it was reachable only by someone running a
dataset. These tests hold it out here.

Two properties, and each is checked at BOTH poles:

  NAMING     the module's LOGIC carries no benchmark or dataset literal. The
             check reads the AST, so a docstring may cite the run something was
             measured on while an identifier or a live string may not.
  FLOW-BACK  a project directory built the way a USER has one — a prompt and
             the runner's own step record, no dataset, no harness, no adapter
             importable — yields all four phases, with the same values a
             benchmark run would report for the same tree.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
MODULE = PROGRAMS / "flow_phase_attribution.py"
sys.path.insert(0, str(PROGRAMS))

import flow_phase_attribution as fpa                       # noqa: E402


# ── helpers ──────────────────────────────────────────────────────────────────
def _project(tmp_path: Path, steps, prompt: str | None = None,
             verdict: str = "FAIL") -> Path:
    """A project directory shaped the way a USER's is: an input and a report.

    Nothing here is a dataset record, a problem id or an adapter.
    """
    p = tmp_path / "design"
    (p / "input" / "docs").mkdir(parents=True, exist_ok=True)
    if prompt is not None:
        (p / "input" / "phase1_prompt.md").write_text(prompt)
    rep = p / "reports" / "orchestrator"
    rep.mkdir(parents=True, exist_ok=True)
    (rep / "phase2_one_shot.json").write_text(
        json.dumps({"verdict": verdict, "steps": steps}))
    return p


def _step(name, status, **extras):
    s = {"name": name, "status": status, "detail": f"{name} {status}"}
    if extras:
        s["extras"] = extras
    return s


_PROMPT = ("Design a purely combinational 4-to-1 multiplexer.\n\n"
           "module TopModule (\n  input [3:0] in,\n  input [1:0] sel,\n"
           "  output out\n);\n")

# The shape measured on a real plain run of vibe_ic_one_shot_runner.py against
# a 4-to-1 multiplexer project: rtl_gen refused, the RTL repair/retry loop fired, rtl_gen
# then emitted with a NAMED emitter, and four gates failed.
_REAL_SHAPE = [
    _step("rtl_gen", "BLOCKED"),
    _step("reference_tb", "FAIL"),
    _step("rtl_repair_retry_iter", "RTL_REPAIR_RETRY"),
    _step("rtl_gen", "PASS", deterministic_generator="multiplexer"),
    _step("sdc_gen", "FAIL"),
    _step("yosys_synth", "PASS"),
    _step("lec_equivalence", "FAIL"),
    _step("final_audit", "FAIL"),
]


# ── NAMING TEST ──────────────────────────────────────────────────────────────
_BENCH_WORDS = ("verilogeval", "cvdp", "rtllm", "pyhdl", "rtl-repo", "metrex",
                "resbench", "chipagents", "pass@1", "jsonl", "problem_id",
                "prob0", "dataset", "solve_report", "benchmark_io_adapter",
                "benchmark_dispatch")


def _logic_strings_and_names(path: Path):
    """Every string and identifier the module's LOGIC uses — docstrings out.

    A docstring may name the run a number was measured on; that is provenance,
    not a dependency. An identifier or a live string literal naming a benchmark
    IS a dependency, and this is what the naming test is asking about.
    """
    tree = ast.parse(path.read_text())
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                docstrings.add(id(body[0].value))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstrings:
                out.append(node.value)
        elif isinstance(node, ast.Name):
            out.append(node.id)
        elif isinstance(node, ast.Attribute):
            out.append(node.attr)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            out.append(getattr(node, "module", "") or "")
            out += [a.name for a in node.names]
    return out


def test_naming_the_logic_carries_no_benchmark_literal():
    hits = [(w, s) for s in _logic_strings_and_names(MODULE)
            for w in _BENCH_WORDS if w in s.lower()]
    assert not hits, (
        f"the general core's LOGIC names a benchmark: {hits} — that is the "
        f"naming debt this module exists to pay off")


def test_naming_check_can_go_red():
    """The control. A scanner that cannot fire is not a scanner.

    The same extractor is pointed at a module that legitimately DOES carry
    benchmark literals in its logic — the adapter — and must find them.
    """
    adapter = PROGRAMS / "benchmark_io_adapter.py"
    if not adapter.is_file():
        pytest.skip("the adapter this control needs is not in this tree")
    hits = [(w, s) for s in _logic_strings_and_names(adapter)
            for w in _BENCH_WORDS if w in s.lower()]
    assert hits, ("the extractor found NO benchmark literal in the benchmark "
                  "adapter's own logic, so it would not have found one in the "
                  "general core either")


def test_the_general_core_does_not_import_any_adapter():
    src = ast.parse(MODULE.read_text())
    imported = set()
    for n in ast.walk(src):
        if isinstance(n, ast.Import):
            imported |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            imported.add(n.module or "")
    assert not any("benchmark" in m for m in imported), imported


# ── FLOW-BACK TEST ───────────────────────────────────────────────────────────
def test_flow_back_a_plain_design_gets_all_four_phases(tmp_path):
    """The decisive one: a user's project, no harness, all four attributed."""
    p = _project(tmp_path, _REAL_SHAPE, prompt=_PROMPT)
    att = fpa.attribute(p)
    for key in ("phase1_routing", "phase2_solving", "phase3_verifying",
                "phase4_debugging"):
        assert att[key]["attributed"] is True, (key, att[key])

    assert att["phase1_routing"]["nature"] == "spec_generation"
    assert att["phase1_routing"]["verdict_source"].startswith("DERIVED_HERE")
    assert att["phase2_solving"]["solved_by"] == "EMITTER"
    assert att["phase2_solving"]["emitter"] == "multiplexer"
    assert att["phase2_solving"]["mechanism"] == "PROGRAM"
    assert att["phase3_verifying"]["failed"] == [
        "final_audit", "lec_equivalence", "reference_tb", "sdc_gen"]
    assert att["phase4_debugging"]["fired"] is True
    assert att["phase4_debugging"]["events"][0]["mechanism"] == "PROGRAM"
    assert att["phase4_debugging"]["verdict_change"] == {
        "changed": True,
        "basis": "rtl_gen status recorded before the first repair marker vs "
                 "the last rtl_gen status recorded",
        "before": "BLOCKED", "after": "PASS"}


def test_flow_back_the_cli_writes_a_report_a_plain_user_can_read(tmp_path):
    p = _project(tmp_path, _REAL_SHAPE, prompt=_PROMPT)
    rc = subprocess.run(
        [sys.executable, str(MODULE), str(p)],
        capture_output=True, text=True, cwd=str(PROGRAMS))
    assert rc.returncode == 0, rc.stdout + rc.stderr
    assert "multiplexer" in rc.stdout
    out = p / "reports" / "orchestrator" / fpa.REPORT_NAME
    assert out.is_file()
    assert json.loads(out.read_text())["phase2_solving"]["emitter"] == \
        "multiplexer"


def test_flow_back_holds_with_no_adapter_importable(tmp_path, monkeypatch):
    """No benchmark module on the path at all, and the answer is unchanged."""
    p = _project(tmp_path, _REAL_SHAPE, prompt=_PROMPT)
    for mod in [m for m in list(sys.modules) if "benchmark" in m]:
        monkeypatch.delitem(sys.modules, mod, raising=False)
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) \
        else __builtins__.__import__

    def guard(name, *a, **kw):
        if "benchmark" in name:
            raise AssertionError(f"the general core imported {name!r}")
        return real_import(name, *a, **kw)

    monkeypatch.setattr("builtins.__import__", guard)
    att = fpa.attribute(p)
    assert att["phase2_solving"]["emitter"] == "multiplexer"


def test_the_general_runner_takes_the_attribution(tmp_path):
    """The lift is WIRED, not merely available. Anchors against silent un-wiring."""
    src = (PROGRAMS / "vibe_ic_one_shot_runner.py").read_text()
    assert "import flow_phase_attribution" in src
    assert "phase_attribution" in src


# ── BOTH POLES, PHASE BY PHASE ───────────────────────────────────────────────
def test_phase1_red_when_there_is_no_prompt_to_route(tmp_path):
    p = _project(tmp_path, _REAL_SHAPE, prompt=None)
    r = fpa.attribute(p)["phase1_routing"]
    assert r["attributed"] is False
    assert "no Path-A input is present" in r["reason"]


def test_phase1_green_and_carries_the_thrown_away_fields(tmp_path):
    p = _project(tmp_path, _REAL_SHAPE, prompt=_PROMPT)
    r = fpa.attribute(p)["phase1_routing"]
    assert r["source"] == "no_context_heuristic"
    assert r["needs_ai_parse"] is True
    assert "NOTHING" in r["needs_ai_parse_consumed_by"]


def test_phase1_sees_supplied_rtl_and_routes_differently(tmp_path):
    """The router's has_context signal is read from the tree, not assumed."""
    p = _project(tmp_path, _REAL_SHAPE, prompt="Fix the bug in this module.\n")
    (p / "input" / "rtl").mkdir(parents=True)
    (p / "input" / "rtl" / "dut.v").write_text("module dut(); endmodule\n")
    r = fpa.attribute(p)["phase1_routing"]
    assert r["rtl_present_at_input"] is True
    assert r["nature"] != "spec_generation", r


def test_phase2_names_the_ai_skill_when_the_runner_waived(tmp_path):
    p = _project(tmp_path, [_step("rtl_gen", "WAIVED",
                                  fallback_skill="spec-to-rtl")],
                 prompt=_PROMPT)
    r = fpa.attribute(p)["phase2_solving"]
    assert (r["solved_by"], r["mechanism"], r["actor"]) == \
        ("AI_BACKUP", "AI_HANDOFF", "spec-to-rtl")
    assert r["emitter"] is None


def test_phase2_separates_a_pass_with_no_named_emitter(tmp_path):
    """PROGRAM_UNNAMED is not EMITTER. A gap must not read as an answer."""
    p = _project(tmp_path, [_step("rtl_gen", "PASS")], prompt=_PROMPT)
    r = fpa.attribute(p)["phase2_solving"]
    assert r["solved_by"] == "PROGRAM_UNNAMED"
    assert r["emitter"] == "UNKNOWN"


def test_phase2_records_the_earlier_waive_alongside_the_later_emit(tmp_path):
    p = _project(tmp_path, [
        _step("rtl_gen", "WAIVED", fallback_skill="spec-to-rtl"),
        _step("rtl_repair_retry_iter", "RTL_REPAIR_RETRY"),
        _step("rtl_gen", "PASS", deterministic_generator="comb_gate"),
    ], prompt=_PROMPT)
    r = fpa.attribute(p)["phase2_solving"]
    assert r["solved_by"] == "EMITTER" and r["emitter"] == "comb_gate"
    assert r["earlier_waive_to"] == "spec-to-rtl"


def test_phase2_never_guesses_the_collector_verdict(tmp_path):
    p = _project(tmp_path, _REAL_SHAPE, prompt=_PROMPT)
    plain = fpa.attribute(p)["phase2_solving"]["artefact_collected"]
    assert plain == {"known": False, "reason": plain["reason"]}
    adapted = fpa.attribute(p, artefact_collected=True)["phase2_solving"]
    assert adapted["artefact_collected"] is True


def test_phase3_failed_is_empty_when_nothing_failed(tmp_path):
    """The negative pole. A detector that fires on every design is useless."""
    p = _project(tmp_path, [
        _step("rtl_gen", "PASS", deterministic_generator="comb_gate"),
        _step("reference_tb", "PASS"), _step("final_audit", "PASS"),
    ], prompt=_PROMPT, verdict="PASS")
    r = fpa.attribute(p)["phase3_verifying"]
    assert r["failed"] == []
    assert r["ran"] == {"rtl_gen": "PASS", "reference_tb": "PASS",
                        "final_audit": "PASS"}


def test_phase3_separates_a_gate_that_never_ran_from_one_that_failed(tmp_path):
    p = _project(tmp_path, [
        _step("rtl_gen", "PASS", deterministic_generator="comb_gate"),
        _step("reference_tb", "FAIL"),
        _step("yosys_synth", "SKIPPED-BY-ENTRY"),
    ], prompt=_PROMPT)
    r = fpa.attribute(p)["phase3_verifying"]
    assert r["failed"] == ["reference_tb"]
    assert r["not_attempted"] == {"yosys_synth": "SKIPPED-BY-ENTRY"}
    assert "yosys_synth" not in r["ran"]


def test_phase3_refuses_to_absorb_a_status_it_does_not_know(tmp_path):
    p = _project(tmp_path, [
        _step("rtl_gen", "PASS", deterministic_generator="comb_gate"),
        _step("new_gate", "INVENTED_TOMORROW"),
    ], prompt=_PROMPT)
    r = fpa.attribute(p)["phase3_verifying"]
    assert r["unclassified_status"] == {"new_gate": "INVENTED_TOMORROW"}
    assert "new_gate" not in r["ran"] and "new_gate" not in r["not_attempted"]


def test_phase4_none_when_the_design_passed_first_time(tmp_path):
    p = _project(tmp_path, [
        _step("rtl_gen", "PASS", deterministic_generator="comb_gate"),
        _step("reference_tb", "PASS"),
    ], prompt=_PROMPT, verdict="PASS")
    r = fpa.attribute(p)["phase4_debugging"]
    assert r["fired"] is False and r["verdict"] == "NONE"
    assert "passed first time" in r["reason"]


def test_phase4_reads_the_mechanism_off_the_step_after_the_marker(tmp_path):
    """PROGRAM and AI_HANDOFF differ ONLY in that next step. Both poles."""
    prog = _project(tmp_path / "a", [
        _step("reference_tb", "FAIL"),
        _step("rtl_repair_retry_iter", "RTL_REPAIR_RETRY"),
        _step("rtl_gen", "PASS", deterministic_generator="vector_ops"),
    ], prompt=_PROMPT)
    ai = _project(tmp_path / "b", [
        _step("reference_tb", "FAIL"),
        _step("rtl_repair_retry_iter", "RTL_REPAIR_RETRY"),
        _step("rtl_gen", "WAIVED", fallback_skill="spec-to-rtl"),
    ], prompt=_PROMPT)
    ep = fpa.attribute(prog)["phase4_debugging"]["events"][0]
    ea = fpa.attribute(ai)["phase4_debugging"]["events"][0]
    assert ep["mechanism"] == "PROGRAM"
    assert ea["mechanism"] == "AI_HANDOFF"
    assert ep["triggered_by"] == {"step": "reference_tb", "status": "FAIL"}
    assert ea["triggered_by"] == {"step": "reference_tb", "status": "FAIL"}


def test_phase4_calls_blocked_reentry_a_retry_not_a_physical_eco(tmp_path):
    """No prior candidate failed when rtl_gen was BLOCKED; this is retry."""
    p = _project(tmp_path, [
        _step("rtl_gen", "BLOCKED"),
        _step("rtl_repair_retry_iter", "RTL_REPAIR_RETRY"),
        _step("rtl_gen", "PASS", deterministic_generator="comb_gate"),
    ], prompt=_PROMPT)
    r = fpa.attribute(p)["phase4_debugging"]
    assert r["verdict"] == "RETRIED"
    assert r["physical_eco"] is False
    assert r["events"][0]["event_kind"] == "RTL_RETRY"
    assert r["events"][0]["physical_eco"] is False
    assert "not a physical/metal ECO" in r["events"][0]["terminology"]


def test_phase4_sees_a_gate_directed_repair_with_no_marker(tmp_path):
    p = _project(tmp_path, [
        _step("rtl_gen", "PASS", deterministic_generator="comb_gate"),
        _step("rtl_hygiene_lint", "PASS",
              gate_directed_repairs=[{"rule": "width_mismatch"}]),
    ], prompt=_PROMPT, verdict="PASS")
    r = fpa.attribute(p)["phase4_debugging"]
    assert r["fired"] is True
    assert r["events"][0]["mechanism"] == "PROGRAM"
    assert r["events"][0]["repairs"] == [{"rule": "width_mismatch"}]


def test_every_phase_is_unknown_with_a_reason_when_the_report_is_absent(tmp_path):
    p = tmp_path / "bare"
    (p / "input").mkdir(parents=True)
    (p / "input" / "phase1_prompt.md").write_text(_PROMPT)
    att = fpa.attribute(p)
    assert att["phase1_routing"]["attributed"] is True     # routing needs no report
    for key in ("phase2_solving", "phase3_verifying", "phase4_debugging"):
        assert att[key]["attributed"] is False, key
        assert att[key]["verdict"] == "UNKNOWN"
        assert "ABSENT" in att[key]["reason"], (key, att[key])


def test_an_unattributable_design_exits_3_not_0(tmp_path):
    p = tmp_path / "bare"
    (p / "input").mkdir(parents=True)
    (p / "input" / "phase1_prompt.md").write_text(_PROMPT)
    rc = subprocess.run([sys.executable, str(MODULE), str(p)],
                        capture_output=True, text=True, cwd=str(PROGRAMS))
    assert rc.returncode == 3, (rc.returncode, rc.stdout, rc.stderr)
    assert "UNATTRIBUTED" in rc.stdout


# ── the roll-up, over N designs, with no dataset in sight ─────────────────────
def test_summarize_counts_the_same_records_it_was_given(tmp_path):
    a = fpa.attribute(_project(tmp_path / "a", _REAL_SHAPE, prompt=_PROMPT))
    b = fpa.attribute(_project(tmp_path / "b", [
        _step("rtl_gen", "PASS", deterministic_generator="comb_gate"),
        _step("reference_tb", "PASS"),
    ], prompt=_PROMPT, verdict="PASS"))
    s = fpa.summarize([a, b])
    assert s["designs"] == 2
    assert s["phase2_emitters"] == {"comb_gate": 1, "multiplexer": 1}
    assert s["phase2_distinct_emitters"] == 2
    assert s["phase3_failed_gates"] == {"final_audit": 1, "lec_equivalence": 1,
                                        "reference_tb": 1, "sdc_gen": 1}
    assert s["phase4"] == {"REPAIRED": 1, "NONE": 1}
    assert s["unattributed_phases"] == {}


def test_summarize_counts_an_unattributed_phase_separately(tmp_path):
    bare = tmp_path / "bare"
    (bare / "input").mkdir(parents=True)
    (bare / "input" / "phase1_prompt.md").write_text(_PROMPT)
    s = fpa.summarize([fpa.attribute(bare)])
    assert s["unattributed_phases"] == {"phase2_solving": 1,
                                        "phase3_verifying": 1,
                                        "phase4_debugging": 1}
    assert s["phase2_emitters"] == {}


def test_summarize_accepts_a_caller_record_that_nests_the_phases(tmp_path):
    """The adapter's shape: its own id plus `phases`. Same roll-up, no branch."""
    a = fpa.attribute(_project(tmp_path / "a", _REAL_SHAPE, prompt=_PROMPT))
    s = fpa.summarize([{"id": "anything", "phases": a}])
    assert s["phase2_emitters"] == {"multiplexer": 1}
