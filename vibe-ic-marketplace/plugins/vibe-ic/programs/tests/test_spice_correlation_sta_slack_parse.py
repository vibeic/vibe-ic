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
    spec = importlib.util.spec_from_file_location("spice_correlation_check", PROG)
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
