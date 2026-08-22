#!/usr/bin/env python3
"""A power rail with no metal is a name, not a supply.

The defect this gate exists for, measured on a real tapeout run whose
third-party hard macro takes a second supply: the DEF declared the rail and
bound the macro's supply pin to it, and the rail carried ZERO routed geometry.
Three tools reported success anyway —

  * ``PG_NET_OWNERSHIP_AUDIT: no_net=0`` counts pins whose net pointer is NULL;
    this pin's pointer is valid, it points at the empty rail. (Spelled
    ``PG_CONNECT_AUDIT: unconnected=0`` through v1.9.62 — a name that asserted
    connectivity the predicate never tested.)
  * ``[INFO PSM-0040] All shapes on net <RAIL> are connected`` is vacuously
    true over an empty shape set.
  * the router had nothing to route, so it had nothing to fail on.

Each answered its own question correctly; none answered "can current reach this
pin", and no gate asked. The fixtures below reproduce that DEF shape — a rail
whose entry ends at the `;` with no `+ ROUTED` clause, beside a sibling rail in
the same section that carries stripes.

The second half of this file pins the ways the gate could be TALKED OUT of that
verdict, which is the only direction that matters for a gate like this one: a
`#` comment, a quoted property value, a self-minted waiver, a truncated file,
and a staged oracle DEF each used to produce a PASS or a crash.

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

# Spelled out rather than imported from the program, so that reverting the
# program does not turn this file into a COLLECTION ERROR. A collection error
# proves only that the tests reference new API; it hides which behaviours are
# actually covered, and every mutant then looks equally "red".
# `test_the_disclosure_field_name_is_the_one_the_program_reads` keeps the two
# in step.
_FIELD = "pg_rails_integration_supplied"


def _waiver(rails, reason=None, approver="Jane Engineer", **extra):
    """A disclosure in the shape the governed channel requires."""
    entry = {
        "id": 31,
        "reason": reason if reason is not None else (
            "delivered by the parent partition at integration; this block "
            "deliberately leaves it unrouted"),
        "approver": approver,
        _FIELD: rails,
    }
    entry.update(extra)
    return json.dumps({"waived_steps": [entry]})


def _project(tmp_path: Path, body: str, waivers: str | None = None,
             marker: dict | None = None, terminate: bool = True) -> Path:
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    tail = ("END SPECIALNETS\nEND DESIGN\n" if terminate else
            # a truncated DEF: the section never closes and a NETS section of
            # ordinary SIGNAL nets follows it
            "NETS 2 ;\n- sig_a ( u1 A ) ;\n- sig_b ( u2 B ) ;\nEND NETS\n")
    (pnr / "routed.def").write_text(
        "VERSION 5.8 ;\nDESIGN t ;\n"
        f"SPECIALNETS {body.count('    - ')} ;\n{body}" + tail)
    if waivers is not None:
        (tmp_path / "waivers.json").write_text(waivers)
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
    assert "all 2 declared rail(s) carry a geometry clause" in out


def test_a_pass_states_its_denominator(tmp_path):
    """A PASS that does not say how many rails it examined is unfalsifiable."""
    rc, out = _run(_project(tmp_path, _ROUTED_A + _ROUTED_G))
    assert rc == 0
    assert "2/2 examined" in out


def test_multiline_geometry_is_not_mistaken_for_empty(tmp_path):
    """A special net's body spans many lines and the geometry may be nowhere
    near the `- NAME` line — which is exactly why a single-line grep for the
    rail name cannot tell an empty rail from a routed one."""
    res = PG.check(_project(tmp_path, _ROUTED_A + _ROUTED_G))
    assert res["verdict"] == "PASS"
    assert all(r["geometry_lines"] > 0 for r in res["rails"])


def test_no_def_skips_rather_than_passing(tmp_path):
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


# ── a `#` comment must not be able to talk the gate out of the defect ────────

def test_commented_out_geometry_does_not_rescue_an_empty_rail(tmp_path):
    """`#` opens a DEF line comment. Reading the raw line let a commented-out
    geometry row PASS an empty rail — a gate whose whole reason to exist is
    "declared but no metal", argued out of it by one character."""
    body = ("    - RAIL_B ( * PIN_B ) + USE POWER\n"
            "    # + ROUTED MET5 1760 + SHAPE STRIPE ( 1 2 ) ( 3 4 )\n"
            "      ;\n") + _ROUTED_A
    rc, out = _run(_project(tmp_path, body))
    assert rc == 1, out
    assert "RAIL_B" in out


def test_geometry_inside_a_quoted_property_is_not_geometry(tmp_path):
    """Same false PASS with no comment character at all: the eight characters
    of a wiring clause sitting inside a quoted property value."""
    body = ('    - RAIL_B ( * PIN_B ) + USE POWER\n'
            '      + PROPERTY note "+ ROUTED by hand" ;\n') + _ROUTED_A
    rc, out = _run(_project(tmp_path, body))
    assert rc == 1, out
    assert "RAIL_B" in out


def test_a_trailing_comment_does_not_hide_real_geometry(tmp_path):
    """The other direction: stripping comments must not eat real metal on the
    same line."""
    body = ("    - RAIL_B ( * PIN_B ) + USE POWER\n"
            "      + ROUTED MET5 1760 + SHAPE STRIPE ( 1 2 ) ( 3 4 ) ; # ok\n"
            ) + _ROUTED_A
    rc, out = _run(_project(tmp_path, body))
    assert rc == 0, out


def test_a_bare_keyword_without_a_layer_is_not_a_wiring_clause(tmp_path):
    """`+ ROUTED` opens a wire segment only when a layer follows it. Matched as
    a substring, the word alone was enough."""
    assert PG.has_geometry_clause("+ ROUTED MET5 1760") is True
    assert PG.has_geometry_clause("+ ROUTED ;") is False
    assert PG.has_geometry_clause("+ USE POWER") is False


def test_sanitizer_removes_comments_and_string_bodies():
    assert PG.sanitize_def_line("  a b # + ROUTED MET1").strip() == "a b"
    kept = PG.sanitize_def_line('+ PROPERTY n "+ ROUTED MET1" ;')
    assert "ROUTED" not in kept and kept.strip().endswith(";")


# ── a truncated DEF must fail closed, not invent findings ────────────────────

def test_truncated_def_is_not_judged(tmp_path):
    """Without `END SPECIALNETS` the old scan ran to EOF and reported the
    SIGNAL nets of the following NETS section as power rails with zero
    geometry — fabricating findings out of a damaged file."""
    rc, out = _run(_project(tmp_path, _ROUTED_A, terminate=False))
    assert rc == 2, out
    assert "never terminates" in out
    assert "sig_a" not in out and "sig_b" not in out


def test_truncated_def_reports_no_rails_at_all(tmp_path):
    p = _project(tmp_path, _EMPTY_B + _ROUTED_A, terminate=False)
    res = PG.check(p)
    assert res["verdict"] == "SKIP" and "findings" not in res


# ── the DEF judged must be the project's own, never a staged oracle ──────────

def test_an_oracle_routed_def_is_never_judged(tmp_path):
    """An unrestricted rglob returned a staged reference/golden DEF when the
    canonical path was absent, and certified the run on the known-good answer."""
    g = tmp_path / "reference_flow" / "golden" / "pnr"
    g.mkdir(parents=True)
    (g / "routed.def").write_text(
        "SPECIALNETS 1 ;\n" + _ROUTED_A + "END SPECIALNETS\n")
    rc, out = _run(tmp_path)
    assert rc == 2, out
    assert "no routed.def" in out


def test_a_non_pnr_routed_def_is_not_judged(tmp_path):
    """The fallback accepts a DEF that really sits in a pnr dir; a stray file
    elsewhere in the tree is not this project's routing result."""
    d = tmp_path / "attic"
    d.mkdir()
    (d / "routed.def").write_text(
        "SPECIALNETS 1 ;\n" + _EMPTY_B + "END SPECIALNETS\n")
    assert _run(tmp_path)[0] == 2


def test_the_canonical_def_is_still_found_outside_the_default_path(tmp_path):
    """The restriction must not break a real, non-oracle pnr directory."""
    d = tmp_path / "runs" / "r1" / "pnr"
    d.mkdir(parents=True)
    (d / "routed.def").write_text(
        "SPECIALNETS 2 ;\n" + _EMPTY_B + _ROUTED_A + "END SPECIALNETS\n")
    assert _run(tmp_path)[0] == 1


# ── the governed disclosure channel ──────────────────────────────────────────

def test_disclosed_integration_rail_passes(tmp_path):
    """A rail legitimately delivered at integration is a hierarchical split,
    not a defect — provided the run SAYS SO through the governed channel."""
    p = _project(tmp_path, _EMPTY_B + _ROUTED_A, waivers=_waiver(["RAIL_B"]))
    rc, out = _run(p)
    assert rc == 0, out
    assert "DISCLOSED" in out and "RAIL_B" in out


def test_a_disclosed_pass_names_the_human_who_approved_it(tmp_path):
    p = _project(tmp_path, _EMPTY_B + _ROUTED_A, waivers=_waiver(["RAIL_B"]))
    rc, out = _run(p)
    assert rc == 0 and "Jane Engineer" in out


def test_disclosure_naming_a_different_rail_does_not_excuse_this_one(tmp_path):
    p = _project(tmp_path, _EMPTY_B + _ROUTED_A,
                 waivers=_waiver(["SOME_OTHER_RAIL"]))
    assert _run(p)[0] == 1


def test_absent_waivers_file_discloses_nothing(tmp_path):
    """Fail-closed: silence is never a disclosure."""
    assert _run(_project(tmp_path, _EMPTY_B + _ROUTED_A))[0] == 1


def test_an_ungoverned_marker_file_is_not_a_disclosure(tmp_path):
    """The escape hatch used to be a private JSON marker with no producer, two
    of whose three accepted paths were directories THIS RUN WRITES INTO — so a
    runner could mint its own waiver. Any JSON with a `rails` list worked."""
    p = _project(tmp_path, _EMPTY_B + _ROUTED_A, marker={"rails": ["RAIL_B"]})
    assert _run(p)[0] == 1


def test_a_bare_rails_list_in_waivers_is_not_a_disclosure(tmp_path):
    p = _project(tmp_path, _EMPTY_B + _ROUTED_A,
                 waivers=json.dumps({"rails": ["RAIL_B"]}))
    assert _run(p)[0] == 1


@pytest.mark.parametrize("kwargs", [
    {"reason": ""},                      # no reason at all
    {"reason": "later"},                 # under the schema's minimum length
    {"reason": "TODO"},                  # a placeholder
    {"approver": ""},                    # nobody approved it
    {"approver": "agent"},               # self-approval
    {"approver": "claude"},
    {"approver": "bot"},
    {"approver": "__TODO_HUMAN_NAME__"},  # an unfilled scaffold slot
    {"approver": "your name"},
])
def test_disclosure_must_survive_the_waiver_legitimacy_rules(tmp_path, kwargs):
    """The disclosure lives in waivers.json so the four waiver gates see it.
    This pins that the SAME reason/approver rules apply here — they are
    imported from `waivers_schema_check`, not restated."""
    p = _project(tmp_path, _EMPTY_B + _ROUTED_A,
                 waivers=_waiver(["RAIL_B"], **kwargs))
    assert _run(p)[0] == 1


def test_the_disclosure_field_name_is_the_one_the_program_reads():
    """The fixtures above hard-code the field name so a reverted program fails
    tests rather than failing to import. This keeps the two honest."""
    assert PG.DISCLOSURE_FIELD == _FIELD


def test_a_governed_disclosure_still_validates_as_a_waiver(tmp_path):
    """The entry this gate asks people to write must not be one the repo's own
    schema gate rejects."""
    import waivers_schema_check as WS
    p = _project(tmp_path, _EMPTY_B + _ROUTED_A, waivers=_waiver(["RAIL_B"]))
    findings, _ = WS.validate(p)
    assert [f for f in findings if f.severity == "error"] == []


# ── non-object JSON must fail closed, not crash ──────────────────────────────

@pytest.mark.parametrize("blob", ['["RAIL_B"]', "true", "null", "42",
                                  '"a string"', "{not json"])
def test_non_object_waivers_json_does_not_crash_a_clean_run(tmp_path, blob):
    """`except (OSError, ValueError)` catches malformed JSON but not JSON that
    is legal and simply is not an object, so `.get()` raised AttributeError. A
    completely clean, fully routed project was reported FAIL with a traceback
    — and `--json` was never written, because it died before the write."""
    p = _project(tmp_path, _ROUTED_A + _ROUTED_G, waivers=blob)
    report = tmp_path / "r.json"
    rc, out = _run(p, "--json", str(report))
    assert rc == 0, out
    assert "Traceback" not in out and "AttributeError" not in out
    assert json.loads(report.read_text())["verdict"] == "PASS"


@pytest.mark.parametrize("blob", ['["RAIL_B"]', "true", "null", "42"])
def test_non_object_waivers_json_discloses_nothing(tmp_path, blob):
    """Fail-closed, not fail-open: garbage must not become an excuse either."""
    assert _run(_project(tmp_path, _EMPTY_B + _ROUTED_A, waivers=blob))[0] == 1


@pytest.mark.parametrize("doc", [
    {"waived_steps": "not a list"},
    {"waived_steps": [None, 7, "x"]},
    {"waived_steps": [{"id": 31, "reason": "a" * 30, "approver": "Jane",
                       _FIELD: "RAIL_B"}]},   # str, not list
    {"waived_steps": [{"id": 31, "reason": "a" * 30, "approver": "Jane",
                       _FIELD: []}]},          # empty list
])
def test_malformed_waived_steps_disclose_nothing(tmp_path, doc):
    p = _project(tmp_path, _EMPTY_B + _ROUTED_A, waivers=json.dumps(doc))
    rc, out = _run(p)
    assert rc == 1, out
    assert "Traceback" not in out


def test_cli_flag_can_supply_the_contract(tmp_path):
    rc, _ = _run(_project(tmp_path, _EMPTY_B + _ROUTED_A),
                 "--integration-supplied", "RAIL_B")
    assert rc == 0


def test_a_cli_supplied_excuse_says_so_in_the_report(tmp_path):
    """A PASS must disclose where its excuse came from."""
    res = PG.check(_project(tmp_path, _EMPTY_B + _ROUTED_A), {"RAIL_B"})
    assert res["verdict"] == "PASS"
    b = [r for r in res["rails"] if r["rail"] == "RAIL_B"][0]
    assert b["disclosure"]["source"] == "cli"


# ── pin counting is reported as fact, so it must be one ──────────────────────

def test_parser_counts_pins_bound_to_the_empty_rail(tmp_path):
    """`pins_bound` is what makes the finding concrete."""
    body = ("    - RAIL_B ( * PIN_B ) ( i1 VPP ) ( i2 VPP ) + USE POWER ;\n"
            + _ROUTED_A)
    res = PG.check(_project(tmp_path, body))
    assert res["findings"][0]["pins_bound"] == 3


def test_routing_coordinates_are_not_counted_as_pin_connections(tmp_path):
    """A DEF coordinate is a parenthesised pair too. Counting them over the
    whole entry turned ONE genuine binding on a real tracked DEF into 333, and
    that number is printed as fact in the FAIL message."""
    res = PG.check(_project(tmp_path, _ROUTED_A + _ROUTED_G))
    assert [r["pins"] for r in res["rails"]] == [1, 1]


def test_a_wildcard_coordinate_is_not_counted_as_a_pin(tmp_path):
    """DEF abbreviates a repeated ordinate as `*`: `( 360640 * )`, `( * 225120 )`
    — both forms occur in the tracked corpus. Those pairs are NOT two numbers,
    so rejecting numeric pairs does not exclude them; only reading pins from
    the entry HEAD does. Without that, a heavily routed rail inflates its own
    pin count with its own corners."""
    body = ("    - RAIL_B ( * PIN_B ) + USE POWER\n"
            "      + ROUTED MET2 ( 355600 216160 ) ( 360640 * )\n"
            "      NEW MET2 ( 360640 216160 ) ( * 225120 ) ;\n")
    res = PG.check(_project(tmp_path, body + _ROUTED_A))
    assert [r["rail"] for r in res["rails"]][0] == "RAIL_B"
    assert res["rails"][0]["pins"] == 1


def test_pin_counting_is_head_only():
    assert PG.count_pin_connections("- RAIL_A ( * PIN_A ) ") == 1
    assert PG.count_pin_connections("- R ( u1 A ) ( u2 B ) ") == 2
    # coordinates, wherever they appear, are never pins
    assert PG.count_pin_connections("( 26800 443180 ) ( 453520 443180 )") == 0


# ── the gate must be able to fail, and declare what it is ────────────────────

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


def test_the_gate_declares_its_enforcement_intent():
    """Wired gates state whether they block or describe. Driven through the
    audit that reads the declaration, not by grepping the source."""
    import flow_gate_enforcement_audit as FGE
    assert FGE.declared_intent(_PROGRAMS, "pg_rail_geometry_check") == "advisory"


def test_the_declared_intent_matches_the_wiring():
    """Declaring `blocking` while wired audit-only is the contradiction that
    audit exists to catch. Whatever this gate declares must not create one."""
    import flow_gate_enforcement_audit as FGE
    rep = FGE.audit(_PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml",
                    _PROGRAMS)
    assert [c for c in rep["contradictions"]
            if c["gate"].startswith("pg_rail_geometry_check")] == []
