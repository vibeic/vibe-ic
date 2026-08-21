"""issue #389 — an explicitly NAMED `--pdk` this runner cannot resolve must
FAIL, on EVERY resolution lane, and a registered name must resolve to THAT PDK.

WHY THESE TESTS EXIST IN THIS SHAPE
-----------------------------------
The original #389 fix put its `raise` at the TAIL of `_detect_pdk`, so it only
guarded the lane where the project carries no usable `input/pdk/`. Measured on
918bf1e7 (v1.6.30), two other lanes still returned BYTE-IDENTICAL results for a
real-but-unregistered PDK and for an invented one:

    project has usable input/pdk/  ->  both -> PdkConfig(name='custom:pdk')
    project has empty  input/pdk/  ->  both -> None -> caller exits 0

`test_lane_project_local_pdk_*` and `test_lane_empty_input_pdk_*` are the tests
that FAIL against that tree — they are the discriminating ones. The tail-lane
test passes both before and after, so it is a NON-REGRESSION guard, not
evidence; it is labelled as such rather than counted as proof.

Both directions are asserted TOGETHER on purpose. "unknown fails" alone would
pass on a resolver that refuses everything; "registered resolves" alone is what
already passed while the defect was live. Neither is evidence without the other.

These are UNIT tests: no docker, no image. The registry is swapped for an
in-memory one and `_pdk_config_from_registry` is stubbed, so what is under test
is the resolver's ACCEPTANCE LOGIC, not what any image happens to ship.

chip/PDK-AGNOSTIC: the registered name used is read out of the fixture registry
rather than spelled into an assertion.
"""
import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402


UNREGISTERED_REAL = "ihp-sg13cmos5l-not-registered-here"
INVENTED = "totally-made-up-pdk-xyz"


@pytest.fixture
def registry(tmp_path, monkeypatch):
    """Install a two-entry in-memory registry and clear the module cache.

    Returns the name of the one registered, container-backed PDK."""
    reg = {
        "schema_version": 1,
        "pdks": [
            {"name": "fixture-pdk-alpha",
             "container_path": "/foss/pdks/fixture-pdk-alpha",
             "liberty_glob": "libs.ref/x/lib/x.lib",
             "tech_lef_glob": "libs.ref/x/lef/x_tech.lef",
             "cell_lef_glob": "libs.ref/x/lef/x.lef",
             "site": "FixtureSite", "metal_prefix": "Metal"},
            # a placeholder entry with no container_path, as the real registry
            # carries — it is still a legal --pdk value.
            {"name": "fixture-placeholder"},
        ],
    }
    f = tmp_path / "pdk_registry.json"
    f.write_text(json.dumps(reg))
    monkeypatch.setattr(R, "PROGRAMS_DIR", tmp_path)
    R._pdk_registry_entry._cache.clear()
    yield "fixture-pdk-alpha"
    R._pdk_registry_entry._cache.clear()


@pytest.fixture
def resolvable(monkeypatch):
    """Make registry-declared assets resolve without a container, so a test
    that reaches the registry lane succeeds for reasons of ACCEPTANCE rather
    than of asset availability."""
    def _fake(project, reg):
        root = reg["container_path"]
        return R.PdkConfig(
            name=reg["name"],
            liberty=f"{root}/{reg['liberty_glob']}",
            tech_lef=f"{root}/{reg['tech_lef_glob']}",
            cell_lef=f"{root}/{reg['cell_lef_glob']}",
            cell_gds=None, drc_deck=None,
            site=reg.get("site"), metal_prefix=reg.get("metal_prefix"))
    monkeypatch.setattr(R, "_pdk_config_from_registry", _fake)


def _project_with_local_pdk(tmp_path: Path) -> Path:
    """A project carrying its OWN usable input/pdk/ — the lane that produced
    PdkConfig(name='custom:pdk') for any unknown name."""
    p = tmp_path / "proj_local"
    (p / "input" / "pdk" / "liberty").mkdir(parents=True)
    (p / "input" / "pdk" / "lef").mkdir(parents=True)
    (p / "input" / "pdk" / "liberty" / "fixture_tt_25C.lib").write_text(
        "library (fixture_typ) { cell (INV) {} }\n")
    (p / "input" / "pdk" / "lef" / "fixture_tech.lef").write_text(
        "SITE FixtureCoreSite\n  CLASS CORE ;\nEND FixtureCoreSite\n"
        "LAYER FM1\n  TYPE ROUTING ;\nEND FM1\n")
    (p / "input" / "pdk" / "lef" / "fixture_stdcell.lef").write_text(
        "MACRO INV\n  CLASS CORE ;\nEND INV\n")
    return p


def _project_with_empty_input_pdk(tmp_path: Path) -> Path:
    """A project whose input/pdk/ exists but holds nothing usable — the lane
    that returned None, which the caller renders as `[SKIP]` and exit 0."""
    p = tmp_path / "proj_empty"
    (p / "input" / "pdk" / "liberty").mkdir(parents=True)
    (p / "input" / "pdk" / "lef").mkdir(parents=True)
    return p


def _bare_project(tmp_path: Path) -> Path:
    p = tmp_path / "proj_bare"
    p.mkdir()
    return p


# ---------------------------------------------------------------------------
# Direction 1 — an unknown NAMED pdk must FAIL. One test per resolution lane.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("unknown", [UNREGISTERED_REAL, INVENTED])
def test_lane_project_local_pdk_unknown_name_raises(
        tmp_path, registry, unknown):
    """DISCRIMINATING. Against the unfixed tree this returns
    PdkConfig(name='custom:pdk') instead of raising."""
    proj = _project_with_local_pdk(tmp_path)
    with pytest.raises(ValueError) as ei:
        R._detect_pdk(proj, override=unknown)
    assert unknown in str(ei.value)


@pytest.mark.parametrize("unknown", [UNREGISTERED_REAL, INVENTED])
def test_lane_empty_input_pdk_unknown_name_raises(tmp_path, registry, unknown):
    """DISCRIMINATING. Against the unfixed tree this returns None, which the
    caller reports as `[SKIP] ... no usable PDK detected` and exits 0."""
    proj = _project_with_empty_input_pdk(tmp_path)
    with pytest.raises(ValueError) as ei:
        R._detect_pdk(proj, override=unknown)
    assert unknown in str(ei.value)


@pytest.mark.parametrize("unknown", [UNREGISTERED_REAL, INVENTED])
def test_lane_bare_project_unknown_name_raises(tmp_path, registry, unknown):
    """NON-REGRESSION guard, not evidence: this lane was already closed by the
    original #389 tail-raise, so it passes before and after."""
    with pytest.raises(ValueError) as ei:
        R._detect_pdk(_bare_project(tmp_path), override=unknown)
    assert unknown in str(ei.value)


def test_refusal_names_the_value_and_lists_registered_names(
        tmp_path, registry):
    """The message must be actionable: the rejected value AND the legal set.
    An operator who mistyped cannot act on 'unknown PDK' alone.

    The expected names are built from the FIXTURE REGISTRY and the branch
    names as literals — deliberately NOT from `_known_pdk_names()`. Sourcing
    them from the symbol under test would make this fail with AttributeError
    on an unfixed tree (proving only that a symbol is absent) instead of
    failing on the behaviour."""
    expected = {"fixture-pdk-alpha", "fixture-placeholder",
                "sky130A", "nangate45", "asap7"}
    with pytest.raises(ValueError) as ei:
        R._detect_pdk(_bare_project(tmp_path), override=INVENTED)
    msg = str(ei.value)
    assert INVENTED in msg
    for name in sorted(expected):
        assert name in msg, f"refusal message omits selectable name {name!r}"


def test_unregistered_and_invented_are_no_longer_indistinguishable(
        tmp_path, registry):
    """The #389 signature itself: the two used to produce byte-identical
    results. They must now BOTH fail AND each name itself."""
    proj = _project_with_local_pdk(tmp_path)
    outs = {}
    for name in (UNREGISTERED_REAL, INVENTED):
        with pytest.raises(ValueError) as ei:
            R._detect_pdk(proj, override=name)
        outs[name] = str(ei.value)
    assert UNREGISTERED_REAL in outs[UNREGISTERED_REAL]
    assert INVENTED in outs[INVENTED]
    assert outs[UNREGISTERED_REAL] != outs[INVENTED]


# ---------------------------------------------------------------------------
# Direction 2 — a REGISTERED pdk must resolve to THAT pdk. Without this the
# tests above would pass on a resolver that refuses everything.
# ---------------------------------------------------------------------------

def test_registered_name_resolves_to_that_pdk(tmp_path, registry, resolvable):
    name = registry
    cfg = R._detect_pdk(_bare_project(tmp_path), override=name)
    assert cfg is not None, f"registered PDK {name!r} failed to resolve"
    assert cfg.name == name
    # the assets must be that PDK's own, not another entry's
    assert f"/{name}/" in cfg.liberty
    assert f"/{name}/" in cfg.tech_lef
    assert f"/{name}/" in cfg.cell_lef


def test_registered_name_resolves_even_with_project_local_pdk_present(
        tmp_path, registry, resolvable):
    """The named-PDK contract must WIN over a project-local input/pdk/ — the
    gate must not have turned the registry lane into a refusal."""
    cfg = R._detect_pdk(_project_with_local_pdk(tmp_path), override=registry)
    assert cfg is not None and cfg.name == registry


def test_placeholder_entry_without_container_path_is_accepted(
        tmp_path, registry):
    """A registry entry with no container_path is still a LEGAL name; the gate
    must reject on absence-from-the-registry, not on asset shape. It may then
    fail later at asset resolution — that is a different, disclosed failure."""
    assert "fixture-placeholder" in R._known_pdk_names()
    try:
        R._detect_pdk(_bare_project(tmp_path), override="fixture-placeholder")
    except ValueError as e:                       # must NOT be the name gate
        assert "unknown PDK" not in str(e)
    except SystemExit:
        pass                                      # asset-resolution refusal


# ---------------------------------------------------------------------------
# Scope guards for the NEW gate — these call the new helper directly, so on an
# unfixed tree they fail with AttributeError (symbol absent). That proves only
# that the symbol is missing, so they are NOT counted as defect evidence; they
# exist to pin the gate's BLAST RADIUS (what it must keep accepting).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("override", [None, "auto", ""])
def test_auto_detect_is_not_gated(tmp_path, registry, override):
    """Defaulting is legitimate when the operator named nothing. Only
    substituting for a name they DID give is the defect."""
    R._assert_pdk_name_resolvable(override)       # must not raise


def test_project_local_pdk_is_still_reachable_via_auto(tmp_path, registry):
    """THE COST CONTROL for closing the project-local lane to unknown names.

    An earlier fix kept that lane open so a project shipping its own PDK could
    be selected by an unregistered name. Closing it is only defensible if the
    workflow keeps a route — and it does: `auto` still resolves to the
    project's own input/pdk/. If this ever fails, the gate has taken something
    away and must be revisited, not just re-asserted."""
    proj = _project_with_local_pdk(tmp_path)
    cfg = R._detect_pdk(proj, override="auto")
    assert cfg is not None, "auto must still find a project-local PDK"
    assert str(cfg.liberty).startswith(str(proj)), (
        "auto must resolve to the PROJECT's own PDK assets")


def test_unreadable_registry_fails_closed_not_open(tmp_path, monkeypatch):
    """If the registry cannot be read at all, the acceptance set collapses to
    the hand-written branches and every registry-only name is REFUSED.

    That is the safe direction and it is asserted so it stays that way: a
    future 'be lenient when the registry is missing' change would turn an
    unreadable registry back into the silent-substitution path this whole
    guard exists to close."""
    monkeypatch.setattr(R, "PROGRAMS_DIR", tmp_path)     # no pdk_registry.json
    R._pdk_registry_entry._cache.clear()
    try:
        assert R._known_pdk_names() == sorted(R._PDK_NAMED_BRANCHES)
        with pytest.raises(ValueError):
            R._detect_pdk(_bare_project(tmp_path), override="ihp-sg13g2")
        for name in R._PDK_NAMED_BRANCHES:               # branches still work
            R._assert_pdk_name_resolvable(name)
    finally:
        R._pdk_registry_entry._cache.clear()


def test_named_branches_are_accepted_without_registry_entries(
        tmp_path, registry):
    """The three hand-written branches must stay legal even though the fixture
    registry does not declare them — otherwise the gate would break every
    existing `--pdk sky130A` caller."""
    for name in R._PDK_NAMED_BRANCHES:
        R._assert_pdk_name_resolvable(name)       # must not raise
