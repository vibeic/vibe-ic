"""vibe-ic#903 — a device FLAVOUR must not be elected by the alphabet.

THE DEFECT, as measured on this tree before the fix. A family that ships the
same MOS role in two voltage-domain flavours, with IDENTICAL corner-section
vocabularies and EQUAL-LENGTH device names, elected one of them purely because
its name sorted first:

    device_map: {nmos: <family>_hv_nmos, pmos: <family>_hv_pmos}
    model_lib:  .../cornerMOShv.lib     section mos_tt
    also present, never considered: the low-voltage corner lib and its devices

Two orderings composed, neither of which reads the design:
`map_device_roles` picked `sorted(names, key=(len, name))[0]`, and the primary
lib then followed the device it had elected.

WHY IT MATTERS AND WHY NOTHING CAUGHT IT. One `.op` in the container, both
flavours, same bias (Vgs = Vds = core supply, W = 1 um, L = drawn minimum,
typical section):

    plain core-voltage flavour     |Id| = 4.005261e-04 A
    elevated-voltage flavour       |Id| = 1.703823e-15 A

~2.4e11 apart, and ngspice exits 0 with NO error on both. The wrong flavour
does not fail — it answers. And the cross combination is not a safety net
either, it is a different failure: loading the core-voltage corner lib while
binding the elevated device aborts with `unknown subckt`, which is why the
primary-lib cascade is load-bearing rather than cosmetic.

WHAT THE FIX DOES: applies, at the ELECTION site, the preference
`analog_a3_netlist_emit._ROLE_PREFER` already STATED and never ran there
("prefer a plain core-voltage device over a high-voltage / low-Vt / isolated
variant … auditable instead of alphabetical"), and RECORDS every election's
basis, its rejected candidates, and the voltage domains the family spans.

WHAT THE FIX DOES NOT DO, and what these tests hold it to: the election is
still CHIP-GLOBAL. `resolve_pdk_context` takes no block argument, so no block
can differ. That half of #903 is DISCLOSED, not resolved, and
`test_903_the_per_block_half_is_declared_unfixed` asserts the disclosure's
factual claim is true rather than pretending the gap is closed.

THE GUARDS (`test_903_guard_*`) pass on BOTH the unfixed and the fixed program
on purpose. They are the paired arm: they fail for any "fix" that satisfies the
headline by dropping elevated devices from consideration, by weakening the
honest NEEDS_NATIVE_TEMPLATE refusal, or by disturbing a candidate set that
carries no flavour signal at all.

chip-AGNOSTIC: every fixture name is synthetic (`famx`). `hv` / `lv` here are
generic device-class components — the same category as `nfet` / `pmos` — not a
vendor, SKU or node.
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


# ── synthetic split-flavour family ─────────────────────────────────────────
# Structure copied from the shape that surfaced #903, with synthetic names:
# two CORNER ENTRY-POINT libs (pure aggregators — they define nothing in their
# own text and `.include` a device sub-lib inside each section), the SAME
# section vocabulary in both, and EQUAL-LENGTH device names whose only
# difference is the voltage-domain component.
_SECTIONS = ("mos_tt", "mos_ss", "mos_ff")
_ELEVATED = "hv"
_ORDINARY = "lv"


def _corner_lib(dom: str) -> str:
    out = [f"* synthetic corner entry-point lib ({dom})"]
    for sec in _SECTIONS:
        out.append(f".lib {sec}")
        out.append(f'.include "famx_mos_{dom}_mod.lib"')
        out.append(".endl")
    return "\n".join(out) + "\n"


def _device_lib(dom: str) -> str:
    return (f"* synthetic device sub-lib ({dom})\n"
            f".subckt famx_{dom}_nmos d g s b w=1 l=1\n.ends\n"
            f".subckt famx_{dom}_pmos d g s b w=1 l=1\n.ends\n")


def _split_family_files() -> dict:
    files = {}
    for dom in (_ELEVATED, _ORDINARY):
        files[f"/pdk/cornerMOS{dom}.lib"] = _corner_lib(dom)
        files[f"/pdk/famx_mos_{dom}_mod.lib"] = _device_lib(dom)
    return files


def _reader_for(files: dict):
    return lambda p: files.get(p)


def _split_family_ctx():
    """The REAL program, over the split-flavour fixture. Lib order deliberately
    puts the elevated family FIRST, the arrangement the alphabet also favours,
    so nothing here depends on which order the libs happen to arrive in."""
    files = _split_family_files()
    res = {"available": True, "source": "container_installed",
           "family": "famx", "target": "famx (synthetic split-flavour node)",
           "spice_libs": [f"/pdk/cornerMOS{_ELEVATED}.lib",
                          f"/pdk/cornerMOS{_ORDINARY}.lib"]}
    return APDC.custom_family_context(res, ("nmos", "pmos"),
                                      _reader_for(files))


def _elevated(role: str) -> str:
    return f"famx_{_ELEVATED}_{role}"


def _ordinary(role: str) -> str:
    return f"famx_{_ORDINARY}_{role}"


# ── the headline: the alphabet no longer decides ───────────────────────────

def test_903_a_split_flavour_family_no_longer_elects_by_name_order():
    """The whole issue in one assertion, on the program's own return value."""
    ctx = _split_family_ctx()
    assert ctx.status == "OK", ctx.work_items
    assert ctx.device_map == {"nmos": _ordinary("nmos"),
                              "pmos": _ordinary("pmos")}, ctx.device_map


def test_903_the_two_flavours_really_are_indistinguishable_to_the_old_rule():
    """The premise, asserted rather than assumed: the historical criterion —
    shortest name, then lexicographic — cannot separate these two candidates on
    length, and separates them on the FIRST DIFFERING CHARACTER of a name. If a
    future fixture edit made the names different lengths, the headline test
    above would pass for a reason that has nothing to do with #903."""
    a, b = _elevated("nmos"), _ordinary("nmos")
    assert len(a) == len(b), (a, b)
    assert sorted((a, b), key=lambda n: (len(n), n))[0] == a, (
        "fixture no longer reproduces the alphabetical election it exists for")


def test_903_the_primary_lib_follows_the_device_that_was_elected():
    """LOAD-BEARING, not cosmetic. Measured in the container: loading the
    core-voltage corner lib while binding the elevated device aborts ngspice
    with `unknown subckt`. So the lib must move with the device."""
    ctx = _split_family_ctx()
    assert ctx.model_lib == f"/pdk/cornerMOS{_ORDINARY}.lib", ctx.model_lib
    assert ctx.deck_loads and ctx.deck_loads[0][0] == ctx.model_lib, \
        ctx.deck_loads
    assert ctx.deck_loads[0][1] in _SECTIONS, ctx.deck_loads


def test_903_the_election_record_states_which_rule_decided():
    ctx = _split_family_ctx()
    rec = (ctx.as_json().get("device_election") or {}).get("roles") or {}
    for role in ("nmos", "pmos"):
        assert rec[role]["elected"] == _ordinary(role), rec[role]
        assert rec[role]["basis"] == APDC.ELECTION_BASIS_FLAVOUR, rec[role]
        assert rec[role]["rejected"] == [_elevated(role)], rec[role]


def test_903_the_multi_domain_fact_is_disclosed_not_hidden():
    """The half of #903 the fix does NOT close has to be visible in the
    artefact, or a chip-global election reads exactly like a designed one."""
    ctx = _split_family_ctx()
    elect = ctx.as_json().get("device_election") or {}
    assert elect.get("multi_domain_roles") == ["nmos", "pmos"], elect
    note = elect.get("chip_global_note") or ""
    assert note, elect
    for role in ("nmos", "pmos"):
        doms = elect["roles"][role]["voltage_domains"]
        assert doms == sorted([_ELEVATED, _ORDINARY]), doms
    assert note in ctx.disclosure, ctx.disclosure


def test_903_a_primary_lib_narrowing_does_not_erase_the_flavour_census():
    """The elected primary lib's closure holds ONE candidate per role, because
    electing the ordinary flavour is what made that lib primary. The narrowing
    is a CONSEQUENCE of the election, not a second election.

    MEASURED WHILE BUILDING THIS FIX, which is why the test exists: letting the
    narrowed record replace the union one made every role report
    `sole-candidate` with an empty `rejected` and dropped `multi_domain_roles`
    to `[]` — a record stating there had been nothing to choose between, about
    a family that ships two flavours. The binding was right and the record
    about it was false, which is the failure mode this whole issue is."""
    elect = _split_family_ctx().as_json()["device_election"]
    assert elect["scope"] == APDC.ELECTION_SCOPE_UNION, elect
    assert elect["closure"]["scope"] == APDC.ELECTION_SCOPE_PRIMARY, elect
    assert elect["closure"]["rebound_roles"] == {}, elect["closure"]
    assert elect["roles"]["nmos"]["rejected"] == [_elevated("nmos")], elect
    assert elect["multi_domain_roles"] == ["nmos", "pmos"], elect


def test_903_a_threshold_component_is_not_read_as_a_voltage_domain():
    """`hvt` is a THRESHOLD flavour. Reading it as a high-voltage DOMAIN would
    make the record claim a domain split the family does not have."""
    assert APDC.name_voltage_domain("famx_hvt_nmos") is None
    assert APDC.name_voltage_domain(f"famx_{_ELEVATED}_nmos") == _ELEVATED


def test_903_a3_names_the_path_that_bound_each_role():
    """`_ROLE_PREFER`'s ranking runs only on the registry branch; a deck-context
    election is taken verbatim. Which one bound a role was unrecorded, so a
    stated preference and a name-order pick looked identical downstream."""
    out, unresolved, bound_by = A3.resolve_role_models(
        {"device_models": ["famx_nmos_alt", "famx_pmos_alt"]},
        ["nmos", "pmos", "res"],
        {"nmos": _ordinary("nmos")})
    assert out["nmos"] == _ordinary("nmos")
    assert bound_by["nmos"] == A3.BOUND_BY_DECK_CONTEXT, bound_by
    assert bound_by["pmos"] == A3.BOUND_BY_REGISTRY, bound_by
    assert unresolved == ["res"], unresolved
    assert "res" not in bound_by, bound_by


def test_903_a3_pdk_context_carries_the_election_forward(tmp_path):
    """The record has to survive the hop into the emitter's context dict, or it
    never reaches the netlist sidecar that a reviewer actually opens."""
    ctx = A3.resolve_pdk_context(tmp_path, "sky130", "", ["nmos", "pmos"])
    elect = ctx["role_model_election"]
    assert elect["bound_by"] == {"nmos": A3.BOUND_BY_DECK_CONTEXT,
                                 "pmos": A3.BOUND_BY_DECK_CONTEXT}, elect
    assert elect["deck_context"]["scope"] == APDC.ELECTION_SCOPE_KNOWN_TABLE
    json.dumps(ctx["role_model_election"])          # must be serialisable


# ── discovery, not enumeration ─────────────────────────────────────────────

def test_903_every_basis_the_program_emits_is_a_declared_constant():
    """The basis vocabulary is SCRAPED from the module, never retyped here. A
    fifth basis added as a bare string — the way a vocabulary quietly grows a
    member no consumer knows about — turns this red."""
    declared = {v for k, v in vars(APDC).items()
                if k.startswith("ELECTION_BASIS_") and isinstance(v, str)}
    assert len(declared) >= 3, declared
    emitted = set()
    for ctx in (_split_family_ctx(),
                APDC.resolve_deck_context("sky130"),
                _no_flavour_signal_ctx()):
        for rec in ((ctx.as_json().get("device_election") or {}
                     ).get("roles") or {}).values():
            emitted.add(rec["basis"])
    assert emitted, "no election basis was emitted at all"
    assert emitted <= declared, (emitted - declared)


def test_903_the_two_flavour_vocabularies_are_held_to_each_other():
    """Two hand-typed copies of one vocabulary each hide the other's gap. a3's
    `_ROLE_AVOID` is READ FROM THE PROGRAM and every token in it is required to
    be something the deck-context ranker also demotes — so the two lists cannot
    drift apart silently."""
    avoid = A3._ROLE_AVOID
    assert avoid, "a3 declares no avoid vocabulary to check against"
    plain = "famx_nmos_zz"
    # the FLAVOUR half of the key, sliced the way the program itself slices it
    # (`APDC.FLAVOUR_KEY_WIDTH`) rather than at a width retyped here — the key
    # grew a component when the per-block half landed and a hard-coded slice
    # would have gone quietly blind to the rating instead of red.
    width = APDC.FLAVOUR_KEY_WIDTH
    base = APDC.device_flavour_rank(plain)[:width]
    for token in avoid:
        marked = "famx_nmos_" + str(token).strip("_")
        got = APDC.device_flavour_rank(marked)[:width]
        assert got > base, (
            f"a3 declares `{token}` a flavour to avoid, but the deck-context "
            f"ranker treats `{marked}` as no worse than `{plain}`: "
            f"{got} vs {base}")


# ── paired guards: these must pass on the UNFIXED program too ──────────────

def _no_flavour_signal_ctx():
    """A family whose candidates carry NO domain and NO variant component."""
    files = {
        "/pdk/cornerMOSplain.lib": (
            "* synthetic corner entry-point lib (no flavour signal)\n"
            + "".join(f".lib {s}\n.include \"famx_mos_plain_mod.lib\"\n.endl\n"
                      for s in _SECTIONS)),
        "/pdk/famx_mos_plain_mod.lib": (
            ".subckt famx_nmos_aa d g s b w=1 l=1\n.ends\n"
            ".subckt famx_nmos_bb d g s b w=1 l=1\n.ends\n"
            ".subckt famx_pmos_long_name d g s b w=1 l=1\n.ends\n"
            ".subckt famx_pmos_bb d g s b w=1 l=1\n.ends\n"),
    }
    res = {"available": True, "source": "container_installed",
           "family": "famxplain", "target": "famx plain (synthetic)",
           "spice_libs": ["/pdk/cornerMOSplain.lib"]}
    return APDC.custom_family_context(res, ("nmos", "pmos"),
                                      _reader_for(files))


def test_903_guard_no_flavour_signal_still_elects_shortest_then_lexicographic():
    """THE PAIRED GUARD. A candidate set with nothing electrical to say about
    itself must elect exactly what it always did — the historical rule is kept
    as the FINAL tiebreak precisely so this cannot move."""
    ctx = _no_flavour_signal_ctx()
    assert ctx.device_map == {"nmos": "famx_nmos_aa",     # lexicographic
                              "pmos": "famx_pmos_bb"}, ctx.device_map  # shortest


def test_903_guard_a_sole_elevated_candidate_is_still_elected():
    """A family that ships ONLY the elevated flavour must still get it. A
    "fix" that satisfies the headline by excluding elevated devices from
    consideration breaks here — that is what this guard is for."""
    subckts = {_elevated("nmos"): 4, _elevated("pmos"): 4}
    device_map, unresolved, _notes = APDC.map_device_roles(
        subckts, ("nmos", "pmos"))
    assert device_map == {"nmos": _elevated("nmos"),
                          "pmos": _elevated("pmos")}, device_map
    assert unresolved == [], unresolved


def test_903_guard_the_known_open_family_device_map_is_untouched():
    """The authored fast path parses nothing and must elect nothing."""
    ctx = APDC.resolve_deck_context("sky130")
    assert ctx.device_map == {"nmos": "sky130_fd_pr__nfet_01v8",
                              "pmos": "sky130_fd_pr__pfet_01v8"}
    assert ctx.typ_section == "tt"
    assert ctx.model_lib.endswith("sky130.lib.spice")


def test_903_guard_a_role_with_no_template_compatible_device_still_refuses():
    """The honest NEEDS_NATIVE_TEMPLATE refusal must survive. Relaxing it would
    make every flavour question disappear by making every family emittable."""
    files = {
        "/pdk/cornerMOSonly_n.lib": (
            "".join(f".lib {s}\n.include \"famx_n_only.lib\"\n.endl\n"
                    for s in _SECTIONS)),
        "/pdk/famx_n_only.lib": ".subckt famx_lv_nmos d g s b w=1 l=1\n.ends\n",
    }
    res = {"available": True, "source": "container_installed",
           "family": "famxn", "target": "famx n-only (synthetic)",
           "spice_libs": ["/pdk/cornerMOSonly_n.lib"]}
    ctx = APDC.custom_family_context(res, ("nmos", "pmos"),
                                     _reader_for(files))
    assert ctx.status == "NEEDS_NATIVE_TEMPLATE", ctx.as_json()
    assert ctx.unresolved_roles == ["pmos"], ctx.unresolved_roles


def test_903_guard_a_mos_like_subckt_with_too_few_terminals_is_still_skipped():
    """The 4-terminal requirement is a separate predicate and must not have
    been loosened to make a flavour question go away."""
    subckts = {"famx_lv_nmos": 2, "famx_lv_pmos": 4}
    device_map, unresolved, notes = APDC.map_device_roles(
        subckts, ("nmos", "pmos"))
    assert "nmos" not in device_map, device_map
    assert unresolved == ["nmos"], unresolved
    assert any("terminal" in n for n in notes), notes


# ── the half that is NOT fixed ─────────────────────────────────────────────

def test_903_the_per_block_half_is_declared_unfixed():
    """CHANGED DELIBERATELY when the per-block half landed — the version of this
    test that shipped with 792e428a6 asserted `resolve_pdk_context` takes NO
    domain argument, and said in its own docstring that it must be rewritten
    together with the sentence it verifies when a domain->block binding is
    added. It has been. See
    `test_issue903_per_block_voltage_domain.py` for the binding itself.

    What remains true, and is what this now holds: a design that states NO
    voltage domain has nothing to scope an election to, so it still gets ONE
    flavour for every block — and the record still SAYS so, in those terms.
    A "fix" that silently invented a domain for such a design turns this red."""
    params = set(inspect.signature(A3.resolve_pdk_context).parameters)
    assert "domain" in params, (
        "the per-block half is landed; `resolve_pdk_context` must take the "
        f"domain the design states: {params}")
    ctx = _split_family_ctx()                      # no domain passed
    election = ctx.as_json().get("device_election") or {}
    assert election.get("domain") is None, election.get("domain")
    assert election.get("domain_scope") == APDC.DOMAIN_SCOPE_CHIP_GLOBAL, (
        election.get("domain_scope"))
    note = election.get("chip_global_note") or ""
    assert "no block can differ" in note, note
