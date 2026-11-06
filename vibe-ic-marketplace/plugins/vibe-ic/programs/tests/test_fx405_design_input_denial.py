"""FX_405 — `_reference_flow_boundary.design_input_denial`, the one check every
design-input reader makes before it opens a file.

It unions two existing authorities and restates neither:
`step_input_scope.oracle_reason` everywhere under `input/`, and — inside the
staged tool-config trees only — the directory vocabulary plus the
`is_oracle_name` word rule llv1 W21 applies to the same trees.

The word rule is scoped on purpose. MEASURED on the tracked corpus: applied to
all of `input/` it denies `docs/L1_product_metadata.md` in five designs and 91
staged PDK `rule_decks/` files, all genuine design input.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import _reference_flow_boundary as rfb  # noqa: E402

_QOR = json.dumps({"timing__setup__ws": {"value": 0.1, "compare": ">="},
                   "design__instance__area": {"value": 900, "compare": "<="}})

DENIED = {
    "input/reference_flow/golden/flow.mk": "export X = 1\n",
    "input/reference_flow/score/cfg.mk": "export X = 1\n",
    "input/reference_flow/metrics/m.tcl": "set x 1\n",
    "input/reference_flow/golden.mk": "export X = 1\n",
    "input/reference_flow/expected_results.tcl": "set x 1\n",
    "input/reference_flow/orfs_rules.json": _QOR,
    "input/reference_flow/qor.json": _QOR,          # judged by CONTENT
    "input/constraints/golden_timing.sdc": "create_clock -period 1\n",
    "input/constraints/oracle.sdc": "create_clock -period 2.5\n",
    "input/golden/top.v": "module top; endmodule\n",
    "input/expected/out.txt": "x\n",
    "input/score/score.py": "x = 1\n",
    "input/canonical_samples/s.v": "module s; endmodule\n",
    "input/rtl/top_ref.v": "module top; endmodule\n",
    "input/rtl/verified_top.v": "module top; endmodule\n",
    # Review 405: a RESULT-named config file outside the staged trees.
    "input/flow/expected_results.tcl": "set x 1\n",
    "input/flow/golden_timing.sdc": "create_clock -period 1\n",
    "input/cfg/results.json": "{}\n",
    # Review wave 8 (shared with W21): one vocabulary, and a word followed by a
    # digit, a space or a capital is still the word.
    "input/reference_flow/oracle.mk": "export X = 1\n",
    "input/reference_flow/ground_truth_qor/flow.mk": "export X = 1\n",
    "input/ip/reference_flow/golden/config.tcl": "set ::env(DIE_AREA) \"0 0 200 200\"\n",
    "input/reference_flow/golden2.mk": "export X = 1\n",
    "input/reference_flow/results1/flow.mk": "export X = 1\n",
    "input/reference_flow/GoldenConfig.mk": "export X = 1\n",
    "input/flow/golden2_timing.sdc": "create_clock -period 1\n",
}

ALLOWED = {
    "input/reference_flow/flow.mk": "export CORE_UTILIZATION = 40\n",
    "input/reference_flow/pre_syn/tcl/sta_run_reports.tcl": "report_checks\n",
    "input/reference_flow/design.sdc": "create_clock -period 10\n",
    "input/constraints/clock.sdc": "create_clock -period 10\n",
    "input/rtl/top.v": "module top; endmodule\n",
    "input/docs/L1_product.md": "# L1\n",
    # The over-match controls: an oracle WORD outside a staged config tree.
    "input/docs/L1_product_metadata.md": "# metadata\n",
    "input/docs/golden_waveform.md": "# waveform\n",
    "input/pdk/lib/rule_decks/antenna.drc": "rule\n",
    # In the constraints tree only the RESULT words deny: SDC's "design rule
    # constraints" and a metrics budget are design input (review 405).
    "input/constraints/design_rules.sdc": "set_max_fanout 16 [current_design]\n",
    "input/constraints/metrics_budget.sdc": "set_max_transition 0.5 [current_design]\n",
    # Outside the staged trees: prose is exempt, and so is a non-result word.
    "input/docs/expected_results.md": "# expected behaviour\n",
    "input/flow/golden_notes.txt": "notes\n",
    "input/flow/rules.tcl": "set x 1\n",
    # A vocabulary word inside another word is not the word.
    "input/reference_flow/coracle.mk": "export X = 1\n",
    "input/reference_flow/truth_table.mk": "export X = 1\n",
    "input/constraints/resultant.sdc": "set_max_fanout 8 [current_design]\n",
}


@pytest.fixture()
def project(tmp_path):
    for rel, body in {**DENIED, **ALLOWED}.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    return tmp_path


@pytest.mark.parametrize("rel", sorted(DENIED))
def test_oracle_input_is_denied_with_a_reason(project, rel):
    reason = rfb.design_input_denial(project, project / rel)
    assert reason and reason.startswith("§4.05"), (rel, reason)


@pytest.mark.parametrize("rel", sorted(ALLOWED))
def test_design_input_is_allowed(project, rel):
    assert rfb.design_input_denial(project, project / rel) is None, rel


def test_a_relative_project_is_judged_the_same(project, monkeypatch):
    monkeypatch.chdir(project.parent)
    rel_proj = Path(project.name)
    for rel in DENIED:
        assert rfb.design_input_denial(rel_proj, rel_proj / rel), rel
    for rel in ALLOWED:
        assert rfb.design_input_denial(str(rel_proj), str(rel_proj / rel)) is None


def test_paths_outside_input_are_not_its_business(project):
    for rel in ("phase1/input_doc/golden.txt", "phase2/stage1/rtl/top_ref.v",
                "golden/top.v"):
        assert rfb.design_input_denial(project, project / rel) is None, rel


def test_a_name_denied_file_is_not_opened(project):
    """Judged on the NAME: the check itself must not read the answer."""
    probe = r'''
import sys
sys.path.insert(0, sys.argv[1])
import _reference_flow_boundary as rfb
from pathlib import Path
proj = Path(sys.argv[2]); opened = []
sys.addaudithook(lambda e, a: opened.append(a[0]) if e == "open" and isinstance(a[0], str) and a[0].startswith(str(proj)) else None)
for rel in sys.argv[3:]:
    assert rfb.design_input_denial(proj, proj / rel), rel
print("OPENED", len(opened), opened)
'''
    by_name = ["input/reference_flow/golden/flow.mk",
               "input/reference_flow/golden.mk",
               "input/reference_flow/expected_results.tcl",
               "input/reference_flow/orfs_rules.json",
               "input/constraints/golden_timing.sdc",
               "input/golden/top.v", "input/expected/out.txt"]
    done = subprocess.run([sys.executable, "-c", probe, str(PROGRAMS),
                           str(project), *by_name],
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]
    assert "OPENED 0 []" in done.stdout, done.stdout


def test_a_classifier_can_leave_the_file_name_to_content(project):
    """`file_name_words=False` (the phase-3 reference-flow audit's classifier
    loop, bound by `test_reference_flow_ingest_coverage`) drops the word rule
    for the FILE name only: a directory and the `_ref.` / `verified_` forms
    still deny unopened, and a QoR-shaped file is still denied on content."""
    rf = project / "input" / "reference_flow"
    (rf / "rules.json").write_text('{"a": 1}\n')
    assert rfb.design_input_denial(project, rf / "rules.json")
    assert rfb.design_input_denial(
        project, rf / "rules.json", file_name_words=False) is None
    for rel in ("input/reference_flow/golden/flow.mk",
                "input/reference_flow/metrics/m.tcl",
                "input/reference_flow/qor.json",
                "input/rtl/top_ref.v"):
        assert rfb.design_input_denial(
            project, project / rel, file_name_words=False), rel


# ── a file the content rule cannot read is the reader's to record ──────────

def _unreadable(path: Path) -> Path:
    path.chmod(0)
    if os.access(path, os.R_OK):
        pytest.skip("running as root: mode 000 does not make a file unreadable")
    return path


def test_an_unreadable_design_recipe_is_not_called_an_oracle(project):
    recipe = _unreadable(project / "input/reference_flow/flow.mk")
    assert rfb.design_input_denial(project, recipe) is None
    # The step-scope guard keeps its fail-closed reading of the same file.
    import step_input_scope as sis
    assert sis.oracle_reason("reference_flow/flow.mk", project / "input")


def test_a_dangling_design_recipe_is_not_called_an_oracle(project):
    link = project / "input/reference_flow/linked.mk"
    link.symlink_to(project / "input/reference_flow/does_not_exist.mk")
    assert rfb.design_input_denial(project, link) is None


def test_a_symlink_loop_falls_through_to_reader_unreadable_handling(project):
    for rel in ("input/constraints/loop.sdc", "input/reference_flow/loop.mk"):
        link = project / rel
        link.symlink_to(link.name)
        assert rfb.design_input_denial(project, link) is None


def test_a_readable_symlink_outside_input_is_denied(project):
    outside = project / "golden" / "ports.md"
    outside.parent.mkdir()
    outside.write_text("input clock_in\n")
    link = project / "input" / "docs" / "design.md"
    link.symlink_to(outside)

    assert link.is_file()
    denial = rfb.design_input_denial(project, link)
    observed = "DENIED" if denial else "ALLOWED"
    assert observed == "DENIED"
    assert denial == (
        "§4.05: input file resolves outside input/")






def test_a_dangling_link_outside_input_stays_unreadable(tmp_path):
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True)
    link = docs / "design.md"
    link.symlink_to(tmp_path / "golden" / "missing.md")

    assert rfb.design_input_denial(tmp_path, link) is None


def test_nested_reference_flow_oracle_directory_is_denied(project):
    path = project / "input/ip/reference_flow/golden/config.tcl"
    assert rfb.design_input_denial(project, path).startswith("§4.05")


def test_an_unreadable_oracle_is_still_denied_by_its_name(project):
    golden = _unreadable(project / "input/reference_flow/golden.mk")
    assert rfb.design_input_denial(project, golden)








def test_an_unreadable_design_sdc_is_still_the_design_sdc(tmp_path):
    import sdc_constraints as sdc
    rf = tmp_path / "input" / "reference_flow"
    rf.mkdir(parents=True)
    design = rf / "design.sdc"
    design.write_text("create_clock -name clk -period 10 [get_ports clk]\n")
    _unreadable(design)
    assert sdc.collect_sdc_files(tmp_path) == [design]
