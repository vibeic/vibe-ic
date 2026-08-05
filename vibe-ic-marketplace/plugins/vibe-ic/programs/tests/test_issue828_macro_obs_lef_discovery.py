"""Regression tests for #828 part 1 — the macro-obs gate's default LEF
discovery missed the LEFs that carry the obstructions, and an incomplete LEF
set read as a clean run.

DEFECT SHAPE
------------
Two halves, and the second is the one that makes the first dangerous.

(a) DISCOVERY. The default was two globs:

        sorted(proj.glob("input/pdk/**/*.lef")) +
        sorted(proj.glob("phase3/**/macro*.lef"))

    Both miss by one step. An IP LEF legitimately lives outside `input/pdk/`
    (a `pdk_local` tree is not `pdk`), and a macro LEF staged under `phase3/`
    need not be named `macro*`. So discovery decided the verdict at least as
    much as the geometry did: the same project passed with the default and
    failed when the same LEFs were named with `--macro-lef`.

(b) HONEST SILENCE. "I found no LEF that declares the offending master" and
    "no metal crosses an obstruction" both printed `[PASS]`. The program
    already had a `[CANNOT DETERMINE]` path and its own docstring is emphatic
    that "found no crossings" must not be the same sentence as "had nothing
    to look at" — but that principle was applied to NO LEF AT ALL and not to
    an INCOMPLETE LEF SET, which is the case that actually occurs.

TEST STRUCTURE
--------------
SECTION A holds the BIDIRECTIONAL / BEHAVIOURAL controls — seven of them.
Every one drives `main()` (the real entry point, present before and after)
and asserts on its EXIT CODE, so against the pre-fix tree they fail on a
return-value comparison, never on an AttributeError for a symbol that did not
exist yet. Measured at e3aa9b126 — the whole run was 19 failed / 5 passed,
and these are the seven that matter:

    test_default_discovery_finds_the_lef_that_carries_the_obstruction
        [3 params]                                  assert 0 == 1
        stdout: `[PASS] macro_obs_geometry_intersect: 1 placed instance(s)
                 of 1 master(s) with OBS, 6 supply segment(s) — none spans
                 an obstruction.`  ... while a crossing is right there.
    test_a_placed_master_with_no_lef_anywhere_is_not_a_pass
                                                    assert 0 == 2
    test_incomplete_lef_set_is_not_a_pass_even_when_named_explicitly
                                                    assert 0 == 2
    test_cannot_determine_names_the_unresolved_master
                                                    assert 0 == 2
    test_a_real_crossing_still_outranks_an_incomplete_lef_set
                                                    assert 0 == 1

One Section-A check, `test_the_crossing_was_always_there_when_the_lef_is_named`,
PASSES on both trees by design: it is the control proving the geometry half
was never broken, so every rc==0 above was discovery and nothing else.

SECTION B unit-tests the two new functions directly. Those CANNOT run against
the pre-fix tree, so they are NOT evidence that the defect existed.

SECTION C is the NO-REGRESSION control: every path that did not involve a
missing LEF must behave exactly as before. It passes on BOTH trees.

DISJOINTNESS FROM PR #811. #811 (`2be2ded82`) rewrites `parse_routed_segments`
and adds `parse_via_layers` / `_path_segments` — DEF SPECIALNETS parsing only.
Nothing here touches those; this branch changes `parse_placed_masters` (new),
`discover_macro_lefs` (new), `audit`'s report dict and `main`'s refusals.
Every fixture below keeps its crossing on the FIRST wiring path of a
SPECIALNET entry, so it is visible to the base parser AND to #811's, and no
assertion here depends on which parser is in the tree.

chip-AGNOSTIC: pure LEF/DEF grammar, synthetic layer and master names.
"""
import importlib.util
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
# Fixtures — a macro with an OBS the supply grid runs straight through, and a
# decoy macro that is always discoverable and always clean.
# ---------------------------------------------------------------------------
_CROSSED_LEF = (
    "MACRO ip_block\n"
    "  SIZE 200.0 BY 100.0 ;\n"
    "  OBS\n"
    "    LAYER METX ;\n"
    "      RECT 20.0 20.0 180.0 80.0 ;\n"
    "  END\n"
    "END ip_block\n"
)
# Discoverable by the ORIGINAL glob, and never crossed: its OBS sits far from
# every emitted segment. Its only job is to keep `masters_with_obs` non-empty
# so the run reaches the PASS line instead of an older rc=2 branch.
_DECOY_LEF = (
    "MACRO decoy_block\n"
    "  SIZE 10.0 BY 10.0 ;\n"
    "  OBS\n"
    "    LAYER METX ;\n"
    "      RECT 1.0 1.0 9.0 9.0 ;\n"
    "  END\n"
    "END decoy_block\n"
)
_NO_MACRO_LEF = (
    "VERSION 5.8 ;\n"
    "UNITS\n  DATABASE MICRONS 1000 ;\nEND UNITS\n"
    "LAYER METX\n  TYPE ROUTING ;\nEND METX\n"
)


def _def(components, n_through=6):
    """A DEF placing `components` = [(inst, master, x, y, orient)] with a
    supply grid whose straps run clean through x=100000..400000.

    `ip_block` placed at (200000, 100000) puts its OBS at
    (220000, 120000)..(380000, 180000) in DEF units, so straps at
    y=122000..132000 enter one side and leave the other: a SPAN, not a
    touch."""
    rows = []
    for i in range(n_through):
        y = 122000 + i * 2000
        rows.append(f"- VDD ( * VDD ) + USE POWER + ROUTED METX 140 + SHAPE "
                    f"FOLLOWPIN ( 100000 {y} ) ( 400000 {y} ) ;")
    comps = "\n".join(
        f"- {i} {m} + FIXED ( {x} {y} ) {o} ;" for i, m, x, y, o in components)
    return ("UNITS DISTANCE MICRONS 1000 ;\n"
            f"COMPONENTS {len(components)} ;\n{comps}\nEND COMPONENTS\n"
            "SPECIALNETS 1 ;\n" + "\n".join(rows) + "\nEND SPECIALNETS\n")


def _project(tmp_path, crossed_lef_at, *, with_decoy=True,
             crossed_placed=True):
    """A project whose OBS-carrying LEF sits at `crossed_lef_at` (relative),
    or nowhere at all when `crossed_lef_at` is None."""
    comps = [("u_decoy", "decoy_block", 500000, 500000, "N")]
    if crossed_placed:
        comps.append(("u_ip", "ip_block", 200000, 100000, "N"))
    d = tmp_path / "phase3/stage3/pnr"
    d.mkdir(parents=True)
    (d / "routed.def").write_text(_def(comps))
    if with_decoy:
        p = tmp_path / "input/pdk/std"
        p.mkdir(parents=True)
        (p / "decoy.lef").write_text(_DECOY_LEF)
    if crossed_lef_at is not None:
        p = tmp_path / crossed_lef_at
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_CROSSED_LEF)
    return tmp_path


# ===========================================================================
# SECTION A — BIDIRECTIONAL / BEHAVIOURAL controls.
# All drive main() and assert on the exit code. All FAIL pre-fix.
# ===========================================================================

@pytest.mark.parametrize("where,why", [
    ("input/pdk_local/ip/ip_block.lef",
     "an IP LEF outside input/pdk/ — `pdk_local` is not `pdk`"),
    ("phase3/stage3/pnr/ip_abstract.lef",
     "a macro LEF under phase3/ whose name does not begin `macro`"),
    ("IP/vendor/ip_block.lef",
     "a macro LEF in neither of the two globbed trees"),
])
def test_default_discovery_finds_the_lef_that_carries_the_obstruction(
        tmp_path, where, why):
    """THE DEFECT. The crossing is real and `--macro-lef` has always found
    it; the DEFAULT discovery decided the verdict instead.

    PRE-FIX: rc == 0, `[PASS] ... none spans an obstruction.`
    POST-FIX: rc == 1, the crossing is reported."""
    proj = _project(tmp_path, where)
    assert M.main([str(proj)]) == 1, why


def test_the_crossing_was_always_there_when_the_lef_is_named(tmp_path):
    """Control on the fixture: with `--macro-lef` the geometry half has
    always worked, so a rc==0 above was discovery and nothing else.

    Holds on BOTH trees."""
    proj = _project(tmp_path, "input/pdk_local/ip/ip_block.lef")
    assert M.main([str(proj), "--macro-lef",
                   str(proj / "input/pdk_local/ip/ip_block.lef")]) == 1


def test_a_placed_master_with_no_lef_anywhere_is_not_a_pass(tmp_path):
    """HONEST SILENCE. Here the LEF is genuinely absent — no glob could have
    found it. `ip_block` is placed, nothing declares it, and no crossing is
    found among the masters that ARE declared.

    PRE-FIX: rc == 0 — "found no crossings" printed as if it were "there is
    nothing to find".
    POST-FIX: rc == 2 — cannot-discover is its own state."""
    proj = _project(tmp_path, None)
    assert M.main([str(proj)]) == 2


def test_incomplete_lef_set_is_not_a_pass_even_when_named_explicitly(
        tmp_path):
    """The same refusal on the explicit path: an operator who names only
    SOME of the LEFs gets the same honest answer, not a pass.

    PRE-FIX: rc == 0.  POST-FIX: rc == 2."""
    proj = _project(tmp_path, "input/pdk_local/ip/ip_block.lef")
    assert M.main([str(proj), "--macro-lef",
                   str(proj / "input/pdk/std/decoy.lef")]) == 2


def test_cannot_determine_names_the_unresolved_master(tmp_path, capsys):
    """The refusal has to be actionable: it must say WHICH master it could
    not resolve, otherwise the operator cannot act on it.

    PRE-FIX: rc == 0 and the string is absent from a [PASS] line."""
    proj = _project(tmp_path, None)
    rc = M.main([str(proj)])
    err = capsys.readouterr().err
    assert rc == 2
    assert "ip_block" in err
    assert "INCOMPLETE" in err
    assert "NOT a pass" in err


def test_a_real_crossing_still_outranks_an_incomplete_lef_set(tmp_path):
    """Ordering. A partial check that FOUND a violation must still report the
    violation — the finding is real and actionable, and demoting it to
    `cannot determine` would lose it. Here `ip_block` IS declared and IS
    crossed, while a third placed master has no LEF at all.

    PRE-FIX: rc == 0 — measured, not assumed. The crossing is invisible for
    the same discovery reason as above, so this does NOT pass on both trees.
    POST-FIX: rc == 1, because a crossing outranks incompleteness. It is here
    to pin the ORDER of the two refusals, which is the thing a future edit is
    most likely to get backwards."""
    proj = _project(tmp_path, "input/pdk_local/ip/ip_block.lef")
    d = proj / "phase3/stage3/pnr"
    (d / "routed.def").write_text(_def([
        ("u_decoy", "decoy_block", 500000, 500000, "N"),
        ("u_ip", "ip_block", 200000, 100000, "N"),
        ("u_ghost", "undeclared_block", 900000, 900000, "N"),
    ]))
    assert M.main([str(proj)]) == 1


# ===========================================================================
# SECTION B — unit tests of the NEW functions.
# NOT bidirectional evidence: neither symbol exists pre-fix.
# ===========================================================================

_PINS_SECTION = (
    "PINS 2 ;\n"
    "    - clk + NET clk + DIRECTION INPUT + USE SIGNAL\n"
    "      + PORT\n"
    "        + LAYER Metal2 ( -100 -360 ) ( 100 360 )\n"
    "        + PLACED ( 109920 360 ) N ;\n"
    "    - p + NET p_reg + DIRECTION OUTPUT + USE SIGNAL\n"
    "      + PORT\n"
    "        + LAYER Metal2 ( -100 -360 ) ( 100 360 )\n"
    "        + PLACED ( 106080 360 ) N ;\n"
    "END PINS\n"
)


def test_placed_masters_is_scoped_to_the_components_section():
    """The scoping is what keeps the new refusal from crying wolf.

    `_COMP_RE` has `[^;]*?` between the master token and the placement, and
    a negated class matches newlines, so an unscoped scan reaches into the
    PINS section: a pin with a placed port matches with inst=`clk` and
    MASTER=`+`. The PINS block below is the real shape, copied from
    benchmark-data/ic/spm/v1.5.58_ihp-sg13g2/phase3/stage3/pnr/routed.def,
    where 36 pins produce exactly 36 such phantom matches.

    A phantom master can never resolve to a LEF, so without the scoping the
    new rc=2 refusal would fire on every real design."""
    def_text = (
        "COMPONENTS 2 ;\n"
        "- u_a master_a + FIXED ( 0 0 ) N ;\n"
        "- u_b master_b + PLACED ( 10 10 ) FS ;\n"
        "END COMPONENTS\n" + _PINS_SECTION
    )
    # The unscoped scan really does mint it — otherwise this test would be
    # asserting against a hazard that is not in the fixture.
    assert "+" in {m.group(2) for m in M._COMP_RE.finditer(def_text)}
    assert M.parse_placed_masters(def_text) == {"master_a", "master_b"}


def test_a_pin_with_a_placed_port_does_not_become_an_unresolved_master():
    """The same hazard at the level that matters: a phantom master would
    make `audit` report an unresolved master on a project where every real
    master resolves, and `main` would refuse a run that is genuinely
    clean."""
    def_text = (
        "UNITS DISTANCE MICRONS 1000 ;\n"
        "COMPONENTS 1 ;\n"
        "- u_ip ip_block + FIXED ( 900000 900000 ) N ;\n"
        "END COMPONENTS\n" + _PINS_SECTION +
        "SPECIALNETS 0 ;\nEND SPECIALNETS\n"
    )
    rep = M.audit(def_text, [_CROSSED_LEF])
    assert rep["placed_masters_without_lef"] == []


def test_placed_masters_falls_back_to_the_whole_text():
    """No delimited COMPONENTS section -> scan everything, which is the
    pre-existing behaviour and no worse than it."""
    assert M.parse_placed_masters(
        "- u_a master_a + FIXED ( 0 0 ) N ;\n") == {"master_a"}


@pytest.mark.parametrize("bad", [None, 0, b"bytes", []])
def test_placed_masters_tolerates_a_non_string(bad):
    assert M.parse_placed_masters(bad) == set()


def test_discovery_keeps_the_two_original_globs_first(tmp_path):
    """Order is load-bearing: `audit` merges with `dict.update`, so the LAST
    file wins a master declared twice. Every project that already resolved
    must keep resolving identically, so the legacy globs come first and
    newly visible files are appended."""
    (tmp_path / "input/pdk/std").mkdir(parents=True)
    (tmp_path / "input/pdk/std/a.lef").write_text(_DECOY_LEF)
    (tmp_path / "phase3/stage3").mkdir(parents=True)
    (tmp_path / "phase3/stage3/macro_b.lef").write_text(_CROSSED_LEF)
    (tmp_path / "IP").mkdir()
    (tmp_path / "IP/c.lef").write_text(_CROSSED_LEF)
    names = [p.name for p in M.discover_macro_lefs(tmp_path)]
    assert names == ["a.lef", "macro_b.lef", "c.lef"]


def test_discovery_filters_on_content_not_on_name(tmp_path):
    """A `.lef` that declares no MACRO is not a macro LEF, whatever it is
    called or wherever it sits; a file that DOES declare one is, likewise."""
    (tmp_path / "input/pdk").mkdir(parents=True)
    (tmp_path / "input/pdk/tech.lef").write_text(_NO_MACRO_LEF)
    (tmp_path / "input/pdk/macro_looking.lef").write_text(_NO_MACRO_LEF)
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor/anything.lef").write_text(_CROSSED_LEF)
    assert [p.name for p in M.discover_macro_lefs(tmp_path)] \
        == ["anything.lef"]


def test_discovery_does_not_return_the_same_file_twice(tmp_path):
    """The three globs overlap by construction; a file matched by two of them
    would otherwise be read, parsed and merged twice."""
    (tmp_path / "input/pdk").mkdir(parents=True)
    (tmp_path / "input/pdk/macro_x.lef").write_text(_CROSSED_LEF)
    assert len(M.discover_macro_lefs(tmp_path)) == 1


def test_audit_reports_the_denominator_it_could_not_see():
    def_text = _def([("u_a", "ip_block", 200000, 100000, "N"),
                     ("u_ghost", "nowhere_block", 900000, 900000, "N")])
    rep = M.audit(def_text, [_CROSSED_LEF])
    assert rep["placed_masters"] == 2
    assert rep["placed_masters_without_lef"] == ["nowhere_block"]
    assert rep["masters_declared_by_lef"] == ["ip_block"]


def test_audit_reports_an_empty_unresolved_set_when_everything_resolves():
    """A master DECLARED by a LEF but carrying no OBS still counts as
    resolved — the gate read its definition and learned it has nothing to
    obstruct. Only a master with no declaration at all is unresolved."""
    def_text = _def([("u_a", "ip_block", 200000, 100000, "N"),
                     ("u_p", "plain_block", 900000, 900000, "N")])
    plain = "MACRO plain_block\n  SIZE 5.0 BY 5.0 ;\nEND plain_block\n"
    rep = M.audit(def_text, [_CROSSED_LEF, plain])
    assert rep["placed_masters_without_lef"] == []


# ===========================================================================
# SECTION C — NO-REGRESSION controls. Pass on BOTH trees.
# ===========================================================================

def test_a_fully_resolved_clean_project_still_passes(tmp_path):
    """The whole point of not over-firing: when every placed master resolves
    and nothing crosses, this is still a PASS."""
    proj = _project(tmp_path, None, crossed_placed=False)
    assert M.main([str(proj)]) == 0


def test_no_def_is_still_not_a_pass(tmp_path):
    (tmp_path / "input/pdk/std").mkdir(parents=True)
    (tmp_path / "input/pdk/std/decoy.lef").write_text(_DECOY_LEF)
    assert M.main([str(tmp_path)]) == 2


def test_no_lef_at_all_is_still_not_a_pass(tmp_path):
    """The three tracked corpus cells are exactly this case (0 `.lef` files),
    and they must keep returning 2 through the original branch."""
    proj = _project(tmp_path, None, with_decoy=False)
    assert M.main([str(proj)]) == 2


def test_no_macro_declares_an_obs_is_still_not_a_pass(tmp_path):
    lef = tmp_path / "m.lef"
    lef.write_text("MACRO plain\n  SIZE 10.0 BY 10.0 ;\nEND plain\n")
    d = tmp_path / "phase3/stage3/pnr"
    d.mkdir(parents=True)
    (d / "routed.def").write_text(_def([("u_a", "plain", 0, 0, "N")]))
    assert M.main([str(tmp_path), "--macro-lef", str(lef)]) == 2
