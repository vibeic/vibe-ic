"""Two owner rulings (2026-09-02), each from a MEASURED failure on one
subservient x gf180mcuD acceptance run.

RULING 1 — PDN EM sizing: when the run has MEASURED the per-segment current
distribution, the measurement supersedes the I_total conservation bound.
Size from `max_segment_current_A * _EM_MEASURED_SAFETY`; keep the bound as the
fallback when no measurement exists; record the basis so it is auditable.

  Measured: the bound demanded Metal4 20.77 um where the measured maximum
  needed 5.62 um (3.70x). The die grew 227x227 -> 416x416 um to seat those
  straps, dropping core utilisation to 17% against an L9-declared 50% — which
  made the metal-COVERAGE rules (>30% over the entire die) unsatisfiable and
  inflated CTS insertion delay to 6.47 ns, itself 40% of the register-to-
  output-port setup budget. Two sign-off failures, one over-sized number.

RULING 2 — the via-patch legalizer must be pin-access aware. The tech-LEF fix
is right (main's own detector: 12 findings -> 0) but widening a landing on the
layer standard-cell PINS live on covers the router's access points.

  Measured: 81 x "[ERROR DRT-0073] No access point", detailed routing did not
  complete, the DEF shipped with NO signal routing, and its DRC then reported
  ZERO violations. A DRC of zero on an unrouted DEF reads exactly like a total
  fix. That number is refused.

ENFORCEMENT of the code under test: both are REMEDIATION paths — they change
which geometry/width is produced and never emit a verdict of their own. Both
degrade LOUDLY: ruling 1 records `sizing_basis`, ruling 2 refuses outright
when the pin layers cannot be derived.

chip-AGNOSTIC: the synthetic LEFs below name no real PDK, layer family or
vendor; the real-artefact tests read the PDK the container ships and are
skipped when it is absent.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hostpaths import corpus_path  # noqa: E402

_PROGRAMS = Path(__file__).resolve().parent.parent


def _p3():
    """phase3_one_shot_runner, loaded by path (it is not import-safe by name)."""
    spec = importlib.util.spec_from_file_location(
        "_p3_under_test", _PROGRAMS / "phase3_one_shot_runner.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_p3_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


# ── synthetic, neutral fixtures ────────────────────────────────────────────
_TLEF = """VERSION 5.7 ;
MANUFACTURINGGRID 0.005 ;
LAYER pinmetal
  TYPE ROUTING ;
  MINWIDTH 0.280 ;
  AREA 0.1444 ;
END pinmetal
LAYER wiremetal
  TYPE ROUTING ;
  MINWIDTH 0.280 ;
  AREA 0.1444 ;
END wiremetal
VIA narrow_via
  LAYER pinmetal ;
    RECT -0.130 -0.130 0.130 0.130 ;
  LAYER wiremetal ;
    RECT -0.130 -0.130 0.130 0.130 ;
END narrow_via
END LIBRARY
"""

_CELL_LEF = """VERSION 5.7 ;
MACRO neutral_cell
  PIN a
    DIRECTION INPUT ;
    PORT
      LAYER pinmetal ;
        RECT 0.1 0.1 0.3 0.3 ;
    END
  END a
  OBS
    LAYER pinmetal ;
      RECT 0.0 0.0 0.5 0.5 ;
  END
END neutral_cell
END LIBRARY
"""


# ── RULING 2: pin-access guard ─────────────────────────────────────────────












def test_pin_layers_are_derived_from_the_cell_lefs_own_records():
    m = _p3()
    got = m._pin_access_layers_from_cell_lef(_CELL_LEF)
    assert got == {"pinmetal"}, got


def test_a_cell_lef_with_no_pin_geometry_derives_nothing():
    """Which the caller must treat as 'not derived', never as 'none exist'."""
    m = _p3()
    assert m._pin_access_layers_from_cell_lef("VERSION 5.7 ;\nEND LIBRARY\n") == set()


# ── RULING 1: measured supersedes the bound ────────────────────────────────
def _em_project(tmp: Path, *, i_total_A: float, max_seg_A=None) -> Path:
    r3 = tmp / "reports" / "phase3"
    r3.mkdir(parents=True, exist_ok=True)
    # The floor is only derived from a measurement that describes the layout
    # being sized, so the fixture must be a project with a layout AND an
    # em.json recording it as its subject -- which is exactly what the EM
    # emitter now writes. Without this the project models a measurement of
    # SOME OTHER layout, which is the stale basis the sizing must refuse.
    _m = _p3()
    pnr = _m._pl.pnr_dir(tmp)
    pnr.mkdir(parents=True, exist_ok=True)
    _def = pnr / _m._ppa_power._PDN_EM_SUBJECT_DEF
    _def.write_text("DESIGN chip_top ;\nEND DESIGN\n")
    _subject = _m._ppa_power._pdn_em_subject_digest(tmp)
    (r3 / "em_current_authority.json").write_text(json.dumps(
        {"supply_authority": [{"supply_current_A": i_total_A}]}))
    (r3 / "em.json").write_text(json.dumps(
        ({"max_segment_current_A": max_seg_A, "segments_analysed": 1234}
         if max_seg_A is not None else {"max_segment_current_A": None})
        | {"subject_def_sha256": _subject}))
    return tmp


#: `DCCURRENTDENSITY AVERAGE` is the record `em_current_density_check.
#: parse_lef_jmax` actually reads (mA/um for a ROUTING layer); AC is ignored.
_JMAX_TLEF = """VERSION 5.7 ;
MANUFACTURINGGRID 0.005 ;
LAYER wiremetal
  TYPE ROUTING ;
  MINWIDTH 0.280 ;
  DCCURRENTDENSITY AVERAGE 0.67 ;
END wiremetal
END LIBRARY
"""


def _floor(tmp, tlef_path, **kw):
    m = _p3()
    class _PDK:
        tech_lef = str(tlef_path)
    return m, m._pdn_em_width_floor(_em_project(tmp, **kw), _PDK(), None)


def test_a_measured_maximum_supersedes_the_bound(tmp_path):
    """THE RULING. Both currents present -> the measurement decides."""
    tlef = tmp_path / "t.tlef"; tlef.write_text(_JMAX_TLEF)
    m, out = _floor(tmp_path, tlef, i_total_A=0.01252, max_seg_A=0.003386)
    assert out is not None, (
        "the fixture must yield a per-layer Jmax — a skip here would hide "
        "whether the ruling is implemented at all")
    assert out["sizing_basis"] == "measured_max_segment"
    assert out["safety_factor"] == m._EM_MEASURED_SAFETY
    assert out["i_drive_A"] == pytest.approx(0.003386 * m._EM_MEASURED_SAFETY)


def test_the_bound_is_the_fallback_when_nothing_was_measured(tmp_path):
    """Behaviour must be UNCHANGED for a run with no measurement."""
    tlef = tmp_path / "t.tlef"; tlef.write_text(_JMAX_TLEF)
    _, out = _floor(tmp_path, tlef, i_total_A=0.01252)
    assert out is not None, (
        "the fixture must yield a per-layer Jmax — a skip here would hide "
        "whether the ruling is implemented at all")
    assert out["sizing_basis"] == "i_total_conservation_bound"
    assert out["i_drive_A"] == pytest.approx(0.01252)
    assert out["safety_factor"] is None


def test_the_measured_basis_keeps_real_headroom(tmp_path):
    """The relaxation is to 'measured worst case x N', never to the raw
    measurement — otherwise this is a margin deletion, not a re-basing."""
    tlef = tmp_path / "t.tlef"; tlef.write_text(_JMAX_TLEF)
    m, out = _floor(tmp_path, tlef, i_total_A=0.01252, max_seg_A=0.003386)
    assert out is not None, (
        "the fixture must yield a per-layer Jmax — a skip here would hide "
        "whether the ruling is implemented at all")
    assert m._EM_MEASURED_SAFETY >= 2.0
    assert out["i_drive_A"] > 0.003386


def test_the_basis_and_both_currents_are_recorded(tmp_path):
    """Auditable, and reversible by reading one field."""
    tlef = tmp_path / "t.tlef"; tlef.write_text(_JMAX_TLEF)
    _, out = _floor(tmp_path, tlef, i_total_A=0.01252, max_seg_A=0.003386)
    assert out is not None, (
        "the fixture must yield a per-layer Jmax — a skip here would hide "
        "whether the ruling is implemented at all")
    for field in ("sizing_basis", "i_drive_A", "safety_factor",
                  "max_segment_current_A", "i_total_A", "ruling",
                  "bound_over_measured_x"):
        assert field in out, field
    assert out["bound_over_measured_x"] > 1.0, (
        "the measured basis must be BELOW the bound, or the ruling changed "
        "nothing")


# ── real artefacts (skipped when the PDK is not staged) ────────────────────
# The staged pair is an EXTERNAL corpus (class b in `_hostpaths`): it lives
# outside the repo, so it is resolved through `$VIBEIC_CORPUS_ROOT` and never
# through a personal home path (vibe-ic#2010 item 7 — `shipped_path_
# portability_check` R1). Stage the two files as
# `$VIBEIC_CORPUS_ROOT/evidence/via_legalize/{nom.tlef,cells.lef}`.
_REAL_EVIDENCE = corpus_path("evidence", "via_legalize")
_REAL_TLEF = _REAL_EVIDENCE / "nom.tlef"
_REAL_CELLS = _REAL_EVIDENCE / "cells.lef"
