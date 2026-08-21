"""v0.1.49 — Netgen supplementary LVS setup-file generator.

What this is
============

A deterministic emitter for the Netgen TCL fragment that gets sourced
AFTER the foundry-provided `<pdk>_setup.tcl` and BEFORE `lvs <c1> <c2>`,
to close the open-source-SkyWater-style net-level LVS gap documented
in the spm pilot `RESULT_tier4_5_lvs_attempts.md` and validated by
external review.

Why a PROGRAM, not a SKILL
==========================

The Netgen-side gap closure rules are deterministic:

  1. Power-net globalisation — `global vccd1 vssd1` etc. — is a fixed
     list per PDK. Magic's `ext2spice` does NOT mark power as `.global`,
     so Netgen sees a separate VPWR-per-instance flat net; the standard
     remediation is a `global` declaration per power name.

  2. Stdcell-library `<lib>__<cell>` ↔ `<cell>` equate is already in
     the foundry setup (e.g. `sky130A_setup.tcl`), so we MUST NOT
     duplicate it — but we DO want to surface that we relied on it.

  3. Symmetric-MOS source-drain `permute default` is in the foundry
     setup too.

  4. Optional `flatten class` directives — used when the layout vs
     schematic differ in stdcell-hierarchy granularity (e.g. yosys
     flatten vs ext2spice subckt). Off by default; opt-in.

  5. Conditional `ignore class` for tap / fill / decap — already in
     the foundry setup, gated by `MAGIC_EXT_USE_GDS=1`. We surface
     a comment so an audit can see we're aware.

All five rules are deterministic. A skill (LLM authoring) is not
needed; the user supplies (PDK, list of power nets, options), and
the program emits the fragment. This follows the
[[closed-loop-enhancement-capture-doctrine]]: deterministic rule → Bucket A program.

Reference
=========

  - Foundry setup: `<PDK>/libs.tech/netgen/<pdk>_setup.tcl`
  - Netgen tutorial 2: Interpreting LVS Results
  - spm pilot empirical evidence:
      `RESULT_tier4_5_lvs_attempts.md` (4 prior open-source attempts)
      `PHASE_C_CLEANUP_RESULT.md` § Tier 4.5 LVS net-level gap

Unit-tested in `programs/tests/test_lvs_netgen_setup_emit.py`.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import plugin_manifest_discovery as _pmd  # noqa: E402  (#800 ONE version reader)


# ---------------------------------------------------------------------------
# Per-PDK power-net default lists. These are the names Magic's `ext2spice`
# emits as ordinary nets (which Netgen then sees as separate per-instance
# nets unless they are declared `global`). Magic itself does support a
# `.global` directive on ext2spice when MAGIC_GLOBAL is set, but the
# default open-source flow doesn't.
# ---------------------------------------------------------------------------
PDK_POWER_NETS: Dict[str, List[str]] = {
    # SKY130A (Open Process Design Kit, SkyWater 130nm).
    # vccd1/vssd1: chipignite user-area 1.8V digital domain.
    # vccd2/vssd2: chipignite user-area 1.8V digital domain (2nd).
    # vdda1/2, vssa1/2: user-area 3.3V analog domains.
    # vddio/vssio: I/O ring 3.3V.
    # VPWR/VGND/VPB/VNB: per-cell std-cell PG pins (Liberty convention).
    "sky130A": [
        "vccd1", "vssd1", "vccd2", "vssd2",
        "vdda1", "vssa1", "vdda2", "vssa2",
        "vddio", "vssio",
        "VPWR", "VGND", "VPB", "VNB",
    ],
    # GF180 (GlobalFoundries 180nm MCU) — single-domain VDD/VSS rails plus the
    # per-cell WELL-BIAS pins VNW (n-well tie) / VPW (p-well tie).
    #
    # The prior list carried "VPWR"/"VGND", which are SKY130 names that DO NOT
    # EXIST anywhere in gf180mcu. Measured on the shipped PDK
    # (`gf180mcu_fd_sc_mcu7t5v0.lef`, vibeic-eda:0.2.24): the complete set of
    # pins with `USE POWER`/`USE GROUND` across the whole std-cell library is
    # exactly {VDD, VNW, VPW, VSS} — e.g. `inv_1` declares VDD (Metal1),
    # VNW (Nwell), VPW (Pwell), VSS (Metal1). So the old list globalised two
    # names that match nothing and MISSED the two that carry the well bias.
    #
    # Consequence: the real per-instance VNW/VPW well nets were never
    # globalised, netgen saw a flat `<inst>/VNW` net per cell
    # ("Net: _NNN_/VNW | (no matching net)") and the POWER-AWARE compare
    # reported "Netlists do not match". It was MASKED on the plain compare,
    # which drops the wells entirely.
    #
    # Globalising the ACTUAL gf180 PG/well names lets the per-cell VNW/VPW pins
    # collapse to single nets that match the power-aware schematic (the wells
    # are tied to the rails at the PDN; the routed DEF's VDD SPECIALNET carries
    # the VNW pins). This restores THIS PDK's own pin semantics — it is not a
    # waiver and it relaxes no gate.
    "gf180mcuC": ["VDD", "VSS", "VNW", "VPW"],
    "gf180mcuD": ["VDD", "VSS", "VNW", "VPW"],
    # IHP SG13G2 (open-source 130nm BiCMOS). The PDK's own Magic startup
    # file states the three names authoritatively:
    #     libs.tech/magic/ihp-sg13g2.magicrc
    #       set VDD VDD ; set GND VSS ; set SUB sub!
    # `sub!` is a Magic GLOBAL node, but ext2spice emits it as an ordinary
    # top-level node, so netgen sees an extra layout PORT `sub` with no
    # schematic counterpart and reports "Netlists do not match" on an
    # otherwise-clean compare. Globalising it restores the PDK's own
    # declared semantics — it is not a waiver.
    "ihp-sg13g2": ["VDD", "VSS", "sub"],
    # NanGate45 / ASAP7 — single-domain VDD/VSS.
    "nangate45": ["VDD", "VSS"],
    "asap7": ["VDD", "VSS"],
}


# ---------------------------------------------------------------------------
# Per-PDK std-cell library name -> regex used by foundry setup to detect
# tap/fill/decap. Reused here to emit an audit comment so a reader knows
# which cells were considered for `ignore class` waiving by the foundry
# setup (we don't emit those rules — the foundry setup already does, gated
# on MAGIC_EXT_USE_GDS=1).
# ---------------------------------------------------------------------------
PDK_STDCELL_PG_HINT: Dict[str, str] = {
    "sky130A": "sky130_fd_sc_*",
    "gf180mcuC": "gf180mcu_fd_sc_mcu*",
    "gf180mcuD": "gf180mcu_fd_sc_mcu*",
}


@dataclass
class LvsSetupOptions:
    """Knobs that change what's emitted, all deterministic.

    `extra_power_nets`: project-specific power names (e.g. an analog block's
                       private VBN_REF) added on top of the PDK defaults.
    `flatten_top_circuits`: pair of top circuit names to `flatten class`
                           BEFORE the lvs comparison. Use when layout
                           is hierarchy-flat (yosys+flatten) but schematic
                           is hierarchy-preserved (Magic ext2spice).
                           Empty list = no flatten directives emitted.
    `equate_stdcell_lib_to_short_name`: True (default) trusts the foundry
                           setup's wildcard `<lib>__<cell>` → `<cell>`
                           equate (no-op emit, just a comment). False
                           emits an explicit equate (rarely needed).
    `audit_comments`: include `puts stdout` lines that announce each
                     supplementary rule is being applied — invaluable
                     during a debug session, off by default for a clean
                     production batch run.
    """
    extra_power_nets: List[str] = field(default_factory=list)
    flatten_top_circuits: Tuple[str, str] = ("", "")
    equate_stdcell_lib_to_short_name: bool = True
    audit_comments: bool = False


def _normalize_pdk(pdk: str) -> str:
    """Return a canonical PDK key present in PDK_POWER_NETS.

    Accepts the loose names a user might type: "sky130", "sky130a", "SkyWater",
    "gf180", "gf180mcu". Unknown PDKs return "" — the caller emits a SKIPPED
    diagnostic.

    An EXACT (case-insensitive) match against the table is tried FIRST, so a
    PDK whose canonical registry name is already a table key resolves without
    needing a bespoke heuristic branch. Before this, the function only
    understood sky130* and gf180*, so every other PDK — including
    registry-declared, fully-supported ones — fell through to "" and the
    emitter wrote LVS_SETUP_SKIPPED with NO power-net globalisation. Measured
    on spm x ihp-sg13g2 (2026-07-21): netgen then reported "Final result:
    Netlists do not match" purely because of the un-globalised substrate
    node, on a layout whose DRC was already 0.
    """
    s = (pdk or "").strip().lower()
    if not s:
        return ""
    for key in PDK_POWER_NETS:
        if key.lower() == s:
            return key
    if s.startswith("sky130") or "skywater" in s:
        return "sky130A"
    if s.startswith("gf180"):
        if "d" in s:
            return "gf180mcuD"
        return "gf180mcuC"
    # Accept the common short/alias spellings of the IHP open PDK.
    if s.startswith("ihp") or s.startswith("sg13g2"):
        return "ihp-sg13g2"
    return ""


def build_supplementary_setup_tcl(
    pdk: str,
    options: Optional[LvsSetupOptions] = None,
    cell_lef: Optional[Path] = None,
) -> str:
    """Generate the supplementary Netgen LVS setup TCL fragment.

    Returns a multi-line string ready to be written next to (or after)
    the foundry `<pdk>_setup.tcl`. When `pdk` is unrecognised, returns
    a minimal SKIPPED-style fragment with a clear `puts stdout` so the
    audit trail records that no PDK-specific globalisation was applied.
    """
    opts = options or LvsSetupOptions()
    pdk_key = _normalize_pdk(pdk)

    out: List[str] = []
    out.append(
        "#---------------------------------------------------------------\n"
        f"# Vibe-IC plugin v{_pmd.running_plugin_version()} — supplementary "
        "Netgen LVS setup\n"
        "# Closes the open-source SkyWater-style net-level gap by\n"
        "# globalising power nets and (optionally) flattening top\n"
        "# circuits to match the layout vs schematic hierarchy.\n"
        "# Generated by programs/lvs_netgen_setup_emit.py\n"
        "# Reference: spm pilot RESULT_tier4_5_lvs_attempts.md\n"
        "#---------------------------------------------------------------"
    )

    # A project-staged (i.e. every commercial) PDK resolves to the synthetic
    # name `custom:pdk`, which is in no table, so this emitter used to write
    # LVS_SETUP_SKIPPED and globalise NOTHING — leaving netgen to see one flat
    # power net per cell instance and diverge from the schematic on every std
    # cell. The PDK declares its own rails: harvest the `USE POWER|GROUND` pin
    # names from its std-cell LEF instead of skipping. Consulted ONLY when the
    # name is unknown, so every named-PDK lane is byte-for-byte unchanged.
    _lef_nets: List[str] = []
    if not pdk_key and cell_lef:
        try:
            from lvs_power_aware_netlist_emit import model_from_cell_lef as _m
        except Exception:  # pragma: no cover - import shape varies by caller
            _m = None  # type: ignore[assignment]
        if _m is not None:
            _model = _m(cell_lef)
            if _model is not None:
                _lef_nets = list(_model.pg_pins)

    if not pdk_key and not _lef_nets:
        out.append(
            f"puts stdout \"LVS_SETUP_SKIPPED: unknown PDK '{pdk}'; "
            "no power-net globalisation applied. Net-level LVS may "
            "report spurious unconnected-power mismatches.\""
        )
        return "\n".join(out) + "\n"

    # --- Rule 1 — global power-net declarations -------------------------
    power_nets = (list(PDK_POWER_NETS.get(pdk_key, [])) + _lef_nets
                  + list(opts.extra_power_nets))
    # Deduplicate while preserving order (Python 3.7+ dict).
    power_nets = list(dict.fromkeys(power_nets))

    out.append("")
    out.append(
        "# Rule 1 — globalise power/ground nets. Magic ext2spice does NOT\n"
        "# mark these as .global, so Netgen otherwise sees a per-instance\n"
        "# flat net per VPWR/VGND/etc., which falsely diverges from a\n"
        "# Yosys structural netlist that shares one wire across cells."
    )
    for net in power_nets:
        out.append(f"global {net}")
    if opts.audit_comments:
        out.append(
            f"puts stdout \"LVS_SETUP_APPLIED: {len(power_nets)} "
            f"global power-net(s) for {pdk_key}\""
        )

    # --- Rule 2 — stdcell lib<->shortname equate (foundry-provided) ------
    out.append("")
    if opts.equate_stdcell_lib_to_short_name:
        sc_hint = PDK_STDCELL_PG_HINT.get(pdk_key, "<stdcell lib>")
        out.append(
            f"# Rule 2 — stdcell library-name equivalence is ALREADY emitted\n"
            f"# by the foundry {pdk_key}_setup.tcl wildcard loop matching\n"
            f"# `{sc_hint}`. No duplicate emit (would cause Netgen\n"
            f"# re-declaration warnings on the cross-name mapping)."
        )
    else:
        out.append(
            "# Rule 2 — explicit stdcell library-name equivalence suppressed\n"
            "# by option; trust the foundry setup's wildcard loop."
        )

    # --- Rule 3 — symmetric-MOS permute (foundry-provided) ---------------
    out.append("")
    out.append(
        "# Rule 3 — symmetric-MOS source-drain permutation plus the\n"
        "# foundry-wide default-symmetric directive are already in the\n"
        "# foundry setup. No supplementary emit needed."
    )

    # --- Rule 4 — optional flatten directives ----------------------------
    out.append("")
    fa, fb = opts.flatten_top_circuits
    if fa and fb:
        out.append(
            "# Rule 4 — flatten the top circuits BEFORE comparison. Use\n"
            "# when layout (Magic ext2spice) preserves stdcell subckt\n"
            "# hierarchy but schematic (yosys+flatten) is fully flat.\n"
            "# Flatten BOTH sides so device-level compare runs at the\n"
            "# same granularity on each."
        )
        out.append(f"flatten class \"-circuit1 {fa}\"")
        out.append(f"flatten class \"-circuit2 {fb}\"")
        if opts.audit_comments:
            out.append(
                f"puts stdout \"LVS_SETUP_APPLIED: flatten {fa}/{fb}\""
            )
    else:
        out.append("# Rule 4 — flatten directives NOT emitted (opt-in).")

    # --- Rule 5 — tap/fill ignore (audit-only comment) -------------------
    out.append("")
    out.append(
        "# Rule 5 — tap/fill/decap `ignore class` is conditionally emitted\n"
        "# by the foundry setup when MAGIC_EXT_USE_GDS=1. Set the env var\n"
        "# (or `--magic-ext-use-gds`) before invoking netgen if your\n"
        "# extracted layout contains tap cells the schematic does not."
    )

    return "\n".join(out) + "\n"


def _cli() -> int:
    """Command-line entrypoint — emit the TCL fragment to stdout or a file."""
    p = argparse.ArgumentParser(
        description="Emit Netgen LVS supplementary setup TCL (deterministic).",
    )
    p.add_argument("--pdk", required=True,
                   help="PDK name: sky130A | gf180mcuC | gf180mcuD")
    p.add_argument("--extra-power-net", action="append", default=[],
                   help="Additional power-net name to globalise (repeatable)")
    p.add_argument("--flatten-top-a", default="",
                   help="Top circuit name in circuit1 (layout) to flatten")
    p.add_argument("--flatten-top-b", default="",
                   help="Top circuit name in circuit2 (schematic) to flatten")
    p.add_argument("--no-equate-stdcell", action="store_true",
                   help="Suppress audit comment about stdcell lib→short equate")
    p.add_argument("--audit-comments", action="store_true",
                   help="Include puts stdout audit lines")
    p.add_argument("--out", type=Path, default=None,
                   help="Output path. Defaults to stdout.")
    args = p.parse_args()

    options = LvsSetupOptions(
        extra_power_nets=args.extra_power_net,
        flatten_top_circuits=(args.flatten_top_a, args.flatten_top_b),
        equate_stdcell_lib_to_short_name=not args.no_equate_stdcell,
        audit_comments=args.audit_comments,
    )
    text = build_supplementary_setup_tcl(args.pdk, options)

    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote: {args.out}", file=__import__("sys").stderr)
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
