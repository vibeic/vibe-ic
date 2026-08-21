"""Declared timing and power evidence says which side of place-and-route it is.

WHY
===
MEASURED: of three reports in one sign-off family, ONE carried the stage
statement because its own emitter wrote it; the siblings deciding the slow and
fast corners were written by emitters that did not. 48 of 56 timing rows were
dropped as out of scope and both setup and hold reported an incomplete view set
rather than a failure. The READ side is already correct — the single reader
returns *undeclared* — so the gap is entirely producer-side.

THE POPULATION IS DRAWN FROM THE FLOW, AND IT IS TESTED
=======================================================
"A report a step offers as sign-off evidence" is not a judgement call: the flow
declares it. Two exclusions are load-bearing and are asserted from both sides,
because each one was a measured false positive or would force a wrong value:

  * NOT a report  — without the `.rpt` requirement this matched a power-INTENT
    document and synthesis stats, taking the population 2 -> 78 and producing
    six wrong findings. `test_a_power_intent_document_is_not_a_report`.
  * INEXPRESSIBLE — the stamp has exactly two values, and a post-CTS pre-route
    report can answer neither honestly. Disclosed, never silently dropped.
    `test_an_inexpressible_stage_is_disclosed_not_refused`.

chip-AGNOSTIC: flow declarations and stamp vocabulary.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
_TOOL = _PROGRAMS / "signoff_report_states_its_stage.py"
_REPO = _PROGRAMS.parents[3]

_spec = importlib.util.spec_from_file_location("srsis", _TOOL)
srsis = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(srsis)

_FLOW_REL = "vibe-ic-marketplace/plugins/vibe-ic/flow/phase1_phase2_phase3.yaml"
_PROG_REL = "vibe-ic-marketplace/plugins/vibe-ic/programs"

_FLOW = ("steps:\n"
         "  - id: 23\n"
         "    required_outputs:\n"
         "      - phase3/stage3/sta/post_route_timing.rpt\n")

_UNSTAMPED = ('def emit(project, body):\n'
              '    p = project / "sta" / "post_route_timing.rpt"\n'
              '    p.write_text(body)\n')
_STAMPED = ('def emit(project, body):\n'
            '    p = project / "sta" / "post_route_timing.rpt"\n'
            '    p.write_text("# STA_BASIS: POST_ROUTE_SPEF\\n" + body)\n')


def _tree(tmp_path, flow, modules):
    f = tmp_path / _FLOW_REL
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(flow)
    d = tmp_path / _PROG_REL
    d.mkdir(parents=True, exist_ok=True)
    for n, b in modules.items():
        (d / n).write_text(b)
    return tmp_path


def _run(root):
    cp = subprocess.run([sys.executable, str(_TOOL), str(root)],
                        capture_output=True, text=True)
    return cp.returncode, cp.stdout + cp.stderr


# ------------------------------------------------------------ red control

def test_an_unstamped_declared_report_goes_red(tmp_path):
    """THE NEGATIVE CONTROL: the sibling emitter that never writes the stamp."""
    root = _tree(tmp_path, _FLOW, {"runner.py": _UNSTAMPED})
    rc, out = _run(root)
    assert rc == 1, f"the defect did not go red:\n{out}"
    assert "post_route_timing.rpt" in out
    assert "UNDECLARED" in out


def test_the_same_emitter_with_the_stamp_passes(tmp_path):
    """BIDIRECTIONAL: add only the stamp and the identical emitter goes green."""
    root = _tree(tmp_path, _FLOW, {"runner.py": _STAMPED})
    rc, out = _run(root)
    assert rc == 0, out


def test_the_stamp_must_be_in_the_emitting_function(tmp_path):
    """Module granularity cannot answer this: one module emits many reports."""
    other = ('def unrelated():\n'
             '    return "# STA_BASIS: POST_ROUTE_SPEF"\n')
    root = _tree(tmp_path, _FLOW, {"runner.py": other + _UNSTAMPED})
    rc, out = _run(root)
    assert rc == 1, ("a stamp in a DIFFERENT function must not satisfy the "
                     "emitter of this report\n" + out)


# ------------------------------------------------- the exclusions, tested

def test_a_power_intent_document_is_not_a_report():
    assert not srsis.is_timing_or_power(
        "phase1/generated_docs/L21_POWER_INTENT.json")
    assert not srsis.is_timing_or_power("phase2/stage2/synth/stats.json")
    assert srsis.is_timing_or_power("phase3/stage3/sta/post_route_timing.rpt")


def test_a_geometry_report_is_not_in_the_population():
    for p in ["reports/phase3/drc_signoff.rpt", "reports/phase3/lvs.rpt",
              "reports/phase3/antenna.rpt", "reports/density.rpt"]:
        assert not srsis.is_timing_or_power(p), p


def test_an_inexpressible_stage_is_disclosed_not_refused(tmp_path):
    flow = ("steps:\n"
            "  - id: 19\n"
            "    required_outputs:\n"
            "      - phase3/stage3/cts/clock_tree.rpt\n"
            "  - id: 23\n"
            "    required_outputs:\n"
            "      - phase3/stage3/sta/post_route_timing.rpt\n")
    cts = ('def emit(project, body):\n'
           '    p = project / "cts" / "clock_tree.rpt"\n'
           '    p.write_text(body)\n')
    root = _tree(tmp_path, flow, {"runner.py": _STAMPED, "cts.py": cts})
    rc, out = _run(root)
    assert rc == 0, out
    assert "cannot describe a report written after CTS" in out
    assert "1 inexpressible" in out


def test_the_inexpressible_count_is_never_silently_zero(tmp_path):
    root = _tree(tmp_path, _FLOW, {"runner.py": _STAMPED})
    rc, out = _run(root)
    assert "0 inexpressible" in out


# ------------------------------------- the gap the record came from, disclosed

def test_an_emitted_but_undeclared_timing_report_is_disclosed(tmp_path):
    stray = ('def emit(project, body):\n'
             '    p = project / "reports" / "power.rpt"\n'
             '    p.write_text(body)\n')
    root = _tree(tmp_path, _FLOW, {"runner.py": _STAMPED, "power.py": stray})
    rc, out = _run(root)
    assert rc == 0, out
    assert "power.rpt" in out
    assert "nothing declares it as evidence" in out


# ------------------------------- the population cannot silently go empty

def test_the_real_flow_still_declares_timing_reports():
    declared = srsis.declared_outputs(_REPO / srsis.FLOW_REL)
    wanted = [p for p in declared if srsis.is_timing_or_power(p)]
    assert "phase3/stage3/sta/post_route_timing.rpt" in wanted
    assert "phase3/stage3/sta/pre_pnr_timing.rpt" in wanted
    assert len(wanted) >= 2, wanted


def test_an_empty_population_is_not_checked(tmp_path):
    root = _tree(tmp_path, "steps: []\n", {"runner.py": _STAMPED})
    rc, out = _run(root)
    assert rc == 2, out
    assert "Not a pass" in out


def test_no_identifiable_emitter_is_not_checked(tmp_path):
    root = _tree(tmp_path, _FLOW, {"unrelated.py": "x = 1\n"})
    rc, out = _run(root)
    assert rc == 2, out


def test_a_missing_flow_is_not_checked(tmp_path):
    (tmp_path / _PROG_REL).mkdir(parents=True)
    rc, out = _run(tmp_path)
    assert rc == 2, out
    assert "NOT CHECKED" in out


def test_absent_root_is_bad_invocation(tmp_path):
    rc, out = _run(tmp_path / "nope")
    assert rc == 3, out


def test_repository_itself_is_clean():
    rc, out = _run(_REPO)
    assert rc == 0, out
