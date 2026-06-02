---
name: drc-fix
description: Diagnose and fix Design Rule Check (DRC) violations in a layout or GDS. Use when the user says "fix DRC", "DRC clean", "resolve spacing errors", "my layout fails DRC", or shares a DRC report from Calibre, Klayout, or Magic.
---

# DRC Fix

Take a DRC report and a layout, and produce a targeted fix plan — which rules are violated, where, why, and the minimal edits to clean them. Handles common rule families: spacing, width, density, via enclosure, antenna, and metal fill.

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

1. **Group by rule** — 1000 violations are usually 5 root causes
2. **Classify severity** — hard (will fail fab) vs soft (waiverable)
3. **Map rule to fix pattern** — spacing → move or add jog; width → widen or replace; density → add fill; antenna → add diode or jumper
4. **Propose minimal edit** — smallest layout change that clears the rule
5. **Check for collateral damage** — does the fix create a new violation or break LVS?
6. **Emit fix script** — KLayout Python, SKILL, or TCL snippet when applicable

## Output format

```
# DRC Fix Plan — <block>

Total violations: N → grouped into M root causes

## Root causes
| # | Rule | Count | Root cause | Fix strategy |
|---|------|-------|------------|--------------|
| 1 | M2.S.1 | 47 | std-cell row abutment on narrow pitch | add 1-track jog on M2 egress |
| 2 | ANT.1  | 12 | long M3 antenna to gate | insert diode at sink |
| ... |

## Fix order (apply in sequence)
1. ...
2. ...

## Expected residual
After applying the plan, residual violations: ~<n> (list each with waiver rationale or further fix)

## Verification
Re-run DRC on <list of affected cells>.
```

## Technical basis

Grounded in DRC-Coder and LLM-assisted layout repair research. Key insight: DRC reports are structured logs, and the mapping from rule violation → fix pattern is largely a classification problem that LLMs handle well when given the rule deck.

## Do not

- Do not propose fixes that break LVS (especially for antenna diodes — maintain connectivity)
- Do not waive hard rules without explicit user approval
- Do not touch cells outside the block boundary without flagging it

## Canonical loop infrastructure (mandatory — shared with all *-fix loops)

When the DRC fix workflow iterates (re-run DRC → residual still > 0 → adjust
spacing/jog/fill → re-run), that loop MUST be driven by the two shared
closed-loop primitives so every fix loop in Vibe-IC obeys one
convergence / plateau / regression policy and one runaway / dedup guard —
do **not** hand-roll a bespoke retry counter or duplicate-fix check.

**1. `programs/iterative_search.py` — the parameter sweep.**
Model the per-rule fix knobs as a typed `SearchSpace`; `IterativeSearch`
proposes the next layout-edit trial and `ConvergenceChecker` classifies the
residual-violation history (`CONVERGED` / `PLATEAU` / `REGRESSION` /
`EXHAUSTED` / `CONTINUE`):

```python
import iterative_search as it
space = it.SearchSpace([
    it.Dimension("jog_tracks", "integer", lo=0, hi=8),       # extra routing tracks
    it.Dimension("spacing_nm", "continuous", lo=0.0, hi=400.0),
    it.Dimension("fill_density", "continuous", lo=0.0, hi=1.0),
    it.Dimension("strategy", "enumerate", choices=["jog", "widen", "fill", "diode"]),
])
# target=0 residual violations; minimize the count
checker = it.ConvergenceChecker(target=0.0, tolerance=0.0, patience=4)
search  = it.IterativeSearch(space, checker, maximize=False, seed=7, max_rounds=20)

def evaluate(point):          # caller runs KLayout/Magic DRC here
    return residual_violation_count   # lower is better
outcome = search.run(evaluate)        # outcome.status / best_point / rounds
```

`IterativeSearch` constructs an `AdmissionGuard(bounds=space.bounds(),
max_iterations=max_rounds)` internally, so each proposed edit is already
runaway- and dedup-guarded when you use `search.propose()` / `search.run()`.

**2. `programs/loop_admission_guard.py` — admit each iteration BEFORE the DRC run.**
A DRC re-run is expensive; gate every proposed edit through
`AdmissionGuard.admit()` first:

```python
import loop_admission_guard as g
guard = g.AdmissionGuard(
    bounds={"spacing_nm": (0.0, 400.0), "fill_density": (0.0, 1.0)},
    caps={"jog_tracks": 8},                 # REJECT a runaway jog count
    max_iterations=20)                       # hard RUNAWAY iteration budget
res = guard.admit({"jog_tracks": 1, "spacing_nm": 90.0, "strategy": "jog"})
if res.admitted:
    rerun_drc(res.proposal)                  # res.proposal is post-clamp / safe
# else res.reason in {DUPLICATE, RUNAWAY_CAP, RUNAWAY_ITERATION_BUDGET}
```

CLI one-shot decision (exit 0 = ADMITTED, 1 = REJECTED):

```bash
python3 programs/loop_admission_guard.py decision.json
# decision.json: {"bounds":{...},"caps":{...},"max_iterations":20,
#                 "history":[...prior edits...],"proposal":{...}}
```

`canonical_fingerprint(proposal)` is the dedup key — re-proposing a fix
combination already tried this session is rejected with `reason="DUPLICATE"`
instead of wasting a KLayout/Magic DRC pass. This is ADDITIVE: it enforces a
budget + plateau/regression exit around the existing "Fix order → Expected
residual → Verification" steps without changing any of them.

## ⛔ ECO spare-cell preservation (mandatory)

> ⛔ **ECO spare-cell preservation:** cells/gates/pads carrying the `dont_touch` /
> `keep` attribute (or otherwise tagged spare/ECO) are RESERVED for a future
> metal-only ECO. NEVER delete, resize, re-purpose, or optimize them away while
> clearing DRC. In particular: a density/metal-fill fix must stay **ECO-aware**
> — do NOT delete spare cells/pads to clear spacing, and do NOT lock metal fill
> over the tracks above spares/reserved pads (use slottable/removable fill there
> so a future metal-only ECO can still route to them). No `opt_clean` /
> `clean -purge` / `remove_buffers` on keep-marked instances to "clean up"
> geometry. After your DRC fix, `spare_cell_preservation_check.py` MUST still
> PASS (spare set + keep attrs intact, 0 removed); a dropped spare is a
> regression — restore it and re-run the checker. See the `design-for-eco` skill.

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

## Compliance gate (vibe-ic-d - mandatory when deterministic edition is installed)

If you have the `vibe-ic-d` plugin installed alongside `vibe-ic`,
after producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic-d/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic-d/skills/drc-fix/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding vibe-ic-d skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.
