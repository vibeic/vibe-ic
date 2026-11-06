#!/usr/bin/env python3
"""The aggregator that writes `phase3/final/metrics.json`.

The control this module is built around: for EVERY key, deleting the one report
that answers it must turn THAT key -- and no other -- into NOT_MEASURED, with
the file still written and the exit code still 0. A rule that answers from
somewhere else, or a rule that takes a whole tree down with it, fails here.
"""
import json
import hashlib
import sys
import subprocess
from pathlib import Path

import pytest
from _direct_density_fixture import stage_direct_density

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import signoff_metrics_aggregate as AGG           # noqa: E402
import tapeout_docs_gen as TDG                    # noqa: E402


def _native_tns_project(root):
    """Existing synthetic retained-native fixture; real strict reader, no EDA."""
    from test_f15_step23_gates_read_the_tool_arm import tool_project, rebind, CORNERS, STA
    project = tool_project(root)
    state_path = project / STA / 'state_out.json'
    state = json.loads(state_path.read_text())
    for corner in CORNERS:
        for role in ('setup', 'hold'):
            state['metrics'][f'timing__{role}__tns__corner:{corner}'] = 0
    _write(state_path, state)
    rebind(project)
    _write(project / 'reports/phase3/sta/post_route_signoff_corner.json', {
        'setup_worst_slack_ns': 1.0, 'hold_worst_slack_ns': 0.4,
        'report': 'reports/phase3/sta_postpnr_signoff.json'})
    return project, state_path, rebind, CORNERS


def test_native_json_tns_uses_real_scene_metrics_and_keeps_negative_totals(tmp_path):
    project, state_path, rebind, corners = _native_tns_project(tmp_path)
    setup = AGG._tns(project, 'setup')
    hold = AGG._tns(project, 'hold')
    setup_value, hold_value = setup.value, hold.value
    assert setup_value == hold_value == 0, 'receipt-bound native TNS was lost by the JSON/text handoff'
    assert setup.source.endswith('/state_out.json')
    state = json.loads(state_path.read_text())
    # Different scenes, distinct totals and unchanged positive WNS: neither
    # the first scene nor the WNS winner supplies the TNS aggregate.
    state['metrics'][f'timing__setup__tns__corner:{corners[3]}'] = -2.5
    state['metrics'][f'timing__setup__tns__corner:{corners[6]}'] = -1.0
    state['metrics'][f'timing__hold__tns__corner:{corners[4]}'] = -0.75
    _write(state_path, state)
    rebind(project)
    assert AGG.main([str(project)]) == 0
    metrics = json.loads((project / 'phase3/final/metrics.json').read_text())
    assert metrics['timing__setup__tns'] == -2.5
    assert metrics['timing__hold__tns'] == -0.75
    clean = {key: 0 for _label, key, _pred in TDG.MANUFACTURABILITY + TDG.ELECTRICAL}
    for role in ('setup', 'hold'):
        clean[f'timing__{role}__tns'] = metrics[f'timing__{role}__tns']
    path = project / 'synthetic-doc-metrics.json'
    _write(path, clean)
    destination = project / 'refused-documents'
    cp = subprocess.run([sys.executable, TDG.__file__, '--metrics', str(path),
                         '--design', 'synthetic', '--pdk', 'neutral',
                         '--out-dir', str(destination)], capture_output=True, text=True)
    assert cp.returncode == 1 and 'NOT RELEASABLE' in cp.stderr
    assert '-2.5' in cp.stderr and '-0.75' in cp.stderr
    assert not destination.exists() or not list(destination.iterdir())
    print('NATIVE_TNS_NEGATIVE_TOTALS', metrics['timing__setup__tns'], metrics['timing__hold__tns'], 'DOCS_RC', cp.returncode)


def test_native_tns_never_defaults_partial_bad_or_unbound_measurements(tmp_path):
    for fault in ('missing-record', 'missing-native-record', 'missing-receipt',
                  'stale-state', 'stale-config', 'changed-input',
                  'partial', 'string', 'bool', 'nan', 'inf', 'wrong-report', 'scope-gap'):
        project, state_path, rebind, corners = _native_tns_project(tmp_path / fault)
        folder = state_path.parent
        if fault == 'missing-record':
            (project / 'reports/phase3/sta/post_route_signoff_corner.json').unlink()
        elif fault == 'missing-native-record':
            (project / 'reports/phase3/sta_postpnr_signoff.json').unlink()
        elif fault == 'missing-receipt':
            (folder / 'vibeic_receipt.json').unlink()
        elif fault in ('stale-state', 'stale-config'):
            path = state_path if fault == 'stale-state' else folder / 'config.json'
            path.write_text(path.read_text() + ' ')
        elif fault == 'changed-input':
            state = json.loads(state_path.read_text())
            path = Path(state['nl'])
            path.write_text(path.read_text() + '// actual timed input changed\n')
        elif fault == 'wrong-report':
            _write(project / 'reports/phase3/unselected.json', {'setup_tns': 0})
            _write(project / 'reports/phase3/sta/post_route_signoff_corner.json',
                   {'report': 'reports/phase3/unselected.json'})
        elif fault == 'scope-gap':
            library = tmp_path / fault / 'pdk_root/p/libs.ref/cells/lib/cells__ss_125C_4v50.lib'
            library.write_text(library.read_text() + '// changed Liberty bytes\n')
        else:
            state = json.loads(state_path.read_text())
            key = f'timing__setup__tns__corner:{corners[-1]}'
            if fault == 'partial':
                state['metrics'].pop(key)
            else:
                state['metrics'][key] = {'string': '0', 'bool': False,
                                         'nan': float('nan'), 'inf': float('inf')}[fault]
            _write(state_path, state)
            rebind(project)
        row = AGG._tns(project, 'setup')
        assert row.value == AGG.NOT_MEASURED and row.reason, fault
        print('NATIVE_TNS_REFUSAL', fault, row.value)


def test_native_tns_repeated_consumers_are_stable_and_report_bytes_still_bind(tmp_path):
    project, _state, _rebind, _corners = _native_tns_project(tmp_path)
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in project.rglob('*') if p.is_file()}
    assert AGG._tns(project, 'setup').value == AGG._tns(project, 'setup').value
    assert before == {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in project.rglob('*') if p.is_file()}
    assert AGG.main([str(project)]) == 0
    assert AGG.main([str(project), '--check']) == 0
    assert AGG.main([str(project), '--check']) == 0
    report = project / 'reports/phase3/sta_postpnr_signoff.json'
    report.write_text(report.read_text() + ' ')
    assert AGG.main([str(project), '--check']) == 1
    print('NATIVE_TNS_REPORT_BYTE_MUTATION_REFUSED')


def _write(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj) if not isinstance(obj, str) else obj,
                 encoding="utf-8")








def test_router_count_comes_from_the_run_named_by_its_own_handoff(tmp_path):
    run = tmp_path / 'phase3/librelane/native-run'
    route = run / '27-openroad-detailedrouting'
    _write(route / 'config.json', {'meta': {'step': 'OpenROAD.DetailedRouting'}})
    _write(route / 'state_out.json', {'metrics': {'route__drc_errors': 4}})
    _write(run / 'flow.log', f"Running 'OpenROAD.DetailedRouting' at '{route}'…\n")
    _write(tmp_path / 'reports/phase3/librelane_floorplan_handoff.json',
           {'state': str(run / '03-openroad-floorplan/state_out.json')})
    measured = AGG._drc_for_tool(tmp_path, 'openroad')
    assert measured.value == 4
    assert measured.source == str((route / 'state_out.json').relative_to(tmp_path))


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    """A tree carrying one report of every kind the rules read.

    Chip-AGNOSTIC: no design name, no PDK, no vendor string decides anything
    here -- the reports are the shapes this flow writes, with values chosen so
    that a wrong rule cannot land on a right answer by coincidence (every count
    is distinct).
    """
    p = tmp_path / "proj"
    stage_direct_density(p)
    _write(p / "reports/phase3/drc_router.json", {
        "summary": {"real_violation_total": 3,
                    "producers": [{"producer": "openroad"}]}})
    _write(p / "reports/phase3/drc_signoff.json", {
        "summary": {"real_violation_total": 5,
                    "categories_found": ["spacing", "density"],
                    "producers": [{"producer": "klayout"}]}})
    _write(p / "reports/phase3/antenna.json",
           {"net_violations": 7, "pin_violations": 9,
            "routing_incomplete": False})
    _write(p / "reports/phase3/lvs.json",
           {"summary": {"terminal_verdict": "MATCH"}})
    _write(p / "reports/phase3/sta/post_route_signoff_corner.json",
           {"setup_worst_slack_ns": 1.25, "hold_worst_slack_ns": 0.5,
            "report": "reports/phase3/sta_spef_multicorner.rpt"})
    _write(p / "reports/phase3/sta_spef_multicorner.rpt",
           "=== SETUP (max) ===\ntns max -2.50\n"
           "=== HOLD (min) ===\ntns max -0.75\n")
    _write(p / "reports/phase3/sta_spef_based.rpt",
           "SIGNOFF_CHECK_TYPES_REPORTED recovery max_slew max_capacitance\n")
    _write(p / "phase3/stage3/pnr/filled.def",
           "UNITS DISTANCE MICRONS 1000 ;\nDIEAREA ( 0 0 ) ( 120000 80000 ) ;\n")
    return p


#: key -> the ONE project-relative artefact that answers it.
OWNER = {
    "route__drc_errors": "reports/phase3/drc_router.json",
    "klayout__drc_error__count": "reports/phase3/drc_signoff.json",
    "klayout__density_error__count": "reports/phase3/drc_signoff.json",
    "antenna__violating__nets": "reports/phase3/antenna.json",
    "antenna__violating__pins": "reports/phase3/antenna.json",
    "design__lvs_error__count": "reports/phase3/lvs.json",
    "design__lvs_unmatched_device__count": "reports/phase3/lvs.json",
    "design__lvs_unmatched_net__count": "reports/phase3/lvs.json",
    "design__lvs_unmatched_pin__count": "reports/phase3/lvs.json",
    "timing__setup__ws": "reports/phase3/sta/post_route_signoff_corner.json",
    "timing__hold__ws": "reports/phase3/sta/post_route_signoff_corner.json",
    "timing__setup__tns": "reports/phase3/sta_spef_multicorner.rpt",
    "timing__hold__tns": "reports/phase3/sta_spef_multicorner.rpt",
    "design__max_slew_violation__count": "reports/phase3/sta_spef_based.rpt",
    "design__max_cap_violation__count": "reports/phase3/sta_spef_based.rpt",
    "design__die__bbox": "phase3/stage3/pnr/filled.def",
}


def test_the_fixture_measures_every_key_that_has_a_source(project):
    metrics, report = AGG.aggregate(project)
    measured = {r["key"] for r in report["rows"] if r["measured"]}
    assert set(OWNER) <= measured, sorted(set(OWNER) - measured)


def test_each_value_is_the_one_its_report_states(project):
    metrics, _ = AGG.aggregate(project)
    assert metrics["route__drc_errors"] == 3
    assert metrics["klayout__drc_error__count"] == 5
    assert metrics["antenna__violating__nets"] == 7
    assert metrics["antenna__violating__pins"] == 9
    assert metrics["timing__setup__ws"] == 1.25
    assert metrics["timing__hold__ws"] == 0.5
    # The HOLD section's line is also spelled `tns max` on real OpenSTA output,
    # so a rule keyed on the LABEL rather than the SECTION reads -2.50 twice.
    assert metrics["timing__setup__tns"] == -2.50
    assert metrics["timing__hold__tns"] == -0.75
    # DEF database units -> microns, or the readers print a die 1000x too big.
    assert metrics["design__die__bbox"] == "0 0 120 80"


@pytest.mark.parametrize("key", sorted(OWNER))
def test_removing_one_report_unmeasures_that_key_and_only_it(project, key):
    base, _ = AGG.aggregate(project)
    (project / OWNER[key]).unlink()
    after, report = AGG.aggregate(project)

    assert after[key] == AGG.NOT_MEASURED
    reason = after["__provenance__"][key]["reason"]
    assert reason and OWNER[key].split("/")[-1] in reason or reason, reason

    # Only the keys THIS artefact owns changed. Nothing else moved, and nothing
    # silently acquired a value from a second reader.
    expected_moved = {k for k, src in OWNER.items() if src == OWNER[key]}
    # The corner record is not only the source of the two worst-slack numbers:
    # it is also what says WHICH report the TNS numbers may be attributed to.
    # Losing it must unmeasure them too -- a TNS taken from a report no record
    # names is a number from an unknown corner, which is the one thing a
    # sign-off document must not print.
    if OWNER[key] == "reports/phase3/sta/post_route_signoff_corner.json":
        expected_moved |= {"timing__setup__tns", "timing__hold__tns"}
    moved = {k for k in base if k != "__provenance__" and base[k] != after[k]}
    assert moved == expected_moved, (moved, expected_moved)


@pytest.mark.parametrize("key", sorted(OWNER))
def test_a_missing_report_is_never_a_default_and_never_an_absent_key(
        project, key):
    (project / OWNER[key]).unlink()
    metrics, _ = AGG.aggregate(project)
    # WRITTEN, not omitted: `tapeout_docs_gen.g` answers NOT_MEASURED for an
    # absent key too, so omitting it would make "this run had no such report"
    # indistinguishable from "this aggregator has no rule for it".
    assert key in metrics
    assert metrics[key] == AGG.NOT_MEASURED
    assert metrics["__provenance__"][key]["measured"] is False


def test_an_empty_tree_answers_every_key_and_still_exits_zero(tmp_path):
    empty = tmp_path / "bare"
    empty.mkdir()
    rc = AGG.main([str(empty)])
    assert rc == 0
    out = json.loads((empty / "phase3/final/metrics.json").read_text())
    for key, _, _ in AGG.RULES:
        assert out[key] == AGG.NOT_MEASURED
        assert out["__provenance__"][key]["reason"]


def test_every_key_the_release_readers_read_has_a_rule():
    """The readers' table is the population; a key added there and not here
    would silently be NOT_MEASURED forever, which is the exact failure this
    whole program was written to end.

    2026-09-15 (icspm2): this aggregator acquired a SECOND consumer —
    `every_required_metric_key_has_a_producer`, which proves a sign-off AXIS
    from a canonical metric name and was reporting six axes as "NOT PROVEN BY
    ANY RUN IN THIS CORPUS" over runs that had measured every one of them. The
    keys added for it are not printed in any release document, so the equality
    below would forbid them. It is kept as an EQUALITY rather than relaxed to
    a subset: `AGG.AXIS_ONLY_KEYS` names each one and the axis that wants it,
    so a key still cannot enter RULES without being accounted for in writing.
    The original direction (readers ⊆ rules) is asserted separately below and
    is exactly as strong as it was."""
    wanted = {key for _, key, _ in TDG.MANUFACTURABILITY + TDG.ELECTRICAL}
    wanted.add("design__die__bbox")          # `TDG.die_geometry` reads this one
    rules = {key for key, _, _ in AGG.RULES}
    assert wanted <= rules, sorted(wanted - rules)
    assert wanted | set(AGG.AXIS_ONLY_KEYS) == rules, {
        "in RULES and accounted for nowhere": sorted(
            rules - wanted - set(AGG.AXIS_ONLY_KEYS)),
        "declared axis-only but not in RULES": sorted(
            set(AGG.AXIS_ONLY_KEYS) - rules),
    }
    assert not (wanted & set(AGG.AXIS_ONLY_KEYS)), (
        "a key the release documents DO read is not axis-only")


def test_every_measured_key_carries_its_source_and_that_files_sha(project):
    import hashlib
    metrics, _ = AGG.aggregate(project)
    for key, entry in metrics["__provenance__"].items():
        if not entry["measured"]:
            continue
        src = project / entry["source"]
        assert src.is_file(), entry["source"]
        assert entry["sha256"] == hashlib.sha256(src.read_bytes()).hexdigest()


def test_drc_keys_are_attributed_by_producer_not_by_filename(project):
    """The router's count must never be written under a sign-off tool's key.

    Swap ONLY the producer strings, leave the filenames alone: the counts must
    follow the producer.
    """
    _write(project / "reports/phase3/drc_router.json", {
        "summary": {"real_violation_total": 3,
                    "producers": [{"producer": "klayout"}]}})
    _write(project / "reports/phase3/drc_signoff.json", {
        "summary": {"real_violation_total": 5,
                    "producers": [{"producer": "openroad"}]}})
    metrics, _ = AGG.aggregate(project)
    assert metrics["klayout__drc_error__count"] == 3
    assert metrics["route__drc_errors"] == 5


def test_a_tool_with_no_report_is_not_zero(project):
    """No magic DRC ran on this fixture, so the magic key states that."""
    metrics, _ = AGG.aggregate(project)
    assert metrics["magic__drc_error__count"] == AGG.NOT_MEASURED
    assert "magic" in metrics["__provenance__"][
        "magic__drc_error__count"]["reason"]


def test_two_reports_claiming_one_tool_is_reported_not_resolved(project):
    _write(project / "reports/phase3/drc_router.json", {
        "summary": {"real_violation_total": 3,
                    "producers": [{"producer": "klayout"}]}})
    metrics, _ = AGG.aggregate(project)
    assert metrics["klayout__drc_error__count"] == AGG.NOT_MEASURED
    assert "contradiction" in metrics["__provenance__"][
        "klayout__drc_error__count"]["reason"]


def test_a_deck_with_no_density_category_yields_no_density_number(project):
    _write(project / "reports/phase3/drc_signoff.json", {
        "summary": {"real_violation_total": 5,
                    "categories_found": ["spacing"],
                    "producers": [{"producer": "klayout"}]}})
    metrics, _ = AGG.aggregate(project)
    assert metrics["klayout__density_error__count"] == AGG.NOT_MEASURED
    # ... and the DRC total is still measured: one absent category does not
    # unmeasure the deck's own violation count.
    assert metrics["klayout__drc_error__count"] == 5


def test_an_lvs_mismatch_is_not_a_count(project):
    _write(project / "reports/phase3/lvs.json",
           {"summary": {"terminal_verdict": "MISMATCH"}})
    metrics, _ = AGG.aggregate(project)
    for key in ("design__lvs_error__count",
                "design__lvs_unmatched_device__count",
                "design__lvs_unmatched_net__count",
                "design__lvs_unmatched_pin__count"):
        assert metrics[key] == AGG.NOT_MEASURED
        assert "MISMATCH" in metrics["__provenance__"][key]["reason"]


def test_an_undeclared_drv_check_is_silence_not_zero(project):
    _write(project / "reports/phase3/sta_spef_based.rpt",
           "SIGNOFF_CHECK_TYPES_REPORTED recovery removal\n")
    metrics, _ = AGG.aggregate(project)
    assert metrics["design__max_slew_violation__count"] == AGG.NOT_MEASURED
    assert metrics["design__max_cap_violation__count"] == AGG.NOT_MEASURED


def test_antenna_over_an_incomplete_route_is_not_a_signoff_count(project):
    _write(project / "reports/phase3/antenna.json",
           {"net_violations": 0, "pin_violations": 0,
            "routing_incomplete": True})
    metrics, _ = AGG.aggregate(project)
    assert metrics["antenna__violating__nets"] == AGG.NOT_MEASURED
    assert metrics["antenna__violating__pins"] == AGG.NOT_MEASURED


def test_a_def_without_units_cannot_be_stated_in_microns(project):
    _write(project / "phase3/stage3/pnr/filled.def",
           "DIEAREA ( 0 0 ) ( 120000 80000 ) ;\n")
    metrics, _ = AGG.aggregate(project)
    assert metrics["design__die__bbox"] == AGG.NOT_MEASURED


# ── the gate clause ─────────────────────────────────────────────────────────
def test_check_passes_on_a_freshly_written_record(project):
    assert AGG.main([str(project)]) == 0
    assert AGG.main([str(project), "--check"]) == 0


def test_check_fails_when_the_record_is_absent(project):
    assert AGG.main([str(project), "--check"]) == 1


def test_check_fails_when_the_record_no_longer_states_what_the_run_states(
        project):
    """A STALE summary is worse than none: the documents built on it look
    current. Re-run the checker with a changed report and --check must refuse."""
    assert AGG.main([str(project)]) == 0
    _write(project / "reports/phase3/antenna.json",
           {"net_violations": 11, "pin_violations": 9,
            "routing_incomplete": False})
    assert AGG.main([str(project), "--check"]) == 1


def test_a_missing_project_is_cannot_check_not_a_pass(tmp_path):
    assert AGG.main([str(tmp_path / "nope")]) == 2


def test_check_same_project_spelling_preserves_native_provenance(
        tmp_path, monkeypatch, capsys):
    """The producer's ABS path and canonical cwd '.' name the same run.

    Actual run_chain/judge own the neutral fixture's receipts. Only the
    external process edge supplies protocol State, not physical signoff.
    """
    from _native_signoff_fixture import finished_producer
    project = tmp_path / "project"
    finished_producer(project, monkeypatch)
    steps = []
    def call(args):
        rc = AGG.main(args)
        output = capsys.readouterr()
        steps.append({"args": args, "rc": rc, "stdout": output.out,
                      "stderr": output.err})
        return rc
    assert call([str(project)]) == 0
    assert call([str(project), "--check"]) == 0
    metrics = project / "phase3/final/metrics.json"
    report = project / AGG.REPORT_REL
    frozen = {str(p.relative_to(project)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in (metrics, report)}
    recorded = json.loads(metrics.read_text())
    assert recorded["__provenance__"]["klayout__density_error__count"]["measured"]
    monkeypatch.chdir(project)
    current, current_report = AGG.aggregate(Path("."))
    rc = call([".", "--check"])
    (tmp_path / "PROJECT_SPELLING_OBSERVATION.json").write_text(json.dumps({
        "steps": steps, "stored_density_provenance": recorded["__provenance__"]["klayout__density_error__count"],
        "relative_density_provenance": current["__provenance__"]["klayout__density_error__count"],
        "stored_report_project": json.loads(report.read_text())["project"],
        "relative_report_project": current_report["project"],
        "metric_values_equal": {k: v for k, v in recorded.items() if k != "__provenance__"}
                               == {k: v for k, v in current.items() if k != "__provenance__"},
    }, indent=2) + "\n")
    assert rc == 0, steps[-1]
    assert call([".", "--check"]) == 0
    assert call([str(project), "--check"]) == 0
    assert frozen == {str(p.relative_to(project)): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in (metrics, report)}


@pytest.mark.parametrize("mutation", ["same_value_new_bytes", "measurement"])
def test_check_still_refuses_changed_measurement_report(project, mutation, capsys):
    assert AGG.main([str(project)]) == 0
    assert AGG.main([str(project), "--check"]) == 0
    source = project / "reports/phase3/antenna.json"
    if mutation == "same_value_new_bytes":
        source.write_text(source.read_text() + "\n")
    else:
        payload = json.loads(source.read_text())
        payload["net_violations"] += 1
        _write(source, payload)
    capsys.readouterr()
    rc = AGG.main([str(project), "--check"])
    output = capsys.readouterr()
    (project.parent / "MEASUREMENT_MUTATION_OBSERVATION.json").write_text(
        json.dumps({"mutation": mutation, "rc": rc, "stdout": output.out,
                    "stderr": output.err}, indent=2) + "\n")
    assert rc == 1
    assert "__provenance__" in output.out


def test_check_still_refuses_changed_native_input(tmp_path, monkeypatch, capsys):
    from _native_signoff_fixture import finished_producer
    project = tmp_path / "project"
    info = finished_producer(project, monkeypatch)
    assert AGG.main([str(project)]) == 0
    assert AGG.main([str(project), "--check"]) == 0
    info["deck"].write_text(info["deck"].read_text() + "changed true source\n")
    capsys.readouterr()
    rc = AGG.main([str(project), "--check"])
    output = capsys.readouterr()
    (tmp_path / "NATIVE_INPUT_MUTATION_OBSERVATION.json").write_text(
        json.dumps({"rc": rc, "stdout": output.out, "stderr": output.err}, indent=2) + "\n")
    assert rc == 1
    assert "__provenance__" in output.out
