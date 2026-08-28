"""#216 — the formal (Step 5) environment gap must be ACTIONABLE, and a
waived formal step must defer only its GENUINE dependents.

Measured defect (EXAMPLE): Step 5 (formal) reported an `ENV_UNAVAILABLE`
waiver that was a dead end. Three separate faults produced it:

  1. `formal_property_run` could not tell "the proof engine was never
     reached" from "the proof ran and was inconclusive". An unreachable
     engine produced `verdict: INCONCLUSIVE` with one UNKNOWN property row
     per .sby task — rows manufactured from the CONFIG, on a transcript that
     was a single `No such container` line. A proof-strength claim on zero
     proof evidence.
  2. `detect_engines` hardcoded `abc: True`, so the report asserted an engine
     was available inside an environment it had failed to reach.
  3. `flow_compliance_check` had no `formal` role-name in its ENV_UNAVAILABLE
     step-name map, so a formal env-waiver hit `sid is None -> continue` and
     was dropped WITHOUT A TRACE. The step then showed a bare MISSING that
     never mentioned the formal engine, the waiver, or the ticket.

These tests assert PUBLIC behaviour only: the CLI exit codes and the JSON /
Markdown artifacts the two programs emit. chip-AGNOSTIC — the fixture design
is a 4-bit counter with one safety property; no chip, vendor or PDK literal
participates.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_PROGRAMS = Path(__file__).resolve().parent.parent
_FORMAL = _PROGRAMS / "formal_property_run.py"
_COMPLIANCE = _PROGRAMS / "flow_compliance_check.py"
_FLOW_YAML = _PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"

#: A container name that cannot exist → the environment is GENUINELY absent.
_ABSENT_CONTAINER = "vibeic_no_such_container_211"
#: The container the image ships; present on a provisioned run host.
_REAL_CONTAINER = "vibeic-eda"

_RTL = """\
module ctr (input clk, input rst, output reg [3:0] q);
  always @(posedge clk) begin
    if (rst) q <= 4'd0;
    else if (q == 4'd9) q <= 4'd0;
    else q <= q + 4'd1;
  end
endmodule
"""

_HARNESS = """\
module formal_ctr (input clk, input rst);
  wire [3:0] q;
  ctr dut (.clk(clk), .rst(rst), .q(q));
  reg init = 1;
  always @(posedge clk) init <= 0;
  always @(posedge clk) if (!init) assert (q <= 4'd9);
  initial assume (rst);
endmodule
"""


def _mk_design(root: Path) -> tuple[Path, Path]:
    (root / "rtl").mkdir(parents=True, exist_ok=True)
    rtl = root / "rtl" / "ctr.v"
    rtl.write_text(_RTL)
    harness = root / "formal_ctr.sv"
    harness.write_text(_HARNESS)
    return rtl, harness


def _run_formal(project: Path, container: str):
    rtl, harness = _mk_design(project)
    r = _pr.run(
        [sys.executable, str(_FORMAL), str(project),
         "--harness", str(harness), "--rtl", str(rtl),
         "--top", "formal_ctr", "--container", container],
        capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def _formal_dir(project: Path) -> Path:
    return project / "phase2" / "stage1" / "formal"


def _docker_container_running(name: str) -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        r = _pr.run(
            ["docker", "ps", "--filter", f"name=^{name}$", "--format", "{{.Names}}"],
            capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError):
        return False
    return name in (r.stdout or "").split()


# ── the environment is GENUINELY absent ───────────────────────────────────

def test_absent_env_reports_env_unavailable_not_inconclusive(tmp_path):
    """An unreachable engine is an ENVIRONMENT gap, never a proof verdict.

    Pre-fix this returned `INCONCLUSIVE`, which is a statement about solver
    convergence — a claim the evidence (one docker error line) cannot
    support.
    """
    _run_formal(tmp_path, _ABSENT_CONTAINER)
    manifest = _formal_dir(tmp_path) / "formal_env_unavailable.json"
    assert manifest.is_file(), "no ENV_UNAVAILABLE manifest was emitted"
    data = json.loads(manifest.read_text())
    assert data["verdict"] == "ENV_UNAVAILABLE"
    assert data["all_proved"] is False


def test_absent_env_names_capability_location_and_remedy(tmp_path):
    """`ENV_UNAVAILABLE` with no detail is a dead end for whoever must fix
    the host. The report must name WHAT is missing, WHERE the flow looked,
    and WHAT to install or stage."""
    _run_formal(tmp_path, _ABSENT_CONTAINER)
    data = json.loads(
        (_formal_dir(tmp_path) / "formal_env_unavailable.json").read_text())
    gap = data["env_gap"]

    assert gap["missing_capability"].strip(), "missing capability not named"
    # WHERE the flow looked must identify the search location concretely.
    assert _ABSENT_CONTAINER in gap["searched"]
    # WHAT to do about it must be a non-trivial instruction.
    assert len(gap["remedy"]) > 40
    assert _ABSENT_CONTAINER in gap["remedy"]
    # The raw tool message is preserved so the diagnosis is checkable.
    assert "No such container" in gap["tool_message"]

    # The human-readable face carries the same three answers.
    md = (_formal_dir(tmp_path) / "formal_env_unavailable.md").read_text()
    assert gap["missing_capability"] in md
    assert _ABSENT_CONTAINER in md


def test_absent_env_fabricates_no_property_rows(tmp_path):
    """Nothing ran, so there is no property result to report.

    Pre-fix, one UNKNOWN row per .sby task was manufactured from the config
    (property_count == 2) even though the transcript contained no proof.
    """
    _run_formal(tmp_path, _ABSENT_CONTAINER)
    data = json.loads(
        (_formal_dir(tmp_path) / "formal_env_unavailable.json").read_text())
    assert data["property_count"] == 0
    assert data["properties"] == []


def test_absent_env_writes_no_proof_artifact(tmp_path):
    """A run that never reached the engine must leave nothing that looks
    like a proof. `results.json` is the artifact the Step-5 evidence gate
    consumes; emitting it here would put false evidence in the record."""
    _run_formal(tmp_path, _ABSENT_CONTAINER)
    assert not (_formal_dir(tmp_path) / "results.json").exists()


def test_absent_env_never_claims_an_engine_is_available(tmp_path):
    """An availability map is evidence ABOUT the environment. Asserting a
    tool is present inside an environment we could not reach is a claim with
    nothing behind it (pre-fix: `abc: True`, hardcoded)."""
    _run_formal(tmp_path, _ABSENT_CONTAINER)
    data = json.loads(
        (_formal_dir(tmp_path) / "formal_env_unavailable.json").read_text())
    avail = data["engine_availability"]
    assert avail["_env_reachable"] is False
    assert not any(v for k, v in avail.items() if k != "_env_reachable"), (
        "an engine was reported available in an unreachable environment")


def test_absent_env_exit_code_is_not_success(tmp_path):
    """The gap must be loud at the process boundary too — never rc=0."""
    rc, _, _ = _run_formal(tmp_path, _ABSENT_CONTAINER)
    assert rc != 0


def test_absent_env_gate_fails_but_names_the_gap(tmp_path):
    """The Step-5 evidence gate must stay a hard FAIL when the engine was
    unreachable — an environment gap is NOT a self-skip and must never go
    vacuous — while carrying the actionable detail instead of the bare
    "nothing claims a proof"."""
    _run_formal(tmp_path, _ABSENT_CONTAINER)
    gate = _PROGRAMS / "formal_proof_evidence_check.py"
    r = _pr.run([sys.executable, str(gate), str(tmp_path)],
                       capture_output=True, text=True)
    report = json.loads(r.stdout)

    assert report["verdict"] == "FAIL"
    assert r.returncode == 1, "an unreachable environment must not be vacuous"

    finding = " ".join(report["findings"])
    assert "ENV_UNAVAILABLE" in finding
    assert _ABSENT_CONTAINER in finding      # where the flow looked
    assert "not running" in finding          # what to do about it


# ── the environment IS available ──────────────────────────────────────────

@pytest.mark.skipif(
    not _docker_container_running(_REAL_CONTAINER),
    reason=f"container {_REAL_CONTAINER!r} not running on this host",
)
def test_available_env_runs_a_real_proof_and_needs_no_waiver(tmp_path):
    """The decisive test for "is this a discovery bug or an environment
    gap?": when the engine IS reachable, formal RUNS, proves the property,
    and emits no environment gap at all. SymbiYosys ships in our own image
    at /usr/local/bin/sby, so on a provisioned host there is nothing to
    waive.

    NOTE ON INTENT: this is a CHARACTERIZATION test, not a defect detector.
    It passes on pre-fix code too — and that is precisely the finding. The
    formal environment was never actually absent on the EXAMPLE run host, so
    an `ENV_UNAVAILABLE` verdict for Step 5 was never supported by the
    environment. This test pins that fact down so a future regression that
    starts declaring the environment unavailable while sby is right there
    is caught immediately.
    """
    # The container only sees paths under the mounted home directory.
    home_tmp = Path.home() / ".pytest_formal_211" / tmp_path.name
    if home_tmp.exists():
        shutil.rmtree(home_tmp)
    home_tmp.mkdir(parents=True)
    try:
        rc, out, err = _run_formal(home_tmp, _REAL_CONTAINER)
        fd = _formal_dir(home_tmp)
        assert not (fd / "formal_env_unavailable.json").exists(), (
            "an environment gap was reported although the engine was "
            f"reachable: {out}\n{err}")
        results = json.loads((fd / "results.json").read_text())
        assert results["verdict"] == "PASS"
        assert results["all_proved"] is True
        assert results["property_count"] > 0
        assert rc == 0
        # The proof is real: a SymbiYosys transcript, not a synthesised
        # verdict. Without this the assertions above could be satisfied by a
        # fabricated results.json.
        log = (fd / "formal_ctr_formal.sby.log").read_text()
        assert "DONE (PASS" in log
        assert "engine_0" in log
    finally:
        shutil.rmtree(home_tmp, ignore_errors=True)


# ── the compliance report: no silent drops, justified cascade ─────────────

_COMPLETE_WAIVER = {
    "step": "formal",
    "verdict_tier": "ENV_UNAVAILABLE",
    "ticket": "EXAMPLE-FORMAL-1",
    "review_required": True,
    "evidence": ["phase2/stage1/formal/formal_env_unavailable.json"],
    "rationale": (
        "SymbiYosys formal engine not reachable from this run host: sby was "
        "not found via docker exec vibeic-eda; stage the vibeic-eda image or "
        "start the container to run Step 5."
    ),
}


def _write_waivers(project: Path, entries) -> None:
    (project / "waivers.json").write_text(
        json.dumps({"waivers": entries}, indent=2) + "\n")


def _compliance(project: Path, out_json: Path):
    rc = _pr.run(
        [sys.executable, str(_COMPLIANCE), str(project), "--strict",
         "--json", str(out_json)],
        capture_output=True, text=True)
    return rc.returncode, json.loads(out_json.read_text())


def _declared_formal_dependents() -> set:
    """Steps the flow DECLARES depend on Step 5's artefacts.

    vibe-ic#776 — this used to return the transitive `blocks_on` closure, which
    is the very thing the test below calls "an over-broad cascade would itself
    be the defect". `blocks_on` is an ORDERING edge: on this flow it makes 1221
    (step, ancestor) pairs and only 6 of them carry a declared dependency. The
    closure returned {6, 39} for Step 5, and neither step's gate nor its
    required_outputs names anything Step 5 writes (`phase2/stage1/formal/*.sby`,
    `phase2/stage1/formal/results.json`,
    `phase2/stage1/sim_full_stack/results.json`) — Step 6 builds an FPGA image,
    Step 39 recompiles it and tests on board.

    Derived from the producer's own relation so it cannot drift away from what
    the checker does, and so a real declaration added to the flow later shows up
    here as a widened expectation rather than a silent one.
    """
    doc = yaml.safe_load(_FLOW_YAML.read_text())
    steps = [s for s in doc["steps"]
             if isinstance(s, dict) and s.get("id") is not None]
    sys.path.insert(0, str(_COMPLIANCE.parent))
    import flow_compliance_check as _fcc

    ids = [s["id"] for s in steps if str(s["id"]) != "P0"]
    results = [_fcc.StepResult(id=i, name="", stage="",
                               status=("WAIVED" if i == 5 else "MISSING"))
               for i in ids]
    info = _fcc._attribute_cascade_verdicts(results, steps,
                                            {5: {"ticket": "T"}})
    return {sid for sid, _parent, _ticket in info["deferred_by_upstream"]}


def test_formal_env_waiver_binds_to_the_formal_step(tmp_path):
    """A complete formal ENV_UNAVAILABLE waiver must reach the formal step.

    Pre-fix, `formal` was absent from the role-name map, so this waiver was
    silently discarded and Step 5 reported a bare MISSING.
    """
    _write_waivers(tmp_path, [_COMPLETE_WAIVER])
    _, report = _compliance(tmp_path, tmp_path / "r.json")
    step5 = next(s for s in report["steps"] if s["id"] == 5)
    assert step5["status"] == "WAIVED"


def test_cascade_defers_only_genuinely_dependent_steps(tmp_path):
    """The cascade must be justified PER STEP, not blanket.

    A waived formal step may only defer the steps that the flow actually
    declares as depending on formal results. Every other step must keep the
    verdict it would have had with no waiver at all — an over-broad cascade
    would itself be the defect.
    """
    baseline_dir = tmp_path / "baseline"
    waived_dir = tmp_path / "waived"
    baseline_dir.mkdir()
    waived_dir.mkdir()
    _write_waivers(waived_dir, [_COMPLETE_WAIVER])

    _, base = _compliance(baseline_dir, tmp_path / "base.json")
    _, waived = _compliance(waived_dir, tmp_path / "waived.json")

    base_status = {s["id"]: s["status"] for s in base["steps"]}
    waived_status = {s["id"]: s["status"] for s in waived["steps"]}
    changed = {sid for sid in base_status
               if base_status[sid] != waived_status.get(sid)}

    # Exactly the waived step plus its DECLARED transitive dependents moved.
    assert changed == {5} | _declared_formal_dependents(), (
        f"cascade touched steps it should not have: {sorted(changed)}")

    deferred = {s["id"] for s in waived["steps"]
                if s["status"] == "DEFERRED-BY-UPSTREAM"}
    assert deferred == _declared_formal_dependents()
    # And each deferral names the parent it inherited from, so a reader can
    # tell "skipped because a dependency was waived" from "ran, produced
    # nothing".
    for s in waived["steps"]:
        if s["status"] == "DEFERRED-BY-UPSTREAM":
            assert "deferred-by-upstream(5" in s["cascade_note"]

    # #776 — the ordering fact is not thrown away, it is recorded WITHOUT
    # softening: the steps ordered behind step 5 say so and stay MISSING. This
    # is what keeps the assertions above from passing vacuously.
    ordered_behind = {s["id"] for s in waived["steps"]
                      if "waived-ancestor-undeclared(5)" in s["cascade_note"]}
    assert ordered_behind, "the ordering fact must still be attributed"
    for sid in ordered_behind:
        assert waived_status[sid] == "MISSING", (sid, waived_status[sid])


def test_waived_formal_never_counts_as_a_pass_downstream(tmp_path):
    """A waiver is open work. Neither the waived step nor anything deferred
    behind it may be counted as executed-PASS, and the run must still fail
    strict mode."""
    _write_waivers(tmp_path, [_COMPLETE_WAIVER])
    rc, report = _compliance(tmp_path, tmp_path / "r.json")

    statuses = {s["id"]: s["status"] for s in report["steps"]}
    assert statuses[5] == "WAIVED"
    for sid in _declared_formal_dependents():
        assert statuses[sid] != "PASS"

    assert report["counts"]["PASS"] == 0
    assert report["counts"]["WAIVED"] == 1
    assert report["overall"] == "FAIL"
    assert rc != 0


def test_unbindable_env_waiver_is_reported_not_silently_dropped(tmp_path):
    """A waiver naming an unknown step role must produce a visible advisory
    naming the problem — pre-fix it vanished with no trace anywhere in the
    report."""
    _write_waivers(tmp_path, [{**_COMPLETE_WAIVER, "step": "formal_engine"}])
    _, report = _compliance(tmp_path, tmp_path / "r.json")

    advisory = " ".join(report["advisories"])
    assert "formal_engine" in advisory
    assert "NOT applied" in advisory
    # The remedy lists the role names that WOULD bind.
    assert "formal" in advisory
    # Rejection is not leniency: the step is still not waived.
    assert next(s for s in report["steps"] if s["id"] == 5)["status"] != "WAIVED"


def test_incomplete_env_waiver_is_reported_with_what_is_missing(tmp_path):
    """An ENV_UNAVAILABLE waiver is only honoured when it is actionable and
    reviewable. When it is not, the report must say exactly which
    attestation fields are absent."""
    _write_waivers(tmp_path, [{
        "step": "formal",
        "verdict_tier": "ENV_UNAVAILABLE",
        "review_required": True,
        "evidence": [],
        "rationale": "env gap",
    }])
    _, report = _compliance(tmp_path, tmp_path / "r.json")

    advisory = " ".join(report["advisories"])
    assert "ticket" in advisory
    assert "evidence" in advisory
    assert "rationale" in advisory
    assert next(s for s in report["steps"] if s["id"] == 5)["status"] != "WAIVED"
