"""A PDK native antenna rule must be measured on the delivered GDS."""
from __future__ import annotations

import hashlib
import json
import posixpath
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import gds_antenna_deck_check as gate  # noqa: E402
import eda_report_audit as audit  # noqa: E402
import _watchdog as watchdog  # noqa: E402
import _klayout_launch as launch  # noqa: E402
from test_librelane_contract import local_image  # noqa: E402,F401 — existing neutral LOCAL launch fixture


@pytest.mark.parametrize('scenario', [
    'current', 'wrong_gds', 'missing_native_proof', 'nonzero_native_inconsistency',
    'default_without_switch', 'standalone_clean', 'standalone_dirty'])
def test_retained_native_antenna_reaches_original_consumer(tmp_path, monkeypatch, local_image, scenario):
    """Real chain/receipt and consumer; only the native process edge is neutral."""
    import librelane_contract as contract
    from _native_signoff_fixture import put
    image = local_image.image
    gds = _project(tmp_path)
    root = tmp_path / 'pdk_root'
    tree = root / 'fixture_pdk'
    standalone = scenario.startswith('standalone_')
    if standalone:
        # SOFTWARE_ONLY native-edge fixture, using the installed standalone
        # runset's report/event shape; no native/adoption credit.
        (tree/'libs.tech/klayout/tech/drc/rule_decks/antenna.rb').unlink()
        parent = tree/'libs.tech/klayout/tech/drc/rule_decks/antenna.drc'
        parent.write_text("source($input)\nreport('native report', $report)\nantenna_check(gate, conductor, ratio)\n")
    else:
        parent = tree / 'libs.tech/klayout/tech/drc/main.drc'
    put(tmp_path / 'phase3/librelane_switch.json', {
        'steps': {'26': 'librelane'}, 'image': image,
        'pdk': 'fixture_pdk', 'pdk_root_host': str(root)})
    config = put(tmp_path / 'phase3/librelane/26-config/KLayout.Antenna.json', {
        'meta': {'step': 'KLayout.Antenna'}, 'PDK': 'fixture_pdk',
        'DESIGN_NAME': 'neutral_core', 'KLAYOUT_ANTENNA_RUNSET': str(parent),
        'KLAYOUT_ANTENNA_OPTIONS': {'decks': 'antenna'}})
    initial = put(tmp_path / 'phase3/librelane/native-input-state.json',
                  {'gds': str(gds), 'metrics': {}})
    count = 1 if scenario in ('nonzero_native_inconsistency', 'standalone_dirty') else 0
    calls = []

    def native_process(argv, **kwargs):
        calls.append(argv[argv.index('--id') + 1])
        folder = Path(argv[argv.index('-o') + 1])
        cfg = json.loads(Path(argv[argv.index('-c') + 1]).read_text())
        state = json.loads(Path(argv[argv.index('-i') + 1]).read_text())
        put(folder / 'config.json', cfg); put(folder / 'state_in.json', state)
        put(folder / 'state_out.json', dict(state, metrics={'klayout__antenna_error__count': count}))
        report = folder / 'reports/antenna.klayout.lyrdb'
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(_rdb(count, str(parent)).replace(
            '</generator>', '</generator><top-cell>neutral_core</top-cell>'))
        put(folder / 'reports/antenna.klayout.json', {'ANT.1': count if standalone else 0, 'total': count if standalone else 0})
        command = ['klayout', '-b', '-r', str(parent), '-rd', 'input=' + str(gds),
                   '-rd', 'topcell=neutral_core', '-rd', 'report=' + str(report), '-rd', 'decks=antenna']
        (folder / 'COMMANDS').write_text(shlex.join(command) + '\n')
        return subprocess.CompletedProcess(argv, 0, '2026-10-30: Executing rule Ant.1\n' if standalone else _transcript(command, count), '')

    monkeypatch.setattr(contract, 'image_capability', lambda *a, **k: {})
    monkeypatch.setattr(contract, 'openroad_home', lambda *a, **k: None)
    monkeypatch.setattr(contract, 'run_container', native_process)
    folder = contract.run_chain(tmp_path, image, [('KLayout.Antenna', config, initial)],
        mounts=[(root, '/pdk')], lane='26-gds', pdk_root='/pdk')[0]
    assert json.loads((folder / 'pdk_root.json').read_text())['execution_route'] == 'LOCAL'
    put(tmp_path / 'phase3/librelane_pdk_root.provenance.json', {
        'path': str(root), 'source': 'resolved', 'derivation': {
            'pdk': 'fixture_pdk', 'image': image,
            'image_id': contract.local_image_attestation(image)['image_id'],
            'guest_path': str(tree), 'host_path': str(tree)}})
    put(tmp_path / 'reports/phase3/antenna_librelane.json', {'gds': {
        'step': 'KLayout.Antenna', 'state': str(folder / 'state_out.json'),
        'state_sha256': contract.digest(folder / 'state_out.json'),
        'subject': str(gds), 'subject_sha256': contract.digest(gds),
        'counts': {'klayout__antenna_error__count': count}}})
    monkeypatch.setattr(gate._kl, 'find_container_runner', lambda **k: None)
    monkeypatch.setattr(gate._kl, 'find_runner', lambda **k: None)
    if scenario == 'wrong_gds':
        gds.write_bytes(gds.read_bytes() + b'changed delivered geometry')
    elif scenario == 'missing_native_proof':
        (folder / 'vibeic_receipt.json').unlink()
    report = tmp_path / 'reports/phase2/gates/gate_oxide_geom_deck.json'
    if scenario == 'default_without_switch':
        import flow_compliance_check as audit_gate
        # Ordinary chip-class inputs select the existing Default owner without
        # a legacy implementation switch. They are not native measurement proof.
        (tmp_path / 'phase3/librelane_switch.json').unlink()
        put(tmp_path / 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json',
            {'fields': {'pdk_target': 'fixture_pdk'}})
        route = tmp_path / 'input/submission_template/SELF_TAPEOUT.txt'
        route.parent.mkdir(parents=True)
        route.write_text('SELF_TAPEOUT\n')
        monkeypatch.setenv('VIBEIC_LIBRELANE_IMAGE', image)
        put(report, {'verdict': 'DISCLOSED_SKIP', 'measurement': 'NOT_MEASURED',
                     'reason': 'retained prior consumer report'})
        original = report.read_bytes()
        command = 'gds_antenna_deck_check . --json reports/phase2/gates/gate_oxide_geom_deck.json'
        outcome = audit_gate._check_program_exit_zero(tmp_path, command)
        assert outcome.exit_code == 0, outcome
        assert outcome.structured_verdict == 'PASS', outcome
        assert report.read_bytes() == original
        redirected = Path(audit_gate._RECEIPT_REDIRECTS[audit_gate._resolved_key(report)][0])
        assert redirected != report and redirected.parent.parent == tmp_path / '.vibeic-state/audit_receipts'
        report, rc = redirected, outcome.exit_code
    else:
        rc = gate.main([str(tmp_path), '--json', str(report)])
    result = json.loads(report.read_text())
    (tmp_path/'retained-observed.json').write_text(json.dumps({'rc':rc,'result':result},indent=2))
    if scenario == 'standalone_clean':
        assert result['verdict'] == 'DISCLOSED_SKIP', result
        assert rc == 2 and result['measurement'] == 'NOT_MEASURED'
        assert result['violations'] == 0 and result['coverage_status'] == 'NOT_MEASURED'
    elif scenario == 'standalone_dirty':
        assert rc == 1 and result['verdict'] == 'FAIL', result
        assert result['violations'] == 1
    elif scenario in ('current', 'default_without_switch'):
        assert rc == 0, result
        assert result['verdict'] == 'PASS' and result['violations'] == 0
        assert result['evidence_basis'] == 'retained_KLayout.Antenna'
        assert result['native_evidence']['receipt'] == str(folder / 'vibeic_receipt.json')
        assert result['gds_sha256'] == contract.digest(gds)
        assert result['rdb_sha256'] == gate._sha(folder / 'reports/antenna.klayout.lyrdb')
    elif scenario == 'nonzero_native_inconsistency':
        assert rc == 1 and result['verdict'] == 'FAIL', result
        assert result['violations'] == 1
        assert 'disagree' in result['reason']
    else:
        assert rc == 2 and result['measurement'] == 'NOT_MEASURED', result
    assert calls == ['KLayout.Antenna'], 'the current consumer must not rerun a native producer'


def test_real_native_rdb_calibration_pair():
    samples = PROGRAMS / "calibration"
    dirty = (samples / "native_antenna_violation.lyrdb").read_text()
    clean = (samples / "native_antenna_clean.lyrdb").read_text()
    assert audit._antenna_klayout_count(dirty) == 1
    assert audit._antenna_klayout_count(clean) == 0
    assert "Executing rule ANT.1" in (samples / "native_antenna_violation.log").read_text()
    assert "Executing rule ANT.1" in (samples / "native_antenna_clean.log").read_text()


def _rdb(violations: int, script: str = "/pdk/tech/drc/main.drc") -> str:
    items = "".join("<item><category>ANT.1</category></item>" for _ in range(violations))
    return ("<?xml version='1.0'?><report-database>"
            "<description>Report for antenna_native</description>"
            f"<generator>drc: script='{script}'</generator>"
            "<categories><category><name>ANT.1</name><description>ANT.1: gate ratio"
            "</description></category></categories><items>" + items +
            "</items></report-database>")


def _script(argv) -> str:
    return argv[argv.index("-r") + 1]


def _transcript(argv, violations: int) -> str:
    """The native deck's own transcript shape, as the real tool writes it
    (calibration/native_antenna_*.log): the rule file each deck came from,
    the executed ANT rules, and the completion tally."""
    rule = posixpath.join(posixpath.dirname(_script(argv)), "rule_decks", "antenna.rb")
    tally = ("DRC RESULT: SUCCESS (0 violations)" if violations == 0
             else f"DRC RESULT: FAILURE ({violations} violation(s))")
    return (f"2026-09-28: Executing deck antenna_poly2 from {rule}\n"
            "2026-09-28: Executing rule ANT.1\n"
            f"2026-09-28: {tally}\n")


class NativeRunner:
    kind = "host"

    def __init__(self, violations=0):
        self.violations = violations
        self.argv = None

    def covers(self, path):
        return True

    def cpath(self, path):
        return str(path)

    def klayout_bin(self):
        return "klayout"

    def run_argv(self, argv, env, *, timeout):
        self.argv = argv
        assert "decks=antenna" in argv
        target = Path(next(x.split("=", 1)[1] for x in argv if x.startswith("report=")))
        target.write_text(_rdb(self.violations, _script(argv)))
        return 0, _transcript(argv, self.violations), ""

    def run_argv_supervised(self, argv, env, *, stall_grace_s,
                            memory_limit_mb, progress_paths):
        rc, out, err = self.run_argv(argv, env, timeout=30)
        return watchdog.SupervisedResult(rc, out, err, "natural", 0.1,
                                         supervision={"watched": ["output"]})


def _project(tmp_path, *, deck=True):
    gds_dir = tmp_path / "phase3/stage4/gds"
    gds_dir.mkdir(parents=True)
    (gds_dir / "layout.gds").write_bytes(b"delivered stream geometry")
    root = tmp_path / "pdk_root"
    drc = root / "fixture_pdk/libs.tech/klayout/tech/drc"
    rules = drc / "rule_decks"
    rules.mkdir(parents=True)
    (drc / "main.drc").write_text("decks: $decks\nload rule_decks\n")
    if deck:
        (rules / "antenna.rb").write_text("# original PDK antenna rule\n")
    receipt = tmp_path / "phase3/librelane_pdk_root.provenance.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps({"path": str(root),
                                   "derivation": {"pdk": "fixture_pdk"}}))
    return gds_dir / "layout.gds"


@pytest.mark.parametrize("violations, verdict", [(0, "PASS"), (1, "FAIL")])
def test_native_pdk_deck_runs_and_preserves_violations(tmp_path, monkeypatch,
                                                       violations, verdict):
    gds = _project(tmp_path)
    runner = NativeRunner(violations)
    monkeypatch.setattr(gate._kl, "find_runner", lambda **kw: runner)
    result = gate.run(tmp_path, None, None, None, None)
    assert result["verdict"] == verdict, result
    assert result["violations"] == violations
    assert result["gds_sha256"] == hashlib.sha256(gds.read_bytes()).hexdigest()
    assert result["pdk_rule_sha256"] == hashlib.sha256(
        (tmp_path / "pdk_root/fixture_pdk/libs.tech/klayout/tech/drc/"
         "rule_decks/antenna.rb").read_bytes()).hexdigest()
    assert result["rdb_sha256"] == gate._sha(Path(result["rdb"]))
    assert result["transcript_sha256"] == gate._sha(Path(result["transcript"]))
    assert runner.argv is not None


def test_stale_native_transcript_is_not_measured(tmp_path):
    gds = _project(tmp_path)
    old_sha = hashlib.sha256(b"a different GDS").hexdigest()
    rdb = tmp_path / "report.lyrdb"
    rdb.write_text(_rdb(0))
    log = tmp_path / "report.log"
    log.write_text(gate._BIND_PREFIX + old_sha + "\nExecuting rule ANT.1\n")
    now_sha = gate._sha(gds)
    count, why, _ = gate._bound_native_count(gds, rdb, log, now_sha)
    assert count is None
    assert "another GDS SHA-256" in why


def test_no_pdk_antenna_deck_remains_not_measured(tmp_path):
    _project(tmp_path, deck=False)
    result = gate.run(tmp_path, None, None, None, None)
    assert result["verdict"] == "DISCLOSED_SKIP"
    assert "no native antenna rule deck" in result["reason"]


@pytest.mark.parametrize("bridge_text, reason", [
    ('{"antenna_deck":"missing.json"}', "points at a missing deck"),
    ("{invalid JSON", "is unreadable"),
])
def test_broken_explicit_bridge_cannot_fall_through_to_another_deck(
        tmp_path, monkeypatch, bridge_text, reason):
    _project(tmp_path)
    bridge = tmp_path / "input/pdk/bridge/signoff_config.json"
    bridge.parent.mkdir(parents=True)
    bridge.write_text(bridge_text)
    runner = NativeRunner()
    monkeypatch.setattr(gate._kl, "find_runner", lambda **kw: runner)
    result = gate.run(tmp_path, None, None, None, None)
    assert result["verdict"] == "DISCLOSED_SKIP"
    assert reason in result["reason"]
    assert runner.argv is None


def test_multiple_streams_cannot_select_a_delivered_gds_by_filename(tmp_path,
                                                                     monkeypatch):
    gds = _project(tmp_path)
    gds.with_name("another.gds").write_bytes(b"a different stream")
    runner = NativeRunner()
    monkeypatch.setattr(gate._kl, "find_runner", lambda **kw: runner)
    result = gate.run(tmp_path, None, None, None, None)
    assert result["verdict"] == "DISCLOSED_SKIP"
    assert "multiple streamed GDS" in result["reason"]
    assert runner.argv is None


def test_declared_native_deck_execution_failure_is_not_clean(tmp_path, monkeypatch):
    _project(tmp_path)
    runner = NativeRunner()
    runner.run_argv = lambda *a, **kw: (1, "", "KLayout failed")
    monkeypatch.setattr(gate._kl, "find_runner", lambda **kw: runner)
    result = gate.run(tmp_path, None, None, None, None)
    assert result["verdict"] == "FAIL"
    assert "failed rc=1" in result["reason"]
    assert result["measurement"] == "NOT_MEASURED"


def test_native_clean_rdb_with_unreadable_router_report_cannot_pass(tmp_path,
                                                                    monkeypatch):
    _project(tmp_path)
    report = tmp_path / "reports/phase3/antenna.rpt"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("OpenROAD check_antennas: report truncated before tally\n")
    monkeypatch.setattr(gate._kl, "find_runner", lambda **kw: NativeRunner())
    result = gate.run(tmp_path, None, None, None, None)
    assert result["cross_check"]["verdict"] == "ERROR", result
    assert result["verdict"] == "NOT_MEASURED", result
    assert gate.main([str(tmp_path)]) != 0


def test_native_clean_rdb_with_cross_check_exception_cannot_pass(tmp_path,
                                                                  monkeypatch):
    _project(tmp_path)
    report = tmp_path / "reports/phase3/antenna.rpt"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("Found 0 net violations.\nFound 0 pin violations.\n")
    monkeypatch.setattr(gate._kl, "find_runner", lambda **kw: NativeRunner())
    monkeypatch.setattr(gate, "_load_module", lambda *args: 1 / 0)
    result = gate.run(tmp_path, None, None, None, None)
    assert result["cross_check"]["verdict"] == "ERROR", result
    assert result["verdict"] == "NOT_MEASURED", result


def test_native_progress_continues_past_former_wall_clock(tmp_path, monkeypatch):
    _project(tmp_path)

    class ProgressRunner(NativeRunner):
        def run_argv(self, argv, env, *, timeout):
            return 124, "", "old 1800 second wall-clock timeout"

        def run_argv_supervised(self, argv, env, *, stall_grace_s,
                                memory_limit_mb, progress_paths):
            self.argv = argv
            assert stall_grace_s > 0 and memory_limit_mb > 0
            assert progress_paths
            target = Path(next(x.split("=", 1)[1] for x in argv
                               if x.startswith("report=")))
            target.write_text(_rdb(0, _script(argv)))
            return watchdog.SupervisedResult(
                0, _transcript(argv, 0), "", "natural", 1801.0,
                supervision={"hard_ceiling_exceeded": True})

    runner = ProgressRunner()
    monkeypatch.setattr(gate._kl, "find_runner", lambda **kw: runner)
    result = gate.run(tmp_path, None, None, None, None)
    assert result["verdict"] == "PASS", result
    assert result["execution"]["elapsed_s"] == 1801.0
    assert runner.argv is not None


def test_native_stall_is_incomplete_measurement_not_antenna_failure(tmp_path,
                                                                   monkeypatch):
    _project(tmp_path)

    class StalledRunner(NativeRunner):
        def run_argv(self, argv, env, *, timeout):
            return 124, "", "old 1800 second wall-clock timeout"

        def run_argv_supervised(self, argv, env, *, stall_grace_s,
                                memory_limit_mb, progress_paths):
            return watchdog.SupervisedResult(
                watchdog.RC_STALLED, "partial deck output", "WATCHDOG_STALLED",
                "stalled", 2000.0, supervision={"watched": ["output", "cpu"],
                                                 "since_last_progress_s": 1800.0})

    monkeypatch.setattr(gate._kl, "find_runner", lambda **kw: StalledRunner())
    result = gate.run(tmp_path, None, None, None, None)
    assert result["verdict"] == "NOT_MEASURED", result
    assert result["execution"]["outcome"] == "stalled"
    assert "stall" in result["reason"]


def test_native_cross_check_reads_real_klayout_rdb_dialect(tmp_path, monkeypatch):
    _project(tmp_path)
    report = tmp_path / "reports/phase3/antenna.rpt"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_bytes((PROGRAMS / "calibration/native_antenna_clean.lyrdb").read_bytes())
    monkeypatch.setattr(gate._kl, "find_runner", lambda **kw: NativeRunner())
    result = gate.run(tmp_path, None, None, None, None)
    assert result["verdict"] == "PASS", result
    assert result["cross_check"]["verdict"] == "AGREE", result
    assert result["cross_check"]["router_violations"] == 0


def test_host_native_runner_enforces_memory_and_keeps_progressing():
    runner = launch.HostRunner(sys.executable, ())
    cmd = [sys.executable, "-c", (
        "import resource,time\n"
        "print(resource.getrlimit(resource.RLIMIT_AS)[0], flush=True)\n"
        "end=time.monotonic()+0.8\n"
        "while time.monotonic()<end: pass\n"
    )]
    result = runner.run_argv_supervised(
        cmd, {}, stall_grace_s=0.3, memory_limit_mb=256)
    assert result.outcome == "natural", result
    assert result.rc == 0, result
    assert result.elapsed_s > 0.3
    assert result.out.strip() == str(256 * 1024 * 1024)


# Typed LOCAL PDK records and nullable native options use the original consumer.
def _current_native_antenna_fixture(tmp_path, monkeypatch, *, typed, options, count=0):
    import librelane_contract as contract
    from _native_signoff_fixture import put
    gds = _project(tmp_path)
    root = tmp_path / 'pdk_root'
    source = tmp_path / 'native-source'
    (source / 'librelane').mkdir(parents=True)
    (source / 'librelane/__init__.py').write_text('VERSION = "neutral"\n')
    switch = {'execution_route': 'LOCAL', 'local_network_mode': 'host',
              'steps': {'26': 'librelane'}, 'pdk_root_host': str(root),
              'librelane_root_host': str(source), 'librelane_executable': sys.executable}
    put(tmp_path / 'phase3/librelane_switch.json', switch)
    put(tmp_path / 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json',
        {'fields': {'pdk_target': 'fixture_pdk'}})
    image = contract.resolve_image(tmp_path)
    # The producer's generic runtime has pdk=None; the caller supplies the PDK.
    provenance = contract.pdk_root_resolution(tmp_path, 'fixture_pdk', image=image)
    assert provenance['source'] == 'local_provider'
    assert provenance['provider']['pdk'] is None
    parent = root / 'fixture_pdk/libs.tech/klayout/tech/drc/main.drc'
    config = put(tmp_path / 'phase3/librelane/26-config/KLayout.Antenna.json', {
        'meta': {'step': 'KLayout.Antenna'}, 'PDK': 'fixture_pdk',
        'DESIGN_NAME': 'neutral_core', 'KLAYOUT_ANTENNA_RUNSET': str(parent),
        'KLAYOUT_ANTENNA_OPTIONS': options})
    initial = put(tmp_path / 'phase3/librelane/native-input-state.json',
                  {'gds': str(gds), 'metrics': {}})
    calls = []
    def native_process(argv, **kwargs):
        calls.append(argv[argv.index('--id') + 1])
        folder = Path(argv[argv.index('-o') + 1])
        cfg = json.loads(Path(argv[argv.index('-c') + 1]).read_text())
        state = json.loads(Path(argv[argv.index('-i') + 1]).read_text())
        put(folder / 'config.json', cfg)
        put(folder / 'state_in.json', state)
        put(folder / 'state_out.json', dict(state, metrics={'klayout__antenna_error__count': count}))
        report = folder / 'reports/antenna.klayout.lyrdb'
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(_rdb(count, str(parent)).replace(
            '</generator>', '</generator><top-cell>neutral_core</top-cell>'))
        put(folder / 'reports/antenna.klayout.json', {'ANT.1': count, 'total': count})
        command = ['klayout', '-b', '-r', str(parent), '-rd', 'input=' + str(gds),
                   '-rd', 'topcell=neutral_core', '-rd', 'report=' + str(report), '-rd', 'decks=antenna']
        if isinstance(options, dict):
            command.extend(item for key, value in options.items() if key != 'decks'
                           for item in ('-rd', str(key) + '=' + str(value)))
        (folder / 'COMMANDS').write_text(shlex.join(command) + '\n')
        return subprocess.CompletedProcess(argv, 0, _transcript(command, count), '')
    # These are only native file/process transport leaves; all chain receipts,
    # PDK resolution, discovery, native counts and the final gate remain real.
    monkeypatch.setattr(contract, 'image_capability', lambda *a, **k: {})
    monkeypatch.setattr(contract, 'openroad_home', lambda *a, **k: None)
    monkeypatch.setattr(contract, 'run_container', native_process)
    folder = contract.run_chain(tmp_path, image, [('KLayout.Antenna', config, initial)],
        mounts=[(root, '/pdk')], lane='26-gds', pdk_root='/pdk')[0]
    put(tmp_path / 'reports/phase3/antenna_librelane.json', {'gds': {
        'step': 'KLayout.Antenna', 'state': str(folder / 'state_out.json'),
        'state_sha256': contract.digest(folder / 'state_out.json'),
        'subject': str(gds), 'subject_sha256': contract.digest(gds),
        'counts': {'klayout__antenna_error__count': count}}})
    if not typed:
        # The existing declared-host shape isolates the nullable-options seam.
        put(tmp_path / gate._PDK_ROOT_RECEIPT,
            {'path': str(root), 'source': 'declared', 'pdk': 'fixture_pdk'})
    def no_second_native(**kwargs):
        raise AssertionError('a retained consumer must not launch another native tool')
    monkeypatch.setattr(gate._kl, 'find_runner', no_second_native)
    monkeypatch.setattr(gate._kl, 'find_container_runner', no_second_native)
    report = tmp_path / 'reports/phase2/gates/gate_oxide_geom_deck.json'
    return provenance, folder, calls, report


def test_typed_local_pdk_producer_reaches_retained_native_antenna(tmp_path, monkeypatch):
    provenance, folder, calls, report = _current_native_antenna_fixture(
        tmp_path, monkeypatch, typed=True, options=None)
    rc = gate.main([str(tmp_path), '--json', str(report)])
    result = json.loads(report.read_text())
    print('LOCAL_PDK_ANTENNA_OBSERVATION', json.dumps({'rc': rc, 'result': result}, sort_keys=True))
    assert rc == 0, result
    assert result['verdict'] == 'PASS' and result['violations'] == 0
    assert result['evidence_basis'] == 'retained_KLayout.Antenna'
    assert result['native_evidence']['receipt'] == str(folder / 'vibeic_receipt.json')
    receipt = tmp_path / gate._PDK_ROOT_RECEIPT
    # Missing/changed PDK, root, typed self-binding and source material do not
    # become a host-tree fallback. Each re-read consumes the same real producer.
    mutations = [dict(provenance, pdk=None), dict(provenance, pdk='other_pdk'),
                 dict(provenance, path=str(tmp_path / 'other-root')),
                 dict(provenance, provider=None), dict(provenance, identity='local://unbound')]
    for bad in mutations:
        receipt.write_text(json.dumps(bad))
        assert gate.main([str(tmp_path), '--json', str(report)]) == 2
        refused = json.loads(report.read_text())
        assert refused['verdict'] == 'DISCLOSED_SKIP'
    receipt.write_text(json.dumps(provenance))
    (tmp_path / 'native-source/librelane/__init__.py').write_text('VERSION = "changed"\n')
    assert gate.main([str(tmp_path), '--json', str(report)]) == 2
    assert calls == ['KLayout.Antenna']


def test_retained_native_antenna_nullable_options_preserve_binding_and_red(tmp_path, monkeypatch):
    observed = []
    for name, options, count, expected in [
            ('null', None, 0, 0), ('nonempty', {'decks': 'antenna', 'custom': 'kept'}, 0, 0),
            ('bad_list', [], 0, 2), ('bad_false', False, 0, 2),
            ('bad_string', '', 0, 2), ('measured_red', [], 1, 1)]:
        project = tmp_path / name
        _, folder, calls, report = _current_native_antenna_fixture(
            project, monkeypatch, typed=False, options=options, count=count)
        rc = gate.main([str(project), '--json', str(report)])
        result = json.loads(report.read_text())
        observed.append({'name': name, 'rc': rc, 'verdict': result['verdict'],
                         'reason': result.get('reason')})
        assert rc == expected, result
        assert result['verdict'] == ('PASS' if expected == 0 else 'FAIL' if expected == 1 else 'DISCLOSED_SKIP')
        assert calls == ['KLayout.Antenna']
        if expected == 0:
            assert result['evidence_basis'] == 'retained_KLayout.Antenna'
            assert result['violations'] == 0
            if name == 'nonempty':
                commands = folder / 'COMMANDS'
                commands.write_text(commands.read_text().replace('custom=kept', 'custom=changed'))
                assert gate.main([str(project), '--json', str(report)]) == 2
        elif expected == 1:
            assert result['violations'] == 1 and result['measurement'] == 'FAIL'
        else:
            assert 'not a mapping' in result['reason']
    print('NULLABLE_ANTENNA_OPTIONS_OBSERVATION', json.dumps(observed, sort_keys=True))



def test_bound_native_transcript_preserves_wrapped_deck_event(tmp_path):
    import textwrap
    # Rich may wrap both the event header and the middle of a long path token.
    tree = '/neutral/' + 'long_process_tree_' * 7
    rule = tree + '/libs.tech/klayout/tech/drc/rule_decks/antenna.rb'
    parent = tree + '/libs.tech/klayout/tech/drc/main.drc'
    pieces = textwrap.wrap(rule, width=76, break_long_words=True, break_on_hyphens=False)
    assert len(pieces) >= 2
    header = '2026-01-01 00:00:00 +0000: Memory Usage (100K) : Executing deck\nantenna_poly2 from\n'
    wrapped = '\n'.join(piece.ljust(80) for piece in pieces)
    following = '\n2026-01-01 00:00:01 +0000: Executing rule ANT.1\nDRC RESULT: SUCCESS (0 violations)\n'
    rdb, transcript = tmp_path / 'native.lyrdb', tmp_path / 'invocation.log'
    rdb.write_text(_rdb(0, parent))
    transcript.write_text(header + wrapped + following)
    deck = {'rule': rule, 'parent': parent}
    count, why, hashes = gate._native_result_count(rdb, transcript, deck)
    assert count == 0 and why == '', (count, why)
    assert hashes['transcript_sha256'] == gate._sha(transcript)
    # Do not remove arbitrary whitespace or cross a new log event to recover
    # a matching token; a different or unfinished rule is still refused.
    continuation = '\n'.join(pieces[1:])
    negatives = {
        'unfinished': header + pieces[0] + following,
        'blank_boundary': header + pieces[0] + '\n\n' + continuation + following,
        'new_event': header + pieces[0] + '\n2026-01-01 00:00:01: INFO: another event\n' + continuation + following,
        'mixed_message': header + pieces[0] + '\nINFO: unrelated message\n' + continuation + following,
        'space_in_fragment': header + pieces[0] + '\n' + pieces[1] + ' another-token\n' + '\n'.join(pieces[2:]) + following,
        'different_deck': header + wrapped + '\n2026-01-01: Executing deck other from /other/rule_decks/antenna.rb' + following,
        'changed_wrapped_path': header + wrapped.replace('long_process_tree_', 'different_tree___', 1) + following,
    }
    for name, text in negatives.items():
        transcript.write_text(text)
        count, why, _ = gate._native_result_count(rdb, transcript, deck)
        assert count is None and 'executed decks from' in why, (name, count, why)
    print('WRAPPED_NATIVE_DECK_OBSERVATION', json.dumps({'positive_count': 0, 'negative_cases': list(negatives)}, sort_keys=True))
