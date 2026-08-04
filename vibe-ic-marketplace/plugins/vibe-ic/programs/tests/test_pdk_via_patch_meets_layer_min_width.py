#!/usr/bin/env python3
"""Tests for pdk_via_patch_meets_layer_min_width_check.

The motivating measurement: a sky130A run whose sign-off deck reported 9
`m5.1` (min met5 width) violations on the shipped GDS. The offending geometry
was the PDK's own `VIA M4M5_PR ... LAYER met5 ; RECT -0.71 -0.71 0.71 0.71`
(1.42 um) on a layer the SAME tech LEF gives `WIDTH 1.6`. The router's own
in-loop DRC reported 0 for that layout.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
        / "pdk_via_patch_meets_layer_min_width_check.py")

# The shape of the real defect, reduced to the two declarations that
# contradict each other. `SPACINGTABLE`'s `WIDTH 0 1.6 ;` row is present on
# purpose: it carries the same number as the layer rule, so a parser that
# read the table row instead would agree with the rule for the wrong reason.
_LEF_NARROW = """\
LAYER met4
  TYPE ROUTING ;
  WIDTH 0.3 ;
END met4

LAYER via4
  TYPE CUT ;
  WIDTH 0.8 ;
END via4

LAYER met5
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
  WIDTH 1.6 ;
  SPACINGTABLE
     PARALLELRUNLENGTH 0
     WIDTH 0 1.6 ;
END met5

VIA M4M5_PR DEFAULT
  LAYER via4 ;
  RECT -0.4 -0.4 0.4 0.4 ;
  LAYER met4 ;
  RECT -0.59 -0.59 0.59 0.59 ;
  LAYER met5 ;
  RECT -0.71 -0.71 0.71 0.71 ;
END M4M5_PR
"""

_LEF_OK = _LEF_NARROW.replace("RECT -0.71 -0.71 0.71 0.71 ;",
                              "RECT -0.8 -0.8 0.8 0.8 ;")


def _run(args, cwd=None):
    return subprocess.run([sys.executable, str(PROG)] + args,
                          capture_output=True, text=True, cwd=cwd)


def _empty_baseline(tmp_path: Path) -> Path:
    p = tmp_path / "bl.json"
    p.write_text(json.dumps({"known": []}))
    return p


def test_narrow_patch_is_found(tmp_path):
    lef = tmp_path / "narrow.tlef"
    lef.write_text(_LEF_NARROW)
    out = tmp_path / "r.json"
    r = _run(["--tech-lef", str(lef), "--json", str(out),
              "--baseline", str(_empty_baseline(tmp_path))])
    assert r.returncode == 1, r.stdout + r.stderr
    rep = json.loads(out.read_text())
    assert len(rep["findings"]) == 1
    f = rep["findings"][0]
    assert (f["via"], f["layer"]) == ("M4M5_PR", "met5")
    assert f["patch_x_um"] == 1.42 and f["patch_y_um"] == 1.42
    assert f["layer_min_width_um"] == 1.6


def test_the_proposed_pdk_fix_clears_it(tmp_path):
    """+-0.8 (=1.6um) satisfies met5's own WIDTH and is the proposed fix."""
    lef = tmp_path / "fixed.tlef"
    lef.write_text(_LEF_OK)
    out = tmp_path / "r.json"
    r = _run(["--tech-lef", str(lef), "--json", str(out),
              "--baseline", str(_empty_baseline(tmp_path))])
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(out.read_text())["findings"] == []


def test_cut_layer_is_not_compared(tmp_path):
    """A CUT layer has no width rule of this kind.

    `via4` here declares `WIDTH 0.8` and the via's own cut RECT is 0.8 —
    equal, so it would not fire anyway. The assertion that matters is that
    the cut layer contributes no finding even when the via's patch on it is
    smaller than the layer's stated WIDTH.
    """
    lef = tmp_path / "cut.tlef"
    lef.write_text(_LEF_NARROW.replace("  WIDTH 0.8 ;\nEND via4",
                                       "  WIDTH 5.0 ;\nEND via4"))
    out = tmp_path / "r.json"
    _run(["--tech-lef", str(lef), "--json", str(out),
          "--baseline", str(_empty_baseline(tmp_path))])
    rep = json.loads(out.read_text())
    assert all(f["layer"] != "via4" for f in rep["findings"])


def test_baselined_finding_does_not_fail(tmp_path):
    """A recorded finding is not standing permission, but it is not news."""
    lef = tmp_path / "narrow.tlef"
    lef.write_text(_LEF_NARROW)
    bl = tmp_path / "bl.json"
    bl.write_text(json.dumps({"known": ["narrow.tlef::M4M5_PR::met5"]}))
    r = _run(["--tech-lef", str(lef), "--baseline", str(bl)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "recorded" in r.stdout


def test_a_baseline_entry_that_stopped_occurring_fails(tmp_path):
    """Shrink-only: the record must not outlive the thing it records."""
    lef = tmp_path / "fixed.tlef"
    lef.write_text(_LEF_OK)
    bl = tmp_path / "bl.json"
    bl.write_text(json.dumps({"known": ["fixed.tlef::M4M5_PR::met5"]}))
    r = _run(["--tech-lef", str(lef), "--baseline", str(bl)])
    assert r.returncode == 1
    assert "no longer occurs" in r.stdout


def test_a_baseline_entry_for_an_unchecked_lef_is_not_judged(tmp_path):
    """Running on a subset must not report the rest as fixed."""
    lef = tmp_path / "fixed.tlef"
    lef.write_text(_LEF_OK)
    bl = tmp_path / "bl.json"
    bl.write_text(json.dumps({"known": ["some_other.tlef::M4M5_PR::met5"]}))
    r = _run(["--tech-lef", str(lef), "--baseline", str(bl)])
    assert r.returncode == 0, r.stdout + r.stderr


def test_no_readable_lef_refuses_instead_of_reporting_clean(tmp_path):
    """An unchecked PDK is not a clean PDK — rc=2, not rc=0."""
    r = _run(["--tech-lef", str(tmp_path / "nope.tlef")])
    assert r.returncode == 2
    assert "REFUSE" in r.stderr


def test_shipped_baseline_is_wellformed_and_records_the_measured_defect():
    """The committed baseline must parse and must carry the measurement
    this checker was written from."""
    bl = json.loads((PROG.parent
                     / "pdk_via_patch_min_width_baseline.json").read_text())
    known = bl["known"]
    assert isinstance(known, list) and known == sorted(known)
    assert len(known) == len(set(known))
    assert "sky130_fd_sc_hd__nom.tlef::M4M5_PR::met5" in known
    # both PDK families the image ships are represented
    assert any(k.startswith("gf180mcu_") for k in known)
    assert any(k.startswith("sky130_") for k in known)
