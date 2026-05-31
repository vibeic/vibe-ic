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

**Mandatory sign-off guard (v0.2.1):** before trusting ANY LVS "match", run
`programs/lvs_signoff_guard.py --spice <extracted.spice> [--top <name>]` (or call
`lvs_signoff_guard.assert_lvs_trustworthy(...)`). It RAISES on a PORTLESS extracted top
`.subckt` — the vacuous-match condition that lets a naive wrapper report a SILENT
FALSE-POSITIVE. A match is only trustworthy when the layout top has ports to anchor against;
if the guard trips, fix the extraction (Route A `port makeall` via `magic_port_extract_emit.py`,
or DEF-seed via `lvs_def_port_seed.py`) and re-run — never sign off on a portless match.

## Top-level pin matching needs PORTS on the layout `.subckt` — two routes (captured v0.1.114)

After device-level netgen reaches device-count-exact + classes-equivalent (e.g. HDLC
16393=16393, 0 disconnected nodes), the last residual is often
`Final result: Top level cell failed pin matching` — because the Magic GDS flat extraction emits
a **portless** `.subckt <top>` (empty port list), so netgen's name-matching partition has nothing
to anchor (flat layout nets ≠ schematic nets, disjoint naming). Two general programs close this:

- **Route A — canonical cause-fix (PREFER): `programs/magic_port_extract_emit.py`.** Emits the
  Magic `port makeall` extraction TCL + the shell preamble. Two prerequisites, both proven on HDLC:
  (1) `export PDK=<pdk>` and `PDK_ROOT` in the SHELL **before** magic launches (the system
  `.magicrc` reads `$env(PDK)` at startup — an in-script `set env(PDK)` is too late; the
  `eda_run_tcl engine=magic` wrapper currently does NOT export it → see
  ORGANIC-20260531-magic-extraction-no-toplevel-ports; drive via `docker exec iic-eda` with the
  export preamble). (2) `port makeall` only promotes labels on the PDK **port-purpose** layer
  (sky130 `MET3PIN` = GDS 70/16); an OpenROAD GDS-streamout step that put pin text on a drawing
  layer (sky130 10/1) yields nothing — relabel 10/1→70/16 (klayout) first. Result on HDLC: a real
  port-labeled flat `.subckt hdlc_core_flat clk fcs_ok …` with 20937 devices, and the netgen
  verdict advances past the pin-match-seed stage. (To reach "Circuits match uniquely" the moved
  label must also be geometrically snapped to the met3 routing shape so it ties to the net.)

- **Route B — tool-independent fallback: `programs/lvs_def_port_seed.py`.** Parses ANY DEF `PINS`
  section → ordered `(pin, net, direction)`, and emits both a netgen port-seed TCL and an ordered
  port list to inject into the portless `.subckt <top>` line. Runs NOW, no Magic dependency.
  **Honest limit (proven on HDLC):** name-seeding ALONE does NOT converge a flat extraction whose
  internal nets carry Magic auto-names (`a_NNNN#`) — the injected ports become *disconnected pins*
  (HDLC: 47 disconnected pins). Route B is a partition HINT / audit artifact; when the layout body
  has no matching net names, **Route A (real label promotion tied to geometry) is genuinely
  required** — say so rather than reporting a false PASS.

Both are deterministic + pytest-pinned (`programs/tests/test_magic_port_extract_emit.py`,
`programs/tests/test_lvs_def_port_seed.py`).

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
