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
# the actual selected-report/corner consumer. No STA or SPICE is launched.
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


def _attested_copy(tmp_path, rpt):
    """The writer's bytes WITHOUT its `PNR_SESSION_UNVERIFIED` line, placed
    where attested sign-off STA lives, and the in-session original removed.

    R-0915-154: the in-session `pnr/sta.rpt` is never a correlation source, so
    the consumer half of these writer tests can no longer run on it. What they
    test -- that the path is bound to the corner the WRITER chose, and that the
    consumer correlates at that corner or refuses -- is unchanged, and it is
    run on the same bytes minus exactly the one line that makes a report
    ineligible. The line itself is asserted on the original before removal.
    """
    text = rpt.read_text()
    assert 'STA_PARASITICS_PROVENANCE: PNR_SESSION_UNVERIFIED' in text
    sta_dir = SCC._pl.sta_dir(tmp_path)
    sta_dir.mkdir(parents=True, exist_ok=True)
    out = sta_dir / 'sta_bound_attested.rpt'
    out.write_text(''.join(l for l in text.splitlines(True)
                           if 'PNR_SESSION_UNVERIFIED' not in l))
    rpt.unlink()
    return out


def _consume_binding(tmp_path, monkeypatch, unreadable=''):
    pnr = tmp_path / 'phase3/stage3/pnr'
    _net = pnr / 'chip_pnr.v'
    _net.write_text('module chip(input a, output z); BUF u1 (.A(a), .Z(z)); endmodule\n')
    # R-0915-166 — PRODUCTION ORDER: route first, THEN time it. These fixtures
    # emit the report before this helper runs, so the netlist would otherwise be
    # NEWER than the STA that timed it and the freshness rule would (correctly)
    # call the report a previous layout's. Backdated so the fixture models the
    # order a real run has, and the cases keep measuring CORNER BINDING.
    import os as _os
    _rpt_t = max((f.stat().st_mtime for f in tmp_path.rglob('*.rpt')),
                 default=_net.stat().st_mtime)
    _os.utime(_net, (_rpt_t - 60, _rpt_t - 60))
    extracted = SCC._pl.extracted_dir(tmp_path)
    extracted.mkdir(parents=True, exist_ok=True)
    (extracted / 'chip.spef').write_text('*SPEF "IEEE 1481-1998"\n')
    monkeypatch.setattr(SCC, '_resolve_ngspice', lambda *_: '/never-launched/ngspice')
    monkeypatch.setattr(SCC, '_read_container_text', lambda _, path: '' if path == unreadable else 'library (fixture) {}')
    monkeypatch.setattr(SCC, 'discover_installed_pdk_sources', lambda *args: {'subckt_names': {'BUF'}})
    # Stop AFTER actual report selection + corner validation. No simulator,
    # deck, tolerance or signoff PASS is fabricated by these CPU fixtures.
    monkeypatch.setattr(SCC, 'resolve_path_stages', lambda *args: None)
    return SCC.run_installed_pdk_path_correlation(tmp_path, '/pdk/typ.lib', container='fixture')


@pytest.mark.parametrize('corner,stanza,expected', [
    ('slow', _CORNER_LIBS, '/pdk/slow.lib'),
    ('quick', _CORNER_LIBS, '/pdk/fast.lib'),
    ('', None, '/pdk/typ.lib'),
], ids=['setup-slow-not-active-typ', 'setup-fast-not-label-assumption', 'single-corner'])
def test_writer_binds_actual_selected_path(tmp_path, monkeypatch, corner, stanza, expected):
    rpt = _emit_bound_report(tmp_path, _native_path(corner), stanza)
    assert 'STA_PARASITICS_PROVENANCE: PNR_SESSION_UNVERIFIED' in rpt.read_text()
    rpt = _attested_copy(tmp_path, rpt)
    result = _consume_binding(tmp_path, monkeypatch)
    assert result['reason'] == 'critical path not stitchable', result
    assert SCC._pick_sta_report(tmp_path, {'BUF'}) == rpt
    assert SCC.parse_sta_corner_basis(rpt.read_text())['liberty'] == expected


@pytest.mark.parametrize('case', ['missing-corner', 'unknown-corner', 'contradictory-corner',
    'conflicting-libraries', 'multiple-bare-libraries', 'hold-path', 'unreadable-library',
    'first-unbound-later-valid', 'missing-path-type', 'unknown-read-syntax'])
def test_writer_binding_refusals(tmp_path, monkeypatch, case):
    stanza = _CORNER_LIBS
    raw = _native_path()
    unreadable = ''
    if case == 'missing-corner': raw = _native_path('')
    if case == 'unknown-corner': raw = _native_path('unloaded')
    if case == 'contradictory-corner': raw = raw.replace('Corner: slow', 'Corner: slow\nCorner: quick')
    if case == 'conflicting-libraries': stanza += '\nread_liberty -corner slow /pdk/other.lib'
    if case == 'multiple-bare-libraries':
        stanza = 'read_liberty /pdk/one.lib\nread_liberty /pdk/two.lib'; raw = _native_path('')
    if case == 'hold-path': raw = _native_path('quick', 'min')
    if case == 'unreadable-library': unreadable = '/pdk/slow.lib'
    if case == 'first-unbound-later-valid': raw = _native_path('') + '\n' + _native_path('slow')
    if case == 'missing-path-type': raw = raw.replace('Path Type: max\n', '')
    if case == 'unknown-read-syntax': stanza += '\nsource /pdk/extra-libs.tcl'
    rpt = _attested_copy(tmp_path, _emit_bound_report(tmp_path, raw, stanza))
    result = _consume_binding(tmp_path, monkeypatch, unreadable)
    assert result['status'] == 'ERROR', result
    assert 'corner' in result['reason'] and ('refusing' in result['reason']), result
    if case == 'unreadable-library' and SCC.parse_sta_corner_basis(
            rpt.read_text())['liberty']:
        assert 'slow.lib, which is unreadable' in result['reason']
    # R-0915-154: when the WRITER refused the binding, the consumer's refusal
    # names the stamp that says so.
    if 'STA_CORNER_BINDING_REFUSED' in rpt.read_text() and not \
            SCC.parse_sta_corner_basis(rpt.read_text())['liberty']:
        assert 'STA_CORNER_BINDING_REFUSED' in result['reason'], result


# ── R-0915-154: the in-session report is never a correlation source ────────

def test_the_in_session_report_is_never_picked_and_the_refusal_says_why(
        tmp_path, monkeypatch):
    rpt = _emit_bound_report(tmp_path, _native_path('slow'))
    assert 'STA_PARASITICS_PROVENANCE: PNR_SESSION_UNVERIFIED' in rpt.read_text()
    assert SCC._pick_sta_report(tmp_path, {'BUF'}) is None
    result = _consume_binding(tmp_path, monkeypatch)
    assert result['status'] == 'ERROR', result
    assert 'PNR_SESSION_UNVERIFIED' in result['reason'], result
    assert 'phase3/stage3/pnr/sta.rpt' in result['reason'], result


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
