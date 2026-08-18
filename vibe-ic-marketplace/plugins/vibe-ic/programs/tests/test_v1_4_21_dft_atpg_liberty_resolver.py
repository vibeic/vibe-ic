"""v1.4.21 regression — the at-speed ATPG producers (DT1 transition-delay /
DT2 path-delay) must resolve a std-cell Liberty chip/PDK-AGNOSTICALLY.

Defect (spm clean-run): both producers globbed ONLY `input/pdk/liberty/*typ*.lib`
and, when that project-relative tree was absent (the mainstream sky130 flow whose
Liberty is container-baked and recorded per-project in pvt_matrix.json, NOT
shipped in-tree), fell through to a NON-EXISTENT `input/pdk/liberty/typ.lib`. So
gate-levelise read a missing file → producer verdict=ERROR → DT1/DT2 FAIL — a
false FAIL that never measured coverage. The shared `_resolve_design_liberty`
adds the flow-recorded-corner + shared-OSS-default fallbacks.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import transition_fault_atpg_run as tdf  # noqa: E402
import path_delay_fault_atpg_run as pdf  # noqa: E402
import lec_run  # noqa: E402


def _pvt(project: Path, corners):
    d = project / "phase2" / "stage2" / "constraints"
    d.mkdir(parents=True, exist_ok=True)
    (d / "pvt_matrix.json").write_text(json.dumps({
        "primary_corner": "TT", "corners": corners}))


def test_explicit_liberty_wins(tmp_path):
    assert tdf._resolve_design_liberty(tmp_path, "/x/my.lib") == "/x/my.lib"


def test_project_pdk_glob_preferred(tmp_path):
    libdir = tmp_path / "input" / "pdk" / "liberty"
    libdir.mkdir(parents=True)
    (libdir / "commercial_pdk_demo_typ.lib").write_text("library(x){}\n")
    got = tdf._resolve_design_liberty(tmp_path, None)
    assert got == "input/pdk/liberty/commercial_pdk_demo_typ.lib"


def test_falls_back_to_flow_recorded_primary_corner(tmp_path):
    # no input/pdk tree (sky130 studio flow) → use the TT corner from pvt_matrix
    _pvt(tmp_path, [
        {"label": "SS", "liberty": "/foss/pdks/sky130A/.../ss.lib"},
        {"label": "TT", "liberty": "/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/"
                                   "lib/sky130_fd_sc_hd__tt_025C_1v80.lib"},
        {"label": "FF", "liberty": "/foss/pdks/sky130A/.../ff.lib"}])
    got = tdf._resolve_design_liberty(tmp_path, None)
    assert got.endswith("sky130_fd_sc_hd__tt_025C_1v80.lib")


def test_flow_recorded_is_not_sky130_hardcoded_gf180(tmp_path):
    # a gf180 project records ITS own path → resolver returns gf180, proving the
    # fix is PDK-agnostic (not a sky130 literal)
    _pvt(tmp_path, [
        {"label": "TT", "liberty": "/foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_"
                                   "mcu7t5v0/liberty/gf180mcu_fd_sc_mcu7t5v0__tt_"
                                   "025C_5v00.lib"}])
    got = tdf._resolve_design_liberty(tmp_path, None)
    assert "gf180" in got and "sky130" not in got


def test_final_fallback_is_shared_oss_default(tmp_path):
    # neither project PDK glob nor pvt_matrix → shared single-source default
    got = tdf._resolve_design_liberty(tmp_path, None)
    assert got == lec_run.DEFAULT_LIBERTY


def test_path_delay_uses_the_same_shared_resolver():
    # DT2 delegates to the same chip-agnostic resolver (no duplicate logic)
    assert pdf._tdf._resolve_design_liberty is tdf._resolve_design_liberty


# ---------------------------------------------------------------------------
# The false-NOT_APPLICABLE anti-gaming guard (pure): a sequential design whose
# cut exposed 0 pairs must NOT self-report NOT_APPLICABLE (the coverage gate
# would silently pass it). The load-bearing predicate is detect_dff_cells on the
# SOURCE netlist — a design with flops is never "combinational".
# ---------------------------------------------------------------------------
def test_source_flop_presence_blocks_false_not_applicable():
    import fault_atpg_run as far  # noqa: E402
    sky130_seq = ("module m(input clk, output q);\n"
                  "  sky130_fd_sc_hd__dfxtp_1 r0 (.CLK(clk), .D(1'b0), .Q(q));\n"
                  "endmodule\n")
    combinational = ("module m(input a, output y);\n"
                     "  sky130_fd_sc_hd__inv_1 g0 (.A(a), .Y(y));\n"
                     "endmodule\n")
    # a sequential design is detected as having flops → the guard forbids N/A
    assert far.detect_dff_cells(sky130_seq) != ""
    # a genuinely combinational design has no flops → an honest N/A is allowed
    assert far.detect_dff_cells(combinational) == ""


# ---------------------------------------------------------------------------
# Container-guarded DECISIVE close-the-gap proof: on a sky130 netlist the real
# `fault cut` (given the now-detected cell) produces a full-scan cut — pseudo-
# PI/PO pairs, 0 residual flops — so DT1/DT2 measure real coverage instead of a
# false N/A. Skipped when the vibeic-eda container is unavailable.
# ---------------------------------------------------------------------------
import pytest  # noqa: E402
# vibe-ic#1128 — these skips mean A VERIFICATION DID NOT HAPPEN, not that
# one passed. Declared through `not_verified_tier` so the run's roll-up
# cannot count them under `passed`; see that module's docstring.
# vibe-ic#1283 — and the probe is TRI-STATE, not a bool. What used to be here
# was `except Exception: return False`, which files a probe that TIMED OUT
# under the same reason as a probe that looked and found nothing. `docker image
# inspect` reads local metadata and answers in milliseconds on an idle box; on
# a loaded one it loses the race, and the old shape then published "container
# not available" about an image whose presence it never established.
from not_verified_tier import (PROBE_PRESENT, probe,  # noqa: E402
                               probe_skip_reason)
PULL_REMEDY = 'docker pull ghcr.io/vibeic/vibeic-eda:$(cat tools/vibeic-eda/VERSION)'
RUN_REMEDY = 'bash tools/vibeic-eda/restart-eda.sh'

_IMAGE_STATE, _IMAGE_DETAIL = probe(
    ["docker", "image", "inspect", "ghcr.io/vibeic/vibeic-eda:0.3.9"])


@pytest.mark.skipif(
    _IMAGE_STATE != PROBE_PRESENT,
    reason=probe_skip_reason(_IMAGE_STATE, _IMAGE_DETAIL,
                             "vibeic-eda container not available",
                             RUN_REMEDY))
def test_sky130_fault_cut_produces_real_scan_pairs(tmp_path):
    import fault_atpg_run as far  # noqa: E402
    nl = tmp_path / "phase2" / "stage2" / "synth" / "spm_synth.v"
    nl.parent.mkdir(parents=True)
    body = ["module spm(input clk, input d0, input d1, output q0, output q1);"]
    body += ["  sky130_fd_sc_hd__dfxtp_1 r0 (.CLK(clk), .D(d0), .Q(q0));"]
    body += ["  sky130_fd_sc_hd__dfxtp_1 r1 (.CLK(clk), .D(d1), .Q(q1));"]
    body += ["endmodule"]
    nl.write_text("\n".join(body) + "\n")
    cells = far.detect_dff_cells(nl.read_text())
    assert cells == "sky130_fd_sc_hd__dfxtp_1"          # the fix detects it
    cut_rel = "phase2/stage2/dft/cut_netlist.v"
    ok, msg = tdf._ensure_cut(tmp_path, "phase2/stage2/synth/spm_synth.v",
                              cut_rel, "clk", None, None, timeout=60)
    assert ok, msg
    cut_text = (tmp_path / cut_rel).read_text()
    _t, _pi, _po, pairs = tdf.parse_cut_ports(cut_text)
    assert len(pairs) == 2                              # both flops cut to pairs
    assert far.detect_dff_cells(cut_text) == ""         # 0 residual flops
