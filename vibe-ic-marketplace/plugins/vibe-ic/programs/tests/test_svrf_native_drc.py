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
















# v1.4.35 — the image's /etc/profile.d prints `[INFO] Final PATH variable:` to
# STDOUT on every login shell; `_docker_exec` uses `bash -lc`, so `command -v`
# stdout arrives banner-polluted. The resolver must still return the clean path.
_BANNER_POLLUTED = (
    "[INFO] Setting up iic-osic-tools ...\n"
    "[INFO] Final PATH variable: /foss/tools/bin:/usr/bin\n"
    "/foss/tools/bin/svrfdrc\n"
)
















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














def test_docker_exec_forwards_the_abort_probe_to_the_supervisor(monkeypatch):
    """THE MIDDLE LINK OF THE CHAIN, which neither neighbour covers.

    `test_the_drc_budget_is_a_no_output_predicate_not_a_wall_clock_ceiling`
    proves the DRC step HANDS an `abort_probe` to `_docker_exec`, and
    `test_progress_supervision_over_wallclock` proves `run_supervised` ACTS on
    one over a real child. Between them sits a one-line pass-through, and a
    one-line pass-through is exactly the kind of thing that is deleted by an
    unrelated edit and noticed by nobody, because both neighbours stay green.
    """
    seen = {}

    def fake_supervised(cmd, **kw):
        seen.update(kw)
        return R._wd.SupervisedResult(0, "", "", "natural", 0.0)

    monkeypatch.setattr(R._wd, "run_supervised", fake_supervised)
    monkeypatch.setattr(R._dwd, "new_job_pidfile", lambda: "/tmp/x.pid")
    monkeypatch.setattr(R._dwd, "cleanup_job_pidfile", lambda *a, **k: None)
    # THE ATTACH CHECK IS STUBBED. Since 1b0cbca8a every path into a
    # container goes through `_container_exec.docker_exec_argv`, which asks
    # `_eda_pin.container_attach_refusal` whether `vibeic-eda` RUNS THE
    # PINNED IMAGE before the argv is built. That is a question about the
    # host this test happens to run on; this test is about the one-line
    # pass-through of `abort_probe`. Unstubbed, it read the host's live
    # container and went red (CONTAINER_IMAGE_MISMATCH) on any host whose
    # `vibeic-eda` is not the pin -- a verdict about the host, not the link.
    import _eda_pin
    monkeypatch.setattr(_eda_pin, "container_attach_refusal", lambda c: "")
    probe = lambda: None                                    # noqa: E731
    R._docker_exec("vibeic-eda", "svrfdrc deck.rule a.gds a.rpt",
                   marker="a.gds", abort_probe=probe)
    assert seen.get("abort_probe") is probe, (
        "_docker_exec dropped the caller's convergence predicate on the floor; "
        "the DRC budget would then never fire and a going-nowhere run would "
        "hold a core until the 24h backstop")




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










# --------------------------------------------------------------------------
# FLOOR-STREAMOUT loud-WARN (v1.4.34): deck present + streamout map absent is
# the silent legacy-numbering fallback that produced spm's false-DRC wall.
# --------------------------------------------------------------------------










# --------------------------------------------------------------------------
# FLOOR-DRC cell-interior-exemption guard (v1.4.36): commercial deck present +
# std-cell exclusion marker unconfigured = the silent miss that re-checks
# foundry-qualified cell interiors → false FEOL over-fire (spm's 15 fails).
# --------------------------------------------------------------------------








# --------------------------------------------------------------------------
# Filler/decap master discovery for commercial PDKs (density fill enablement).
# --------------------------------------------------------------------------
