---
name: analog-layout
description: Plan analog layout with matching, common-centroid, interdigitation, dummy devices, guard rings, and shielding. Use when the user says "analog layout", "matching layout", "common centroid", "dummies", "guard ring", "interdigitated", "current mirror layout", "differential pair layout".
---

# Analog Layout

`analog-sizing` picks W/L; this skill translates the sized schematic into a layout plan that actually survives process variation. Matching and noise immunity live or die on layout, not schematic.

## When to use

- Current mirrors, differential pairs, bandgap references, DAC ladders
- Any circuit where σ(Vth) or σ(β) matching drives the spec
- Circuits near digital noise sources (guard rings / shielding needed)
- Before handing off to a layout engineer or Magic / Virtuoso

## Inputs

1. Sized schematic with device list (W, L, M, NF)
2. Matching pairs / groups (which devices must match)
3. Sensitivity list (which mismatches kill which spec)
4. PDK rules (well spacing, latch-up, antenna)
5. Floorplan block size budget

## Workflow

1. **Identify matching groups** — pairs, quads, ratios
2. **Choose matching style**:
   - Common-centroid 2×2, 4×4 for differential pairs
   - Interdigitation ABAB or ABBA for current mirrors
   - Centroid-preserving patterns for large ratios
3. **Dummy devices**: at least 2 dummies on each side of a matching row
4. **Guard rings**: n-well ring around PMOS, p-substrate ring around NMOS near digital
5. **Routing rules**:
   - Symmetric routing for differential signals
   - Shielded routing for sensitive nodes (clock, bandgap output)
   - Avoid crossing a matched row with unrelated metal
6. **Density / antenna**: ensure fill rules and antenna rules met without breaking symmetry
7. **Post-layout extraction**: plan for RC back-annotation → re-simulate → may need sizing iteration

## Drawing a layout that actually closes A6 (measured recipe)

Everything above produces a *plan*. A6 (`analog_a6_block_pv_check`) does not grade plans: it
demands **DRC == 0 AND a netgen LVS match, per block**. `eda_analog_layout` cannot supply that —
it is honest that it returns `status: SCAFFOLD` because `readspice` + `gds write` places nothing.
So the layout is authored here, and three separate things have to be true. Each line below was
measured on sky130A (magic 8.3.679, device generator 1.0.599); the shape of the rule is
PDK-independent, the numbers are not.

### 0. First check the netlist is layout-realizable at all

**An A3 netlist containing an ideal `V`/`I` source, or an ideal `R`/`C`/`L`, inside the block
subcircuit can never pass A6, no matter how well it is drawn.** The netgen PDK setup declares
device classes for the PDK's own `res_*` / `cap_*` subcircuits; it declares nothing that equates
an ideal SPICE primitive to a drawn device, so the compare cannot match. Measured: a block whose
netlist carried `Vbias nbias VSS 0.8`, `R1 VOUT FB 100k`, `Cc nd2 VOUT 3p` passed A3, A4 and A5
and made A6 unreachable **by construction** for three rounds.

Fix it upstream before drawing anything:

- ideal bias source → hoist to a **block port** the testbench drives (electrically identical);
- ideal R → the PDK poly/diff resistor with W/L solved for the same value;
- ideal C → the PDK MIM/VPP cap (arrayed if one instance is capped by the gencell's `lmax/wmax`);
- an ideal **load** element that the topology doc draws outside the block → move it to the
  testbench, do not delete it.

Then **re-run A4** on the revised deck and quote the new corner numbers. A netlist change that
was never re-simulated is not a fix.

### 1. One `nf=1` device per schematic MOS, with W = W_schematic x M

A multi-finger gencell exposes **per-finger pins** (`D0_0`, `G0_0`, `S1`…), and every one of them
extracts as a separate unconnected node — the single most common cause of
`Final result: Top level cell failed pin matching.` Setting `conn_gates 1` merges the *gates*
only and leaves the source/drain comb unstrapped, so it does not rescue the compare.

An `nf=1` gencell exposes exactly four clean ports: `B D S G`. And netgen expands `m=` into
parallel devices and merges them with `parallel {w add} {l critical}`, so a single wide finger is
LVS-equivalent to the schematic's multiplier. Verify that on your PDK in one command before
committing to it:

```
netgen -batch lvs "a.sp t" "b.sp t" <pdk>_setup.tcl out.log
#   a.sp:  X1 d g s b <nfet> W=4  L=1 m=4
#   b.sp:  X1 d g s b <nfet> W=16 L=1
#   -> Final result: Circuits match uniquely.
```

For a very wide device, partition it into N parallel `nf=1` devices whose widths **sum** to
W x M (12 x W=60 for `W=6 m=120`). Disclose the partition in the RESULT: it is LVS-equivalent
and it is a real connected structure, but its parasitics are not those of an interdigitated
device.

### 2. A routing discipline that is DRC-clean by construction

Do not hand-route. Use a two-layer discipline with a strict axis rule, so no two same-layer
shapes of different nets ever share a coordinate band:

- **met2 vertical only** — one unique column per device terminal, at the terminal's own x;
- **met3 horizontal only** — one unique rail per net, above every device;
- via1 at the terminal, via2 at the (column, rail) crossing;
- devices spaced far enough apart that each device's columns stay inside its own slot.

This is generated from the netlist, not drawn, and it makes column/rail collisions a
precondition check rather than a DRC round-trip.

### 3. The four PDK-specific facts that cost the most iterations

| symptom | cause | fix |
|---|---|---|
| `Via1 width < 52` / `via2 width < 56` / `via3 width < 0.32um` | magic's contact *type* carries the metal enclosure, so the **drawn** via must exceed cut + 2 x enclosure — not the cut size | draw via1/via2 >= 0.30 um, via3 >= 0.35 um |
| `Metal1 minimum area < 0.083um^2` on a short-L device | the gencell's gate met1 strap is tiny at minimum L, at **both** top and bottom | enlarge **both** gate straps, not just the one carrying the port label |
| gate contact too close to the source/drain straps | the S/D met1 straps run the full device height and end just below the gate strap | raise the gate pad **upward only**; keep `drc euclidean on` so the diagonal clearance counts |
| `MiM cap spacing to unrelated metal3 < 1.34um` | the cap's top plate lives on met4 over its own met3 bottom plate | escape the top plate on **met4 past the bottom plate's edge**, then drop met4 -> met3 -> met2 |
| `Width of RPM/URPM < 1.27um` on a bare resistor cell | the narrowest poly-resistor gencell variant is DRC-dirty **by itself** | use the next wider variant and re-solve L for the same resistance |

Also: the substrate/well **guard ring is the bulk terminal**. Hang a short local-interconnect
stub off the ring's own bar, put the li->met1 cut in the stub, and give it its own column — do
not try to contact the ring under the device's met1 straps.

### 4. Prove it, then prove what it licensed

```
magic: drc euclidean on; drc style drc(full); drc check; drc catchup; drc list count total
magic: extract do local; extract all; ext2spice lvs; ext2spice -o <top>_layout.spice
netgen -batch lvs "<top>_layout.spice <top>" "<block>_lvs_schematic.spice <top>" <pdk>_setup.tcl
```

Copy netgen's own transcript verbatim into `lvs.report` and magic's own count into `drc.report`.

Then remember what A6 was **holding back**. A7 and A8 are `PASS-VOIDED` while A6 fails; the
moment A6 goes green they become live PASSes on whatever evidence happens to be sitting there.
Measured: a `pre_vs_post.json` whose every `delta_pct` was `0.0` because the post values had been
copied from the pre values, and a hardmacro LEF/GDS streamed from the superseded unrouted layout.
Rebuild both from the routed layout:

- **A7** — `extract all` + `ext2spice cthresh 0` + `rthresh infinite` gives a real post-layout
  netlist; simulate it with the **same** stimulus and the **same** `.meas` statements as A4.
  If every delta is exactly zero, the numbers were copied.
- **A8** — `gds write` + `lef write` from the routed cell. Two traps: magic's `lef write` frame
  is the **magic cell bbox**, which can include magic-only layers (sky130 `pwell`) that stream no
  GDS, so the LEF and GDS land in different frames — set an explicit `FIXED_BBOX` equal to the
  GDS extent first. And magic's `lef write` emits **no `USE POWER` / `USE GROUND`**, which
  silently turns the supply-rail gates from FAIL into SKIP; re-attach `DIRECTION` and `USE` to
  every pin or you have disarmed a gate rather than passed it.


## Output format

- `layout/<block>_layout_plan.md`:
  - Device placement diagram (ASCII or SVG)
  - Matching pattern per group
  - Routing rules
  - Dummy / guard-ring list
  - Known risks

## Technical basis

Classic references: Razavi "Design of Analog CMOS Integrated Circuits" ch. on layout, Hastings "The Art of Analog Layout", Pelgrom matching model. Process-specific matching coefficients come from the PDK.

## Handoff

- Sized devices → input to this skill came from `/analog-sizing`
- LVS verification → `/lvs-triage`
- DRC verification → `/drc-fix`
- Post-layout resim → `/ams-sim`

## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/analog-layout/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.
