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


def _marker(name="rtl_repair_retry_iter", **extras):
    """A repair/retry PROGRESS MARKER row, as the runner records one.

    R-0915-85 — `RTL_REPAIR_RETRY` was a status word for a row that is not an
    outcome at all. The runner writes the marker as `PASS` carrying
    `Disclosure.PROGRESS_MARKER`, and the attribution asks the DISCLOSURE, so
    the fixture has to carry it: a bare `PASS` here would be a gate that
    decided, which is the exact confusion the word caused.
    """
    s = _step(name, "PASS", **extras)
    s["disclosures"] = ["progress_marker"]
    return s


_PROMPT = ("Design a purely combinational 4-to-1 multiplexer.\n\n"
           "module TopModule (\n  input [3:0] in,\n  input [1:0] sel,\n"
           "  output out\n);\n")

# The shape measured on a real plain run of vibe_ic_one_shot_runner.py against
# a 4-to-1 multiplexer project: rtl_gen refused, the RTL repair/retry loop fired, rtl_gen
# then emitted with a NAMED emitter, and four gates failed.
_REAL_SHAPE = [
    _step("rtl_gen", "NOT_MEASURED"),
    _step("reference_tb", "FAIL"),
    _marker(),
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


@pytest.mark.parametrize("owner_status", ["PASS", "FAIL", None])
@pytest.mark.parametrize("native_status", ["PASS", "FAIL", "NOT_MEASURED", "SKIPPED", "missing-row", "missing-report"])
def test_sim_attribution_uses_native_report_verdict(tmp_path, owner_status, native_status):
    steps = [_step("rtl_validate", "FAIL"), _step("step4_functional_evidence", "PASS")]
    if owner_status:
        steps.append(_step("sim", owner_status))
    project = _project(tmp_path, steps, prompt=_PROMPT)
    name = "functional_simulation_and_coverage"
    if native_status != "missing-report":
        rows = [] if native_status == "missing-row" else [_step(name, native_status)]
        (project / "reports/flow_engine.json").write_text(json.dumps({"selected": 1, "steps": rows}))
    phase = fpa.attribute(project)["phase3_verifying"]
    observed = {**phase["not_attempted"], **phase["ran"], **phase["unclassified_status"]}
    expected = owner_status if native_status == "missing-report" else None if native_status == "missing-row" else native_status
    selected_name = "sim" if native_status == "missing-report" else name
    assert observed.get(selected_name) == expected
    assert phase["failed"] == sorted(["rtl_validate"] + ([selected_name] if expected == "FAIL" else []))
    if native_status != "missing-report":
        assert "sim" not in observed


@pytest.mark.parametrize("before,after,expected", [
    ("PASS", "FAIL", "ELIGIBLE"), ("PASS", None, "ELIGIBLE"),
    ("FAIL", "PASS", "INELIGIBLE"), (None, "PASS", "NOT_MEASURED")])
@pytest.mark.parametrize("owner_status", [None, "PASS", "FAIL", "ERROR", "REFUSED", "UNKNOWN"])
def test_native_sim_consumers_share_the_live_verdict(tmp_path, before, after, expected, owner_status):
    import benchmark_dispatch as bd
    steps = [_step("rtl_gen", "PASS"), _step("rtl_validate", "PASS")]
    if owner_status:
        steps.append(_step("sim", owner_status))
    project = _project(tmp_path, steps, prompt=_PROMPT)
    report = project / "reports/flow_engine.json"
    name = "functional_simulation_and_coverage"
    for status in (before, after):
        report.write_text(json.dumps({"selected": 1, "steps": [_step(name, status)] if status else []}))
        phases = fpa.attribute(project)
        assert phases["phase3_verifying"]["ran"].get(name) == status
        ledger = bd._required_gate_ledger({"exit": "4", "phases": phases})
        assert ledger["eligibility"] == ({"PASS": "ELIGIBLE", "FAIL": "INELIGIBLE"}.get(status, "NOT_MEASURED"))


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
        "before": "NOT_MEASURED", "after": "PASS"}


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
    p = _project(tmp_path, [_step("rtl_gen", "PASS_WITH_WAIVERS",
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
        _step("rtl_gen", "PASS_WITH_WAIVERS", fallback_skill="spec-to-rtl"),
        _marker(),
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
        _step("yosys_synth", "NOT_APPLICABLE"),
    ], prompt=_PROMPT)
    r = fpa.attribute(p)["phase3_verifying"]
    assert r["failed"] == ["reference_tb"]
    assert r["not_attempted"] == {"yosys_synth": "NOT_APPLICABLE"}
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
        _marker(),
        _step("rtl_gen", "PASS", deterministic_generator="vector_ops"),
    ], prompt=_PROMPT)
    ai = _project(tmp_path / "b", [
        _step("reference_tb", "FAIL"),
        _marker(),
        _step("rtl_gen", "PASS_WITH_WAIVERS", fallback_skill="spec-to-rtl"),
    ], prompt=_PROMPT)
    ep = fpa.attribute(prog)["phase4_debugging"]["events"][0]
    ea = fpa.attribute(ai)["phase4_debugging"]["events"][0]
    assert ep["mechanism"] == "PROGRAM"
    assert ea["mechanism"] == "AI_HANDOFF"
    assert ep["triggered_by"] == {"step": "reference_tb", "status": "FAIL"}
    assert ea["triggered_by"] == {"step": "reference_tb", "status": "FAIL"}


def test_phase4_calls_blocked_reentry_a_retry_not_a_physical_eco(tmp_path):
    """No prior candidate failed when rtl_gen could not look; this is retry."""
    p = _project(tmp_path, [
        _step("rtl_gen", "NOT_MEASURED"),
        _marker(),
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
        assert att[key]["reason"], (key, att[key])


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


# Inputs are declared independently in data/retained_rtl_attribution.json.
# These are source fixtures, not copies of a design or a reporter's capture.
_RETAINED_INPUT_PATH = Path(__file__).parent / "data" / "retained_rtl_attribution.json"
_RETAINED_INPUTS = json.loads(_RETAINED_INPUT_PATH.read_text())["cases"]
_RETAINED_EXPECTED = {
    # id: (ownership, solved_by, emitter)
    "fresh-emit": ("generated", "EMITTER", "neutral_logic_emit"),
    "fresh-waived-emit": ("generated", "WAIVED_NO_SKILL", None),
    "retained-handoff": ("generated", "AI_BACKUP", None),
    "retained-other-producer": ("generated", "AI_BACKUP", None),
    "fallback-no-artifact": ("empty", "AI_BACKUP", None),
    "modified-rtl": ("authored", "AI_BACKUP", None),
    "added-authored-rtl": ("authored", "AI_BACKUP", None),
    "missing-ledger": ("unknown", "AI_BACKUP", None),
    "invalid-ledger": ("unknown", "AI_BACKUP", None),
    "foreign-preexisting": ("unknown", "AI_BACKUP", None),
    "source-comment-spoof": ("unknown", "AI_BACKUP", None),
    "removed-all-rtl": ("generated", "AI_BACKUP", None),
    "missing-producer": ("generated", "AI_BACKUP", None),
    "invalid-producer": ("generated", "AI_BACKUP", None),
    "retained-without-fallback": ("generated", "WAIVED_NO_SKILL", None),
}
_REUSED_IDS = {"retained-handoff", "retained-other-producer",
               "retained-without-fallback"}


def _retained_project(tmp_path, declared):
    project = tmp_path / declared["id"]
    stage = project / "phase2" / "stage1"
    stage.mkdir(parents=True)
    prompt = project / "input" / "phase1_prompt.md"
    prompt.parent.mkdir()
    prompt.write_text(declared["prompt"])
    for rel, text in declared["rtl"].items():
        dest = stage / "rtl" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text)
    if declared["ledger"] is not None:
        (stage / "rtl.provenance.json").write_text(
            json.dumps(declared["ledger"], indent=2) + "\n")
    if declared["fallback_note"] is not None:
        (stage / "fallback_skill.md").write_text(declared["fallback_note"])
    report = project / "reports" / "orchestrator" / "phase2_one_shot.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps(declared["report"], indent=2) + "\n")
    return project


def _input_state(project):
    """Include inode and mtime: rewriting equal RTL/ledger bytes is forbidden."""
    import hashlib
    return {
        p.relative_to(project).as_posix(): {
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            "inode": p.stat().st_ino, "mtime_ns": p.stat().st_mtime_ns,
        }
        for p in sorted(project.rglob("*")) if p.is_file()
        and p.name not in (fpa.REPORT_NAME, "vibe_ic_one_shot.json",
                           "consumer.stdout", "consumer.stderr")
    }


@pytest.mark.parametrize("consumer", ["pure", "standalone"])
@pytest.mark.parametrize("declared", _RETAINED_INPUTS,
                         ids=[c["id"] for c in _RETAINED_INPUTS])
def test_retained_rtl_origin_through_report_consumers(
        tmp_path, declared, consumer, monkeypatch, record_property):
    import hashlib
    import rtl_provenance

    project = _retained_project(tmp_path, declared)
    before = _input_state(project)
    ownership = rtl_provenance.classify(project)

    if consumer == "pure":
        att = fpa.attribute(project)
    else:
        proc = subprocess.run([sys.executable, str(MODULE), str(project), "--json"],
                              capture_output=True, text=True)
        (project / "consumer.stdout").write_text(proc.stdout)
        (project / "consumer.stderr").write_text(proc.stderr)
        assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
        att = json.loads((project / "reports" / "orchestrator"
                          / fpa.REPORT_NAME).read_text())
        stdout_att = json.loads(proc.stdout)
        stdout_att.pop("report")
        assert stdout_att == att

    after = _input_state(project)
    current = rtl_provenance.classify(project)
    observed = {"input_id": declared["id"], "consumer": consumer,
                "input_population_sha256": hashlib.sha256(
                    _RETAINED_INPUT_PATH.read_bytes()).hexdigest(),
                "attribution": att, "ownership_before": ownership,
                "ownership_after": current,
                "input_state_before": before, "input_state_after": after}
    record_property("observed", json.dumps(observed, sort_keys=True))
    (tmp_path / "observed.json").write_text(json.dumps(observed, indent=2) + "\n")

    expected_kind, expected_solver, expected_emitter = _RETAINED_EXPECTED[declared["id"]]
    assert before == after
    assert ownership == current
    assert ownership[0] == expected_kind
    # Both publication paths must return exactly the pure API's current facts.
    assert att == fpa.attribute(project)
    assert att["phase3_verifying"]["failed"] == ["reference_tb"]
    assert att["phase3_verifying"] == fpa.phase3_verifying(declared["report"], None)
    assert att["phase4_debugging"] == fpa.phase4_debugging(declared["report"], None)
    r = att["phase2_solving"]
    # Existing values fail first on the pre-fix source, independently of new
    # fields. The paired RED is a wrong attribution, not an absent feature.
    assert (r["solved_by"], r["emitter"]) == (expected_solver, expected_emitter), r
    assert r["status"] == declared["report"]["steps"][0]["status"]
    if declared["id"] in _REUSED_IDS:
        skill = declared["report"]["steps"][0]["extras"].get("fallback_skill")
        assert r["mechanism"] == ("AI_HANDOFF" if skill else "NONE")
        assert r["actor"] == (skill or "UNKNOWN")
        assert r["ai_authored_in_this_invocation"] is False
        assert r["emitter"] is None
        assert not fpa.summarize([att])["phase2_emitters"]
    elif declared["id"] == "fresh-emit":
        assert r["mechanism"] == "PROGRAM" and r["actor"] == "runner"
        assert not r.get("reused", False)
    elif declared["id"] == "fresh-waived-emit":
        # A recorded current output prevents a retained/no-new-emission claim.
        # Preserve the existing waiver attribution; changing it is out of scope.
        assert r["mechanism"] == "NONE" and r["actor"] == "UNKNOWN"
        assert not r.get("reused", False)
        assert "emitted_in_this_invocation" not in r
    else:
        assert r["mechanism"] == "AI_HANDOFF" and r["actor"] == "spec-to-rtl"
        assert r["ai_authored_in_this_invocation"] is False
        assert not r.get("reused", False)
        assert not fpa.summarize([att])["phase2_emitters"]
