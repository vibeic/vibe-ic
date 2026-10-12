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


def _native_path(corner='slow', kind='max'):
    return ('Startpoint: in\nEndpoint: out\nPath Group: clk\n'
            f'Path Type: {kind}\n' + (f'Corner: {corner}\n' if corner else '') +
            '\n  Delay    Time   Description\n'
            '  0.00    0.00 ^ in (in)\n'
            '  0.50    0.50 ^ u1/Z (BUF)\n'
            '  0.50    1.00 ^ u2/Z (BUF)\n'
            '  1.00    1.00 data arrival time\n'
            '  2.00 slack (MET)\n')


def _production_basis_stamp() -> str:
    """The basis line `_emit_spef_sta` really writes, read out of its source.

    `phase3_one_shot_runner` builds that report's Tcl inline, so there is no
    builder to call; the literal `puts` is the production statement and is what
    this reads. Returns it as the report line it produces.
    """
    import re as _re
    import phase3_one_shot_runner as _runner
    src = Path(_runner.__file__).read_text(encoding='utf-8')
    m = _re.search(r'puts \$_bf \\"(STA_BASIS: [A-Z_]+)\\"', src)
    assert m, ("no production `STA_BASIS` stamp found in phase3_one_shot_runner "
               "— the fixture must not invent one")
    return m.group(1) + "\n"


def _emit_bound_report(tmp_path, raw, stanza=_CORNER_LIBS):
    import inspect
    import phase3_one_shot_runner as runner
    pnr = tmp_path / 'phase3/stage3/pnr'
    pnr.mkdir(parents=True, exist_ok=True)
    kw = {n: '' for n, p in inspect.signature(runner._build_pnr_tcl_text).parameters.items()
          if p.default is inspect.Parameter.empty}
    kw.update(tech_lef_c='/pdk/tech.lef', cell_lef_c='/pdk/core.lef',
              liberty_c='/pdk/typ.lib', top='chip', netlist_c='/work/chip.v',
              metal_prefix='M', die_w=100, die_h=100, core_pad=10,
              core_w=80, core_h=80, site='unit', util=0.4,
              out_dir_c=str(pnr), corner_liberty_block=stanza,
              macro_libs_tcl='read_liberty /pdk/io.lib')
    full = runner._build_pnr_tcl_text(**kw)
    start = full.index('\nreport_checks ', full.index('\nwrite_verilog '))
    end = full.index('\nreport_design_area ', start)
    tail = full[start:end]
    # Tcl primitives perform real file IO. Only OpenSTA report generation is
    # replaced with neutral, input-derived report bytes.
    # R-0915-166 — THE BASIS LINE COMES FROM THE PRODUCER THAT REALLY WRITES
    # IT, not from this fixture. Round 1 prepended `STA_BASIS: POST_ROUTE_SPEF`
    # by hand, which modelled a `pnr/sta.rpt` production never writes: that
    # writer stamps STA_BASIS_LIBERTY and no STA_BASIS (run23's own
    # phase3/stage3/pnr/sta.rpt is exactly that). The stamp is taken out of
    # `_emit_spef_sta`'s source — the post-route SPEF emitter that does stamp it
    # — so if production ever stops, `test_the_basis_stamp_is_productions_own`
    # goes red instead of this fixture quietly inventing a reachable path.
    (tmp_path / 'native.rpt').write_text(_production_basis_stamp() + raw)
    script = tmp_path / 'writer.tcl'
    script.write_text('proc report_checks {args} {\n'
                      ' set f [open native.rpt r]; set text [read $f]; close $f\n'
                      ' set f [open [lindex $args end] w]; puts -nonewline $f $text; close $f\n'
                      '}\n' + tail + '\nputs WRITER_COMPLETE\n')
    result = subprocess.run(['tclsh', str(script)], cwd=tmp_path,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'WRITER_COMPLETE' in result.stdout, result.stderr
    return pnr / 'sta.rpt'


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
    rpt = _emit_bound_report(p, _native_path(corner), stanza)
    assert 'STA_PARASITICS_PROVENANCE: PNR_SESSION_UNVERIFIED' in rpt.read_text()
    assert SCC.parse_sta_corner_basis(rpt.read_text())['liberty'] == expected
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
    assert SCC._pick_sta_report(p, {'BUF'}) is None
    assert rpt.is_file()


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
    assert 'CURRENT_STAPOSTPNR_CORNER_LIBRARY_UNBOUND' in result['reason']
    assert len(calls) == 1, 'the unbound addition must stop before a second native invocation'


@pytest.mark.parametrize('case', ['missing-corner', 'unknown-corner', 'contradictory-corner',
    'conflicting-libraries', 'multiple-bare-libraries', 'hold-path', 'unreadable-library',
    'first-unbound-later-valid', 'missing-path-type', 'unknown-read-syntax'])
def test_writer_binding_refusals(tmp_path, monkeypatch, case):
    import test_default_si_spice_power as fixture
    p, folder, lib, calls = _current_binding_fixture(tmp_path, monkeypatch)
    stanza = _CORNER_LIBS
    raw = _native_path()
    record_path = p / fixture.LP.STEP23_RECORD
    record = json.loads(record_path.read_text())
    log = folder / 'slow/sta.log'
    expected = 'CURRENT_STEP30_CORNER_MISSING'
    if case == 'missing-corner':
        raw = _native_path('')
        record['judgment']['worst_setup'].pop('corner')
    elif case == 'unknown-corner':
        raw = _native_path('unloaded')
        record['judgment']['worst_setup']['corner'] = 'unloaded'
        expected = 'LL_CORNER_NOT_ANALYSED'
    elif case == 'contradictory-corner':
        raw = raw.replace('Corner: slow', 'Corner: slow\nCorner: quick')
        log.write_text(log.read_text().replace("'slow' corner", "'quick' corner"))
        expected = 'LL_CORNER_LIBRARY_UNREAD'
    elif case == 'conflicting-libraries':
        stanza += '\nread_liberty -corner slow /pdk/other.lib'
        with log.open('a') as f:
            f.write("Reading cell library for the 'slow' corner at '/pdk/neutral/other.lib'\n")
        expected = 'CURRENT_STAPOSTPNR_CORNER_LIBRARY_UNBOUND'
    elif case == 'multiple-bare-libraries':
        stanza = 'read_liberty /pdk/one.lib\nread_liberty /pdk/two.lib'
        raw = _native_path('')
        record['judgment']['worst_setup'].pop('corner')
        record['judgment']['available_libraries'] = ['one.lib', 'two.lib']
    elif case == 'hold-path':
        raw = _native_path('quick', 'min')
        record['judgment']['worst_hold'] = record['judgment'].pop('worst_setup')
    elif case == 'unreadable-library':
        lib.unlink()
        expected = 'slow.lib'
    elif case == 'first-unbound-later-valid':
        raw = _native_path('') + '\n' + _native_path('slow')
        record['judgment']['worst_setup'].pop('corner')
        record['judgment']['later_setup'] = {'corner': 'slow'}
    elif case == 'missing-path-type':
        raw = raw.replace('Path Type: max\n', '')
        record['judgment']['untyped_path'] = record['judgment'].pop('worst_setup')
    elif case == 'unknown-read-syntax':
        stanza += '\nsource /pdk/extra-libs.tcl'
        log.write_text('SOURCE_FIXTURE_ONLY\nsource /pdk/neutral/extra-libs.tcl\n')
        expected = 'LL_CORNER_LIBRARY_UNREAD'
    rpt = _emit_bound_report(p, raw, stanza)
    fixture.put(record_path, record)
    # Re-seal only substituted tool output after constructing this scenario.
    # Original input-library hashes remain unchanged, including the unreadable one.
    fixture.seal(folder, json.loads((folder / 'input_fingerprint.json').read_text()))
    result = _consume_current_binding(p)
    _assert_unmeasured_current_refusal(p, result)
    assert expected in result['reason'], (case, result)
    assert calls == [], 'invalid current corner material must not launch native work'
    assert rpt.is_file() and 'PNR_SESSION_UNVERIFIED' in rpt.read_text()
    if 'STA_CORNER_BINDING_REFUSED' in rpt.read_text():
        assert not SCC.parse_sta_corner_basis(rpt.read_text())['liberty']


# ── R-0915-154: the in-session report is never a correlation source ────────

def test_the_in_session_report_is_never_picked_and_the_refusal_says_why(
        tmp_path, monkeypatch):
    import test_default_si_spice_power as fixture
    p, folder, lib, calls = _current_binding_fixture(tmp_path, monkeypatch)
    rpt = _emit_bound_report(p, _native_path('slow'))
    assert 'STA_PARASITICS_PROVENANCE: PNR_SESSION_UNVERIFIED' in rpt.read_text()
    assert SCC._pick_sta_report(p, {'BUF'}) is None
    record_path = p / fixture.LP.STEP23_RECORD
    record = json.loads(record_path.read_text())
    record_path.unlink()
    result = _consume_current_binding(p)
    _assert_unmeasured_current_refusal(p, result)
    assert 'LL_STAPOSTPNR_STATE_ABSENT' in result['reason'], result
    assert 'PNR_SESSION_UNVERIFIED' in result['reason'], result
    assert 'phase3/stage3/pnr/sta.rpt' in result['reason'], result
    assert calls == [] and rpt.is_file()
    # Restoring the actual current declaration reaches the native boundary.
    # Its unrelated transport refusal must not blame the retained PnR report.
    fixture.put(record_path, record)
    current = _consume_current_binding(p)
    _assert_unmeasured_current_refusal(p, current)
    assert current['reason'].startswith('SOURCE_FIXTURE_ONLY_NATIVE_TRANSPORT_NOT_RUN:')
    assert 'PNR_SESSION_UNVERIFIED' not in current['reason']
    assert len(calls) == 1 and rpt.is_file()


def test_without_the_stamp_the_same_report_is_still_a_source(tmp_path):
    """The other direction: the line is what excludes it, not the location."""
    rpt = _emit_bound_report(tmp_path, _native_path('slow'))
    rpt.write_text(''.join(l for l in rpt.read_text().splitlines(True)
                           if 'PNR_SESSION_UNVERIFIED' not in l))
    assert SCC._pick_sta_report(tmp_path, {'BUF'}) == rpt


def test_writer_sections_preserve_path_order_and_scope(tmp_path):
    raw = _native_path('quick') + '\n' + _native_path('slow')
    rpt = _emit_bound_report(tmp_path, raw)
    text = rpt.read_text()
    first = SCC.parse_sta_corner_basis(text)
    assert first['liberty'] == '/pdk/fast.lib'
    assert first['sections'] == 2
    assert first['declared_liberties_in_file'] == ['/pdk/fast.lib', '/pdk/slow.lib']
    assert '/pdk/io.lib' in text
    assert text.count('Startpoint: in') == 2
    assert text.index('Corner: quick') < text.index('Corner: slow')


def test_the_basis_stamp_is_productions_own(tmp_path):
    """R-0915-166 — the fixture may not invent a reachable path.

    The basis line these cases rely on must be one a shipped producer writes.
    If `_emit_spef_sta` stops stamping it, this fails here rather than leaving
    13 cases exercising a report shape production cannot emit."""
    stamp = _production_basis_stamp().strip()
    assert stamp == "STA_BASIS: POST_ROUTE_SPEF", stamp
    assert SCC.is_post_route_spef_basis(stamp + "\n") is True
    # ...and the OTHER writer, the one these cases' bodies come from, really
    # does NOT stamp it — which is why round 1's hand-written line was wrong.
    import phase3_one_shot_runner as runner
    import inspect
    pnr_src = inspect.getsource(runner._build_pnr_tcl_text)
    assert "STA_BASIS:" not in pnr_src, (
        "the PnR writer now stamps a basis; this fixture's reasoning needs "
        "re-deriving")
