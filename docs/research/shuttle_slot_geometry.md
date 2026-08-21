# Die size, and the slot it must fit — the wall behind the seal ring

Research note. No program, no gate. Follow-on from
`docs/research/wafer_space_id_cells.md` (`5acf73d1a`).

**Headline: agent `jseal`'s acceptance criterion — "the refusal must move past
stage 3" — is reachable, but it buys one stage, not a pass.** Adding a seal ring
moves the refusal from `check_size.py:70` to `check_size.py:107`, and the corpus
misses the *smallest* slot by between 5.5x and 51x in each linear dimension. That
is a floorplan fact, not a seal-ring fact, and it must not be read as a failure of
`jseal`'s work.

**The die size is not something a submitter computes. It is a constant the
operator's template hands them, per slot.** All four slot files pin `DIE_AREA`
verbatim, and the four values are exactly the four `check_size.py` computes. So
this is the same finding as the id cells: the missing thing is **template
ingestion**, not a missing calculation.

---

## 1. The arithmetic, confirmed against the source

Read from `/workspace/scripts/klayout/check_size.py` in
`ghcr.io/wafer-space/gf180mcu-precheck:latest`
(digest `sha256:f6c0cb88efce8769ec87de5a2035ada731fd8fffb1b3e5e1968078f6dd191c2f`):

```python
  8  USER_PROJECT_WIDTH = 3880
  9  USER_PROJECT_HEIGHT = 5070
 11  SEAL_RING_SIZE = 26
 13  USER_DIE_WIDTH = USER_PROJECT_WIDTH + 2 * SEAL_RING_SIZE
 14  USER_DIE_HEIGHT = USER_PROJECT_HEIGHT + 2 * SEAL_RING_SIZE
 16  SAW_STREET_MINIMUM = 60
...
100      slot_width  = (USER_DIE_WIDTH  - ((div_x - 1) * SAW_STREET_MINIMUM)) / div_x
101      slot_height = (USER_DIE_HEIGHT - ((div_y - 1) * SAW_STREET_MINIMUM)) / div_y
107      if layout_width != slot_width or layout_height != slot_height:
108          print(f"[Error]: Layout size does not match slot size {slot}.")
109          sys.exit(-1)
```

Recomputed from those constants:

| slot | div_x, div_y | width x height (um) |
|---|---|---|
| `1x1` | 1, 1 | **3932.0 x 5122.0** |
| `0p5x1` | 2, 1 | **1936.0 x 5122.0** |
| `1x0p5` | 1, 2 | **3932.0 x 2531.0** |
| `0p5x0p5` | 2, 2 | **1936.0 x 2531.0** |

The brief's arithmetic is correct in every entry. Line 107 is `!=` on floats, to
the micron, **with no tolerance**.

### The ladder is six checks, not four — and two of them sit *before* the seal ring

Worth recording, because "past stage 3" is about position in this ladder:

| order | check | line | refusal |
|---|---|---|---|
| 1 | top-cell bbox `p1 == (0,0)` | 36 | `Layout origin is not at (0, 0)` |
| 2 | `ly.dbu == 0.001` | 41 | `Database unit (dbu) is not 0.001um.` |
| 3 | `Via5` (82/0) unused | 52 | `Layer 'Via5' is used. ... 5LM metal stackup` |
| 4 | `MetalTop` (53/0) unused | 58 | `Layer 'MetalTop' is used. ... 5LM metal stackup` |
| 5 | `GUARD_RING_MK` (167/5) non-empty | 70 | `... requires a seal ring (guard ring) around the die.` |
| 6 | **size == slot, exact** | 107 | `Layout size does not match slot size {slot}.` |

Checks 3 and 4 are a 5-metal-layer stackup constraint I did not see recorded
elsewhere in our tree. They are not currently a problem for us — see the
measurement, no corpus layout uses either layer — but they are two more walls
that exist and are not represented in our flow.

---

## 2. What size are our published layouts, actually? — MEASURED

Measured with the precheck image's own KLayout 0.30.9, reading each GDS and
reporting the top cell's `dbbox()`, the dbu, and the three gated layers:

```
$ docker run --rm -v "$PWD":/w \
    --entrypoint /nix/store/dljmpck53kb6zxhvd73b688286b0kwkn-klayout-0.30.9/bin/klayout \
    ghcr.io/wafer-space/gf180mcu-precheck:latest -b -r /w/measure.py
```

**Corpus scope.** The brief's path `~/benchmark-data/ic/*/` does not exist; the
published corpus lives in the many `benchmark-data/` trees under `$HOME`
(see the note that benchmark-data left the repo). Sweeping **all 32** of them for
`*.gds` / `*.gds.gz` / `*.oas` under `ic/` yields **192 files but only 8 distinct
relative paths**, and those 8 are byte-identical across worktrees (spot-checked by
`md5sum`). Two of the 8 are themselves byte-identical to each other
(`md5 abd486c1868…`), so the corpus is **7 distinct layouts**. All 8 rows are
listed; nothing was sampled or dropped.

Design names are redacted to `<A>` / `<B>` per the NDA rule; the version string
identifies each row uniquely and the mapping is recoverable from `benchmark-data`.

| # | layout | top cell | w x h (um) | origin at (0,0)? | dbu | GUARD_RING_MK | Via5 / MetalTop | matches a slot? | **first refusal** |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `<A>/v1.10.18_*/…/stage4/gds/spm.gds` | `spm` | 176.0000 x 176.0000 | yes | 0.001 | **0** | 0 / 0 | NONE | seal ring, line 70 |
| 2 | `<A>/v1.5.58_*/…/stage4/gds/spm.gds` | `spm` | 186.0000 x 186.0000 | yes | 0.001 | **0** | 0 / 0 | NONE | seal ring, line 70 |
| 3 | `<A>/v1.5.65_*/…/stage4/gds/spm.gds` | `spm` | 93.0000 x 93.0000 | yes | 0.001 | **0** | 0 / 0 | NONE | seal ring, line 70 |
| 4 | `<A>/v1.5.66_*/…/stage4/gds/spm.gds` | `spm` | 237.0000 x 237.0000 | yes | 0.001 | **0** | 0 / 0 | NONE | seal ring, line 70 |
| 5 | `<A>/v1.9.96_*/…/stage4/gds/chip_top.gds` | `chip_top` | 240.0000 x 240.0000 | yes | 0.001 | **0** | 0 / 0 | NONE | seal ring, line 70 |
| 6 | `<B>/v1.9.86_*/…/analog/hardmacro/delta_sigma/delta_sigma.gds` | `delta_sigma` | 71.8000 x 49.4400 | **NO** — `(-4.5000, -17.0950)` | 0.001 | **0** | 0 / 0 | NONE | **origin, line 36** |
| 7 | `<B>/v1.9.86_*/…/analog/hardmacro/ldo/ldo.gds` | `ldo` | 332.5800 x 463.4150 | **NO** — `(-4.5000, -223.3050)` | 0.001 | **0** | 0 / 0 | NONE | **origin, line 36** |
| 8 | `<B>/v1.9.86_*/…/stage4/gds/ldo.gds` | `ldo` | 332.5800 x 463.4150 | **NO** — `(-4.5000, -223.3050)` | 0.001 | **0** | 0 / 0 | NONE | **origin, line 36** |

Rows 7 and 8 are the same bytes.

### Against the four slots

**No layout matches any slot. Not one, in either dimension.** The gap is not a
rounding question that a tolerance would fix — it is one to two orders of
magnitude. Measured against the **smallest** slot, `0p5x0p5` = 1936 x 2531 um
(area 4 900 016 um^2):

| # | w x h (um) | too narrow by | too short by | area too small by |
|---|---|---|---|---|
| 1 | 176.0000 x 176.0000 | 11.00x | 14.38x | 158.2x |
| 2 | 186.0000 x 186.0000 | 10.41x | 13.61x | 141.6x |
| 3 | 93.0000 x 93.0000 | 20.82x | 27.22x | 566.5x |
| 4 | 237.0000 x 237.0000 | 8.17x | 10.68x | 87.2x |
| 5 | 240.0000 x 240.0000 | 8.07x | 10.55x | 85.1x |
| 6 | 71.8000 x 49.4400 | 26.96x | 51.19x | 1380.4x |
| 7,8 | 332.5800 x 463.4150 | **5.82x** | **5.46x** | **31.8x** |

The closest any published layout comes to the smallest purchasable slot is row 7/8,
which fills **3.15 %** of its area. The largest *digital* result, row 5, fills 1.2 %.

**These are IP blocks, and they measure like IP blocks.** That is the honest
reading: nothing here was ever floor-planned to a die. It is consistent with the
flow yaml's own statement at line 2707 that the flow "HAS ALWAYS BEEN A cell/IP
FLOW AND NEVER SAID SO".

### The origin finding, reconciled with `sshut`

`sshut`'s sweep reported **one** layout refused for an origin not at (0,0). I
measure **three files** with a non-zero origin — rows 6, 7, 8 — which is **two
distinct layouts**, since 7 and 8 are the same bytes.

The discrepancy reconciles exactly if `sshut` swept only the published deliverable
directory `phase3/stage4/gds/`. Restricted to that directory the corpus is rows
1-5 plus row 8, and row 8 is then **the unique** origin refusal:

> `<B>/v1.9.86_*/phase3/stage4/gds/ldo.gds` — bbox `(-4.5000, -223.3050) - (328.0800, 240.1100)`

Rows 6 and 7 live under `phase3/analog/hardmacro/`, which is a hardmacro handoff
directory rather than a submission deliverable. So: **yes, the same file**, and the
extra two are an artefact of my wider sweep. I did not confirm `sshut`'s scope
directly — I did not read its harness — so this is a reconciliation that fits the
numbers, not a verified account of what it ran.

The `-4.5` on both is the same left-edge offset, which suggests a shared analog
cell origin convention rather than two independent mistakes.

---

## 3. Where does die size come from in OUR flow?

**It is never pinned.** Neither an input the user states nor a value derived to a
target — the flow lets the backend auto-size and then checks only that the result
is not degenerate.

**Step 15 declares no die geometry.** `flow/phase1_phase2_phase3.yaml:2644`:

```yaml
2644    - id: 15
2645      name: "Floorplan + PDN"
2646      stage: stage3
2647      required_inputs:
2648        - from: 12
2649          path: "phase2/stage2/synth/post_dft_netlist.v"
2650        - from: 7
2651          path: "phase2/stage2/constraints/*.sdc"
2652      mcp_tools: [eda_pnr]
2653      programs:
2654        - phase3_backend_step
2661        - floorplan_pdn_check
2662      required_outputs:
2663        - "phase3/stage3/pnr/floorplan.def"
```

Two inputs: a netlist and constraints. **No die area, no slot, no target
geometry, in `required_inputs` or anywhere else in the step.**

**Its checker only tests for non-degeneracy.** `programs/floorplan_pdn_check.py:15-17`:

```
  1. DIEAREA — ``floorplan.def`` must declare a non-degenerate die:
       ``DIEAREA ( x1 y1 ) ( x2 y2 ) ;`` with x2 > x1, y2 > y1 (positive
       area). A missing / zero-area DIEAREA is a structural FAIL.
```

and line 59 states the scope in its own words:

```
only bounds applied are universal structural facts (positive die area,
```

So the flow reads the die area the backend chose and asks only "is it bigger than
nothing". There is no comparison against any target, because no target exists.

**The repo already knew, and wrote it down.** `programs/floorplan_contract.py:5-10`:

```
Before this module, phase1 dropped that contract entirely — L19
carried `die_area_budget_um: null`, `floorplan_hints: []`,
`constraints_present: false` even when the design shipped an OpenLane-style
`config.json` with `DIE_AREA`/`FP_SIZING`/`FP_DEF_TEMPLATE` AND a prose
`DIE_AREA = [x0,y0,x1,y1] µm` statement — so phase3 auto-sized a die the
design had already fixed.
```

"**phase3 auto-sized a die the design had already fixed**" is the mechanism, in
the repo's own words.

### Measured today, not quoted from the stale comment

`floorplan_contract.py:56` records "194 of 194 tracked L19 documents carry
`die_area_budget_um: null`", and `tools/gen_flow_gate_d9_section.py:310-312`
already flags that comment as out of date. So I re-measured it rather than quoting
either. Over the 194 `L19_*.json` in the live `benchmark-data`:

```
L19 docs               : 194
  die_area_budget_um null : 134
  key absent entirely     : 54
  populated               : 6   (of which non-machine-comparable prose: 4)
```

**188 of 194 (96.9 %) carry no machine-usable die budget.** The 6 populated:

```
<A-caravel>/v1.9.43_*/…/L19_CONSTRAINTS_PDK.json  -> '2920x3520'
<C>/generated_docs/L19_CONSTRAINTS_PDK.json       -> 'user macro ~2900 x 3500 um (…-class)'
<C>/phase1/ai_docs/…                              -> 'user macro ~2900 x 3500 um (…-class)'
<C>/phase1/generated_docs/…                       -> 'user macro ~2900 x 3500 um (…-class)'
<C>/phase1/merged_docs/…                          -> 'user macro ~2900 x 3500 um (…-class)'
<B>/v1.9.86_*/…/L19_CONSTRAINTS_PDK.json          -> '1300x1300'
```

Only **two** are machine-comparable — `'2920x3520'` and `'1300x1300'` — and
**neither matches any of the four slots**. Both are a *different* shuttle's
geometry (a user-macro area, not a die), which is the sharper version of the
finding: even where our flow does carry a die number, it is a number for another
programme's wrapper, not a slot on this one.

---

## 4. Is there ANY notion of a target slot / shuttle geometry in this repository?

**Mixed, and the distinction matters: `DIE_AREA` is FOUND as a design-declared
contract; a SLOT is ABSENT, and deliberately so.**

**FOUND — `DIE_AREA` as something a design may declare:**
- `programs/floorplan_contract.py` — extracts `DIE_AREA` (rect -> WxH),
  `FP_SIZING`, `FP_DEF_TEMPLATE`, `FP_PIN_ORDER_CFG` from a design's own
  `config.json` / `config.tcl` / prose (lines 15-18, 321-341).
- `programs/l9_floorplan_contract_check.py:97` —
  `DIE_AREA / DIE_WIDTH+DIE_HEIGHT / PL_TARGET_DENSITY / FP_CORE_UTIL`.
- `programs/l19_pdk_floorplan_contract_check.py:34`.
- `tools/phase1_engine/canonical_alias_map.yaml:63,65` — `L9.die_width_um`,
  `L9.die_height_um`.

Every one of these reads a number **the design supplies**. None supplies one, and
none knows what a slot is.

**ABSENT — a slot, a shuttle geometry, or a saw street:**
- `git grep -in "saw_street\|saw street\|scribe"` — no hit in any program;
  the only `scribe` hit is in a step *name* at `flow/…yaml:5133` ("scribe layout"),
  with nothing behind it.
- `git grep -in "reticle"` — hits are `foundry_handoff_pack_gen.py` emitting a
  `PENDING_FOUNDRY_reticle_steppers` placeholder and
  `manufacturing_fab_intake_check.py` treating `reticle_id` as an opaque string.
  No geometry.
- `git grep -in "slot"` — **1554 matching lines across 233 files**, and every hit
  I inspected is an unrelated sense of the word. The senses, all of them: a
  concurrency/scheduling slot (`tools/ci/_gate_dispatch.sh`, `tools/liar_census.py`),
  a gate-clause slot (`advisory_program_exit_zero` etc., throughout the flow yaml),
  a canonical-field slot (`tools/phase1_engine/*`, `agents/class_kb/*`), a
  benchmark scoring slot (`benchmark/cvdp_gate.py`), and a packed-array/FIFO bit
  slot (`agents/ic-expert-agent.md`, `ic_expert_db.json`). **No shuttle slot.**
  I sampled rather than read all 1554 lines, so this is "no hit found in a wide
  sample", not a proof of absence.

**The named slot checks do not exist.** `programs/tapeout_readiness_check.py:250-259`
maps the upstream ladder step to in-tree coverage:

```python
250        LadderStep(
251            "KLayout.CheckSize", "Check Slot Size",
252            "origin is not at (0,0), or the die dimensions do not match the "
253            "purchased slot",
257            covered_by=("die_slot_dimension_check", "seal_ring_check",
258                        "frame_dimension_check")),
```

Checked on disk — **all three are ABSENT**, as are the three named for the
neighbouring steps:

```
ABSENT   die_slot_dimension_check      ABSENT   frame_marker_check
ABSENT   seal_ring_check               ABSENT   die_id_marker_check
ABSENT   frame_dimension_check         ABSENT   pad_ring_mask_check
```

**This is recorded, not overlooked.** `programs/tests/test_tapeout_readiness_check.py:119-127`
asserts the gap and says why it is written as an assertion:

> "Not an assertion that we have no frame check — a RESOLUTION. If somebody lands
> `die_slot_dimension_check.py` or `frame_marker_check.py` this test starts
> failing and the registry entry, not the claim, is what gets edited."

and it asserts `"KLayout.CheckSize" in uncovered`.

**And the absence is policy.** `test_it_wraps_rather_than_reimplements`
(same file, 333-349) forbids the slot vocabulary from appearing in our code at all:

```python
    for forbidden in ("0p5x0p5", "GUARD_RING_MK", "Metal5", "0.001",
                      "dbu", "um2", "density_window"):
        assert forbidden not in code, forbidden
```
> "No slot dimension, density window, DRC rule or pad geometry lives here. A
> reimplementation would be ours again, and could drift into passing. The registry
> may name the upstream STEPS; it may not encode what they enforce."

That is a good rule and this note does not argue against it. But it constrains the
shape of any fix: **the slot geometry must arrive as ingested data, not as a
literal typed into one of our checkers.** Which is exactly what section 5 finds.

---

## 5. Does the template pin `DIE_AREA`? — YES, to the slot, exactly

**This is the whole answer.** `wafer-space/gf180mcu-project-template`
(HEAD `0de7e394337a1f7f5303ac7a3681bf2481b58176`) ships one config file per slot,
and each pins `DIE_AREA` absolutely:

```yaml
# librelane/slots/slot_1x1.yaml
FP_SIZING: absolute
# 3880umx5070um including 26um
# for the sealring on all sides
DIE_AREA: [0, 0, 3932, 5122]
CORE_AREA: [442, 442, 3490, 4680]
```

The comment is `check_size.py`'s own derivation, restated: `3880 x 5070`, plus
`26` for the seal ring on all sides. Same three constants, same arithmetic, in the
operator's two artefacts independently.

All four, measured by `grep -rn DIE_AREA` across the template:

| file | `DIE_AREA` | `check_size.py` slot | match |
|---|---|---|---|
| `librelane/slots/slot_1x1.yaml:5` | `[0, 0, 3932, 5122]` | 3932.0 x 5122.0 | ✅ |
| `librelane/slots/slot_0p5x1.yaml:3` | `[0, 0, 1936, 5122]` | 1936.0 x 5122.0 | ✅ |
| `librelane/slots/slot_1x0p5.yaml:3` | `[0, 0, 3932, 2531]` | 3932.0 x 2531.0 | ✅ |
| `librelane/slots/slot_0p5x0p5.yaml:3` | `[0, 0, 1936, 2531]` | 1936.0 x 2531.0 | ✅ |

**Four for four.** And `DIE_AREA: [0, 0, …]` also satisfies the origin check at
line 36 by construction — the template hands the submitter the (0,0) origin too.

Each slot file also carries `FP_SIZING: absolute`, a `CORE_AREA` inset 442 um from
the die edge (the pad-ring + seal-ring margin), and the full four-sided
`PAD_SOUTH` / `PAD_EAST` / `PAD_NORTH` / `PAD_WEST` instance lists — the pad
ordering that `OpenROAD.PadRing` requires as a config contract per
`/tmp/UPSTREAM_REFERENCE.md` §1. The 1x1 slot places 40 `bidir` + 12 `inputs` +
2 `analog` pads; `0p5x0p5` places 38 `bidir` + 4 `inputs` + 4 `analog`. So the
**pad count is a function of the slot**, and a design cannot choose its die size
independently of its pin count.

`macros_5v.yaml:63,78` then read `$DIE_AREA[2]` / `$DIE_AREA[3]` to place the
marker and logo relative to the die — the same first-class-variable pattern
`KLayout.SealRing` uses (`/tmp/UPSTREAM_REFERENCE.md` §2). One declared
`DIE_AREA` feeds the floorplan, the seal ring, and the id-cell placement.

**Conclusion.** The submitter does not choose a die size and does not compute one.
They pick a slot, and the template supplies `DIE_AREA`, `CORE_AREA`, `FP_SIZING`,
the pad lists and the id-cell placement as one coherent, pre-pinned set. Our gap
is the same one the id-cell note found: **no template ingestion step**.

---

## 6. The declaration change I want but did NOT make

Per the brief I did not touch `flow/phase1_phase2_phase3.yaml`. Stated in words,
with exact keys, for the gatekeeper's signature.

**Step 15 (`Floorplan + PDN`, line 2644) should gain a declared die-geometry
input.** Today it declares only a netlist and constraints, so nothing in the flow
can tell a die that was chosen from a die that was defaulted. I would add, under
step 15:

```yaml
    required_inputs:
      - from: 12
        path: "phase2/stage2/synth/post_dft_netlist.v"
      - from: 7
        path: "phase2/stage2/constraints/*.sdc"
      # NEW — the target die geometry, when the design has one.
      - from: 0.5ic
        path: "input/submission_template/slots/*.yaml"
        optional: true
```

which depends on a **new step** that does the ingestion. I would declare it as
`0.5ic` (chip/IC path only, before Step 1), named something like
`"Submission Template Ingest (chip/IC path only)"`, whose `required_outputs` are

```yaml
      - "input/submission_template/slots/<slot>.yaml"
      - "input/submission_template/ip/gf180mcu_ws_ip__*/"      # the four id cells
      - "reports/phase3/submission_template.json"
```

and whose gate records the **declared slot** and the `DIE_AREA` read from it.

The single most important new key is a **top-level declared target slot**, because
it is the thing that has no representation anywhere in the tree today. I would put
it in the flow's declared project inputs as:

```yaml
    target_slot: "1x1" | "0p5x1" | "1x0p5" | "0p5x0p5" | null
```

with `null` meaning **the cell/IP path** — no die, no slot, and the chip-path steps
(`15.5ic`, `26.5ic`, `37.5ic`) correctly not applicable. That single key is what
lets Step 15 say "this die was chosen" instead of "this die happened", and it is
what makes the `flow_path: ic` / `ip` split already on this branch operational
rather than descriptive.

Two constraints on whoever implements it:

1. **Do not type the slot dimensions into a checker.**
   `test_it_wraps_rather_than_reimplements` forbids exactly that, and it is right.
   `1936`, `2531`, `3932`, `5122` must be *read from the ingested template file*,
   never literals in `programs/`. The template is data; treat it as data.
2. **Ingest, do not reimplement.** The seal-ring half of Step 26.5ic already gets
   this right — it calls the PDK's generator rather than drawing a ring. The die
   size deserves the same discipline: fetch the operator's slot yaml, pin its
   commit, and read `DIE_AREA` out of it.

I would also record, somewhere the flow can see it, that the corpus **cannot
currently satisfy any slot** — so that when `die_slot_dimension_check` does land,
its first run producing 7 FAILs is understood as the measurement working, not as a
regression.

### And one thing that is NOT a gap

`jseal`'s work stands. Moving the refusal from line 70 to line 107 is real
progress through a six-check ladder, and the ladder cannot be entered at line 107
— a layout with no seal ring never reaches the size check at all. The seal ring is
necessary. It is simply not sufficient, and the insufficiency was never theirs.

---

## What I did NOT run

- **I did not run `precheck.py` or `check_size.py` against any corpus layout.**
  The "first refusal" column is computed by my own reimplementation of the six
  checks in `measure.py`, reading the same layers and constants out of the same
  source file. It **is corroborated** by the one real recorded refusal in the
  tree: `programs/tests/fixtures/shuttle_precheck_refusal/runs/RUN_2026-08-18_21-40-05/`
  contains exactly three stage directories (`01-klayout-readlayout`,
  `02-klayout-checktoplevel`, `03-klayout-checksize`) and its
  `03-klayout-checksize/klayout-checksize.log` reads

      [Error]: Layer 'GUARD_RING_MK' is not used. wafers.space requires a seal
      ring (guard ring) around the die.

  which is the same verdict my model predicts for the digital rows, produced by a
  real container run. But that is ONE point of agreement, on ONE layout, for ONE
  of the six checks — it validates neither the origin branch nor the size branch.
  This remains a **model of** the checker, not the checker. Somebody should run
  the real container against row 5 and row 8 before this table is treated as an
  oracle.
- I did not verify the `1x1` slot is the default `--slot`, nor test the `else`
  branch at line 96-98.
- **I did not read `sshut`'s harness**, so the reconciliation of "one origin
  refusal" vs my three files is inference from the directory layout, not a
  verified account of its scope.
- I did not measure any layout outside `benchmark-data/**/ic/`. Layouts elsewhere
  in the corpus (evaluation/, or non-`ic` trees) were not swept.
- I did not check whether the four slot yamls are identical between
  `macros_5v.yaml` and `macros_3v3.yaml` flows, nor whether a 3v3 variant changes
  `DIE_AREA`. I read the 5V path only, plus a `grep` confirming `macros_3v3.yaml`
  uses the same `$DIE_AREA[2]/[3]` expressions.
- I did not run `tools/d9_flow_gate_reality.py` itself; I re-implemented its
  `die_area_budget_um` tally against `benchmark-data` because the L19 documents are
  not in the repo tree (`find . -name "L19*.json"` returns 0 there).
- I did not run the plugin test suite, `flow_compliance_check.py`, or any gate.
  This note changes no code and claims no PASS.
- **NDA note, flagged for the gatekeeper:** I redacted one design codename and the
  PDK directory segments in paths, but I retained the public shuttle-operator and
  open-source tool names (wafer.space, LibreLane, KLayout, OpenROAD) because the
  brief itself uses them throughout and they are public. If the NDA rule is meant
  to reach those too, this note needs another pass.
