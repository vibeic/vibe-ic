"""Unit tests for fault_atpg_run.py.

Fault runs inside a Docker container so the heavy integration path cannot
be unit-tested without the image. These tests cover:
  - Argument parsing and PDK config validation
  - IO-error handling (missing project dir, missing netlist, bad pdk)

Full end-to-end Fault-in-Docker run is validated by the aon_timer pilot
(see reports/dft/coverage.json); no need to re-run in unit tests.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "fault_atpg_run.py"
assert SCRIPT.exists()

sys.path.insert(0, str(SCRIPT.parent))
import fault_atpg_run as far  # noqa: E402


def _run(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
    )


def test_missing_project_dir(tmp_path):
    r = _run(str(tmp_path / "nope"), "--clock", "clk")
    assert r.returncode == 2
    assert "not a directory" in r.stderr.lower()


def test_missing_netlist(tmp_path):
    r = _run(str(tmp_path), "--netlist", "synth/missing.v", "--clock", "clk")
    assert r.returncode == 2
    assert "netlist not found" in r.stderr.lower()


def test_unsupported_pdk(tmp_path):
    (tmp_path / "phase2" / "stage2" / "synth").mkdir(parents=True)
    (tmp_path / "phase2" / "stage2" / "synth" / "netlist.v").write_text("module top; endmodule\n")
    r = _run(str(tmp_path), "--clock", "clk", "--pdk", "nonexistent_pdk")
    # Program imports fine and gets to run_fault which returns exit 2 for bad pdk
    assert r.returncode in (1, 2)


def test_clock_arg_required(tmp_path):
    r = _run(str(tmp_path))
    assert r.returncode != 0
    assert "clock" in r.stderr.lower() or "required" in r.stderr.lower()


# --- image-resolution pinning ------------------------------------------------
# A floating `:latest` must never reach `docker run` from this program: it does
# not consult the registry, so it means "whatever this machine pulled, whenever".
# `_eda_image.resolve()` answers a digest, or a named local tag, and says so on
# stderr when it degrades.
#
# It used to be a literal kept in step with `tools/vibeic-eda/VERSION` by
# `sync_image_version.py`. Both are deleted — that file held vibeic-eda's version
# number inside this repo, so every image release needed a PR here — and the
# helper that located it went with them, unused.

def test_no_floating_fork_image_tag():
    """A floating `:latest` must never reach `docker run` from this program.

    THE SECOND HALF OF THIS TEST WAS RETIRED, and the reason is worth having in
    front of whoever reads it next. It used to also require a literal
    `vibeic-eda:X.Y.Z` in this file, on the stated ground that a pinned tag is
    "what the plugin was verified against". Measured 2026-08-20: nothing ever
    verified that — the publish step proved only that the tag was PULLABLE and
    wrote the verification claim anyway. The image is now RESOLVED from the
    registry to a DIGEST (`programs/_eda_image.py`), so demanding a version
    literal here would demand back the thing that was removed.

    What replaced it, by name, both proven to discriminate:
      * `test_the_eda_image_is_resolved_not_remembered.py
         ::test_the_image_consumers_carry_no_pinned_version[fault_atpg_run.py]`
      * `...::test_resolve_returns_a_digest_not_a_floating_tag`

    The half kept below is still true and still worth guarding: a digest is
    fine, a floating tag is not.
    """
    src = SCRIPT.read_text(encoding="utf-8")
    assert "vibeic-eda:latest" not in src, (
        "a floating :latest can silently resolve to a stale local image; the "
        "image is resolved to a digest through programs/_eda_image.py"
    )


def test_this_program_pins_no_image_version_at_all():
    """RETIRED AND RESTATED, not deleted.

    This was `test_pinned_tag_matches_version_source_of_truth`: it required a
    pinned `vibeic-eda:X.Y.Z` here and required it to equal
    `tools/vibeic-eda/VERSION`. That invariant is gone by intent — the image is
    resolved from the registry to a digest — so the guard is restated as its
    NEGATION rather than removed, which is the only version of "retire a check"
    that does not quietly reduce what is checked.

    The cross-file half (agreement with VERSION) is carried by
    `test_the_eda_image_is_resolved_not_remembered.py
     ::test_no_module_level_constant_freezes_an_image_version`, which sweeps
    every shipped program rather than this one.
    """
    src = SCRIPT.read_text(encoding="utf-8")
    tags = re.findall(r"vibeic-eda:(\d+\.\d+\.\d+)", src)
    assert not tags, (
        f"{SCRIPT.name} pins {sorted(set(tags))}. The image is RESOLVED, not "
        f"remembered: call programs/_eda_image.resolve()."
    )


# --- pure helpers: dff-cell detection / merge / cell-model resolution -------
# These back the commercial PDK fix where the PDK-config seed (DFFRQD1,DFFSQD1) did
# NOT match the netlist's real flop cell (DFFHQD1); auto-detect + union fixes
# it chip-AGNOSTICally, and the cell-model resolver lets the commercial Verilog
# sim model be supplied explicitly (the proprietary PDK ships only a liberty in
# the run dir).

def test_detect_dff_cells_commercial_pdk_dffhqd1():
    # 64 DFFHQD1 instances as emitted by yosys for the spm commercial PDK netlist.
    nl = "\n".join(f"  DFFHQD1 _{n}_ ( .CK(clk), .D(d{n}), .Q(q{n}) );"
                   for n in range(3))
    assert far.detect_dff_cells(nl) == "DFFHQD1"


def test_detect_dff_cells_sorted_unique_union():
    nl = ("  DFFSQD1 a ( .Q(x) );\n"
          "  DFFHQD1 b ( .Q(y) );\n"
          "  SDFFHQD1 c ( .Q(z) );\n"
          "  DFFHQD1 d ( .Q(w) );\n")
    assert far.detect_dff_cells(nl) == "DFFHQD1,DFFSQD1,SDFFHQD1"


def test_detect_dff_cells_ignores_wire_decls():
    # A wire/reg named dff_* must NOT be picked up as a cell instantiation.
    nl = ("  wire dff_out;\n"
          "  reg  dffstate;\n"
          "  NAND2D1 g0 ( .A(a), .B(b), .Y(y) );\n")
    assert far.detect_dff_cells(nl) == ""


def test_detect_dff_cells_sky130_infix(tmp_path=None):
    # v1.4.21 REGRESSION — sky130 flops are `sky130_fd_sc_hd__dfxtp_1` (lowercase
    # `__df` INFIX, not a DFF prefix). The auto-detect previously returned "" on
    # sky130 → `fault cut` got the wrong seed → cut NOTHING → 64 un-cut flops →
    # a FALSE NOT_APPLICABLE (a sequential design silently skipping TDF ATPG).
    nl = ("  sky130_fd_sc_hd__dfxtp_1 \\creg_reg[0]  (.CLK(clk), .D(d0), .Q(q0));\n"
          "  sky130_fd_sc_hd__dfrtp_1 \\creg_reg[1]  (.CLK(clk), .D(d1), .Q(q1));\n"
          "  sky130_fd_sc_hd__sdfxtp_1 u2 (.CLK(clk), .D(d2), .Q(q2));\n")
    got = far.detect_dff_cells(nl)
    assert "sky130_fd_sc_hd__dfxtp_1" in got
    assert "sky130_fd_sc_hd__dfrtp_1" in got
    assert "sky130_fd_sc_hd__sdfxtp_1" in got


def test_detect_dff_cells_gf180_infix():
    nl = ("  gf180mcu_fd_sc_mcu7t5v0__dffq_1 u0 (.D(x), .Q(y));\n"
          "  gf180mcu_fd_sc_mcu7t5v0__sdffq_1 u1 (.D(a), .Q(b));\n")
    got = far.detect_dff_cells(nl)
    assert "gf180mcu_fd_sc_mcu7t5v0__dffq_1" in got
    assert "gf180mcu_fd_sc_mcu7t5v0__sdffq_1" in got


def test_detect_dff_cells_yosys_inline_autoname_comment():
    # REGRESSION (caravel_user_project x sky130A) — a yosys `write_verilog`
    # netlist prints the cell's auto-name as an INLINE block comment BETWEEN the
    # instance name and its `(`. The detector's tail required `(` to immediately
    # follow the instance name, so EVERY flop line carrying such a comment
    # detected as zero flops → `--dff` fell back to a hard-coded seed matching
    # nothing → `fault cut` cut nothing → a sequential design self-skipped
    # (DT1 false NOT_APPLICABLE) or ERRORed (DT2/DT3), failing Steps DT2/DT3.
    # Generic pre-techmap ($_DFF_P_):
    nl_generic = (
        "  \\$_DFF_P_  \\mprj.counter.count_reg[0]  /* _1154_ */ (\n"
        "    .C(clk), .D(d0), .Q(q0)\n  );\n"
        "  \\$_DFF_P_  \\mprj.counter.ready_reg  /* _1153_ */ (\n"
        "    .C(clk), .D(d1), .Q(q1)\n  );\n")
    assert far.detect_dff_cells(nl_generic) == "\\$_DFF_P_"
    # Mapped sky130 flop whose line also carries the auto-name comment:
    nl_mapped = ("  sky130_fd_sc_hd__dfxtp_1 \\creg_reg[0]  /* _0007_ */ "
                 "(.CLK(clk), .D(d0), .Q(q0));\n")
    assert far.detect_dff_cells(nl_mapped) == "sky130_fd_sc_hd__dfxtp_1"


def test_detect_dff_cells_infix_no_false_positive_on_non_flops():
    # non-flop std cells that merely contain letters — buf/dly/mux/inv — must NOT
    # be mistaken for flops (only the `__[s][e]df…` D-flop family matches).
    # LATCHES (`__dl*`, `__lat*`) and delay (`__dly*`) never reach `df`.
    nl = ("  sky130_fd_sc_hd__buf_1 u0 (.A(a), .X(x));\n"
          "  sky130_fd_sc_hd__dlygate4sd3_1 u1 (.A(a), .X(x));\n"
          "  sky130_fd_sc_hd__dlrtp_1 u2 (.RESET_B(r), .D(d), .GATE(g), .Q(q));\n"
          "  sky130_fd_sc_hd__mux2_1 u3 (.A0(a), .A1(b), .S(s), .X(x));\n"
          "  sky130_fd_sc_hd__inv_1 u4 (.A(a), .Y(y));\n"
          "  gf180mcu_fd_sc_mcu7t5v0__latq_1 u5 (.D(d), .Q(q));\n")
    assert far.detect_dff_cells(nl) == ""


def test_detect_dff_cells_sky130_enable_flop_family(tmp_path=None):
    # v1.4.21 STEP-2.7 REGRESSION — the ENABLE-flop (`edf*`) and scan-enable-flop
    # (`sedf*`) families are the MOST common flop on real sky130 synth (yosys maps
    # `$_DFFE_*` → `edfxtp`; subservient has 1024 `edfxtp_1`). Missing them left a
    # clock-enabled sequential design with detect=="" → a FALSE NOT_APPLICABLE the
    # coverage gate silently passed (gate-gaming). `__s?e?df` must catch them.
    nl = ("  sky130_fd_sc_hd__edfxtp_1 \\r0  (.CLK(clk), .DE(e), .D(d0), .Q(q0));\n"
          "  sky130_fd_sc_hd__edfxbp_1 \\r1  (.CLK(clk), .DE(e), .D(d1), .Q(q1));\n"
          "  sky130_fd_sc_hd__sedfxtp_1 u2 (.CLK(clk), .DE(e), .D(d2), .Q(q2));\n")
    got = far.detect_dff_cells(nl)
    assert "sky130_fd_sc_hd__edfxtp_1" in got
    assert "sky130_fd_sc_hd__edfxbp_1" in got
    assert "sky130_fd_sc_hd__sedfxtp_1" in got
    # a pure-enable-flop sequential design is NEVER classified combinational —
    # this is the anti-gaming invariant the false-N/A guard relies on
    assert far.detect_dff_cells(nl) != ""


def test_detect_dff_cells_generic_yosys_primitives():
    # v1.4.22 REGRESSION — a Fault-emitted cut/scan netlist is in the GENERIC
    # yosys internal-cell vocabulary (`\$_DFF_P_`, `\$_DFFE_PP_`, `\$_SDFF_*`,
    # `\$_DFFSR_*`), NOT the PDK std-cell names. Missing this left a bogus non-cut
    # (a netlist full of `\$_DFF_P_` "generated by Fault") UN-recognised as having
    # flops → the cut-validity guard did NOT fire → the bogus cut was REUSED → a
    # false NOT_APPLICABLE for a sequential design (gate-gaming vector).
    nl = (
        r"  \$_DFF_P_ \flop_reg[0]  (.C(clk), .D(d0), .Q(q0));" "\n"
        r"  \$_DFFE_PP_ \flop_reg[1]  (.C(clk), .E(e), .D(d1), .Q(q1));" "\n"
        r"  \$_SDFF_PP0_ u2 (.C(clk), .R(r), .D(d2), .Q(q2));" "\n"
        r"  \$_DFFSR_PPP_ u3 (.C(clk), .S(s), .R(r), .D(d3), .Q(q3));" "\n"
    )
    got = far.detect_dff_cells(nl)
    assert r"\$_DFF_P_" in got
    assert r"\$_DFFE_PP_" in got
    assert r"\$_SDFF_PP0_" in got
    assert r"\$_DFFSR_PPP_" in got
    assert got != ""


def test_detect_dff_cells_generic_primitives_excludes_latch_sr_not():
    # generic latches (`\$_DLATCH_*`), set/reset (`\$_SR_*`) and gates (`\$_NOT_`,
    # `\$_AND_`) must NEVER be mistaken for flops — none carry the `DFF` token.
    nl = (
        r"  \$_DLATCH_P_ u4 (.E(e), .D(d4), .Q(q4));" "\n"
        r"  \$_SR_PP_ u5 (.S(s), .R(r), .Q(q5));" "\n"
        r"  \$_NOT_ u6 (.A(a), .Y(y));" "\n"
        r"  \$_AND_ u7 (.A(a), .B(b), .Y(y));" "\n"
    )
    assert far.detect_dff_cells(nl) == ""


def test_merge_dff_cells_unions_seed_and_detected():
    # seed misses the real cell (DFFHQD1); union must still include it.
    assert far.merge_dff_cells("DFFRQD1,DFFSQD1", "DFFHQD1") == \
        "DFFHQD1,DFFRQD1,DFFSQD1"
    assert far.merge_dff_cells(None, "DFFHQD1") == "DFFHQD1"
    assert far.merge_dff_cells("DFFRQD1", "") == "DFFRQD1"
    assert far.merge_dff_cells("", "") == ""
    # de-dups overlapping tokens with surrounding whitespace
    assert far.merge_dff_cells(" DFFHQD1 , DFFRQD1 ", "DFFHQD1") == \
        "DFFHQD1,DFFRQD1"


def test_resolve_cell_model_container_absolute_passthrough():
    assert far.resolve_cell_model("/pdk/verilog/x.v", None) == "/pdk/verilog/x.v"
    assert far.resolve_cell_model("/foss/pdks/y.v",
                                  {"cell_model": "/z.v"}) == "/foss/pdks/y.v"


def test_resolve_cell_model_project_relative_under_work():
    assert far.resolve_cell_model("input/pdk/verilog/m.v", None) == \
        "/work/input/pdk/verilog/m.v"
    assert far.resolve_cell_model("./a/b.v", None) == "/work/a/b.v"


def test_resolve_cell_model_falls_back_to_pdk_config_then_none():
    assert far.resolve_cell_model(None, {"cell_model": "/pdk/c.v"}) == "/pdk/c.v"
    assert far.resolve_cell_model(None, None) is None


def test_env_override_wins_over_pinned_candidates():
    r = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, sys.argv[1]); "
         "import fault_atpg_run as f; print(f.DOCKER_IMAGE)",
         str(SCRIPT.parent)],
        capture_output=True, text=True,
        env={**os.environ, "VIBEIC_EDA_IMAGE": "example/override:9.9.9"},
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().splitlines()[-1] == "example/override:9.9.9"
