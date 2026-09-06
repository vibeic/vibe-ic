#!/usr/bin/env python3
"""svrf-native commercial DRC wiring (spm commercial PDK clean-run, 2026-07-11).

A commercial PDK ships its sign-off DRC as a Calibre/SVRF `.rule` deck. The
vibeic KLayout fork's native `svrfdrc` buddy (C++, no Python interpreter) runs
that deck NATIVELY, so `step_drc` can produce a real, license-free sign-off
verdict on the FOUNDRY'S OWN deck when the `calibre` binary is absent — instead
of returning ENV_UNAVAILABLE.

These tests pin the deterministic pieces (report tally parsing, buddy discovery
via `command -v svrfdrc`, the native-buddy invocation, and the ENV_UNAVAILABLE
fallback when the buddy is genuinely absent). The full container run is exercised
by the commercial PDK chip runs. Report format is byte-identical to the retired
run_svrf_drc.py, so the tally/classifier tests are unchanged.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

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


# v1.4.35 — the image's /etc/profile.d prints `[INFO] Final PATH variable:` to
# STDOUT on every login shell; `_docker_exec` uses `bash -lc`, so `command -v`
# stdout arrives banner-polluted. The resolver must still return the clean path.
_BANNER_POLLUTED = (
    "[INFO] Setting up iic-osic-tools ...\n"
    "[INFO] Final PATH variable: /foss/tools/bin:/usr/bin\n"
    "/foss/tools/bin/svrfdrc\n"
)


def test_clean_command_v_path_strips_login_banner():
    assert R._clean_command_v_path(_BANNER_POLLUTED, "svrfdrc") \
        == "/foss/tools/bin/svrfdrc"


def test_clean_command_v_path_passthrough_when_clean():
    assert R._clean_command_v_path("/foss/tools/bin/svrfdrc\n", "svrfdrc") \
        == "/foss/tools/bin/svrfdrc"


def test_clean_command_v_path_falls_back_to_name_when_only_chatter():
    # A shell builtin/alias resolution or an all-banner stdout → the name itself
    # (rc==0 already proved it resolved; never return empty).
    assert R._clean_command_v_path("[INFO] noise\n", "svrfdrc") == "svrfdrc"


def test_svrfdrc_bin_container_strips_banner_pollution(monkeypatch):
    # End-to-end: banner-polluted `command -v` stdout → clean resolved path,
    # NOT the 3-line `[INFO]...\n[INFO]...\n/foss/tools/bin/svrfdrc` string.
    monkeypatch.setattr(R, "_docker_exec",
                        lambda c, cmd, **k: (0, _BANNER_POLLUTED, ""))
    assert R._svrfdrc_bin_container("vibeic-eda") == "/foss/tools/bin/svrfdrc"


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
# v1.4.38 — DRC wall-clock budget (commercial-PDK sign-off floor): the stall
# watchdog never kills a 100%-CPU tool, so svrfdrc's pathological single-thread
# derived-layer build ran 4.4h unbounded.
#
# vibe-ic#925 — the BUDGET was right and the TIER was not. This block used to
# assert the kill returned `SKIPPED-CONDITION`, i.e. it pinned the defect: that
# word is EXCUSED, so the step left the denominator, and it is foreign to this
# runner's vocabulary, so `_aggregate_verdict` let it fall through its catch-all
# to a green `"PASS"`. The claim is corrected here; the behaviour it now pins is
# proven two-armed in `test_issue925_drc_timeout_is_not_excused.py`.
# --------------------------------------------------------------------------
def test_drc_wall_budget_default_and_env(monkeypatch):
    monkeypatch.delenv("VIBE_IC_DRC_BUDGET_S", raising=False)
    assert R._drc_wall_budget_s() == 7200.0          # 2h default
    monkeypatch.setenv("VIBE_IC_DRC_BUDGET_S", "3600")
    assert R._drc_wall_budget_s() == 3600.0
    monkeypatch.setenv("VIBE_IC_DRC_BUDGET_S", "notanumber")
    assert R._drc_wall_budget_s() == 7200.0          # invalid -> safe default
    monkeypatch.setenv("VIBE_IC_DRC_BUDGET_S", "0")
    assert R._drc_wall_budget_s() == 7200.0          # non-positive -> default


def _drc_probe_harness(tmp_path, monkeypatch, rc):
    """Drive `_try_svrf_native_drc` with a faked exec and hand back what the
    step passed to the supervisor, plus the StepResult."""
    monkeypatch.setattr(R, "_svrfdrc_bin_container", lambda c: "svrfdrc")
    monkeypatch.setattr(R, "_to_container_path", lambda p, c: p)
    seen = {}

    def _fake_exec(c, cmd, **k):
        seen.update(k)
        return (rc, "", "")
    monkeypatch.setattr(R, "_docker_exec", _fake_exec)
    gds = R._pl.pnr_dir(tmp_path) / "spm.gds"
    gds.parent.mkdir(parents=True, exist_ok=True)
    gds.write_text("gds")
    res = R._try_svrf_native_drc(
        tmp_path, "spm",
        R.PdkConfig(name="custom:commercial_pdk", liberty="x", tech_lef="x",
                    cell_lef="x", cell_gds=None, site="unit", drc_deck=None,
                    calibre_drc="/x/DRC.rule"),
        "vibeic-eda")
    return res, seen


@pytest.mark.parametrize("rc,expect", [
    (R._RC_ABORTED, "ABORTED_NO_OUTPUT"),
    (R._RC_STALLED, "STALLED"),
    (124, "CEILING"),
])
def test_try_svrf_native_drc_stop_is_blocked_not_excused_and_says_which(
        tmp_path, monkeypatch, rc, expect):
    """Every way this step can be STOPPED is BLOCKED, and the record says WHICH.

    BLOCKED is this runner's own word for "the check could not be completed, so
    NOTHING is known about the design", and `_aggregate_verdict` names it
    explicitly in the non-green bucket. Three stop states, three distinct
    labels — a reader must never have to guess whether the engine hung, was
    deliberately stopped, or hit the pathological backstop.
    """
    monkeypatch.delenv("VIBE_IC_DRC_BUDGET_S", raising=False)
    res, _seen = _drc_probe_harness(tmp_path, monkeypatch, rc)
    assert res.status == "BLOCKED"
    assert res.extras.get("finding") == "SVRFDRC_PERF_CEILING"
    assert res.extras.get("stopped_as") == expect


def test_the_drc_budget_is_a_no_output_predicate_not_a_wall_clock_ceiling(
        tmp_path, monkeypatch):
    """THE ASSERTION HERE WAS CORRECTED, NOT RELAXED.

    It used to read ``seen["hard_ceiling_s"] == 7200.0  # bounded, not the 24h
    ceiling`` — i.e. it required the step to hand its budget to the parameter
    `_watchdog`'s own docstring reserves for "a pathological-infinite-loop
    backstop ONLY ... NOT the primary control". Under that pin a DRC that was
    STREAMING violations into its report was killed at the same second as one
    stuck in the silent derived-layer build, because a clock cannot tell them
    apart.

    The budget is still 7200 s and still honours VIBE_IC_DRC_BUDGET_S; what
    changed is the QUESTION it answers. It is now spent only while the report
    has NOT grown, expressed through `abort_probe` — the primitive written for
    a job that is progressing and going nowhere. This test is strictly stronger
    than the line it replaces: it pins the budget value AND both directions of
    the predicate, neither of which the old single-number assertion could see.
    """
    monkeypatch.delenv("VIBE_IC_DRC_BUDGET_S", raising=False)
    res, seen = _drc_probe_harness(tmp_path, monkeypatch, R._RC_ABORTED)
    assert seen.get("hard_ceiling_s") is None, (
        "the DRC budget is back on the watchdog's pathological backstop — a "
        "wall-clock deadline wearing the watchdog's clothes")
    assert seen.get("log_path") is not None, (
        "the report is the only real progress signal this step has; it must be "
        "wired")
    probe = seen.get("abort_probe")
    assert callable(probe), "the DRC budget must be expressed as a predicate"

    # DIRECTION 1 — a report that is GROWING is never aborted, however long.
    rpt = tmp_path / "phase3" / "reports" / "drc_svrf_calibre.rpt"
    rpt.parent.mkdir(parents=True, exist_ok=True)
    fake_now = [0.0]
    monkeypatch.setattr(R.time, "monotonic", lambda: fake_now[0])
    for i in range(1, 6):
        rpt.write_text("x" * (i * 1000))
        fake_now[0] += 100_000.0            # a full day between looks
        assert probe() is None, (
            "a DRC that is still emitting report bytes was aborted")

    # DIRECTION 2 — a report that has STOPPED growing is aborted past the
    # budget, and the reason names the measurement rather than the clock.
    fake_now[0] += 7201.0
    reason = probe()
    assert reason, "a DRC that produced nothing for the whole budget ran on"
    assert "no new report bytes" in reason
    assert "7200" in reason


def test_drc_budget_env_override_still_governs_the_predicate(tmp_path,
                                                             monkeypatch):
    """The knob keeps working, on the predicate instead of on a clock."""
    monkeypatch.setenv("VIBE_IC_DRC_BUDGET_S", "60")
    _res, seen = _drc_probe_harness(tmp_path, monkeypatch, R._RC_ABORTED)
    probe = seen["abort_probe"]
    fake_now = [0.0]
    monkeypatch.setattr(R.time, "monotonic", lambda: fake_now[0])
    (tmp_path / "phase3" / "reports").mkdir(parents=True, exist_ok=True)
    assert probe() is None                  # first look establishes the baseline
    fake_now[0] += 30.0
    assert probe() is None                  # inside the 60 s budget
    fake_now[0] += 40.0
    assert probe()                          # past it, with nothing written


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


def test_streamout_warn_silent_when_no_deck_AT_ALL():
    # NO sign-off deck of any kind will run — `_signoff_drc_deck` returned None
    # because the PDK ships neither a Calibre `.rule` nor a KLayout deck. There
    # is then no verdict for the numbering to corrupt, so no warning.
    #
    # vibe-ic#789: the comment here used to read "OSS PDK path", which was
    # FALSE and is the reason this argument stayed Calibre-scoped for so long.
    # `None` does NOT mean "an OSS PDK": an OSS PDK such as nangate45 or asap7
    # ships a real KLayout `.lydrc` whose rules select layers BY NUMBER, so it
    # is a deck-PRESENT case (pinned in the test below), not this one. `None`
    # means one thing only — this run runs no sign-off DRC at all.
    assert R._streamout_layermap_warning(None, None) is None
    assert R._streamout_layermap_warning(None, "/pdk/lef/map.txt") is None


def test_streamout_warn_fires_for_a_KLAYOUT_deck_too(tmp_path):
    """vibe-ic#789 — the guard is keyed on DECK-PRESENT, not on the deck being
    a commercial Calibre deck.

    GDSII stores no layer names, so a KLayout `.lydrc` binds its rules to layer
    NUMBERS exactly as an SVRF deck does (`input(19, 0)`, `polygons(1, 0)`).
    A KLayout-deck PDK with no streamout map therefore has the SAME defect —
    and used to get NO warning, because the argument was `calibre_drc`."""
    w = R._streamout_layermap_warning("/pdk/klayout/drc/FreePDK45.lydrc", None)
    assert w is not None
    assert "FreePDK45.lydrc" in w
    assert "LEGACY" in w and "ARTEFACTS" in w
    # and a KLayout deck WITH a map stays silent, as the Calibre one does
    assert R._streamout_layermap_warning(
        "/pdk/klayout/drc/asap7.lydrc", "/pdk/tech/asap7.map") is None


def test_signoff_drc_deck_is_deck_presence_not_vendor():
    """`_signoff_drc_deck` names the deck the run will EXECUTE, from the same
    two fields `step_drc` dispatches on — and returns None only when there is
    no deck at all."""
    # Calibre-only PDK
    assert R._signoff_drc_deck("/pdk/calibre/KF_DRC.rule", None) == \
        "/pdk/calibre/KF_DRC.rule"
    # KLayout-only PDK (the case that used to read as "no deck")
    assert R._signoff_drc_deck(None, "/pdk/klayout/drc/asap7.lydrc") == \
        "/pdk/klayout/drc/asap7.lydrc"
    # both present → the KLayout deck, mirroring step_drc's own dispatch
    # (`if not pdk.drc_deck:` takes the Calibre route, so a KLayout deck wins)
    assert R._signoff_drc_deck("/pdk/calibre/KF_DRC.rule",
                               "/pdk/klayout/drc/x.lydrc") == \
        "/pdk/klayout/drc/x.lydrc"
    # genuinely deckless
    assert R._signoff_drc_deck(None, None) is None
    assert R._signoff_drc_deck("", "") is None


# --------------------------------------------------------------------------
# FLOOR-DRC cell-interior-exemption guard (v1.4.36): commercial deck present +
# std-cell exclusion marker unconfigured = the silent miss that re-checks
# foundry-qualified cell interiors → false FEOL over-fire (spm's 15 fails).
# --------------------------------------------------------------------------
def test_excl_marker_warn_fires_when_deck_present_marker_unconfigured():
    # ic1-spm's exact condition: a Calibre deck, no exclusion marker key.
    w = R._stdcell_exclusion_marker_warning("/pdk/calibre/KF_DRC_D4.20.rule", None)
    assert w is not None
    assert "KF_DRC_D4.20.rule" in w
    assert "stdcell_exclusion_marker_layer" in w and "OVER-FIRE" in w


def test_excl_marker_warn_fires_on_empty_string_marker():
    # An empty-string marker config is still "unconfigured".
    assert R._stdcell_exclusion_marker_warning("/pdk/calibre/DRC.rule", "") is not None


def test_excl_marker_warn_silent_when_marker_configured():
    # Marker wired (e.g. the deck's 113/0 don't-check layer) → no warning.
    assert R._stdcell_exclusion_marker_warning(
        "/pdk/calibre/DRC.rule", "113/0") is None


def test_excl_marker_warn_silent_when_no_deck():
    # No commercial deck (OSS PDK path) → no exclusion-marker concern.
    assert R._stdcell_exclusion_marker_warning(None, None) is None
    assert R._stdcell_exclusion_marker_warning(None, "113/0") is None


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
