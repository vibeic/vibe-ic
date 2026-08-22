# HANDOFF → Repo Gatekeeper / Flow Gatekeeper

**NOT PUSHED. Prepared for the gatekeeper role to land. 2026-07-25.**

Post-release, all pushes to `origin/main` go through the gatekeeper role. This
change is verified and gate-clean but deliberately left unpushed.

---

## 1. Where it is

| | |
|---|---|
| Worktree | `/home/reyerchu/vibe-ic-wt-sha256mcr` |
| Branch | `sha256mcr-land` |
| Commit | `cf64d2f82` |
| Rebased on | `0d2c63d34` (origin/main at time of verification) |
| Fast-forward safe | yes (merge-base == origin/main tip) |

## 2. VERSION — RE-ASSIGN AT LAND TIME. DO NOT ASSUME 1.5.79 IS FREE.

The commit currently carries **1.5.78 → 1.5.79**.

**Collision history — this already happened once today.** I originally assigned
**1.5.78**; while I was verifying, `e6120d7e9` landed on `origin/main` and took
1.5.78. My rebase then silently ABSORBED my version bump, leaving the commit
with *no* bump at all — a user-facing behaviour change that would have shipped
unversioned had I not re-checked. I re-assigned to 1.5.79.

The same race can happen again between now and land. **Re-run
`gatekeeper_assign_version.py --repo . --write` at land time** and update the
commit subject (`v1.5.79 — …`) to match whatever it assigns. Do not trust the
number baked in here.

## 3. What the change does, and why

The phase-3 synth netlist cache was keyed on the **PDK alone**:
`_netlist_matches_liberty` sniff-checks the cached netlist's cell masters
against the active liberty, which validates PDK provenance but has **no notion
of whether the RTL changed**. So "edit RTL → re-run" reused the previous
netlist: the flow placed-and-routed the PREVIOUS design and reported a clean
PASS for RTL it had never synthesised. Measured proof — two full phase-3 runs on
two different RTL revisions:

    run          RTL md5         netlist md5     SHIP_WNS_POSTROUTE
    2-cycle      7af1a9fa6876    7aab999ecf6d    -2.519266644380789
    carry-split  ac257c7df3d4    7aab999ecf6d    -2.519266644380789
                 ^^ different    ^^ IDENTICAL    ^^ identical to 16 s.f.

Two different RTL files produced a byte-identical netlist and a post-route
number agreeing to **16 significant figures** — a precise, confident,
meaningless number produced by a full sign-off flow for RTL it never read.
`_stale_rtl_vs_netlist()` now compares the cached netlist against the staged RTL
mtimes and **fails closed** (unreadable mtime ⇒ re-synthesise).

**RETRACTION, carried in the commit message:** this defect makes every
RTL-level convergence experiment run through this flow unmeasurable. Any prior
conclusion of the form *"I changed the RTL and nothing improved"* produced under
the PDK-only cache is not evidence of anything. **My own multi-cycle-round
measurements from earlier today are retracted on exactly this basis.** Other
in-flight RTL work on this fleet may be affected — that is why this is worth
landing promptly.

The commit ALSO records a **negative result that is deliberately NOT applied**:
`abc -D` is inert on the non-`-constr` path (proven — byte-identical netlist),
but *binding* it via `-sizing -area_recover` improved pre-PnR delay 22% and made
the shipped corner **1.87 ns WORSE** (post-route SS −2.519 → −4.386, +4.6%
cells, +4.3% GDS). **The runner's abc invocation is byte-for-byte unchanged**;
what ships is the corrected comment (the old one asserted a falsehood), the
counter-evidence at the lever, and a test that fires if anyone re-enables it
without a fresh post-route A/B.

## 4. Verification

**Full suite, NO deselection** (the `func_src` collection blocker was fixed
upstream by `e6120d7e9`, so this is a genuine full run):

| | failed | passed | collection errors |
|---|---|---|---|
| pristine `0d2c63d34` | 55 | 18444 | 0 |
| this change | 55 | 18474 | 0 |

- **NEW failures introduced: none** (`comm -13` empty)
- **Failures only in baseline: none** (`comm -23` empty)
- +30 passed = exactly the new tests added here
- The 55 are pre-existing on pristine main (`yosys`/`iverilog`-absent host)

**`gatekeeper_review --role core-agent --base origin/main --head HEAD`:
`MERGE_OK`** — 12/12 machine gates PASS, incl. scope guard, version-bump
monotonic + marketplace sync, chip-agnostic, NDA diff scan, stale-branch
(FRESH), path portability, loop watchdog, plugin_full_audit.

**Step-2.7 §4.05 adversarial (re-run on final commit):**
- design-name occurrences in runner diff: **0**
- branches on design identity: **0**
- runner abc invocation changed vs origin/main: **0** (behaviour unchanged)
- each fix's test provably fails on pre-fix code (negative controls run)

## 5. Files

    programs/phase3_one_shot_runner.py            (cache fix + corrected comment)
    programs/iterative_recurrence_timing_diagnosis.py   (new)
    programs/INDEX.md                             (regenerated, 919 programs)
    programs/tests/test_synth_netlist_cache_rtl_freshness.py      (new)
    programs/tests/test_abc_delay_target_not_naively_enabled.py   (new)
    programs/tests/test_iterative_recurrence_timing_diagnosis.py  (new)
    skills/sta-review/SKILL.md                    (capture)
    .claude-plugin/* , vibe-ic-marketplace/.claude-plugin/*        (version)

Note: `vibe-ic-marketplace/scratch_geom_signoff_tests/` is an untracked
**pre-existing test side-effect** (a test writes into the repo root). It is NOT
part of this change and was deliberately not staged.

## 6. Driving task outcome — no convergence claimed

sha256 × sky130A **does not converge**: post-route SS WNS **−2.519 ns** against
the HARD 25.907 ns period. `abc` dretime byte-identical (loop-bound);
restructuring worse (+26% area); delay-driven mapping worse (−4.386). The
multi-cycle RTL variants are **functionally verified only** (NIST vectors 100%,
300/300 random blocks bit-identical to the reference) and were **never validly
timed** because of the cache defect above. No fix is claimed for that cell.
