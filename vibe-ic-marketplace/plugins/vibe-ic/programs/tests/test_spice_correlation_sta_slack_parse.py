#!/usr/bin/env python3
"""Regression: spice_correlation_check STA-slack parser must not crash on a
report separator dash line, and must read the OpenROAD ``report_checks`` slack
value in EITHER column order.

ROOT CAUSE this guards (real spm / commercial PDK sign-off, Post-Layout SPICE
Verification / Step 30): the pre-fix slack regex was
``slack\\s*\\(?\\w*\\)?\\s+([-\\d.]+)`` — its ``\\s+`` swallowed the newline after
``slack (MET)`` and its ``[-\\d.]+`` class then matched the following run of
``----`` separator dashes; ``float("----...")`` raised ``ValueError`` and
aborted the entire gate, which cascade-blocked Steps 31/32/34/35/36/37 of the
completion audit. It ALSO never captured the real OpenROAD slack, whose value
sits BEFORE the word ``slack`` (``5.55   slack (MET)``), not after it.

Everything here is SYNTHETIC report text — no chip / PDK / vendor literal, no
hard-coded golden path — so the guard is chip-AGNOSTIC.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "spice_correlation_check.py"


def _load_module():
    # A path-loaded parser fixture must not replace the module used by the
    # real runner and its producer controls during the same suite collection.
    spec = importlib.util.spec_from_file_location("_spice_correlation_slack_fixture", PROG)
    mod = importlib.util.module_from_spec(spec)
    # Register before exec so @dataclass can resolve cls.__module__ in sys.modules.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


SCC = _load_module()


# An OpenROAD `report_checks` post-route report: the slack VALUE precedes the
# word "slack", and a run of separator dashes follows the block (the exact
# shape that crashed the pre-fix parser).
_OPENROAD_STA = """\
Startpoint: _100_ (rising edge-triggered flip-flop clocked by clk)
Endpoint: _200_ (rising edge-triggered flip-flop clocked by clk)
Path Group: clk
Path Type: max

  Delay    Time   Description
---------------------------------------------------------
   0.00    0.00   clock clk (rise edge)
   4.20    4.20   data arrival time
  -0.22    9.78   library setup time
           5.55   slack (MET)
---------------------------------------------------------

tns max 0.00
wns max 0.00
worst slack max 5.55
"""

# The "value-after" column order some OpenSTA prints use (and the shape the
# pre-existing tests exercise) — must keep working.
_STA_VALUE_AFTER = """\
Startpoint: ff1
Endpoint: ff2
Path Delay       5.0
slack (MET)      0.5
"""


def _write_sta(tmp_path: Path, text: str) -> Path:
    d = tmp_path / "phase3" / "stage3" / "sta"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "post_route_timing.rpt"
    p.write_text(text)
    return p


def test_safe_float_rejects_dash_run():
    # The exact token that used to reach float() and raise ValueError.
    assert SCC._safe_float("--------------------------------------------") is None
    assert SCC._safe_float("MET") is None
    assert SCC._safe_float("") is None
    assert SCC._safe_float("5.55") == 5.55
    assert SCC._safe_float("-0.22") == -0.22
    assert SCC._safe_float("1.2e-9") == pytest.approx(1.2e-9)


def test_openroad_report_does_not_crash_and_parses(tmp_path):
    _write_sta(tmp_path, _OPENROAD_STA)
    # Pre-fix this raised ValueError on the '----' separator line.
    paths = SCC._extract_sta_worst_paths(tmp_path)
    assert len(paths) == 1
    # `data arrival time 4.20` is the worst delay the correlator consumes.
    assert paths[0]["delay_ns"] == pytest.approx(4.20)
    # Slack read from the value-BEFORE-"slack" column (and the wns/worst summary
    # lines); worst (min) slack is the setup wns 0.00.
    assert paths[0]["slack_ns"] == pytest.approx(0.00)


def test_value_after_slack_form_still_parses(tmp_path):
    _write_sta(tmp_path, _STA_VALUE_AFTER)
    paths = SCC._extract_sta_worst_paths(tmp_path)
    assert len(paths) == 1
    assert paths[0]["delay_ns"] == pytest.approx(5.0)
    assert paths[0]["slack_ns"] == pytest.approx(0.5)


def test_dash_separator_never_becomes_a_slack(tmp_path):
    # A report that is ONLY a header + separator + a bare "slack (VIOLATED)"
    # with no numeric column must yield no spurious slack and must not raise.
    _write_sta(
        tmp_path,
        "Path Delay       3.0\n"
        "------------------------------------\n"
        "slack (VIOLATED)\n"
        "------------------------------------\n",
    )
    paths = SCC._extract_sta_worst_paths(tmp_path)
    assert len(paths) == 1
    assert paths[0]["delay_ns"] == pytest.approx(3.0)
    # No numeric slack present -> falls back to 0.0, never the dash run.
    assert paths[0]["slack_ns"] == pytest.approx(0.0)


def test_end_to_end_gate_does_not_crash_on_openroad_report(tmp_path):
    """Full CLI with SPEF + SPICE deck/result + OpenROAD STA present so the
    critical-path CORRELATION branch (which calls _extract_sta_worst_paths)
    actually runs — the exact path that ABORTED pre-fix. The regression
    guarantee is that the process never crashes on the '----' separator: no
    Traceback, no float()-ValueError, and a parseable JSON is still written.
    (The pass/fail verdict itself depends on correlation policy and is not the
    subject of this guard.)"""
    ex = tmp_path / "phase3" / "stage3" / "extracted"
    ex.mkdir(parents=True, exist_ok=True)
    (ex / "parasitic.spef").write_text(
        "*SPEF \"IEEE 1481-1998\"\n*DESIGN \"t\"\n*D_NET n1 0.001\n*END\n"
    )
    sp = tmp_path / "phase3" / "stage3" / "spice"
    sp.mkdir(parents=True, exist_ok=True)
    (sp / "path.sp").write_text("* critical path deck\n.end\n")
    (sp / "path.log").write_text("tpd_max = 4.5e-9\n")
    _write_sta(tmp_path, _OPENROAD_STA)
    out = tmp_path / "report.json"
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--json", str(out)],
        capture_output=True, text=True,
    )
    assert "Traceback" not in r.stderr, r.stderr
    assert "could not convert string to float" not in r.stderr, r.stderr
    rpt = json.loads(out.read_text())
    assert "summary" in rpt

# SPM1130: exercise the actual PnR writer tail in a Tcl interpreter, then
# the current State/receipt corner consumer. No STA or SPICE is launched.
_CORNER_LIBS = ('define_corners nominal quick slow\n'
                'read_liberty -corner nominal /pdk/typ.lib\n'
                'read_liberty -corner quick /pdk/fast.lib\n'
                'read_liberty -corner slow /pdk/slow.lib')








def _current_binding_fixture(tmp_path, monkeypatch, *, corner='slow', liberty_name='slow.lib'):
    """Use the current producer's real State/receipt input contract.

    Native transport stops explicitly after current binding and actual Tcl
    construction. These source controls provide no STA/SPICE/IC PASS credit.
    """
    import test_default_si_spice_power as fixture
    LC, PST = fixture.LC, fixture.PST
    p, folder, lib = fixture.project(tmp_path, corner=corner, liberty_name=liberty_name)
    fixture.write(p / 'fixture_pdk/neutral/libs.tech/ngspice/model.sp',
                  '.model neutral nmos level=1\n')
    fixture.write(p / 'fixture_pdk/neutral/libs.tech/magic/neutral.magicrc',
                  '# SOURCE_FIXTURE_ONLY\n')
    fixture.write(p / 'fixture_pdk/neutral/libs.tech/librelane/config.tcl',
                  '# SOURCE_FIXTURE_ONLY\n')
    monkeypatch.setattr(LC, 'resolve_image', lambda *_a, **_k: fixture.BF.IMAGE)
    monkeypatch.setattr(LC, 'pdk_root_resolution', lambda *_a, **_k: {
        'path': str(p / 'fixture_pdk')})
    calls = []
    def stopped_transport(project, image, root, pdk, **_kwargs):
        subject, context = PST.current_context(project, image, root, pdk)
        inputs = LC.post_pnr_timing_inputs(project, folder / 'state_out.json', context['corner'])
        script = PST.arm_tcl(inputs, project, 'neutral', str(project / inputs['spef']),
                            ('neutral_fixture', 'typ'), [PST.REG_TO_REG],
                            project / 'SOURCE_FIXTURE_ONLY', 'fixture_cells.sp',
                            'fixture_models.sp', 'VDD', 'VSS', 'ngspice')
        calls.append({'subject': subject, 'context': context, 'inputs': inputs, 'script': script})
        raise LC.Refusal('SOURCE_FIXTURE_ONLY_NATIVE_TRANSPORT_NOT_RUN',
                         'current binding observed; no native simulator launched')
    monkeypatch.setattr(PST, 'run_step30', stopped_transport)
    return p, folder, lib, calls


def _consume_current_binding(project):
    # The active Liberty hint must not override the corner owned by Step23.
    return SCC.run_installed_pdk_path_correlation(
        project, '/pdk/neutral/typ.lib', container='SOURCE_FIXTURE_ONLY')


def _assert_unmeasured_current_refusal(project, result):
    assert result['status'] == 'ERROR', result
    assert result['measurement'] == 'NOT_MEASURED', result
    assert not (project / 'reports/phase3/spice_correlation.current.json').exists()
    gate = SCC.run_audit(project, run_spice=False)
    assert not gate.passed and gate.summary['measurement'] == 'NOT_MEASURED'
    assert SCC.main([str(project), '--no-spice', '--json', str(project / 'fixture-gate.json')]) == 1


@pytest.mark.parametrize('corner,stanza,expected', [
    ('slow', _CORNER_LIBS, '/pdk/slow.lib'),
    ('quick', _CORNER_LIBS, '/pdk/fast.lib'),
    ('', None, '/pdk/typ.lib'),
], ids=['setup-slow-not-active-typ', 'setup-fast-not-label-assumption', 'single-corner'])
def test_writer_binds_actual_selected_path(tmp_path, monkeypatch, corner, stanza, expected):
    p, folder, lib, calls = _current_binding_fixture(
        tmp_path, monkeypatch, corner=corner or 'nominal', liberty_name=Path(expected).name)
    result = _consume_current_binding(p)
    _assert_unmeasured_current_refusal(p, result)
    assert result['reason'].startswith('SOURCE_FIXTURE_ONLY_NATIVE_TRANSPORT_NOT_RUN:'), result
    assert len(calls) == 1
    observed = calls[0]
    assert observed['context']['corner'] == (corner or 'nominal')
    guest = '/pdk/neutral/' + Path(expected).name
    assert observed['inputs']['liberties'] == [guest]
    assert [row['path'] for row in observed['subject']['inputs']
            if row['role'].startswith('liberty:')] == [str(lib)]
    assert 'read_liberty ' + guest + '\n' in observed['script']
    assert 'report_checks -path_delay max ' in observed['script']
    assert 'write_path_spice -path_args {-path_delay max ' in observed['script']
    assert 'read_spef ' + str(p / observed['inputs']['spef']) + '\n' in observed['script']
    # A PnR-session report stays ineligible; no fixture removes its stamp.


def test_current_corner_accepts_bound_libraries_and_refuses_an_unbound_addition(tmp_path, monkeypatch):
    import test_default_si_spice_power as fixture
    p, folder, lib, calls = _current_binding_fixture(tmp_path, monkeypatch)
    aux = fixture.write(lib.parent / 'aux.lib',
                        'library(neutral_aux) { default_operating_conditions: typ; }\n')
    guest = '/pdk/neutral/aux.lib'
    config_path = p / 'phase3/librelane/22-config/OpenROAD.STAPostPNR.json'
    config = json.loads(config_path.read_text())
    config['CELL_LIBS']['*'].append(guest)
    fixture.put(config_path, config)
    fixture.put(folder / 'config.json', config)
    fp = json.loads((folder / 'input_fingerprint.json').read_text())
    fp['config'] = fixture.LC.digest(config_path)
    fp['config_files'][guest] = fixture.LC.digest(aux)
    fp['liberty_files'][guest] = fixture.LC.digest(aux)
    log = folder / 'slow/sta.log'
    with log.open('a') as f:
        f.write("Reading cell library for the 'slow' corner at '" + guest + "'\n")
    fixture.seal(folder, fp)
    result = _consume_current_binding(p)
    _assert_unmeasured_current_refusal(p, result)
    assert result['reason'].startswith('SOURCE_FIXTURE_ONLY_NATIVE_TRANSPORT_NOT_RUN:')
    assert len(calls) == 1 and calls[0]['inputs']['liberties'] == ['/pdk/neutral/slow.lib', guest]
    assert [row['path'] for row in calls[0]['subject']['inputs']
            if row['role'].startswith('liberty:')] == [str(lib), str(aux)]
    assert 'read_liberty ' + guest + '\n' in calls[0]['script']
    with log.open('a') as f:
        f.write("Reading cell library for the 'slow' corner at '/pdk/neutral/unbound.lib'\n")
    fixture.seal(folder, fp)
    result = _consume_current_binding(p)
    _assert_unmeasured_current_refusal(p, result)
    assert 'unbound.lib' in result['reason']
    assert len(calls) == 1, 'the unbound addition must stop before a second native invocation'


@pytest.mark.parametrize('case', ['missing-corner', 'unknown-corner', 'contradictory-corner',
    'conflicting-libraries', 'multiple-bare-libraries', 'hold-path', 'unreadable-library',
    'first-unbound-later-valid', 'missing-path-type', 'unknown-read-syntax'])
def test_writer_binding_refusals(tmp_path, monkeypatch, case):
    import test_default_si_spice_power as fixture
    p, folder, lib, calls = _current_binding_fixture(tmp_path, monkeypatch)
    state_path = folder / 'state_out.json'
    state = json.loads(state_path.read_text())
    setup_key = 'timing__setup__ws__corner:slow'
    log = folder / 'slow/sta.log'
    expected = 'LL_STEP30_CORNER_UNDECLARED'
    if case == 'missing-corner':
        state['metrics'].pop(setup_key)
    elif case == 'unknown-corner':
        state['metrics'] = {'timing__setup__ws__corner:unloaded': 1.0}
    elif case == 'contradictory-corner':
        log.write_text(log.read_text().replace("'slow' corner", "'quick' corner"))
        expected = 'LL_CORNER_LIBRARY_UNREAD'
    elif case == 'conflicting-libraries':
        with log.open('a') as f:
            f.write("Reading cell library for the 'slow' corner at '/pdk/neutral/other.lib'\n")
        expected = 'other.lib'
    elif case == 'multiple-bare-libraries':
        state['metrics'].pop(setup_key)
    elif case == 'hold-path':
        state['metrics'] = {'timing__hold__ws__corner:slow': 1.0}
    elif case == 'unreadable-library':
        lib.unlink()
        expected = 'slow.lib'
    elif case == 'first-unbound-later-valid':
        state['metrics']['timing__setup__ws__corner:unloaded'] = -1.0
    elif case == 'missing-path-type':
        state['metrics'].pop(setup_key)
    elif case == 'unknown-read-syntax':
        log.write_text('SOURCE_FIXTURE_ONLY\nsource /pdk/neutral/extra-libs.tcl\n')
        expected = 'LL_CORNER_LIBRARY_UNREAD'
    fixture.put(state_path, state)
    # Re-seal only substituted tool output after constructing this scenario.
    # Original input-library hashes remain unchanged, including the unreadable one.
    fixture.seal(folder, json.loads((folder / 'input_fingerprint.json').read_text()))
    result = _consume_current_binding(p)
    _assert_unmeasured_current_refusal(p, result)
    assert expected in result['reason'], (case, result)
    assert calls == [], 'invalid current corner material must not launch native work'


# ── R-0915-154: the in-session report is never a correlation source ────────

def test_the_in_session_report_is_never_picked_and_the_refusal_says_why(
        tmp_path, monkeypatch):
    import test_default_si_spice_power as fixture
    p, folder, lib, calls = _current_binding_fixture(tmp_path, monkeypatch)
    state_path = folder / 'state_out.json'
    state = json.loads(state_path.read_text())
    state_path.unlink()
    result = _consume_current_binding(p)
    _assert_unmeasured_current_refusal(p, result)
    assert 'LL_STATE_FILE_MISSING' in result['reason'], result
    assert 'state_out.json' in result['reason'], result
    assert calls == []
    # Restoring the actual current declaration reaches the native boundary.
    # Its unrelated transport refusal must not blame the retained PnR report.
    fixture.put(state_path, state)
    current = _consume_current_binding(p)
    _assert_unmeasured_current_refusal(p, current)
    assert current['reason'].startswith('SOURCE_FIXTURE_ONLY_NATIVE_TRANSPORT_NOT_RUN:')
    assert 'PNR_SESSION_UNVERIFIED' not in current['reason']
    assert len(calls) == 1
