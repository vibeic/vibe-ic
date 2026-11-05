"""llv1 W19: rows imported from LibreLane's own step records are WITNESSED runs.

Owner decision 4a (2026-09-28): a row imported from LibreLane's step log counts
as a witnessed run attributed to LibreLane, citing its source log by path and
sha256. Rule #365 stays: a runner back-fill is still `reconstructed: true`.

On main, `provenance_check` has no notion of a witness, so a row can claim one
and cite anything and bind its artefact exactly as a real run does. The review
of the first cut (review_W0_W15_W19.json, branch W19) showed that "the flow
printed Running" is no witness either: LibreLane prints it before a step skips
or fails. These tests hold what a witness must show: the step ran a tool
subprocess, did not skip, finished (state_out.json), and wrote the declared
bytes; and the run's own log is pinned by prefix, so appends do not break it.

The flow logs are the real calibration samples: the CMP3 LibreLane flow.log
reduced to its step/subprocess/skip lines, whole and cut before step 44.
"""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
_PLUGIN = PROGRAMS.parent
for _p in (str(PROGRAMS), str(_PLUGIN)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

CHECK = PROGRAMS / "provenance_check.py"
CAL = PROGRAMS / "calibration"
WHOLE = CAL / "librelane_flow_log_complete_negative.log"
ABORTED = CAL / "librelane_flow_log_aborted_positive.log"

RUN = "phase3/librelane/runs/seg2"
STEP = "44-openroad-detailedrouting"
STEP_ID = "OpenROAD.DetailedRouting"
LOG = f"{STEP}/openroad-detailedrouting.log"
SRC = f"{STEP}/top.def"
OUT = "phase3/stage3/pnr/routed.def"
DEF = "VERSION 5.8 ;\nDESIGN top ;\nEND DESIGN\n"


def _step(run: Path, rel: str, *, log: str = None, state: bool = True):
    d = run / rel
    d.mkdir(parents=True, exist_ok=True)
    (d / "runtime.txt").write_text("00:00:01.000\n")
    (d / "config.json").write_text("{}\n")
    if log:
        (d / log).write_text("[INFO] tool transcript\n")
    if state:
        (d / "state_out.json").write_text('{"def": "top.def"}\n')
    return d


def _project(tmp_path: Path, flow_log: Path = WHOLE) -> Path:
    proj = tmp_path / "proj"
    run = proj / RUN
    run.mkdir(parents=True)
    shutil.copyfile(flow_log, run / "flow.log")
    _step(run, STEP, log="openroad-detailedrouting.log")
    (run / SRC).write_text(DEF)
    (proj / OUT).parent.mkdir(parents=True)
    shutil.copyfile(run / SRC, proj / OUT)
    return proj


def _row(proj: Path, **kw):
    import _tool_log_provenance as T
    args = dict(flow="librelane", step_id=STEP_ID, run_dir=proj / RUN,
                step_dir=STEP, outputs={OUT: proj / RUN / SRC},
                timestamp="2026-09-28T00:00:00Z")
    args.update(kw)
    return T.witnessed_row(proj, **args)


def _ledger(proj: Path, *rows) -> None:
    (proj / "provenance.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows))


def _check(proj: Path, out: str = OUT, tool: str = "openroad"):
    return subprocess.run(
        [sys.executable, str(CHECK), str(proj), "--output", out,
         "--tool", tool], capture_output=True, text=True, timeout=120)


def _refused(proj: Path, row, why: str, **kw):
    _ledger(proj, row)
    r = _check(proj, **kw)
    assert r.returncode == 1, r.stdout
    assert "claims a witness that does not hold" in r.stdout, r.stdout
    assert why in r.stdout, r.stdout


# ── the witnessed row ────────────────────────────────────────────────────

def test_a_witnessed_row_cites_the_step_evidence_run_dir_relative(tmp_path):
    import _tool_log_provenance as T
    proj = _project(tmp_path)
    row = _row(proj)
    assert row["reconstructed"] is False and row["exit_code"] == 0
    assert row["attributed_to"] == "librelane"
    assert row["tool"] == "openroad"          # the allow-lists judge it as is
    w = row["witness"]
    run = proj / RUN
    assert w["run_dir"] == RUN and w["step_dir"] == STEP
    assert w["flow_log"] == {"path": "flow.log",
                             "bytes": (run / "flow.log").stat().st_size,
                             "sha256": T._sha256(run / "flow.log")}
    assert w["completion"] == {"path": f"{STEP}/state_out.json",
                               "sha256": T._sha256(run / STEP / "state_out.json")}
    # the one transcript the flow's own log names for this step
    assert w["logs"] == [{"path": LOG, "sha256": T._sha256(run / LOG)}]
    assert w["sources"] == {OUT: {"path": SRC, "sha256": T._sha256(run / SRC)}}
    assert row["outputs"] == {OUT: T._sha256(proj / OUT)}
    assert T.is_witnessed(row, proj)
    _ledger(proj, row)
    r = _check(proj)
    assert r.returncode == 0, r.stdout + r.stderr


def test_the_attributed_tool_comes_from_the_step_not_the_caller():
    import _tool_log_provenance as T
    assert T.underlying_tool("OpenROAD.STAMidPNR-3") == "openroad"
    assert T.underlying_tool("Odb.ReportWireLength") == "openroad"
    assert T.underlying_tool("Magic.StreamOut") == "magic"
    assert T.underlying_tool("KLayout.DRC") == "klayout"
    assert T.underlying_tool("Netgen.LVS") == "netgen"
    assert T.underlying_tool("Yosys.Synthesis") == "yosys"
    assert T.underlying_tool("Checker.TrDRC") is None
    assert T.underlying_tool("Misc.ReportManufacturability") is None


def test_an_appended_flow_log_keeps_the_witness(tmp_path):
    """flow.log is append-only and a run tag can be reused: the row pins the
    prefix it was written against, so a later invocation leaves it valid."""
    proj = _project(tmp_path)
    _ledger(proj, _row(proj))
    with (proj / RUN / "flow.log").open("a") as fh:
        fh.write("Running 'OpenROAD.CheckSDCFiles' at 'runs/seg2/99-x'…\n")
    assert _check(proj).returncode == 0
    # but a rewritten prefix does not
    log = proj / RUN / "flow.log"
    log.write_text(log.read_text().replace("Verilator.Lint", "Verilator.Lynt"))
    r = _check(proj)
    assert r.returncode == 1 and "no longer begins with the bytes" in r.stdout


# ── the review's reproductions: none of these is a tool run ───────────────

def test_a_step_the_flow_skipped_is_not_witnessed(tmp_path):
    """IOPlacement: `Running` printed, then `Skipping 'OpenROAD.IOPlacement'`.
    Its folder has state_out.json and runtime.txt and no transcript."""
    import _tool_log_provenance as T
    proj = _project(tmp_path)
    run = proj / RUN
    _step(run, "25-openroad-ioplacement")
    (run / "25-openroad-ioplacement/top.def").write_text(DEF)
    with pytest.raises(T.WitnessRefused, match="skipped"):
        _row(proj, step_id="OpenROAD.IOPlacement",
             step_dir="25-openroad-ioplacement",
             outputs={OUT: run / "25-openroad-ioplacement/top.def"})
    forged = _row(proj)
    w = forged["witness"]
    forged["step"] = w["step_id"] = "OpenROAD.IOPlacement"
    w["step_dir"] = "25-openroad-ioplacement"
    w["completion"] = {"path": "25-openroad-ioplacement/state_out.json",
                       "sha256": T._sha256(run / "25-openroad-ioplacement/state_out.json")}
    w["logs"] = [{"path": "25-openroad-ioplacement/runtime.txt",
                  "sha256": T._sha256(run / "25-openroad-ioplacement/runtime.txt")}]
    w["sources"] = {OUT: {"path": "25-openroad-ioplacement/top.def",
                          "sha256": T._sha256(run / "25-openroad-ioplacement/top.def")}}
    _refused(proj, forged, "skipped")


def test_a_pure_python_step_is_not_witnessed(tmp_path):
    """OpenROAD.CheckSDCFiles runs no subprocess: its block names no
    transcript, whatever its step-id prefix says."""
    import _tool_log_provenance as T
    proj = _project(tmp_path)
    run = proj / RUN
    _step(run, "10-openroad-checksdcfiles")
    (run / "10-openroad-checksdcfiles/top.def").write_text(DEF)
    with pytest.raises(T.WitnessRefused, match="no tool ran"):
        _row(proj, step_id="OpenROAD.CheckSDCFiles",
             step_dir="10-openroad-checksdcfiles",
             outputs={OUT: run / "10-openroad-checksdcfiles/top.def"})


def test_a_step_that_did_not_finish_is_not_witnessed(tmp_path):
    """No state_out.json: LibreLane writes it only after run() returns."""
    import _tool_log_provenance as T
    proj = _project(tmp_path)
    row = _row(proj)
    (proj / RUN / STEP / "state_out.json").unlink()
    with pytest.raises(T.WitnessRefused, match="did not finish"):
        _row(proj)
    _refused(proj, row, "completion record")


def test_a_canonical_file_the_step_did_not_write_is_not_witnessed(tmp_path):
    """The canonical DEF was edited: it is not the bytes in the step folder."""
    import _tool_log_provenance as T
    proj = _project(tmp_path)
    row = _row(proj)
    (proj / OUT).write_text(DEF + "# hand edit\n")
    with pytest.raises(T.WitnessRefused, match="is not the bytes"):
        _row(proj)
    row["outputs"][OUT] = T._sha256(proj / OUT)     # re-declare the edit
    _refused(proj, row, "declared with bytes other than its source")


def test_a_step_the_flow_never_started_is_not_witnessed(tmp_path):
    import _tool_log_provenance as T
    proj = _project(tmp_path)
    row = _row(proj)
    shutil.copyfile(ABORTED, proj / RUN / "flow.log")
    row["witness"]["flow_log"].update(
        bytes=(proj / RUN / "flow.log").stat().st_size,
        sha256=T._sha256(proj / RUN / "flow.log"))
    ok, why = T.verify_witness(row, proj)
    assert ok is False and "never started" in why
    _refused(proj, row, "never started")


def test_a_rewritten_step_log_unbinds_the_row(tmp_path):
    proj = _project(tmp_path)
    row = _row(proj)
    (proj / RUN / LOG).write_text("edited\n")
    _refused(proj, row, "no longer has the sha256")


# ── the verifier-side guards, each at ledger level ────────────────────────

def test_the_cited_flow_log_must_be_the_run_directorys(tmp_path):
    proj = _project(tmp_path)
    row = _row(proj)
    shutil.copyfile(proj / RUN / "flow.log", proj / RUN / "alt.log")
    row["witness"]["flow_log"]["path"] = "alt.log"
    _refused(proj, row, "not the run directory's flow.log")


def test_a_cited_log_must_be_inside_the_step_folder(tmp_path):
    import _tool_log_provenance as T
    proj = _project(tmp_path)
    run = proj / RUN
    _step(run, "43-openroad-stamidpnr-3", log="openroad-stamidpnr-3.log")
    row = _row(proj)
    row["witness"]["logs"] = [{
        "path": "43-openroad-stamidpnr-3/openroad-stamidpnr-3.log",
        "sha256": T._sha256(run / "43-openroad-stamidpnr-3/openroad-stamidpnr-3.log")}]
    _refused(proj, row, "is not inside the step directory")


def test_a_cited_log_must_be_a_transcript_the_flow_names(tmp_path):
    import _tool_log_provenance as T
    proj = _project(tmp_path)
    row = _row(proj)
    row["witness"]["logs"] = [{"path": f"{STEP}/runtime.txt", "sha256":
                               T._sha256(proj / RUN / STEP / "runtime.txt")}]
    _refused(proj, row, "not a transcript the flow's own log names")


@pytest.mark.parametrize("edit,why", [
    (lambda r: r["witness"].update(kind="note"), "unknown witness kind"),
    (lambda r: r.update(attributed_to="orfs"), "not a supported matching pair"),
    (lambda r: r["witness"].update(logs=[]), "cites no tool log"),
    (lambda r: r.update(reconstructed=True), "#365"),
    (lambda r: r.pop("witness"), "cites no witness"),
    (lambda r: r.update(tool="klayout"), "is not the tool step"),
    (lambda r: r["witness"].update(sources={}), "a source for every output"),
    (lambda r: r["witness"]["flow_log"].update(bytes=0), "pins no byte length"),
])
def test_each_verifier_guard_refuses_at_ledger_level(tmp_path, edit, why):
    proj = _project(tmp_path)
    row = _row(proj)
    edit(row)
    _refused(proj, row, why, tool="klayout,openroad")


def test_a_symlinked_log_is_not_evidence(tmp_path):
    import _tool_log_provenance as T
    proj = _project(tmp_path)
    row = _row(proj)
    log = proj / RUN / LOG
    real = tmp_path / "elsewhere.log"
    shutil.move(log, real)
    log.symlink_to(real)
    with pytest.raises(T.WitnessRefused):
        _row(proj)
    _refused(proj, row, "symlink")


# ── witnessed_row refuses what it cannot support ─────────────────────────

@pytest.mark.parametrize("kw,match", [
    (dict(step_id="Checker.TrDRC"), "runs no tool"),
    (dict(flow="orfs"), "no witness rule"),
    (dict(step_id="OpenROAD.GlobalRouting"), "never started"),
    (dict(outputs={}), "at least one output"),
])
def test_witnessed_row_refuses_unsupported_claims(tmp_path, kw, match):
    import _tool_log_provenance as T
    proj = _project(tmp_path)
    with pytest.raises(T.WitnessRefused, match=match):
        _row(proj, **kw)


def test_an_output_source_outside_the_step_folder_is_refused(tmp_path):
    import _tool_log_provenance as T
    proj = _project(tmp_path)
    other = proj / RUN / "top.def"
    other.write_text(DEF)
    with pytest.raises(T.WitnessRefused, match="not inside the step"):
        _row(proj, outputs={OUT: other})


def test_a_run_without_its_flow_log_has_no_witness(tmp_path):
    import _tool_log_provenance as T
    proj = _project(tmp_path)
    (proj / RUN / "flow.log").unlink()
    with pytest.raises(T.WitnessRefused, match="nothing names the step"):
        _row(proj)


# ── an uncalibrated reader is NOT_MEASURED, never a FAIL ──────────────────







def _main(proj: Path, tmp_path: Path, *extra):
    """provenance_check in-process, so the monkeypatched calibration holds."""
    import provenance_check as PC
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = PC.main([str(proj), "--output", OUT, "--tool", "openroad",
                      "--json", str(tmp_path / "r.json"), *extra])
    return rc, out.getvalue(), json.loads((tmp_path / "r.json").read_text())


def _no_state_out(proj: Path) -> None:
    (proj / RUN / STEP / "state_out.json").unlink()


def _rewritten_log(proj: Path) -> None:
    (proj / RUN / LOG).write_text("edited\n")


def _redeclared_edit(proj: Path, row) -> None:
    import _tool_log_provenance as T
    (proj / OUT).write_text(DEF + "# hand edit\n")
    row["outputs"][OUT] = T._sha256(proj / OUT)










# ── rule #365 is untouched ────────────────────────────────────────────────

def test_a_runner_back_fill_is_still_reconstructed_and_never_witnessed(
        tmp_path):
    import _tool_log_provenance as T
    import phase3_one_shot_runner as R
    proj = _project(tmp_path)
    (proj / "provenance.jsonl").write_text("")
    R._restamp_provenance_output(proj, OUT, proj / OUT, "openroad", "import")
    rows = [json.loads(l) for l in
            (proj / "provenance.jsonl").read_text().splitlines() if l.strip()]
    assert len(rows) == 1
    assert rows[0]["reconstructed"] is True
    assert rows[0]["duration_ms"] is None
    assert not T.claims_witness(rows[0])
    assert T.verify_witness(rows[0], proj) == (None, "")
    assert not T.is_witnessed(rows[0], proj)
    assert _check(proj).returncode == 0


# ── the readers ───────────────────────────────────────────────────────────



def test_the_flow_log_lists_instance_ids_in_run_order():
    import _tool_log_provenance as T
    steps = T.flow_log_steps(WHOLE.read_text())
    ids = [s for s, _ in steps]
    assert ids[0] == "Verilator.Lint"
    assert "OpenROAD.STAMidPNR-3" in ids               # instance, not class, id
    assert ("OpenROAD.CheckAntennas",
            ("runs", "cmp3", "42-openroad-repairantennas",
             "2-openroad-checkantennas")) in steps     # nested sub-step
    assert ids.index("OpenROAD.GlobalRouting") < ids.index(STEP_ID)


def test_a_step_block_reads_skips_and_transcripts():
    import _tool_log_provenance as T
    text = WHOLE.read_text()
    sta = T.step_block(text, "OpenROAD.STAPrePNR", "12-openroad-staprepnr")
    # `Skipping corner ...` is not a step skip; each corner's transcript is
    # logged (the members, compared both ways, not their count)
    assert sta["skipped"] is False
    want = {("runs", "cmp3", "12-openroad-staprepnr", c, "sta.log")
            for c in ("nom_tt_025C_5v00", "nom_ss_125C_4v50",
                      "nom_ff_n40C_5v50")}
    got = set(sta["subprocess_logs"])
    assert got == want, (sorted(got - want), sorted(want - got))
    skip_io = T.step_block(text, "OpenROAD.GlobalPlacementSkipIO",
                           "24-openroad-globalplacementskipio")
    assert skip_io["skipped"] is True            # "Returning state unaltered"
    rep = T.step_block(text, "OpenROAD.RepairAntennas",
                       "42-openroad-repairantennas")
    assert rep is not None                       # nested sub-steps stay inside
    assert T.step_block(text, STEP_ID, "43-openroad-stamidpnr-3") is None
