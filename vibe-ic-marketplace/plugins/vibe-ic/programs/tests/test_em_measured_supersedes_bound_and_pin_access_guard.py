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
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pdk_via_patch_legalize import legalize_via_patches  # noqa: E402

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
def test_a_pin_layer_landing_is_never_widened():
    """THE DEFECT. Pre-fix every routing layer was widened, including the one
    the router needs access points on."""
    _, rep = legalize_via_patches(_TLEF, pin_layers={"pinmetal"})
    touched = {c["layer"] for c in rep["changes"]}
    assert "pinmetal" not in touched, (
        "a widened landing on the pin layer covers the router's access "
        "points; that is the DRT-0073 failure this guard exists for")
    assert "wiremetal" in touched, (
        "the guard must not disable the remediation it is guarding")


def test_the_pin_layer_bytes_are_untouched():
    """Not merely 'not in changes' — the emitted text must be identical on
    that layer, so nothing widens it by another path."""
    guarded, _ = legalize_via_patches(_TLEF, pin_layers={"pinmetal"})
    unguarded, _ = legalize_via_patches(_TLEF)
    assert guarded != unguarded, "fixture guard: the two arms must differ"
    def _block(text, layer):
        lines = text.splitlines()
        i = next(n for n, l in enumerate(lines) if l.strip() == f"LAYER {layer} ;")
        return lines[i + 1].strip()
    assert _block(guarded, "pinmetal") == _block(_TLEF, "pinmetal")
    assert _block(unguarded, "pinmetal") != _block(_TLEF, "pinmetal"), (
        "fixture guard: without the pin set this layer IS widened, which is "
        "what made the guard necessary")


def test_the_guard_still_fixes_everything_it_should():
    """Skipping the pin layer must not leave a real violation behind."""
    _, rep = legalize_via_patches(_TLEF, pin_layers={"pinmetal"})
    assert rep["remaining_via_rule_violations"] == 0


def test_an_undeclared_pin_set_is_distinguishable_from_an_empty_one():
    """A caller that could not derive the set must not look like one that
    derived an empty set — those mean opposite things."""
    _, undeclared = legalize_via_patches(_TLEF)
    _, empty = legalize_via_patches(_TLEF, pin_layers=[])
    assert undeclared["pin_layers_declared"] is False
    assert empty["pin_layers_declared"] is True


def test_pin_layer_matching_is_case_insensitive():
    _, rep = legalize_via_patches(_TLEF, pin_layers={"PINMETAL"})
    assert "pinmetal" not in {c["layer"] for c in rep["changes"]}


def test_the_report_names_the_policy_and_the_skipped_layers():
    """Degrade LOUDLY: a reader must see WHICH layers were withheld."""
    _, rep = legalize_via_patches(_TLEF, pin_layers={"pinmetal"})
    assert rep["pin_layers_skipped_from_rules"] == ["pinmetal"]
    assert rep["pin_access_policy"].strip()


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
    (r3 / "em_current_authority.json").write_text(json.dumps(
        {"supply_authority": [{"supply_current_A": i_total_A}]}))
    if max_seg_A is not None:
        (r3 / "em.json").write_text(json.dumps(
            {"max_segment_current_A": max_seg_A, "segments_analysed": 1234}))
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
_REAL_TLEF = Path("/home/reyerchu/_ksubs6/evidence/via_legalize/nom.tlef")
_REAL_CELLS = Path("/home/reyerchu/_ksubs6/evidence/via_legalize/cells.lef")


@pytest.mark.skipif(not (_REAL_TLEF.is_file() and _REAL_CELLS.is_file()),
                    reason="staged PDK LEFs not present on this host")
def test_on_the_real_pdk_the_guard_costs_no_fixed_violation():
    """REAL ARTEFACT: withholding the pin layer must not resurrect a
    violation — the offenders live on the layers ABOVE it."""
    m = _p3()
    pin = m._pin_access_layers_from_cell_lef(_REAL_CELLS.read_text(errors="replace"))
    assert pin, "no pin geometry parsed from the shipped cell LEF"
    text = _REAL_TLEF.read_text(errors="replace")
    _, guarded = legalize_via_patches(text, pin_layers=pin)
    _, unguarded = legalize_via_patches(text)
    assert guarded["remaining_via_rule_violations"] == 0
    assert unguarded["remaining_via_rule_violations"] == 0
    assert guarded["changed_patch_records"] < unguarded["changed_patch_records"], (
        "fixture guard: the guard must actually withhold something here")
    assert not (set(guarded["pin_layers_skipped_from_rules"]) &
                {c["layer"] for c in guarded["changes"]})
