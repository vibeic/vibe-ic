"""ORGANIC GAP-E2E-1 + GAP-E2E-7 — Phase-3 auto-SDC generation.

GAP-E2E-1 (SDC period inherit — NARROW residual)
    On the clean-project layout the Phase-3 minimal auto-SDC emitted a 20 ns
    clock even though Phase-1/Phase-2 captured period_ns=10 (Phase-2 sdc_gen
    writes a concrete 10 ns `create_clock` at phase2/stage1/fpga/*.sdc). Root
    cause: the L9 doc states the period as a `-period <PERIOD>` PLACEHOLDER plus
    a PDK-keyed lookup table, so `_resolve_clock_spec`'s L9/L1 prose regex found
    no literal and fell through to the 20 ns default. The Phase-2 emitted SDC was
    never consulted. Fix: `_phase2_emitted_period_ns` inherits the concrete
    Phase-2 period, ranked below the design's own staged SDC and above the prose.

    §4.05 NO-LEAK: only ever inherit an upstream-STATED (tightest) period; never
    fabricate a clock faster than any upstream source states; keep the default +
    disclose when nothing upstream states a period.

GAP-E2E-7 (SDC completeness — multicycle/false-path)
    The minimal auto-SDC lacked timing exceptions, so long combinational
    datapaths show spurious setup violations. SAFE subset: INGEST ONLY
    set_false_path / set_multicycle_path the design's OWN staged reference flow
    (input/constraints + input/reference_flow) explicitly authored — never
    auto-derive them (an exception MASKS a real violation). Phase-2's own
    heuristic-emitted exceptions are DELIBERATELY NOT ingested.
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402
import _path_layout as _pl  # noqa: E402


# ── layout helpers ──────────────────────────────────────────────────────────

def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _fpga_sdc(project: Path, name: str, period, port: str = "clk") -> Path:
    return _write(
        _pl.fpga_early_dir(project) / f"{name}.sdc",
        f"# phase2 sdc_gen fpga proto\n"
        f"create_clock -name clk_main -period {period} [get_ports {{{port}}}]\n",
    )


def _stage2_sdc(project: Path, name: str, period, port: str = "clk") -> Path:
    return _write(
        _pl.constraints_dir(project) / f"{name}.sdc",
        f"create_clock -name core_clock -period {period} [get_ports {port}]\n",
    )


def _input_constraints_sdc(project: Path, name: str, body: str) -> Path:
    return _write(project / "input" / "constraints" / f"{name}.sdc", body)


def _reference_flow_sdc(project: Path, rel: str, body: str) -> Path:
    return _write(project / "input" / "reference_flow" / rel, body)


def _l9_placeholder_doc(project: Path) -> Path:
    """Reproduces the spm-class L9: a `<PERIOD>` placeholder + a PDK-keyed
    lookup table — NO literal adjacent to a `-period` token."""
    return _write(
        project / "input" / "docs" / "L9_constraints_floorplan.md",
        "# L9 — Constraints / Floorplan\n"
        "## 9.1 SDC\n"
        "```tcl\n"
        "set_units -time ns\n"
        "create_clock [get_ports clk]  -name core_clock  -period <PERIOD>\n"
        "```\n"
        "### 9.1.2 `<PERIOD>` per library\n"
        "| Std-cell library | `<PERIOD>` (ns) | freq |\n"
        "| `sky130_fd_sc_hd` | 10 | 100 MHz |\n"
        "| `gf180mcu_*` | 24 | ~41.7 MHz |\n",
    )


# ═══════════════════════════════════════════════════════════════════════════
# GAP-E2E-1 — SDC period inherit
# ═══════════════════════════════════════════════════════════════════════════

def test_e2e1_inherits_phase2_fpga_period_10_not_20(tmp_path):
    """Phase-2 emitted a 10 ns fpga SDC, nothing staged in input/constraints →
    Phase-3 create_clock inherits 10, NOT the 20 ns default."""
    _fpga_sdc(tmp_path, "spm", 10)
    period, _port = R._resolve_clock_spec(tmp_path, top="chip_top")
    assert period == 10.0
    assert period != 20.0


def test_e2e1_spm_placeholder_l9_still_inherits_10(tmp_path):
    """spm reproduction: the L9 prose carries a `<PERIOD>` placeholder + PDK
    table (prose regex misses), but the Phase-2 fpga SDC supplies 10."""
    _l9_placeholder_doc(tmp_path)
    _fpga_sdc(tmp_path, "spm", 10)
    period, _port = R._resolve_clock_spec(tmp_path, top="chip_top")
    assert period == 10.0


def test_e2e1_no_upstream_period_keeps_default_no_fabrication(tmp_path):
    """No staged SDC, no Phase-2 SDC, no doc period, no config → the current
    20 ns default is kept (never fabricated faster)."""
    period, port = R._resolve_clock_spec(tmp_path, top="chip_top")
    assert period == 20.0
    assert port == "clk"
    assert R._phase2_emitted_period_ns(tmp_path, top="chip_top") is None


def test_e2e1_picks_smallest_stated_period(tmp_path):
    """Two Phase-2 SDCs (10 and 20) → the tightest STATED period (10) is
    inherited. A tighter period only makes STA more conservative."""
    _fpga_sdc(tmp_path, "main", 10)
    _fpga_sdc(tmp_path, "bist", 20)
    assert R._phase2_emitted_period_ns(tmp_path, top="chip_top") == 10.0


def test_e2e1_never_faster_than_upstream_states(tmp_path):
    """Upstream states exactly 12 → we return exactly 12, never a fabricated
    faster value."""
    _fpga_sdc(tmp_path, "main", 12)
    assert R._phase2_emitted_period_ns(tmp_path, top="chip_top") == 12.0
    period, _ = R._resolve_clock_spec(tmp_path, top="chip_top")
    assert period == 12.0


def test_e2e1_excludes_self_written_canon_copy(tmp_path):
    """The Phase-3 self-written canon copy phase2/stage2/constraints/<top>.sdc
    is excluded, so a stale faster prior-run artifact (5 ns) can NOT feed back
    in and win over the genuine upstream (10 ns)."""
    _fpga_sdc(tmp_path, "spm", 10)               # genuine upstream
    _stage2_sdc(tmp_path, "chip_top", 5)         # stale self-copy (top=chip_top)
    assert R._phase2_emitted_period_ns(tmp_path, top="chip_top") == 10.0


def test_e2e1_staged_input_sdc_still_wins(tmp_path):
    """Regression: the design's OWN staged input/constraints SDC (8 ns) ranks
    strictly ABOVE the Phase-2 emitted SDC (10 ns)."""
    _input_constraints_sdc(
        tmp_path, "constraint",
        "create_clock -name clk -period 8 [get_ports clk]\n")
    _fpga_sdc(tmp_path, "spm", 10)
    period, _ = R._resolve_clock_spec(tmp_path, top="chip_top")
    assert period == 8.0


def test_e2e1_docs_literal_period_still_resolves_without_phase2(tmp_path):
    """Regression: with a literal L9 doc period and NO Phase-2 SDC, the prose
    path still resolves (unchanged behaviour)."""
    _write(tmp_path / "input" / "docs" / "L9_x.md",
           "CLOCK_PERIOD = 15 ns\n")
    period, _ = R._resolve_clock_spec(tmp_path, top="chip_top")
    assert period == 15.0


def test_e2e1_stage2_constraints_period_inherited(tmp_path):
    """Phase-2 sign-off SDC in phase2/stage2/constraints is also a valid
    upstream source (non-self-copy name)."""
    _stage2_sdc(tmp_path, "spm_10ns", 10)
    assert R._phase2_emitted_period_ns(tmp_path, top="chip_top") == 10.0


# ═══════════════════════════════════════════════════════════════════════════
# GAP-E2E-7 — timing-exception ingest (SAFE subset only)
# ═══════════════════════════════════════════════════════════════════════════

def test_e2e7_ingests_reference_flow_exceptions(tmp_path):
    """A staged input/reference_flow SDC carrying set_false_path /
    set_multicycle_path → both exceptions appear in the Phase-3 SDC."""
    _reference_flow_sdc(
        tmp_path, "top/constraint.sdc",
        "create_clock -name clk -period 10 [get_ports clk]\n"
        "set_false_path -from [get_ports rst_n] -to [all_clocks]\n"
        "set_multicycle_path -setup 2 -to [get_ports slow_out]\n")
    sdc = R._build_auto_silicon_sdc(tmp_path, top="chip_top")
    assert "set_false_path -from [get_ports rst_n] -to [all_clocks]" in sdc
    assert "set_multicycle_path -setup 2 -to [get_ports slow_out]" in sdc


def test_e2e7_ingests_input_constraints_exceptions(tmp_path):
    """A staged input/constraints SDC exception is carried into the Phase-3 SDC."""
    _input_constraints_sdc(
        tmp_path, "constraint",
        "create_clock -name clk -period 10 [get_ports clk]\n"
        "set_multicycle_path -hold 1 -from [get_ports a]\n")
    sdc = R._build_auto_silicon_sdc(tmp_path, top="chip_top")
    assert "set_multicycle_path -hold 1 -from [get_ports a]" in sdc


def test_e2e7_no_staged_exceptions_emits_none(tmp_path):
    """Negative no-leak: with NO staged reference exceptions the Phase-3 SDC
    carries NO fabricated exception, and discloses that none were derived."""
    _fpga_sdc(tmp_path, "spm", 10)  # period source only
    exceptions = R._staged_timing_exceptions(tmp_path)
    assert exceptions == []
    sdc = R._build_auto_silicon_sdc(tmp_path, top="chip_top")
    assert "set_false_path" not in sdc
    assert "set_multicycle_path" not in sdc
    assert "none auto-derived" in sdc  # disclosure present


def test_e2e7_phase2_heuristic_exception_not_ingested(tmp_path):
    """§4.05 CRITICAL: a Phase-2 sdc_gen heuristic-emitted set_false_path in
    phase2/stage1/fpga/*.sdc is NOT the design's authored exception, so it is
    NOT carried into the silicon SDC (carrying it would MASK a real violation)."""
    _write(
        _pl.fpga_early_dir(tmp_path) / "spm.sdc",
        "create_clock -name clk_main -period 10 [get_ports {clk}]\n"
        "set_false_path -from [get_ports {rst}] -to [all_clocks]\n")
    assert R._staged_timing_exceptions(tmp_path) == []
    sdc = R._build_auto_silicon_sdc(tmp_path, top="chip_top")
    assert sdc.count("set_false_path") == 0
    # but the period IS inherited from the same phase2 fpga SDC
    assert "create_clock -name clk -period 10" in sdc


def test_e2e7_tcl_var_in_exception_resolves(tmp_path):
    """A `$var`-parameterised exception in a reference SDC resolves to the
    literal port before being carried."""
    _reference_flow_sdc(
        tmp_path, "top/constraint.sdc",
        "set rst_port rst_n\n"
        "create_clock -name clk -period 10 [get_ports clk]\n"
        "set_false_path -from [get_ports $rst_port] -to [all_clocks]\n")
    sdc = R._build_auto_silicon_sdc(tmp_path, top="chip_top")
    assert "set_false_path -from [get_ports rst_n] -to [all_clocks]" in sdc
    assert "$rst_port" not in sdc


def test_e2e7_dedup_verbatim_across_files(tmp_path):
    """The same exception staged in two files is carried ONCE, verbatim."""
    body = ("create_clock -name clk -period 10 [get_ports clk]\n"
            "set_false_path -from [get_ports rst_n] -to [all_clocks]\n")
    _input_constraints_sdc(tmp_path, "a", body)
    _reference_flow_sdc(tmp_path, "b/constraint.sdc", body)
    exceptions = R._staged_timing_exceptions(tmp_path)
    assert exceptions.count(
        "set_false_path -from [get_ports rst_n] -to [all_clocks]") == 1


def test_e2e7_comment_lines_skipped(tmp_path):
    """A commented-out exception is NOT ingested (only live directives)."""
    _input_constraints_sdc(
        tmp_path, "c",
        "create_clock -name clk -period 10 [get_ports clk]\n"
        "# set_false_path -from [get_ports x] -to [all_clocks]\n")
    assert R._staged_timing_exceptions(tmp_path) == []


def test_e2e7_only_exception_directives_collected(tmp_path):
    """Only set_false_path / set_multicycle_path are collected — set_input_delay
    and other directives are ignored."""
    _reference_flow_sdc(
        tmp_path, "top/c.sdc",
        "create_clock -name clk -period 10 [get_ports clk]\n"
        "set_input_delay 3 -clock clk [all_inputs]\n"
        "set_clock_groups -asynchronous -group clk\n"
        "set_false_path -from [get_ports rst_n]\n")
    exceptions = R._staged_timing_exceptions(tmp_path)
    assert exceptions == ["set_false_path -from [get_ports rst_n]"]


# ═══════════════════════════════════════════════════════════════════════════
# Real spm benchmark reproduction (skips if the reference tree is absent)
# ═══════════════════════════════════════════════════════════════════════════

def test_spm_real_project_reproduction():
    """End-to-end on the real spm reference tree: period inherits 10 (not 20)
    and NO fabricated exception is carried (spm's only false_path is Phase-2
    heuristic, correctly ignored)."""
    import pytest
    spm = (Path(__file__).resolve().parents[5]
           / "benchmark-data" / "ic" / "spm")
    if not (_pl.fpga_early_dir(spm) / "spm.sdc").is_file():
        pytest.skip("spm reference tree not present")
    period, _ = R._resolve_clock_spec(spm, top="chip_top")
    assert period == 10.0
    sdc = R._build_auto_silicon_sdc(spm, top="chip_top")
    assert "create_clock -name clk -period 10.0" in sdc
    assert "set_false_path" not in sdc
    assert "set_multicycle_path" not in sdc
