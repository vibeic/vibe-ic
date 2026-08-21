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
  ORGANIC-20260531-magic-extraction-no-toplevel-ports; drive via `docker exec vibeic-eda` with the
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

## When a field design-side recipe SUCCEEDS but runner automation FAILS: DIFF the two runs' INPUTS first (captured #512)

When you are field-verifying a plugin's automation of a recipe the field agent
ALREADY proved by hand — the runner's automated run FAILs at some step while the
field's manual run SUCCEEDED at that same step — **do NOT re-triage the failure
from scratch.** Chasing the failure text (e.g. a netgen "Netlists do not match"
/ "failed pin matching") leads to round after round of symptom fixes.

Instead, **DIFF what the successful field run fed vs what the runner fed** at that
step: which netlist, which env var, which extraction path, which artifact
version. That single differing INPUT is almost always the plugin's blind spot —
the runner's automation silently selected a different (wrong) input that the
field, running by hand, implicitly avoided.

**Worked evidence (the same GDSII-LVS feature, twice):**
- **#508** — the env var was `export`ed in the magic-extraction shell, but the
  tool that consumes it (`netgen`) runs in a SEPARATE shell (`_docker_exec` =
  fresh `bash -lc` per call, env does not persist). *Input delta = shell scope.*
- **#509** — the LVS schematic side used the PRE-PnR synth netlist (spare=0,
  clkbuf=0) while the field used the POST-PnR netlist (spare=18, clkbuf=89).
  *Input delta = netlist choice.* The fix is itself programmable + chip-AGNOSTIC:
  prefer the post-PnR netlist and sanity-check the pre-vs-post signature (a
  layout DEF carrying spare/PnR-inserted cells must be compared against a
  schematic netlist that also has them) — see `_v0_3_15_select_lvs_netlist`.

Neither root cause is visible in the failure text; both surface INSTANTLY from a
field-input-vs-runner-input diff — short-circuiting N rounds of surface fixes.
**General rule:** every field→core handoff where the field has manually proven the
recipe — the runner's automation has likely picked a different input than the
field did; diff the inputs first.

## Switching a design-side artifact to runner-auto regeneration leaves a stale provenance entry — verify provenance completeness before declaring the upgrade done (captured #516)

When you promote a step output from a **design-side** manually-installed
artifact to **runner-auto** regeneration — i.e. you move the design-side
artifact aside so the runner freshly selects its own input (the right move to
avoid the #512 input-masking blind spot) — the design-side `provenance.jsonl`
entry it leaves behind goes **stale** in two distinct ways, and you must
reconcile BOTH before you can honestly call the design-side→runner-auto switch
"done":

- **(a) generated_by is stale even when the bytes are identical.** If the
  runner reproduces the same recipe, the runner output is byte-identical and
  the entry's content hash still matches — but the entry's `generated_by` field
  is now wrong (it claims design-side; the file on disk is the runner's). A
  byte-identical hash is actually the *proof* that runner-auto == the
  design-side recipe, but it does NOT make the provenance attribution correct.
  (繁中：`generated_by` 過時 — 雜湊雖對，歸屬已錯。)
- **(b) other declared outputs of the entry can go missing.** A provenance
  entry frequently declares MORE than one output (e.g. the report *and* the
  tool's stdout log). If you move those aside and the runner only regenerates
  SOME of them under the same names, the entry's other declared outputs are now
  absent → a `PROVENANCE_OUTPUT_FILE_MISSING` / completeness failure.

**Doctrine:** before declaring the switch complete, run the provenance
output-hash **completeness check**, and then either **restore the moved-aside
declared outputs** (regenerate them under their declared names) or **supersede
the stale entry** (write a fresh runner-authored entry so the runner entry is
authoritative). Pick restore-vs-supersede by intent, not by reflex.

**Worked evidence (spm LVS upgrade):** moved aside `lvs.rpt` +
`lvs_netgen_stdout.log`; the runner regenerated `lvs.rpt` (byte-identical hash —
runner-auto result == design-side recipe) but did NOT regenerate the stdout log
under that name → the stale entry's declared log was missing → P0 provenance
FAIL; restoring the log fixed it.

**why_not_bucket_a:** deciding whether a given stale entry should be
*superseded* (runner now owns it) or have its outputs *restored* depends on
whether the runner wrote its own replacement entry AND whether a byte-identical
output is semantically the runner's — a provenance-intent judgement, not a fixed
rule. The deterministic residual (the completeness check that catches a missing
declared output) already exists and fires correctly; this section is the
judgement layer over it. So when you switch a design-side artifact to
runner-auto, treat the provenance reconciliation as a required closing step, not
an afterthought.

## Handoff

- Re-run DRC after LVS fix → `/drc-fix`
- Layout edits → documented in `/eco-plan` log
- Schematic change → back to `/rtl-repair` or `/analog-layout`

## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/lvs-triage/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.
