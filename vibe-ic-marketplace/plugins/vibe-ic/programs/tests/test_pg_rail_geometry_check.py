#!/usr/bin/env python3
"""A power rail with no metal is a name, not a supply.

The defect this gate exists for, measured on a real tapeout run whose
third-party hard macro takes a second supply: the DEF declared the rail and
bound the macro's supply pin to it, and the rail carried ZERO routed geometry.
Three tools reported success anyway —

  * ``PG_CONNECT_AUDIT: unconnected=0`` counts pins whose net pointer is NULL;
    this pin's pointer is valid, it points at the empty rail.
  * ``[INFO PSM-0040] All shapes on net <RAIL> are connected`` is vacuously
    true over an empty shape set.
  * the router had nothing to route, so it had nothing to fail on.

Each answered its own question correctly; none answered "can current reach this
pin", and no gate asked. The fixtures below reproduce that DEF shape — a rail
whose entry ends at the `;` with no `+ ROUTED` clause, beside a sibling rail in
the same section that carries stripes.

chip-AGNOSTIC: rail names here are generic (RAIL_A/RAIL_B/RAIL_G). No chip
name, PDK SKU, vendor or part number appears in this file.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import pg_rail_geometry_check as PG  # noqa: E402

PROG = _PROGRAMS / "pg_rail_geometry_check.py"

_ROUTED_A = """\
    - RAIL_A ( * PIN_A ) + USE POWER
      + ROUTED MET5 1760 + SHAPE STRIPE ( 26800 443180 ) ( 453520 443180 )
      NEW MET5 1760 + SHAPE STRIPE ( 26800 418780 ) ( 453520 418780 ) ;
"""
_ROUTED_G = """\
    - RAIL_G ( * PIN_G ) + USE GROUND
      + ROUTED MET5 1760 + SHAPE STRIPE ( 26800 400000 ) ( 453520 400000 ) ;
"""
# The defect shape: declared, pin bound, ends at the `;`, no geometry clause.
_EMPTY_B = "    - RAIL_B ( * PIN_B ) + USE POWER ;\n"


def _project(tmp_path: Path, body: str, marker: dict | None = None) -> Path:
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "routed.def").write_text(
        "VERSION 5.8 ;\nDESIGN t ;\n"
        f"SPECIALNETS {body.count('    - ')} ;\n{body}"
        "END SPECIALNETS\nEND DESIGN\n")
    if marker is not None:
        d = tmp_path / "reports" / "phase3"
        d.mkdir(parents=True, exist_ok=True)
        (d / "pdn_integration_supplied.json").write_text(json.dumps(marker))
    return tmp_path


def _run(project: Path, *extra) -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(PROG), str(project), *extra],
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


# ── the defect ───────────────────────────────────────────────────────────────

def test_declared_rail_with_no_geometry_fails(tmp_path):
    """THE defect. A rail declared beside routed siblings, with a pin bound to
    it and no metal of its own."""
    rc, out = _run(_project(tmp_path, _EMPTY_B + _ROUTED_A + _ROUTED_G))
    assert rc == 1, out
    assert "PG_RAIL_NO_GEOMETRY" in out
    assert "RAIL_B" in out
    assert "RAIL_A" not in out.split("[PG_RAIL_NO_GEOMETRY]")[1].split("\n")[0]


def test_the_empty_rail_is_named_with_its_def_line(tmp_path):
    """A finding that cannot be located is hard to act on."""
    p = _project(tmp_path, _ROUTED_A + _EMPTY_B + _ROUTED_G)
    res = PG.check(p)
    assert res["verdict"] == "FAIL"
    f = res["findings"][0]
    assert f["rail"] == "RAIL_B" and f["pins_bound"] == 1
    line = p / "phase3" / "stage3" / "pnr" / "routed.def"
    assert "RAIL_B" in line.read_text().splitlines()[f["def_line"] - 1]


# ── direction 1: what must NOT change ────────────────────────────────────────

def test_all_rails_routed_passes(tmp_path):
    rc, out = _run(_project(tmp_path, _ROUTED_A + _ROUTED_G))
    assert rc == 0, out
    assert "all 2 declared rail(s) carry routed geometry" in out


def test_multiline_geometry_is_not_mistaken_for_empty(tmp_path):
    """A special net's body spans many lines and the geometry may be nowhere
    near the `- NAME` line — which is exactly why a single-line grep for the
    rail name cannot tell an empty rail from a routed one."""
    res = PG.check(_project(tmp_path, _ROUTED_A + _ROUTED_G))
    assert res["verdict"] == "PASS"
    assert all(r["geometry_lines"] > 0 for r in res["rails"])


def test_no_def_skips_rather_than_passing(tmp_path):
    """A run that never reached the router must not be certified clean."""
    rc, out = _run(tmp_path)
    assert rc == 2, out
    assert "no routed.def" in out


def test_def_without_specialnets_skips(tmp_path):
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "routed.def").write_text("VERSION 5.8 ;\nDESIGN t ;\nEND DESIGN\n")
    rc, out = _run(tmp_path)
    assert rc == 2, out
    assert "no SPECIALNETS" in out


# ── the disclosed-integration path ───────────────────────────────────────────

def test_disclosed_integration_rail_passes(tmp_path):
    """A rail legitimately delivered at integration is a hierarchical split,
    not a defect — provided the run SAYS SO in a machine-readable marker."""
    p = _project(tmp_path, _EMPTY_B + _ROUTED_A,
                 marker={"integration_supplied_rails": ["RAIL_B"]})
    rc, out = _run(p)
    assert rc == 0, out
    assert "DISCLOSED" in out and "RAIL_B" in out


def test_marker_naming_a_different_rail_does_not_excuse_this_one(tmp_path):
    """The disclosure must name the rail it excuses."""
    p = _project(tmp_path, _EMPTY_B + _ROUTED_A,
                 marker={"integration_supplied_rails": ["SOME_OTHER_RAIL"]})
    assert _run(p)[0] == 1


def test_absent_marker_discloses_nothing(tmp_path):
    """Fail-closed: silence is never a disclosure."""
    assert _run(_project(tmp_path, _EMPTY_B + _ROUTED_A))[0] == 1


def test_unreadable_marker_discloses_nothing(tmp_path):
    p = _project(tmp_path, _EMPTY_B + _ROUTED_A)
    d = p / "reports" / "phase3"
    d.mkdir(parents=True, exist_ok=True)
    (d / "pdn_integration_supplied.json").write_text("{not json")
    assert _run(p)[0] == 1


def test_cli_flag_can_supply_the_contract(tmp_path):
    rc, _ = _run(_project(tmp_path, _EMPTY_B + _ROUTED_A),
                 "--integration-supplied", "RAIL_B")
    assert rc == 0


# ── the gate must be able to fail, and its report must be usable ─────────────

@pytest.mark.parametrize("body,expect", [
    (_ROUTED_A + _ROUTED_G, "PASS"),
    (_EMPTY_B + _ROUTED_A, "FAIL"),
])
def test_verdict_is_falsifiable_both_ways(tmp_path, body, expect):
    """A gate that cannot reach both verdicts on realistic input is not a gate.
    Same fixture family, opposite answers."""
    assert PG.check(_project(tmp_path, body))["verdict"] == expect


def test_json_report_is_written_on_fail(tmp_path):
    out = tmp_path / "r.json"
    _run(_project(tmp_path, _EMPTY_B + _ROUTED_A), "--json", str(out))
    d = json.loads(out.read_text())
    assert d["verdict"] == "FAIL" and d["rails_total"] == 2
    assert d["rails_routed"] == 1 and d["rails_empty_undisclosed"] == 1


def test_parser_counts_pins_bound_to_the_empty_rail(tmp_path):
    """`pins_bound` is what makes the finding matter: an empty rail nothing
    connects to is inert; one with pins on it starves those pins."""
    body = ("    - RAIL_B ( * PIN_B ) ( i1 VPP ) ( i2 VPP ) + USE POWER ;\n"
            + _ROUTED_A)
    res = PG.check(_project(tmp_path, body))
    assert res["findings"][0]["pins_bound"] == 3
