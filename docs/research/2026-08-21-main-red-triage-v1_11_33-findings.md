# findings — agent `ptmo`, RUN 4: re-triage against the NEW main

host 8hd-3 · 2026-08-21

## M0 — THE BRIEF'S PREMISE DOES NOT HOLD ON THE REMOTE, MEASURED THREE WAYS

I was told: my work landed as v1.11.40 and v1.11.46, and `origin/main` is now
v1.11.47, ~30 versions past my subject. **None of that is visible from here.**

**1. The authoritative remote head is v1.11.33, not v1.11.47.**

```
git ls-remote origin refs/heads/main
  e36d81c0a39dfa2ac496c4f683e7a21fb4fbf075   refs/heads/main
git log -1 --oneline e36d81c0a
  e36d81c0a landing(ACTIVATE): wire what the fourteen lanes shipped, and redden
            the one clause that could not go red [v1.11.33]
```

`ls-remote`, not the local tracking ref — the tracking ref agrees with it, so
this is not the stale-ref trap.

**2. Both my branches are still exactly where I pushed them — unmerged.**

```
git ls-remote origin refs/heads/ptmo/main-92-red-triage
  2b230dce32d67484a901f3845e11d1e4b3cb66d6     (= my last push, byte-identical)
git ls-remote origin refs/heads/ptmo/pytest-timeout-image-suite-agreement
  fc5a19353e5073d0324e0ab270eb22dcdc539368     (= my last push, byte-identical)
git merge-base --is-ancestor <each> origin/main   -> NO, for all three of my commits
```

**3. Nothing on this host, on any ref, mentions v1.11.40 / v1.11.46 / v1.11.47.**

```
git log --all --oneline | grep -oE '\[v1\.11\.[0-9]+\]' | sort -t. -k3 -n | tail -3
  [v1.11.31]  [v1.11.32]  [v1.11.33]
```
The operator's own checkout `/home/reyerchu/vibe-ic` has `main` at `f6db3e921`,
older still. Only one remote is configured in either checkout
(`https://github.com/vibeic/vibe-ic.git`), so there is no second destination I
am failing to look at.

### What I conclude, and what I do NOT

I do **not** conclude the landings did not happen — they may exist on a machine I
cannot see, or be committed locally somewhere and not yet pushed. What I can say
is that **as of this measurement they are not on `github.com/vibeic/vibe-ic`,
and my branches are not ancestors of its `main`.** If they landed, they landed
somewhere else, and the SHAs quoted back to me are not resolvable here.

### What I therefore measure against

**`e36d81c0a` (v1.11.33)** — which IS a genuinely newer main than my last
subject `867de4289` (v1.11.18): **16 commits, 15 versions.** Not 30, and not
v1.11.47, but real. The re-triage below is against that.

One thing that HAS landed and matters: `bb90724dc` — the old
`origin/land/ppa-tf` head — is now an ancestor of main. **The fourteen PPA lanes
are in.** So the ppa-tf A/B I ran last night is no longer a comparison against a
side branch; it is a comparison against history.

# ===== THE WHY, SETTLED AGAINST THE NEW MAIN — it is the SECOND, not the third =====

Three options were put to me: the verdict is **(1) collected but never made
fatal**, **(2) the lane is invoked from a path those landings did not take**, or
**(3) the landings bypassed it with `--no-verify`**.

## (1) EXCLUDED — the verdict is collected AND fatal, on the new main too

`tools/gatekeeper-land.sh` @ `e36d81c0a` has 19 `FAILED=1` sites; the targeted
arm's failure branch is one of them, and the script ends `exit "$FAILED"`. On
failure it does the opposite of authorising:

```
rm -f "$(git rev-parse --absolute-git-dir)/gatekeeper-stamp"
echo "=== FAILURES ABOVE — stamp removed; the pre-push hook will refuse ==="
```

## (3) EXCLUDED — there is no hook on this host to bypass

`--no-verify` skips a hook. Re-measured NOW, not carried over from last night:

```
ls /home/reyerchu/vibe-ic/.git/hooks/ | grep -vc '\.sample$'   -> 0
git config --get core.hooksPath        (repo)                  -> UNSET
git config --global --get core.hooksPath                       -> UNSET
find /home/reyerchu -maxdepth 6 -path '*/.git/hooks/*' -type f -not -name '*.sample'
                                                               -> (nothing, anywhere)
find /home/reyerchu/vibe-ic/.git/worktrees -name gatekeeper-stamp
                                                               -> (nothing)
```

**No installed git hook exists anywhere on this host at depth ≤ 6, in any repo,
and no worktree has ever carried a gatekeeper stamp.** `--no-verify` cannot be
the cause of an escape past a gate that was never armed. Scoped honestly: I
measured THIS host. If the landings were made from a machine I cannot see, and
that machine has the hook installed, then (3) is live there and I cannot see it.

## (2) IS THE ANSWER — every invocation path leads back to a human or to a merge

`gatekeeper-land.sh` is reached by exactly three routes:

| route | does a direct-push landing take it? |
|---|---|
| a human types `tools/gatekeeper-land.sh` | only if they choose to |
| the pre-push hook's stamp requirement forces the above | **no — the hook is not installed** |
| `tools/gatekeeper-verify-merge.sh`, the PR-merge path | **no — these are direct pushes** |

and there is no server-side backstop:

```
ls -d .github/workflows            -> No such file or directory
ls .github/workflows-disabled      -> ci.yml.disabled  gatekeeper-ci.yml.disabled
crontab -l | grep -i gatekeeper    -> (nothing)
```

The hook's own first line already says what this means: *"pre-push — the ONLY
enforced gate on what reaches `main`, by necessity … Actions is disabled at the
ACCOUNT level … So the checks CI would enforce are enforced HERE or nowhere."*
With the hook absent, "or nowhere" is the operative half.

**So the lane IS invoked — from a path a direct-push landing does not take.**
That is option (2), word for word.

## A CORRECTION TO MY OWN ANSWER LAST NIGHT

Last night I labelled this **(c) "run, fatal, and bypassed"** and then, in the
same section, wrote that there was no hook to bypass and the proximate cause was
a missing install. **The mechanism I described was right; the label was wrong.**
Against this brief's phrasing the accurate label is **(2)**, and the difference
matters here rather than being pedantry: (3) would put the finding on the person
who typed the flag, and the measurement does not support that.

## M0b — I CONTAMINATED THE OPERATOR'S CHECKOUT TWICE, and cleaned it up

The shell trap `cd X && CMD &` backgrounds the WHOLE `cd X && CMD` list, so the
foreground shell never leaves its original cwd — which here is
`/home/reyerchu/vibe-ic`, the operator's landing checkout. Two of my writes
landed there instead of in my private path:

```
/home/reyerchu/vibe-ic/refresher.pid    (48 bytes, my refresher PIDs)
/home/reyerchu/vibe-ic/findings92.md    (1077 bytes, one section of my log)
```

Both removed. `git -C /home/reyerchu/vibe-ic status --porcelain` is now byte-for-byte
the set that was there when this session started (`AES-THRASHED`, `AGENTS.md`
and five untracked `test_*.py` — none of them mine).

**The findings92.md fragment was NOT a duplicate.** `grep -c` against my private
copy returned 0, so deleting it blind would have LOST the PASS-3 section. It was
copied to `rescued_fragment.md` first and folded back into the private log.

Recorded because it is the same class as the harness defects in the last run: a
silent write to the wrong place, caught only because I looked. It also
IMPLICATES ONE OF MY OWN EARLIER READINGS — the `ls out147/image/*.xml | wc -l`
that returned `0` right after the files existed was the same trap, not a
vanished measurement.

## M1 — Phase A: the old 92 re-run against `e36d81c0a` (v1.11.33), both lanes

Same shape as before: pristine clone, all 32 files still present on the new main,
one pytest session per file, no xdist, image lane =
`ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2...d01ff` with `--skip` first and
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`; host lane with `-p no:pytest_ethereum`.
Published incrementally to `TRIAGE147.md`, refreshed every 45 s.

Buckets carry a fifth value this time, **CLOSED** — green in BOTH lanes on the
new main, i.e. fixed by the last 15 versions.

Known load-driven flakes are annotated rather than reported as findings: a
single-shot lane difference on `test_a_pinless_abstract_is_never_staged`
(image 4/13, host 13/13 at v1.11.18) or on
`test_live_collection_relays_finite_semantic_progress_past_old_bound`
(image 1/10, host 0/10) is expected noise. Publishing either as a fresh
HOST-ONLY would mislead exactly the readers this table exists for.

## M2 — Phase B, prepared: where a NEW red would come from

A full re-derivation of the failing set on the new main would mean the targeted
selection for the 16 commits, which is **962 test files** — effectively a third
of the suite, and the brief forbids running the whole suite on this host
(measured at load 276 with 0 free memory). So Phase B is bounded to the highest-
yield subset and its limits are stated rather than hidden:

```
git diff --name-only 867de4289..e36d81c0a                       -> 129 files
  ...of which test files changed or ADDED                       ->  39
  ...programs ADDED                                             ->  69
```

The 39 changed/added test files are Phase B (whole file each, not a selection);
37 of them are the new `test_ppa_*` family that arrived with the fourteen PPA
lanes. The 69 added programs move the ratchet-style counters — inventory drift,
atomic-write, prose polarity, checker wiring — and those gates are ALREADY in
the old 92, so Phase A covers them.

**NOT MEASURED, stated plainly:** the remaining ~920 targeted files. A test that
was green at v1.11.18, is untouched by the 16 commits, and went red for an
indirect reason would not be caught by either arm. That is the gap in this
number and I am not going to pretend otherwise.

# ===== jlandpar's mechanism: I CONFIRM THE FACT, and DIFFER ON WHAT IT EXPLAINS =====

jlandpar reports: the verdict IS produced, and a `max_commits` deadline that
would fail a persistent red is in the schema and nothing ever opens it.

## Where I confirm it — independently, and I had not looked here

The deadline is real and I had not read this file. Measured at `e36d81c0a`:

```
tools/ci/gate_red_since.json
  "acknowledged": []          <-- EMPTY. No row has ever been opened.
  fields: gate | since | max_commits | owner | why
```

`programs/gate_red_since_check.py` adjudicates it and IS wired — into
`programs/gatekeeper_review.py::gate_red_since` (the only production caller;
`ci_targeted_test_select.py` merely names it). So: mechanism present, ledger
empty, no row ever opened. **jlandpar's fact is correct and I confirm it.**

I also confirm the two exclusions from my own side: not `--no-verify` (no
installed hook exists anywhere on this host at depth <= 6), and not selection
(17 matrix test files were in the targeted selection for `7fcbc7397`).

## Where I differ — the unarmed deadline cannot be what let 1.6x through

Three reasons, all from the program's own text and all checkable:

**1. An unacknowledged red is ALREADY fatal, by this program's explicit design.**
`gate_red_since_check.py`, "WHAT IS REPORTED BUT DOES NOT FAIL":

> "A NEW red is not failed HERE **because the suite has already failed it** —
> reporting it twice would say nothing extra."

and, in "the one thing it refuses to do":

> "the hygiene suite still exits 1 for every FAIL, exactly as before. A ledger
> row grants NO leniency to the gate it names … **It can only ever ADD a
> failure. It cannot turn a red gate green.**"

An empty ledger is therefore the TIDY state, not a hole: every red is NEW, and
every NEW red is already fatal. A register that can only add failures cannot,
by being empty, subtract one. **Arming the deadline would not have changed the
1.6x outcome.**

**2. The hygiene rc is fatal on the landing path, so "already failed it" is true
here and not just in theory.** `gatekeeper-land.sh:957` invokes the suite through
`run "full:repo-hygiene" …`, and the surrounding comment states the rule the
helper implements: *"`run` treats any non-zero as FAIL … 'I could not measure'
must never reach the stamp as 'I measured and it was clean'."*

**3. DOMAIN MISMATCH — this ledger never covered the 1.6x reds at all.**
`gate_red_since.json` is keyed by *"the gate's label EXACTLY as
`tools/ci/_gate_dispatch.sh` records it"* — hygiene-suite gate labels. The 1.6x
reds are **pytest test IDs in the targeted-test arm**:

```
grep -cv '^programs/tests/test_.*::' out92/all92.txt   ->  0
```

All 92 are pytest node ids; not one is a dispatcher gate label. The red-since
ledger is a different lane, so no row in it — armed or not — would ever have
been about `assert 69 == 68`.

## So the mechanism I measure is still: the verdict was never PRODUCED

For those landings the fatal verdict does not exist to be adjudicated. Every
route that produces it was untaken: a human typing `gatekeeper-land.sh`; the
pre-push hook's stamp requirement forcing that (no hook installed anywhere on
this host, `core.hooksPath` unset repo-wide and globally, no worktree has ever
carried a stamp); or `gatekeeper-verify-merge.sh` on a PR merge (these were
direct pushes). No `.github/workflows`, no crontab entry.

**Two mechanisms, both real, answering different questions.** jlandpar's answers
"why does a red that IS produced stay red forever with nobody on the hook for
it" — a genuine durability gap, worth closing on its own merits, and there are
~72 persistent hygiene reds with no owner and no clock. Mine answers "why was a
red never produced for these five commits". The 1.6x escape is the second.

## One correction to the record while I was in there

`gate_red_since_check.py`'s docstring describes `_hygiene_verdict` as folding
NOT_CHECKED into prose and *"returning rc 0 regardless"*. That is the state
**MEASURED 2026-08-12** and it has since been CLOSED: the live function carries
`# vibe-ic#584 — the three keys that make NOT_CHECKED load-bearing HERE and not
only in the script's exit code. Before this, `not_checked` reached the … and
this function returned rc 0, i.e. MERGE_OK.` So the (1)-shaped hole that
docstring was written against is not open today. Anyone quoting that paragraph
as current would be quoting history.

## M3 — Phase A, 72/92: NOTHING HAS CLOSED

```
CLOSED          0
BOTH           70      red in BOTH lanes on the new main
FLAKY-KNOWN     2      the two annotated flakes, neither a finding
NOT_MEASURED   20      image lane still running the expensive matrix files
IMAGE-ONLY      0
HOST-ONLY       0
```

**Fifteen versions landed and, of the 72 old IDs measured so far, not one is
fixed.** Including the whole `1.6x` cluster: `test_matrix_63x8_census_freshness`,
the ledger, the mutation ledger and the d1..d8 dimensions are all still red in
both lanes, so step `1.6x` still has no 63x8 rows.

### A correction I made to my own bucketer mid-run

At 60/92 the table said `CLOSED 1`. The one ID was
`test_live_collection_relays_finite_semantic_progress_past_old_bound` — the
0.3 s-lease flake I measured at **image 1/10, host 0/10** at v1.11.18. A known
flake coming up green is NOT a closure, and `CLOSED 1` would have been reporting
noise as a result — the single most misleading number I could have published,
because "one of your reds is fixed" is exactly what a reader would act on.

The bucketer now routes a known flake to `FLAKY-KNOWN` whether it lands
IMAGE-ONLY, HOST-ONLY **or CLOSED**. Same rule as before, one more outcome:
a flake's colour is never evidence, in either direction.

## M4 — PHASE A COMPLETE: 92/92, and ZERO closures

```
image lane 32/32 files   host lane 32/32 files   NOT_MEASURED 0

   CLOSED          0
   BOTH           90
   FLAKY-KNOWN     2      (test_a_pinless_abstract_is_never_staged;
                           test_live_collection_relays_..._past_old_bound)
   IMAGE-ONLY      0
   HOST-ONLY       0
```

**Fifteen versions, zero of the 92 fixed.** The whole `1.6x` cluster is still red
in both lanes — `test_matrix_63x8_census_freshness`, `..._ledger`,
`test_matrix_mutation_ledger` and every `test_matrix_d1..d8`. Step `1.6x` still
has no 63x8 rows at v1.11.33.

The four-way shape is unchanged from v1.11.18: **IMAGE-ONLY 0, HOST-ONLY 0** —
these are properties of main, not of this host, and that conclusion now rests on
two independent measurements fifteen versions apart.

This is also, quietly, a second confirmation of the WHY: fifteen more versions
landed ON TOP of 90 reds without any of them being closed or blocking anything.
A red that cannot stop a landing is a red that accumulates, and 90 of them have.

## M5 — PHASE B COMPLETE: no new red from the 16 commits' own tests

The 39 test files changed or ADDED by `867de4289..e36d81c0a`, whole file, both
lanes:

```
image : 39/39 files, 1203 cases, 1 red
host  : 39/39 files, 1203 cases, 1 red
        BOTH 1 · IMAGE-ONLY 0 · HOST-ONLY 0

already in the 92 (1): test_matrix_d2_falsifiable.py::test_d2_gate_has_a_reachable_fail[step1.6x]
GENUINELY NEW       (0): none
```

The one red is the `1.6x` cluster again. **The fourteen PPA lanes' own 37 new
test files are green in both lanes** — 1203 cases and not one new failure.

# ================== THE CURRENT NUMBER ==================

```
                       at v1.11.18        at v1.11.33 (e36d81c0a)
  red test IDs              92                    92
    closed since             —                     0
    newly red                —                     0   (within Phase B's scope)
  IMAGE-ONLY                 0                     0
  HOST-ONLY                  0                     0
  FLAKY (annotated)          2                     2
```

**The number is unchanged: 92.** Fifteen versions landed, none of the 92 closed,
and the new work added none of its own.

### The scope of "0 newly red", stated rather than implied

Phase B covered the **39 test files the 16 commits touched**, plus Phase A's 32.
It did NOT cover the other ~920 files in the targeted selection for that range.
A test that was green at v1.11.18, is untouched by these commits, and went red
for an INDIRECT reason would not be caught by either arm. Running all 962 was
refused deliberately: the brief forbids the whole suite on this host (measured
at load 276, 0 free memory), and 962 is a third of it.

What makes that residual risk small rather than unknown: the 16 commits ADDED 69
programs, and the gates that react to added programs — inventory drift,
atomic-write ratchet, prose polarity, checker wiring — are ALL already inside
the 92 and were all re-measured in Phase A. The indirect blast radius of "new
programs arrived" is therefore measured; what is unmeasured is a subtler
coupling nobody has named.
