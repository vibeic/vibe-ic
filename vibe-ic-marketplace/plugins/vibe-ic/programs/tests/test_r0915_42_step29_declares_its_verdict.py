"""R-0915-42 — step 29's declared verdict document is produced, never silence.

THE GAP, MEASURED on sha256's own run11 (`phase3/stage3/sim_postlayout/`):

    sdf.log  sdf_sim_skipped.json  sdf_sha256.tcl  sha256.sdf
    reports/phase2/gates/post_layout_sim.json   ABSENT

The run DID attempt the back-annotated simulation and DID reach a result — the
attempt note carries `"verdict": "ERROR"` and the reason "sdf_gate_sim reported
verdict=ERROR reason=no self-checking testbench" — and the document the flow
declares for that verdict did not exist. The step had an answer and published
nothing.

The flow names the producer in three places at once: step 29 lists
`post_layout_sim_check` under `programs:`, its gate clause invokes that same
program with `--json reports/phase2/gates/post_layout_sim.json`, and that path
is one of the step's own `required_outputs`.

`flow_declared_producer_run` cannot close it, and that is not a defect in that
program: it only fills a clause when the step's OTHER declared outputs are on
disk, and step 29's others are `results.log` / `pass.flag` — exactly what a
simulation that ran and FAILED never writes. A failed step is indistinguishable
from a never-run step by that test. So the RUN writes it, at the point where
the attempt happened.
"""
import json
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402


def _project(tmp_path: Path, *, note: dict | None = None,
             results_log: str | None = None, sdf: bool = True) -> Path:
    sim = tmp_path / "phase3/stage3/sim_postlayout"
    sim.mkdir(parents=True)
    if sdf:
        (sim / "top.sdf").write_text("(DELAYFILE)\n")
    if note is not None:
        (sim / "sdf_sim_skipped.json").write_text(json.dumps(note))
    if results_log is not None:
        (sim / "results.log").write_text(results_log)
    return tmp_path


def _run(project: Path, tmp_path: Path) -> dict:
    out = tmp_path / "gates" / "post_layout_sim.json"
    return json.loads(out.read_text())


# --------------------------------------------- direction 1: a named refusal

def test_the_declared_document_names_the_cause_not_only_the_symptom(tmp_path):
    """"no results.log" is what a reader can already see. The document has to
    say WHY: never attempted, could not compile, or ran and found no
    self-checking testbench."""
    proj = _project(tmp_path / "p", note={
        "verdict": "ERROR",
        "reason": "sdf_gate_sim reported verdict=ERROR reason=no "
                  "self-checking testbench",
    })
    rep = _run(proj, tmp_path)
    assert rep["verdict"] == "FAIL"
    f = [x for x in rep["findings"] if x["category"] == "NO_RESULTS"]
    assert len(f) == 1, rep["findings"]
    assert "no self-checking testbench" in f[0]["details"]
    assert "verdict=ERROR" in f[0]["details"]


def test_a_capability_flag_in_the_attempt_note_is_carried(tmp_path):
    proj = _project(tmp_path / "p", note={
        "verdict": "SKIPPED-CONDITION", "reason": "no iverilog on PATH",
        "capability_flag": "cap:no_simulator"})
    rep = _run(proj, tmp_path)
    assert "no iverilog on PATH" in rep["findings"][0]["details"]


def test_no_attempt_record_at_all_is_said_so_and_not_left_blank(tmp_path):
    """The other direction: when nothing states that a sim was attempted, the
    document must say THAT, rather than emitting an empty details field that
    reads as 'no further information'."""
    proj = _project(tmp_path / "p", note=None)
    rep = _run(proj, tmp_path)
    f = [x for x in rep["findings"] if x["category"] == "NO_RESULTS"][0]
    assert "no attempt record" in f["details"]
    assert f["details"].strip() != ""


def test_an_unreadable_attempt_note_is_disclosed_rather_than_swallowed(tmp_path):
    sim = tmp_path / "p/phase3/stage3/sim_postlayout"
    sim.mkdir(parents=True)
    (sim / "top.sdf").write_text("(DELAYFILE)\n")
    (sim / "sdf_sim_skipped.json").write_text("{not json")
    rep = _run(tmp_path / "p", tmp_path)
    assert "unreadable" in rep["findings"][0]["details"]


# ------------------------------------------------------- sim_executed

def test_sim_executed_is_false_when_nothing_ran(tmp_path):
    proj = _project(tmp_path / "p", note={"verdict": "ERROR", "reason": "x"})
    assert _run(proj, tmp_path)["summary"]["sim_executed"] is False


def test_sim_executed_is_true_only_on_a_real_log(tmp_path):
    proj = _project(tmp_path / "p", results_log="sim done\n$finish\n")
    assert _run(proj, tmp_path)["summary"]["sim_executed"] is True


def test_a_bare_pass_flag_does_not_claim_a_simulation_executed(tmp_path):
    """#437(d) already refuses a lone pass.flag as simulation evidence; this
    pins that `sim_executed` agrees with that refusal instead of contradicting
    it from the same document."""
    proj = _project(tmp_path / "p", note=None)
    (proj / "phase3/stage3/sim_postlayout/pass.flag").write_text("")
    rep = _run(proj, tmp_path)
    assert rep["summary"]["sim_executed"] is False


# ------------------------------------------------ the RUN produces it

def test_the_runner_writes_step29s_declared_output_through_its_own_producer():
    """One writer, one grammar: the run must not hand-author a second document
    in a shape that can disagree with the producer the gate re-runs."""
    src = (PROG / "phase3_one_shot_runner.py").read_text()
    assert "reports/phase2/gates/post_layout_sim.json" in src
    assert "import post_layout_sim_check as _plsc" in src
    assert '_plsc.main([str(project), "--json", str(_pls_json)])' in src


def test_the_runner_does_not_overwrite_a_document_the_run_already_produced():
    """It fills a gap; it never restates somebody else's verdict."""
    src = (PROG / "phase3_one_shot_runner.py").read_text()
    i = src.index("_pls_json = project / \"reports/phase2/gates/post_layout_sim.json\"")
    assert "if not _pls_json.is_file():" in src[i:i + 200]


def test_a_producer_that_cannot_run_is_disclosed_and_costs_the_run_nothing():
    src = (PROG / "phase3_one_shot_runner.py").read_text()
    i = src.index("import post_layout_sim_check as _plsc")
    window = src[i:i + 600]
    assert "except Exception" in window
    assert "could not be produced" in window
