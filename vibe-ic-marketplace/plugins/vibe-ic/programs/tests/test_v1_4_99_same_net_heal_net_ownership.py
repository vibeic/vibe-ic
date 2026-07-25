#!/usr/bin/env python3
"""§4.05 — the same-net heal must verify the DIFFERENT-net-clean premise, not
infer it from the PDN marker alone.

Field evidence (commercial 180nm BCD, 683x683um die, 100% row utilisation):
the PDN was correctly inserted (PDN_INSERTED_ADAPTIVE), so the pre-existing
guard admitted the heal — yet 932 of the deck's 1287 MET1 sub-min-space edge
pairs were DIFFERENT-net (power-to-signal), because 9719 of 16123 placed
instances (FILL1/FILL2/DECAP*) participated in no net at all and the router
therefore never held signal routes min-space away from their metal. A 0.22um
close merged a filler VSS stub into signal net _01841_ — a real short.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import phase3_one_shot_runner as p3  # noqa: E402

_TECH_LEF = (
    "LAYER MET1\n  TYPE ROUTING ;\n  WIDTH 0.23 ;\n  SPACING 0.23 ;\n"
    "  SPACING 0.6 RANGE 10.001 100000 ;\nEND MET1\n")

_DEF_HEAD = (
    "VERSION 5.8 ;\nDESIGN x ;\nUNITS DISTANCE MICRONS 1000 ;\n"
    "DIEAREA ( 0 0 ) ( 1000 1000 ) ;\n")

_DEF_CONNECTED = _DEF_HEAD + (
    "COMPONENTS 2 ;\n"
    "    - u1 INVD1 + PLACED ( 0 0 ) N ;\n"
    "    - u2 INVD1 + PLACED ( 10 0 ) N ;\n"
    "END COMPONENTS\n"
    "NETS 1 ;\n    - n1 ( u1 Z ) ( u2 A ) ;\nEND NETS\n"
    # a CONFIRMED PDN: the marker in openroad.log is corroborated by real
    # strap GEOMETRY in SPECIALNETS. Without SHAPE STRIPE/RING the
    # measured-PDN check (_def_pdn_evidence: straps==0 and vias==0)
    # refuses FIRST, so the net-ownership guard under test is never
    # reached and the assertion pins the wrong refusal reason.
    "SPECIALNETS 1 ;\n"
    "    - VDD ( u1 VDD ) ( u2 VDD )\n"
    "      + ROUTED MET1 800 + SHAPE STRIPE ( 0 0 ) ( 0 100 )\n"
    "      NEW MET4 800 + SHAPE STRIPE ( 0 0 ) ( 100 0 ) ;\n"
    "END SPECIALNETS\n"
    "END DESIGN\n")

# same design + physical-only cells whose PG pins were never global-connected
_DEF_ORPHANS = _DEF_HEAD + (
    "COMPONENTS 4 ;\n"
    "    - u1 INVD1 + PLACED ( 0 0 ) N ;\n"
    "    - u2 INVD1 + PLACED ( 10 0 ) N ;\n"
    "    - FILLER_1 FILL1 + SOURCE DIST + PLACED ( 20 0 ) N ;\n"
    "    - FILLER_2 DECAP4 + SOURCE DIST + PLACED ( 30 0 ) N ;\n"
    "END COMPONENTS\n"
    "NETS 1 ;\n    - n1 ( u1 Z ) ( u2 A ) ;\nEND NETS\n"
    # a CONFIRMED PDN: the marker in openroad.log is corroborated by real
    # strap GEOMETRY in SPECIALNETS. Without SHAPE STRIPE/RING the
    # measured-PDN check (_def_pdn_evidence: straps==0 and vias==0)
    # refuses FIRST, so the net-ownership guard under test is never
    # reached and the assertion pins the wrong refusal reason.
    "SPECIALNETS 1 ;\n"
    "    - VDD ( u1 VDD ) ( u2 VDD )\n"
    "      + ROUTED MET1 800 + SHAPE STRIPE ( 0 0 ) ( 0 100 )\n"
    "      NEW MET4 800 + SHAPE STRIPE ( 0 0 ) ( 100 0 ) ;\n"
    "END SPECIALNETS\n"
    "END DESIGN\n")


def _mk(tmp_path, def_text):
    pnr = p3._pl.pnr_dir(tmp_path)
    pnr.mkdir(parents=True, exist_ok=True)
    (pnr / "openroad.log").write_text(
        "PDN_INSERTED_ADAPTIVE: MET1 follow-pins net=VDD/VSS width=0.8\n")
    (pnr / "routed.def").write_text(def_text)
    return pnr


def test_def_net_orphan_instances_counts_only_net_less_instances(tmp_path):
    _mk(tmp_path, _DEF_CONNECTED)
    n, detail = p3._def_net_orphan_instances(tmp_path)
    assert n == 0, detail

    _mk(tmp_path, _DEF_ORPHANS)
    n, detail = p3._def_net_orphan_instances(tmp_path)
    assert n == 2, detail
    assert "FILL1" in detail and "DECAP4" in detail
    assert "2/4" in detail


def _pdk(tl):
    return p3.PdkConfig(
        name="custom:pdk", liberty="l", tech_lef=str(tl), cell_lef="c",
        cell_gds=None, site="s", drc_deck=None,
        # 0.22 < MET1 min-space 0.23 -> passes the pre-existing min-space guard
        same_net_heal={"layers": [
            {"name": "MET1", "gds": "9/0", "max_bridge_um": 0.22}]})


def test_same_net_heal_refuses_when_metal_is_not_net_owned(tmp_path,
                                                           monkeypatch):
    """A CONFIRMED PDN plus a SAFE max_bridge_um is not enough: if any placed
    instance owns metal that belongs to no net, a sub-min-space gap to it is not
    evidence of same-net and the close would short a live signal to it."""
    tl = tmp_path / "tech.lef"
    tl.write_text(_TECH_LEF)
    gds = tmp_path / "x.gds"
    gds.write_bytes(b"\x00")
    monkeypatch.setattr(p3, "_tool_in_path", lambda c, t: True)
    calls = {}

    def _fake_exec(container, cmd, marker=None):
        calls["cmd"] = cmd
        return 1, "", "no-docker"
    monkeypatch.setattr(p3, "_docker_exec", _fake_exec)

    # (a) orphan physical cells -> REFUSE, and the container is never reached
    _mk(tmp_path, _DEF_ORPHANS)
    ok, note = p3._klayout_same_net_heal(tmp_path, "x", _pdk(tl),
                                         "vibeic-eda", gds)
    assert ok is False
    assert "REFUSED" in note and "participate in no net" in note
    assert "cmd" not in calls, "an unsafe heal must not reach the container"

    # (b) NEGATIVE CONTROL — same PDN, same safe max_bridge_um, but every
    # instance is net-owned: the guard must NOT fire, and the heal proceeds.
    _mk(tmp_path, _DEF_CONNECTED)
    ok2, note2 = p3._klayout_same_net_heal(tmp_path, "x", _pdk(tl),
                                           "vibeic-eda", gds)
    assert "participate in no net" not in note2, note2
    assert "HEAL_SPEC" in calls.get("cmd", ""), \
        "a net-owned design must still reach the heal exec"
