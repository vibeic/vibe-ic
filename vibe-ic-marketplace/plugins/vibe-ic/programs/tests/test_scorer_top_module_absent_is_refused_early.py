"""An artefact that never declares the module the scorer instantiates is not an
answer, and must be refused where the flow can still act on it.

Measured on a 156-problem VerilogEval-v2 run: one candidate of 132 was emitted as
`module chip_top` with entirely correct logic and no `TopModule`. The identical
check existed ONLY at the sample-export step -- the last step of the run -- so:

  * the candidate was sent for blind AI review, where it CANNOT be failed: the
    review contract requires a challenge testbench that instantiates the missing
    module, and such a testbench cannot elaborate, so the reviewer can record
    neither PASS nor FAIL; and
  * the all-or-nothing export then blocked the ENTIRE run's score on it.

`benchmark_io_adapter.collect` now refuses it up front, which routes it to AI
backup for re-authoring -- the correct remedy.
"""
import json
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import benchmark_io_adapter as bio  # noqa: E402

_GOOD = "module TopModule (input x, output z);\n assign z = x;\nendmodule\n"
_CHIP_TOP = ("module chip_top (input x, output z);\n ModuleA A1(.x(x),.z(z));\n"
             "endmodule\nmodule ModuleA(input x, output z);\n assign z=x;\n"
             "endmodule\n")


def _project(tmp_path, rtl_text, status="PASS"):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "00_top.sv").write_text(rtl_text)
    rep = tmp_path / "reports" / "orchestrator"
    rep.mkdir(parents=True)
    (rep / "phase2_one_shot.json").write_text(
        json.dumps({"steps": [{"name": "rtl_gen", "status": status,
                               "detail": ""}]}))
    return tmp_path


def test_declaring_the_required_top_is_accepted(tmp_path):
    got = bio.collect("verilogeval", "P1", _project(tmp_path, _GOOD),
                      required_top="TopModule")
    assert got["ok"] is True


def test_missing_required_top_is_refused(tmp_path):
    """RED before the fix: this returned ok=True and the run carried an
    unscoreable sample all the way to export."""
    got = bio.collect("verilogeval", "P1", _project(tmp_path, _CHIP_TOP),
                      required_top="TopModule")
    assert got["ok"] is False
    assert "TopModule" in got["reason"]
    assert got["declared_modules"] == ["chip_top", "ModuleA"]


def test_refusal_names_what_was_declared_instead(tmp_path):
    """A refusal a human cannot act on is a bad refusal."""
    got = bio.collect("verilogeval", "P1", _project(tmp_path, _CHIP_TOP),
                      required_top="TopModule")
    assert "chip_top" in got["reason"]


def test_no_required_top_leaves_behaviour_unchanged(tmp_path):
    """Benchmarks whose scorer does not fix one top name must be unaffected."""
    got = bio.collect("verilogeval", "P1", _project(tmp_path, _CHIP_TOP))
    assert got["ok"] is True


def test_an_instantiation_is_not_a_declaration(tmp_path):
    """`TopModule u0(...)` inside another module must NOT satisfy the
    requirement to DECLARE TopModule -- that is the exact substring a naive
    check would accept, and the grading testbench would still not elaborate."""
    text = ("module chip_top (input x, output z);\n"
            "  TopModule u0 (.x(x), .z(z));\n endmodule\n")
    got = bio.collect("verilogeval", "P1", _project(tmp_path, text),
                      required_top="TopModule")
    assert got["ok"] is False


def test_a_commented_out_declaration_does_not_count(tmp_path):
    text = "// module TopModule (input x, output z);\n" + _CHIP_TOP
    got = bio.collect("verilogeval", "P1", _project(tmp_path, text),
                      required_top="TopModule")
    assert got["ok"] is False


def test_block_commented_declaration_does_not_count(tmp_path):
    text = "/* module TopModule (input x); endmodule */\n" + _CHIP_TOP
    got = bio.collect("verilogeval", "P1", _project(tmp_path, text),
                      required_top="TopModule")
    assert got["ok"] is False


def test_the_scaffold_refusal_still_fires_first(tmp_path):
    """The pre-existing rtl_gen guard must keep priority: a scaffold is refused
    for being a scaffold, not for its module name."""
    got = bio.collect("verilogeval", "P1",
                      _project(tmp_path, _GOOD, status="BLOCKED"),
                      required_top="TopModule")
    assert got["ok"] is False
    assert "rtl_gen reported BLOCKED" in got["reason"]


# ── the other half: the author must be TOLD the name ─────────────────────────
# Refusing an artefact for declaring the wrong top, without telling the author
# which name is required, makes the re-authoring loop unresolvable. On
# VerilogEval-v2 exactly ONE prompt of 156 never states the name, and that is
# the very problem this refusal fires on, so the requirement must travel with
# the backup task rather than be assumed derivable from the prompt.

import benchmark_dispatch as BD  # noqa: E402


def test_required_scorer_top_is_driven_by_the_registry_strategy():
    assert BD._required_scorer_top(
        {"layout": {"module_name_strategy": "always_TopModule"}}) == "TopModule"


def test_a_description_driven_benchmark_fixes_no_top_name():
    """Benchmarks that take the name from the description must stay unaffected."""
    assert BD._required_scorer_top(
        {"layout": {"module_name_strategy":
                    "from_description_module_name_line"}}) is None
    assert BD._required_scorer_top({}) is None
    assert BD._required_scorer_top({"layout": {}}) is None


def _backup_task(tmp_path, required_top):
    proj = tmp_path / "proj"
    (proj / "input").mkdir(parents=True)
    (proj / "input" / "phase1_prompt.md").write_text("implement something")
    return BD._make_ai_backup_task(
        "P1", proj, ["spec-to-rtl"], "rtl_gen_waive", "detail", "verilogeval-v2",
        tmp_path, tmp_path, required_top=required_top)


def test_backup_task_carries_the_required_top_name(tmp_path):
    task = _backup_task(tmp_path, "TopModule")
    assert task["required_top_module"] == "TopModule"
    assert "TopModule" in task["required_top_module_note"]


def test_backup_task_says_the_prompt_may_not_state_it(tmp_path):
    """The note must tell the author WHY they cannot just read it off the
    prompt, or they will trust the prompt and be refused again."""
    note = _backup_task(tmp_path, "TopModule")["required_top_module_note"]
    assert "may not state it" in note


def test_no_required_top_carries_no_instruction(tmp_path):
    task = _backup_task(tmp_path, None)
    assert task["required_top_module"] is None
    assert task["required_top_module_note"] is None
