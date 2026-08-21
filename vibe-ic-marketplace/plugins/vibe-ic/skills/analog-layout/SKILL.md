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

**SCOPE — this recipe is for the devices that do NOT have to match.** Read it against the
Workflow above, not instead of it. §1 (one `nf=1` device per schematic MOS) and §2 (each device's
columns inside its own slot) make a common-centroid quad and an interdigitated mirror
*unconstructible*: both of those patterns exist precisely to INTERLEAVE the devices this recipe
keeps apart. The two are not in competition — they apply to different devices:

| the devices whose mismatch drives a spec | every other device in the block |
|---|---|
| Workflow §1-§5 above: common-centroid 2×2 / 4×4, ABAB / ABBA interdigitation, ≥2 dummies per side, guard ring, symmetric routing | §1-§2 below: one `nf=1` device per MOS, one slot each, generated two-layer routing |
| A6 LVS will NOT match with dummies in the layout — the dummy is a device the schematic does not contain. Take the waiver route (`/lvs-triage` **Batch waivers**: "some analog dummies intentionally don't appear in schematic — document waiver") and record the waiver id in `lvs_dummy_waiver`. | A6 LVS matches outright, which is what §1-§2 are optimised for |

**State which one you took, in a field.** A6's LVS compare is topology-only: it does not see a
centroid, does not see finger order, and dummies make it *harder*. So a block laid out as N
isolated devices closes A6 exactly as green as a fully matched one, and nothing in the tree tells
a reader which happened. Emit `analog/<block>/layout_matching.json` (schema under
**Output format** below). `"matching_style": "none"` is a legitimate, certifying answer — a level
shifter, a power switch and an ESD clamp have no matching group to build. What is not legitimate
is answering nothing: `analog_a5_layout_check` and `analog_a6_block_pv_check` both report the
class (`declared_matched` / `declared_none` / `undisclosed`) in their `--json` summary and on a
`MATCHING:` line, and A5 holds a disclosure that EXISTS to its own content
(`A5_MATCHING_GROUP_DUMMIES_INSUFFICIENT` is the ≥2-dummies rule above, executed;
`A5_MATCHING_DUMMIES_LVS_UNRECONCILED` is the waiver route, executed).

### 0. First check the netlist is layout-realizable at all

**An A3 netlist containing an ideal `V`/`I` source, or an ideal `R`/`C`/`L`, inside the block
subcircuit can never pass A6, no matter how well it is drawn.** The netgen PDK setup declares
device classes for the PDK's own `res_*` / `cap_*` subcircuits; it declares nothing that equates
an ideal SPICE primitive to a drawn device, so the compare cannot match. Measured: a block whose
netlist carried `Vbias nbias VSS 0.8`, `R1 VOUT FB 100k`, `Cc nd2 VOUT 3p` passed A3, A4 and A5
and made A6 unreachable **by construction** for three rounds.

**This is a gate, not a review item.** `analog_a3_netlist_gen_check` fails it as
`A3_NETLIST_IDEAL_PRIMITIVE_IN_BLOCK` — at A3, where the deck is written, not at A6 three steps
later where it reads as a layout defect. It is SPICE card grammar: `V`/`I` and the controlled and
behavioural sources `E`/`F`/`G`/`H`/`B` fire on the card letter alone; `R`/`C`/`L` fire only when
the value field holds a number or an expression, so `R1 a b <pdk_res_model> w= l=` and
`XR1 a b <pdk_device> W= L=` are both left alone. Cards at file scope and anything inside a
testbench subcircuit are out of scope — the testbench is where the fixes below SEND these
elements. The runner's own disclosed `deterministic_stub` deck is exempt.

Fix it upstream before drawing anything:

- ideal bias source → hoist to a **block port** the testbench drives (electrically identical);
- ideal R → the PDK poly/diff resistor with W/L solved for the same value;
- ideal C → the PDK MIM/VPP cap (arrayed if one instance is capped by the gencell's `lmax/wmax`);
- an ideal **load** element that the topology doc draws outside the block → move it to the
  testbench, do not delete it.

Then **re-run A4** on the revised deck and quote the new corner numbers. A netlist change that
was never re-simulated is not a fix — and that is a gate too: a `corner_results.json` that
publishes `netlist_sha256` / `netlist_testbench_sha256` (as `analog_real_corner_sweep` does)
fails `analog_a4_corner_sweep_check` with `A4_SWEEP_STALE_VS_NETLIST` the moment either digest
stops recomputing from the file on disk. Every other subject-of-measurement rule at A4 is
answered once, when the artefact is written; this one is re-answered on every gate run.

### 1. One `nf=1` device per schematic MOS, with W = W_schematic x M

*(non-matched devices only — see SCOPE above. A matched group is interdigitated, and its finger
count is set by the pattern, not by this rule.)*

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
W x M (12 x W=60 for `W=6 m=120`). Disclose the partition in
`layout_matching.json`'s `device_partitions[]`, not only in prose: it is LVS-equivalent and it is
a real connected structure, but its parasitics are not those of an interdigitated device.
`analog_a5_layout_check` does the arithmetic — `A5_DEVICE_PARTITION_WIDTH_MISMATCH` when the
declared layout widths do not sum to `w_um x m`, because netgen merges parallel devices by
ADDING their widths and so sees the sum, not the intent. A declared layout device with `nf > 1`
is **recorded** (`multifinger_layout_devices`) and not failed: whether a multi-finger gencell
extracts with per-finger pins is a property of one PDK's device generator, which is what the
one-command check above is for.

### 2. A routing discipline that is DRC-clean by construction

*(non-matched devices only — see SCOPE above. "Each device's columns inside its own slot" is the
opposite of interdigitation, and a matched row routes symmetrically instead.)*

Do not hand-route. Use a two-layer discipline with a strict axis rule, so no two same-layer
shapes of different nets ever share a coordinate band:

- **met2 vertical only** — one unique column per device terminal, at the terminal's own x;
- **met3 horizontal only** — one unique rail per net, above every device;
- via1 at the terminal, via2 at the (column, rail) crossing;
- devices spaced far enough apart that each device's columns stay inside its own slot.

This is generated from the netlist, not drawn, and it makes column/rail collisions a
precondition check rather than a DRC round-trip.

### 3. The five PDK-specific facts that cost the most iterations

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
  If every delta is exactly zero, the numbers were copied — and both gates over
  `pre_vs_post.json` now refuse it: a comparison whose every compared spec's post value equals
  its pre value certifies only if it NAMES the post-layout artefact its post column was
  simulated from **and that artefact resolves on disk**
  (`A7_POSTSIM_ALL_ZERO_DELTA_UNEVIDENCED` in `analog_a7_post_layout_resim_check`,
  `PRE_VS_POST_ALL_ZERO_DELTA_UNEVIDENCED` in `analog_pre_vs_post_layout_check`). Name the
  extraction; a `0.0` column with nothing behind it is the one input that used to score better
  than every honest comparison.
- **A8** — `gds write` + `lef write` from the routed cell. Two traps: magic's `lef write` frame
  is the **magic cell bbox**, which can include magic-only layers (sky130 `pwell`) that stream no
  GDS, so the LEF and GDS land in different frames — set an explicit `FIXED_BBOX` equal to the
  GDS extent first. And magic's `lef write` emits **no `USE POWER` / `USE GROUND`**: re-attach
  `DIRECTION` and `USE` to every pin. This one is also gated now — an abstract that types NO pin
  at all is no longer read as an abstract with nothing to declare, and
  `l21_macro_supply_rail_declared_check` recovers the typing from the macro's own Liberty
  `pg_pin`/`pg_type` and from `L21.power_domains[]` before reporting the real rail finding, or
  says the contract is UNVERIFIABLE (rule **L21-5**, waiver key
  `l21_macro_lef_pin_use_absent_disclosed`). An untyped abstract used to SKIP with a message
  byte-identical to a design that has no macro at all.

**Still unowned here, named rather than dropped.** Two of §4's claims are not yet programs, and
neither is silently assumed:

- **A7/A8 staleness against the routed layout.** The rules above catch a COPIED post column and
  an UNTYPED abstract; neither catches evidence that was honestly measured against a
  *superseded* layout. A4 has the equivalent rule (`A4_SWEEP_STALE_VS_NETLIST`) only because its
  producer stamps a digest of its input; no A7 or A8 producer records the layout digest it was
  built from, so the check has nothing to recompute against. It needs the producer change first
  — do not substitute mtime, which a fresh checkout rewrites.
- **The `netgen -batch lvs` parallel-merge self-test in §1.** It is a real probe and it belongs
  in a program, but it needs netgen and a PDK setup TCL inside the EDA container. A program that
  cannot run its tool would either SKIP always — certifying nothing while looking like a gate —
  or assert the answer it was meant to measure. Run the command by hand until it is wired to a
  container-backed tool call.


## Output format

- `layout/<block>_layout_plan.md`:
  - Device placement diagram (ASCII or SVG)
  - Matching pattern per group
  - Routing rules
  - Dummy / guard-ring list
  - Known risks

- `analog/<block>/layout_matching.json` — the same three facts as a FIELD, because A6's LVS
  compare is topology-only and cannot tell a matched layout from an unmatched one. Read by
  `analog_a5_layout_check` (rules) and `analog_a6_block_pv_check` (record). Every rule fires only
  on a file that exists, so writing one costs nothing except having to mean it:

  ```json
  {
    "block": "<block>",
    "matching_style": "common_centroid" | "interdigitated" | "none",
    "matched_groups": [
      {"name": "input_pair", "devices": ["Mn1", "Mn2"],
       "style": "common_centroid", "dummies_per_side": 2}
    ],
    "lvs_dummy_waiver": "<ticket>",
    "device_partitions": [
      {"schematic_device": "Mpass", "w_um": 6.0, "m": 120,
       "layout_devices": [{"w_um": 60.0, "nf": 1}]}
    ],
    "note": "free text"
  }
  ```

  | field | rule |
  |---|---|
  | `matching_style` absent / empty | `A5_MATCHING_DISCLOSURE_MALFORMED` |
  | `"none"` with groups listed, or a style with no group | `A5_MATCHING_STYLE_GROUPS_CONTRADICT` |
  | a matched group with `dummies_per_side` < 2, or none declared | `A5_MATCHING_GROUP_DUMMIES_INSUFFICIENT` |
  | dummies declared, no `lvs_dummy_waiver` | `A5_MATCHING_DUMMIES_LVS_UNRECONCILED` |
  | `layout_devices[].w_um` does not sum to `w_um x m` | `A5_DEVICE_PARTITION_WIDTH_MISMATCH` |
  | omitted entirely | no rule — `undisclosed`, reported in both gates' summary and on the `MATCHING:` line |

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
