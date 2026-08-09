#!/usr/bin/env python3
"""vibe-ic#903 — the device flavour was elected ALPHABETICALLY.

`analog_pdk_deck_context.map_device_roles` picked a role's device with

    sorted(names, key=lambda n: (len(n), n))[0]      # shortest, then a-z

On a PDK that ships a HIGH-VOLTAGE and a LOW-VOLTAGE MOS family the two device
names tie on length, so the HV one won because `h` sorts before `l` — an
alphabetical accident standing in for a voltage-domain decision. A high-voltage
device biased at core voltage does not error; it simulates happily and returns
plausible, wrong numbers.

The preference itself already existed and was DEAD on the path that runs:
`analog_a3_netlist_emit._ROLE_AVOID` literally contains `hv_`, but
`resolve_role_models` takes the deck-context map VERBATIM and only reaches that
ranking on the REGISTRY fallback — i.e. for the known open PDKs, and never for
the parsed families that can actually ship an HV/LV split.

WHAT THESE TESTS PIN, in both directions:

  * the election is no longer decided by name order when a STATED preference
    separates the candidates (`test_903_*_no_longer_elects_the_hv_flavour*`);
  * the OPPOSITE verdict is still reachable — an HV device that is the only
    candidate is still elected, and a candidate set carrying no flavour signal
    still falls through to the historical shortest-then-lexicographic rule and
    SAYS SO (`test_903_*_still_reachable*`);
  * whatever it picks, it records WHY (`basis`, `rejected`, and the available
    voltage domains), end to end into the A3 emit record.

Every device / lib / family name below is INVENTED. No chip, PDK, vendor or
part number appears in this file.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import analog_pdk_deck_context as APDC   # noqa: E402
import analog_pdk_availability as APA    # noqa: E402
import analog_a3_netlist_emit as A3      # noqa: E402


# ── the historical rule, kept here as the CONTROL ──────────────────────────
def _old_rule(names):
    """What `map_device_roles` did before #903: shortest, then lexicographic."""
    return sorted(names, key=lambda n: (len(n), n))[0]


# ── synthetic families (invented names, no vendor/SKU literal) ─────────────
def _stage_split_domain_family(tmp_path):
    """A family that ships TWO MOS corner libs — one low-voltage, one
    high-voltage — with the SAME section vocabulary and EQUAL-LENGTH device
    names, which is the arrangement that makes the alphabet decide."""
    sp = tmp_path / "input" / "pdk" / "spice"
    sp.mkdir(parents=True)
    for flavour in ("lv", "hv"):
        body = []
        for sec in ("mos_ss", "mos_tt", "mos_ff"):
            body += [f".lib {sec}",
                     f".subckt famx_{flavour}_nmos d g s b", ".ends",
                     f".subckt famx_{flavour}_pmos d g s b", ".ends",
                     ".endl"]
        (sp / f"famx_corner_mos_{flavour}.lib").write_text("\n".join(body) + "\n")
    return sp


def _stage_single_domain_family(tmp_path, flavour="hv"):
    """The same family shipping ONE MOS corner lib. A PDK with a single
    flavour must behave exactly as it did before #903 — including electing a
    high-voltage device when that is the only device there is."""
    sp = tmp_path / "input" / "pdk" / "spice"
    sp.mkdir(parents=True)
    body = []
    for sec in ("mos_ss", "mos_tt", "mos_ff"):
        body += [f".lib {sec}",
                 f".subckt famx_{flavour}_nmos d g s b", ".ends",
                 f".subckt famx_{flavour}_pmos d g s b", ".ends",
                 ".endl"]
    (sp / f"famx_corner_mos_{flavour}.lib").write_text("\n".join(body) + "\n")
    return sp


def _ctx_for(tmp_path):
    res = APA.resolve_pdk("Famx N180 (custom node)", project=str(tmp_path))
    assert res["available"] and res["source"] == "project_custom_pdk", res
    return APDC.resolve_deck_context("famx180", res=res)   # local reader


# ── 1. the defect: the alphabet decided a voltage-domain question ──────────

def test_903_the_old_rule_really_did_pick_the_hv_flavour():
    """The control, stated as an executable fact rather than as prose: on
    equal-length names the historical rule picks HV because `h` < `l`."""
    names = ["famx_lv_nmos", "famx_hv_nmos"]
    assert len(names[0]) == len(names[1])          # the tie is real
    assert _old_rule(names) == "famx_hv_nmos"      # decided by the alphabet


def test_903_split_domain_family_no_longer_elects_the_hv_flavour(tmp_path):
    """THE MUTATION TEST. Same libs, same call, opposite answer to origin/main:
    the elected MOS pair is the LOW-voltage flavour, not the alphabetically
    first one."""
    _stage_split_domain_family(tmp_path)
    ctx = _ctx_for(tmp_path)
    assert ctx.status == "OK", ctx.work_items
    assert ctx.device_map["nmos"] == "famx_lv_nmos"
    assert ctx.device_map["pmos"] == "famx_lv_pmos"
    # and NOT what the historical rule would have said
    assert ctx.device_map["nmos"] != _old_rule(["famx_lv_nmos",
                                                "famx_hv_nmos"])


def test_903_the_elected_lib_follows_the_elected_device(tmp_path):
    """The device election is upstream of the PRIMARY-lib election
    (`_primary_rank` counts how many RESOLVED device names a lib defines), so
    fixing the flavour must also move the `.lib` line the deck loads — else the
    deck would bind a device the loaded section never defines."""
    _stage_split_domain_family(tmp_path)
    ctx = _ctx_for(tmp_path)
    assert Path(ctx.model_lib).name == "famx_corner_mos_lv.lib"
    assert [Path(p).name for p, _sec in ctx.deck_loads] == ["famx_corner_mos_lv.lib"]


# ── 2. the election is auditable, whatever it picks ────────────────────────

def test_903_the_election_records_why_it_picked_what_it_picked(tmp_path):
    """Not "is the answer right" but "can the answer be read back". An election
    that cannot say why is indistinguishable from a coin flip."""
    _stage_split_domain_family(tmp_path)
    ctx = _ctx_for(tmp_path)
    for role, loser in (("nmos", "famx_hv_nmos"), ("pmos", "famx_hv_pmos")):
        rec = ctx.device_election[role]
        assert rec["device"] == ctx.device_map[role]
        assert rec["basis"] == APDC.ELECTION_PREFERENCE
        assert loser in rec["rejected"]
        assert rec["voltage_domains_available"] == ["hv", "lv"]
        assert "per-block voltage domain" in rec["note"]


def test_903_the_disclosure_states_the_basis_and_the_domains(tmp_path):
    """An artefact that carries only the prose must still state the policy."""
    _stage_split_domain_family(tmp_path)
    ctx = _ctx_for(tmp_path)
    assert "device elected by:" in ctx.disclosure
    assert "nmos=%s" % APDC.ELECTION_PREFERENCE in ctx.disclosure
    assert "voltage domains available:" in ctx.disclosure


def test_903_the_election_survives_into_the_emitted_json(tmp_path):
    """`as_json` is what a consumer reads off disk."""
    _stage_split_domain_family(tmp_path)
    j = _ctx_for(tmp_path).as_json()
    assert j["device_election"]["nmos"]["basis"] == APDC.ELECTION_PREFERENCE
    assert j["device_election"]["nmos"]["device"] == j["device_map"]["nmos"]


# ── 3. the OPPOSITE verdict is still reachable ─────────────────────────────

def test_903_a_high_voltage_device_is_still_elected_when_it_is_the_only_one(
        tmp_path):
    """The fix DEMOTES an explicitly-elevated domain; it never refuses one. A
    family that ships only a high-voltage flavour must elect it, exactly as
    before — otherwise the fix would be a different bug."""
    _stage_single_domain_family(tmp_path, flavour="hv")
    ctx = _ctx_for(tmp_path)
    assert ctx.status == "OK", ctx.work_items
    assert ctx.device_map == {"nmos": "famx_hv_nmos", "pmos": "famx_hv_pmos"}
    assert ctx.device_election["nmos"]["basis"] == APDC.ELECTION_SOLE
    assert ctx.device_election["nmos"]["rejected"] == []
    # a single-flavour family is byte-identical to the historical rule
    assert ctx.device_map["nmos"] == _old_rule(["famx_hv_nmos"])


def test_903_name_order_is_still_reachable_and_is_named_as_such():
    """When NOTHING electrical distinguishes the candidates the historical
    shortest-then-lexicographic rule still decides — and the record says
    `name-order` rather than dressing it up as a preference."""
    names = ["famx_nmos_bb", "famx_nmos_a"]
    won, rec = APDC.elect_device_for_role(names)
    assert won == _old_rule(names) == "famx_nmos_a"
    assert rec["basis"] == APDC.ELECTION_NAME_ORDER
    assert rec["rejected"] == ["famx_nmos_bb"]
    assert "voltage_domains_available" not in rec


def test_903_no_flavour_signal_means_the_historical_answer_everywhere():
    """The blast-radius floor: for any candidate set carrying no variant
    marker, no domain component and no stated voltage, the new election and the
    old rule agree."""
    for names in (["famx_nmos"],
                  ["famx_nmos", "famx_nmos_wide"],
                  ["famx_pmos_b", "famx_pmos_a"],
                  ["p1_pmos", "p2_pmos", "p0_pmos"]):
        won, _rec = APDC.elect_device_for_role(names)
        assert won == _old_rule(names), names


# ── 4. the ranking itself, key by key (structural, no vendor literal) ──────

def test_903_a_stated_voltage_rating_ranks_below_a_lower_one():
    """A name that spells its rating is ranked by the HIGHEST voltage it
    spells; lowest wins. This is the case the historical rule got right only by
    luck — `..._g5v0` vs `..._10v0` tie on length and the alphabet picks the
    10 V part."""
    names = ["famx_nmos_g5v0", "famx_nmos_10v0"]
    assert len(names[0]) == len(names[1])
    assert _old_rule(names) == "famx_nmos_10v0"          # the alphabet
    won, rec = APDC.elect_device_for_role(names)
    assert won == "famx_nmos_g5v0"                       # the rating
    assert rec["basis"] == APDC.ELECTION_PREFERENCE


def test_903_a_special_variant_ranks_below_a_plain_device():
    """Special-Vt / isolated / varactor / ESD / native flavours are demoted —
    the intent `_ROLE_AVOID` states and never applied on this path."""
    for variant in ("famx_nmos_lvt", "famx_nmos_iso", "famx_nmos_esd",
                    "famx_nmos_nat"):
        names = [variant, "famx_nmos_plainer"]
        won, rec = APDC.elect_device_for_role(names)
        assert won == "famx_nmos_plainer", variant
        assert rec["basis"] == APDC.ELECTION_PREFERENCE


def test_903_a_vt_marker_is_not_read_as_a_voltage_domain():
    """`hvt` is a threshold flavour, not a high-voltage domain. Component
    matching is what keeps the two apart; a substring match would conflate
    them and demote the wrong device twice."""
    assert APDC.device_flavour_signals("famx_nmos_hvt")["domain"] is None
    assert APDC.device_flavour_signals("famx_hv_nmos")["domain"] == "hv"
    assert APDC.device_flavour_signals("famx_lv_nmos")["domain"] == "lv"
    assert APDC.device_flavour_signals("famx_nmos")["domain"] is None


def test_903_an_unmarked_name_is_never_demoted_by_the_domain_rule():
    """`lv` and "no domain component at all" rank EQUAL on purpose: this rule
    may only push an explicitly elevated domain down, never promote anything.
    Otherwise adding the rule would silently re-elect on families that never
    had a domain question."""
    s_absent = APDC.device_flavour_signals("famx_nmos")
    s_low = APDC.device_flavour_signals("famx_lv_nmos")
    assert s_absent["domain_rank"] == s_low["domain_rank"] == 0
    assert APDC.device_flavour_signals("famx_mv_nmos")["domain_rank"] == 1
    assert APDC.device_flavour_signals("famx_hv_nmos")["domain_rank"] == 2


def test_903_stated_volts_reads_the_highest_rating_in_the_name():
    f = APDC.device_flavour_signals
    assert f("famx_nmos_01v8")["stated_volts"] == 1.8
    assert f("famx_nmos_g5v0d10v5")["stated_volts"] == 10.5
    assert f("famx_nmos_20v0")["stated_volts"] == 20.0
    assert f("famx_nmos")["stated_volts"] is None


# ── 5. end to end into the A3 emit record ──────────────────────────────────

def test_903_a3_reports_which_path_bound_each_role_and_on_what_basis(
        tmp_path):
    """`resolve_role_models` used to take the context map verbatim and report
    nothing about it, which is why the dead preference went unnoticed for as
    long as it did. It now names the path AND carries the basis."""
    ctx_map = {"nmos": "famx_lv_nmos"}
    ctx_election = {"nmos": {"device": "famx_lv_nmos",
                             "basis": APDC.ELECTION_PREFERENCE,
                             "rejected": ["famx_hv_nmos"],
                             "voltage_domains_available": ["hv", "lv"],
                             "note": "spans 2 voltage-domain class(es)"}}
    models, unresolved, election = A3.resolve_role_models(
        {}, ["nmos"], ctx_map, ctx_election)
    assert models == {"nmos": "famx_lv_nmos"}
    assert unresolved == []
    assert election["nmos"]["source"] == "deck_context"
    assert election["nmos"]["basis"] == APDC.ELECTION_PREFERENCE
    assert election["nmos"]["rejected"] == ["famx_hv_nmos"]
    assert election["nmos"]["voltage_domains_available"] == ["hv", "lv"]


def test_903_a3_registry_fallback_still_works_and_names_itself(tmp_path):
    """The OTHER path — the registry list — is unchanged in what it picks, and
    now says that it is the one that picked."""
    entry = {"device_models": ["famx_nmos_01v8", "famx_nmos_g5v0"]}
    models, unresolved, election = A3.resolve_role_models(entry, ["nmos"], {})
    assert unresolved == []
    assert election["nmos"]["source"] == "registry"
    assert models["nmos"] == election["nmos"]["device"]


def test_903_a3_context_dict_carries_the_election(tmp_path):
    """The dict `resolve_pdk_context` returns is what the emit record is built
    from; the election must be in it, not only inside the nested
    `deck_context`."""
    _stage_split_domain_family(tmp_path)
    (tmp_path / "phase1" / "generated_docs").mkdir(parents=True)
    (tmp_path / "phase1" / "generated_docs"
     / "L19_CONSTRAINTS_PDK.json").write_text(
        '{"fields": {"pdk_target": "Famx N180 (custom node)"}}')
    out = A3.resolve_pdk_context(tmp_path, "famx180", "", ["nmos", "pmos"])
    assert out["role_models"]["nmos"] == "famx_lv_nmos"
    assert out["role_model_election"]["nmos"]["source"] == "deck_context"
    assert (out["role_model_election"]["nmos"]["basis"]
            == APDC.ELECTION_PREFERENCE)
    assert (out["deck_context"]["device_election"]["nmos"]["rejected"]
            == ["famx_hv_nmos"])
