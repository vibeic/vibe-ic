---
name: lvs-triage
description: Triage Layout-vs-Schematic (LVS) mismatches — missing connections, short/open nets, device parameter mismatches, unmatched instances. Use when the user says "LVS", "layout vs schematic", "LVS mismatch", "netlist compare", "Calibre LVS", "Netgen".
---

# LVS Triage

LVS proves that the drawn layout corresponds to the schematic / netlist. Mismatches are common in early iterations. This skill reads LVS reports (Calibre, Netgen, Pegasus) and proposes focused fixes.

## When to use

- After routing / layout finalization
- After any manual layout edit
- Before tapeout sign-off
- When integrating analog macros into a digital floorplan

## Inputs

1. LVS report file (Calibre `.rep`, Netgen `comp.out`, etc.)
2. Schematic netlist (`.cdl` / `.sp` / `.v`)
3. Extracted layout netlist
4. Device model list (PDK-specific)

## Workflow

1. **Parse report** into categories:
   - Unmatched instances
   - Unmatched nets (shorts, opens)
   - Device parameter mismatches (W/L, M, NF)
   - Property mismatches (labels, dummies)
2. **Top-3 root-cause check**:
   - Missing label on a net (most common)
   - Missing via between metal layers
   - Wrong device variant picked from PDK
3. **For each mismatch** propose the exact layer + coordinate to edit
4. **Batch waivers**: some analog dummies intentionally don't appear in schematic — document waiver
5. **Re-run plan**: minimal LVS subset to re-verify

## Output format

- `lvs/lvs_triage.md`:
  - Mismatch summary (count by category)
  - Top 20 mismatches with fix
  - Waiver list with justification
  - Re-run script

## Technical basis

LVS methodology references: Mentor Calibre user guide, open-source Netgen (http://opencircuitdesign.com/netgen/). Signoff tools: Calibre LVS, Cadence Pegasus, Synopsys IC Validator.

## Structural-LEC "unproven cells" are a substitute-tool gap — cover with device-level LVS (captured v0.1.98)

`eda_lvs mode=yosys_equiv` is *structural* LEC (yosys `equiv_simple`+`equiv_induct`): it proves
Boolean equivalence with a SAT engine. That engine lacks a model for some standard-cell
primitives, so those cells come back **"unproven" / `sat_model_unsupported_cells`** — this is a
LIMITATION OF THE SUBSTITUTE TOOL, **not** a netlist mismatch, and **no yosys flag closes it for
all cells** (`-undef`, deeper `equiv_induct -seq N`, `dfflibmap`/`async2sync` only widen it).

**To actually cover the unproven cells, switch to device-level LVS** (the sky130/gf180 sign-off
path — netgen has no SAT-model concept, it matches transistors):
1. `eda_extraction` (magic ext2spice, pdk=sky130, output_format=spice) — GDS → flat layout SPICE.
2. `lvs_netgen_setup_emit.py` — emit the netgen `setup_supplement` TCL that globalizes power nets
   (`global vccd1 vssd1 VPWR VGND`); Magic's ext2spice does NOT mark power as `.global`.
3. netgen `lvs <layout.spice> <schematic>` with the foundry setup + the supplement, AND the
   **std-cell SPICE library loaded into the SCHEMATIC circuit** so each gate expands to
   transistors (else the schematic cells are empty placeholders → a false device-granularity
   mismatch). This reaches device-class-exact (e.g. HDLC: 20937 = 20937 devices, all 4 classes
   equivalent — the 230 yosys-unproven cells became 0 device-level-unproven; cf. benchmark_clean
   sha256 device-exact 12148 = 12148).

**Expected honest residual when the schematic side is a logic-only Verilog netlist:** the tie
cells (sky130 `conb_1` = two poly resistors to VPWR/VGND) show their power-side terminals as
disconnected, because a post-PnR Verilog gate netlist has NO power connectivity (`grep VPWR` = 0).
This is a **Category-D Verilog-vs-extracted power-modeling artifact** (sha256 documented the same),
NOT a real mismatch — every logic net + all devices match. Closing it fully needs a power-aware
SPICE schematic side. Caveat: `eda_lvs mode=netgen`'s `matched` flag is currently an unreliable
regex (see ORGANIC-20260531-eda-lvs-netgen-false-positive-and-no-stdcell-lib) — verify against the
real netgen verdict lines ("Circuits match"/"failed pin matching"/device-class equivalence), not
the boolean.

## Handoff

- Re-run DRC after LVS fix → `/drc-fix`
- Layout edits → documented in `/eco-plan` log
- Schematic change → back to `/rtl-repair` or `/analog-layout`

## Compliance gate (vibe-ic-d - mandatory when deterministic edition is installed)

If you have the `vibe-ic-d` plugin installed alongside `vibe-ic`,
after producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic-d/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic-d/skills/lvs-triage/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding vibe-ic-d skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.
