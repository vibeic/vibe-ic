# HANDOFF TO GATEKEEPER — false-certificate investigation + mask-stack floor

**Worktree:** `/home/reyerchu/vibe-ic-wt-falsecert86/`
**Branch:** `fix/gds-falsecert-verify-fc86` (branched from `origin/main` @ `0d2c63d3`)
**Commits:**

| sha | what |
|---|---|
| `d51e6bda` | **cherry-pick of `fc32928c`**, unchanged — the other agent's `gds_substance_check`, taken as my base |
| `abd1508c` | **mine** — mask-stack floor (check D) + de-flake of an inherited negative control |

**NOT pushed.** Nothing went to any remote. Landing is the gatekeeper's call.

> **VERSION: deliberately NOT bumped.** `.claude-plugin/plugin.json` still
> reads `1.5.78`. Assign the version in the landing commit — a bump committed
> here would be silently eaten by the rebase. That collision already happened
> once today.

> **⚠️ BRANCH OVERLAP — READ BEFORE LANDING.** `fc32928c` also lives in
> `/home/reyerchu/vibe-ic-wt-gdssubstance/` (another agent, ~13:22), where it
> has **uncommitted** further work: a `_FLOOR_EXEMPT_GLOBS` diff that adds
> `phase3/stage4/foundry_handoff/**/*.gds` to the structure+substance scope
> while exempting it from the instance floor. **My branch does not contain
> that diff** — take it from their worktree. See §5: I verified it is
> corpus-clean and orthogonal to my commit.

---

## 1. Headline: the run is legitimate. It is not a false certificate.

The premise does not hold, and I am reporting that plainly because the
opposite conclusion would trigger a rollback that isn't warranted. This
independently reproduces the conclusion in `fc32928c` — I re-derived it from
the raw artefacts before reading their handoff.

### The 86 bytes is a symlink's target-path length, not a file size

```
$ cd ~/campaign_v1574/spm/converge_1.5.74_ihp-sg13g2
$ ls -la steps/37_gdsii_output_only_if_step_31_pv_fully_clean/spm.gds
lrwxrwxrwx 1 reyerchu reyerchu 86 ... spm.gds -> /home/reyerchu/campaign_v1574/spm/converge_1.5.74_ihp-sg13g2/phase3/stage4/gds/spm.gds

$ stat  -c %s steps/37_.../spm.gds     # no deref
86
$ stat -Lc %s steps/37_.../spm.gds     # deref
822084
$ readlink steps/37_.../spm.gds | wc -c
87                                     # 86 chars + newline
```

`ls -l` on a symlink reports the length of the target-path string. The target
path is exactly 86 characters. Everything under `steps/` is a symlink index
into the phase trees, materialised at 12:31:55. Any measurement that does not
dereference (`ls -l`, `stat -c %s`, `find -size`, `du -b`, a tar listing) reads
86 for that entry.

### The shipped artefact is a real 822,084-byte layout

Read straight from the bytes, not from any summary JSON:

```
00000000: 0006 0002 0258            HEADER, version 600
          001c 0102 07ea 0007 0019  BGNLIB, 2026-07-25
          0008 0206 7370 6d00       LIBNAME "spm"
          0014 0305 3e41 8937 …     UNITS
          001c 0502 …               BGNSTR
          0012 0606 7367 3133 6732… STRNAME "sg13g2_buf_16"   ← ihp-sg13g2 cell
```

Full parse: **28 structures, 11,583 elements, 19 mask layers, 1,826 SREF
placements against exactly 1,826 `COMPONENTS` in `phase3/stage3/pnr/routed.def`**
— byte-for-byte identical geometry to the committed golden
`benchmark-data/ic/spm/v1.5.58_ihp-sg13g2/` (also 822,084 B, also 28/11,583/19).
The SHA differs (`94be29af…` vs `acbb3ae1…`) only because GDSII embeds
BGNLIB/BGNSTR timestamps.

### The 169 s is honest — it was never a full phase1→3

From `campaign_logs/runner_spm_ihp-sg13g2.log`, the run's own first-hand log:

```
    phase1   : SKIPPED          ← 28/13 L docs already present, docs mode
    analog   : SKIPPED          ← "analog track skipped via --skip-ana"
    phase2   : PASS_WITH_WAIVERS
    phase3   : PASS_WITH_WAIVERS
  duration   : 169.2s
```

What actually ran in that time, on a design the runner itself scores
`complexity=9.58 tier=TRIVIAL`:

- phase2 — yosys synth (`cells=449`, 0.284 s per `provenance.jsonl`), TB gen,
  28/28 golden vectors, yosys LEC PASS
- phase3 — **PnR cache explicitly invalidated and re-run**
  (`[pnr] cache invalid — cached run requested die=103x103 …; now requested
  die=auto`), magic streamout `size=822084`, DRC `violations=0`,
  netgen LVS `circuits match uniquely`

169 s is unremarkable for that. The 198 s figure is outer wall-clock including
container setup.

### The run never claimed to be a tape-out certificate

Its own orchestrator output says so:

```
deliverable : NOT DELIVERED YET — RUN_STILL_IN_PROGRESS. This run is NOT
              complete until RESULT.md is authored. NO RESULT / empty
              output = the run FAILED.
```

`overall.pct 100.0%` is a step-compliance percentage, not a sign-off.

**One thing worth flagging separately** (not fixed here, out of scope): phase3
logged `PASS synth — netlist already present: spm_synth.v (skipped re-run to
preserve provenance)`. That is the known main-branch hole — netlist reuse
checks the PDK but not whether the RTL changed. It was harmless in this run
(RTL unchanged, and phase2's own yosys_synth did execute), but it fired. The
fix is pending in `/home/reyerchu/vibe-ic-wt-sha256mcr/`.

---

## 2. The gate hole I found — and it is NOT the 86-byte shape

An 86-byte GDS was already caught: `gds_size_check`'s 100 KB floor fails it
`TOO_SMALL`, and the substance gate fails it `TRUNCATED_RECORD`. The real hole
is the opposite shape — **anything big enough signed off regardless of content.**

`fc32928c` closes most of it. I attacked what it left. Six fakes, all mine,
all built independently of their four:

| # | fake | `gds_size_check` (pre-fix) | `fc32928c` | **`abd1508c`** |
|---|---|---|---|---|
| a1 | real GDS truncated to 60% | PASS | FAIL `TRUNCATED_RECORD` | FAIL |
| a2 | real GDS with an early ENDLIB | PASS | FAIL `MALFORMED_RECORD` | FAIL |
| a3 | gzip of a real GDS, renamed `.gds` | PASS | FAIL `MALFORMED_RECORD` | FAIL |
| a4 | **replay** — another design's real GDS | PASS | PASS | PASS ⚠️ |
| a5 | **2,600 squares on ONE layer, 166 KB** | PASS | **PASS** ❌ | **FAIL `TOO_FEW_MASK_LAYERS`** |
| a6 | the literal 86 bytes, as a real file | FAIL `TOO_SMALL` | FAIL | FAIL |

**a5 is the survivor.** It defeats every check by construction:

- structurally valid GDSII → the record walk (A) is clean
- has a structure, elements and a LAYER → substance (B) is clean
- 2,600 elements vs 1,826 placed instances → the design-derived floor (C) is clean
- 166 KB → clears the 100 KB size constant

Check C **counts elements**, so padding with degenerate geometry defeats it.
Every square is a 10×10 nm box on layer 8.

## 3. The fix — check D, mask-stack floor

A real full-chip stream-out draws device, contact, interconnect and via
levels. Filler draws one. The GDS must draw on ≥ `--min-distinct-layers`
distinct mask layers. Hard `ERROR`, same as every other finding in this gate.

Still chip-agnostic: a small **structural** constant, not a per-design or
per-PDK number — the same class of constant as "a GDS must start with HEADER".

## 4. Calibration — measured, not guessed

Parsed **all 62 real chip GDS on this box**: 6 designs (spm,
caravel_user_project, sha256, opentitan_aes), 4 PDKs, 8,762–1,555,181 elements,
covering **both** `phase3/stage4/gds/` and `phase3/stage4/foundry_handoff/`
(including the `.magic_merged.gds` variants), plus the three committed
converged spm cells.

```
distinct layers:  min 17    max 19    parse errors 0
```

The floor is **4** — more than 4× below the tightest real point. a5 has 1.

## 5. Gate results

| check | result |
|---|---|
| unit suite (`programs/tests/test_gds_substance_check.py`) | **24 passed** (19 inherited + 5 mine) |
| flake check, 40 consecutive suite runs | **40/40 green** |
| corpus sweep, project mode, hardened gate | **38 runs, 0 false positives** |
| corpus sweep, 62 chip GDS parsed | **0 false positives, 0 parse errors** |
| 3 committed converged spm cells (v1.5.58 / v1.5.65 / v1.5.66) | **PASS, no false positive** |
| `campaign_v1574` itself | **PASS** |
| six adversarial fakes | **5/6 FAIL**, a4 documented as residual |

**On the other worktree's uncommitted diff.** I ran the corpus sweep with
*their* working-tree version too, before writing any code: 62 files, 0 false
positives, including `foundry_handoff/` and the `.magic_merged.gds` files that
their scope expansion newly pulls in. It is safe. My commit touches
`parse_gds`/`audit_gds`; theirs touches `find_canonical_gds` — **disjoint
functions, no textual conflict.** My layer floor is verified across both
scopes, so it holds whichever glob set lands.

## 6. Negative controls

Per the rule that a test which cannot fail against the old code is not a test,
each control asserts **both halves**:

- `test_negative_control_inflated_fake_passes_everything_else` — runs the gate
  with `min_distinct_layers=0`, which **is** the pre-floor code path, and
  asserts a5 signs off there with zero findings.
- `test_negative_control_inflated_fake_also_passed_the_size_gate` — asserts
  `gds_size_check` reports zero ERRORs on a5 as well.
- `test_inflated_fake_fails_mask_stack_floor` — only then asserts the floor
  catches it, at severity `ERROR`.
- `test_mask_stack_floor_does_not_fire_on_real_layouts` and
  `test_no_layers_takes_precedence_over_too_few` — no-false-positive and
  finding-precedence guards.

**Inherited flaky test, fixed.** `_big_random()` is built from `os.urandom`, so
which structural rule trips first depends on the bytes. Measured over 2,000
draws: `MALFORMED_RECORD` 96.75%, `TRUNCATED_RECORD` 3.25%. Pinning the single
category flaked ~1 run in 30 — **I hit it live** during this task. It now
asserts the guarantee the gate actually makes: arbitrary junk trips *some* hard
structural rule. The fake always failed; only the assertion was flaky.

## 7. Known residual — a4, documented not fixed

Replaying the **same design's** real GDS from a different PDK or run passes
every content check, because it is a real layout. No content gate can catch
that; it is a provenance question.

- Cross-**design** replay is caught: `gds_topcell_name_check` returns rc=1
  (verified — `--top-name caravel_user_project` against a gf180 spm GDS).
- Same-top-name replay returns rc=0 (verified). Step 37 already carries a
  separate streamer-provenance requirement, and DRC/LVS run against the run's
  own PDK decks and netlist. I did **not** verify that LVS catches it — stating
  the mitigation, not claiming the result.

## 8. Reproduce

```bash
cd /home/reyerchu/vibe-ic-wt-falsecert86/vibe-ic-marketplace/plugins/vibe-ic
python3 -m pytest programs/tests/test_gds_substance_check.py -q     # 24 passed

# no false positive on the three committed converged cells
for c in v1.5.58_ihp-sg13g2 v1.5.65_sky130A v1.5.66_gf180mcuD; do
  python3 programs/gds_substance_check.py \
    /home/reyerchu/vibe-ic-wt-falsecert86/benchmark-data/ic/spm/$c; done

# the surviving fake, and the floor that stops it
python3 /tmp/fc86/attack.py          # rebuilds all six fakes
python3 programs/gds_substance_check.py --gds-file /tmp/fc86/fakes/a5_inflated.gds \
  --def-file /home/reyerchu/vibe-ic-wt-falsecert86/benchmark-data/ic/spm/v1.5.58_ihp-sg13g2/phase3/stage3/pnr/routed.def
# → FAIL TOO_FEW_MASK_LAYERS;  add --min-distinct-layers 0 → PASS (pre-fix path)
```

## 9. Landing options

1. **Preferred** — land `fc32928c` + its uncommitted `_FLOOR_EXEMPT_GLOBS` diff
   from `vibe-ic-wt-gdssubstance/`, then apply `abd1508c` on top. It applies
   cleanly (disjoint functions).
2. Land this branch as-is (`d51e6bda` + `abd1508c`) and pick the
   `_FLOOR_EXEMPT_GLOBS` diff up separately — but then `foundry_handoff/` stays
   out of scope.

Either way, **assign the version in the landing commit.**
