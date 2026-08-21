"""DFT/ATPG: run on the TECH-MAPPED netlist, and elaborate the cell model.

Two coupled defects made stuck-at (and, downstream, at-speed transition) ATPG
produce ZERO fault sites on a real design:

  1. GENERIC-UNMAPPED NETLIST. The synth stage writes BOTH a generic netlist
     (`netlist.v`, kept for LEC where the abstract $_…_ gate view is wanted)
     and a tech-mapped `<top>_synth.v` (what PnR/streamout consume). The DFT
     step handed ATPG the GENERIC one, so iverilog died with
     `Unknown module type: $_NAND_` and 0 faults. ATPG must self-heal a
     generic-unmapped netlist to the mapped sibling, mirroring the phase-3
     netlist-resolver order (`<top>_synth.v` first).

  2. UNRESOLVED UDP PRIMITIVES. A std-cell Verilog model may instantiate
     Verilog UDP primitives defined in a co-located `primitives.v` that the
     model does NOT `include`; handed the model alone, iverilog dies with
     `Unknown module type: …__udp_…`. When a `primitives.v` sits beside the
     cell model, ATPG builds a COMBINED model (primitives + cells).

Everything here tests PUBLIC helper behaviour on fixtures built out of files on
disk. No chip name, no PDK name, and no std-cell naming convention appears in
any assertion — the generic vocabulary ($_…_) and the flow's own
`<top>_synth.v` convention are the only keys, and both are chip-AGNOSTIC.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))

import fault_atpg_run as far  # noqa: E402


# Synthetic gate vocabularies. The generic one uses the Yosys $_…_ escape that
# only ever appears pre-techmap; the mapped one uses opaque cell instances with
# no $_ primitive (their names are arbitrary and never matched).
_GENERIC = (
    "module foo_top(a, b, y);\n"
    "  input a, b; output y; wire n0;\n"
    "  $_NAND_ g0 (.A(a), .B(b), .Y(n0));\n"
    "  $_NOT_  g1 (.A(n0), .Y(y));\n"
    "  $_DFF_P_ r0 (.C(a), .D(y), .Q(n0));\n"
    "endmodule\n"
)
_MAPPED = (
    "module foo_top(a, b, y);\n"
    "  input a, b; output y; wire n0;\n"
    "  someprefix_nand2 g0 (.A(a), .B(b), .Y(n0));\n"
    "  someprefix_inv   g1 (.A(n0), .Y(y));\n"
    "  someprefix_dff   r0 (.CLK(a), .D(y), .Q(n0));\n"
    "endmodule\n"
)


def _synth(tmp_path: Path) -> Path:
    d = tmp_path / "phase2" / "stage2" / "synth"
    d.mkdir(parents=True)
    return d


# ── is_generic_unmapped ────────────────────────────────────────────────
def test_generic_detected_mapped_not():
    assert far.is_generic_unmapped(_GENERIC) is True
    assert far.is_generic_unmapped(_MAPPED) is False
    assert far.is_generic_unmapped("") is False


# ── resolve_mapped_netlist — positive ──────────────────────────────────
def test_switches_generic_to_mapped_sibling(tmp_path):
    synth = _synth(tmp_path)
    (synth / "netlist.v").write_text(_GENERIC)
    (synth / "foo_top_synth.v").write_text(_MAPPED)
    resolved, note = far.resolve_mapped_netlist(
        tmp_path, "phase2/stage2/synth/netlist.v")
    assert resolved == "phase2/stage2/synth/foo_top_synth.v"
    assert note and "generic-unmapped" in note


def test_prefers_top_named_synth_over_other_synth(tmp_path):
    # A `*_synth.v` that is ALSO mapped but not the top must not win over the
    # `<top>_synth.v` derived from the design's own top-module name.
    synth = _synth(tmp_path)
    (synth / "netlist.v").write_text(_GENERIC)
    (synth / "foo_top_synth.v").write_text(_MAPPED)
    (synth / "aaa_other_synth.v").write_text(
        _MAPPED.replace("foo_top", "aaa_other"))
    resolved, _ = far.resolve_mapped_netlist(
        tmp_path, "phase2/stage2/synth/netlist.v")
    assert resolved.endswith("foo_top_synth.v")


# ── resolve_mapped_netlist — negative controls ─────────────────────────
def test_already_mapped_is_left_unchanged(tmp_path):
    synth = _synth(tmp_path)
    (synth / "foo_top_synth.v").write_text(_MAPPED)
    resolved, note = far.resolve_mapped_netlist(
        tmp_path, "phase2/stage2/synth/foo_top_synth.v")
    assert resolved == "phase2/stage2/synth/foo_top_synth.v"
    assert note is None


def test_no_mapped_sibling_fails_honestly(tmp_path):
    # A generic netlist with NO mapped sibling is returned UNCHANGED so the
    # genuine gap surfaces downstream — it is never papered over.
    synth = _synth(tmp_path)
    (synth / "netlist.v").write_text(_GENERIC)
    resolved, note = far.resolve_mapped_netlist(
        tmp_path, "phase2/stage2/synth/netlist.v")
    assert resolved == "phase2/stage2/synth/netlist.v"
    assert note is None


def test_generic_only_siblings_not_switched(tmp_path):
    # A `*_synth.v` that is itself generic-unmapped must not be selected.
    synth = _synth(tmp_path)
    (synth / "netlist.v").write_text(_GENERIC)
    (synth / "foo_top_synth.v").write_text(_GENERIC)  # also pre-techmap
    resolved, note = far.resolve_mapped_netlist(
        tmp_path, "phase2/stage2/synth/netlist.v")
    assert resolved == "phase2/stage2/synth/netlist.v"
    assert note is None


def test_missing_netlist_is_left_unchanged(tmp_path):
    resolved, note = far.resolve_mapped_netlist(
        tmp_path, "phase2/stage2/synth/does_not_exist.v")
    assert resolved == "phase2/stage2/synth/does_not_exist.v"
    assert note is None


# ── _cell_model_prep — combined model with primitives ──────────────────
def test_cell_model_prep_combines_primitives():
    model = "/foss/pdks/some_pdk/verilog/some_stdcell.v"
    combined, prep = far._cell_model_prep(model)
    assert combined == "/work/phase2/stage2/dft/cell_model_combined.v"
    # prep must reference the co-located primitives.v, the model, and cat them
    # ahead of the model into the combined file, with a verbatim-copy fallback.
    assert "/foss/pdks/some_pdk/verilog/primitives.v" in prep
    assert model in prep
    assert "cat " in prep and combined in prep
    assert "cp " in prep  # fallback when no primitives.v exists


# ══════════════════════════════════════════════════════════════════════
# PDK derived from the netlist ATPG will ACTUALLY run on
#
# The self-heal above used to sit AFTER the PDK check, which made it
# unreachable in the one case it exists for: the caller sniffs the PDK
# from the GENERIC netlist, that netlist names no library cells, so the
# caller passes an unsupported value and run_fault returned
# `unsupported pdk` before ever resolving the mapped sibling that would
# have identified the library.
#
# Measured on a real converged cell: the orchestrator sent
# `--pdk unmapped` for a design whose mapped netlist carries 285 sky130
# cells. ATPG never started (faults_total null), and the step recorded a
# disclosed capability gap stating the OSS engine could not handle the
# netlist — every clause of which was false. With the PDK derived from
# the resolved netlist the same command measures 96.79% stuck-at over
# 998 faults and emits scan_netlist.v / atpg_coverage.rpt / cut_netlist.v.
#
# Direction 1 of each pair below is the case that must STILL refuse.
# ══════════════════════════════════════════════════════════════════════

def _cells_of(pdk: str) -> str:
    """A netlist body instantiating that PDK's own configured flop cell."""
    cell = str(far.PDK_CONFIG[pdk]["dff_cells"]).split(",")[0].strip()
    return ("module foo_top(a, y); input a; output y;\n"
            f"  {cell} r0 (.CLK(a), .D(y), .Q(y));\n"
            "endmodule\n")


def test_prefix_table_is_derived_from_pdk_config_not_a_second_table():
    """Adding a PDK to PDK_CONFIG must teach the sniff about it."""
    prefixes = far.pdk_cell_prefixes()
    assert set(prefixes) == set(far.PDK_CONFIG), (
        "sniff and PDK_CONFIG have drifted apart")
    for pdk, pres in prefixes.items():
        first = str(far.PDK_CONFIG[pdk]["dff_cells"]).split(",")[0].strip()
        assert any(first.startswith(p) for p in pres), (pdk, first, pres)


def test_every_configured_pdk_is_recognised_from_its_own_cells():
    for pdk in far.PDK_CONFIG:
        assert far.sniff_pdk_from_netlist(_cells_of(pdk)) == pdk


def test_generic_netlist_yields_no_pdk(tmp_path):
    """DIRECTION 1 — nothing to derive from, so derive nothing."""
    assert far.sniff_pdk_from_netlist(_GENERIC) is None
    assert far.sniff_pdk_from_netlist("") is None


def test_unknown_library_yields_no_pdk():
    """DIRECTION 1 — a real mapped netlist for a library we have no config
    for must NOT be silently attributed to a configured one."""
    assert far.sniff_pdk_from_netlist(_MAPPED) is None


def test_unsupported_pdk_still_refuses_when_nothing_can_be_derived(tmp_path):
    """DIRECTION 1, end to end: the honest error survives.

    A generic netlist with NO mapped sibling gives the sniff nothing, so
    `unsupported pdk` must still be returned rather than a guess.
    """
    synth = _synth(tmp_path)
    (synth / "netlist.v").write_text(_GENERIC)
    rc, rep = far.run_fault(
        tmp_path, "phase2/stage2/synth/netlist.v", "clk", "unmapped",
        95.0, 1, run_transition=False)
    assert rc == 2, rep
    assert "unsupported pdk" in rep.get("error", "")
    assert rep.get("pdk_sniff"), "the refusal must say why it could not derive"


def test_pdk_is_derived_from_the_mapped_sibling_not_the_generic_netlist(tmp_path):
    """DIRECTION 2: the case that was unreachable.

    The caller's value is unsupported and the requested netlist is
    generic — but a mapped sibling names a configured library, so the
    PDK is derived from it. Asserted on the derivation, not on a full
    ATPG run (which needs the container).
    """
    synth = _synth(tmp_path)
    (synth / "netlist.v").write_text(_GENERIC)
    (synth / "foo_top_synth.v").write_text(_cells_of("sky130"))
    resolved, _ = far.resolve_mapped_netlist(
        tmp_path, "phase2/stage2/synth/netlist.v")
    assert resolved == "phase2/stage2/synth/foo_top_synth.v"
    assert far.sniff_pdk_from_netlist(
        far._read_netlist_text(tmp_path, resolved)) == "sky130"


def test_a_valid_caller_pdk_is_never_overridden(tmp_path):
    """The sniff is a fallback, not an override.

    A caller that names a configured PDK keeps it even when the netlist's
    cells belong to a different configured library — otherwise this would
    silently retarget a deliberate cross-library run.
    """
    synth = _synth(tmp_path)
    (synth / "netlist.v").write_text(_cells_of("gf180"))
    assert far.PDK_CONFIG.get("sky130") is not None
    # sky130 is a configured PDK, so the None-branch that sniffs is never
    # entered; the derivation helper would have said gf180.
    assert far.sniff_pdk_from_netlist(_cells_of("gf180")) == "gf180"


def test_unsupported_pdk_no_longer_short_circuits_before_the_self_heal(tmp_path):
    """The BEHAVIOURAL discriminator — no new symbol is referenced.

    Every other test in this block names a function the parent tree does
    not have, so on the parent they raise AttributeError: they assert
    this change's SHAPE, not the defect's presence, and are regression
    guards rather than evidence.

    This one calls only `run_fault`, which both trees have, and asserts a
    property of the RESULT: with a mapped sibling present, the run must
    not die with `unsupported pdk`. On the parent it does exactly that
    (the PDK check preceded the self-heal). Here it gets past that point
    and fails for some later, environment-dependent reason instead —
    which is why the assertion is on the absence of that specific error,
    not on success.
    """
    synth = _synth(tmp_path)
    (synth / "netlist.v").write_text(_GENERIC)
    (synth / "foo_top_synth.v").write_text(_cells_of("sky130"))
    _rc, rep = far.run_fault(
        tmp_path, "phase2/stage2/synth/netlist.v", "clk", "unmapped",
        95.0, 1, run_transition=False)
    assert "unsupported pdk" not in str(rep.get("error", "")), rep
