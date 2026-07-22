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
