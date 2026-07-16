#!/usr/bin/env python3
"""svrf-native commercial DRC wiring (spm commercial_pdk clean-run, 2026-07-11).

A commercial PDK ships its sign-off DRC as a Calibre/SVRF `.rule` deck. The
vibeic KLayout fork's native `svrfdrc` buddy (C++, no Python interpreter) runs
that deck NATIVELY, so `step_drc` can produce a real, license-free sign-off
verdict on the FOUNDRY'S OWN deck when the `calibre` binary is absent — instead
of returning ENV_UNAVAILABLE.

These tests pin the deterministic pieces (report tally parsing, buddy discovery
via `command -v svrfdrc`, the native-buddy invocation, and the ENV_UNAVAILABLE
fallback when the buddy is genuinely absent). The full container run is exercised
by the commercial_pdk chip runs. Report format is byte-identical to the retired
run_svrf_drc.py, so the tally/classifier tests are unchanged.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402


_SAMPLE_REPORT = """\
# SVRF-native DRC via KLayout KLayout 0.30.9
# deck=/x/Calibre_commercial_pdk_DRC_D4.20.rule  layout=/x/spm.gds  dbu=0.001
# 224 layers, 17531 derivations, 7394 rules  |  {'PASS': 7138, 'FAIL': 2}

PASS  SPACE.M1.1         EXTERNAL M1 < 0.23 [metrics=euclidian] -> 0
FAIL  WIDTH.M2.1         INTERNAL M2 < 0.28 [metrics=euclidian] -> 5
FAIL  ENC.CO.1           ENCLOSURE CO M1 < 0.06 [metrics=euclidian] -> 3
SKIP  ANT.M3             COPY antenna -> antenna routed to its own checker

# tally: {'PASS': 7138, 'FAIL': 2, 'SKIP': 1}
"""


def test_parse_svrf_tally_counts_and_failing_rules(tmp_path):
    rpt = tmp_path / "drc_svrf_calibre.rpt"
    rpt.write_text(_SAMPLE_REPORT)
    fails, passes, skips, failing = R._parse_svrf_tally(rpt)
    assert fails == 2
    assert passes == 1
    assert skips == 1
    assert failing == ["WIDTH.M2.1", "ENC.CO.1"]


def test_parse_svrf_tally_clean_report(tmp_path):
    rpt = tmp_path / "clean.rpt"
    rpt.write_text(
        "# SVRF-native DRC via KLayout\n"
        "# 224 layers ... | {'PASS': 7394}\n\n"
        "PASS  A.1  EXTERNAL A < 1 [x] -> 0\n"
        "PASS  B.1  INTERNAL B < 1 [x] -> 0\n\n"
        "# tally: {'PASS': 7394}\n")
    fails, passes, skips, failing = R._parse_svrf_tally(rpt)
    assert fails == 0 and passes == 2 and skips == 0 and failing == []


def test_parse_svrf_tally_missing_file(tmp_path):
    fails, passes, skips, failing = R._parse_svrf_tally(tmp_path / "nope.rpt")
    assert (fails, passes, skips, failing) == (0, 0, 0, [])


def test_svrfdrc_bin_container_found_via_command_v(monkeypatch):
    # The native `svrfdrc` buddy is baked on PATH in the vibeic-eda image; a
    # `command -v` returning rc=0 resolves its command/path — a clean install
    # needs NO host checkout (a compiled binary can't be mounted in anyway).
    monkeypatch.setattr(R, "_docker_exec",
                        lambda c, cmd, **k: (0, "/foss/tools/bin/svrfdrc\n", ""))
    assert R._svrfdrc_bin_container("vibeic-eda") == "/foss/tools/bin/svrfdrc"


def test_svrfdrc_bin_container_none_when_absent(monkeypatch):
    # rc!=0 (buddy not in image) → None → step_drc emits honest ENV_UNAVAILABLE.
    monkeypatch.setattr(R, "_docker_exec", lambda c, cmd, **k: (1, "", ""))
    assert R._svrfdrc_bin_container("vibeic-eda") is None


def test_svrfdrc_bin_container_env_override(monkeypatch):
    # The command name is overridable for a differently-laid-out image.
    monkeypatch.setenv("VIBE_IC_SVRFDRC_BIN", "/opt/svrfdrc")
    seen = {}

    def _fake_exec(c, cmd, **k):
        seen["cmd"] = cmd
        return (0, "/opt/svrfdrc\n", "")
    monkeypatch.setattr(R, "_docker_exec", _fake_exec)
    assert R._svrfdrc_bin_container("vibeic-eda") == "/opt/svrfdrc"
    assert "command -v /opt/svrfdrc" in seen["cmd"]


def test_try_svrf_native_drc_returns_none_when_buddy_absent(
        tmp_path, monkeypatch):
    # When the buddy is absent from the image, the helper returns None so step_drc
    # falls through to the honest ENV_UNAVAILABLE (never a fabricated PASS).
    monkeypatch.setattr(R, "_svrfdrc_bin_container", lambda c: None)
    res = R._try_svrf_native_drc(
        tmp_path, "spm",
        R.PdkConfig(name="custom:commercial_pdk", liberty="x", tech_lef="x",
                    cell_lef="x", cell_gds=None, site="unit", drc_deck=None,
                    calibre_drc="/x/DRC.rule"),
        "vibeic-eda")
    assert res is None


def test_try_svrf_native_drc_invokes_native_buddy(tmp_path, monkeypatch):
    # When the buddy IS present, the command is the NATIVE
    # `svrfdrc <deck> <layout> <report> --cell=TOP` — NOT `klayout -b -r
    # run_svrf_drc.py`. Proves the interpreter path is fully retired.
    monkeypatch.setattr(R, "_svrfdrc_bin_container", lambda c: "svrfdrc")
    monkeypatch.setattr(R, "_to_container_path", lambda p, c: p)
    seen = {}

    def _fake_exec(c, cmd, **k):
        seen["cmd"] = cmd
        return (0, "", "")
    monkeypatch.setattr(R, "_docker_exec", _fake_exec)
    gds = R._pl.pnr_dir(tmp_path) / "spm.gds"
    gds.parent.mkdir(parents=True, exist_ok=True)
    gds.write_text("gds")
    R._try_svrf_native_drc(
        tmp_path, "spm",
        R.PdkConfig(name="custom:commercial_pdk", liberty="x", tech_lef="x",
                    cell_lef="x", cell_gds=None, site="unit", drc_deck=None,
                    calibre_drc="/x/DRC.rule"),
        "vibeic-eda")
    assert seen["cmd"].startswith("svrfdrc ")
    assert "--cell=spm" in seen["cmd"]
    assert "run_svrf_drc.py" not in seen["cmd"]
    assert " -r " not in seen["cmd"]


def test_step_drc_env_unavailable_names_buddy(tmp_path, monkeypatch):
    # calibre absent + svrfdrc buddy absent → ENV_UNAVAILABLE mentioning svrfdrc.
    monkeypatch.setattr(R, "_tool_in_path", lambda c, t: False)
    monkeypatch.setattr(R, "_svrfdrc_bin_container", lambda c: None)
    pdk = R.PdkConfig(name="custom:commercial_pdk", liberty="x", tech_lef="x",
                      cell_lef="x", cell_gds=None, site="unit", drc_deck=None,
                      calibre_drc="/x/DRC.rule")
    res = R.step_drc(tmp_path, "spm", pdk, "vibeic-eda")
    assert res.status == "ENV_UNAVAILABLE"
    assert "svrfdrc" in res.detail


# --------------------------------------------------------------------------
# LEF->GDS streamout layermap discovery (so GDS gets the foundry's real layer
# numbers; without it a sign-off deck misreads routing layers).
# --------------------------------------------------------------------------
# Encounter/SoC streamout map: "<lefname> <purpose> <gdslayer> <gdsdatatype>".
_KF_STREAMOUT_MAP = """\
# KF common layermap for SOC encounter
MET1            NET         9               0
VIA1            VIA         10              0
MET2            NET         11              0
"""

# A Virtuoso .layermap is NOT the streamout format (no <name purpose int int>).
_VIRTUOSO_MAP = """\
; MPDK layer table
LayerName  Purpose  ...
MET1  drawing
"""


def test_discover_lefdef_layermap_finds_encounter_map(tmp_path):
    lef = tmp_path / "input" / "pdk" / "lef" / "m18_lef"
    lef.mkdir(parents=True)
    m = lef / "KF_common_layermap_for_SOC_encounter.txt"
    m.write_text(_KF_STREAMOUT_MAP)
    found = R._discover_lefdef_layermap(tmp_path)
    assert found == str(m)


def test_discover_lefdef_layermap_skips_non_streamout_format(tmp_path):
    # A file named *.layermap but NOT in streamout format must be rejected by
    # the FORMAT probe (so we never feed a Virtuoso table to GDS streamout).
    v = tmp_path / "virtuoso" / "MPDK.layermap"
    v.parent.mkdir(parents=True)
    v.write_text(_VIRTUOSO_MAP)
    assert R._discover_lefdef_layermap(tmp_path) is None


def test_discover_lefdef_layermap_prefers_encounter_over_virtuoso(tmp_path):
    (tmp_path / "virtuoso").mkdir()
    (tmp_path / "virtuoso" / "MPDK.layermap").write_text(_VIRTUOSO_MAP)
    lef = tmp_path / "lef"
    lef.mkdir()
    m = lef / "KF_common_layermap_for_SOC_encounter.txt"
    m.write_text(_KF_STREAMOUT_MAP)
    assert R._discover_lefdef_layermap(tmp_path) == str(m)


def test_discover_lefdef_layermap_none_when_absent(tmp_path):
    (tmp_path / "input").mkdir()
    assert R._discover_lefdef_layermap(tmp_path) is None


# --------------------------------------------------------------------------
# FLOOR-STREAMOUT loud-WARN (v1.4.34): deck present + streamout map absent is
# the silent legacy-numbering fallback that produced spm's false-DRC wall.
# --------------------------------------------------------------------------
def test_streamout_warn_fires_when_deck_present_map_absent():
    # The exact ic1-spm condition: a sign-off DRC deck exists, no streamout map.
    w = R._streamout_layermap_warning("/pdk/calibre/KF_DRC_D4.20.rule", None)
    assert w is not None
    # Loud + actionable: names the deck, calls out legacy numbering + artefacts.
    assert "KF_DRC_D4.20.rule" in w
    assert "LEGACY" in w and "ARTEFACTS" in w


def test_streamout_warn_silent_when_map_present():
    # A discoverable streamout map → no warning (GDS lands on foundry numbers).
    assert R._streamout_layermap_warning(
        "/pdk/calibre/KF_DRC.rule", "/pdk/lef/KF_layermap_SOC.txt") is None


def test_streamout_warn_silent_when_no_deck():
    # No sign-off deck → legacy numbering is irrelevant (OSS PDK path); no warning
    # even if the map is also absent.
    assert R._streamout_layermap_warning(None, None) is None
    assert R._streamout_layermap_warning(None, "/pdk/lef/map.txt") is None


# --------------------------------------------------------------------------
# Filler/decap master discovery for commercial PDKs (density fill enablement).
# --------------------------------------------------------------------------
def _pdk_with_lef(lef_path):
    return R.PdkConfig(name="custom:kf", liberty="x", tech_lef="x",
                       cell_lef=str(lef_path), cell_gds=None, site="unit",
                       drc_deck=None)


def test_discover_filler_masters_orders_decap_then_fill_largest_first(tmp_path):
    lef = tmp_path / "cells.lef"
    lef.write_text(
        "MACRO FILL1\nMACRO FILL64\nMACRO FILL8\n"
        "MACRO DECAP4\nMACRO DECAP64\n"
        "MACRO INV_1\nMACRO NAND2_2\n")   # non-filler cells ignored
    got = R._discover_filler_masters_from_lef(str(lef))
    # decaps largest-first, then fills largest-first
    assert got == ["DECAP64", "DECAP4", "FILL64", "FILL8", "FILL1"]


def test_filler_masters_for_custom_pdk_uses_lef_discovery(tmp_path):
    lef = tmp_path / "cells.lef"
    lef.write_text("MACRO FILL2\nMACRO FILL16\nMACRO DECAP8\n")
    pdk = _pdk_with_lef(lef)          # tapcell_master=None → not sky130
    assert R._filler_masters_for_pdk(pdk) == ["DECAP8", "FILL16", "FILL2"]


def test_filler_masters_empty_when_no_fillers(tmp_path):
    lef = tmp_path / "cells.lef"
    lef.write_text("MACRO INV_1\nMACRO NAND2_2\nMACRO DFF_1\n")
    assert R._filler_masters_for_pdk(_pdk_with_lef(lef)) == []


def test_filler_masters_sky130_unchanged():
    pdk = R.PdkConfig(name="sky130A", liberty="x", tech_lef="x", cell_lef="x",
                      cell_gds=None, site="unit", drc_deck=None,
                      tapcell_master="sky130_fd_sc_hd__tapvpwrvgnd_1")
    got = R._filler_masters_for_pdk(pdk)
    assert got and all("sky130_fd_sc_hd" in m for m in got)
