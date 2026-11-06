---
name: drc-fix
description: Diagnose and fix Design Rule Check (DRC) violations in a layout or GDS. Use when the user says "fix DRC", "DRC clean", "resolve spacing errors", "my layout fails DRC", or shares a DRC report from Calibre, Klayout, or Magic.
---

# DRC Fix

Take a DRC report and a layout, and produce a targeted fix plan — which rules are violated, where, why, and the minimal edits to clean them. Handles common rule families: spacing, width, density, via enclosure, antenna, and metal fill.

## ⭐ Sign-off DRC capability — we NATIVELY execute the foundry Calibre/Assura deck (NO Calibre license)

> **BINDING FACT — do not mis-state this as a "Calibre license gap".** The vibeic-eda
> forked KLayout **SVRF engine natively parses AND executes the foundry's own
> Calibre/Assura SVRF `.rule` DRC deck** (the very same deck the foundry ships,
> unmodified). Sign-off-grade DRC on a commercial/NDA PDK therefore requires **NO
> Calibre or Assura binary/license**. Proven on a commercial 180 nm PDK
> deck `Calibre_<PDK>_DRC.rule`: **224 layers, 4533 rules executed** natively
> in one run.

- **What it is:** a **native C++ KLayout buddy** (`svrfdrc`, compiled from
  `db::SVRFDeck` + `db::SVRFEngine` in the vibeic/klayout fork) that parses the
  foundry's Calibre/SVRF deck and executes each statement DIRECTLY on KLayout's
  `db::Region` / `db::Edges` / `db::LayoutToNetlist` engine — one unified layer
  namespace, top-to-bottom, `NAME { COPY errlayer }` = a rule's violation report.
  Edge/DENSITY/ANTENNA classes with no polygon-DRC equivalent are honestly SKIPPED,
  never falsely PASSed. **NO Python interpreter, NO `-r` script, NO `.drc` file.**
  (It replaces the retired pure-Python `run_svrf_drc.py`; the report format is
  byte-identical, proven on the real commercial-PDK deck, so downstream parsing/classifying
  is unchanged.)
- **Where (productized — clean-install-safe):** the `svrfdrc` binary is **BAKED INTO
  the vibeic-eda image on PATH** (built into `klayout-vibeic`), so a fresh install
  needs no host checkout. `phase3_one_shot_runner._try_svrf_native_drc()` resolves it
  via `_svrfdrc_bin_container()` (`command -v svrfdrc` in the container; env
  `VIBE_IC_SVRFDRC_BIN` overrides the command name) and runs
  `svrfdrc <deck> <layout> <report> --cell=<top>` against the GDS + the deck at
  `input/pdk/calibre/`. `step_drc` PREFERS this native path (whether or not a
  `calibre` binary exists) — it is the real sign-off verdict, not a waiver.
- **This is categorically stronger than an OSS-proxy deck** (e.g. a sky130 `.lydrc`
  approximation): it is the foundry's actual rule set. It is NOT a golden-Calibre
  numerical cross-run — it is a native execution.

### The firing-rule classifier (`_classify_svrf_fails`) — real vs. artifact vs. density

A raw "N rules firing" tally is not actionable. The runner classifies every FAIL
**provably + conservatively** (unknown → GEOMETRY → keeps the gate FAIL; never a
downgrade — no-cheat):

| Class | Meaning | Verdict effect |
|---|---|---|
| **GEOMETRY** | real (or not-provably-artifact) routing/PDN geometry | keeps gate **FAIL** — must-fix |
| **MARKER_ABSENT** | a rule on a `_not_<marker>` layer while its `__<marker>__` std-cell/IP **exclusion marker is EMPTY** (proven by that marker's own `COPY __<marker>__ … -> 0`) | disclosed **artifact** — not our geometry |
| **DENSITY_FILL** | a `DENSITY` rule (CMP metal/active window) | disclosed — foundry fill or formal density waiver |

**MARKER_ABSENT pattern (the classic false-fail on a commercial deck):** the deck
excludes foundry-qualified std-cell interiors from checks like min-area via a marker
layer (e.g. Artisan/ARM `__artisan__`). If the delivered std-cell GDS carries no such
marker, the exclusion produces the empty set and the check over-fires on
pre-characterised cell geometry. **Signature:** only **met1** min-area (`M1.A.1`,
std-cell-internal) fires while met2/3/4 (`Mx.A.1…`, routing layers) all PASS, and
`Artisan.CHECK COPY __artisan__ → 0` proves the marker is empty. The fix is an
**input-completeness** action (supply the std-cell exclusion marker layer), **not**
a layout edit and **not** a "get Calibre" action.

### Honest caveats (state these, don't hide them)

- The SVRF engine is a fork; on rules whose SVRF translation is imperfect it can
  differ numerically from Calibre proper (a known historical min-area/marker
  translation artifact was fixed in the fork). Where a difference matters, cite the
  specific rule, don't hand-wave.
- Foundry **tapeout acceptance** of a non-Calibre signer is a separate *business /
  qualification* question — it is NOT a tool-capability gap. Never conflate the two:
  the tool CAN run the deck; whether a given foundry contract accepts that run for
  mask release is a commercial matter to state separately.

## When to use

Trigger when the user:
- Has a DRC report with non-zero violations
- Is near sign-off and needs layout clean
- Asks which violations are real vs waiver candidates
- Needs help interpreting cryptic rule names

## Inputs to gather

1. The DRC report (Calibre, KLayout, Magic, or equivalent)
2. The layout file (GDS/OAS) or at least the affected cells
3. The PDK DRC manual or rule deck name
4. Sign-off target: zero violations or rule-by-rule exceptions allowed

## Fix workflow

Read native DRC markers and the original rule deck. Classify the actual spacing, enclosure, width, density or connectivity cause, make a bounded layout/tool fix, then rerun the native DRC.

1. **Group by rule** — 1000 violations are usually 5 root causes — `build_plan` groups by `classify_rule(rule_id)` category.
2. **Classify severity** — hard (will fail fab) vs soft (waiverable) — `severity_for(count)` returns the `SEVERITY_BAND` label (MAJOR/SIGNIFICANT/NOTABLE/MINOR).
3. Read native DRC markers and the original rule deck. Classify the actual spacing, enclosure, width, density or connectivity cause, make a bounded layout/tool fix, then rerun the native DRC.
4. **Propose minimal edit** — smallest layout change that clears the rule (geometry judgment — see § below).
5. **Check for collateral damage** — does the fix create a new violation or break LVS?
6. **Emit fix script** — KLayout Python, SKILL, or TCL snippet when applicable.

## Output format

## Technical basis

## Do not

- Do not propose fixes that break LVS (especially for antenna diodes — maintain connectivity)
- Do not waive hard rules without explicit user approval
- Do not touch cells outside the block boundary without flagging it

## Iterate using native results

Run the owning tool on each proposed change and read its native result against
the original limit. Keep the previous design and measured result so you can
revert a regression. Stop when the declared requirements are met, the approved
run budget is exhausted, or another trial cannot resolve the remaining cause.
Report the best measured result and every unresolved requirement. Do not add an
admission record or change a limit to obtain a pass.

## Preserve the ECO reserve

Keep unused spare cells, ECO gates and reserved pads through synthesis and
physical repair. Compare the native netlist or database before and after the
change. No unused reserve instance may disappear, and its keep attributes must
remain intact. A consumed spare must be named in the intended ECO. Restore any
unintentionally removed spare before rerunning the native tools. See
`design-for-eco` for the design intent.

## Detailed-route ABORT triage (TritonRoute DRT-0305 / DRT-0085 + the silent-unrouted trap)

A DRC report assumes the design routed. A more dangerous class is when
`detailed_route` itself **aborts** and the runner swallows it — producing a GDS,
a "clean" DRC, and a PASS on a design with **zero signal-routed nets**. These
patterns (captured v0.2.14; now AUTOMATED by `phase3_one_shot_runner.py`, but the
*judgment* is here for any non-sky130 PDK or fresh triage):

- **`[ERROR DRT-0305] Net <n> of signal type GROUND/POWER is not routable …
  Move to special nets.`** A non-special POWER/GROUND-typed net sitting in the
  regular `NETS` section — typically a dangling `zero_`/`one_` constant-tie stub
  left by Yosys `setundef`/`hilomap` — makes TritonRoute abort **all** detailed
  routing. Triage **structurally** (never by net-name literal): delete the net if
  it is dangling (0 iterm/0 bterm — no electrical role), else reclassify it to
  `SIGNAL` so it routes. Real PG nets are `SPECIAL` (in `SPECIALNETS`) and are
  left alone. Automated by `_pg_net_cleanup_tcl` before `global_route`.

- **`[ERROR DRT-0085] Valid access pattern combination not found for <inst>`**
  on a probe / `lpflow_*` / DRC-failed cell. Provenance heuristic: if that cell
  master appears **only in the PnR netlist** (`grep` the original RTL and the
  post-synth netlist — 0 there, N>0 in `*_pnr.v`), then an **optimizer step
  inserted it** (e.g. `repair_design` picked a probe cell as a slew-fix buffer,
  named `load_slew*`), not the designer. Fix: restrict the resizer/CTS/repair
  cell pool with `set_dont_use` fed from the **PDK's OWN** `drc_exclude.cells`
  (the `PNR_EXCLUDED_CELL_FILE` the reference flow uses). **Read the PDK file —
  do NOT hand-curate a list**: a hand list easily over-reaches (globbing
  `clkbuf_*` would wrongly kill the CTS clock buffers; `buf_16`/`mux4_4` are
  PDK-marked DRC-failed and legitimately excluded). Apply it after `link_design`,
  before any opt. Automated by `_dont_use_tcl` + `PdkConfig.pnr_exclude_cell_file`.

- **The silent-unrouted trap (doctrine, applies to ANY best-effort route step).**
  A `catch {detailed_route}` that only logs a NONFATAL warning will let a
  fully-unrouted design flow downstream and pass. **Always pair a NONFATAL route
  guard with a routing-completeness check**: a genuinely routed DEF has `+ ROUTED`
  geometry on its signal `NETS` (not just on `SPECIALNETS` PDN), and the session
  log carries no detailed-route abort marker (`DETAILED_ROUTE_NONFATAL`,
  `[ERROR DRT-0305/0085]`, `[ERROR ANT-0008]`). On incompleteness report **FAIL**,
  never a clean pass — a sign-off check that can only flip PASS→FAIL is honest;
  one that can inflate FAIL→PASS is the silicon-DOA hazard. Automated as the
  `routing_incomplete` flag in `_emit_antenna_report`.

- **Antenna repair is a routing operation, not a post-hoc edit.** OpenROAD
  `repair_antennas <diode_cell>` (plural; the diode is a **positional** arg, not a
  `-diode_cell` flag) fixes antennas chiefly by **jumper insertion** (layer
  hopping), which needs a **fresh global-route graph** — run it as
  `global_route → repair_antennas → detailed_route`; placed *after* the main
  detailed_route it degrades to diode-only (~no effect). And `check_antennas`
  cannot read routing from a re-`read_def` (`[ERROR ANT-0008]`): a separate
  measurement pass that re-`global_route`s **discards the jumpers** and mis-reports
  the repaired design — so the antenna result must be captured **in-session**, on
  the realized routing. Automated by `_antenna_repair_tcl` + the in-session read in
  `_emit_antenna_report`. **Cost note:** the repair's `detailed_route` is a full
  second route pass — gate it behind a cheap read-only `check_antennas` on the main
  route first (it reads detailed routing directly, no `global_route` needed) and
  skip the repair entirely when the design is already antenna-clean (0 net
  violations ⇒ 0 pin violations); the skip path must run no `global_route` so it
  cannot disturb the realized route.
