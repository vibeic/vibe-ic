"""vibe-ic#903 — a device flavour is elected for a BLOCK's voltage domain, and
still not by the alphabet.

WHAT WAS MEASURED, ON THE TREE, BEFORE ANY OF THIS
==================================================
#903 makes TWO claims. Commit 792e428a6 answered one of them. Both halves were
re-measured by RUNNING the real entry points over a synthetic split-flavour
family, not by reading the commit message:

  (1) ORDERING — ANSWERED. Rename the families so the alphabetical winner
      flips and the election does not move: with the elevated-domain name
      sorting FIRST the plain device is elected, and with the plain name
      renamed longer AND lexicographically last it is STILL elected. Both
      report basis `flavour-preference`. `test_903_renaming_*` and
      `test_903_a_name_that_sorts_last_*` are that measurement as tests; they
      go RED against the program as it stood at 792e428a6^, where
      `sorted(names, key=(len, name))[0]` decided.

  (2) SCOPE — WAS NOT. Two blocks of ONE project, one declaring 1.8 V and one
      declaring 1.2 V, called through `analog_a3_netlist_emit
      .resolve_pdk_context` with exactly what the per-block caller has:

          pass_block (1.8 V)  role_models = {nmos: *_lv_nmos, pmos: *_lv_pmos}
          core_block (1.2 V)  role_models = {nmos: *_lv_nmos, pmos: *_lv_pmos}
          DIFFERENT? False

      `resolve_pdk_context(project, pdk, container, roles)` had no parameter
      that could tell one block from another, so every block on a chip got one
      flavour. `test_903_two_blocks_*` is that measurement as a test; it goes
      RED against origin/main.

WHAT CLOSES (2), AND WHY IT IS THE EXISTING SEAM AND NOT A NEW ONE
==================================================================
The design already STATES its domains — a block's A1 `spec.json` carries its
supply and terminal voltages WITH UNITS, because every other consumer needs
them. `analog_a3_netlist_emit.block_voltage_domains` discovers the domain from
those rows (by the row's UNIT, never by a list of blessed spec NAMES — both
key spellings this pipeline produces are read) and hands it
down as `analog_pdk_deck_context.VoltageDomain`; the ranking stays the deck
resolver's own property, so no call site chooses a POLICY — only which DOMAIN
it is asking about. `elevated` is RELATIVE to the design's lowest declared
domain, because 1.8 V is one design's core rail and the next design's elevated
one.

WHAT IS STILL TRUE ABOUT #903 AFTER THIS — asserted, not hoped
==============================================================
  * A design that states NO voltage anywhere has no domain to scope to and
    still gets ONE flavour for every block. The record still says so, in those
    words (`chip_global_note`); `test_903_guard_a_design_that_states_no_domain_
    still_gets_a_sane_default` holds the default it falls back to. The rule
    reads VOLTAGES, not intent: a block whose spec omits its supply is
    indistinguishable from a core block.
  * THE RULE STILL CANNOT PROMOTE A DEVICE THAT CARRIES NO SIGNAL. A candidate
    that spells neither a domain COMPONENT nor a rating is neither demoted nor
    overstressed, so an elevated block cannot prefer an elevated flavour over
    it and falls back to the name-order tiebreak between the two.
    `test_903_a_candidate_carrying_no_signal_at_all_cannot_be_scoped` states
    that limit as an assertion rather than leaving it to be discovered.

THE PAIRED GUARDS (`test_903_paired_guard_*`) call ONLY API that predates this
change and pass on BOTH arms on purpose. They are what stops the per-block half
being bought by breaking the half that was already right: a design stating no
domain must keep its sane default and keep DISCLOSING that the answer is
chip-global, a PDK with one family per role must still elect `sole-candidate`
with nothing rejected, a threshold component must still not read as a voltage
domain, and an honest NEEDS_NATIVE_TEMPLATE refusal must stay honest.
`test_903_guard_*` (no `paired_`) guard the NEW behaviour and can only run on
the fixed arm — they are guards, not controls, and are named apart so nobody
reads a red one on the unfixed arm as a failed control.

chip-AGNOSTIC: every family and device name is synthetic (`famx`). The
voltage-domain name COMPONENTS are generic device-class vocabulary — the same
category as `nfet`/`pmos` — and they are SCRAPED from the program at runtime,
never retyped, so a component added to that vocabulary is covered here the day
it lands.
"""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import analog_pdk_deck_context as APDC          # noqa: E402
import analog_a3_netlist_emit as A3             # noqa: E402

_SECTIONS = ("mos_tt", "mos_ss", "mos_ff")
_ROLES = ("nmos", "pmos")


# ── vocabulary, scraped from the program ───────────────────────────────────

def _an_elevated_component() -> str:
    """One voltage-domain component the PROGRAM declares elevated. Scraped, so
    this fixture follows the vocabulary instead of pinning it.

    THE FALLBACK IS NOT DECORATION. The ordering tests below are the UNFIXED
    arm of a mutation control against the program as it stood at 792e428a6^,
    which has no `_DOMAIN_ELEVATED` at all. Reading the vocabulary only from
    there would make that arm die of an AttributeError — a red that looks like
    proof and is not, because it never exercises the ranking. So the fallback
    scrapes a3's `_ROLE_AVOID`, the vocabulary that PREDATES the fix and stated
    the same preference all along, and takes its short alphabetic components:
    the domain markers, as opposed to the threshold suffixes and the spelled
    ratings that share that list. Both arms then rank the same fixture."""
    declared = tuple(getattr(APDC, "_DOMAIN_ELEVATED", ()) or ())
    if declared:
        return sorted(declared)[0]
    avoid = {str(t).strip("_").lower() for t in A3._ROLE_AVOID}
    short = sorted(t for t in avoid if t.isalpha() and len(t) <= 2)
    assert short, sorted(avoid)
    return short[0]


def _an_ordinary_component() -> str:
    return sorted(APDC._DOMAIN_ORDINARY)[0]


# ── synthetic families ─────────────────────────────────────────────────────

def _lib(devices) -> str:
    """A single-file sectioned model lib defining `devices` in every corner."""
    body = "\n".join(f".subckt {d} d g s b w=1 l=1\n.ends" for d in devices)
    out = ["* synthetic model lib"]
    for sec in _SECTIONS:
        out += [f".lib {sec}", body, ".endl"]
    return "\n".join(out) + "\n"


def _ctx(devices, domain=None, required=_ROLES):
    """The REAL dispatcher over a one-file family holding `devices`."""
    path = "/pdk/famx_models.lib"
    files = {path: _lib(devices)}
    res = {"available": True, "source": "project_custom_pdk", "family": "famx",
           "target": "famx (synthetic)", "spice_libs": [path]}
    kw = {} if domain is None else {"domain": domain}
    return APDC.resolve_deck_context("famx", res=res, required=tuple(required),
                                     reader=lambda p: files.get(p), **kw)


def _elected(devices, domain=None):
    return _ctx(devices, domain).device_map


def _family(*tokens):
    """Device names for every role, one per token component."""
    return [f"famx_{t}_{r}" for t in tokens for r in _ROLES]


# ── (1) ORDERING — the alphabet still must not decide ──────────────────────
#
# These call ONLY the pre-existing entry point and pass NO domain, so they are
# runnable — and RED — against the program as it stood at 792e428a6^.

def test_903_renaming_the_families_so_the_alphabet_flips_does_not_move_it():
    """THE MEASUREMENT #903's first claim asks for, as a test.

    One MOS family in two flavours, EQUAL-LENGTH names differing only in the
    voltage-domain component. Arm A names the plain flavour so it sorts LAST;
    arm B renames it so it sorts FIRST. The plain device must be elected in
    BOTH, which is only possible if something other than the name order
    decided. Arm A is the one the alphabet gets wrong."""
    elev = _an_elevated_component()
    plain_last = "z" * len(elev)                  # sorts after any letter
    plain_first = "a" * len(elev)                 # sorts before any letter
    assert elev not in (plain_last, plain_first), elev

    got_a = _elected(_family(elev, plain_last))
    got_b = _elected(_family(elev, plain_first))
    for role in _ROLES:
        assert got_a[role] == f"famx_{plain_last}_{role}", got_a
        assert got_b[role] == f"famx_{plain_first}_{role}", got_b


def test_903_a_name_that_sorts_last_still_beats_an_elevated_one():
    """The sharper half of the same question: give the plain candidate the
    WORST possible name-order position — longer AND lexicographically last —
    and it must still be elected, because it carries no elevated component.
    RED against 792e428a6^ on BOTH tiebreak components at once."""
    elev = _an_elevated_component()
    got = _elected(_family(elev, "zzzzzzzzzz"))
    for role in _ROLES:
        assert got[role] == f"famx_zzzzzzzzzz_{role}", got


def test_903_the_ordering_answer_is_recorded_as_a_flavour_decision():
    """The record must attribute the election to the flavour rule, not leave a
    reader unable to tell it from the tiebreak that used to decide."""
    elev = _an_elevated_component()
    election = _ctx(_family(elev, "zzzz")).as_json()["device_election"]
    for role, rec in election["roles"].items():
        assert rec["basis"] == APDC.ELECTION_BASIS_FLAVOUR, (role, rec)
        assert rec["rejected"] == [f"famx_{elev}_{role}"], rec


# ── (2) SCOPE — two blocks of one project, two flavours ────────────────────

def _project(tmp_path: Path, devices, blocks) -> Path:
    """A project staging a rung-1 custom PDK plus one A1 spec per block.

    `blocks` is {name: volts or None}; a None block states no voltage, which is
    exactly how a design that never declares one reaches the resolver."""
    spice = tmp_path / "input" / "pdk" / "spice"
    spice.mkdir(parents=True, exist_ok=True)
    (spice / "famx_models.lib").write_text(_lib(devices))
    gen = tmp_path / "phase1" / "generated_docs"
    gen.mkdir(parents=True, exist_ok=True)
    (gen / "L19_CONSTRAINTS_PDK.json").write_text(
        json.dumps({"fields": {"pdk_target": "famx"}}))
    for name, volts in blocks.items():
        bd = tmp_path / "phase3" / "analog" / name
        bd.mkdir(parents=True, exist_ok=True)
        rows = ([{"name": "vsupply", "target": volts, "max": volts,
                  "units": "V"}] if volts is not None else
                [{"name": "gain", "target": 40, "units": "dB"}])
        bd.joinpath("spec.json").write_text(
            json.dumps({"block": name, "specs": rows}))
    return tmp_path


def _entries(blocks):
    return [{"name": n, "type": "generic"} for n in blocks]


def _per_block(tmp_path, devices, blocks):
    """What A3 binds for each block, through the REAL per-block path: discover
    the design's domains, then call the resolver the way `emit_for_block` does.

    ON THE UNFIXED ARM there is no discovery to do — the per-block caller has
    no way to say WHICH block it is asking about, so the only call available is
    the four-argument one. That is not a shortcut around the control, it IS the
    defect: taking it makes the unfixed arm fail on the two blocks binding the
    same device, which is the measurement, rather than on a missing attribute,
    which would be a red that proves nothing."""
    project = _project(tmp_path, devices, blocks)
    discover = getattr(A3, "block_voltage_domains", None)
    if discover is None:
        return {n: A3.resolve_pdk_context(project, "famx", "", list(_ROLES))
                for n in blocks}
    domains = discover(project, _entries(blocks))
    return {n: A3.resolve_pdk_context(project, "famx", "", list(_ROLES),
                                      domains[n])
            for n in blocks}


def test_903_two_blocks_of_one_project_receive_different_flavours(tmp_path):
    """THE MEASUREMENT #903's second claim asks for, as a test. RED against
    origin/main, where both blocks bound the ordinary flavour."""
    elev, ordn = _an_elevated_component(), _an_ordinary_component()
    devices = _family(elev, ordn)
    got = _per_block(tmp_path, devices,
                     {"pass_block": 1.8, "core_block": 1.2})
    pas = got["pass_block"]["role_models"]
    core = got["core_block"]["role_models"]
    assert pas != core, (pas, core)
    for role in _ROLES:
        assert pas[role] == f"famx_{elev}_{role}", pas
        assert core[role] == f"famx_{ordn}_{role}", core


def _split_corner_family():
    """A family shipping ONE CORNER ENTRY-POINT LIB PER FLAVOUR, the shape #903
    was measured on: two pure aggregators with the SAME section vocabulary,
    each `.include`ing its own device sub-lib."""
    files = {}
    for dom in (_an_elevated_component(), _an_ordinary_component()):
        files[f"/pdk/corner_{dom}.lib"] = "\n".join(
            [f"* corner entry-point lib ({dom})"]
            + [line for sec in _SECTIONS
               for line in (f".lib {sec}",
                            f'.include "famx_{dom}_dev.lib"', ".endl")]) + "\n"
        files[f"/pdk/famx_{dom}_dev.lib"] = "".join(
            f".subckt famx_{dom}_{r} d g s b w=1 l=1\n.ends\n" for r in _ROLES)
    res = {"available": True, "source": "container_installed",
           "family": "famx", "target": "famx (synthetic)",
           # elevated FIRST, the arrangement the alphabet also favours
           "spice_libs": [f"/pdk/corner_{_an_elevated_component()}.lib",
                          f"/pdk/corner_{_an_ordinary_component()}.lib"]}
    return res, files


def test_903_the_lib_the_deck_loads_follows_the_block_that_elected_it():
    """THE LOAD-BEARING half of the cascade. Binding a device is only half a
    deck: the emitted `.lib <path> <section>` line has to point at the lib that
    DEFINES it, or ngspice aborts with `unknown subckt` — the issue's own
    second failure mode. So a per-block flavour is only real if the primary lib
    and `deck_loads` move with it, per block."""
    res, files = _split_corner_family()
    elev, ordn = _an_elevated_component(), _an_ordinary_component()
    for dom, want in ((APDC.VoltageDomain(volts=1.8, elevated=True), elev),
                      (APDC.VoltageDomain(volts=1.2, elevated=False), ordn)):
        ctx = APDC.custom_family_context(res, _ROLES,
                                         lambda p: files.get(p), dom)
        assert ctx.status == "OK", ctx.work_items
        assert ctx.device_map == {r: f"famx_{want}_{r}" for r in _ROLES}, \
            ctx.device_map
        assert ctx.model_lib == f"/pdk/corner_{want}.lib", ctx.model_lib
        loaded = {lib for lib, _sec in ctx.deck_loads}
        assert loaded == {f"/pdk/corner_{want}.lib"}, ctx.deck_loads
        for lib, sec in ctx.deck_loads:
            assert sec in _SECTIONS, (lib, sec)


def test_903_the_primary_lib_tie_break_cannot_become_a_flavour_decision():
    """#903's first claim also names the OTHER ordering: `custom_family_context`
    picks `max(readable, key=_primary_rank)`, and `max` returns the first
    maximal element, so a genuine tie is still broken by the order the libs
    happen to arrive in. That is UNCHANGED and deliberately so — it is a choice
    between two libs, not between two flavours.

    Measured here rather than asserted about: two libs defining the SAME device
    set tie on every rank component, the elected LIB does follow arrival order,
    and the elected DEVICE does NOT — because the flavour election runs over
    the cross-lib union first and the re-derivation over the tied lib's closure
    reaches the same answer. If that ever stops being true this goes red, which
    is the point of writing it down instead of trusting it."""
    devices = _family(_an_elevated_component(), _an_ordinary_component())
    files = {"/pdk/one.lib": _lib(devices), "/pdk/two.lib": _lib(devices)}
    seen_libs, seen_devices = set(), set()
    for order in (["/pdk/one.lib", "/pdk/two.lib"],
                  ["/pdk/two.lib", "/pdk/one.lib"]):
        res = {"available": True, "source": "container_installed",
               "family": "famx", "target": "famx", "spice_libs": order}
        for dom in (None, APDC.VoltageDomain(volts=1.8, elevated=True)):
            ctx = APDC.custom_family_context(res, _ROLES,
                                             lambda p: files.get(p), dom)
            seen_libs.add(ctx.model_lib)
            seen_devices.add((dom, tuple(sorted(ctx.device_map.items()))))
    assert len(seen_libs) == 2, (
        "the fixture no longer produces the tie it is about", seen_libs)
    per_domain = {}
    for dom, devmap in seen_devices:
        per_domain.setdefault(dom, set()).add(devmap)
    for dom, maps in per_domain.items():
        assert len(maps) == 1, (
            "the lib tie-break moved the elected FLAVOUR, which is the thing "
            f"#903 is about: domain={dom} maps={maps}")


def test_903_the_resolver_takes_the_domain_the_design_states(tmp_path):
    """The seam must be a parameter a call site can actually POPULATE — the
    complaint `RETIRED_PRIMARY_STRATEGIES` records about dead seams. So the
    parameter and the discovery that fills it are asserted together."""
    params = set(inspect.signature(A3.resolve_pdk_context).parameters)
    assert "domain" in params, params
    blocks = {"a": 1.8, "b": 1.2}
    project = _project(tmp_path, _family(_an_elevated_component(),
                                         _an_ordinary_component()), blocks)
    domains = A3.block_voltage_domains(project, _entries(blocks))
    assert domains["a"].volts == 1.8 and domains["a"].elevated is True
    assert domains["b"].volts == 1.2 and domains["b"].elevated is False
    assert domains[A3.CORE_VOLTS_KEY] == 1.2


def test_903_the_domain_is_read_from_units_not_from_a_blessed_spec_name():
    """A design is free to call its supply anything. The voltage is found by
    the row's UNITS, so renaming every row leaves the domain unchanged — and a
    row that is not a voltage at all is never mistaken for one."""
    named = {"specs": [{"name": "vdd_core", "target": 1.2, "units": "V"},
                       {"name": "gain", "target": 60, "units": "dB"}]}
    renamed = {"specs": [{"name": "wholly_unrelated", "target": 1.2,
                          "units": "V"},
                         {"name": "also_unrelated", "target": 60,
                          "units": "dB"}]}
    assert A3.spec_voltage(named) == A3.spec_voltage(renamed) == 1.2
    assert A3.spec_voltage({"specs": [{"name": "gain", "target": 60,
                                       "units": "dB"}]}) is None


def test_903_every_volt_unit_the_program_declares_is_read_at_its_scale():
    """The unit table is SCRAPED from the program: a unit added to it is
    covered here the day it lands, and one whose scale is wrong is caught by
    the round trip rather than by a hand-typed expectation."""
    table = A3._VOLT_UNITS
    assert table, "the program declares no volt units at all"
    for unit, scale in table.items():
        spec = {"specs": [{"name": "v", "target": 1.0 / scale, "units": unit}]}
        got = A3.spec_voltage(spec)
        assert got is not None and abs(got - 1.0) < 1e-9, (unit, scale, got)


def test_903_the_highest_stated_voltage_is_the_one_that_must_be_withstood():
    """A block's domain is the WORST case its own spec puts across a device,
    over every numeric field on every voltage row — not the first row, not the
    target."""
    spec = {"specs": [{"name": "vout", "target": 1.2, "max": 1.3,
                       "units": "V"},
                      {"name": "vin", "target": 1.8, "max": 2.0, "units": "V"},
                      {"name": "dropout", "target": 0.5, "units": "V"}]}
    assert A3.spec_voltage(spec) == 2.0


def test_903_a_rated_family_binds_the_tightest_adequate_flavour():
    """A family that SPELLS its ratings must not simply bind the smallest: the
    device has to survive the domain first, and only then be the tightest fit.
    Read through the program's own rating spelling, not a foundry token."""
    devices = _family("01v2", "01v8", "03v3")
    assert APDC.name_voltage_rating("famx_01v8_nmos") == 1.8, "fixture"
    for volts, want in ((1.2, "01v2"), (1.8, "01v8"), (3.3, "03v3")):
        got = _elected(devices, APDC.VoltageDomain(volts=volts,
                                                   elevated=volts > 1.2))
        for role in _ROLES:
            assert got[role] == f"famx_{want}_{role}", (volts, got)


def test_903_an_overstressed_device_is_ranked_last_but_never_removed():
    """A family that offers NOTHING adequate must still elect something and
    still say what it bound — refusing to emit for a whole class of families is
    a contract decision nobody has taken, and a silent drop would turn an
    honest binding into an unresolved role."""
    devices = _family("01v2")
    ctx = _ctx(devices, APDC.VoltageDomain(volts=3.3, elevated=True))
    assert ctx.unresolved_roles == [], ctx.unresolved_roles
    for role in _ROLES:
        assert ctx.device_map[role] == f"famx_01v2_{role}", ctx.device_map


def test_903_every_elevated_component_the_program_knows_is_scoped():
    """DISCOVER, DO NOT ENUMERATE. For EVERY component the module declares
    elevated, paired against EVERY component it declares ordinary, an elevated
    block must elect the elevated flavour and a core block the ordinary one. A
    component added to either vocabulary is covered the day it lands; one added
    to the elevated list that the ranker does not act on turns this red."""
    checked = 0
    for elev in APDC._DOMAIN_ELEVATED:
        for ordn in APDC._DOMAIN_ORDINARY:
            devices = _family(elev, ordn)
            hi = _elected(devices, APDC.VoltageDomain(volts=5.0,
                                                      elevated=True))
            lo = _elected(devices, APDC.VoltageDomain(volts=1.2,
                                                      elevated=False))
            for role in _ROLES:
                assert hi[role] == f"famx_{elev}_{role}", (elev, ordn, hi)
                assert lo[role] == f"famx_{ordn}_{role}", (elev, ordn, lo)
            checked += 1
    assert checked, "no domain-component pair was exercised at all"


def test_903_a_candidate_carrying_no_signal_at_all_cannot_be_scoped():
    """THE LIMIT, STATED. The rule cannot PROMOTE: a candidate spelling neither
    a domain component nor a rating is neither demoted nor overstressed, so an
    elevated block cannot prefer an elevated flavour over it and the name-order
    tiebreak decides between them. A family whose ordinary flavour is named
    without any signal is therefore still chip-global in effect. Asserted here
    so the limit is a measured property, not a surprise."""
    elev = _an_elevated_component()
    devices = _family(elev, "zzzz")
    hi = _elected(devices, APDC.VoltageDomain(volts=5.0, elevated=True))
    lo = _elected(devices, APDC.VoltageDomain(volts=1.2, elevated=False))
    for role in _ROLES:
        # the elevated block gets the SHORTER name, not the elevated device,
        # because nothing separates them on flavour.
        assert hi[role] == f"famx_{elev}_{role}", hi
        assert lo[role] == f"famx_zzzz_{role}", lo
    assert len(f"famx_{elev}_nmos") < len("famx_zzzz_nmos"), (
        "the fixture no longer demonstrates that the TIEBREAK decided")
    basis = _ctx(devices, APDC.VoltageDomain(volts=5.0, elevated=True)
                 ).as_json()["device_election"]["roles"]["nmos"]["basis"]
    assert basis == APDC.ELECTION_BASIS_NAME_ORDER, basis


# ── the REGISTRY branch, which has its own fixed-polarity preference ───────
#
# `_ROLE_PREFER` / `_ROLE_AVOID` prefer the core-voltage device and avoid the
# elevated one unconditionally, which is the wrong answer for an elevated
# block. The domain therefore has to reach this branch too — but only on the
# components that are ABOUT the domain, or it would override a stated
# preference between candidates the domain does not separate at all.

def _registry_family_with_a_rating_split():
    """A registry family that DECLARES more than one voltage rating for a MOS
    role, discovered from the shipped registry rather than named here."""
    data = json.loads((PROGRAMS / "pdk_registry.json").read_text())
    for ent in data.get("pdks") or []:
        if not isinstance(ent, dict):
            continue
        models = [m for m in ent.get("device_models") or []
                  if isinstance(m, str)]
        for role in ("nmos", "pmos"):
            toks = A3._ROLE_TOKENS.get(role, ())
            cands = [m for m in models
                     if any(t in m.lower() for t in toks)]
            ratings = sorted({APDC.name_voltage_rating(m) for m in cands}
                             - {0.0})
            if len(ratings) >= 2:
                return ent, role, ratings
    return None, None, None


def test_903_the_registry_branch_binds_a_device_that_survives_the_domain():
    """An elevated block must not be handed the core-voltage device just
    because a fixed list prefers it. Asserted as a PROPERTY of the bound
    model's own spelled rating, over a family discovered from the registry —
    no device name is written down here."""
    ent, role, ratings = _registry_family_with_a_rating_split()
    if ent is None:
        import pytest
        pytest.skip("no registry family declares two ratings for a MOS role")
    low, high = ratings[0], ratings[-1]
    got, _unres, _by = A3.resolve_role_models(
        ent, [role], {}, APDC.VoltageDomain(volts=high, elevated=True))
    assert APDC.name_voltage_rating(got[role]) >= high, (high, got)
    # and the core block still gets the ordinary device it always got
    base, _u, _b = A3.resolve_role_models(ent, [role], {})
    same, _u, _b = A3.resolve_role_models(
        ent, [role], {}, APDC.VoltageDomain(volts=low, elevated=False))
    assert same == base, (base, same)


def test_903_a_stated_domain_does_not_override_the_registrys_preference():
    """The domain key must contribute ONLY its flavour components. Measured
    before this was true: a stated domain re-bound a passive role away from the
    device `_ROLE_PREFER` names first to a shorter name the list does not
    mention. For every role the registry preference covers, a non-elevated
    stated domain must bind exactly what no domain binds."""
    data = json.loads((PROGRAMS / "pdk_registry.json").read_text())
    roles = sorted(A3._ROLE_PREFER)
    checked = 0
    for ent in data.get("pdks") or []:
        if not isinstance(ent, dict) or not ent.get("device_models"):
            continue
        base, _u, _b = A3.resolve_role_models(ent, roles, {})
        for volts in (1.2, 1.8):
            got, _u, _b = A3.resolve_role_models(
                ent, roles, {}, APDC.VoltageDomain(volts=volts,
                                                   elevated=False))
            assert got == base, (ent.get("name"), volts, base, got)
        checked += 1
    assert checked, "no registry family declares any device model"


# ── both unit spellings the pipeline actually produces ─────────────────────

def test_903_both_unit_key_spellings_the_pipeline_writes_are_read():
    """`analog_a1_spec_emit` writes `unit`; the `analog-spec-extract` skill
    writes `units`. Reading one would make the domain discoverable for half the
    pipeline and invisible for the other half, which reads as "this design
    states no domain" when it states one. The key list is scraped from the
    program, so a third spelling added there is covered here."""
    keys = A3._UNIT_KEYS
    assert len(keys) >= 2, keys
    for key in keys:
        spec = {"specs": [{"name": "vsupply", "target": 1.8, key: "V"}]}
        assert A3.spec_voltage(spec) == 1.8, (key, spec)


def test_903_no_voltage_domain_line_is_emitted_when_none_is_stated(tmp_path):
    """The netlist provenance gains a `voltage_domain=` line ONLY when the
    design states one — a design that states none must emit the deck it always
    emitted, or every existing artefact changes for a decision nobody made."""
    devices = _family(_an_elevated_component(), _an_ordinary_component())
    got = _per_block(tmp_path, devices, {"quiet": None})
    dom = got["quiet"]["role_model_election"].get("domain")
    assert dom in (None, {"volts": None, "elevated": False}), dom
    assert not (dom or {}).get("volts")
    assert not (dom or {}).get("elevated")


# ── the record has to SAY which domain it answered ─────────────────────────

def test_903_the_election_record_names_the_domain_it_was_scoped_to():
    """An artefact that binds a different device per block must say WHY, or two
    decks differing in one token are indistinguishable from a bug."""
    devices = _family(_an_elevated_component(), _an_ordinary_component())
    ctx = _ctx(devices, APDC.VoltageDomain(volts=1.8, elevated=True))
    election = ctx.as_json()["device_election"]
    assert election["domain_scope"] == APDC.DOMAIN_SCOPE_STATED, election
    assert election["domain"] == {"volts": 1.8, "elevated": True}, election
    assert "chip_global_note" not in election, election
    assert "can and does bind a different flavour" in (
        election.get("block_domain_note") or ""), election
    for rec in election["roles"].values():
        assert rec["basis"] == APDC.ELECTION_BASIS_DOMAIN, rec
    assert APDC.DOMAIN_SCOPE_STATED in ctx.disclosure, ctx.disclosure


def test_903_every_domain_scope_the_program_emits_is_a_declared_constant():
    """The scope vocabulary is scraped from the module, never retyped here — a
    third scope added as a bare string turns this red."""
    declared = {v for k, v in vars(APDC).items()
                if k.startswith("DOMAIN_SCOPE_") and isinstance(v, str)}
    assert declared, "no domain-scope vocabulary is declared"
    devices = _family(_an_elevated_component(), _an_ordinary_component())
    emitted = {_ctx(devices, d).as_json()["device_election"]["domain_scope"]
               for d in (None, APDC.VoltageDomain(volts=1.8, elevated=True),
                         APDC.VoltageDomain())}
    emitted.add(APDC.resolve_deck_context("sky130").as_json()
                ["device_election"]["domain_scope"])
    assert emitted <= declared, (emitted - declared)


def test_903_a3_carries_the_domain_into_its_own_record(tmp_path):
    """A3's `role_model_election` is what the netlist sidecar quotes. It must
    carry the domain, so the emitted artefact answers "why THIS device"."""
    devices = _family(_an_elevated_component(), _an_ordinary_component())
    got = _per_block(tmp_path, devices,
                     {"pass_block": 1.8, "core_block": 1.2})
    assert (got["pass_block"]["role_model_election"].get("domain")
            == {"volts": 1.8, "elevated": True})
    assert (got["core_block"]["role_model_election"].get("domain")
            == {"volts": 1.2, "elevated": False})


# ── PAIRED GUARDS ──────────────────────────────────────────────────────────
#
# `test_903_paired_guard_*` call ONLY the API that predates this change and
# pass on BOTH arms of the mutation control — they are the arm that stops the
# per-block half being bought by breaking the behaviour that was already
# right. `test_903_guard_*` below them guard the NEW behaviour and can only
# run on the fixed arm; they are guards, not controls, and are named apart so
# nobody reads a red one on the unfixed arm as a failed control.

def test_903_paired_guard_a_design_that_states_no_domain_gets_a_sane_default(
        tmp_path):
    """THE control for this change, through the FOUR-argument call that
    predates it. A design declaring no voltage anywhere has nothing to scope
    to: every block must still bind the ORDINARY flavour (the pre-existing sane
    default), every block must get the SAME one, and the record must still SAY
    the answer is chip-global rather than implying a per-block one it did not
    make. PASSES on both arms; a "fix" that invented a domain for a silent
    design, or that stopped disclosing the chip-global scope, turns it red."""
    elev, ordn = _an_elevated_component(), _an_ordinary_component()
    blocks = {"block_a": None, "block_b": None}
    project = _project(tmp_path, _family(elev, ordn), blocks)
    got = {n: A3.resolve_pdk_context(project, "famx", "", list(_ROLES))
           for n in blocks}
    a = got["block_a"]["role_models"]
    b = got["block_b"]["role_models"]
    assert a == b, (a, b)
    for role in _ROLES:
        assert a[role] == f"famx_{ordn}_{role}", a
    election = got["block_a"]["role_model_election"]["deck_context"]
    assert "chip_global_note" in election, election


def test_903_paired_guard_a_pdk_with_one_family_per_role_is_unaffected():
    """A PDK shipping ONE flavour per role has nothing to elect: it must bind
    that device, and the election must call it a sole candidate rather than
    claiming a preference decided something. PASSES on both arms — the issue
    never touched such a family and neither may the fix."""
    devices = [f"famx_{r}" for r in _ROLES]
    ctx = _ctx(devices)
    assert ctx.device_map == {r: f"famx_{r}" for r in _ROLES}, ctx.device_map
    election = ctx.as_json()["device_election"]
    for role, rec in election["roles"].items():
        assert rec["basis"] == APDC.ELECTION_BASIS_SOLE, (role, rec)
        assert rec["rejected"] == [], rec


def test_903_paired_guard_a_threshold_component_is_not_a_voltage_domain():
    """A threshold-flavour component must not read as a voltage DOMAIN — the
    misreading the domain vocabulary was component-matched to prevent. Every
    such component the program declares is checked, not one chosen by hand.
    PASSES on both arms."""
    thresholds = [t for t in APDC._SPECIAL_VARIANT
                  if APDC.name_voltage_domain(f"famx_{t}_nmos") is None]
    assert thresholds, "no special-variant component to check"
    for tok in thresholds:
        got = _elected(_family(tok, "zzz"))
        for role in _ROLES:
            assert got[role] == f"famx_zzz_{role}", (tok, got)


def test_903_paired_guard_an_honest_refusal_stays_honest():
    """A role with no template-compatible device must still be REFUSED, not
    filled from somewhere. PASSES on both arms — the cheapest way to make a
    flavour question go away is to loosen the refusal, and that must stay
    expensive."""
    ctx = _ctx([f"famx_{_an_ordinary_component()}_nmos"])
    assert ctx.status == "NEEDS_NATIVE_TEMPLATE", ctx.status
    assert ctx.unresolved_roles == ["pmos"], ctx.unresolved_roles
    assert any("NEEDS_NATIVE_TEMPLATE" in w for w in ctx.work_items), \
        ctx.work_items


# ── guards on the NEW behaviour (fixed arm only) ───────────────────────────

def test_903_guard_a_single_family_pdk_is_unmoved_by_any_domain():
    """The sole-candidate family must bind the same device at EVERY domain and
    at none — a domain may narrow a choice, never invent one."""
    devices = [f"famx_{r}" for r in _ROLES]
    baseline = _elected(devices)
    for dom in (None, APDC.VoltageDomain(),
                APDC.VoltageDomain(volts=1.2, elevated=False),
                APDC.VoltageDomain(volts=5.0, elevated=True)):
        assert _elected(devices, dom) == baseline, dom


def test_903_guard_a_threshold_component_is_not_promoted_by_a_domain():
    """The threshold-vs-domain distinction must hold at an ELEVATED domain too,
    where a misread `*vt` component would newly win instead of newly lose."""
    thresholds = [t for t in APDC._SPECIAL_VARIANT
                  if APDC.name_voltage_domain(f"famx_{t}_nmos") is None]
    for tok in thresholds:
        got = _elected(_family(tok, "zzz"),
                       APDC.VoltageDomain(volts=5.0, elevated=True))
        for role in _ROLES:
            assert got[role] == f"famx_zzz_{role}", (tok, got)


def test_903_guard_a_design_on_one_voltage_has_no_elevated_block(tmp_path):
    """`elevated` is RELATIVE. Every block on the same rail is a core block, so
    a single-domain design elects exactly what it elected before."""
    elev, ordn = _an_elevated_component(), _an_ordinary_component()
    blocks = {"one": 1.8, "two": 1.8}
    devices = _family(elev, ordn)
    project = _project(tmp_path, devices, blocks)
    domains = A3.block_voltage_domains(project, _entries(blocks))
    assert all(domains[n].elevated is False for n in blocks), domains
    got = _per_block(tmp_path, devices, blocks)
    for name in blocks:
        for role in _ROLES:
            assert (got[name]["role_models"][role]
                    == f"famx_{ordn}_{role}"), got


def test_903_guard_the_known_open_family_table_is_untouched_by_a_domain():
    """The authored known-family table is not an election. Passing a domain
    must not move it — a per-block flavour for a family whose map was written
    by hand would be invented, not resolved."""
    base = APDC.resolve_deck_context("sky130")
    for dom in (APDC.VoltageDomain(volts=5.0, elevated=True),
                APDC.VoltageDomain(volts=1.2, elevated=False)):
        got = APDC.resolve_deck_context("sky130", domain=dom)
        assert got.device_map == base.device_map, (dom, got.device_map)
        assert got.model_lib == base.model_lib, dom


def test_903_guard_an_unstated_domain_ranks_identically_to_no_domain():
    """`VoltageDomain()` — a block the design simply did not describe — must be
    indistinguishable from passing nothing, over a candidate set carrying every
    signal the ranker knows about. This is what keeps the discovery step from
    changing an answer merely by running."""
    tokens = (tuple(APDC._DOMAIN_ELEVATED) + tuple(APDC._DOMAIN_ORDINARY)
              + tuple(APDC._SPECIAL_VARIANT) + ("01v8", "03v3"))
    devices = _family(*tokens) + [f"famx_{r}" for r in _ROLES]
    order_none = sorted(devices, key=lambda n: APDC.device_flavour_rank(n))
    order_blank = sorted(devices, key=lambda n: APDC.device_flavour_rank(
        n, APDC.VoltageDomain()))
    assert order_none == order_blank
    assert _elected(devices) == _elected(devices, APDC.VoltageDomain())
