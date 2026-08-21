"""The deck must LOAD every lib it BINDS a device from.

`custom_family_context` re-derives `device_map` from the elected PRIMARY lib and
keeps the cross-lib UNION map whenever the primary cannot cover a required role.
That is honest for the MAP — those devices do exist — but the deck emitted a
single `.lib <model_lib> <section>` line, so a device resolved out of a
DIFFERENT lib was bound and never defined. ngspice stops at `unknown subckt`.

The failure is only reachable for a family whose devices SPAN SEVERAL LIBS
(actives in one corner lib, passives in another). Such families do not share a
corner-section vocabulary between those libs, so each loaded lib must carry its
OWN section name — a second `.lib` line with the first lib's section would be
just as unloadable.

A SINGLE-LIB family must be unaffected: its primary closure IS the union, so
nothing is ever added and the deck keeps exactly one `.lib` line.

chip-AGNOSTIC: synthetic family, synthetic device and section names only.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import analog_pdk_deck_context as APDC         # noqa: E402


def _write_split_family(tmp_path):
    """Actives and passives in SEPARATE sectioned corner libs, each with its own
    corner vocabulary — the shape that reaches the defect."""
    act_dev = tmp_path / "act_devices.lib"
    act_dev.write_text(
        ".subckt synth_nch d g s b w=1 l=1\n.ends\n"
        ".subckt synth_pch d g s b w=1 l=1\n.ends\n", encoding="utf-8")
    pas_dev = tmp_path / "pas_devices.lib"
    pas_dev.write_text(
        ".subckt synth_cap_a p n c=1\n.ends\n"
        ".subckt synth_res_a p n r=1\n.ends\n", encoding="utf-8")
    # Corner aggregators: define nothing themselves, compose their sub-lib.
    act = tmp_path / "corner_act.lib"
    act.write_text(
        ".LIB dev_tt\n.include act_devices.lib\n.ENDL\n"
        ".LIB dev_ss\n.include act_devices.lib\n.ENDL\n", encoding="utf-8")
    pas = tmp_path / "corner_pas.lib"
    pas.write_text(
        ".LIB pas_typ\n.include pas_devices.lib\n.ENDL\n"
        ".LIB pas_wcs\n.include pas_devices.lib\n.ENDL\n", encoding="utf-8")
    return {"available": True, "source": "container_installed",
            "family": "synthfoundry180", "target": "synthfoundry180",
            "spice_libs": [str(act), str(pas)]}


def test_deck_loads_cover_every_bound_device(tmp_path):
    """Every device in device_map must be defined by SOME loaded (lib, section).

    FAILS on the unfixed program, which offers only the primary lib while the
    passive roles are bound out of a lib the deck never loads.
    """
    res = _write_split_family(tmp_path)
    ctx = APDC.resolve_deck_context(
        "synthfoundry180", res=res,
        required=("nmos", "pmos", "cap", "res"),
        reader=APDC._default_reader, container="")
    j = ctx.as_json()

    assert j["status"] == "OK", f"family did not resolve: {j.get('work_items')}"
    bound = set((j.get("device_map") or {}).values())
    assert {"synth_cap_a", "synth_res_a"} <= bound, (
        f"fixture did not bind the passive devices; device_map={j['device_map']}")

    loads = [tuple(dl) for dl in (j.get("deck_loads") or [])]
    assert loads, "the context offered no deck_loads at all"

    defined = set()
    for lib, section in loads:
        txt = APDC._default_reader(lib) or ""
        assert section in APDC.parse_sections(txt), (
            f"`.lib {lib} {section}` names a section that lib does not define "
            f"— a split family does not share one corner vocabulary")
        defined |= set(APDC.transitive_subckts(lib, txt, APDC._default_reader))

    unloaded = sorted(bound - defined)
    assert not unloaded, (
        f"device(s) {unloaded} are BOUND by the deck but defined by no loaded "
        f"lib — ngspice would stop at `unknown subckt`. loads={loads}")


def test_single_lib_family_still_loads_exactly_one_lib(tmp_path):
    """A family that legitimately has ONE lib must not gain a second `.lib`."""
    only = tmp_path / "corner_all.lib"
    only.write_text(
        ".LIB dev_tt\n"
        ".subckt synth_nch d g s b w=1 l=1\n.ends\n"
        ".subckt synth_pch d g s b w=1 l=1\n.ends\n"
        ".subckt synth_cap_a p n c=1\n.ends\n"
        ".subckt synth_res_a p n r=1\n.ends\n"
        ".ENDL\n", encoding="utf-8")
    res = {"available": True, "source": "container_installed",
           "family": "synthfoundry180", "target": "synthfoundry180",
           "spice_libs": [str(only)]}

    ctx = APDC.resolve_deck_context(
        "synthfoundry180", res=res,
        required=("nmos", "pmos", "cap", "res"),
        reader=APDC._default_reader, container="")
    j = ctx.as_json()

    assert j["status"] == "OK", f"single-lib family broke: {j.get('work_items')}"
    loads = [tuple(dl) for dl in (j.get("deck_loads") or [])]
    assert len(loads) <= 1, (
        f"a one-lib family must not require more than one `.lib` line; "
        f"got {loads}")
    if loads:
        assert loads[0][0] == j["model_lib"], (
            "the single load must be the elected primary itself")
