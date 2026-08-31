---
name: analog-extraction-resim
description: Post-layout parasitic extraction + re-simulation for analog blocks — compares pre-layout vs post-layout specs. Use when the user says "post-layout resim", "extract and resimulate", "parasitic check", or at Step A7 of the analog track.
---

# Analog Extraction Resim

After analog layout in Magic, extracts parasitic RC and re-simulates across PVT corners to check for layout-induced performance degradation. Compares pre-layout vs post-layout results and flags regressions.

## When to use

- Step A7 of the analog track
- After `analog-layout` has produced a Magic `.mag` file
- When the user asks "did the layout hurt my bandwidth?"

## Inputs

1. `analog/<block>/layout.mag` — Magic layout file
2. `analog/<block>/corner_results.json` — pre-layout SPICE results (baseline)
3. `analog/<block>/spec.json` — specs for pass/fail comparison
4. PDK (gf180 or sky130)

## Workflow

1. **Extract parasitics** — emit/validate the Magic parasitic-RC TCL with
   `programs/magic_extract_spice_emit.py` (do not hand-write the recipe):
   ```bash
   # emit the deterministic .mag -> RC-annotated .subckt extraction TCL
   python3 programs/magic_extract_spice_emit.py --block <block> \
       --out-spice analog/<block>/<block>_extracted.spice --out extract.tcl
   # or validate an existing extraction TCL (FAILs if it omits `extract all`
   # or `ext2spice lvs`, AND if it puts them in an order magic will not
   # honour — the silent causes of a vacuous 0% degradation)
   python3 programs/magic_extract_spice_emit.py --validate extract.tcl
   ```
   Then run it via `eda_extraction` (or magic). Output:
   `analog/<block>/<block>_extracted.spice`.
   > The recipe's **order** is the product, not just its command set
   > (vibe-ic#1953). Measured on magic 8.3: `ext2spice lvs` RESETS
   > cthresh/rthresh to `infinite`, so the thresholds must be asserted
   > **after** it; `extresist` reads the `.ext` that `extract all` writes,
   > so it runs **after** the extract; and `ext2spice rthresh <float>` is a
   > parse error magic silently refuses (it wants an integer). All of this is
   > enforced by `programs/magic_extract_spice_emit.py` (distinct from the
   > GDS-read + port-promote LVS recipe in `magic_port_extract_emit.py`).

1b. **Audit what magic actually WROTE — mandatory, before any re-sim.**
   A recipe that validates can still yield a parasitic-free netlist if the
   tool or PDK refuses; the only way to know is to read the output.
   ```bash
   python3 programs/magic_extract_spice_emit.py \
       --audit-netlist analog/<block>/<block>_extracted.spice \
       --res-ext analog/<block>/<block>.res.ext
   ```
   Exit 1 = the netlist carries **0 R and 0 C**. Re-simulating it
   re-simulates the *pre-layout* circuit, and the pre-vs-post comparison in
   step 3 is a false 0% degradation. Do not proceed; fix the extraction.
   Exit 0 prints the **depth achieved** — `RC` or `C_ONLY`. `C_ONLY` is a
   real, common outcome (magic 8.3 / sky130A emits no R elements even with
   resistance extraction fully armed), and it is **passable but must be
   disclosed**: carry `"parasitic_depth": "C_ONLY"` into `pre_vs_post.json`
   `_provenance` so no reader mistakes it for full RC. If the block's claim
   genuinely needs series R, add `--require-resistance` and take the honest
   FAIL rather than a silent capacitance-only substitution.

2. **Re-simulate with extracted netlist**:
   - Replace ideal subcircuit with extracted netlist in testbench
   - Run `eda_spice_corner` with same corners as pre-layout
   - Output: `analog/<block>/post_layout_corner_results.json`

3. **Compare pre vs post** — run the deterministic checker; do not re-grade by hand:
   ```bash
   python3 programs/analog_pre_vs_post_layout_check.py <project> --json
   ```
   It computes per-metric per-corner degradation `(post - pre) / pre × 100%` and
   classifies it against the **canonical degradation bands, which the program owns**
   (single source of truth — see "Degradation thresholds" below). Do NOT hardcode a
   different ERROR/WARNING cutoff in your report; quote the program's verdict.
   - Typical degradation sources:
     - Bandwidth reduction (parasitic C on high-impedance nodes)
     - Gain reduction (parasitic R in signal path)
     - Increased noise (parasitic coupling)

## Output format

### `analog/<block>/pre_vs_post.json`

Write it at `phase3/analog/<block>/pre_vs_post.json` — the canonical analog
dir (`_path_layout.analog_dir`), which is what the A7 gate globs.

**The container key is `comparisons` (plural).** This doc used to show
`comparison` (singular); `analog_pre_vs_post_layout_check.py` has only ever
read `comparisons` or `specs`, so a file authored exactly per the old example
was parsed as zero comparable specs and the gate FAILed it
`PRE_VS_POST_ZERO_COMPARED` — a correct result authored per its own
instructions was rejected. The program is the single source of truth here, as
it already is for the thresholds below.

```json
{
  "block_name": "ldo_1v8",
  "pre_layout_file": "corner_results.json",
  "post_layout_file": "post_layout_corner_results.json",
  "comparisons": {
    "gain_db": {"pre": 62.3, "post": 58.1, "degradation_pct": -6.7, "status": "OK"},
    "ugb_mhz": {"pre": 11.2, "post": 7.5, "degradation_pct": -33.0, "status": "ERROR"},
    "vout_dc": {"pre": 1.8002, "post": 1.7998, "degradation_pct": -0.02, "status": "OK"}
  },
  "worst_degradation": {"metric": "ugb_mhz", "pct": -33.0},
  "overall_status": "NEEDS_RELAYOUT"
}
```

Accepted spellings (exactly what the gate parses — nothing else is read):

| position | accepted keys |
|---|---|
| container | `comparisons` (preferred) or `specs` |
| container shape | dict of `{metric: {…}}`, or list of `{"name": …, …}` |
| pre value | `pre_layout` or `pre` |
| post value | `post_layout` or `post` |

Both values must be numeric and `pre` must be non-zero, otherwise that metric
is not counted. A file in which NO metric is comparable FAILs
`PRE_VS_POST_ZERO_COMPARED` — a comparison gate must never report PASS having
compared nothing.

### Naming the post-layout measurement (required when every delta is zero)

If **every** compared metric's post value is exactly equal to its pre value,
the artefact must NAME the post-layout artefact its post column was simulated
from, and that artefact must exist on disk. Otherwise both gates over this file
FAIL `*_ALL_ZERO_DELTA_UNEVIDENCED`.

This is not a style rule. A degradation gate fed a post column copied from the
pre column can only ever compute 0 %, which is its most acceptable tier — so a
copy scores better than every honest comparison, and `PRE_VS_POST_ZERO_COMPARED`
does not see it (a copy is N comparisons of a number against itself, not zero
comparisons). An all-zero result that carries its provenance is a legitimate
(if surprising) measurement and still passes.

Accepted evidence keys, read at `_provenance.<key>` and at the top level:

| key | what it should point at |
|---|---|
| `extracted_netlist` | `<block>_extracted.spice` from step 1 |
| `post_layout_netlist` | same, alternative spelling |
| `post_layout_corner_results` | `post_layout_corner_results.json` from step 2 |
| `post_layout_file` | either of the above (the spelling used in the example) |

```json
{
  "_provenance": {"extracted_netlist": "ldo_1v8_extracted.spice"},
  "comparisons": { "...": {} }
}
```

Relative paths resolve against the block directory, then the project root. The
named file must be non-empty, inside the project, and must not be
`pre_vs_post.json` itself or the pre-layout `corner_results.json` it is compared
against — neither of those is a post-layout measurement.

If the layout is a placement-only PV vehicle and no extraction was run, do NOT
copy the pre-layout column into the post column: A7 has not happened, and an
artefact that says it has is worse than an absent one.

## Degradation thresholds

Enforced by `programs/analog_pre_vs_post_layout_check.py` (single source of
truth — `≤20%` OK / `>20%` WARNING / `>30%` ERROR→NEEDS_RELAYOUT). Quote the
program's verdict; do not restate a conflicting cutoff. If the policy must
change, change it in the program (one place) so SKILL.md and runtime never drift.

## Do not

- Do not skip extraction and go straight to hardmacro — parasitic RC is the #1 cause of analog silicon failure
- Do not compare only TT corner — worst-case degradation often appears at SS+hot
- Do not ignore capacitive loading on compensation nodes (Cc) — parasitics add to Cc

## Handoff

Branch on the `overall_status` field emitted by
`programs/analog_pre_vs_post_layout_check.py` (deterministic, not a judgment call):

- `OK` / `WARNING` → `analog-hardmacro-gen` (Step A8)
- `NEEDS_RELAYOUT` → back to `analog-layout` (Step A5)
- `post_layout_corner_results.json` → `analog_pre_vs_post_layout_check` gate

## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/analog-extraction-resim/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.

**Your task is not complete until the audit returns PASS.**
