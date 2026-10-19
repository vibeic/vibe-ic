#!/usr/bin/env python3
"""vibe-ic#2080 — `eda_log_check` was credited by a closing parenthesis.

WHAT WAS MEASURED ON THE PRE-FIX TIP (94617408759e)
===================================================
`checker_execution_wiring_baseline.json` recorded the whole of it under #1347:

    "Never wired; held up solely by the fragment `eda_log_check)` at the end of
     a sentence in `openroad_tcl_deprecation_check`'s deprecation table."

    programs/openroad_tcl_deprecation_check.py:123
        "eda_log_check)"

One string fragment, and both wiring registers read it as an execution path.
Its own triage note names the home this commit uses: "Takes --log-file, so it is
per-design and belongs ... at the step that produces the log it should read."

WHAT THE ROW BUYS
=================
`step_yosys_synth` writes `phase2/stage2/synth/yosys.log` unconditionally, and
NOTHING in the tree asked whether that file exists, is non-empty, or carries the
`stat` table the step dropped `-q` (v1.6.193) in order to capture. The step's
own sibling comment names the failure mode it does not cover —
`_ystat.emit_stats_json` refuses to write accounting because "the docker-fallback
path can return rc=0 with an empty stdout capture" — but that guard reads the
IN-MEMORY capture, and the FILE is the artefact every later reader has. A
zero-byte `yosys.log` beside a netlist has read exactly like a complete one.

BOTH DIRECTIONS
===============
`test_a_log_carrying_the_tools_own_stat_table_is_a_PASS` and the three FINDING
cases beside it are one fixture apart: same project, same synth verdict, the
log's CONTENT the only variable. And the discriminator that must not be got
wrong is measured on its own:
`test_a_design_that_never_synthesised_is_NOT_APPLICABLE_not_a_FINDING` — a
pure-analog design has no digital RTL, `step_yosys_synth` answers SKIP by
design, and reading the log's absence directly would accuse every such design.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import design_one_shot_runner as DOSR                # noqa: E402
import step_preflight as _spf                        # noqa: E402

_DISPATCH = "plan.append(step_synth_log_audit(project, _synth_row))"
_GATE = "eda_log_check"

#: SPELLED HERE, and pinned to the runner's constants by
#: `test_this_file_measures_the_same_log_and_the_same_skip_set`.
#:
#: A module-level `DOSR._SYNTH_LOG_REL` / `DOSR._SYNTH_NOT_ATTEMPTED` would be
#: read at COLLECTION time, so on the pre-fix tree this file aborted collection
#: with one AttributeError instead of failing seventeen tests by name — and a
#: collection abort scrapes as zero failures, which is the weakest possible
#: negative control. Literals here, membership asserted below.
_SYNTH_LOG_REL = "phase2/stage2/synth/yosys.log"
# R-0915-85 — the five spellings collapse to the two words that mean NO TOOL
# RAN. A row is built for each below, so each needs the field its word requires.
_NOT_ATTEMPTED = ("NOT_MEASURED", "NOT_APPLICABLE")

_REAL_STAT_LOG = (
    "\n=== chip_top ===\n"
    "\n   Number of wires:                 12\n"
    "   Number of cells:                   42\n"
    "     $_AND_                            8\n"
)


def _project(tmp: Path, log: str | None = None) -> Path:
    p = tmp / "proj"
    (p / _SYNTH_LOG_REL).parent.mkdir(parents=True)
    if log is not None:
        (p / _SYNTH_LOG_REL).write_text(log)
    return p


def _synth(status: str):
    """A synth row wearing *status*. R-0915-85 — NOT_APPLICABLE must name the
    input line that declares it and NOT_MEASURED must say why; the row type
    refuses either without, which is the point."""
    kw = {}
    if status == "NOT_APPLICABLE":
        kw["declared_by"] = "L1: the design declares no digital RTL"
    if status == "NOT_MEASURED":
        kw["reason_class"] = "not_executed"
    return DOSR.StepResult("yosys_synth", status, 0.0, "", **kw)


def _row(res):
    assert res.extras and "synth_log_audit" in res.extras, res.extras
    return res.extras["synth_log_audit"]


# ---------------------------------------------------------------------------
# THE WIRING
# ---------------------------------------------------------------------------
def test_the_runner_dispatches_the_gate_at_a_real_call_site() -> None:
    src = Path(DOSR.__file__).read_text(errors="replace")
    assert _DISPATCH in src, (
        f"design_one_shot_runner no longer dispatches {_GATE} ({_DISPATCH!r} "
        f"absent). Its only other credit in this tree is the fragment "
        f"'eda_log_check)' inside a string — vibe-ic#2080.")


def test_the_dispatch_follows_the_step_that_writes_the_log() -> None:
    """The gate reads a file; it must run after the step that writes it, and it
    must be handed THAT step's verdict rather than a later one."""
    src = Path(DOSR.__file__).read_text(errors="replace")
    synth = src.index("step_yosys_synth, project, args.top_name, args.container")
    here = src.index(_DISPATCH)
    binding = src.index("_synth_row = plan[-1]")
    assert synth < binding < here, (
        "the synth-log audit moved ahead of the step that writes the log; it "
        "would then judge the PREVIOUS run's file, or none.")
    qsf = src.index("plan.append(step_qsf_gen(project, args.top_name, ic_class))")
    assert here < qsf, (
        "the synth-log audit no longer sits immediately after the synth "
        "dispatch, so `plan[-1]` is some other step's verdict and the "
        "NOT_APPLICABLE discriminator is reading the wrong row.")


def test_the_gate_left_both_unwired_registers() -> None:
    wired = json.loads((_PROGRAMS / "gate_is_wired_baseline.json").read_text())
    assert _GATE not in wired["unwired"], (
        "gate_is_wired_baseline.json still records this gate as unwired.")
    checkers = json.loads(
        (_PROGRAMS / "checker_execution_wiring_baseline.json").read_text())
    assert _GATE + ".py" not in checkers["known"], (
        "checker_execution_wiring_baseline.json still records this checker as "
        "test-only; its audit FAILs on a recorded checker that gained a runner.")
    assert _GATE + ".py" not in (checkers.get("triage") or {}), (
        "the triage note outlived its `known` row.")


def test_the_step_can_never_move_the_run_verdict() -> None:
    src = Path(DOSR.__file__).read_text(errors="replace")
    step = next(n for n in ast.walk(ast.parse(src))
                if isinstance(n, ast.FunctionDef)
                and n.name == "step_synth_log_audit")
    calls = [c for c in ast.walk(step)
             if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
             and c.func.id == "StepResult" and len(c.args) >= 2
             and isinstance(c.args[1], ast.Constant)]
    statuses = {c.args[1].value for c in calls}
    # R-0915-85 — `ADVISORY` was a STATUS that meant "this row cannot move the
    # verdict". It is a DISCLOSURE beside a `PASS` now, and the property #2080
    # pins is unchanged: `run_verdict` gives a disclosure no arithmetic at all,
    # so the row still cannot move anything. Asserted in BOTH halves, because
    # a PASS without the disclosure would be a row that CAN move the verdict.
    assert statuses == {"PASS"}, (
        f"step_synth_log_audit returns {sorted(statuses)}; vibe-ic#2080 wires a "
        f"recorded-unwired gate as non-moving unless its docstring declares it "
        f"BLOCKING, and this gate's does not.")
    for c in calls:
        kw = {k.arg: k.value for k in c.keywords}
        disc = ast.unparse(kw["disclosures"]) if "disclosures" in kw else ""
        assert "ADVISORY" in disc, (
            f"a StepResult in step_synth_log_audit is a bare PASS: without "
            f"Disclosure.ADVISORY beside it, the row CAN move the run verdict, "
            f"which is exactly what #2080 forbids")


# ---------------------------------------------------------------------------
# THE VERDICT MOVES ON THE LOG'S CONTENT — BOTH DIRECTIONS
# ---------------------------------------------------------------------------
def test_a_log_carrying_the_tools_own_stat_table_is_a_PASS(
        tmp_path: Path) -> None:
    p = _project(tmp_path, _REAL_STAT_LOG)
    row = _row(DOSR.step_synth_log_audit(p, _synth("PASS")))
    assert row["verdict"] == "PASS", row
    assert row["expect_matched"], row


def test_an_empty_log_beside_a_passing_synth_is_a_FINDING(
        tmp_path: Path) -> None:
    """The exact shape `step_yosys_synth`'s own comment names: the
    docker-fallback path "can return rc=0 with an empty stdout capture". The
    guard beside it refuses to write ACCOUNTING for that; nothing said anything
    about the LOG, which is what a later reader has."""
    p = _project(tmp_path, "")
    row = _row(DOSR.step_synth_log_audit(p, _synth("PASS")))
    assert row["verdict"] == "FINDING", row
    assert row["categories"] == ["EMPTY_LOG"], row


def test_an_absent_log_after_a_synth_that_ran_is_a_FINDING(
        tmp_path: Path) -> None:
    p = _project(tmp_path, None)
    row = _row(DOSR.step_synth_log_audit(p, _synth("PASS")))
    assert row["verdict"] == "FINDING", row
    assert row["categories"] == ["LOG_MISSING"], row


def test_a_log_without_the_tools_accounting_is_a_FINDING(
        tmp_path: Path) -> None:
    """Non-empty is not the same as complete. A log that stops before `stat`
    is a run that did not finish saying what it produced."""
    p = _project(tmp_path, "Yosys 0.33\n-- Running command `read_verilog` --\n")
    row = _row(DOSR.step_synth_log_audit(p, _synth("PASS")))
    assert row["verdict"] == "FINDING", row
    assert row["categories"] == ["EXPECTED_NOT_FOUND"], row


# ---------------------------------------------------------------------------
# THE DISCRIMINATOR THAT MUST NOT BE GOT WRONG
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("status", _NOT_ATTEMPTED)
def test_a_design_that_never_synthesised_is_NOT_APPLICABLE_not_a_FINDING(
        tmp_path: Path, status: str) -> None:
    """A pure-analog design has no digital RTL and `step_yosys_synth` answers
    SKIP by design. Judging the log's ABSENCE would accuse every one of them;
    judging it as a skip would launder a real missing artefact. The synth
    step's own verdict is the only thing that can tell the two apart, and it is
    passed in rather than re-derived."""
    p = _project(tmp_path, None)
    row = _row(DOSR.step_synth_log_audit(p, _synth(status)))
    assert row["verdict"] == "NOT_APPLICABLE", row
    assert row["synth_status"] == status


def test_this_file_measures_the_same_log_and_the_same_skip_set() -> None:
    """MEMBERSHIP, both ways, against the shipped constants.

    A literal here that drifted from the runner's would leave this file green
    while measuring a file the runner never writes and a skip set it does not
    use. `_spf.REFUSAL_STATUS` is compared rather than spelled twice: a BLOCKED
    step never ran, so it never owed a log, and a rename there must not
    silently start accusing every refused run.
    """
    assert _SYNTH_LOG_REL == DOSR._SYNTH_LOG_REL
    assert set(_NOT_ATTEMPTED) == set(DOSR._SYNTH_NOT_ATTEMPTED)
    # The pre-flight refusal is still in the set — it is NOT_MEASURED now, and
    # a refused synth step is exactly "no tool ran".
    assert _spf.REFUSAL_STATUS in DOSR._SYNTH_NOT_ATTEMPTED


def test_a_synth_that_FAILED_still_owes_its_log(tmp_path: Path) -> None:
    """FAIL means the tool ran and the step judged the result. The log is the
    evidence for that judgement and must still be there — this is the direction
    a "skip when anything went wrong" rule would silently lose."""
    p = _project(tmp_path, None)
    row = _row(DOSR.step_synth_log_audit(p, _synth("FAIL")))
    assert row["verdict"] == "FINDING", row


def test_no_reject_pattern_is_passed(tmp_path: Path) -> None:
    """Deliberate, and stated in the row rather than left to inference.

    This step has a slang fallback frontend whose diagnostics legitimately
    contain the word `error`; deciding which strings in a synthesis log are
    fatal is a contract about the tool and the design, and inventing one here
    would manufacture findings on correct runs.
    """
    p = _project(tmp_path, _REAL_STAT_LOG + "ERROR: harmless downstream note\n")
    row = _row(DOSR.step_synth_log_audit(p, _synth("PASS")))
    assert row["reject_pattern"] is None
    assert row["verdict"] == "PASS", row


def test_the_verdict_report_is_published_under_reports_phase2_gates(
        tmp_path: Path) -> None:
    p = _project(tmp_path, _REAL_STAT_LOG)
    res = DOSR.step_synth_log_audit(p, _synth("PASS"))
    out = p / "reports/phase2/gates/synth_log_audit.json"
    assert out.is_file(), sorted(str(x) for x in p.rglob("*.json"))
    assert res.output_files == [str(out)]
    assert json.loads(out.read_text())["program"] == _GATE


def _native_log_project(tmp_path, monkeypatch, text=_REAL_STAT_LOG, *, critical_error=False):
    """Real run_chain receipt and handoff; neutral synthesis process output only."""
    import subprocess
    import librelane_contract as lc
    import synth_handoff_netlist_check as handoff
    from _stated_eda_image import mock_docker_route
    from test_step14_report_producer_authorship import project_fixture, put
    project, _ = project_fixture(tmp_path)
    put(project / 'phase3/librelane_switch.json', {'steps': {'9': 'librelane'}})
    mock_docker_route(monkeypatch)
    folder = project / 'phase3/librelane/02-yosys-synthesis'
    cfg = project / 'phase3/librelane/synthesis_resolved.json'
    saved = {path.relative_to(folder): path.read_bytes() for path in folder.rglob('*')
             if path.is_file() and path.name not in ('vibeic_receipt.json', 'input_fingerprint.json', 'pdk_root.json')}
    if critical_error:
        saved[Path('reports/chk.rpt')] = (
            b'Warning: Wire core.\\bad is used but has no driver.\n'
            b'Found and reported 1 problems.\n')
    header_config = put(project / 'phase3/librelane/header.json', {'meta': {'step': 'Yosys.JsonHeader'}})
    initial = put(project / 'phase3/librelane/initial.state.json', {})
    monkeypatch.setattr(lc, 'image_capability', lambda *a, **k: {})
    monkeypatch.setattr(lc, 'openroad_home', lambda *a, **k: None)
    calls = []

    def process_edge(argv, **kwargs):
        step = argv[argv.index('--id') + 1]
        target = Path(argv[argv.index('-o') + 1])
        put(target / 'config.json', json.loads(Path(argv[argv.index('-c') + 1]).read_text()))
        put(target / 'state_in.json', json.loads(Path(argv[argv.index('-i') + 1]).read_text()))
        if step == 'Yosys.JsonHeader':
            header = put(target / 'core.h.json', {'module': 'core'})
            put(target / 'state_out.json', {'json_h': str(header)})
        else:
            for rel, data in saved.items():
                path = target / rel; path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
        calls.append(step)
        return subprocess.CompletedProcess(argv, 0, text if step == 'Yosys.Synthesis' else 'neutral header output', '')

    monkeypatch.setattr(lc, 'run_container', process_edge)
    lc.run_chain(project, 'registry.invalid/source-control@sha256:' + 'a' * 64,
                 [('Yosys.JsonHeader', header_config, initial), ('Yosys.Synthesis', cfg, initial)],
                 pdk_root='/pdk')
    if not critical_error:
        handoff.publish_handoff(project, folder, project / 'phase2/stage2/synth/core_synth.v', 'core')
    (project / 'reports').mkdir(exist_ok=True)
    assert calls == ['Yosys.JsonHeader', 'Yosys.Synthesis']
    assert not (project / _SYNTH_LOG_REL).exists()
    return project, folder


def test_native_log_audit_and_lint_cite_the_current_receipt_bound_log(tmp_path, monkeypatch):
    project, folder = _native_log_project(tmp_path, monkeypatch)
    row = _row(DOSR.step_synth_log_audit(project, _synth('PASS')))
    DOSR.step_emit_phase2_manifests(project, [])
    hygiene = json.loads((project / 'reports/phase2/lint/rtl_hygiene.json').read_text())
    observed = {'audit': row['verdict'], 'audit_log': row['log_file'],
                'lint': hygiene['verdict'], 'lint_evidence': hygiene.get('evidence')}
    (tmp_path / 'NATIVE_LOG_READBACK.json').write_text(json.dumps(observed, indent=2) + '\n')
    assert (row['verdict'], hygiene['verdict']) == ('PASS', 'PASS'), observed
    assert Path(row['log_file']) == folder / 'invocation.log'
    assert hygiene['evidence'] == str((folder / 'invocation.log').relative_to(project))
    receipt = json.loads((project / 'reports/phase2/gates/eda_log_check_receipt.json').read_text())
    assert receipt['verdict'] == 'PASS' and receipt['examined'] > 0
    assert receipt['subject']['items'][0]['path'] == str(folder / 'invocation.log')
    assert not (project / _SYNTH_LOG_REL).exists()


def test_native_log_refusals_never_fall_back_to_an_unrelated_legacy_log(tmp_path, monkeypatch):
    for damage in ('missing', 'changed', 'missing_binding', 'malformed_binding', 'changed_binding', 'rtl', 'critical_check'):
        with monkeypatch.context() as patch:
            project, folder = _native_log_project(tmp_path / damage, patch, critical_error=damage == 'critical_check')
            legacy = project / _SYNTH_LOG_REL
            legacy.write_text(_REAL_STAT_LOG)
            if damage == 'missing':
                (folder / 'invocation.log').unlink()
            elif damage == 'changed':
                (folder / 'invocation.log').write_text(_REAL_STAT_LOG + '\nERROR: changed native execution bytes\n')
            elif damage in ('missing_binding', 'malformed_binding', 'changed_binding'):
                path = project / 'phase2/stage2/synth/synth_inputs.json'
                doc = json.loads(path.read_text())
                if damage == 'missing_binding': del doc['librelane_synthesis']
                elif damage == 'malformed_binding': doc['librelane_synthesis'] = 'malformed'
                else: doc['librelane_synthesis']['receipt_sha256'] = '0' * 64
                path.write_text(json.dumps(doc))
            elif damage == 'rtl':
                (project / 'phase2/stage1/rtl/core.v').write_text('module changed; endmodule\n')
            with pytest.raises((ValueError, OSError, RuntimeError)) as refused:
                DOSR._synthesis_log_path(project)
            expected = f'{type(refused.value).__name__}: {refused.value}'
            row = _row(DOSR.step_synth_log_audit(project, _synth('PASS')))
            assert row['verdict'] == 'NOT_MEASURED' and row['reason'], row
            assert row.get('rc') is None, row
            result = DOSR.step_emit_phase2_manifests(project, [])
            hygiene = json.loads((project / 'reports/phase2/lint/rtl_hygiene.json').read_text())
            assert result.status == 'PASS'  # publication completed, not synthesis
            assert hygiene['verdict'] == 'INCOMPLETE' and hygiene['reason'] == expected, hygiene
            assert hygiene.get('evidence') is None, hygiene
            assert legacy.read_text() == _REAL_STAT_LOG


def test_a_bound_native_log_without_accounting_keeps_a_real_fail_receipt(tmp_path, monkeypatch):
    project, _ = _native_log_project(tmp_path, monkeypatch, 'neutral producer stopped before stat\n')
    row = _row(DOSR.step_synth_log_audit(project, _synth('PASS')))
    assert row['verdict'] == 'FINDING' and row['categories'] == ['EXPECTED_NOT_FOUND'], row
    receipt = json.loads((project / 'reports/phase2/gates/eda_log_check_receipt.json').read_text())
    assert receipt['verdict'] == 'FAIL' and receipt['examined'] > 0


def _absent_selected_handoff(project):
    import synth_handoff_netlist_check as handoff
    switch = project / 'phase3/librelane_switch.json'
    switch.parent.mkdir(parents=True, exist_ok=True)
    switch.write_text('{"steps":{"9":"librelane"}}\n')
    current = handoff.bound_handoff(project.resolve())
    assert current['verdict'] == 'FAIL', current
    assert current['reason_class'] == 'tool_handoff_invalid', current
    assert 'current LibreLane synthesis handoff is absent' in current['findings'], current
    return 'ValueError: SYNTH_LOG_HANDOFF_UNBOUND: ' + str(current)


def test_absent_selected_handoff_is_disclosed_without_running_log_gate(tmp_path, monkeypatch):
    expected = _absent_selected_handoff(tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError('an unbound transcript reached eda_log_check')
    monkeypatch.setattr(DOSR._eda_log, 'main', forbidden)
    result = DOSR.step_synth_log_audit(tmp_path, _synth('FAIL'))
    row = _row(result)
    assert row['verdict'] == 'NOT_MEASURED' and row['reason'] == expected, row
    assert row['synth_status'] == 'FAIL' and row.get('rc') is None, row
    assert result.disclosures == [DOSR._V.Disclosure.ADVISORY]
    assert not (tmp_path / _SYNTH_LOG_REL).exists()


@pytest.mark.parametrize('handoff_state', ['absent', 'bound', 'native-failed'])
def test_normal_phase2_report_survives_absent_advisory_handoff(tmp_path, monkeypatch, handoff_state):
    """Real manifest owner, coordinator and final report; no EDA invocation.

    Native synthesis and all unrelated producer leaves are declared neutral.
    A real run_chain/receipt fixture supplies the bound-log cases; the strict
    handoff reader, advisory audit and complete manifest writer remain real.
    """
    if handoff_state == 'absent':
        project = tmp_path / 'project'
        project.mkdir()
        expected = _absent_selected_handoff(project)
        rtl = project / 'phase2/stage1/rtl/core.v'
        rtl.parent.mkdir(parents=True)
        rtl.write_text('module core(input a, output y); assign y=a; endmodule\n')
    else:
        project, _ = _native_log_project(tmp_path, monkeypatch,
                                         critical_error=handoff_state == 'native-failed')
        if handoff_state == 'native-failed':
            with pytest.raises(ValueError) as refused:
                DOSR._synthesis_log_path(project)
            expected = f'ValueError: {refused.value}'
        else:
            expected = None
    switch = project / 'phase3/librelane_switch.json'
    selected = json.loads(switch.read_text())
    selected['steps']['3'] = 'direct'  # unrelated CDC producer is outside this fixture
    switch.write_text(json.dumps(selected))
    synth_status = 'PASS' if handoff_state == 'bound' else 'FAIL'
    docs = project / 'phase1/generated_docs'
    docs.mkdir(parents=True, exist_ok=True)
    for number in range(1, 14):
        (docs / f'L{number}.json').write_text('{}')
    for name in list(vars(DOSR)):
        if not name.startswith('step_') or name in ('step_synth_log_audit', 'step_emit_phase2_manifests'):
            continue
        def neutral(*args, _name=name, **kwargs):
            result = (_synth(synth_status) if _name == 'step_yosys_synth' else
                      DOSR.StepResult(_name.removeprefix('step_'), 'NOT_APPLICABLE', 0.0,
                                      'unrelated producer outside this reporting regression',
                                      declared_by='neutral coordinator fixture'))
            return [result] if _name == 'step_dft_lec_chain' else result
        monkeypatch.setattr(DOSR, name, neutral)
    monkeypatch.setattr(DOSR._spf, 'gate', lambda project, owner, site, refuse, fn, *a, **kw:
                        fn(*a, **{k: v for k, v in kw.items() if not k.startswith('_preflight')}))
    import execution_policy
    import flow_declared_producer_run
    monkeypatch.setattr(flow_declared_producer_run, 'run_for_step', lambda *a, **kw: None)
    monkeypatch.setattr(DOSR, '_audit_after_declared_producers', lambda *a, **kw:
        DOSR.StepResult('final_audit', 'NOT_MEASURED', 0.0,
                        'unrelated whole-flow audit outside this reporting fixture',
                        reason_class=DOSR._V.ReasonClass.NOT_EXECUTED))
    # The manifest's canonical step consumers are separate from this writer.
    # Keep their absence explicit, not PASS, while exercising real retention.
    import execution_backend_gates
    monkeypatch.setattr(execution_backend_gates, 'evaluate', lambda *a, **kw:
                        {'status': 'NOT_MEASURED',
                         'reasons': ['unrelated canonical consumer outside reporting fixture']})
    monkeypatch.setattr(DOSR._pl, 'emit_final_summary', lambda *a, **kw: False)
    monkeypatch.setattr(execution_policy, '_ordinary_runtime', None)
    monkeypatch.setattr(sys, 'argv', ['design', str(project), '--skip-hardware',
                                    '--skip-phase3', '--skip-analog',
                                    '--max-rtl-repair-retries', '0'])
    rc = DOSR.main()
    assert rc == 1  # incomplete neutral fixture is never whole-flow PASS
    report = json.loads((project / 'reports/orchestrator/phase2_one_shot.json').read_text())
    rows = {row['name']: row for row in report['steps']}
    assert not report.get('final_audit_pending'), report
    assert rows['yosys_synth']['status'] == synth_status, rows['yosys_synth']
    if synth_status == 'FAIL':
        assert report['verdict'] == 'FAIL', report
        assert rows['yosys_synth']['status'] == 'FAIL', rows['yosys_synth']
    audit = rows['synth_log_audit']['extras']['synth_log_audit']
    hygiene = json.loads((project / 'reports/phase2/lint/rtl_hygiene.json').read_text())
    assert rows['phase2_manifests']['status'] == 'PASS'
    if expected is None:
        assert audit['verdict'] == 'PASS' and hygiene['verdict'] == 'PASS', (audit, hygiene)
        assert hygiene['evidence'].endswith('/invocation.log'), hygiene
    else:
        assert audit['verdict'] == 'NOT_MEASURED' and audit['reason'] == expected, audit
        assert hygiene['verdict'] == 'INCOMPLETE' and hygiene['reason'] == expected, hygiene
        assert hygiene.get('evidence') is None, hygiene
    assert not (project / _SYNTH_LOG_REL).exists()
    (tmp_path / 'REPORTING_OBSERVATION.json').write_text(json.dumps({
        'scope': 'Real manifest/audit/main/report; neutral unrelated producers and native process leaf',
        'handoff': handoff_state, 'rc': rc, 'report': report, 'hygiene': hygiene, 'audit': audit,
    }, indent=2))


@pytest.mark.parametrize('synth_status', ['FAIL', 'PASS'])
def test_manifest_publication_discloses_current_refusal_and_replaces_old_lint_pass(tmp_path, synth_status):
    expected = _absent_selected_handoff(tmp_path)
    rtl = tmp_path / 'phase2/stage1/rtl/core.v'
    rtl.parent.mkdir(parents=True)
    rtl.write_text('module core(input clk, output y); assign y=clk; endmodule\n')
    old = tmp_path / 'reports/phase2/lint/rtl_hygiene.json'
    old.parent.mkdir(parents=True)
    old.write_text('{"verdict":"PASS","evidence":"old.log"}')
    legacy = tmp_path / _SYNTH_LOG_REL
    legacy.parent.mkdir(parents=True)
    legacy.write_text(_REAL_STAT_LOG)
    result = DOSR.step_emit_phase2_manifests(tmp_path, [_synth(synth_status)], 'core', None)
    hygiene = json.loads(old.read_text())
    assert result.name == 'phase2_manifests'
    assert hygiene['verdict'] == 'INCOMPLETE' and hygiene['reason_class'] == 'tool_handoff_invalid', hygiene
    assert hygiene['reason'] == expected, hygiene
    assert hygiene['rtl_files'] == ['core.v'] and 'evidence' not in hygiene, hygiene
    assert all((tmp_path / rel).is_file() for rel in result.output_files), result.output_files
    # Publication must not convert the strict reader's refusal into a usable
    # legacy transcript, even if the incoming source row itself claims PASS.
    with pytest.raises(ValueError, match='SYNTH_LOG_HANDOFF_UNBOUND'):
        DOSR._synthesis_log_path(tmp_path)


def test_full_phase2_report_survives_real_manifest_emitter_on_failed_synthesis(tmp_path, monkeypatch):
    """Actual coordinator, strict reader, emitter and final writer; neutral unrelated leaves."""
    _absent_selected_handoff(tmp_path)
    docs = tmp_path / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    for number in range(1, 14):
        (docs / f'L{number}.json').write_text('{}')
    rtl = tmp_path / 'phase2/stage1/rtl/core.v'
    rtl.parent.mkdir(parents=True)
    rtl.write_text('module core(input clk, output y); assign y=clk; endmodule\n')
    (tmp_path / 'reports').mkdir()
    for name in list(vars(DOSR)):
        if not name.startswith('step_') or name in ('step_synth_log_audit', 'step_emit_phase2_manifests'):
            continue
        def neutral(*args, _name=name, **kwargs):
            result = (_synth('FAIL') if _name == 'step_yosys_synth' else
                      DOSR.StepResult(_name.removeprefix('step_'), 'NOT_APPLICABLE', 0.0,
                                      'unrelated producer outside manifest publication regression',
                                      declared_by='neutral coordinator fixture'))
            return [result] if _name == 'step_dft_lec_chain' else result
        monkeypatch.setattr(DOSR, name, neutral)
    monkeypatch.setattr(DOSR._spf, 'gate', lambda project, owner, site, refuse, fn, *a, **kw:
                        fn(*a, **{k: v for k, v in kw.items() if not k.startswith('_preflight')}))
    import execution_policy
    import flow_declared_producer_run
    monkeypatch.setattr(execution_policy, '_ordinary_runtime', None)
    monkeypatch.setattr(flow_declared_producer_run, 'run_for_step', lambda *a, **kw: None)
    monkeypatch.setattr(sys, 'argv', ['design', str(tmp_path), '--skip-hardware',
                                    '--skip-phase3', '--skip-analog', '--max-rtl-repair-retries', '0'])
    assert DOSR.main() == 1
    report = json.loads((tmp_path / 'reports/orchestrator/phase2_one_shot.json').read_text())
    rows = {row['name']: row for row in report['steps']}
    assert report['verdict'] == 'FAIL' and not report.get('final_audit_pending'), report
    assert rows['yosys_synth']['status'] == 'FAIL'
    hygiene = json.loads((tmp_path / 'reports/phase2/lint/rtl_hygiene.json').read_text())
    assert hygiene['verdict'] == 'INCOMPLETE' and 'SYNTH_LOG_HANDOFF_UNBOUND' in hygiene['reason']
