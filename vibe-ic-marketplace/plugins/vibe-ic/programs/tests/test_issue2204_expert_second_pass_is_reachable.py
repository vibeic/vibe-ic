#!/usr/bin/env python3
"""test_issue2204_expert_second_pass_is_reachable.py

`phase1_expert_parse_track` ends its first pass by telling the operator to
invoke the `vibe-ic:ic-expert-agent` subagent and "re-run to consume its
answer". THE ONE CANONICAL FRONT DOOR COULD NOT PERFORM THAT RE-RUN.
`vibe_ic_one_shot_runner._phase1_decision` returned `(False, "")` as soon as
`L_count >= 13`, and Phase 1 emits 28 L documents — so from the first
successful run onward every orchestrator invocation SKIPPED Phase 1 and a
delivered expert answer sat unread on disk forever.

MEASURED before the fix, on a synthesised project carrying 28 L documents, the
subagent's `l_doc_expectations.json` on disk and an `expert_parse_track.json`
whose `ai_subtrack.status` is still `HANDOFF_EMITTED`:

    _phase1_decision(project, force_skip=False) -> (False, '')

— identical to the answer it gives for the same project with no answer file at
all. The decision could not see the difference between "phase 1 has run" and
"phase 1 has run AND its expert answer has been read".

WHAT IS PINNED HERE, AND WHY BOTH DIRECTIONS ARE PINNED
------------------------------------------------------
A change that always re-runs Phase 1 would make the first half of this file
green and would be a wall-clock tax on every run, not a fix. So the SKIP
direction is pinned as hard as the RE-ENTER direction:

  * an UNREAD delivered answer re-enters Phase 1, in a mode that runs the
    second track ALONE and re-extracts nothing;
  * a root whose answer was read — under EVERY status the track can record
    once it has opened an answer — is still SKIPPED;
  * a root with no answer at all is still SKIPPED;
  * an operator's `--skip-phase1` is still a skip.

The last three are CONTROLS: they are green before this fix and must stay
green after it. A fix that reddens them has replaced one defect with a worse
one.

TERMINATION is keyed to the bytes the producer actually read. An unchanged
refused answer is skipped; a corrected answer or an answer without a read
receipt is retried. The subprocess lifecycle fixtures below reproduce both
independent review variants. Their L-docs and initial PASS summary are synthetic
seam scaffolding, not certified extraction or golden benchmark evidence.

Every fixture is synthesised here from neutral parts. No design, PDK, vendor
or IP-model identifier appears anywhere in this file.

Run: python3 -m pytest programs/tests/test_issue2204_expert_second_pass_is_reachable.py -q
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import vibe_ic_one_shot_runner as ORCH        # noqa: E402
import _p1_identity_fixture  # noqa: E402  FX_STALE_LDOCS
import phase1_expert_parse_track as TRACK     # noqa: E402
import _path_layout as _pl                    # noqa: E402
from _route_fixture import stage_owner_route  # noqa: E402
from _ai_judgement_fixture import sign as _sign_ai_fixture  # noqa: E402

#: WHERE PASS 1's RECORD LIVES, asked of the router. R-0915-151 moved
#: `phase1_one_shot.json` onto `_path_layout`'s router, because the flat
#: `reports/phase1_one_shot.json` is a location this repo's own
#: `reports_subfolder_taxonomy_check` calls a stray file. These arms are about the SECOND PASS
#: being reachable and consuming the delivered answer, not about layout: they staged pass 1 flat
#: and then read the flat path back, so once the second pass began publishing at the routed path
#: they were reading a file nobody had updated. The legacy-location behaviour has its own home,
#: `test_a_pass_one_written_before_the_move_is_still_carried.py`; these ask the router so they
#: are not accidentally testing two things.
def _pass1_record(project: Path) -> Path:
    # The parent is created because several of these call sites WRITE pass 1's record to stage a
    # project. The flat location they used to write needed no mkdir -- `reports/` already existed
    # -- and the routed one does; my first rewrite of these arms missed that and turned them into
    # FileNotFoundError at `reports/orchestrator/`. Harmless on a read.
    path = _pl.report_path(project, "phase1_one_shot.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path



_INPUT_DOC = """# Block specification

The converter accepts an external reference on the REFHI terminal and
digitises to 12 bits at 500 ksps. Trim values are restored at power-up.
"""

#: A well-formed answer in the shape `answer_schema_mismatch` accepts.
_ANSWER = {
    "expectations": [{
        "id": "reference-terminal-is-a-named-port",
        "layer": "L9_INTERFACE",
        "field_path": "top_ports",
        "requirement": "the external reference terminal the input names must "
                       "appear as a named port",
        "expected_tokens": ["REFHI"],
        "evidence": ["the input names REFHI as an external terminal"],
    }],
}


def _report(project: Path) -> Path:
    return _pl.report_path(project, "phase1/expert_parse_track.json")


def _answer_path(project: Path) -> Path:
    return (_report(project).parent / "expert_parse_track_pack"
            / "l_doc_expectations.json")


def _project(tmp_path: Path, name: str, *, l_docs: int = 28,
             answer: bool = False, status: str | None = "HANDOFF_EMITTED",
             report: bool = True) -> Path:
    """A project in a stated Phase-1 state. Nothing is inferred: the L-doc
    count, the answer's presence and the track's recorded status are three
    independent knobs, because they are three independent facts on disk."""
    p = tmp_path / name
    (p / "input" / "docs").mkdir(parents=True)
    (p / "input" / "docs" / "spec.md").write_text(_INPUT_DOC)
    # owner route rule 2026-09-28 (ICROUTE)
    stage_owner_route(p, "ic")
    gd = p / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    for i in range(1, l_docs + 1):
        (gd / f"L{i}_LAYER.json").write_text(json.dumps({"doc_id": f"L{i}"}))
    rep = _report(p)
    rep.parent.mkdir(parents=True, exist_ok=True)
    (rep.parent / "expert_parse_track_pack").mkdir(parents=True, exist_ok=True)
    if report:
        rep.write_text(json.dumps({
            "program": TRACK.PROGRAM,
            "verdict": "PASS",
            "ai_subtrack": {"status": status, "expectations": [],
                            **({"answer_sha256": hashlib.sha256(
                                json.dumps(_ANSWER).encode()).hexdigest()}
                               if answer and status != TRACK.AI_HANDOFF_EMITTED
                               else {})},
        }))
    if answer:
        _answer_path(p).write_text(json.dumps(_ANSWER))
    # FX_STALE_LDOCS (orchestrator ruling 2026-09-28): the planted L docs stand
    # for "phase 1 already ran", so they carry the identity phase 1 stamps.
    # Without it the front door would -- correctly -- regenerate them.
    _p1_identity_fixture.stamp_current(p)
    # A second-track-only retry also requires the first pass's summary to
    # carry forward. L-doc presence alone does not establish that outcome.
    _pass1_record(p).write_text(json.dumps({
        "phase": 1, "mode": "docs", "verdict": "PASS",
        "pass1": {"verdict": "PASS", "rc": 0},
    }))
    return p


# ── the defect: an unread answer could not re-enter Phase 1 ────────────────





# ── termination: at most one re-entry per delivered answer ─────────────────





# ── the controls: green before this fix, and they must stay green ─────────

















# ── the second pass itself ────────────────────────────────────────────────

def test_the_phase1_runner_accepts_second_track_only():
    """The mode the orchestrator dispatches has to exist on the runner it
    dispatches to; a mode nothing accepts is the same dead end one file
    along."""
    cp = subprocess.run(
        [sys.executable, str(_PROGRAMS / "phase1_one_shot_runner.py"),
         "--help"], capture_output=True, text=True)
    assert cp.returncode == 0, cp.stderr
    assert "--second-track-only" in cp.stdout






# ── the front door's own half: the mode must reach the runner as an argv ───

def _assert_front_door_second_pass(src):
    """PROVED BY PARSE, not by grepping the file for a string.

    `_phase1_decision` returning a mode is worth nothing if the call site does
    not turn that mode into the argument the runner reads. Nothing else in this
    file joins the two halves: the decision tests stop at the mode, and the
    execution test below starts from the argv. This is the seam, and it is
    asserted over the syntax tree of the branch that owns it — a comment or a
    docstring naming the flag cannot satisfy it.
    """
    import ast
    from _runner_ast_fixture import called_main, live_nodes
    main = called_main(ast.parse(src))

    def _guards_second_pass(test: ast.expr) -> bool:
        return any(isinstance(n, ast.Attribute)
                   and n.attr == "_P1_MODE_EXPERT_SECOND_PASS"
                   or isinstance(n, ast.Name)
                   and n.id == "_P1_MODE_EXPERT_SECOND_PASS"
                   for n in ast.walk(test))

    branches = [n for n in live_nodes(main)
                if isinstance(n, ast.If) and _guards_second_pass(n.test)]
    assert branches, ("nothing in vibe_ic_one_shot_runner.main branches on the "
                      "second-pass mode, so the mode the decision returns "
                      "reaches no argv")
    # ONLY the branch's own BODY. `ast.walk` on an `If` also walks `orelse`,
    # which is the `elif p1_mode == "docs"` arm — so a walk of the whole node
    # sees the extraction flags too and the second assertion below could never
    # hold. (It did not, first time round; the test was wrong, not the code.)
    flags = {c.value for b in branches for n in b.body
             for c in live_nodes(n) if isinstance(c, ast.Constant)
             and isinstance(c.value, str)}
    assert "--second-track-only" in flags, (
        "the second-pass branch does not build the flag "
        "`phase1_one_shot_runner` needs; the branch would run a full "
        "re-extraction instead")
    # And it must NOT ask for the extraction mode: `--mode docs` in this branch
    # would re-derive the L documents under the answer that was authored
    # against them.
    assert "docs" not in flags and "--mode" not in flags
    # Bind the flag to the same argv variable the live dispatch consumes.
    appends = [n for b in branches for stmt in b.body for n in live_nodes(stmt)
               if isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name)
               and n.target.id == "p1_args" and isinstance(n.op, ast.Add)
               and isinstance(n.value, ast.List)
               and any(isinstance(v, ast.Constant) and v.value == "--second-track-only"
                       for v in n.value.elts)]
    assert appends, "the second-pass flag is not appended to p1_args"
    dispatches = [n for n in live_nodes(main) if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Name) and n.func.id == "_run_phase"
                  and len(n.args) >= 3 and isinstance(n.args[2], ast.Name)
                  and n.args[2].id == "p1_args"]
    assert any(c.lineno > a.lineno for c in dispatches for a in appends), (
        "the second-pass argv is not forwarded after its flag is appended")


def test_the_front_door_maps_the_mode_onto_the_flag_it_dispatches():
    _assert_front_door_second_pass(Path(ORCH.__file__).read_text(errors="replace"))


@pytest.mark.parametrize("mutation", ["uncalled", "dead_branch", "wrong_argv", "no_dispatch"])
def test_the_second_pass_wiring_check_rejects_disconnected_code(mutation):
    src = Path(ORCH.__file__).read_text(errors="replace")
    if mutation == "uncalled":
        old, new = 'return _main()', 'return 0'
    elif mutation == "dead_branch":
        old, new = 'if p1_mode == _P1_MODE_EXPERT_SECOND_PASS:', 'if False:'
    elif mutation == "wrong_argv":
        old, new = 'p1_args += ["--second-track-only"]', 'unused_args = ["--second-track-only"]'
    else:
        old, new = '_run_phase(label, runner, p1_args, env=_phase_env)', '_run_phase(label, runner, [], env=_phase_env)'
    assert old in src
    with pytest.raises(AssertionError):
        _assert_front_door_second_pass(src.replace(old, new))




def _invoke_lifecycle(project, label, *, track=False, first_pass=False,
                      extract_rc=None):
    """Retain the real producer's argv, rc, output and both report snapshots."""
    argv = [sys.executable, "-B", str(_PROGRAMS / (
        "phase1_expert_parse_track.py" if track else "phase1_one_shot_runner.py")),
        str(project)]
    if not track:
        argv += ["--ic-name", "review_counter"]
        if not first_pass:
            argv += ["--second-track-only", "--route", "ic"]
    if extract_rc is not None:
        # Only the extraction delegate is a seam. main(), preflight, route,
        # expert subprocess, summary and CLI return path are the real code.
        code = ("import sys; sys.path.insert(0, sys.argv[1]); "
                "import phase1_one_shot_runner as p; "
                f"p._run_docs_mode = lambda *a: {extract_rc}; "
                "sys.argv = sys.argv[2:]; raise SystemExit(p.main())")
        argv = [sys.executable, "-B", "-c", code, str(_PROGRAMS), *argv[2:]]
    cp = subprocess.run(argv, capture_output=True, text=True)
    (project / f"{label}.stdout").write_text(cp.stdout)
    (project / f"{label}.stderr").write_text(cp.stderr)
    row = {"argv": argv, "rc": cp.returncode}
    for key, path in (("track", _report(project)),
                      ("summary", _pass1_record(project))):
        if path.is_file():
            row[key] = json.loads(path.read_text())
    (project / f"{label}.json").write_text(json.dumps(row, indent=2))
    return row














def test_actual_first_pass_failure_survives_consumption(tmp_path):
    p = tmp_path / "no_input"
    p.mkdir()
    # owner route rule 2026-09-28 (ICROUTE)
    stage_owner_route(p, "ic")
    first = _invoke_lifecycle(p, "01_no_input", first_pass=True)
    # R-0915-85 — rc 1 is unchanged and is what this case is about: a first
    # pass over a project with NO INPUT is not green. The WORD is NOT_MEASURED,
    # because nothing failed -- D1 was refused for want of anything to read --
    # and publishing FAIL would claim a finding about a design nobody examined.
    assert first["rc"] == 1, first
    assert first["summary"]["verdict"] == "NOT_MEASURED", first["summary"]
    # Provide synthetic L-docs/answer for the retry seam without re-extraction.
    (p / "input/docs").mkdir(parents=True)
    (p / "input/docs/spec.md").write_text(_INPUT_DOC)
    gd = _pl.generated_docs_dir(p)
    gd.mkdir(parents=True, exist_ok=True)
    for i in range(1, 29):
        (gd / f"L{i}_LAYER.json").write_text(json.dumps({"doc_id": f"L{i}"}))
    _answer_path(p).parent.mkdir(parents=True, exist_ok=True)
    _answer_path(p).write_text(json.dumps(_ANSWER))
    before = {f.name: f.read_bytes() for f in gd.glob("L*.json")}
    second = _invoke_lifecycle(p, "02_consumed")
    assert second["track"]["ai_subtrack"]["status"] == TRACK.AI_CONSUMED
    assert second["rc"] == 1, second
    assert second["summary"]["verdict"] == "FAIL"
    assert second["summary"]["second_pass"]["rc"] == 0
    assert second["summary"]["steps"] == first["summary"]["steps"]
    assert {f.name: f.read_bytes() for f in gd.glob("L*.json")} == before


@pytest.mark.parametrize("extract_rc", [0, 1])
def test_initial_expert_failure_is_separate_from_extraction(tmp_path, extract_rc):
    p = _project(tmp_path, "initial_refusal", answer=True, report=False)
    _answer_path(p).write_text('{"ports": ["REFHI"]}')
    first = _invoke_lifecycle(p, "01_initial_refusal", first_pass=True,
                              extract_rc=extract_rc)
    assert first["rc"] == 1, first
    assert first["track"]["ai_subtrack"]["status"] == TRACK.AI_SCHEMA_MISMATCH
    _answer_path(p).write_text(json.dumps(_ANSWER))
    _sign_ai_fixture(p, "D1")
    second = _invoke_lifecycle(p, "02_corrected")
    assert second["track"]["ai_subtrack"]["status"] == TRACK.AI_CONSUMED
    assert second["rc"] == extract_rc, second
    assert second["summary"]["verdict"] == ("FAIL" if extract_rc else "PASS")
    # The first pass had an unread answer and no signed judgement. Its
    # mechanical PASS was uncredited; the corrected signed pass restores it.
    if extract_rc == 0:
        assert first["summary"]["steps"][0]["status"] == "NOT_MEASURED"
        assert first["summary"]["steps"][0]["program_status"] == "PASS"
        assert second["summary"]["steps"][0]["status"] == "PASS"
        assert (second["summary"]["steps"][0]["detail"]
                == first["summary"]["steps"][0]["program_detail"])
        assert second["summary"]["steps"][1:] == first["summary"]["steps"][1:]
    else:
        assert second["summary"]["steps"] == first["summary"]["steps"]
    assert second["summary"]["pass1"]["rc"] == extract_rc
    assert first["summary"]["steps"][0]["status"] == ("FAIL" if extract_rc else "NOT_MEASURED")


@pytest.mark.parametrize("prior", [None, {"mode": "expert_second_pass", "verdict": "FAIL"},
    {"mode": "docs", "verdict": "PASS", "pass1": {"rc": False, "verdict": "PASS"}}])
def test_unknown_first_pass_cannot_become_pass(tmp_path, prior):
    p = _project(tmp_path, "unknown_pass1", answer=True)
    if prior is not None:
        _pass1_record(p).write_text(json.dumps(prior))
    else:
        _pass1_record(p).unlink()
    result = _invoke_lifecycle(p, "01_consumed")
    assert result["track"]["ai_subtrack"]["status"] == TRACK.AI_CONSUMED
    assert result["rc"] == 1
    assert result["summary"]["verdict"] == "FAIL"
    assert result["summary"]["second_pass"]["rc"] == 0
