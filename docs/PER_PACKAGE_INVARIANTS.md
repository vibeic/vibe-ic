# Per-package invariants — the rule lives in the directory it binds

## The gap this closes

The deepseek-harness source study
(`docs/research/2026-08-19-deepseek-harness-source-study.md`, authored in a
sibling change and not yet in this tree; every file:line below was re-read in
the clone) measured that harness at `99f6f02fe`: 54 top-level packages, 226
leaf packages, **219 `invariant.ts` files** — one beside each package, loaded next to the code
rather than imported by it, with failures attributed to the owning package.

Its verdict on us was two-sided. We are **AHEAD on enforcement**: their
`scripts/verify-package-invariants.ts` passes over an empty population
(`scripts/package-invariants.ts:38` discovers owners with a hardcoded depth-2
glob; zero owners means the loop body never runs and `:21` prints
`0 hand-owned package companion(s) conform.` and exits 0), whereas
`plugin_full_audit.py:29` already separates "could not look" (rc 2) from
"looked and found nothing" (rc 0). We are **BEHIND on locality**: our rules
live centrally — in `programs/*_check.py`, in `tools/ci/repo_hygiene_gates.sh`,
in skill documents — so a contributor editing `mcp-eda/src/lib/pnr_antenna.mjs`
cannot see the rule that binds it without going somewhere else and knowing to
look.

Nothing here moves a checker. The flat `programs/*.py` namespace stays flat,
because that flatness is what every one of our audits greps (D1/D2/D3,
`gate_discloses_denominator_check`, `checker_execution_wiring_audit`). What
lands is a *declaration* beside the code, and a gate that reads it.

## What a package is

A **package** is a directory that carries an `INVARIANTS.yaml`. Ownership of a
file is by **nearest declaring ancestor**: the tracked file `tools/ci/x.sh` is
owned by `tools/ci` if `tools/ci/INVARIANTS.yaml` exists, otherwise by the
nearest ancestor that has one, otherwise by nobody.

Nearest-ancestor is chosen over an explicit `owns:` list for one reason: it is
single-valued by construction, so "two packages claim one file" — the case
their `invariants/src/index.ts:140-142` has to throw on — cannot be expressed.
There is no second place for a scope to be stated and therefore no second place
for it to disagree.

Directory-as-package is not applied to the whole tree, and that is deliberate.
Measured on `74ac9fa78`, directories holding tracked files directly:

    programs/tests   2636      tools/ci     45      mcp-eda/test 32
    programs         1211      tools        62      ... then a tail of 4-15

A rule required of every directory would either be red on arrival across that
tail or would be shaped to fit it. Coverage is a ratchet instead: the registered
set is pinned in three places and can only GROW without a deliberate edit to the
enforcement code (see "What fails", rows 7-9).

## What a package declares

```yaml
package: tools/ci                 # must equal this file's own directory
invariants:
  - id: ci-worktree-snapshot-must-see-ignored-files   # globally unique
    rule: >                                           # prose the contributor reads
      A worktree snapshot taken to attribute leftovers must pass --ignored.
    applies_to: ["*.sh", "*.py"]  # package-relative globs; * does not cross /
    excludes: ["fixtures/*"]      # optional
    forbid: '<regex>'             # exactly one of forbid: / require:
    counterexample: |             # MANDATORY: text this rule must reject
      git status --porcelain -- benchmark-data
```

`counterexample` is mandatory, and it is the part that makes the declaration
self-proving rather than decorative. Consider the two polarities:

* A `require` rule that PASSES has matched its regex in **every** file of a
  non-empty population — so the population itself proves the regex matches real
  code, and the counterexample proves it can also say no.
* A `forbid` rule that PASSES has matched **nothing**. Zero matches is the
  healthy state for a prohibition, and it is *byte-identical to a typo in the
  regex*. Nothing in the population can distinguish them. The counterexample is
  the only evidence that the rule discriminates, so the checker re-proves it on
  every run and refuses a rule that does not reject its own counterexample.

This is the repo's own "an unmeasured thing reads as a measured zero", one level
up: the check that found nothing must show it was capable of finding something.

## Who reads it

1. **The contributor**, because it is in the directory they already have open.
   That is the entire point of the port; if only the gate ever read it, a
   central rule would be strictly better.
2. **`programs/package_invariants_check.py`**, wired into
   `tools/ci/repo_hygiene_gates.sh` — the one list that both CI workflows and
   `gatekeeper_review` invoke. A violation is a red landing gate, not advice.
   No `gate_scope` is declared, so the gate runs on every change
   (`_gate_dispatch.sh`, "NARROWING IS OPT-IN … a gate with no `gate_scope`
   line ALWAYS runs").
3. **`programs/tests/test_package_invariants_check.py`**, which pins the
   registered set and drives the checker against synthetic trees.

The gate wiring is not optional decoration, and it is the reason this change
touches a protected path at all. Two things were measured on `44964cff2`:

* `checker_execution_wiring_audit` — itself a blocking gate in the same list —
  FAILS a checker that only its own test runs, and it is right to: a suite-only
  checker never sees a production file.
* The targeted suite cannot substitute for it. A synthetic PR that changes ONE
  file, `tools/ci/install_hooks.sh`, and violates
  `ci-worktree-snapshot-must-see-ignored-files` in it selects **18 tests, and
  `test_package_invariants_check.py` is not one of them** —
  `ci_targeted_test_select` is plugin-scoped by construction, so nothing under
  `tools/` reaches a selection. The gate catches that same PR at rc 1. Wired
  only to the suite, this checker would be blind to the package whose rules it
  carries the most of.

## What fails

| # | Condition | Verdict |
|---|---|---|
| 1 | an owned file violates a declared invariant | FAIL, attributed `package: id` at `file:line` |
| 2 | an invariant's population is ZERO files | FAIL — VACUOUS |
| 3 | an invariant does not reject its own `counterexample` | FAIL — TOOTHLESS |
| 4 | `package:` disagrees with the declaration's own directory | FAIL |
| 5 | an `id` is reused across packages | FAIL |
| 6 | a declaration is malformed (missing key, both/neither of require+forbid, uncompilable regex) | FAIL |
| 7 | a REGISTERED package has no `INVARIANTS.yaml` | FAIL — MISSING |
| 8 | an `INVARIANTS.yaml` exists that the registry does not name | FAIL — UNREGISTERED |
| 9 | the registry names fewer packages than `MIN_REGISTERED_PACKAGES` | FAIL — RATCHET |
| 10 | no git index, unreadable registry, or zero declarations discovered | **rc 2 NOT CHECKED**, never PASS |

Rows 7-9 are the half that matters most: *a missing invariant must not read as
"no constraints".* Row 7 alone is not enough, because the registry row
can be deleted with the file. Three things stand behind it, and they are
deliberately in three different kinds of artefact:

* the registry `programs/package_invariants_registry.json`, which lives OUTSIDE
  every declared package, so deleting a package's own directory cannot delete
  the record that it owes a declaration;
* `MIN_REGISTERED_PACKAGES` in the checker source, so *shrinking* the registry
  is a refusal until someone edits the enforcement code itself — and editing
  that file is what makes `ci_targeted_test_select` select its test;
* `REGISTERED_PACKAGES` in that test, which pins the exact set.

**The residual, stated rather than implied:** an author willing to make all
three edits in one change can retire a package silently. Nothing makes a
register unforgeable against someone who edits every copy of it. What the
three-way pin buys is that the last edit is in enforcement code and the one
before it lowers a floor — both of which a reviewer reading a diff will see.

## Row 10 is the one their gate gets wrong

`verify-package-invariants.ts` cannot tell a moved corpus from a clean one:
empty root gives 0 owners gives exit 0. Here, discovery of zero declarations is
rc 2 and prints `NOT CHECKED`, and the gate is wired with plain `run` rather
than `run_tolerating_uncheckable`, so rc 2 fails the suite. A run that could not
run is not a pass.

## Rule selection: what shipped and what was rejected

A candidate rule must **hold over its whole population on day one**, or the gate
is red on arrival and gets routed around. Each of the nine below was measured
against `74ac9fa78` before it was written down, and each was then reverted in a
scratch tree to confirm the gate goes red — a guard never seen to fail has not
been shown to check anything.

Rejected, and why:

* `set -euo pipefail` in `tools/ci/*.sh` — 3 of 11 carry it. Does not hold, and
  could not be made to hold without editing eight scripts in a change that is
  about something else.
* every `commands/*.md` cites `_anti_fabrication_rules.md` — 5 of 7 (a
  different candidate for the same package than the one that shipped).
  `vibe-ic-benchmark.md` and `vibe-ic-phase1.md` do not. Fixable, but fixing two
  documents to make a new rule green is shaping the population to the rule.
* `hooks/*.sh` never exits non-zero — 4 of 5. `phase23_claim_validator.sh` exits
  2 *on purpose* (`:210`, `:268`): for a Stop hook, 2 is the documented way to
  block turn-end. The rule was wrong, not the file.
* no `except ...: pass` in `tools/ci/*.py` — 8 of 29 have one, including
  `hermetic_candidate_runner.py` and `landing_completion_record.py`. It does not
  hold, and the reason it does not is that swallowing is sometimes the right
  call in cleanup paths; a rule that has to argue with eight existing decisions
  is a style preference wearing a gate's clothes.

One measurement changed a rule rather than rejecting it. `execSync(` appears in
`mcp-eda/src/lib/shell_safety.mjs:5` — inside the `//` comment block that
explains the injection it exists to prevent. A rule that fires on the
documentation of a hazard is a rule people delete. Every regex that shipped is
therefore anchored with `(?m)^(?![ \t]*(?:#|//))` so it reads code lines and not
comment lines, which is also why the `tools/ci` rule can cover `*.py` — where
`git status --porcelain` appears only in a comment — instead of being scoped to
`*.sh` to dodge it.

## Proved, not asserted

Measured in the container against this branch; the gate's own disclosure line is
`7 package(s), 9 invariant(s), 111 owned file(s), 112 file-rule pair(s)
examined, out of 4765 tracked`.

* **Green on arrival.** `rc 0` on the unmodified tree.
* **Every one of the nine fires.** Each rule was violated once, in isolation, in
  a scratch worktree — `rc 1`, one finding, attributed to the owning package and
  the exact `file:line`.
* **A deleted declaration fails.** `git rm tools/ci/INVARIANTS.yaml` → `rc 1`,
  `MISSING`, even though every remaining rule still passed.
* **Deleting the registry row too still fails.** → `rc 1`, `RATCHET`.
* **A typo'd regex fails.** `shell=True` → `shelll=True` in the declaration →
  `rc 1`, `TOOTHLESS`, before any file is read.
* **Six negative controls on the checker itself.** Removing the TOOTHLESS check,
  the MISSING check, the RATCHET, the VACUOUS check, or the per-file scan, and
  downgrading rc 2 to rc 0, each turns the corresponding test(s) red. The
  9-case mutation arm dies with the scan, which is what makes it evidence
  rather than decoration.

## What shipped

Seven packages, nine invariants.

| Package | id | polarity | population |
|---|---|---|---|
| `tools/ci` | `ci-worktree-snapshot-must-see-ignored-files` | forbid | 40 |
| `tools/ci` | `ci-no-shell-interpolated-subprocess` | forbid | 29 |
| `.../mcp-eda/src/lib` | `mcp-lib-builds-no-shell-command-from-a-string` | forbid | 5 |
| `.../hooks` | `hooks-do-not-mutate-the-users-repository` | forbid | 5 |
| `.../hooks` | `hooks-do-not-reach-the-network` | forbid | 5 |
| `.../programs/gds_antenna` | `antenna-geometry-check-stays-independent-of-the-router` | forbid | 2 |
| `tools/phase1_engine` | `phase1-engine-reads-only-the-design-input` | forbid | 10 |
| `.../_shared` | `shared-harness-names-no-individual-skill` | forbid | 10 |
| `.../commands` | `command-documents-declare-a-description` | require | 6 |

Two of them are worth naming for what they encode, because neither is a lint
rule any general tool could infer:

`antenna-geometry-check-stays-independent-of-the-router` says
`gds_antenna/antenna_check.py` may not parse the OpenROAD antenna report. The
package exists to produce a **second, independent** number against the router's
own count (`antenna_check.py:12-17`); a well-meant change that reads the report
to "reconcile" the two would leave both gates green while silently collapsing
the second opinion into a copy of the first. `xcheck_router.py` is excluded
because reading that report is its entire job — the exclusion names a role
stated in the package, not the file that happened to fail.

`phase1-engine-reads-only-the-design-input` is §4.05 — read only the design
INPUT, never the oracle, harness, or golden — enforced in the directory that
does the ingesting, rather than in a doctrine document the ingesting code never
loads.
