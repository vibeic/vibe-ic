"""The macro-obs gate's completeness claim must name the property its verdict
CONSUMES, not a weaker precondition that stands in for it.

THE MEASURED LINE, from a blocking gate on a real run. Every clause is TRUE:

    [PASS] macro_obs_geometry_intersect: 1698 placed instance(s) of 325
           master(s) with OBS, 489 supply segment(s), 0 path(s) abandoned —
           none spans an obstruction. All 79 placed master(s) resolved to a LEF.

28 supply segments spanning a declared obstruction went unreported underneath
it. The master DID resolve to a LEF; the file it resolved to did not carry the
obstruction. **"resolved to a LEF" is not "its obstructions were read"** — the
first is a PRECONDITION (some file names this master), the second is what the
verdict actually reads (that master's OBS rects reached the intersection). The
published completeness line was computed from the first and reads as the second.

THE GENERAL SHAPE, which is what these tests are written against: a gate
publishes a coverage line derived from a PROXY for the thing its verdict
depends on. "N of N resolved" answers a question ADJACENT to "N of N supplied
the evidence the verdict needs", and the two counts can differ silently.

WHAT IS ASSERTED, AND WHY IT IS NOT ASSERTED AGAINST THE IMPLEMENTATION
-----------------------------------------------------------------------
Every test in SECTION A and SECTION B drives `main()` — the entry point that
exists before and after the fix — and asserts on its EXIT CODE and its PRINTED
TEXT. None reads a report key the fix introduces, so none can fail pre-fix with
a KeyError for a symbol that did not exist yet; they fail on a return-value or
a text property. SECTION C's two back-compat tests call `audit()` with the
two-argument signature that predates the fix.

`test_pass_line_carries_no_universal_claim_wider_than_the_evidence` is the one
that states the rule itself rather than one instance of it: it scans the whole
output for any `all N` / `every N` and requires N never to exceed the number of
masters that supplied the consumed evidence. Any other correct fix — different
wording, different mechanism — satisfies it; the pre-fix line does not, because
`All 3 placed master(s) resolved to a LEF` quantifies over 3 while 1 master
supplied obstruction geometry.

THE OVER-CORRECTION THIS GUARDS AGAINST (SECTION B, and it is the half that
matters). A rule demanding that every gate prove TOTAL coverage would fire on
every honest partial measurement, and partial coverage here is normal: fillers,
taps and most standard cells legitimately declare no OBS at all. So the target
is the MISMATCH between what a claim says and what it establishes, never the
existence of a gap. Section B pins four states that must STILL PASS:

    * a placed master that legitimately declares no OBS          (rc 0)
    * the same LEF staged twice, identical OBS                   (rc 0)
    * a master whose winning declaration is the RICHEST one      (rc 0)
    * contradictory declarations on a master that is NOT placed  (rc 0)

and one that must still BLOCK unchanged:

    * a real crossing, same finding count, no fabrication        (rc 1)

WHY THE CONTRADICTION CASE IS rc 2 AND NOT rc 1. When two read LEFs disagree
about a placed master's obstruction, promoting the richer declaration would let
an obsolete LEF left in the project FABRICATE a crossing on a gate that blocks.
A fabricated finding is worse than a missed one, so the gate refuses to certify
and names both files instead of arbitrating between them.

chip-AGNOSTIC and PDK-AGNOSTIC: pure LEF/DEF grammar, invented master and layer
names, no vendor, process or part number anywhere.
"""
import os
import importlib.util
import re
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "macro_obs_geometry_intersect_check",
    _PROGRAMS / "macro_obs_geometry_intersect_check.py")
M = importlib.util.module_from_spec(_spec)
sys.modules["macro_obs_geometry_intersect_check"] = M
try:
    _spec.loader.exec_module(M)
except SystemExit:
    pass


# ---------------------------------------------------------------------------
# Fixtures. `ip_block` is 50x40 with a full-footprint obstruction on METX;
# placed at (10000, 10000) DBU its obstruction covers 10..60 x 10..50 um, and
# the supply strap at y=20000 DBU runs from x=0 to x=100000 DBU — in one side
# and out the other, a SPAN and not a touch.
# ---------------------------------------------------------------------------
_WITH_OBS = (
    "VERSION 5.8 ;\n"
    "MACRO ip_block\n"
    "  CLASS BLOCK ;\n"
    "  SIZE 50.0 BY 40.0 ;\n"
    "  OBS\n"
    "    LAYER METX ;\n"
    "      RECT 0.0 0.0 50.0 40.0 ;\n"
    "  END\n"
    "END ip_block\n"
)

# The same master, declared WITHOUT an OBS section. This is an abstract /
# black-box view: legitimate as a file, and fatal as the winner of a merge.
_NO_OBS = (
    "VERSION 5.8 ;\n"
    "MACRO ip_block\n"
    "  CLASS BLOCK ;\n"
    "  SIZE 50.0 BY 40.0 ;\n"
    "  PIN VDD\n"
    "    DIRECTION INOUT ;\n"
    "    USE POWER ;\n"
    "  END VDD\n"
    "END ip_block\n"
)

# A second obstruction-bearing master, placed far from every strap. Its job is
# to keep `masters_with_obs` non-empty so a run reaches the PASS line rather
# than an unrelated rc=2 branch.
_DECOY = (
    "VERSION 5.8 ;\n"
    "MACRO decoy_block\n"
    "  CLASS BLOCK ;\n"
    "  SIZE 10.0 BY 10.0 ;\n"
    "  OBS\n"
    "    LAYER METX ;\n"
    "      RECT 0.0 0.0 10.0 10.0 ;\n"
    "  END\n"
    "END decoy_block\n"
)

# Masters that genuinely have nothing to obstruct. Ordinary, and the reason a
# rule demanding total coverage would be a bug rather than a gate.
_OBSLESS_CELLS = (
    "VERSION 5.8 ;\n"
    "MACRO filler_cell\n"
    "  CLASS CORE FILLER ;\n"
    "  SIZE 1.0 BY 10.0 ;\n"
    "END filler_cell\n"
    "MACRO welltap_cell\n"
    "  CLASS CORE WELLTAP ;\n"
    "  SIZE 2.0 BY 10.0 ;\n"
    "END welltap_cell\n"
)

_UNPLACED_WITH_OBS = (
    "VERSION 5.8 ;\n"
    "MACRO shelf_block\n"
    "  CLASS BLOCK ;\n"
    "  SIZE 5.0 BY 5.0 ;\n"
    "  OBS\n"
    "    LAYER METX ;\n"
    "      RECT 0.0 0.0 5.0 5.0 ;\n"
    "  END\n"
    "END shelf_block\n"
)
_UNPLACED_NO_OBS = (
    "VERSION 5.8 ;\n"
    "MACRO shelf_block\n"
    "  CLASS BLOCK ;\n"
    "  SIZE 5.0 BY 5.0 ;\n"
    "END shelf_block\n"
)


def _def(components, ip_y=10000):
    """A routed DEF placing `components` = [(inst, master, x, y)] with one
    METX follow-pin strap along y=20000 DBU from x=0 to x=100000 DBU."""
    rows = "\n".join(f"- {i} {m} + PLACED ( {x} {y} ) N ;"
                     for i, m, x, y in components)
    return (
        "VERSION 5.8 ;\n"
        "DESIGN top ;\n"
        "UNITS DISTANCE MICRONS 1000 ;\n"
        f"COMPONENTS {len(components)} ;\n"
        f"{rows}\n"
        "END COMPONENTS\n"
        "SPECIALNETS 1 ;\n"
        "- VDD\n"
        "  + ROUTED METX 480 + SHAPE FOLLOWPIN ( 0 20000 ) ( 100000 * )\n"
        "  + USE POWER ;\n"
        "END SPECIALNETS\n"
        "END DESIGN\n"
    )


# `ip_block` at (10000, 10000) is crossed; the decoy at (400000, 400000) and
# the obstruction-less cells are not.
_CROSSED = [("u_ip", "ip_block", 10000, 10000),
            ("u_dec", "decoy_block", 400000, 400000)]
# `ip_block` lifted to y=200000 so its obstruction sits above the strap: a
# clean run with real, uncrossed obstruction geometry in it.
_CLEAN = [("u_ip", "ip_block", 10000, 200000),
          ("u_dec", "decoy_block", 400000, 400000),
          ("u_f", "filler_cell", 1000, 1000),
          ("u_t", "welltap_cell", 3000, 1000)]


def _project(tmp_path, def_text, lefs):
    """`lefs` = [(relative_path, text)], written in the order given. Default
    discovery reads `input/pdk/**` before anything else, so a file staged
    elsewhere is read later and wins the merge — which is the mechanism under
    test, not an accident of the fixture."""
    proj = tmp_path / "cell"
    (proj / "phase3" / "stage3" / "pnr").mkdir(parents=True)
    (proj / "phase3" / "stage3" / "pnr" / "routed.def").write_text(def_text)
    for rel, text in lefs:
        p = proj / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return proj


def _run(capsys, proj, *extra):
    rc = M.main([str(proj), *extra])
    cap = capsys.readouterr()
    return rc, cap.out + cap.err

def test_pass_line_carries_no_universal_claim_wider_than_the_evidence(
        tmp_path, capsys):
    """THE RULE ITSELF, not one instance of it.

    A completeness claim must be computed from the property the verdict
    consumes. Scan the entire output for any universal quantifier over a count
    — `all N`, `every N` — and require N never to exceed the number of masters
    that actually supplied obstruction geometry.

    Pre-fix the line reads `All 4 placed master(s) resolved to a LEF` while 2
    masters supplied obstruction geometry, so N=4 > 2 and this fails on the
    text, not on a missing symbol. Any correct fix passes it regardless of how
    it words the result."""
    proj = _project(tmp_path, _def(_CLEAN), [
        ("input/pdk/full.lef", _WITH_OBS + _DECOY + _OBSLESS_CELLS),
    ])
    rc, out = _run(capsys, proj)
    assert rc == 0, f"this fixture is clean and must pass.\n{out}"
    # ip_block and decoy_block supplied OBS; filler_cell and welltap_cell did
    # not. The consumed denominator is 2 of 4 placed masters.
    consumed = 2
    claims = [int(n) for n in
              re.findall(r"\b(?:all|every)\s+(\d+)\b", out, re.I)]
    over = [n for n in claims if n > consumed]
    assert not over, (
        f"the output quantifies universally over {over} while only {consumed} "
        f"placed master(s) supplied the evidence the verdict reads. "
        f"A completeness claim must be computed from the consumed property, "
        f"not from 'resolved to a LEF'.\n{out}")


def test_pass_publishes_the_consumed_count_and_the_precondition_count(
        tmp_path, capsys):
    """Both numbers, so the reader can SEE the gap rather than infer its
    absence. 2 of 4 placed masters supplied obstruction geometry; the output
    must state a 2-of-4 relationship and must not stop at the 4."""
    proj = _project(tmp_path, _def(_CLEAN), [
        ("input/pdk/full.lef", _WITH_OBS + _DECOY + _OBSLESS_CELLS),
    ])
    rc, out = _run(capsys, proj)
    assert rc == 0, out
    assert re.search(r"\b2\s+of\s+4\b", out), (
        "the PASS line must publish the CONSUMED count against the placed "
        f"total, so the gap is visible without re-deriving it.\n{out}")
    assert re.search(r"filler_cell|welltap_cell", out), (
        "the placed masters that contributed nothing to the verdict must be "
        f"nameable from the output.\n{out}")


def test_a_found_crossing_discloses_that_its_count_is_a_floor(
        tmp_path, capsys):
    """When a crossing IS found and OTHER evidence was discarded, the number
    reported is a lower bound. A FAIL that publishes a total it cannot support
    is the same defect as a PASS that does."""
    # `decoy_block` is crossed for real; `ip_block`'s obstruction is discarded
    # by an abstract read later.
    crossed_decoy = [("u_ip", "ip_block", 10000, 10000),
                     ("u_dec", "decoy_block", 5000, 15000)]
    proj = _project(tmp_path, _def(crossed_decoy), [
        ("input/pdk/full.lef", _WITH_OBS + _DECOY),
        ("ip/abstract.lef", _NO_OBS),
    ])
    rc, out = _run(capsys, proj)
    assert rc == 1, f"a real crossing must still block.\n{out}"
    assert "FLOOR" in out.upper(), (
        "a FAIL count computed from an input set that lost evidence must be "
        f"published as a floor.\n{out}")


def test_a_refusal_names_every_reason_it_has(tmp_path, capsys):
    """Discarded OBS evidence and a truncated wiring path are both rc=2. The
    branch that returns first must not swallow the other's evidence, or the
    refusal publishes half a reason — the same shape this gate exists to
    catch, one scale down."""
    # A via that is not declared in this DEF's VIAS section truncates the path.
    d = _def(_CROSSED).replace(
        "( 0 20000 ) ( 100000 * )",
        "( 0 20000 ) via_from_tech_lef ( 100000 * )")
    proj = _project(tmp_path, d, [
        ("input/pdk/full.lef", _WITH_OBS + _DECOY),
        ("ip/abstract.lef", _NO_OBS),
    ])
    rc, out = _run(capsys, proj)
    assert rc == 2, out
    assert "ip_block" in out, f"the discarded declaration is not named.\n{out}"
    assert "ABANDONED" in out.upper(), (
        f"the truncated path is not named alongside it.\n{out}")


# ===========================================================================
# SECTION B — the over-correction. Every one of these must STILL PASS.
# A rule that demanded total coverage would fire on all four.
# ===========================================================================

def test_legitimately_obstruction_less_placed_masters_still_pass(
        tmp_path, capsys):
    """THE ONE THAT MATTERS. Fillers and taps declare no OBS; that is ordinary,
    not a defect, and half the placed masters supplying no obstruction geometry
    must not become a refusal. The target is the MISMATCH between claim and
    evidence, never the existence of a gap."""
    proj = _project(tmp_path, _def(_CLEAN), [
        ("input/pdk/full.lef", _WITH_OBS + _DECOY + _OBSLESS_CELLS),
    ])
    rc, out = _run(capsys, proj)
    assert rc == 0, (
        "partial obstruction coverage is legitimate and must remain a PASS; "
        f"got rc={rc}.\n{out}")


def test_the_same_lef_staged_twice_still_passes(tmp_path, capsys):
    """A PDK or IP LEF copied into two locations is ordinary staging. The two
    declarations agree, nothing was discarded, and the run is clean."""
    body = _WITH_OBS + _DECOY + _OBSLESS_CELLS
    proj = _project(tmp_path, _def(_CLEAN), [
        ("input/pdk/full.lef", body),
        ("phase3/staged/full.lef", body),
    ])
    rc, out = _run(capsys, proj)
    assert rc == 0, (
        "identical duplicate declarations discard no evidence and must not "
        f"trip the guard; got rc={rc}.\n{out}")


def test_a_richer_winning_declaration_still_passes(tmp_path, capsys):
    """The winner carries every rect the other does AND one more. Nothing was
    lost — a guard that fired here would be measuring 'declared twice' rather
    than 'evidence not consumed'."""
    richer = _WITH_OBS.replace(
        "      RECT 0.0 0.0 50.0 40.0 ;\n",
        "      RECT 0.0 0.0 50.0 40.0 ;\n      RECT 1.0 1.0 4.0 4.0 ;\n")
    proj = _project(tmp_path, _def(_CLEAN), [
        ("input/pdk/full.lef", _WITH_OBS + _DECOY + _OBSLESS_CELLS),
        ("phase3/staged/richer.lef", richer),
    ])
    rc, out = _run(capsys, proj)
    assert rc == 0, (
        "the consumed set is a superset of every other declaration, so no "
        f"evidence was discarded; got rc={rc}.\n{out}")


def test_contradictory_declarations_on_an_unplaced_master_still_pass(
        tmp_path, capsys):
    """An obstruction on a master that was never placed occupies no area in
    this design and can never be crossed. Flagging it would make the guard fire
    on library contents rather than on this run's verdict."""
    proj = _project(tmp_path, _def(_CLEAN), [
        ("input/pdk/full.lef", _WITH_OBS + _DECOY + _OBSLESS_CELLS
         + _UNPLACED_WITH_OBS),
        ("phase3/staged/shelf.lef", _UNPLACED_NO_OBS),
    ])
    rc, out = _run(capsys, proj)
    assert rc == 0, (
        "a master that is not placed cannot be crossed and must not decide "
        f"this verdict; got rc={rc}.\n{out}")


def test_a_real_crossing_still_blocks_with_the_same_finding(tmp_path, capsys):
    """No swallowing. With a single consistent LEF set the crossing is found,
    the exit code is still 1, and the instance is still named. A fix that
    tightened a filter until the count reached zero would fail here."""
    proj = _project(tmp_path, _def(_CROSSED), [
        ("input/pdk/full.lef", _WITH_OBS + _DECOY),
    ])
    rc, out = _run(capsys, proj)
    assert rc == 1, f"the crossing must still block.\n{out}"
    assert "u_ip" in out and "ip_block" in out, out
    assert "1 supply segment(s) SPAN" in out, (
        f"exactly the one real crossing, neither swallowed nor multiplied.\n"
        f"{out}")


def test_no_fabrication_on_a_clean_single_lef_run(tmp_path, capsys):
    """The mirror of the previous test. A clean run with real obstruction
    geometry in it stays clean — the guard must not invent a crossing, which
    on a blocking gate is strictly worse than missing one."""
    proj = _project(tmp_path, _def(_CLEAN), [
        ("input/pdk/full.lef", _WITH_OBS + _DECOY + _OBSLESS_CELLS),
    ])
    rc, out = _run(capsys, proj)
    assert rc == 0, out
    assert "SPAN" not in out, f"a crossing was fabricated.\n{out}"


# ===========================================================================
# SECTION C — the merge refactor changed no geometry, and the old call
# signature still works.
# ===========================================================================

def test_audit_still_accepts_the_two_argument_call(tmp_path):
    """`audit(def_text, lef_texts)` is the shape every existing caller and
    every existing test uses. The label argument is optional and positional."""
    rep = M.audit(_def(_CROSSED), [_WITH_OBS + _DECOY])
    assert len(rep["findings"]) == 1
    assert rep["findings"][0]["master"] == "ip_block"


# --------------------------------------------------------------------------
# SUPERSEDED, and recorded rather than deleted silently.
#
# Three tests here asserted that the merge keeps LAST-WRITE-WINS geometry and
# answers rc=2 CANNOT DETERMINE when an OBS-less abstract is read last. That was
# this change's original design, and it was the right call against the main it
# was written on.
#
# `merge_macro_obs` then landed and went further: an empty declaration can no
# longer WIN, so the geometry is corrected and the gate ANSWERS — rc=1 with the
# crossings named — instead of refusing. Refusing is strictly weaker than
# answering: on the measured project the refusal reports nothing while the
# answer reports 28 supply segments spanning a declared obstruction.
#
# What survives from the original design, and is kept below, is its real
# contribution: a conflict a reader cannot act on is barely better than a wrong
# pass, so the record must name WHICH master and WHICH files disagreed.
# --------------------------------------------------------------------------
def test_an_obs_less_declaration_cannot_win_and_the_gate_answers(tmp_path):
    """The composed behaviour: not a pass, and not a refusal either."""
    import importlib.util, sys as _s
    sp = importlib.util.spec_from_file_location(
        "_mo", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "macro_obs_geometry_intersect_check.py"))
    g = importlib.util.module_from_spec(sp); _s.modules["_mo"] = g
    sp.loader.exec_module(g)
    full = """
MACRO ip_block
  SIZE 100.0 BY 60.0 ;
  OBS
    LAYER MET1 ;
      RECT 0 0 100.0 60.0 ;
  END
END ip_block
"""
    abstract = """
MACRO ip_block
  SIZE 100.0 BY 60.0 ;
END ip_block
"""
    merged, conflicts = g.merge_macro_obs(
        [g.parse_macro_obs(full), g.parse_macro_obs(abstract)],
        ["full.lef", "abstract.lef"])
    assert len(merged["ip_block"]["obs"]) == 1, (
        "the OBS-less abstract was read LAST and must not have won")
    assert conflicts == [], "an empty declaration is not a disagreement"


def test_a_real_disagreement_names_the_master_and_both_files(tmp_path):
    """The surviving contribution of the original design. Two files that BOTH
    describe obstructions, differently, is a real ambiguity — and a record a
    reader cannot act on is barely better than a wrong pass."""
    import importlib.util, sys as _s
    sp = importlib.util.spec_from_file_location(
        "_mo2", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "macro_obs_geometry_intersect_check.py"))
    g = importlib.util.module_from_spec(sp); _s.modules["_mo2"] = g
    sp.loader.exec_module(g)
    one = """
MACRO ip_block
  SIZE 100.0 BY 60.0 ;
  OBS
    LAYER MET1 ;
      RECT 0 0 100.0 60.0 ;
  END
END ip_block
"""
    two = """
MACRO ip_block
  SIZE 100.0 BY 60.0 ;
  OBS
    LAYER MET1 ;
      RECT 0 0 100.0 60.0 ;
    LAYER MET2 ;
      RECT 0 0 100.0 60.0 ;
  END
END ip_block
"""
    _, conflicts = g.merge_macro_obs(
        [g.parse_macro_obs(one), g.parse_macro_obs(two)],
        ["m3.lef", "m5.lef"])
    assert len(conflicts) == 1, conflicts
    c = conflicts[0]
    assert c["master"] == "ip_block"
    assert {c["kept_from"], c["other_from"]} == {"m3.lef", "m5.lef"}, c
    assert c["kept_rect_count"] < c["other_rect_count"], (
        "the floor must win — on a blocking gate an over-report is a false "
        "accusation, an under-report is a gap")
