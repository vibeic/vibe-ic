"""CZT-19 — a STALLED LVS is a third state, and both arms booked it as FAIL.

THE DEFECT, in one sentence: when the progress watchdog stopped magic's
extraction, `_run_extraction_lvs` wrote `lvs_verdict.json` status "FAIL" — the
runner's word for "netgen compared these two circuits and they are not the
same" — for a run in which NOTHING was compared, because no netlist ever
reached netgen.  `lvs_verdict.json` is a contract seven other programs read.

WHY THE WORD IS `BLOCKED` AND NOT A NEW ONE.  `_aggregate_verdict` enumerates
its own vocabulary and lets ANY word it does not know fall through to a
catch-all green `return "PASS"` (vibe-ic#925).  `BLOCKED` is named there
explicitly, in the same bucket as FAIL — so the headline run verdict is
unchanged and only the step's own word, and the persisted contract, move.
`test_blocked_still_aggregates_to_fail` below is that control, and it is what
makes this a CORRECTION rather than a weakening.

BOTH DIRECTIONS, every claim:
  * a stopped extraction  -> BLOCKED / LVS_EXTRACTION_STALLED  (was FAIL)
  * a stopped compare     -> BLOCKED / LVS_COMPARE_STALLED     (was FAIL)
  * a real MISMATCH       -> still FAIL / LVS_MISMATCH         (control)
  * a real MATCH          -> still PASS / LVS_MATCH            (control)
  * netgen exiting on its OWN with no terminal token -> still INCOMPLETE,
    step FAIL (control: the split must not swallow the #477 diagnosis)

chip-AGNOSTIC: synthetic project + fake docker transcripts; no chip / vendor /
SKU literal is used as detection logic.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import phase3_one_shot_runner as runner  # noqa: E402


def _pdk():
    return runner.PdkConfig(
        name="sky130A", liberty="/foss/pdks/x.lib", tech_lef="/t.tlef",
        cell_lef="/c.lef", cell_gds=None, site="s", drc_deck=None)


def _proj(tmp_path):
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "chip_top.def").write_bytes(
        b"VERSION 5.8 ;\nDESIGN chip_top ;\nEND DESIGN\n")
    synth = tmp_path / "phase2" / "stage2" / "synth"
    synth.mkdir(parents=True)
    (synth / "chip_top_synth.v").write_text("module chip_top();\nendmodule\n")
    return tmp_path


#: What `_watchdog.run_supervised` really appends to `.err` on a stall kill.
#: Copied in the SHAPE the supervisor emits, so the evidence this test asserts
#: on is the evidence a real run carries.
STALL_ERR = (
    "\nWATCHDOG_STALLED: configured forward-progress signals did not advance "
    "for > 1800s — killed as hung, not slow. watched=output+log+cpu "
    "since_last_progress_s=1803.4 elapsed_s=5401.2\n")


def _fake_docker(*, stall_leg=None, netgen_transcript="", lvs_rpt_body=None,
                 spice_body=".subckt chip_top a b\n.ends\n",
                 ext2spice_log="MAGIC_EXT2SPICE_DONE\n"):
    """Docker stub.  `stall_leg` in {None, 'magic', 'netgen'} decides which leg
    comes back with the supervisor's stall return code and its `.err` note."""
    import re as _re

    def fake(container, cmd, timeout=0, **_):
        if cmd.startswith("command -v") or cmd.startswith("test -f"):
            return (0, "", "")
        if "magic" in cmd and "SPICE_OUT=" in cmd:
            m = _re.search(r"SPICE_OUT=(\S+)", cmd)
            out_p = Path(m.group(1))
            ext_dir = out_p.parent
            ext_dir.mkdir(parents=True, exist_ok=True)
            _fb = _re.search(r"FEEDBACK_OUT=(\S+)", cmd)
            if _fb:
                Path(_fb.group(1)).parent.mkdir(parents=True, exist_ok=True)
                Path(_fb.group(1)).write_text("")
            if stall_leg == "magic":
                # A killed extraction leaves a PARTIAL netlist behind — the
                # exact artefact #570 isolates.  Writing it is the point: a
                # stub that writes nothing cannot show the isolation happened.
                out_p.write_text(".subckt chip_top a\n")
                (ext_dir / "ext2spice.log").write_text(
                    "Magic 8.3\nextract all\n")
                return (runner._RC_STALLED, "", STALL_ERR)
            out_p.write_text(spice_body)
            (ext_dir / "ext2spice.log").write_text(ext2spice_log)
            return (0, ext2spice_log, "")
        if "netgen" in cmd:
            m = _re.search(r"(\S+/lvs\.rpt)", cmd)
            if m:
                rpt = Path(m.group(1))
                rpt.parent.mkdir(parents=True, exist_ok=True)
                body = (lvs_rpt_body if lvs_rpt_body is not None
                        else ("Netgen 1.5\n" + netgen_transcript))
                rpt.write_text(body)
            if stall_leg == "netgen":
                return (runner._RC_STALLED, "", STALL_ERR)
            return (0, netgen_transcript, "")
        return (0, "", "")
    return fake


def _run(tmp_path, monkeypatch, **kw):
    p = _proj(tmp_path)
    monkeypatch.setattr(runner, "_docker_exec", _fake_docker(**kw))
    monkeypatch.setattr(runner, "_to_container_path", lambda s, c: s)
    r = runner.step_lvs(p, "chip_top", _pdk(), "x")
    vpath = p / "reports" / "phase3" / "lvs_verdict.json"
    v = json.loads(vpath.read_text()) if vpath.is_file() else None
    return p, r, v


# ---------------------------------------------------------------------------
# THE DEFECT — arm A: the extraction was stopped
# ---------------------------------------------------------------------------
def test_stalled_extraction_is_blocked_not_a_mismatch(tmp_path, monkeypatch):
    p, r, v = _run(tmp_path, monkeypatch, stall_leg="magic")

    assert r.status == "BLOCKED", (r.status, r.detail)
    assert r.extras.get("finding") == "LVS_EXTRACTION_STALLED"
    assert r.extras.get("stopped_as") == "STALLED"

    # THE CONTRACT, which is the whole point of the finding.
    assert v is not None, "no lvs_verdict.json was written for a stopped run"
    assert v["status"] == "BLOCKED", v["status"]
    assert v["result"] == "BLOCKED", v["result"]
    assert v["finding"] == "LVS_EXTRACTION_STALLED"
    assert v["stopped_as"] == "STALLED"

    # THE LAST PROGRESS EVIDENCE.  A stop that cannot say what was watched, and
    # for how long the job showed none of it, is an assertion.
    sup = v.get("supervision") or {}
    assert sup.get("supervisor_outcome") == "STALLED", sup
    assert sup.get("watched") == "output+log+cpu", sup
    assert sup.get("since_last_progress_s") == 1803.4, sup
    assert sup.get("elapsed_s") == 5401.2, sup

    # The message must not assert a finding about the design.
    assert "NOT a mismatch" in r.detail
    assert "NOTHING is known" in r.detail

    # #570 — the partial netlist must not be left at the canonical path where
    # the next reader cannot tell it from a finished one.
    ext = p / "phase3" / "stage3" / "extracted"
    assert not (ext / "chip_top_extracted.sp").is_file(), \
        sorted(q.name for q in ext.iterdir())
    assert (ext / "chip_top_extracted.sp.timeout.partial").is_file(), \
        sorted(q.name for q in ext.iterdir())


# ---------------------------------------------------------------------------
# THE DEFECT — arm B: the compare was stopped
# ---------------------------------------------------------------------------
def test_stalled_compare_is_blocked_not_a_mismatch(tmp_path, monkeypatch):
    _p, r, v = _run(tmp_path, monkeypatch, stall_leg="netgen",
                    netgen_transcript="Netgen 1.5\nFlattening unmatched ",
                    lvs_rpt_body="Netgen 1.5\nFlattening unmatched ")
    assert r.status == "BLOCKED", (r.status, r.detail)
    assert r.extras.get("finding") == "LVS_COMPARE_STALLED"
    assert v["status"] == "BLOCKED"
    assert v["finding"] == "LVS_COMPARE_STALLED"
    assert v["stopped_as"] == "STALLED"
    assert (v.get("supervision") or {}).get("watched") == "output+log+cpu"
    assert "NOT a mismatch" in r.detail


# ---------------------------------------------------------------------------
# CONTROLS — the three verdicts that must NOT move
# ---------------------------------------------------------------------------
def test_real_mismatch_is_still_fail(tmp_path, monkeypatch):
    _p, r, v = _run(
        tmp_path, monkeypatch,
        netgen_transcript="Final result: Circuits do NOT match.\n")
    assert r.status == "FAIL", (r.status, r.detail)
    assert v["status"] == "FAIL", v
    assert v["finding"] == "LVS_MISMATCH", v


def test_real_match_is_still_pass(tmp_path, monkeypatch):
    _p, r, v = _run(
        tmp_path, monkeypatch,
        netgen_transcript="Final result: Circuits match uniquely.\n")
    assert r.status == "PASS", (r.status, r.detail)
    assert v["status"] == "PASS", v
    assert v["finding"] == "LVS_MATCH", v


def test_netgen_own_exit_without_terminal_token_is_still_incomplete(
        tmp_path, monkeypatch):
    """The #477 diagnosis must survive the split.

    A tool that exits ON ITS OWN and still prints no terminal token is a
    DIFFERENT fact from a tool the supervisor stopped: a truncated or malformed
    report from a run that believed it had finished.  Folding the two together
    would have been the easy version of this fix and would have destroyed a
    diagnosis #477 measured in the field.
    """
    _p, r, v = _run(tmp_path, monkeypatch,
                    netgen_transcript="Netgen 1.5\nFlattening unmatched ",
                    lvs_rpt_body="Netgen 1.5\nFlattening unmatched ")
    assert r.status == "FAIL", (r.status, r.detail)
    assert r.extras.get("finding") == "LVS_NO_TERMINAL_VERDICT"
    assert v["status"] == "INCOMPLETE", v
    assert v["finding"] == "LVS_NO_TERMINAL_VERDICT", v
    assert "stopped_as" not in v, v


# ---------------------------------------------------------------------------
# NOT A WEAKENING — the control that licenses the word change
# ---------------------------------------------------------------------------
def test_blocked_still_aggregates_to_fail():
    """BLOCKED and FAIL are the same run-level verdict, so nothing green can be
    manufactured by moving the step's own word.  If this ever stops holding,
    the word change above becomes a weakening and this test says so."""
    def _sr(status):
        return runner.StepResult("lvs", status, 0.0, "d", extras={})
    assert runner._aggregate_verdict([_sr("BLOCKED")]) == "FAIL"
    assert runner._aggregate_verdict([_sr("FAIL")]) == "FAIL"
    assert runner._aggregate_verdict([_sr("PASS")]) == "PASS"
    # And the catch-all that makes an INVENTED word dangerous — asserted, so
    # the reason a new status word was NOT introduced is measured, not stated.
    assert runner._aggregate_verdict([_sr("STALLED")]) == "PASS"


# ---------------------------------------------------------------------------
# The supervision-evidence parser, both directions
# ---------------------------------------------------------------------------
def test_supervision_evidence_reads_the_note():
    ev = runner._supervision_evidence("some tool noise" + STALL_ERR)
    assert ev == {"supervisor_outcome": "STALLED",
                  "watched": "output+log+cpu",
                  "since_last_progress_s": 1803.4,
                  "elapsed_s": 5401.2}, ev


def test_supervision_evidence_is_empty_when_there_is_no_note():
    """AN ABSENT NOTE AND A NOTE SAYING NOTHING WAS WATCHED ARE DIFFERENT FACTS.
    Returning a default here would let a reader believe a supervisor spoke."""
    assert runner._supervision_evidence("") == {}
    assert runner._supervision_evidence("netgen: ordinary stderr\n") == {}


def test_supervision_evidence_records_a_meter_wired_to_nothing():
    """`watched=NOTHING` is a real reading the supervisor can emit, and it must
    reach the record — a job supervised on no signal is a stall BY
    CONSTRUCTION, which is a property of the wiring, not of the design."""
    ev = runner._supervision_evidence(
        "\nWATCHDOG_STALLED: ... watched=NOTHING "
        "since_last_progress_s=1801.0 elapsed_s=1801.0\n")
    assert ev["watched"] == "NOTHING", ev
    assert ev["supervisor_outcome"] == "STALLED"
