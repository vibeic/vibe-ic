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
   # or `ext2spice lvs` — the two silent causes of a vacuous 0% degradation)
   python3 programs/magic_extract_spice_emit.py --validate extract.tcl
   ```
   Then run it via `eda_extraction` (or magic). Output:
   `analog/<block>/<block>_extracted.spice`.
   > The fixed `load / extract all / ext2spice lvs / ext2spice` recipe is
   > enforced by `programs/magic_extract_spice_emit.py` (distinct from the
   > GDS-read + port-promote LVS recipe in `magic_port_extract_emit.py`).

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
