# jverify — independent verification of the two capture-distillation branches

**Host** 8hd-3 · **date** 2026-08-22 · **agent** `jverify`

**Standing:** an independent read of `origin/jdistmat/matrix-distil` and
`origin/capture/jdistchip-chip-path-rules`, asked for by the person about to land
them. The brief's hard rules were: report only, do not push to `main`, do not bump
the version, do not edit either verified branch. **All three hold.** This document
was later pushed on a branch of its own, on the requester's explicit instruction,
so that the report has a home other than `/tmp` — it adds this one file and
nothing else, and neither `main` nor either verified branch was touched.

**Verdicts** — `jdistmat` LAND with F14 + F15 + F9 + F12 fixed;
`jdistchip` LAND with F1 fixed. F14 is the only finding that stops anything.


## ACT ON THIS — the whole answer in one screen. Evidence for every line is below.

```text
  origin/jdistmat/matrix-distil  @ facc28860   >> LAND WITH FOUR THINGS FIXED
  origin/capture/jdistchip-...   @ c0e19ace9   >> LAND WITH ONE THING FIXED

  Neither is blocked by the other any more. The four-filename collision that
  made them mutually unlandable (F13) was ruled on by the author and I verified
  the resolution by blob hash. jdistmat has since merged main and now merges
  back with ZERO conflicts; jdistchip still has four generated count files to
  re-render, and so will whichever branch lands second.

  jdistmat, in the order the fixes matter:
    F14  THE ONLY FINDING THAT STOPS ANYTHING. It fails the repository's own
         landing-gate suite: atomic_artifact_write_check, wired at
         repo_hygiene_gates.sh:1795 where rc 1 fails. 20 of jdistmat's own new
         programs write their `--json` non-atomically.
         VERDICT VALIDATED END TO END, not asserted. I converted all 20 in a
         throwaway worktree: the gate goes rc 1 -> rc 0, the 28 wired landing
         invocations become IDENTICAL TO MAIN, and — the only evidence here
         that touches the converted code — all 20 run with `--json` pre and
         post with identical rc and BYTE-IDENTICAL artefacts. Do NOT rely on
         the suite being green: it is (233 tests at today's tip) and it stays
         green on a conversion applied WRONGLY — see F17. Use the repo's
         `from _atomic_artefact import write_text as atomic_write_text` idiom:
         these sites write TEXT, not the `write_json` I first named. A bare
         import leaves the name unresolved and degrades the program to rc 2,
         so verify the IMPORT landed and not just the string, and COMMIT
         before running the suite:
         policy_direction_pin_check returns an untolerated rc 2 against a dirty
         checkout. Do NOT register the 20 instead: the gate permits it, the
         suite refuses it.
    F15  A new gate ships RED on a verdict that is FALSE, with a test pinning
         the false red. Its scan root is `programs/`; the producers it says do
         not exist are real and live one directory outside it. REMEDY TESTED:
         two parts — widen the root, and define the producer by what it EMITS —
         together take the gate to rc 0. Careful with the second: a substring
         test for the schema id re-admits the CONSUMER and breaks two
         discrimination tests. The predicate is "writes metric records".
         I BUILT IT on 2026-08-22 and it is worse than this line says — see
         F15+ below: THREE tests encode the false verdict, one of which no
         passing tree can satisfy.
    F9   A gate's docstring claims a predicate its code does not have: 31 live
         sites of its own class are invisible to it, and its PASS line asserts
         something untrue of this tree. REMEDY TESTED: ~60 lines takes findings
         10 -> 50 and inventory keys 8 -> 31, and its shipped-tree test then
         fails for the right reason. Budget the 23 new rows, or fix the sites.
         (Published as 96/52 and corrected downward on 2026-08-22 — the 96
         double-counted sites in nested functions. Half the price I quoted.)
    F12  THREE of its sixteen non-census gates answer PASS on an empty scan,
         where all twelve of the sibling branch refuse. CORRECTED DOWNWARD on
         2026-08-22 from "nine of fourteen" — the nine came from driving the
         gates BARE, which this report's own warning says not to do; under the
         `--root` form they accept, thirteen of the sixteen refuse correctly.
         See the CORRECTION in F12. NOT a mechanical fix — I tried it; the
         branch's own tests distinguish "no corpus" from "a corpus with nothing
         of this kind in it", and only the first should refuse.
    F17  Nineteen of its twenty checkers ship a `--json` artefact path that no
         test exercises — proved by breaking one and watching 33 tests pass. Not
         blocking, but it means the F14 remedy above lands untested unless the
         person applying it runs the twenty with `--json` themselves. jdistchip
         has no such gap: none of its twelve writes an artefact, which is also
         why F14 does not touch it.
    F15+ Its blocking finding is worse than recorded: THREE of the gate's eight
         tests encode the false verdict, and one of them
         (`test_the_consumer_is_excluded_and_that_is_what_makes_it_discriminate`)
         asserts the unprovable-axis list is non-empty — which is the exact
         condition for the gate to exit 1. No tree on which the gate passes can
         satisfy it. I implemented the two-part remedy and measured it: gate
         rc 1 -> 0, 0 unprovable axes, consumer still excluded, both real
         producers admitted, 3 of 8 tests red. Repair is cheap and named below.

  jdistchip:
    F16  three gates never return 1 on ANY revision of main I tested, including
         the capture commit, while their record claims fires_on_original: Yes.
         Probably innocent — their incidents live in run artefacts, not tracked
         source — but then the RECORD's claim is what is unsupported. Give them
         a committed fixture that fires, or restate the claim. Not a blocker.
    F1   only_the_declaring_step_writes_its_output exits 1 on the tree it ships
         on, with six findings I verified one by one as real, and it is the only
         file on the branch with no repository-sweep test. Four fixes to the
         instrument have landed since; none addressed this. REMEDY TESTED: the
         advisory route is 10 lines in the program plus ONE in the test helper,
         after which 61 tests pass and all six findings are still printed on
         every run. (8 lines / 57 tests were the figures at f3f0beeb6; the
         branch has added tests since.) NOT "inventory them": that program has
         no inventory mechanism at all, so that route means building one first.
    F1+  Its remedy, by contrast, is SAFE and I can say so with a control
         rather than an assertion. Re-built at c0e19ace9: 10 lines + 1 test-
         helper line, advisory rc 0 with all six findings still printed,
         `--strict` rc 1, 61 tests passing. Then I broke the property it is
         sold on — kept the advisory rc and SUPPRESSED the findings — and the
         branch's own tests caught it, 2 of 61 red. That is the difference from
         F14, whose remedy can be applied wrongly and pass 233 tests.

  IMPORTANT QUALIFIER, and it changes how the rest reads: apart from F14,
  NOTHING HERE BLOCKS ANYTHING TODAY. Five gates sit at rc 1 in composition and
  not one is wired, so "THIS GATE BLOCKS" in a docstring is an intent, not a
  wiring fact (F5b). These are wrong or undisposed verdicts, not obstructions.

  WHAT I COULD NOT BREAK: all 32 checkers reproduce their defect from a fixture
  I wrote myself, in both directions, with the finding naming the site and no
  traceback; all 32 negative controls fail on CONTENT when the checker is
  blinded — true of the 32 this report QUOTES; see the re-derivation for the
  eight OTHER red controls on jdistchip that assert rc alone, and for why that
  is a narrower defect than it first looked; zero duplicate any existing program, checked four ways — on the
  EMPIRICAL probe's authority, 25 adjacent programs driven over defect and
  remedy arms, not on the docstring sweep's, which I re-derived on 2026-08-22
  and found separates twins from strangers by only 0.02; and 1824 cross-runs
  found no rule that reddens another rule's remedy.


SUBJECTS, AND THEY MOVED UNDER ME
    origin/jdistmat/matrix-distil             first seen 88ec1594f  10 programs
    origin/capture/jdistchip-chip-path-rules  first seen 8470a80c4  12 programs
    base  origin/main  81cd5321b (v1.11.68) at the start — AND IT DID NOT STAY
          THERE. Main advanced 214 commits to a4caccefe (v1.11.69) during this
          work. Everything load-bearing has been re-measured against the new
          baseline; see "MAIN MOVED UNDER THE BASELINE" below.

TREAT THIS REPORT AS DATED. Both branches were pushed to repeatedly while I
worked. The full sequence I observed:

    jdistmat   88ec1594f -> bb8bf676f -> c68d3be81 -> 3c3a6e0e4
               10 -> 14 -> 15 -> 16 added programs
    jdistchip  8470a80c4 -> 35e9bc1e8 -> 3b8466453 -> 317cef847
               12 programs throughout; 11 of the 12 rewritten at 35e9bc1e8

    jdistmat   -> 222a24479 -> b100334fa -> 89b1c1969   (20 programs;
               F13 ruled on and resolved at 222a24479)
    jdistchip  -> 12b227b4b -> ... -> c6985374b   (12 programs)

    LAST TIPS MEASURED:  jdistmat 3df090f9f    jdistchip 994668036
                         main     a4caccefe (v1.11.69)

    jdistmat HAS NOW MERGED MAIN (b7f504e25, "merge origin/main (v1.11.69), and
    repair a false positive the merge exposed"), so `a4caccefe` is an ANCESTOR
    of its tip and the branch tip IS the composed tree. jdistchip has not
    merged; its composed tree still has to be built. Re-measured at those tips:

      F1   UNCHANGED across three further jdistchip fixes to that very file —
           "the writer scan could not see the repo's own atomic-write idiom"
           (994668036), "the read_spef scan missed catch{} and command
           substitution" and "disclose unparseable skips in the two
           largest-population gates" (3d2dff2c9). Each improved DISCLOSURE or
           the DENOMINATOR — outputs with an identified writer went 55 -> 57 —
           and none changed the verdict: still rc 1, still the same six
           findings. Its two siblings touched in the same commits stayed rc 0
           (declared_basis 22 pairs, signoff_report_states_its_stage 4 emitters).
      F14  UNCHANGED on the merged tip: rc 1 under the wired invocation,
           533 non-atomic writes against a baseline of 515, 20 unregistered.
      THE MERGE PICTURE CHANGED, and in jdistmat's favour. Having absorbed main
           and regenerated the derived files, jdistmat now merges into
           a4caccefe with ZERO CONFLICTS — F4 no longer applies to it.
           jdistchip still carries the four generated count-file conflicts, and
           whichever lands second will need them re-rendered against a main that
           by then includes the first.

      THE LANDING SUITE, REPLAYED AGAIN at these tips with its own 28 wired
           invocations (cwd and argv as the runner gives them):

               new main a4caccefe   26 rc 0, 0 rc 1, 2 rc 2   GREEN
               jdistmat tip         25 rc 0, 1 rc 1, 2 rc 2   RED
               chip-composed        26 rc 0, 0 rc 1, 2 rc 2   GREEN

           Both rc 2 are the tolerated wrapper on all three. The single failure
           is atomic_artifact_write_check on jdistmat — F14 — and it is the same
           single failure it has been through every tip and every baseline this
           report has measured against.

      F15  STANDS, AND MY CORRECTED DIAGNOSIS IS NOW THE DEMONSTRATED CAUSE.
           The gate has been widened — 18 emitting modules and 110 declared
           names became 38 and 143, repairing what its own docstring calls a
           "filename-shaped" narrowing. Its scan ROOT is still
           `<root>/vibe-ic-marketplace/plugins/vibe-ic/programs` (line 191),
           and both drv producers still sit outside it —
           ppa-crosslayer/tools/drv_records.py (7 literal `timing.drv.*`
           mentions) and ppa-e2e/tools/signoff_records.py (1). So the verdict is
           still rc 1 on the same four keys. One narrowing was fixed; the
           DIRECTORY-shaped one, which is the one F15 names, remains.

    BOTH BRANCHES HAVE SINCE ADVANCED AGAIN, WITH CODE THIS TIME:
        jdistmat  -> ad3825d29  (4 commits; fixes to its own write-enumeration,
                    "my own gates had the enumeration bug I documented six times")
        jdistchip -> eeff80d4e  (8 commits; "seven PASS lines claimed more than
                    their check established", a fix to the metric gate that
                    "counted the consumer as its own producer", and the commit
                    that RESOLVES the drv dispute — see F15)
    F15 was re-verified against those, and its DIAGNOSIS corrected as a result.
    THE CHEAP PARTS WERE THEN RE-RUN at ad3825d29 / eeff80d4e, on freshly
    composed trees:
        F1                 UNCHANGED — rc 1, the same six findings. The edit to
                           that file was a one-line PASS-wording fix.
        the 29-gate sweep  UNCHANGED — chip-composed regresses nothing,
                           matrix-composed regresses exactly one
                           (atomic_artifact_write_check, F14).
        Q3                 matrix-composed 20 programs, 3 red — the same three
                           declared reds. chip-composed 12 programs, TWO red:
                           F1, and a NEW one described below.

    A SECOND RED ON THE CHIP SIDE, AND IT IS THE HONEST KIND.
    `every_required_metric_key_has_a_producer` is now rc 1, having been rc 0.
    It went red because jdistchip FIXED it: commit 094c2cb7e, "the metric gate
    counted the consumer as its own producer". With the consumer-echo removed it
    finds a real gap — two axes, `em` and `equivalence`, with no MEASURED
    evidence in any run in the corpus.

    I verified that myself rather than trusting the gate that had just been
    repaired. Walking all 1276 JSON files in the composed tree and counting
    `"metric"`/`"status"` pairs directly:

        equivalence.verdict          MEASURED 0    NOT_MEASURED 364
        reliability.em.violations    MEASURED 0    NOT_MEASURED 364
        reliability.em.worst_ratio   MEASURED 0    NOT_MEASURED 120
        physical.drc.violations      MEASURED 206  NOT_MEASURED 0   <- control

    Zero against hundreds, beside a control axis measured 206 times. The claim
    is true. The red is DECLARED in the verdict line, PINNED by
    `test_the_repository_has_two_axes_with_no_measured_evidence`, and carefully
    bounded — "a producer may exist and never have measured it". It is not a
    defect and does not change jdistchip's verdict.

    AND THE TWO LANES HAVE RECONCILED THE F15 DISPUTE. That gate's own output
    now says: "This gate is EMPIRICAL, so it says what the runs it can see did;
    whether the flow COULD ever measure it is a source question, and
    `gate_proof_vocabulary_has_a_producer` is the instrument for that" — naming
    the matrix rule as its complement rather than its rival. That is the F13
    resolution pattern applied to the F15 disagreement, by the lanes themselves.
    F15 still stands as written: the matrix gate's scan-scope boundary is
    undisclosed and its verdict sentence still over-reaches.

MAIN MOVED UNDER THE BASELINE — 214 COMMITS, v1.11.68 -> v1.11.69, 1238 -> 1240
programs. I did not notice on my own; jdistchip's commit 11becf58b ("re-measure
against main at v1.11.69 — the old numbers had a shelf life") is what prompted
the check. Everything load-bearing was then re-measured against a4caccefe:

    the merge          both branches still merge onto the NEW main with only
                       the four generated count-file conflicts (F4). No add/add.
    THE LANDING SUITE, REPLAYED AS IT ACTUALLY RUNS. My 29-gate sweep drove
                       each gate with NO arguments; the runner drives several
                       with argv that changes what they look at
                       (`... atomic_artifact_write_check.py programs`,
                       `... silent_decline_audit.py programs --ratchet`,
                       `... policy_direction_pin_check.py programs
                       --verify-pins --jobs 6`, and others), and wraps two of
                       them in `run_tolerating_uncheckable`, where rc 2 is not a
                       failure. So I parsed the 28 wired invocations out of
                       tools/ci/repo_hygiene_gates.sh — wrapper, cwd and argv —
                       and replayed them exactly, on all three trees:

                          new main a4caccefe   26 rc 0, 0 rc 1, 2 rc 2   GREEN
                          chip-composed        26 rc 0, 0 rc 1, 2 rc 2   GREEN
                          matrix-composed      25 rc 0, 1 rc 1, 2 rc 2   RED

                       Both rc 2 are the tolerated wrapper, on all three trees.
                       ONE gate fails, on matrix only, through the BLOCKING
                       wrapper: atomic_artifact_write_check (F14). This
                       supersedes the no-argument sweep below, which produced
                       five spurious "needs args" rc 2/3 entries that are not
                       what the suite sees.

    the 29-gate sweep  re-extracted from the new main's own
                       tools/ci/repo_hygiene_gates.sh (still 29, unchanged set)
                       and re-run — first on the branch TIPS, then, when that
                       proved to be the wrong subject, on the COMPOSED trees
                       (new main + branch), which is what actually lands:
                            [SUPERSEDED by the 28-invocation replay above:
                             the "5 need args" are MY wrong invocations,
                             not the suite's. Authoritative: 26/0/2.]
                          new main         24 rc 0, 0 rc 1, 5 need args
                          chip-composed    24 rc 0, 0 rc 1, 5  NO REGRESSION
                          matrix-composed  23 rc 0, 1 rc 1, 5
                       Exactly one gate flips, and only on matrix:
                       atomic_artifact_write_check (F14).
                       WHY THE COMPOSED TREE AND NOT THE TIP: neither branch has
                       rebased, so a gate MAIN repaired in its 214 new commits
                       still reads red on the branch tip, and a tip-vs-main diff
                       reports main's own repair as a branch regression. Three
                       gates behave exactly that way here. Details under F5.
    the duplicate sweep re-run over the new main's 1240 programs against all 32
                       new checkers: highest overlap 0.17, ZERO above the 0.20
                       threshold — same verdict as against v1.11.68.
    F5's count         635 checker-shaped programs on new main, on
                       matrix-composed and on chip-composed alike, while the
                       program total goes 1240 -> 1260 / 1252. Still not one of
                       the new programs is visible to the wiring gates.
    F14                holds, and has GROWN: new main 513 offenders against a
                       baseline of 515 (main shrank it by two), jdistchip 513 —
                       identical to main, contributing nothing — and jdistmat
                       533, so TWENTY unregistered, up from the eighteen I first
                       measured, because the branch kept adding programs.
    Q3, RE-MEASURED WHERE IT LANDS. Every sweep rc in the table was first taken
                       on a branch TIP. After the composed-tree lesson above I
                       re-took all 32 on the COMPOSED trees:
                          chip-composed    10 rc 0, 1 rc 1 (F1, SAME six
                                           findings), 1 rc 2 (declared)
                          matrix-composed  17 rc 0, 3 rc 1 — the three
                                           deliberately-red gates, unchanged
                       Identical to the tip measurements. Q3 holds where it
                       matters.
    F15                holds: the drv keys still appear in emitted records on
                       the new main, `_ppa/timing.py:651` still builds them by
                       format, and the matrix rule still reports the axis
                       unprovable.
    F9                 holds ON THE COMPOSED TREE, positive control first. The
                       corpus grew — 1416 modules parsed, 734 constant-size
                       windows, against 1291 on the branch tip alone — and the
                       two counts did not move: the SHIPPED checker reports the
                       same 10 slice-then-search sites, and my scanner the same
                       40 name-bound ones invisible to it. At its shipped
                       8-row inventory the checker is rc 0, which is the Q3
                       verdict; the 10 is what an empty inventory exposes.
    F10                holds on the composed tree: the same 2 candidates, both
                       already disproved by inspection, and the planted-instance
                       control still returns 1. Still 0 genuine live instances.

So the conclusions survive the advance. But the lesson is the chip lane's, not
mine: a verification's baseline has a shelf life, and mine was 214 commits stale
before anyone said so.

    jdistmat kept adding rules to the end: 20 programs at 89b1c1969, of which
    THREE now ship deliberately red (rows 29, 31, 32). Two of those three reds
    I verified as TRUE; the third is F15. jdistchip has been docs-only since
    e6f938465 — verified, not inferred from commit titles: `git diff
    --name-only ... -- '*.py' '*.json' '*.yaml'` outside `docs/` is EMPTY.

Everything here was FIRST measured at 88ec1594f / 8470a80c4 and then RE-measured
at the later tips. What was re-measured, and what was not, is stated at
"RE-VERIFICATION AT THE LATER TIPS" near the end. Anyone landing should re-run
the cheap parts — the Q3 sweep and the fixture pairs — against the tip of the
day. Rows 1-22 were measured first; rows 23-30 as the author pushed them.

THE BRANCHES ABSORBED MUCH OF THIS WHILE I WROTE IT.
  F7  fixed at 317cef847 (the checker whose filename began with `test_`).
  F13 RULED ON AND RESOLVED at bebd9c1e1 — the author accepted the ruling, gave
      the gate name to the refusing instrument, and renamed their own four to
      `*_census`. I verified every claim in that commit; see F13.
  One chip commit (3b8466453) claimed to resolve a dual-writer path and the NEXT
      commit (de551e09f) retracted it in the author's own words; both are under
      F1, and the retraction's corrected measurement is the better one.

STILL OPEN at the last tips measured, ordered by what each actually does:

    F14 (matrix) — THE ONLY ONE THAT STOPS ANYTHING, established by replaying
                   the landing suite's own 28 wired invocations rather than my
                   own: main GREEN, chip-composed GREEN, matrix-composed RED at
                   exactly one gate — atomic_artifact_write_check, wired at
                   tools/ci/repo_hygiene_gates.sh:1795 through `run`
                   (_dispatch 0 0), where rc 1 fails the suite. 20 unregistered offenders,
                   all jdistmat's own programs; remedy is conversion, not
                   registration.

    The rest are wrong or undisposed verdicts, not obstructions — none of the
    programs involved is wired (F5b):

    F15 (matrix) — a NEW gate ships RED on a verdict that is FALSE, with a test
                   pinning the false red; the sibling lane had already measured
                   that same verdict as false and rewrote its own rule because
                   of it. BLOCKING.
    F14 (matrix) — turns the existing main gate `atomic_artifact_write_check`
                   red; the composed tree inherits it. BLOCKING, and it is a
                   correction to a claim I had made the other way.
    F1  (chip)   — a blocking gate that exits 1 on the tree it ships on.
    F9, F12 (matrix).
The merge is clean again (four mechanical count-file conflicts, F4), but the
COMPOSED tree is red until F14 is fixed. Mergeable and landable are different
questions and I answered them in the wrong order the first time.

COUNT CORRECTION: the brief says "21 new checkers (10 + 11)". The chip branch
adds TWELVE, not eleven — `test_aggregate_carries_its_runtime_identity.py` is a
CHECKER whose filename began with `test_`, easy to read as a test file (the
author has since renamed it; see F7). With jdistmat's later additions the final
population is 32 program files: 20 on jdistmat, 12 on jdistchip. (This sentence
read "30 ... 18 on jdistmat" until 2026-08-22, when I re-derived the population
from the tree and found it disagreed with this report's own table header, which
says 32 rows. The table was right and the sentence was stale — the four
`*_census` files appear in it under their pre-rename names, so coverage was
always complete at 32; only the count in this paragraph was wrong.) Four filenames
appeared on BOTH branches with different implementations for part of this
exercise; that was F13 and it is resolved. All 30 are covered in the table.
```

## REPRODUCE THIS — the load-bearing numbers, as commands

```text
Every figure below can be re-derived without my worktrees. Substitute your own
checkouts for $MAIN / $MAT / $CHIP. Write $P(<tree>) for
<tree>/vibe-ic-marketplace/plugins/vibe-ic. Run with PYTHONDONTWRITEBYTECODE=1
and a TMPDIR outside $HOME.

  WHICH TREE HOLDS WHICH PROGRAM — I got this wrong once while writing this
  section, so it is stated rather than assumed. `atomic_artifact_write_check`
  is an EXISTING main program and runs from any tree. Every other program
  named below exists ONLY on its own branch: run it from $P($MAT) or
  $P($CHIP), or from a composed tree. Running a branch program out of
  $P($MAIN) fails with "can't open file", which is not a verdict.

  F14 — the only landing-suite failure. Use the RUNNER'S invocation, not a bare
  one; the positional `programs` matters and so does the cwd:

      cd $P(<any tree>) && python3 programs/atomic_artifact_write_check.py programs
          main   rc 0    513 non-atomic writes, residual baseline 515
          chip   rc 0    513
          matrix rc 1    533   -> the 20 unregistered

  THE WHOLE LANDING SUITE. Do not hand-pick gates and do not drive them with no
  arguments — both give the wrong answer. Parse the wired invocations out of the
  runner and replay them:

      grep -E '^\s*(run|run_tolerating_uncheckable)\b' \
           $MAIN/tools/ci/repo_hygiene_gates.sh | grep 'programs/'
          25 lines as a plain grep — JOIN BACKSLASH CONTINUATIONS FIRST and
          it resolves to 28 invocations, which is what I replayed.
          `run` is _gate_dispatch.sh:1158 -> _dispatch 0 0,
          where rc 1 AND rc 2 fail; run_tolerating_uncheckable tolerates rc 2.
          main 26/0/2, chip-composed 26/0/2, matrix 25/1/2.

  COMPOSE BEFORE COMPARING. jdistchip has not merged main, so compare its
  MERGED tree, never its tip — a tip-vs-main diff reports main's own repairs as
  branch regressions (three gates behave that way).

      git merge --no-ff <branch> onto $MAIN, resolve only the four generated
      count files, then run the suite.

  F1 — six real dual writers:

      python3 $P($CHIP)/programs/only_the_declaring_step_writes_its_output.py $CHIP
          rc 1, six "declared by step" lines. Verify one by hand:
          spare_cell_coverage_check.py:223 and
          phase3_one_shot_runner.py:21655 both write reports/spare_cell_coverage.json.

  F15 — the producers the gate says do not exist:

      python3 $P($MAT)/programs/gate_proof_vocabulary_has_a_producer.py --root $MAT
          rc 1 on axis drv. Then:
      grep -n 'timing.drv' $MAIN/ppa-crosslayer/tools/drv_records.py
      grep -n 'timing.drv.violations' $MAIN/ppa-e2e/tools/signoff_records.py
          Both declare the keys as plain literals, outside the gate's scan root.

  F9 — what the gate sees vs what exists. The 10 is only visible with an EMPTY
  inventory; at its shipped inventory it is correctly rc 0:

      echo '{"known": []}' > /tmp/empty.json
      python3 $P($MAT)/programs/declaration_searched_only_inside_a_truncated_window.py \
              --root $MAT --inventory /tmp/empty.json
          "slice-then-search sites: 10" against 40 name-bound sites a scanner
          handling `not in` and windows nested in concatenations finds.

  F12 — PASS on nothing. Build a tree holding only .git and an empty
  programs/, then run each gate against it WITHOUT an inventory override —
  and DRIVE EACH IN THE FORM IT ACCEPTS. This is the step I got wrong when I
  first published F12; a bare invocation reports three times the true number.

      E=$(mktemp -d)/e; mkdir -p $E/programs; git init -q $E
      matrix gates:  python3 <prog> --root $E     (positional gives rc 3)
      chip gates:    python3 <prog> $E            (--root gives rc 3)
      Score ONLY rc 0. Never score an rc 3 — that is a bad invocation, not a
      verdict, and it is what makes the two branches look falsely identical.

      3 of jdistmat's 16 non-census gates answer rc 0; 0 of jdistchip's 12 do.
      The three are layer_membership_is_declared_not_inferred_from_a_filename_
      prefix, reference_control_resolved_through_a_mutable_ref, and
      wall_clock_bound_standing_in_for_a_verdict. The other thirteen refuse.

  A WARNING THAT COST ME FOUR WRONG FIRST READINGS: an invocation flag changes
  the answer. `--strict` on an advisory rule, `--inventory <empty>` on a rule
  that grandfathers, a missing `--inventory` on one that needs it, and a dirty
  checkout under policy_direction_pin_check all produce verdicts that are not
  what the suite sees. Drive each program the way its wiring drives it.
```

## METHOD

```text
Each arm its own tree, its own TMPDIR, PYTHONDONTWRITEBYTECODE=1. Worktrees, one
per tip measured:
    /tmp/jvM  main 81cd5321b
    /tmp/jvA  jdistmat 88ec1594f   /tmp/jvA3 c68d3be81   /tmp/jvA4 3c3a6e0e4
    /tmp/jvB3 jdistchip 3b8466453  /tmp/jvB4 317cef847
    /tmp/jvfx, /tmp/jvfx2   the fixture trees I built
Every checkout was `git status --porcelain`-clean before and after every
measurement. No container was needed: all 30 are pure static Python over the
tree; host python3 3.10.12 / pytest 9.1.1 runs them. The whole programs/tests
suite was NOT run — only the new test files, two `*polarity*` regression files,
and the repo-level meta-gates named under F5.

Q1/Q2 were answered TWICE, by two independent methods, because they answer
different halves of the question.

  METHOD 1 — I REINTRODUCED EVERY DEFECT MYSELF.
  For all 30 I built a throwaway tree, authored the defect from the rule's OWN
  stated predicate (never by copying the test's fixture constant), ran the
  checker, and read the output. Then I authored the REMEDY and re-ran, so every
  row is bidirectional. Results: 30/30 go rc 1 with a finding naming the file,
  the line and the specific shape; 30/30 remedies go rc 0; stderr EMPTY on every
  red — no traceback masquerading as a verdict.
  This is the half that proves the CHECKER detects the defect.

  METHOD 2 — I BLINDED EVERY CHECKER.
  Each checker was replaced by a stub that exits 1 and prints nothing. This is
  the mutation that matters: a control asserting only `rc == 1` is satisfied by
  a crash, so such a control proves nothing. Under the silent-rc-1 stub every
  one of the 30 negative controls FAILED, and every one failed on its CONTENT
  assertion — never on `rc`, never on ImportError / KeyError / FileNotFoundError.
  Under a silent-rc-0 stub they fail on `rc` instead. Baseline with the real
  checkers: every new test file green (253 passed at the original tips; 147 and
  216 at the later ones).
  This is the half that proves the TEST is load-bearing.

  Two exceptions, stated rather than smoothed over. For
  `every_required_metric_key_has_a_producer` and for the renamed
  `pytest_aggregate_carries_its_runtime_identity`, the blanket stub broke the
  test FIXTURE (both import the module in-process), so Method 2 was re-run there
  with an importable stub, or with a targeted `main() -> return 1`. Same result:
      test_every_required_metric_key_has_a_producer.py:77 AS MEASURED:
        assert "'hold'" in out and "STRUCTURALLY UNPROVABLE" in out
      E   assert ("'hold'" in '')
      RE-CHECKED at jdistchip f3f0beeb6: the control still exists and still
      pins the red, but it has MOVED and its text has CHANGED — it is now at
      line 106 and reads
        assert "'hold'" in out
        assert "IS NOT PROVEN BY ANY RUN IN THIS CORPUS" in out
      because that lane reframed the gate from a source claim to an empirical
      one. The Method-2 result is unaffected — a content assertion still fires
      under the blinded checker — but the quotation above is dated, and this is
      the only citation in this report whose TEXT moved rather than just its
      line number.

  METHOD 5 — THE REAL-HISTORY CONTROL, which I did not think of and jdistchip
  did. Applied to BOTH branches it cleared six of jdistmat's seven testable
  gates and five of jdistchip's twelve, and produced F16. A rule firing on a fixture I built proves it can detect the shape I
  wrote. It does NOT prove it would have caught the ORIGINAL defect in the tree
  where that defect actually lived. jdistchip proved the gap matters: they ran
  five of their always-green gates against five revisions of main and NONE ever
  returned 1, while their capture claimed "fires_on_original: Yes" of all five
  (4445f34a2, "it passed on the incident that motivated it").

  So I applied the same control to jdistmat's gates — today's rule against four
  past revisions of main spanning the capture period (a758f4adc, 506ff68c1,
  e33d2735d, 7ce038284), driven with an EMPTY inventory so the answer is what
  the rule DETECTS rather than what it has grandfathered:

      declaration_searched_only_inside_a_truncated_window   1 1 1 1
      denial_that_constitutes_the_value_it_appears_to_negate 1 1 1 1
      invocation_proved_by_parse_not_by_text                1 1 1 1
      population_pin_without_its_member_set                 1 1 1 1
      registry_is_the_iteration_domain                      1 1 1 1
      spawned_gate_whose_status_is_discarded                1 1 1 1
      reference_control_resolved_through_a_mutable_ref      0 0 0 0

  SIX OF SEVEN FIRE ON REAL HISTORY. They are not vacuous.

  THE SEVENTH IS SILENT AND CORRECTLY SO, and I checked rather than filing it.
  Its capture named one live instance,
  `tests/test_w4_absent_condition_is_not_a_pass.py`. That file is PRESENT in all
  four trees and mentions `origin/` six times — which looks exactly like the
  vacuity jdistchip found. It is not. Line 127 of it reads
  "#: PINNED, and deliberately not `origin/main`", i.e. the defect was repaired
  to an immutable object name, and all six surviving mentions are prose in
  docstrings and comments. The gate ignoring them is the discrimination its own
  docstring claims — "a regular expression over the same corpus returns 15 sites
  across 12 files, 13 of them prose". And it demonstrably CAN fire: my own
  fixture for row 7 (`git show origin/main:<rel>`) makes it rc 1. Silent because
  there is nothing to find, not because it cannot look.

  METHOD 3 — I RAN EVERY RULE OVER EVERY OTHER RULE'S REMEDY.
  The brief's stated harm is "two checkers that disagree make the tree
  unlandable". That is testable: I froze the defects and their remedies as 19
  paired fixture trees (the rest need the real tree and were verified on real
  code instead), then ran every checker over all 38 arms — 836 runs at the
  original tips, and 988 again at the new tips with the four F13 collision
  copies kept as distinct entities. A disagreement is a checker going rc 1 on
  ANOTHER rule's remedy. Result in "THE DISAGREEMENT TEST" below: none, in
  either run.

  METHOD 4 — I ASKED WHETHER AN EXISTING PROGRAM ALREADY CATCHES THE DEFECT,
  and then, because hand-picking is judgement rather than measurement, swept all
  1238 of them mechanically as well (see "THE EMPIRICAL DUPLICATE PROBE").
  Name-and-docstring analysis answers "is there a program about this"; it does
  not answer "does one already fire on this". So I drove 37 adjacent existing
  main programs over the defect AND remedy arms — 25 for the first 22 rows, 12
  more for the two genuinely new ones. A genuine duplicate is red on the defect
  and green on the remedy; red on both is noise. Result: zero discriminating
  programs. The adjacent programs that need a whole tree and cannot be driven on
  a fixture were closed instead by running them on main and on both branches and
  diffing finding sets — zero delta, every one.

  EVERY LINE-ANCHORED CITATION IN THIS REPORT WAS VERIFIED AT THE TIPS IT
  NAMES — 21 real ones (the rest point at my own throwaway fixtures). Two were
  stale and are now corrected: `gen_programs_index.py` lives under `tools/`,
  not `programs/` (my F9 scanner reads both, so the site is real and the path
  was wrong), and the Method-2 control I quote for row 12 has both moved and
  been reworded by jdistchip's test hardening. The other 19 resolve to exactly
  what this report says they do. Citation rot is what makes a verification
  unusable six weeks later, and jdistchip dated their own citations for the
  same reason at 641f2ec51.

  EVERY ZERO IN THIS REPORT HAS A POSITIVE CONTROL, because F10 records me
  publishing one that did not. The instruments and what proves each can answer
  non-zero:
      the F10 constitutive-denial scan   a planted instance makes it return 1
      the duplicate probe harness        3 of 4 known-catching drives show the
                                         discriminating signature (the fourth is
                                         an invocation-form limit, explained)
      the duplicate similarity threshold true same-rule twins score 0.21-0.27,
                                         nothing in the sweep exceeds 0.17
                                         (swept over main's 1238 programs at
                                         v1.11.68; v1.11.69 has 1240)
      F9's slice-then-search scanner     reproduces the shipped checker's own
                                         ten findings exactly
      the 836/988-run cross matrix       its 19/19 owner check (defect 1,
                                         remedy 0) is the control
      the 29-gate hygiene sweep          it found a real difference nobody else
                                         had (F14)
      the blinded-stub method            stub-0 and stub-1 produce different
                                         failures, and the tree is verified
                                         clean after every mutation

  FOUR TIMES MY FIRST READING WAS WRONG BECAUSE OF AN INVOCATION FLAG, and
  every time the checker was right and I was not. Recorded together because the
  pattern is the point, not the instances:
      passing `--strict` to two rules that are ADVISORY by default, and reading
        the resulting rc 1 as two new reds;
      passing `--inventory <empty>` to ten inventory-taking rules during a Q3
        sweep, which disables their grandfathering and turned 3 reds into 11;
      passing `--inventory` to two rules that do not accept it, and reading the
        rc 3 as their behaviour;
      NOT passing `--inventory` in the duplicate-probe harness, so a rule fell
        back to its shipped inventory and its stale-row rule fired on both arms.
  An empty inventory is a legitimate diagnostic — I use it deliberately under F9
  to ask what a rule would find without grandfathering — but it is not the Q3
  invocation, and conflating the two makes a clean tree look red.

  SIX of my hand-built fixtures came up GREEN on the first attempt. I chased
  every one to a cause rather than filing it — four were MY error, two are real
  findings. That breakdown is the most useful thing in this report and it is in
  "WHERE MY FIXTURES CAME UP GREEN" below.
```

## TABLE — 32 rows

`sweep rc` = the checker run against the tree being shipped.

Rows 1–22 are the two branches as they stood at the original SHAs. Rows 23–30
are what jdistmat added while I was verifying; all are covered to the same four
questions. Rows 23–26 were the F13 collisions and have since been renamed to
`*_census` by the author — the row text describes them as I measured them, and
F13 records the resolution I verified.

```text
--- origin/jdistmat/matrix-distil -------------------------------------------
 #  checker
     red reproduced BY ME (Y/N) — what my own fixture produced
     control assertion that fired under the blinded checker
     right reason / sweep rc / duplicate

 1  content_pinned_authority_verified_only_at_merge
     Y  my manifest pinned tools/ci/x.sh in two states; I edited the file to a
        third. -> rc 1 "tools/ci/x.sh hashes to 222e0a52347e, which is neither
        pinned state". Moving the tree INTO the `next` state -> rc 0.
     ctl: assert "tools/ci/x.sh" in r.stdout      -> AssertionError: in ''
     Y   rc 0   N (d3_manifest_declaration_parity_check pins a different
                  manifest against required_outputs)

 2  declaration_searched_only_inside_a_truncated_window
     Y  my own shapes, which the test does not use — a head window fed to
        `.startswith` and a tail window fed to `.find`:
        -> rc 1  "my_audit.py:6  text[1500] searched by .startswith()"
                 "my_audit.py:11 text[-800:] searched by .find()"
     ctl: assert "text[4000]" in r.stdout         -> AssertionError: in ''
     Y   rc 0   N     *** BUT SEE FINDING F9 — a real coverage gap ***

 3  declared_invocation_accepted_by_its_own_parser
     Y  my flow clause declared `release_docs_gen.py` with no arguments against
        a parser marking two required. -> rc 1 "argparse rejected the umbrella's
        argv: the following arguments are required: --project, --version".
        Supplying both -> rc 0.
     ctl: assert "release_docs_gen" in r.stdout   -> AssertionError: in ''
     Y   rc 0   POPULATION EXTENSION of p0_gate_invocability_drift_check —
                VERIFIED not a copy: `grep -rn "def classify_not_invocable"`
                returns exactly ONE definition (_gate_invocation.py:153) and
                both programs call it. The branch's own test pins the import.

 4  denial_that_constitutes_the_value_it_appears_to_negate
     Y  my `extract_unconstrained_paths()` with a denial regex inline ->
        rc 1 "extracts 'freedom' (by function name) and applies inline denial
        regex '\b(?:no|not|never)\b'". Routing it through
        `classify_denial("freedom", ...)` -> rc 0.
     ctl: assert "extract_unconstrained_paths" in r.stdout -> AssertionError:''
     Y   rc 0   POPULATION EXTENSION beside prose_polarity_consulted_check —
                imports _prose_polarity; that diff is PURELY ADDITIVE and the
                module's existing tests still pass (42 passed).
                See F10 for a latent limitation.

 5  invocation_proved_by_parse_not_by_text
     Y  my own text-deciding wiring audit -> rc 1 "sample_coverage_check.py:20
        `in` membership over `runner_text` (python source read at line 26), and
        the module never parses it".  stderr empty.
     ctl: assert "runner_text" in r.stdout        -> AssertionError: in ''
     Y   rc 0   N (hdl_declaration_scan_strips_comments_check enforces the same
                  discipline over HDL text, not python; nothing to share)

 6  population_pin_without_its_member_set
     Y  my test module asserting `len(steps) == 69` over an rglob -> rc 1
        "1 pin(s): 69 via rglob (line 8)". Adding a member-set assertion -> rc 0.
     ctl: assert "test_sample.py" in r.stdout     -> AssertionError: in ''
     Y   rc 0   N, adjacent to corpus_cardinality_pin_scan (rc 1 on origin/main,
                PRE-EXISTING) and emitter_population_pin_check (rc 0). Different
                predicates; no verdict conflict measured.

 7  reference_control_resolved_through_a_mutable_ref
     Y  my control reading `git show origin/main:<rel>` -> rc 1
        "my_control.py:6  git show origin/main:". Same call with a full object
        name -> rc 0.
     ctl: assert "git show origin/main" in r.stdout -> AssertionError: in ''
     Y   rc 0   N

 8  registry_is_the_iteration_domain
     Y  (after two wrong fixtures of mine — see below) my re-typed
        local-loader shape -> rc 1 "sample_gate_check.py:17  for row in ledger
        <- acknowledged.json  (findings.append())". Demoting the registry to a
        filter over a derived population -> rc 0.
     ctl: assert "sample_gate_check.py" in r.stdout -> AssertionError: in ''
     Y   rc 0   N (gate_zero_denominator_refuses_check / gate_discloses_
                  denominator_check answer the RUNTIME question by probing each
                  gate against an empty project; this one is STRUCTURAL, over
                  the loop. Both measured rc 0 on main — no conflict.)

 9  spawned_gate_whose_status_is_discarded
     Y  my unbound `subprocess.run([... "flow_compliance_check.py"], check=False)`
        inside `except Exception: pass` -> rc 1 "result unbound, check off,
        inside a handler that swallows everything". Binding and reading the
        status -> rc 0.
     ctl: assert "flow_compliance_check.py" in r.stdout -> AssertionError: ''
     Y   rc 0   N (neutered_gate_tree_check finds a gate made unable to fail by
                  an injected early return — a different defect)

10  wall_clock_bound_standing_in_for_a_verdict
     Y  my 0.45 s kill reported as a finding -> rc 1 "my_probe.py:11  0.45 s ->
        kill()". Same bound with the load carried in the message -> rc 0.
     ctl: assert "0.45 s" in r.stdout             -> AssertionError: in ''
     Y   rc 0   N (ci_harness_timeout_ceiling_check asks whether a test's own
                  timeout CAN fire under the harness — a different question)


--- origin/jdistmat/matrix-distil, ADDED AFTER MY FIRST PASS -----------------
Numbered 23-27 so the rows above keep their numbers. Rows 23-26 are the four
F13 collisions: the SAME filename as chip rows 13, 15, 17 and 20. Each was
verified against ITS OWN docstring's canonical defect, not against chip's.

23  explicit_argument_outranks_the_environment_pointer          [matrix copy]
     Y  my fixture from ITS predicate — env value written onto a parsed-argument
        ATTRIBUTE under a guard requiring the argument to be PRESENT
        (`if _env_tree and args.tree: args.tree = _env_tree`) -> rc 1.
        Its documented-correct form (`and not args.tree`) -> rc 0.
     ctl (blinded): assert '--tree' in ''
     Y   rc 0   *** DUPLICATE of chip row 13, AND THEY DISAGREE — F13 ***
                chip refuses the form this copy documents as correct; this copy
                returns rc 0 on chip's canonical defect. Two rules, one name.

24  local_clone_does_not_borrow_objects                         [matrix copy]
     Y  my `git clone --shared` fixture -> rc 1; hardlink clone -> rc 0.
     ctl (blinded): assert '--shared' in ''
     Y   rc 0   DUPLICATE of chip row 15 — but the two AGREE on my fixture in
                both directions. Same predicate, different file. Still F13:
                one of the two files has to go.

25  only_the_declaring_step_writes_its_output                   [matrix copy]
     Y  my two-writer fixture -> rc 1; single writer -> rc 0.
     ctl (blinded): assert 'reports/coverage.json' in ''
     Y   rc 0   DUPLICATE of chip row 17. Agrees on my fixture; on the REAL
                tree this copy is rc 0 and chip's is rc 1, because this one
                sees 121 declared paths / 23 resolvable writes and waives its
                2 findings by inventory, and chip's sees 195 / 55 and refuses
                its 6. F13.

26  provenance_value_is_resolved_not_constant                   [matrix copy]
     Y  my fixture from ITS predicate — a `source` key written with a constant
        path string -> rc 1 "my_emit.py:6  source =
        'phase3/stage3/pnr/openroad.log'"; rendered from a resolved value
        -> rc 0.
     ctl (blinded): assert 'reports/phase3/antenna.rpt' in ''
     Y   rc 0   *** DUPLICATE of chip row 20, AND EACH IS BLIND TO THE OTHER'S
                INSTANCES — the worst of the four. Driven with an EMPTY
                inventory on origin/main this copy reports 12 candidates and 10
                findings, all `source = '<path>'` data fields, and it does NOT
                include phase3_one_shot_runner.py:37700 — the site chip found
                and repaired. It reports :19171 in the same file instead.
                Chip's copy answers rc 2 NOT CHECKED on my fixture for this
                copy, because it has no resolved-subject write to look at.
                Neither is a superset. Landing either one alone leaves the
                other's entire class unguarded. F13.

27  population_guard_asserts_equality_not_a_floor
     Y  my fixture — `_TABLE = ["a","b","c"]` then `assert len(_TABLE) == 3`
        -> rc 1 "tests/test_sample.py:5  len(_TABLE) == 3  (the literal holds
        3)". Re-derived against a live population, count AND member set -> rc 0.
     ctl (blinded): assert '_PORTS' in '' / assert 'NEG_FIXTURES' in ''
     Y   rc 0   N — searched by name, by docstring and empirically.
                Closest two on main, both ADJACENT and neither a duplicate:
                  corpus_cardinality_pin_scan — pins a LIVE census
                    (`len(rows) == 23` over a published tree). Opposite failure
                    mode: that assertion fires spuriously, this one never fires
                    at all. rc 0 on both arms of my fixture.
                  flow_step_can_fail_check — "a step whose gate cannot fail
                    must say so", same DOCTRINE but read from the flow yaml
                    over 63 steps, not from python assertions over literals.
                    rc 0 on main and on the matrix tip, 0 new lines.
                Six candidates driven over my defect/remedy pair: 0
                discriminating (0 red-on-defect and green-on-remedy).
                Self-consistent, too: its own test uses
                `len(NEG_FIXTURES) >= 5`, the floor form its docstring names as
                acceptable. (23 len()-over-a-literal sites, 3 guards that cannot
                fail, all 3 grandfathered with a reason.)

28  two_input_selectors_given_together_must_refuse
     Y  my fixture — a parser offering a positional `project` AND `--corpus`,
        with neither a mutually-exclusive group nor an `if` deciding the
        both-given case -> rc 1, "single=['project'] collection=['corpus']".
        Adding `if args.project and args.corpus: ... return 3` -> rc 0.
     ctl (blinded): assert ('record' in '')
     Y   rc 0   N — nothing on main enforces "a parser offering two input
                selectors must refuse or decide the both-given case". The
                name-similar cmd_argument_validation_present_check is about IC
                opcode argument validation in L3_CMD_PROTOCOL.json, not CLI
                parsers, and is red on BOTH arms of my fixture (it is answering
                about an absent protocol document). Six candidates driven over
                my defect/remedy pair: 0 discriminating.
                (8 dual-selector parsers on its tree that neither refuse nor
                decide, all 8 grandfathered with a reason.)
                SCOPE NOTE, and it is F11 for the third time: the selector
                vocabulary is two fixed lists. My first fixture used
                `--project-dir` for the collection selector and the rule did not
                see it, because the list holds `--dir/--tree/--corpus/--batch/
                --all/--inputs/--files/--glob/--roots` and not that. Renaming
                the flag made the identical defect go red.

29  layer_membership_is_declared_not_inferred_from_a_filename_prefix
     Y  my fixture — a layer whose population is a filename-prefix glob while a
        real member (an executable importing the layer's package) sits outside
        it -> rc 1. A glob reaching the whole relation -> rc 0.
     ctl (blinded): assert ('other_0.py' in '')
     Y   rc 1   *** DECLARED, PINNED, AND ITS SIX FINDINGS VERIFIED TRUE BY ME:
                three of the six named files live inside `_ppa/` and import it,
                two more import `_ppa` at module level, and the sixth
                (`gate_proof_vocabulary_has_a_producer.py`) imports
                `_ppa.feasibility` at line 85 as a function-local import — my
                first grep missed that one and I nearly filed a false positive
                against the rule. None of the six matches the `ppa_*.py` glob,
                so all six are genuinely layer members the glob omits.
                Its docstring header reads "THIS GATE
                BLOCKS (rc=1), AND IT IS RED ON THE TREE IT SHIPPED WITH. That
                is deliberate and it is the point", and
                `test_the_shipped_tree_is_RED_and_that_is_the_point` PINS the
                red — asserting rc 1 AND the two finding strings, with an
                instruction to assert rc 0 rather than weaken the gate once the
                repair lands. Deliberately no inventory: "a recorded waiver
                would make the question disappear."
                This is the HONEST form of the thing F1 criticises, by the same
                author, on the sibling branch. Contrast is the point: F1's gate
                ships red with no declaration and no pinning test; this one
                ships red with both.   duplicate: N

30  published_absence_claim_is_rechecked_against_the_tree
     Y  my fixture — a non-docstring string saying "programs/real_module.py is
        not present in this tree yet" while that file EXISTS -> rc 1,
        "my_placeholder.py:2 names programs/real_module.py". Re-deriving the
        state with a file test at publish time -> rc 0.
     ctl (blinded): assert 'em_report_check.py' in ''
     Y   rc 0   N — and the green is guarded against F12's failure mode by its
                own test: `test_the_shipped_tree_is_green_over_a_NON_EMPTY_
                population` asserts the scanned population exceeds 50. Measured:
                1291 modules parsed, 328 absence-shaped strings, 0 attached to a
                path, 0 false. The 0 that matters is the finding count; the
                denominator that must not be 0 is the 328, and the test pins it.
                This is F12's remedy, applied by the same author.

31  gate_proof_vocabulary_has_a_producer
     Y  my fixture from its predicate — an axis whose proof names appear in no
        emitting module's declared names -> rc 1; adding a producer -> rc 0.
     ctl (blinded): the negative control fails on its content assertion.
     Y   rc 1   *** RED ON A FALSE FINDING — see F15. The red is DECLARED and
                PINNED by `test_the_shipped_tree_is_RED_on_drv`, but the drv
                verdict it pins is untrue: all four keys have producers in
                emitted records, and the sibling lane already measured this
                exact verdict as false before rewriting its own rule to be
                empirical. duplicate: not by filename, but it CONTRADICTS chip
                row 12 `every_required_metric_key_has_a_producer` on one tree.

32  metric_constant_across_differing_arms_is_not_measured
     Y  an axis taking one value across provably-differing arms -> rc 1.
     ctl (blinded): the negative control fails on its content assertion.
     Y   rc 1   DECLARED and PINNED by
                `test_the_shipped_tree_is_RED_and_names_the_corroborated_axis`,
                and the findings are TRUE — I verified the denominator myself:
                `ppa-e2e/search/trials.json` holds 60 arms with 60 DISTINCT
                `knobs` dicts, and area.instances.total.um2, power.total_w and
                design.instance.count each take exactly one value across all
                60. Its own remedy text concedes some axes may be legitimately
                invariant and says the artefact cannot currently support that
                claim, which is the honest form.   duplicate: N

--- origin/capture/jdistchip-chip-path-rules ---------------------------------

11  declared_basis_matches_the_session_inputs
     Y  my POST_ROUTE-stamped report over a session with `read_spef` removed ->
        rc 1 "claims POST_ROUTE ... but its session measured PRE_LAYOUT. The
        session loads NO extracted parasitics, so this number cannot move when
        the layout moves". Restoring read_spef -> rc 0.
     ctl: assert "claims POST_ROUTE" in out       -> AssertionError: in ''
     Y   rc 0   N — imports the single reader `_sta_basis`; its own test pins
                `dbmtsi._sta_basis is _sta_basis`, so no sixth stamp reader.

12  every_required_metric_key_has_a_producer
     Y  I derived the axis table from the checker itself, then emitted every
        axis key EXCEPT one axis's — and deliberately not the axis the test
        uses ('setup', not 'hold') -> rc 1 "axis 'setup' is STRUCTURALLY
        UNPROVABLE ... on any design, forever". Restoring it -> rc 0.
     ctl: assert "'hold'" ... "STRUCTURALLY UNPROVABLE"  -> assert ("'hold'" in '')
     Y   rc 0   N

13  explicit_argument_outranks_the_environment_pointer
     Y  my module letting VIBE_IC_BENCHMARK_DATA silently replace `args.corpus`
        -> rc 1 "can redirect its subject with it, and prints nothing naming
        the tree it scanned". Announcing the override -> rc 0.
     ctl: assert "cannot tell" in out             -> AssertionError: in ''
     Y   rc 0   N   (vocabulary limit noted in F11)

14  generated_values_state_whether_they_were_read_or_defaulted
     Y  my emitter using `rep["delay"] or 5.0` and writing the artefact without
        any of the disclosure -> rc 1 "The artefact is then identical whether
        the input was READ or DEFAULTED". Carrying source+line -> rc 0.
     ctl: assert "read or DEFAULTED" in out       -> AssertionError: in ''
     Y   rc 0   N   (vocabulary limit noted in F11)

15  local_clone_does_not_borrow_objects
     Y  my `git clone --shared` preparation site -> rc 1 "creates
        objects/info/alternates — the exact shape landing_tier_checkout_
        preflight refuses". The plain hardlink clone -> rc 0, which is the
        point: it must not redden the remedy its sibling prints.
     ctl: assert option in out (4 parametrised rows, all four fired)
     Y   rc 0   N — COMPLEMENTARY to landing_tier_checkout_preflight (this is
                the producer side), and deliberately narrowed so the two cannot
                contradict. I read both; the narrowing is real.

16  measurement_only_artefact_is_not_a_verdict_source
     Y  my record carrying `outcomes: [SATISFIED]` together with a note saying
        it is not a sign-off verdict -> rc 1 "an axis proof is SATISFIED by a
        record that declares itself not a verdict". Dropping the note -> rc 0.
     ctl: assert "declares itself not a verdict" in out -> AssertionError: ''
     Y   rc 0   N

17  only_the_declaring_step_writes_its_output
     Y  my flow declaring one output and two modules writing it -> rc 1
        "declared by step ['23'] and written by 2 modules". Removing the second
        writer -> rc 0. Declaring the path for TWO steps -> rc 0 + an explicit
        EXEMPT line. Three-way control, all three correct.
     ctl: assert "reports/coverage.json" in out   -> AssertionError: in ''
     Y   rc 1   *** SEE FINDING F1 — THE ONE BROKEN-TREE DEFECT ***
             N (no duplicate)

18  prepared_checkout_states_the_revision_it_holds
     Y  reproduced on REAL CODE: reverting the branch's own fix to
        ip_catalog_reproduce_pull.py -> rc 1 (full transcript under CLAIM 2).
     ctl: assert "REFUTED" in out                 -> AssertionError: in ''
     Y   rc 0   N (producer-side sibling of landing_tier_checkout_preflight)

19  printed_remedy_runs_as_printed
     Y  my printed `docker run ... vibeic-eda:0.3.13 bash -lc 'yosys -V'` ->
        rc 1 "puts 'bash' where the entry point expects `--skip` — the entry
        point consumes the command". Putting --skip first -> rc 0.
        (This rule is this brief's own hard rule, enforced deterministically.)
     ctl: assert "Unexpected option" in out       -> AssertionError: in ''
     Y   rc 0   N

20  provenance_value_is_resolved_not_constant
     Y  reproduced on REAL CODE: reverting the branch's own fix to
        phase3_one_shot_runner.py -> rc 1 (full transcript under CLAIM 2).
     ctl: assert "phase3/stage3/pnr/openroad.log" in out -> AssertionError: ''
     Y   rc 0   N

21  signoff_report_states_its_stage
    [UPDATED at jdistchip 4445f34a2. Sweep rc 0 -> 1. The author found that
     five of their always-green gates never returned 1 across five revisions of
     main while the capture record claimed "fires_on_original: Yes" — "both
     cannot be true" — and repaired this one by adding a sibling-stamp arm. It
     now reports 3 unstamped reports beside a stamped sibling.
     THE NEW RED IS HANDLED THE WAY F1's IS NOT, and by the same author on the
     same branch: `test_repository_itself_is_clean` was not deleted, it was
     REWRITTEN as `test_repository_arm_a_is_clean_and_arm_b_reports_the_known_
     set`, which asserts rc 1, asserts arm A is still clean with a message
     saying what a regression would mean, and pins arm B's finding SET by
     identity against `_KNOWN_UNSTAMPED` — a member-set pin, which is precisely
     what jdistmat's `population_pin_without_its_member_set` rule demands. 22
     tests pass. This is the disposition F1 is missing, demonstrated next door.]
     Y  my flow-declared power report whose emitter writes no STA_BASIS ->
        rc 1 "emitted by power_emit.py:emit() which never writes STA_BASIS ...
        dropped from the evidence set quietly". Writing the stamp -> rc 0.
     ctl: assert "post_route_timing.rpt" in out   -> AssertionError: in ''
     Y   rc 0   OVERLAP, not duplicate: the existing
                tests/test_multicorner_signoff_reports_declare_their_stage.py
                pins TWO named emitters by hand; this is the flow-derived
                population rule that covers them. Both green.

22  test_aggregate_carries_its_runtime_identity
    [renamed to pytest_aggregate_carries_its_runtime_identity at 317cef847 —
     re-verified under the new name, all four answers unchanged; see F7]
     Y  my per-case aggregate with no runtime block -> rc 1 "omits image,
        interpreter, unimportable_plugins — a failure count that does not name
        its runtime can be charged to the revision when it belongs to the
        runtime". Stamping it -> rc 0.
     ctl: assert "image" in out and "interpreter" in out -> AssertionError: ''
     Y   rc 2   DELIBERATE and PINNED: the repository is not a run tree, the
                program says "NOT CHECKED — ... This tree is a repository, not
                a run tree", and its own test asserts rc == 2 and that phrase.
                The empty-denominator rule obeyed, not evaded.
             N (adjacent: container_image_provenance, image_gated_verification_
                check, landing_pytest_runtime_preflight — all named in its own
                docstring, none enforcing this predicate)

SUMMARY OF THE TABLE
    red reproduced by my own hand-built defect ....  32 / 32
    bidirectional (my remedy goes green) ..........  32 / 32
    stderr empty on the red (no masked traceback) .  32 / 32
    negative control fails on CONTENT when blinded   32 / 32
    sweep rc 0 ....................................  27 / 32
    sweep rc 2, declared + pinned .................   1 / 32   (#22)
    sweep rc 1, DECLARED + pinned, findings TRUE ..   4 / 32   (#29, #32, chip's
                                       every_required_metric_key_has_a_producer
                                       once repaired at eeff80d4e, and #21 once
                                       repaired at 4445f34a2)
    sweep rc 1, DECLARED + pinned, finding FALSE ..   1 / 32   (#31 — F15)
    sweep rc 1, UNDECLARED ........................   1 / 32   (#17 — F1)
    Q4 settled by name + fixture + whole-tree diff
      + a calibrated sweep of all 1238 main programs   32 / 32
    duplicates against anything already on main ...   0 / 32
    duplicates the two branches created between
      THEMSELVES ..................................   4 / 30   RESOLVED (rows 23-26,
                                       were F13 collisions with chip rows
                                       13/15/17/20; renamed to `*_census` by the
                                       author and re-verified. 2 declared
                                       population extensions verified as such —
                                       one definition of the predicate,
                                       imported.)
    disagreements (a rule red on another's remedy)    0 / 1824 runs
                                       (836 at the original tips + 988 at the
                                        new tips, 19 fixture pairs each)
    existing programs that already catch the defect   0 / 37 probed
    PASS on an empty scan (zero denominator) ......   3 / 28 gates
                                       (3 of jdistmat's 16 non-census gates;
                                        0 of jdistchip's 12 — see F12. The four
                                        `*_census` files are excluded: rc 0 is
                                        correct by construction for a census.)
                                       Was published as 9 / 26 and corrected on
                                       2026-08-22; the 9 was a bare-invocation
                                       artefact. CORRECTION in F12.
```

## WHERE MY FIXTURES CAME UP GREEN — six cases, four mine, two real

```text
This is the part of the exercise that found things, so it is written out.

MINE (the checker was right and my fixture was wrong):

  #8 registry_is_the_iteration_domain. My first fixture iterated a registry and
     emitted findings, and passed. Bisecting my own fixture against the test's
     showed the difference was two lines I had dropped: the module must also
     reach an INDEPENDENT population. That is not an oversight — it is
     documented and tested as `test_a_check_whose_only_artefact_is_the_registry_
     is_not_refused`, which names the real-tree example
     (`phase1_no_waivers_used_check`, whose subject IS the waiver file).
     Flagging that shape would flag a correct check. Checker right.

  #22 test_aggregate_carries_its_runtime_identity. My first aggregate used a
     `testsuites` summary shape and got rc 2 NOT CHECKED. The recognised shape
     is per-case (`cases` with `nodeid`), and the narrowing is deliberate and
     tested: `test_a_gate_profile_is_not_a_test_aggregate` records the exact
     false positive an earlier version produced. Checker right.

  #3 declared_invocation_accepted_by_its_own_parser. My YAML put the clause at
     the wrong nesting, so no clause was extracted — and the program answered
     rc 2 "the flow document declares no invocation at all. A verdict over an
     empty population is NOT a pass." It refused instead of passing on my
     malformed input. Checker right, and behaving well.

  #28 two_input_selectors_given_together_must_refuse. I named the collection
     selector `--project-dir`, which is not in the rule's list, so nothing was
     in population. Renaming it `--corpus` made the identical defect go red.
     The checker is right about its own stated vocabulary — but the vocabulary
     itself is the finding, and it is F11's third instance.

REAL (nothing documents the limit):

  #2 declaration_searched_only_inside_a_truncated_window  -> FINDING F9
  #4 denial_that_constitutes_the_value_it_appears_to_negate -> FINDING F10

  And THREE rules answered rc 2 NOT CHECKED, or PASS, on fixtures that fell
  outside a hardcoded VOCABULARY rather than outside the rule
  (explicit_argument..., generated_values..., two_input_selectors...)
  -> FINDING F11. Those three sit between the two columns: the checker is
  right about the rule it states, and the rule it states is a word list.
```

## THE DISAGREEMENT TEST — 836 runs, the brief's named harm

```text
19 paired fixture trees (<name>/defect and <name>/remedy), every body authored
by me from the rule's own predicate. All 22 checkers run over all 38 arms.

  OWNER CHECK — each fixture's owning rule must be red on the defect and green
  on the remedy. 19 of 19 OK, machine-checked. This is my hand reproduction
  restated as a matrix, and it agrees with it row for row.

  DISAGREEMENTS — a checker going rc 1 on ANOTHER rule's REMEDY: ZERO.
  Applying any one of these 22 remedies does not trip any of the other 21.
  That is the property the brief was worried about, and it holds.

  THE ONE NON-OWNER RED, and why it is not a disagreement:
    every_required_metric_key_has_a_producer is rc 1 on my `measonly` fixture —
    on BOTH arms, defect and remedy alike. My fixture's records file carries a
    single metric key, so 8 of that rule's 9 axes are unprovable in it. It is
    answering its own question correctly about a tree I built for a different
    rule. Firing identically on both arms is the signature of noise, not of
    contradiction: the remedy changes nothing it looks at.
    Worth knowing all the same — two of the 22 read the same `records/*.json`
    corpus, so a project with a partial records set gets two reds with two
    different remedies. They do not contradict; they ask different questions.

  RC DISTRIBUTION over all 836 runs:  rc 2 = 506, rc 0 = 309, rc 1 = 21
    (21 = the 19 owner-defects + the 2 measonly noise rows.)
    The 506 is the interesting number: in three runs out of five, a checker
    handed a tree that is not its subject REFUSED rather than certifying. That
    is the empty-denominator doctrine working across the set — with the
    exception F12 records.
```

## THE EMPIRICAL DUPLICATE PROBE

```text
Reading docstrings answers "is there an existing program about this". It does
not answer "does an existing program already fire on this". So I drove 25
adjacent main programs over the defect and remedy arms:

  corpus_cardinality_pin_scan, emitter_population_pin_check,
  landing_tier_checkout_preflight, neutered_gate_tree_check,
  ci_harness_timeout_ceiling_check, checker_execution_wiring_audit,
  gate_is_wired_check, flow_step_executor_coverage_check,
  d3_manifest_declaration_parity_check, hdl_declaration_scan_strips_comments_check,
  p0_gate_invocability_drift_check, prose_polarity_consulted_check,
  shipped_path_portability_check, tracked_symlink_target_present_check,
  manifest_leak_check, signoff_audit, gameable_placeholder_scan,
  silent_decline_audit, flow_gate_enforcement_audit, single_testpath_guard

  THE HARNESS WAS POSITIVE-CONTROLLED, because a "0 discriminating" from an
  instrument nobody proved could answer non-zero is worth nothing — the same
  mistake F10 records me making. Driving programs that DO catch a fixture's
  defect through the identical `drive()`:

      local_clone_does_not_borrow_objects   on clone     defect=1 remedy=0  OK
      printed_remedy_runs_as_printed        on remedy19  defect=1 remedy=0  OK
      only_the_declaring_step_writes_its_output on writers defect=1 remedy=0 OK
      population_guard_asserts_equality...  on popguard  defect=1 remedy=1  no

  3 of 4. The fourth is explained and is a LIMITATION OF THE HARNESS'S
  INVOCATION FORMS, not of its rc logic: `drive()` tries only `--root R` and
  `R`, so an inventory-taking checker falls back to its SHIPPED inventory, whose
  rows match nothing in a one-file fixture, and its stale-inventory-row rule
  fires rc 1 on BOTH arms. Red-on-both is discarded as noise, so the failure
  mode biases toward MISSING a duplicate, never toward inventing one.
  It did not bite here: of the 24 adjacent main programs I could drive, ZERO
  take an `--inventory` flag. The six that could not be driven at all were
  closed by whole-tree finding-set diff instead.

  DISCRIMINATING (red on the defect, green on the remedy): ZERO.
  Red on BOTH arms, i.e. answering about something else: 2
      gameable_placeholder_scan on `mutref` and on `genval`.
  Not drivable on a synthetic fixture (they need the whole tree): 6. Those were
  closed the right way instead — run on main, on jdistmat and on jdistchip, and
  the finding sets diffed:
      emitter_population_pin_check       rc 0 / 0 / 0    0 new lines
      p0_gate_invocability_drift_check   rc 0 / 0 / 0    0 new lines
      flow_gate_enforcement_audit        rc 1 / 1 / 1    0 new lines
      corpus_cardinality_pin_scan        rc 1 / 1 / 1    0 new lines
      gate_is_wired_check                rc 1 / 1 / 1    0 new lines
      checker_execution_wiring_audit     rc 1 / 1 / 1    0 new lines
  Those figures are as of main v1.11.68. At v1.11.69 main has REPAIRED three of
  them — gate_is_wired_check, checker_execution_wiring_audit and
  flow_gate_enforcement_audit are rc 0 on the new main and rc 0 on both COMPOSED
  trees; only corpus_cardinality_pin_scan is still red, identically everywhere.
  See the composed-tree table under F5. The "0 new lines" conclusion — neither
  branch adds a finding to any of them — is unchanged. In particular corpus_cardinality_pin_scan, the
  closest thing on main to `population_pin_without_its_member_set`, produces a
  byte-identical finding set on all three trees — the new rule neither extends
  nor contradicts it.

  EXTENDED TO ROWS 27 AND 28, the two genuinely new rules added while I was
  verifying. Twelve more candidates driven over their defect/remedy pairs: 0
  discriminating. Three could not be driven on a fixture and were closed by
  whole-tree diff at the CURRENT tips instead — flow_step_can_fail_check
  rc 0/0 with 0 new lines, emitter_population_pin_check rc 0/0/0 with 0 new
  lines on both branches, p0_gate_invocability_drift_check already closed the
  same way.

  AND FINALLY SYSTEMATICALLY, because hand-picking adjacents is exactly what
  produced my F5 error. The brief says "grep programs/ for an existing checker
  enforcing the same predicate"; I had been picking candidates by judgement. So
  I swept every one of the 30 new checkers against ALL 1238 main programs by
  docstring-token overlap (Jaccard over 4+-character terms, stop-listed):

      highest score of ANY new checker against ANY main program:  0.17
      new checkers above a 0.20 review threshold:                 ZERO

  THE THRESHOLD WAS POSITIVE-CONTROLLED, since a threshold is an instrument
  too. The one case where two programs are provably the SAME RULE is the F13
  census/gate twins — independent implementations of one predicate:

      explicit_argument_outranks_the_environment_pointer   0.21
      local_clone_does_not_borrow_objects                  0.22
      only_the_declaring_step_writes_its_output            0.22
      provenance_value_is_resolved_not_constant            0.27

  True twins land at 0.21-0.27; nothing in the sweep exceeds 0.17; the two
  ACKNOWLEDGED population extensions score 0.09 and 0.15, correctly below the
  twin band. The separation is real but narrow, and it is if anything
  conservative: those four twins had their census docstrings REWRITTEN to
  declare themselves censuses, which dilutes the overlap, so 0.21 is a floor for
  what a twin scores rather than a typical value.
  The sweep also surfaced, unprompted, the same adjacents I had hand-picked —
  landing_tier_checkout_preflight, corpus_cardinality_pin_scan,
  prose_polarity_consulted_check, _sta_basis, l_doc_field_producer_check — which
  is the retrospective check on my judgement that I could not otherwise have
  made.

  So Q4 is answered FOUR ways for all 30 rows — by name, by fixture, by
  whole-tree finding set, and by a calibrated sweep of the whole program set — and all three say the same thing: no duplicates
  against anything already on main, and no contradictions. The only duplicates
  anywhere in this report are the four the two branches create between
  THEMSELVES, which is F13.
```

## THE DUPLICATE SWEEP, RE-DERIVED — AND IT IS WEAKER EVIDENCE THAN I IMPLIED

```text
Question 4 re-checked at main a4caccefe / mat facc28860 / chip c0e19ace9. The
answer does not change — ZERO duplicates — but WHICH evidence carries it does,
and that is worth correcting.

A BETTER CALIBRATION EXISTS NOW THAN WHEN I FIRST RAN THIS, and it exists
because of F13. The four filename collisions were the same rule written twice by
two authors who had not read each other — a same-rule twin set that is not
hand-picked and not mine. Docstring-token Jaccard over them:

    0.282  only_the_declaring_step_writes_its_output
    0.298  provenance_value_is_resolved_not_constant
    0.291  local_clone_does_not_borrow_objects
    0.254  explicit_argument_outranks_the_environment_pointer
    -> same-rule twins land at 0.254 - 0.298

SWEEPING ALL 32 NEW CHECKERS AGAINST ALL 1240 MAIN PROGRAMS WITH THAT SAME
TOKENISATION, the maximum is 0.234 — TWO HUNDREDTHS below the twin floor.

    0.234  explicit_argument_outranks_the_environment_pointer vs _corpus_location
    0.225  signoff_report_states_its_stage      vs post_route_signoff_corner_check
    0.221  local_clone_does_not_borrow_objects  vs landing_tier_checkout_preflight

I RECORDED THIS SWEEP AS HAVING COMFORTABLE SEPARATION — "twins 0.21-0.27
against a sweep max of 0.17". Re-derived here with the tokenisation stated
above, the margin is a fifth of that. I am NOT claiming the number moved: a
different stopword list and minimum token length give different absolute
values, and I no longer hold the first one to compare against. The claim is
narrower and worse: THIS METRIC'S SEPARATION IS TOKENISATION-DEPENDENT, so a
threshold calibrated on one tokenisation is not evidence under another, and I
presented it as though it were a clean discriminator. It is not. It is a way of
generating CANDIDATES.

SO THE CANDIDATES GET CLOSED INDIVIDUALLY, which is what the evidence actually
supports:

  * `_corpus_location` — the top score, and it CANNOT be a duplicate gate: no
    `main()`, no `__main__` block, a leading underscore. It is a library helper
    answering "where is the published corpus". The highest number in the sweep
    is against something that is not a checker.
  * `post_route_signoff_corner_check` — a real gate, a different predicate. It
    is a Step-23 multi-corner SLACK gate; the new rule is about whether a report
    STATES which side of place-and-route it came from. High token overlap
    because both live in signoff vocabulary; no shared verdict.
  * `landing_tier_checkout_preflight` — the genuinely adjacent one, and the
    reason the empirical probe exists. It was already DRIVEN over that rule's
    defect and remedy arms and found non-discriminating.

WHAT ACTUALLY CLOSES QUESTION 4 IS THE EMPIRICAL PROBE, not the sweep: 25
adjacent main programs driven over defect and remedy arms, positive-controlled
against programs known to catch those fixtures, ZERO discriminating. The sweep's
job is to make sure the probe's 25 were the right 25 — and re-run today it
nominates the same neighbourhoods, which is the useful thing it does.
```

## THE TWO CLAIMS THE BRIEF ASKED TO BE CHECKED HARDEST

```text
CLAIM 1 (jdistmat) — "all ten rule_name fields renamed to slugs, nothing
deleted, the sentence moved to `title`."   VERIFIED, exactly as stated.

    Parsed recoveries.json before and after and compared record by record:
        11 records before, 11 after.
        Records 1-10 (bucket A): the ONLY key whose value changed is
            `rule_name`, from the sentence to its slug — in every case exactly
            `old.replace(" ", "_")` and exactly the new program's filename stem.
            The ONLY key added is `title`, whose value is the old `rule_name`
            VERBATIM. Every other key/value pair is byte-identical.
        Record 11 (bucket C) is UNTOUCHED — `old == new` as whole objects. It
            already carried `title` and never had `rule_name`, so the rename
            makes the file MORE consistent, not less.
        Zero string values from any old record are absent from its new record.
    (My first pass reported 30 "lost" strings. That was my bug: I compared
     against `json.dumps(b)` with the default ensure_ascii=True, so every
     em-dash and CJK character escaped and failed a substring test. With
     ensure_ascii=False the loss set is empty. Recorded because a reader
     re-running the check the naive way will see the same false alarm.)

CLAIM 2 (jdistchip) — "found and fixed 2 true positives with its own new
checkers."   VERIFIED. Both are real, and I reproduced both by REVERTING the
fix in my own tree and re-running the checker.

  TP1  ip_catalog_reproduce_pull.py::_git_clone_shallow — the pinned-commit
       `git checkout` result was discarded and the function returned True
       regardless, so a reproducibility comparison made against the DEFAULT
       BRANCH was published as a verdict about the PINNED COMMIT.

         [as shipped]  examined 3 revision-selecting checkout site(s)
                       PASS — every revision-selecting checkout inspects its
                       outcome                                          rc 0
         [fix reverted]
           .../ip_catalog_reproduce_pull.py:60: a revision is checked out and
             the outcome is never inspected — no check=True, no returncode test
             and no rev-parse of the resulting HEAD. A checkout that silently
             failed leaves the tree on its previous revision, and every
             measurement after it is about a commit nobody named.
           FAIL — a prepared checkout never confirms its revision       rc 1

  TP2  phase3_one_shot_runner.py::_emit_antenna_report — the artefact carried a
       RESOLVED subject block and, three lines below it, a TYPED source path,
       so it made two source claims and the typed one could never look wrong.

         [as shipped]  examined 2 resolved-subject artefact write(s)     rc 0
         [fix reverted]
           .../phase3_one_shot_runner.py:37700: this write emits a RESOLVED
             subject block and also types the source path 'phase3/stage3/pnr/
             openroad.log'. ... Render it from the value the emitter resolved.
                                                                        rc 1

       The repair was checked, not assumed: `pnr_log` is assigned
       unconditionally at function-body indentation (line 37637) and the new
       f-string reads it at 37725; the file compiles.

  Neither is a checker misreading something. Both are the exact shape the rule
  describes, and both fixes are minimal with the contract unchanged.
```

## FINDINGS

```text
Numbered in the order I found them, listed in order of severity. Read F5b
before F1 and F15: it separates "rc 1, a fact about the tree" from "BLOCKS, an
intent nothing fulfils", and both findings are about the first, not the second. F13 was the
hard blocker for landing BOTH; the author ruled on it and I verified the
resolution, so it is closed. F14, F1, F9 and F12 must be fixed before their own
branch lands — F14 is the one that also keeps the COMPOSED tree red. Everything
below F11 is a follow-up. F13 and F14 were both found on re-checks after the
branches moved under me, and F14 corrects a claim I had made in this report.

F13 *** RESOLVED BY THE AUTHOR, VERIFIED BY ME — was a HARD BLOCKER ***

    RESOLUTION, at jdistmat 222a24479, commit bebd9c1e1 "ruling(F13): my four
    are CENSUSES, not gates — renamed, and they say so". The author accepted the
    ruling and gave the gate NAME to the refusing instrument (jdistchip's),
    renaming their own four with a `_census` suffix via `git mv`. I verified
    every claim in that commit rather than taking it:

      CLAIM "nothing left for the add/add conflicts to conflict over"  TRUE.
        Trial merge of 222a24479 then 12b227b4b onto main: 4 conflicts, ALL of
        them the generated count files (F4's mechanical ones). ZERO add/add.
        Down from 12 conflicts of which 8 were add/add on a program + its test.

      CLAIM "exit status is now informational by construction"  TRUE, and the
        censuses still REPORT. On my own defect fixtures all four exit 0 and
        still print their finding — e.g. the two-writer census prints
        "[CENSUS] 1 declared output path(s) have two writers: reports/phase3/
        antenna.json declared by step(s) 23, written by: antenna_report_gen.py,
        phase3_runner.py". A census that exits 0 AND says nothing would have
        been worse than the collision; this is not that.
        (I briefly measured "0 finding lines" for one of them. That was my grep
        pattern, not the census. Checked and corrected.)

      CLAIM "each docstring opens with the declaration, not a footnote"  TRUE.
        All four carry, at line 3, "THIS IS A CENSUS, NOT A GATE. IT MUST NOT BE
        WIRED AS A BLOCKING CHECK", each naming its jdistchip gate by path, and
        each recording WHY two implementations existed so the next reader does
        not rediscover the collision as a mystery.

      VERIFIED AT THE LEVEL THE RULING IS STATED AT, not by a proxy for it.
        My first check was that the two branches' added-file lists no longer
        intersect, and I INFERRED from that which implementation the composed
        tree carries. That is inference. jdistchip made the same point about
        their own record at 951c778a5 — "a proxy that happens to be right is
        still not the measurement" — so I measured it directly, by blob hash,
        in my own composed tree:

            for all FOUR programs and all FOUR of their tests,
                composed blob == jdistchip's blob, byte for byte
            and all four `*_census.py` present beside them,
                composed blob == jdistmat's blob, byte for byte

        So the composed tree carries the GATE at each disputed filename and the
        CENSUS beside it, which is exactly what the ruling says it should. This
        is the single thing F13 turns on: if a merge had silently taken the
        other implementation at one filename, someone lands the wrong instrument
        and every verdict from it is about a different rule.

    So the four rules are now complementary by construction rather than in
    contradiction: the WIDE population with recorded debt reports, and the
    NARROW population refuses. That is the disposition F13 asked for, and it is
    the one I would have recommended — the semantics match what I measured, that
    matrix waived where chip repaired.

    WHAT REMAINS OF F13: nothing blocking. The four count-file conflicts are
    F4's, and are mechanical.

    THE ORIGINAL FINDING IS PRESERVED BELOW, because the measurement is what
    justified the ruling and a reader should be able to check it.

F13-AS-FOUND  (the measurement that justified the ruling, on tips
    3c3a6e0e4 / 317cef847) — THE TWO BRANCHES SHIPPED FOUR
    RULES WITH THE SAME FILENAME, DIFFERENT IMPLEMENTATIONS, AND ON TWO OF THEM
    OPPOSITE VERDICTS ABOUT THE SAME TREE. This is the exact harm the brief
    named, and it is no longer hypothetical.

    jdistmat's 9 new commits add FOUR programs that jdistchip already owns:
        explicit_argument_outranks_the_environment_pointer.py
        local_clone_does_not_borrow_objects.py
        only_the_declaring_step_writes_its_output.py
        provenance_value_is_resolved_not_constant.py
    (jdistmat now adds 14 programs, jdistchip 12; four names are in both.)

    They are not near-copies, they are independent rewrites:
        explicit_argument...    matrix 250 lines / chip 241   425 differing
        local_clone...          matrix 282 / chip 303          529 differing
        only_the_declaring...   matrix 290 / chip 288          522 differing
        provenance_value...     matrix 206 / chip 208          360 differing
    They do not even share a CLI: the matrix copies take `--root`, the chip
    copies take a positional path. Feeding one the other's invocation is rc 3.

    MEASURED DISAGREEMENT — both versions, same tree (origin/main), each with
    its own CLI:
        explicit_argument...       matrix rc 0  |  chip rc 0     agree
        local_clone...             matrix rc 0  |  chip rc 0     agree
        only_the_declaring...      matrix rc 0  |  chip rc 1, 6 findings   ***
        provenance_value...        matrix rc 0  |  chip rc 1, 1 finding    ***

    WHY THEY DISAGREE, AND IT IS NOT A BUG IN EITHER — IT IS A POLICY SPLIT.
    Their denominators are different rules wearing one name:
        only_the_declaring...  matrix: 121 declared paths, 23 with a resolvable
                                       write, 2 with >1 writer, 2 INVENTORY ROWS
                                       APPLIED -> PASS
                               chip:   195 declared outputs, 55 with a writer,
                                       6 findings, NO inventory -> FAIL
        provenance_value...    matrix: 1273 modules, 490 source-naming writes,
                                       12 typed from a constant, 10 INVENTORY
                                       ROWS APPLIED -> PASS
                               chip:   2 resolved-subject writes, 1 finding,
                                       no inventory -> FAIL

    AND ON TWO SITES THE TWO BRANCHES TAKE OPPOSITE ACTIONS ON THE SAME DEFECT:

      phase3_one_shot_runner.py :: source :: phase3/stage3/pnr/openroad.log
        jdistchip  REPAIRS it in code, and counts it as one of its two true
                   positives (my CLAIM 2, TP2 — I reproduced it by reverting).
        jdistmat   WAIVES it, in provenance_constant_inventory.json, reason:
                   "Not repaired here: each is a change to what that emitter
                    publishes, and belongs to the lane that owns the artefact."

      reports/spare_cell_coverage.json (two writers)
        jdistchip  reports it as a live FAIL (one of the six in F1).
        jdistmat   WAIVES it, in declared_output_writer_inventory.json, reason:
                   "The shape the chip capture measured, on its own evidence
                    path ... Recorded, not repaired: which of the two is the
                    declaring producer is a flow-ownership decision, and the
                    record is explicit that fixing the clobber ALONE would turn
                    the cell green while leaving the real gap invisible."

    So jdistmat knows about the chip lane's findings and has decided to record
    them; jdistchip has decided to repair one and refuse on the other. Both
    positions are defensible. What is not defensible is shipping both under one
    filename, because then the repository holds two answers and the one that
    wins is whichever file survives the merge.

    THE MERGE DOES NOT RESOLVE IT. Trial merge of the two new tips onto main:
    12 conflicts, of which EIGHT are add/add on a program and its test —
        programs/{explicit_argument,local_clone,only_the_declaring,
                  provenance_value}*.py  and their four test files
    plus the four generated count files from F4. An add/add conflict cannot be
    auto-resolved and must not be hand-merged: the two files are different
    rules, not two edits of one.

    WHAT HAS TO HAPPEN BEFORE EITHER LANDS. Someone has to decide, per rule,
    which of the two definitions the repository holds — the wide-population
    one with an inventory, or the narrow-population one that refuses — and the
    losing branch drops its copy. That is a judgement about how much debt the
    repo records versus refuses, and it is the owner's call, not mine. It
    cannot be deferred to the merge, and it cannot be settled by land order:
    landing matrix first makes the tree PASS on two defects that chip's copy
    would then have to re-open, and landing chip first makes the tree FAIL on
    six rows that matrix's copy would then waive.

    RE-MEASURED AT THE NEW TIPS, AND ON ONE OF THE FOUR IT IS SHARPER THAN A
    POLICY SPLIT. I ran both copies of each colliding rule over my own paired
    fixtures (the 988-run matrix):

      local_clone_does_not_borrow_objects        AGREE both directions
                                                 (defect 1/1, remedy 0/0)
      only_the_declaring_step_writes_its_output  AGREE both directions
                                                 (defect 1/1, remedy 0/0)
      -> for these two the predicates match; the real-tree disagreement is
         population size plus jdistmat's inventory, exactly as described above.
         Two of four is the good case, and it is still a collision: one of the
         two files has to be deleted, and the inventory decision travels with
         whichever survives.

      explicit_argument_outranks_the_environment_pointer   DO NOT AGREE, and
      neither copy dominates. They are two different rules under one filename:

        On CHIP's canonical defect — a pointer that silently redirects the
        subject and prints nothing naming the tree scanned:
            chip   rc 1, names file and line
            matrix rc 0  "env writes onto a parsed argument: 0"   <- misses it

        On MATRIX's canonical defect — `if _env_tree and args.tree:
        args.tree = _env_tree`, the pointer overruling an argument the caller
        NAMED:
            matrix rc 1     chip rc 1      both catch it

        On MATRIX's documented-CORRECT form, which its own docstring spells out
        in as many words — `elif _env_tree and not args.tree: args.tree =
        _env_tree`   "CORRECT — the pointer fills a gap":
            matrix rc 0     accepts it, as its own rule requires
            chip   rc 1     REFUSES IT

      provenance_value_is_resolved_not_constant   DO NOT AGREE either, and
      this is the worst of the four: EACH IS BLIND TO THE OTHER'S INSTANCES.
        Driven over origin/main with an EMPTY inventory, the matrix copy
        reports 12 candidates and 10 findings, every one a `source = '<path>'`
        data field — and phase3_one_shot_runner.py:37700, the site jdistchip
        found and REPAIRED and counts as a true positive, IS NOT AMONG THEM.
        It reports :19171 in the same file instead, a different write.
        Run the other way, chip's copy answers rc 2 NOT CHECKED on a fixture
        built to the matrix copy's predicate, because that fixture contains no
        resolved-subject write for it to look at.
        So the wide one (490 candidate writes, 10 waived) and the narrow one
        (2 candidate writes, 1 repaired) are not two qualities of one rule and
        neither is a superset. Whichever file survives the merge, a whole class
        of this defect stops being guarded — and nothing in either docstring
        tells the reader that.

      Chip is not malfunctioning. Its rule is "a pointer reader must NAME the
      tree it scanned", my fixture prints nothing, so by chip's own standard it
      is a finding. That is exactly the problem: matrix accepts a silent pointer
      that only fills a gap, chip requires disclosure unconditionally. Land
      matrix's copy and the repository accepts code chip's copy refuses; land
      chip's and the reverse. Those two sentences do not merge — someone has to
      say which one the repository means.

    A SECOND THING THE SIDE-BY-SIDE SHOWS, corroborating F12 without needing a
    synthetic empty tree: across every fixture where a rule has no subject
    matter, the matrix copies answer rc 0 PASS and the chip copies answer rc 2
    NOT CHECKED — the same rule name, one certifying an empty scan and one
    refusing it.

    This supersedes F4, which described the count-file conflicts as mechanical.
    Four of the twelve still are; eight are not.

F15 BLOCKING (matrix) — A NEW GATE SHIPS RED ON A FINDING THAT IS FALSE, AND A
    TEST PINS THE FALSE RED. The sibling lane had already built this exact rule,
    measured the same verdict as false, and rewrote it — and wrote down why.

    `gate_proof_vocabulary_has_a_producer` (jdistmat 89b1c1969) exits 1 on its
    own tree, deliberately and declared, reporting:

        [FAIL] 1 axis/axes prove from names nobody produces:
           drv:  timing.drv.violations, timing.drv.max_tran_violations,
                 timing.drv.max_cap_violations, timing.drv.max_fanout_violations

    ITS CONSEQUENCE CLAIM IS ABOUT RUNTIME — "a gate that cannot be answered;
    every run says not determined, the overall verdict is never reached, and no
    candidate can ever be promoted" — but it INFERS that from a SOURCE scan: a
    set difference between the axis table and the names emitting modules
    declare as literals.

    THE CLAIM IS FALSE — AND MY FIRST DIAGNOSIS OF WHY WAS WRONG. I attributed
    it to format-built names invisible to a literal scan. It is simpler and
    worse than that: a SCAN-SCOPE BOUNDARY. Re-verified directly:

      * all four keys appear as emitted `"metric":` values in real run records
        (`ppa-crosslayer/records/trials/b000/drv_records.json` and others);
      * THE PRODUCERS ARE ALIVE AND DECLARE THE KEYS AS PLAIN LITERALS —
            ppa-crosslayer/tools/drv_records.py:73  `_CHECKS` names
                timing.drv.max_tran_violations, .max_cap_violations,
                .max_fanout_violations as string constants, and :156 emits them
                with `"status": "MEASURED"`;
            ppa-e2e/tools/signoff_records.py:204   `emit("timing.drv.violations",
                "count", "openroad", ...)` — the fourth key, also a literal.
        A literal scan WOULD have found all four. It did not, because both
        producers live OUTSIDE `programs/`, which is the gate's scan root.
      * so the gate's premise is true of its scan root and FALSE of the
        repository. Its verdict sentence — "on any design, forever" — is a
        claim about the repository drawn from a directory.

    I did not find the scope explanation myself; jdistchip's commit b794c662c
    did, having first chased the one possibility that would have REVERSED their
    position (that the 63 MEASURED rows were historical, from a producer since
    removed). I verified their finding rather than adopting it: both producer
    files exist on the new main and on the composed tree, and both declare the
    keys as literals.

    THE REMEDY CHANGES WITH THE DIAGNOSIS — AND I TESTED IT, WHICH SHOWED MY
    ONE-LINE VERSION WAS HALF A REMEDY. I said "widen the scan to the trees that
    actually emit metric records". Applied in a throwaway copy — adding
    `ppa-crosslayer/tools` and `ppa-e2e/tools` to the walk:

        emitting modules      38 -> 41
        names they declare   143 -> 169
        the drv finding      four keys -> ONE

    Three of the four resolve. `timing.drv.violations` does not, and the reason
    is the second half I had missed: the gate's population is a RELATION — "in
    the `_ppa` package or IMPORTS it" — and `ppa-e2e/tools/signoff_records.py`,
    which declares that key as a literal at line 204, mentions `_ppa` only in
    its docstring and comments. It never imports it. So a real producer stays
    invisible however wide the root, because the relation uses package coupling
    as a proxy for "is a producer".

    SO THE REMEDY IS TWO-PART: widen the root AND define the producing side by
    what it EMITS rather than by what it imports. I IMPLEMENTED BOTH PARTS AND
    IT DOES CLEAR THE VERDICT:

        emitting modules   38 -> 44      names declared   143 -> 178
        axes with no produced name   1 -> 0
        [PASS] every axis proves from at least one produced name      rc 0

    BUT MY IMPLEMENTATION OF PART TWO IS TOO CRUDE, and its own suite says so.
    I tested "emits" as a substring search for the schema id
    `vibeic.ppa.metric.v1`. Three tests then fail: the pinned false red (which
    SHOULD fail — that is the point), but also
    `test_the_consumer_is_excluded_and_that_is_what_makes_it_discriminate` and
    `test_a_proof_name_only_the_consumer_declares_is_not_produced`. The reason
    is that the CONSUMER mentions the schema too — `_ppa/feasibility.py` carries
    the string twice — so a substring test re-admits the very module the gate
    excludes on purpose, and the discrimination those tests pin is lost.

    IMPLEMENTED AND MEASURED, 2026-08-22 — AND IT FOUND SOMETHING WORSE THAN A
    PINNED RED. I had left this as a recommendation. This session's lesson is that
    an untested recommendation of mine is where I go wrong, so I built it.

    The predicate: a module is a producer when it CONSTRUCTS metric records and
    WRITES them — three conjuncts, a `"metric"` key or an `emit(...)` call, a
    MEASURED / NOT_MEASURED status constant, and a write call. Each conjunct earns
    its place; the consumer satisfies the first two.

        gate                       rc 1  ->  rc 0
        emitting modules             38  ->  50
        names they declare          143  ->  191
        axes with no produced name    1  ->  0

        discrimination preserved, checked directly:
            consumer `_ppa/feasibility.py`   _writes_metric_records() = False
            ppa-crosslayer/tools/drv_records.py                       = True
            ppa-e2e/tools/signoff_records.py                          = True

    THREE OF THE GATE'S EIGHT TESTS THEN FAIL, and all three encode the false
    verdict. I expected one:

      1 `test_the_shipped_tree_is_RED_on_drv` — asserts rc 1. Pins the red itself;
        failing is the point.
      2 `test_a_proof_name_only_the_consumer_declares_is_not_produced` — asserts
        the four `timing.drv.*` are NOT produced, on a docstring premise ("occurs
        in the consumer and in tests, nowhere else") that is untrue of the
        repository. Fails with "timing.drv.violations is now produced — re-derive
        the finding", which is exactly right.
      3 `test_the_consumer_is_excluded_and_that_is_what_makes_it_discriminate` —
        and this one is the finding. It asserts `unprovable_correct` is NON-EMPTY.
        The gate exits 1 if and only if some axis is unprovable. SO THIS TEST
        REQUIRES THE GATE TO BE RED. No tree on which the gate passes can satisfy
        it; it failed with a bare `assert []`.

    SO THE GATE CANNOT GO GREEN WHILE ITS OWN SUITE IS GREEN. That is stronger
    than "a test pins the false red", which is what I had written, and it is the
    reason to fix this before landing rather than after: the red is not one
    assertion to update but a premise built into three, one of which forbids the
    passing state outright.

    THE THIRD TEST'S INTENT IS SOUND AND ITS PROXY IS NOT, which makes it cheap to
    repair. It wants "the exclusion must change the answer, or the exclusion is
    doing nothing" — a good thing to pin. Measured after the remedy:

        produced WITH the consumer excluded    191 names
        produced WITHOUT the exclusion         195 names
        contributed by the consumer alone        4 — area.total_um2,
            physical.lvs.violations, timing.hold.violations, timing.setup.violations
        unprovable axes, either way             [] and []

    The exclusion still changes the answer; it no longer changes which AXES are
    unprovable. So assert the property directly — that excluding the consumer
    REMOVES NAMES — instead of through an axis count that only holds while the gate
    is broken. One line, and the test then pins what it says it pins.

    THE CORRECT PREDICATE IS "WRITES METRIC RECORDS", NOT "MENTIONS THE SCHEMA":
    a module that CONSTRUCTS a record with a `"metric":` key and a MEASURED /
    NOT_MEASURED status and writes it, versus one that reads them. Both real
    producers do the first (drv_records.py:156, signoff_records.py:204) and the
    consumer does the second. So the direction of the remedy is right and
    measured; the one-line version of it is not, and whoever implements it
    should expect the consumer-exclusion tests to be the thing that keeps them
    honest.

    The widening alone is still worth doing: it takes the finding from four keys
    to one and the gate's own docstring already records that it moved off a
    directory-shaped population once for the same reason.

    Either way, or say the gate speaks only for `programs/` and stop concluding
    anything about "any design, forever" from it.

    A NOTE ON MY OWN EVIDENCE. One of my three original supports was "driving
    jdistchip's producer table resolves a producer for every one of the four".
    jdistchip has since fixed a bug in that very rule (094c2cb7e, "the metric
    gate counted the consumer as its own producer"), so that support was weaker
    than I presented it. The finding does not depend on it: the record evidence
    and the two literal-declaring producers are independent of jdistchip's gate
    entirely.

    THE SIBLING LANE'S OWN ACCOUNT, which pointed the same way from a different
    direction. jdistchip's
    `every_required_metric_key_has_a_producer` carries a section headed "WHY
    THIS IS EMPIRICAL AND NOT A SOURCE SCAN — MEASURED, AND IT MATTERED":

        "This was FIRST written as a static cross-reference ... Swept, it
         declared the whole `drv` axis STRUCTURALLY UNPROVABLE and named four
         keys as having no producer. That verdict was FALSE, and false in the
         blocking direction — it would have stopped a flow that works."

    Run over one tree the two disagree exactly as that predicts: the chip rule
    rc 0 "every axis has at least one fully-produced proof group"; the matrix
    rule rc 1 "drv proves from names nobody produces". They do not collide by
    filename, so this is not an F13 merge problem — it is worse in one respect:
    both would land, and the repository would hold a red gate asserting
    something its neighbour has already measured as untrue.

    THE PINNED RED IS THE PART THAT COMPOUNDS. `test_the_shipped_tree_is_RED_on_
    drv` asserts rc 1. So the false verdict is now a fixture: if anyone repairs
    the rule or the tree, the SUITE goes red and the instruction beside it says
    not to weaken the gate. A wrong answer that a test defends is harder to
    remove than one that merely exists.

    NOT a criticism of shipping red per se — see row 29 and row 32, where the
    same branch ships red on findings I verified as TRUE, declares it, and pins
    it. That pattern is sound. This one is the same pattern applied to a false
    positive.

F16 MINOR-TO-MEDIUM (chip) — THREE GATES HAVE NO DEMONSTRATED REAL-HISTORY
    CONTROL, and their capture record claims they do. This is jdistchip's own
    finding (4445f34a2) extended to three gates that commit did not cover.

    I ran all twelve chip gates against four past revisions of main AND against
    the capture commit e36d81c0a (v1.11.33) itself:

        fire on real history (rc 1)  5   every_required_metric_key,
                                         only_the_declaring, provenance_value,
                                         signoff_report (after its repair),
                                         prepared_checkout
        rc 2 by design               1   pytest_aggregate — a repo is not a run
                                         tree, which its own test pins
        SILENT on every revision     6

    jdistchip accounted for three of the six in that commit — local_clone
    narrowed so it cannot redden the remedy its sibling prints, printed_remedy's
    defect since landed as fixed, explicit_argument narrowed by statement — and
    repaired the fourth. THE REMAINING THREE ARE:

        declared_basis_matches_the_session_inputs
        generated_values_state_whether_they_were_read_or_defaulted
        measurement_only_artefact_is_not_a_verdict_source

    and they are NOT silent for want of a population: on a4caccefe they examine
    22 (session, report) pairs, 3 call sites of 2 helpers, and 9694 axis-key
    records across 1275 JSON files respectively. They look at a great deal and
    find nothing, on every revision including the one their capture was measured
    on.

    Their capture record says of all three `fires_on_original: Yes`, and of two
    `measured_after: Not fixed`. That is the same contradiction jdistchip stated
    about their other five: "Both cannot be true."

    THE LIKELY INNOCENT EXPLANATION, and it is worth stating because it decides
    what to do. All three incidents are described as living in RUN ARTEFACTS
    rather than in tracked source — "the shipped artefact", "the consumed
    artefact", "the emitted constraint file". A gate scanning a repository may
    legitimately never meet them. If so the gates are sound and the CAPTURE's
    `fires_on_original` claim is what is unsupported, because it cannot be
    reproduced from anything in the repository.

    Either way the remedy is the one jdistchip already applied elsewhere: give
    each a control that can actually fire — a committed fixture artefact
    carrying the original defect — or restate `fires_on_original` as measured
    against a live run and not against the tree. Not a blocker: none of the
    three is wired (F5b), and all three pass their own synthetic controls, which
    I reproduced by hand (rows 11, 14, 16).

    I RAN THE SAME CONTROL ON jdistmat, because a finding I only look for on one
    branch is not a finding. Of its six testable non-deliberately-red gates,
    FOUR fire on real history (content_pinned on three of four revisions,
    wall_clock, population_guard, two_input_selectors) and TWO are silent on
    every one — `declared_invocation_accepted_by_its_own_parser` and
    `published_absence_claim_is_rechecked_against_the_tree`. Both have
    populations: the first drives the flow's declared clauses and reports
    "refused by their parser: 0"; the second reports 328 absence-shaped strings
    with 0 attached to a path.

    BUT THERE IS NOTHING TO CONTRADICT THERE, AND THAT IS ITSELF THE POINT.
    jdistchip's record carries `fires_on_original`, `fires_on_a_different_
    instance`, `measured_before` and `measured_after` — falsifiable fields, and
    it is precisely because they exist that this control could catch anything.
    jdistmat's records carry no equivalent: the matrix-lane schema is
    {docstring, pattern, measurement, measured_on_commit, original_and_class,
    fix_action, notes} and the ppa-lane schema is thinner still, with no
    `measurement` and no `measured_on_commit` at all.

    So "no contradiction found on jdistmat" is a WEAKER statement than it looks.
    jdistchip made a checkable claim and it turned out to be wrong for three
    gates; jdistmat made no such claim, so the same two silent gates cannot be
    convicted or cleared. The stronger record is the one that caught its author
    out, and if either lane should copy the other here it is jdistmat copying
    jdistchip's `fires_on_original` field.

F14 BLOCKING (matrix) — jdistmat TURNS AN EXISTING MAIN GATE RED, and my own
    earlier claim that it did not was wrong. Correcting myself in full.

    WHAT I CLAIMED, AND WHY IT WAS UNSOUND. F5 below said "NEITHER BRANCH
    REGRESSES A REPO-LEVEL GATE". I had run FIVE gates I picked by hand
    (plugin_full_audit, single_testpath_guard, source_chip_agnostic_check,
    gate_is_wired_check, checker_execution_wiring_audit) and generalised from
    them to every gate. That is a claim wider than its measurement — the exact
    shape this whole capture is about — and it is false.

    HOW I FOUND OUT. Not by re-reading my own work: jdistchip's commit ffa316c78
    reported a composed-tree failure and attributed it to the census lane. I
    verified it rather than accepting it, and the attribution is right.

    THE PROPER MEASUREMENT, which is what I should have done first. I extracted
    the gate list from the repository's OWN runner, `tools/ci/repo_hygiene_
    gates.sh` — 29 gates — and ran all 29 on three trees rather than hand-picking
    again. (I did not RUN that script: it is 1674 lines, it creates worktrees,
    and this repo is shared by several agents. I took its gate list and drove the
    gates read-only.)

        [SUPERSEDED — this drove each gate with NO arguments. The runner
         passes argv that changes what several of them look at. The
         authoritative figures are the 28-invocation replay: 26/0/2.]

        main       81cd5321b   24 rc 0,  0 rc 1,  5 not-driveable-without-args
        jdistchip  ffa316c78   24 rc 0,  0 rc 1,  5     IDENTICAL TO MAIN
        jdistmat   222a24479   23 rc 0,  1 rc 1,  5
    (Re-run against the NEW main a4caccefe at the current tips: same three
     lines, same single flip. See "MAIN MOVED UNDER THE BASELINE".)

    EXACTLY ONE GATE FLIPS, and only on jdistmat:

        atomic_artifact_write_check     main = 0     jdistmat = 1

    THE FAILURE IS jdistmat'S OWN PROGRAMS. The gate is a RATCHET against
    `_atomic_artefact_residual.json`:

        1256 program(s) parsed; 531 write their declared report destination
        NON-atomically (residual baseline 515)

    531 - 515 = 16 unregistered offenders at the tip I first measured; at the
    CURRENT tips (unchanged through every push since 4cd606564) it is
    533 - 513 = TWENTY, the
    branch having kept adding programs. The named ones are jdistmat's own
    new files — all four `*_census.py`, plus population_guard_asserts_equality_
    not_a_floor, population_pin_without_its_member_set, published_absence_claim_
    is_rechecked_against_the_tree, reference_control_resolved_through_a_mutable_
    ref, registry_is_the_iteration_domain, spawned_gate_whose_status_is_
    discarded, two_input_selectors_given_together_must_refuse,
    wall_clock_bound_standing_in_for_a_verdict. Every one writes its `--json`
    output with a plain `.write_text(...)`.

    CAN THEY JUST BE REGISTERED IN THE BASELINE? I first wrote that they could
    not, "refused by the ratchet's own test
    (test_the_shipped_residual_only_ever_shrinks)". I had taken that from
    jdistchip's commit message, which had taken it from that test's NAME. Then
    jdistchip retracted it, having tested the GATE and found registering
    permitted. Neither of us had measured the whole instrument, so I did.

    MEASURED, by adding all the unregistered offenders to
    `_atomic_artefact_residual.json` in my own tree and re-running:

        atomic_artifact_write_check              rc 0
        atomic_artifact_write_check --strict     rc 0
        the test suite                           2 FAILED

            test_issue1470_atomic_declared_report.py
                ::test_the_green_was_not_bought_by_widening_the_register
            test_issue1082_atomic_tranche_40_gates.py
                ::test_the_recorded_baseline_followed_the_tree_down

    So BOTH earlier statements were wrong in different directions, and the truth
    is the union: THE GATE PERMITS REGISTERING; THE SUITE REFUSES IT. The guard
    is not the gate's `--strict` arm — that compares the current count against
    the count in the COMMITTED baseline, so editing the baseline in the same
    change moves both numbers together and it cannot see the growth, exactly as
    jdistchip found. The guard is a TEST, and not the one either of us named:
    `test_the_green_was_not_bought_by_widening_the_register`, whose docstring
    says in as many words "Adding these two names to the residual would ALSO
    have exited 0", and which asserts a CEILING on the register's size. Its
    sibling pins that the baseline followed the tree down, "because it only ever
    fails on growth".

    The repository, in other words, already knows its gate is weaker than its
    own contract and has put the real guard in the suite. Which is worth knowing
    before anyone reasons from the gate alone.

    I THEN CONVERTED ALL TWENTY AND RAN THE LANDING SUITE. This is the test of
    the VERDICT, not just of the remedy: does fixing F14 actually make the
    branch land? Measured, in a throwaway worktree at f4e8d0875:

        all 20 offenders converted, each verified by an `ast.ImportFrom` node
        atomic_artifact_write_check      rc 1  ->  rc 0   (residual back to 513)
        the 28 wired landing invocations IDENTICAL TO MAIN
                                         26 rc 0, 0 rc 1, 2 rc 2 (tolerated)
        the branch's own 20 test files   206 passed

    So the verdict is validated end to end: the conversion is mechanical, it
    clears the only landing-suite failure, and it breaks nothing on the branch.

    ONE OPERATIONAL CAVEAT, found the hard way. With the 20 edits UNCOMMITTED
    the suite still failed — at a different gate: `policy_direction_pin_check`
    returned rc 2, which the `run` wrapper does NOT tolerate. Its message says
    why: "parallel mutation verification needs a clean tracked checkout because
    isolated workers are created from HEAD". Committing the conversion made it
    rc 0. Whoever does this work must COMMIT before running the suite, or they
    will chase a second failure that is an artefact of a dirty tree — which is
    exactly the class of mistake this report keeps recording.

    THE SINGLE-SITE TEST THAT PRECEDED IT, kept because it isolates the cost per
    file. Converted ONE offender in a throwaway copy —
    `population_pin_without_its_member_set.py:368`, its `--json` write — to the
    helper, using the idiom the repository already uses elsewhere
    (`from _atomic_artefact import write_json as atomic_write_json`, as in
    analog_netlist_include_order_check.py and two others):

        offenders BEFORE   533   (baseline 515)
        offenders AFTER    532
        the rule still works: my defect fixture rc 1, my remedy fixture rc 0,
        and the --json output still written, 396 bytes.

    So the remedy is real and each conversion costs one import line and one call
    site. TWO CAVEATS I only found by doing it:
      * it is NOT a drop-in. My first attempt put a bare `import
        _atomic_artefact` at the wrong place, the name never resolved, and the
        program degraded to rc 2 "the walk did not complete (NameError)". The
        established idiom is a `from ... import ... as ...` beside the other
        module-level imports.
      * my own check that the edit had landed was a FALSE POSITIVE — I tested
        that the string "_atomic_artefact" appeared in the file, which the
        inserted CALL satisfied while no import existed. The second attempt
        verified an actual `ast.ImportFrom` node instead. Twenty conversions
        done by grep-and-eyeball would repeat that.

    PRACTICAL CONSEQUENCE FOR jdistmat, unchanged by any of that: converting is
    the remedy. The gate names it — "Remedy: `from _atomic_artefact import
    write_json` and write through it. See vibe-ic#1082" — and the baseline's own
    `how_to_shrink` field says the same. Registering would buy a green gate and
    a red suite. Two programs were converted since the baseline, so the path is
    well-trodden.

    I PROPAGATED AN UNTESTED CLAIM. It came to me in a commit message, it was
    plausible, and I repeated it in a finding that directs someone's work. The
    correction came from testing it, which is the only thing that was ever going
    to correct it.

    AND THIS ONE IS ACTUALLY WIRED — WHICH IS WHAT SEPARATES IT FROM F1 AND F15.
    Under F5b I record that five gates sit at rc 1 in composition and not one is
    wired, so none of them stops anything. `atomic_artifact_write_check` is the
    exception, and I checked it rather than assuming either way:

        tools/ci/repo_hygiene_gates.sh:1795
            run "declared reports are written atomically" "$PLUGIN" \
                python3 programs/atomic_artifact_write_check.py programs

        _gate_dispatch.sh:1158   run() { _dispatch 0 0 "$@"; }
            — the first 0 means rc 2 is NOT tolerated; rc 1 is a real finding
              and FAILS THE SUITE.

    Re-run under that exact invocation (cd to the plugin, positional `programs`,
    which is not how my sweeps called it):

        new main a4caccefe   rc 0   513 non-atomic writes, baseline 515
        chip-composed        rc 0   513   identical to main
        matrix-composed      rc 1   533   twenty unregistered

    So F14 is the ONLY finding in this report that stops anything today: landing
    jdistmat as it stands turns the repository's own landing-gate suite red, at
    a gate the repository wired deliberately and measured green before wiring
    ("MEASURED before wiring, so this adds a gate that passes rather than a new
    red" — the comment above line 1795).

    MERGEABLE IS NOT LANDABLE. I had said the branches were landable together
    once F13 was resolved, on the strength of the merge producing only four
    mechanical conflicts. That was necessary and not sufficient: I never ran the
    gates on the COMPOSED tree. I have now — composed = rc 1, inherited whole
    from jdistmat, chip contributing nothing to it.

F1  BLOCKING (chip) — `only_the_declaring_step_writes_its_output` EXITS 1 ON THE
    TREE IT SHIPS ON, and it is the only one of the 22 whose test file never
    sweeps the repository, which is precisely why nobody saw it.

      examined 195 flow-declared output(s), 49 with an identified writer,
      1 exempt      ->  6 findings, rc 1:
        phase1/generated_docs/L21_POWER_INTENT.json
            ['l21_doc_supply_rail_synth.py', 'l21_macro_supply_rail_synth.py']
        phase3/stage3/eco/eco_log.json          ['eco_status_gen.py',
                                                 'phase3_one_shot_runner.py']
        phase3/stage3/eco/no_eco_needed.flag    (same pair)
        reports/phase1/extraction_coverage_report.json
            ['phase1_coverage_report_gen.py', 'phase1_doc_one_shot_runner.py']
        reports/phase1/extraction_coverage_report.md   (same pair)
        reports/spare_cell_coverage.json        ['phase3_one_shot_runner.py',
                                                 'spare_cell_coverage_check.py']

    Same rc 1, same six rows, on origin/main and on a trial merge of both
    branches — pre-existing repository debt, not damage this branch did.

    ALL SIX ARE REAL — hand-verified every one, not one and a generalisation.
    Each was traced from the declared path to an actual write call in two
    independent modules:
        L21_POWER_INTENT.json  l21_doc_supply_rail_synth:582 `l21.write_text`
                               l21_macro_supply_rail_synth:741 `l21.write_text`
                               (and with different `indent`, 2 vs 1, so which
                                runs last changes the file's bytes)
        eco_log.json           phase3_one_shot_runner:33561 `_eco_log.write_text`
                               eco_status_gen:216/220 `log_path.write_text`
        no_eco_needed.flag     phase3_one_shot_runner:33417 `_eco_flag.write_text`
                               eco_status_gen:143 `flag.write_text`
        extraction_coverage_report.json / .md
                               phase1_coverage_report_gen:910/912
                               phase1_doc_one_shot_runner:51051/51063
        reports/spare_cell_coverage.json   the pair below.
    Worth recording HOW that nearly went wrong: my first grep for the flag found
    only an `unlink()` in the runner and I briefly suspected a checker false
    positive. The real write is on `_eco_flag`, a variable whose name does not
    contain the basename — which is exactly the intra-scope resolution the
    checker performs and my grep did not. The imprecise instrument was mine.

    The pair I traced first, in full:
        spare_cell_coverage_check.py:222-225  canon = project/"reports"/
            "spare_cell_coverage.json"; canon.write_text(out + "\n")
        phase3_one_shot_runner.py:21655-21658 cov_path = project/"reports"/
            "spare_cell_coverage.json"; cov_path.write_text(json.dumps(...))
    Two independent unconditional writers of one flow-declared path. The
    checker is right, and my own three-way fixture (#17 above) shows it is
    right for the right reason and exempts what the flow itself declares twice.

    WHY IT IS STILL A LANDING DEFECT — and note the correction under F5b: the
    program is NOT wired, so nothing it does stops a batch. The defect is a
    verdict shipped with no disposition, not an obstruction. The program
    declares itself blocking
    ("rc 1  a declared output is written by more than one module"), ships no
    inventory or waiver — unlike all seven inventoried rules on the other
    branch — and its test file has no `test_repository_itself_is_clean`, which
    every one of its eleven siblings has. The branch would land a gate that is
    red on the tree it lands on, with no disposition for the six rows and
    nothing that would notice a seventh.

    Three ways out — BUT I CHECKED WHAT EACH ACTUALLY COSTS, having recommended
    them as equals when they are not:

      (a) fix the six writers. Available, and it is the flow-ownership decision
          the author has already said is the hard part. Nothing blocks it.
      (b) inventory the six with a reason each, "as the matrix arm does for 38
          rows". *** NOT AVAILABLE AS WRITTEN. *** This program has NO
          inventory mechanism: `--help` shows one positional `root` and nothing
          else, and there is no `--inventory`, no allowlist, no waiver anywhere
          in it, and no `*declared_output*inventory*.json` in programs/. Taking
          this route means IMPLEMENTING inventory support first and then using
          it — a different and larger job than the sentence implied. I should
          not have listed it beside (a) and (c) as though it were a choice of
          equal cost.
      (c) restate the rule as ADVISORY, the way
          `wall_clock_bound_standing_in_for_a_verdict` does it with a `--strict`
          flag. I IMPLEMENTED AND TESTED THIS ONE rather than costing it by eye,
          in a throwaway worktree at f3f0beeb6:

              ~8 lines in the program: a `--strict` flag, and the single
              `return 1` becoming `return 1 if args.strict else 0` with the
              label switching FAIL -> ADVISORY.
              Result: default rc 0 printing "[...] ADVISORY — a flow-declared
              output has more than one writer" with all six findings still
              listed; `--strict` rc 1 exactly as before.

              Cost to the suite: 6 tests fail, all of them the ones asserting
              the REFUSAL. Fixed by ONE line — adding `--strict` to the test
              helper's invocation, since those tests are asserting the refusal
              and the program is now advisory unless asked. After that:
              57 passed, including the whole
              `test_chip_path_rules_rc_contract` family, which is untouched
              because crash->rc2, bad-invocation->rc3 and empty->no-finding all
              still hold.

          So option (c) is genuinely mechanical and bounded — 10 lines and 1 —
          and it PRESERVES the finding rather than hiding it: the six are still
          printed on every run.

          RE-BUILT AND POSITIVE-CONTROLLED AT TODAY'S CHIP TIP
          (c0e19ace9), 2026-08-22. Everything above reproduces: 10
          lines in the program, default rc 0 printing ADVISORY with
          all six findings listed, `--strict` rc 1 with the same
          six. Six tests then fail, all of them the ones asserting
          the refusal, and one line in the test helper (adding
          `--strict` to its argv) fixes every one — 61 passed across
          this file and the whole `test_chip_path_rules_rc_contract`
          family. The count is 61 rather than the 57 I first
          recorded because the branch has added tests since
          f3f0beeb6, not because anything moved.

          AND THE PRESERVATION CLAIM IS PINNED BY SOMETHING OTHER
          THAN ME. F17 taught me that "the suite is green" can be
          worth nothing, so I broke the exact property option (c) is
          sold on: kept the advisory rc and SUPPRESSED the six
          findings from the output. The suite catches it —
          test_two_writers_of_one_declared_output_go_red and
          test_a_shell_second_writer_goes_red both fail, 2 of 61.

          THAT IS THE DIFFERENCE BETWEEN THIS REMEDY AND F14's, and
          it is why I can recommend this one without a caveat. F14's
          conversion can be applied wrongly and pass 233 tests. This
          one cannot be applied in the way that would matter —
          silently dropping the findings — without the branch's own
          tests going red. Worth knowing the shape of the cover:
          only 2 of the 6 red-control tests assert on the finding
          TEXT and the other 4 assert rc alone, so the guard holds
          against removing the message and is thinner against
          weakening it.

    Plus the missing sweep test in every case.

    AND THE SAME AUTHOR DID IT CORRECTLY NEXT DOOR, WHICH IS THE SHARPEST FORM
    OF THIS FINDING. At 4445f34a2 `signoff_report_states_its_stage` went rc 0 ->
    rc 1 on the shipped tree, and its shipped-tree test was REWRITTEN rather
    than dropped: it now asserts rc 1, asserts the other arm is still clean, and
    pins the new finding set BY IDENTITY. That is exactly the disposition this
    finding asks for, on the same branch, in the same session. The capability is
    not in question; only this file's turn has not come.

    STILL OPEN, AND THE REMEDY HAS NOT BEEN ATTEMPTED. Measured again at
    3d2dff2c9: rc 1, six findings, unchanged. The file itself has now taken FOUR
    successive repairs — the atomic-write idiom, `read_spef` missing `catch{}`
    and command substitution, unparseable-skip disclosure, and a writer-scan
    widening that took outputs-with-an-identified-writer from 49 to 57. Every
    one improved the INSTRUMENT. None addressed what this finding asks for:
    there is still NO repository-sweep test on that file, and still no inventory
    recording a disposition for the six. Checked directly at the current tip —
    no `test_*repo*`/`*shipped*`/`*itself*` test in
    tests/test_only_the_declaring_step_writes_its_output.py, and no
    `*declared_output*inventory*.json` anywhere in programs/.
    That distinction is the whole finding: the checker is right and getting
    better; what is missing is a decision about what it found.

    Earlier tips showed the same: rc 1, six findings, unchanged
    through four pushes. Two of those pushes were about these six, and both are
    worth reading before anyone acts on this finding:
      3b8466453 claimed one of the six was resolvable from the flow, and
      de551e09f RETRACTED that claim one commit later, in the author's own
      words: "I read ONE key and treated its absence as absence of the fact."
      The corrected measurement is that all 197 declared outputs DO have a
      declared producer — 137 via `programs:`, 55 via `skills:`, 5 via
      `mcp_tools:`, 0 with none — and the five remaining dual-writer paths
      belong to steps whose producer is a SKILL, which is why no `programs:`
      entry names them.
    That does not close F1 and the author does not claim it does; it narrows
    what the six are. My own finding is unaffected: the gate is BLOCKING, it
    exits 1 on the tree it ships on, and its test file still has no
    repository-sweep test.

F9  BLOCKING (matrix) — `declaration_searched_only_inside_a_truncated_window`
    implements a NARROWER predicate than the one it documents, and 31 live
    instances of its own class are invisible to it.

    The docstring says a finding is a constant-bound slice "whose result is
    SEARCHED in the same function". The implementation only sees the slice when
    it is written AT the search site. Bind it to a name first — the ordinary
    way anyone writes this — and the rule goes silent. Measured, my own
    fixtures, semantically identical:

      direct       return text[:1500].startswith("ENFORCEMENT")
                   return text[-800:].find("FATAL") != -1
                   -> rc 1, both sites named
      name-bound   head = text[:1500]; return head.startswith("ENFORCEMENT")
                   tail = text[-800:]; return tail.find("FATAL") != -1
                   -> rc 0, "slice-then-search sites: 0"

    LIVE ON THE SHIPPED TREE: 31 name-bound slice-then-search sites across 14
    files, of which — CLASSIFIED SITE BY SITE, because the raw 31 came from a
    scanner I wrote and had only spot-checked at three —

        31  are clearly the class: a bound that decides a verdict about
            content, where the same input outside the window flips the answer.
             _signoff_drc_format 4096 · analog_pdk_availability 4000 ·
             benchmark_verify_report 4000 · floorplan_contract 4000 (x3) ·
             ethernet_protocol_synth 3500 (x2) · mdio_protocol_synth 3500 (x2) ·
             sgmii_protocol_synth 3500 (x3) · mpw_precheck_cleanup 1500 ·
             golden_model_auto 500 (x2) · ip_integration_check 20000 ·
             foundry_handoff_package_check 200000 and 20000 ·
             phase3_one_shot_runner 200000 (x3)
         9  are DEFENSIBLE and I withdraw them from the count:
             phase1_doc_one_shot_runner `read_bytes()[:4096]` then `b"\x00" in
             head` — that is the standard binary-file sniff, not a verdict about
             authorship; five `text[:5_000_000]` bounds in the same file, which
             are memory guards, not predicate windows; and three
             `log[-50000:]` error-log tails in design_one_shot_runner, which are
             triage bounds on a compile log.

    THEN I POSITIVE-CONTROLLED THE SCANNER ITSELF, after F10 taught me what an
    unvalidated instrument is worth. The control available here is the strongest
    kind: make my scanner reproduce the SHIPPED CHECKER'S OWN findings. It did
    not — it found 5 of the checker's 10 — and chasing the five misses exposed
    two structural blind spots in MY code:

        * a window nested inside a concatenation, `re.search(pat, name + " " +
          prompt[:200])` — I inspected only bare arguments;
        * `not in`. I matched `ast.In` and never `ast.NotIn`, so every negated
          membership test was invisible. (This repository has a whole landed
          finding about `not in` being misread — vibe-ic#712. I reproduced it.)

    Fixed, my scanner reproduces the checker's TEN exactly — same files, same
    lines. That is the positive control, and only after it does any number of
    mine mean anything.

    RE-MEASURED WITH THE VALIDATED SCANNER: 40 name-bound sites, not 31. The
    same nine remain withdrawn as defensible; the nine newly found are all
    clearly the class, and I had been blind to them for the reasons above:
        gen_program_inventory.py:131 and tools/gen_programs_index.py:203
            head[2000] then `"DEPRECATION SHIM" in head.upper()` — a shim
            declared past byte 2000 reads as not-a-shim;
        phase3_one_shot_runner.py:17323  head[4096] then `... not in head` —
            an ECO deck stamp past 4096 reads as ABSENT, and it is a `not in`,
            the exact shape my scanner could not see;
        ip_catalog_upstream_audit.py:102, post_layout_sim_check.py:61,
        sdf_gate_sim.py:505 — the same shape over 5000- and 1500-byte windows.

    SO THE FIGURE IS 31 IN-CLASS OF 40 RAW. It lands back where my first,
    unvalidated number happened to be — which is luck, not method: that 31 was
    31 raw sites with nine false positives and nine misses cancelling out. This
    31 is 40 raw, nine withdrawn by inspection, from an instrument checked
    against the checker's own output. The rule detects 10 and misses 31.

    Three of the 31 are exactly the class the rule exists for:

      _signoff_drc_format.py:109   head = text[:4096]; _SVRF_BANNER_RE.search(head)
          The SAME FILE's direct-form twin at line 264 IS detected and IS in the
          shipped inventory as `_signoff_drc_format.py::text::head::4096`. One
          file, one variable name, one bound — one seen, one not.
      mpw_precheck_cleanup.py:159  _has_spdx(): head = text[:1500];
          "SPDX-License-Identifier" in head
          An SPDX header below byte 1500 reads as ABSENT. That is verbatim the
          rule's own headline failure: "it reports the author as having
          declared nothing."
      floorplan_contract.py:367-369  _looks_like_openlane_config():
          head = text[:4000]; "FP_SIZING" in head or "DIE_AREA" in head
          A config with FP_SIZING at byte 5000 is classified as not a config.

    Nothing documents the limit. The docstring's only stated exclusion is "a
    slice that only feeds OUTPUT". No test pins the name-bound form either way.
    And the verdict line makes a claim over the whole population — "no search
    decides a verdict inside a fixed-size slice" — which is not true of this
    tree. The gate is BLOCKING with an 8-row inventory.

    In its favour, it degrades legibly rather than silently: it prints
    "constant-size windows: 732" beside "slice-then-search sites: 10", so a
    reader who looks can see 722 windows it did not link. That is why this is a
    fix-before-landing and not a withdrawal.

    I IMPLEMENTED THE FIX RATHER THAN COSTING IT BY EYE, and the price is
    higher than I said. Adding one level of name-binding resolution to `scan()`
    is about 60 lines with its comments and the gate still runs. Measured on the merged tree with
    an empty inventory:

          slice-then-search sites      10  ->  50
          distinct inventory keys       8  ->  31

      CORRECTED 2026-08-22, DOWNWARD, AND THE INFLATION MECHANISM IS IDENTIFIED.
      This read "10 -> 96" and "8 -> 52" until I rebuilt the remedy at today's tip and
      could not reproduce it. The honest figures are 50 sites and 31 keys — so 23 new
      inventory rows, not 44. Roughly half the price I quoted the author.

      WHY THE 96 WAS TOO HIGH, and I know because my first attempt today reproduced
      it: `ast.walk(tree)` yields nested FunctionDefs, and walking the outer function
      already covers the inner, so every site inside a nested function was recorded
      TWICE. That first attempt gave 60 sites.

      THE SECOND DEFECT WAS A MISS, NOT A DOUBLE-COUNT, and only a positive control
      found it. I checked the remedy against the six sites F9 names as missed. Five
      were found and `gen_program_inventory.py:131` was not, because the searched
      object there is `head.upper()` — a Call, not a bare Name — and I had required a
      Name. Looking for the bound name ANYWHERE in the searched expression fixes it.
      After both fixes all six are found:

          _signoff_drc_format 110      mpw_precheck_cleanup 159
          floorplan_contract 367,368,369   phase3_one_shot_runner 17326
          gen_program_inventory 134    gen_programs_index 206

      AND THE TWO IMPLEMENTATIONS NOW AGREE. 50 = the checker's own 10 direct forms
      plus 40 name-bound — and 40 is exactly what my separate, separately
      positive-controlled scanner reports. Two implementations written on different
      days from different directions landing on the same 40 is the strongest support
      this number has. The 96 never had it, and I published it anyway.

    Its own suite: 9 of 10 tests still pass. The one that fails is
    `test_the_shipped_tree_passes_its_own_rule`, and it fails for the RIGHT
    reason — the gate now sees 44 keys its inventory does not cover. That is a
    different kind of failure from F12's, where the remedy broke a test encoding
    a real design distinction; here the test is simply reporting that the
    inventory has to grow with the predicate.

      So the true cost is: the resolution, PLUS 23 new inventory rows each with
      a written reason (this branch's own convention, and it holds 38 such rows
      elsewhere), OR repairing the sites. Not the "8 rows to ~39" I first
      estimated, not the 44 I corrected that to, and not free. Acceptable
      alternative: state the limit in the docstring AND in the verdict line, and
      add a test pinning it, so the PASS stops claiming more than it measured.
      Either is fine; shipping the current docstring against the current
      implementation is what is not.

F12 FIX WITH F9 (matrix) — matrix checkers answer PASS on an EMPTY SCAN where
    every chip checker refuses. Measured against a tree holding nothing but
    `.git` and an empty `programs/`.

    COMPLETE MEASUREMENT AT THE LAST TIPS (jdistmat 222a24479, all 18 of its
    programs; jdistchip ffa316c78, all 12). I first reported "8 of the 10
    original matrix rules" and assumed the six added later were better behaved.
    I checked instead of assuming, and the assumption was wrong:

    CORRECTION, 2026-08-22, AFTER PUBLICATION — THE NINE WAS MY INSTRUMENT.
    Re-running this measurement at today's tips to check it still held, I could
    not reproduce my own number. The corrected figure is THREE of sixteen, and
    the finding against this branch is a third of what I published.

    What produced the nine: I drove each gate BARE — no root argument, cwd set
    to the empty tree. Driven that way at least eleven of the sixteen exit 0.
    Driven the way they are meant to be driven, `--root <empty tree>`, which all
    sixteen accept with ZERO bad-invocation returns, only three do:

        --root <empty>  ......  3 of 16 rc 0   (0 returned rc 3)
        positional      ......  0 of 16 rc 0   (16 returned rc 3 — wrong form)
        bare, cwd=tree  .....  >=11 of 16 rc 0  <- what I published

    This is the fourth time in this report that an invocation form changed the
    answer, and this one I had already written the warning against, two hundred
    lines above: "do not drive them with no arguments — both give the wrong
    answer." I then did exactly that and published the result.

    IT IS NOT THAT THE AUTHOR FIXED IT. I checked, because a shrinking finding
    is the pleasant explanation and therefore the one to distrust. Same harness,
    same empty tree, the tip this report originally measured versus today's:

        00c2a6f33 (measured in this report)  ->  3 of 16 PASS
        facc28860 (today)                    ->  3 of 16 PASS

    Identical, and the same three names. The branch did not move on this axis;
    my measurement was wrong when it was written.

    THE THREE THAT GENUINELY PASS ON NOTHING, at facc28860:

        layer_membership_is_declared_not_inferred_from_a_filename_prefix
            "filename-prefix globs in tests: 0 ... [PASS] every prefix-selected
             layer population contains its whole relation."
        reference_control_resolved_through_a_mutable_ref   "modules parsed: 0"
        wall_clock_bound_standing_in_for_a_verdict         "modules parsed: 0"

    THIRTEEN OF THE SIXTEEN REFUSE CORRECTLY, which is the part my published
    number hid and which is the fairer reading of this branch. Six answer rc 2
    with a named reason — e.g. metric_constant_across_differing_arms: "[CANNOT
    DETERMINE] no multi-arm result set with provably differing arms was found. A
    verdict over no arms is NOT a pass." Seven answer rc 1. Both are defensible;
    neither certifies nothing.

    So the finding stands but changes character. It is no longer "this branch
    does not hold the house doctrine" — it plainly does, in thirteen places.
    It is "three gates are inconsistent with their own thirteen siblings", which
    is a smaller fix and an easier argument to make to the author.

    jdistchip is unchanged and confirmed: 0 of 12, each refusing with a named
    reason, measured with the POSITIONAL root its gates take (`--root` returns
    rc 3 on all twelve — the mirror image of matrix, and worth knowing before
    anyone re-runs this).

    The pre-correction measurement is left below as written.

      jdistmat, NON-census gates .......... 9 of 14 answer rc 0 on nothing
          the original eight, PLUS `layer_membership_is_declared_not_inferred_
          from_a_filename_prefix` — the NEWEST gate on the branch, and the one
          that ships deliberately RED on the real tree. On an empty tree it
          goes green.
          Refusing correctly (5): content_pinned_authority (2),
          declared_invocation (2), population_guard_asserts_equality (2),
          published_absence_claim (2, "no programs/ under that root"),
          two_input_selectors (2).
      jdistmat, the four `*_census` files  2 rc 0, 2 rc 2. For a CENSUS an
          rc 0 is correct by construction, so these are not F12 instances —
          though the four are inconsistent with each other, which is worth a
          line in whichever one is right.
      jdistchip .......................... 0 of 12. TWELVE OF TWELVE refuse,
          each with a named reason.

    So F12 is WIDER than I first reported, not narrower, and the pattern has
    not self-corrected as the branch grew.
    (Two of those readings were rc 3 on my first pass because I passed
    `--inventory` to programs that do not accept it. That was my flag, not their
    behaviour; re-run correctly, one is rc 0 and one is rc 2. Recorded because
    it is the same mistake as the `--strict` one earlier in this report, and
    twice is a habit.)

    The original measurement, on the first tips, read:

      matrix, rc 0 with the zero printed:
        declaration_searched_only_inside_a_truncated_window  "modules parsed: 0"
        denial_that_constitutes_the_value_it_appears_to_negate      "        0"
        invocation_proved_by_parse_not_by_text     "enforcement modules: 0"
        population_pin_without_its_member_set      "test modules parsed: 0"
        reference_control_resolved_through_a_mutable_ref            "        0"
        registry_is_the_iteration_domain                            "        0"
        spawned_gate_whose_status_is_discarded                      "        0"
        wall_clock_bound_standing_in_for_a_verdict                  "        0"
      matrix, rc 2 (correct): content_pinned_authority..., declared_invocation...
      chip, rc 2 with a named reason: ALL TWELVE. For example
        "[local_clone_does_not_borrow_objects] NOT CHECKED — no clone site was
         found"; "[only_the_declaring_step_writes_its_output] NOT CHECKED — the
         flow's declarations ...".

    This repository already has the doctrine and a gate for it:
    `gate_zero_denominator_refuses_check` — "a gate that read NOTHING must not
    exit 0" (vibe-ic#564) — which on main reports "569 gate(s) probed ... 25
    stated a zero population, of which 24 refused and 1 exited 0". The house
    norm is 24 out of 25 refusing. It cannot see any of the 22 because its
    population is `sorted(programs_dir.glob("*_check.py"))` and none of the 22
    ends in `_check.py` (this is F5 biting for the second time).

    Stated precisely, because the distinction matters: I applied that gate's OWN
    predicate (`states_zero_population(output) and rc == 0`) to all 22. Exactly
    ONE — registry_is_the_iteration_domain — phrases its zero in a way that
    gate's regex recognises, so only one would be a finding of it as written.
    The other seven exit 0 on a zero denominator but phrase the denominator in a
    form the regex does not match. That is a limitation of the existing gate's
    text matching, not evidence that the seven are fine.

    Two things keep this below F9. On the real repository the denominator is
    1402, so it cannot produce a false green there today; and five of the eight
    DO refuse a MISSING tree (`test_a_missing_tree_is_undetermined_not_a_pass`),
    so the authors drew the line — just at "tree absent" rather than at
    "population empty". The concrete harm is a wrong `--root`, a moved cwd or a
    shifted checkout: "modules parsed: 0" plus a PASS line reads as a clean
    verdict, and this fleet has produced exactly that mistake before.

    I SAID THE FIX WAS "ABOUT THREE LINES EACH". I TRIED IT, AND IT IS NOT
    MECHANICAL. Applied to `invocation_proved_by_parse_not_by_text` — refuse
    rc 2 when the enforcement-module count is 0 — it is five lines with a
    properly worded message, the empty tree correctly becomes
    "[CANNOT DETERMINE] ... An empty scan is NOT a pass" at rc 2, and both my
    fixture arms still behave (defect rc 1, remedy rc 0).

    BUT ITS OWN SUITE GOES RED: `test_a_non_enforcement_module_is_out_of_
    population` fails, because it builds a tree whose one module is NOT in the
    population and asserts rc 0. So the branch's own tests already encode a
    distinction my one-line recommendation flattened:

        no modules in the tree at all        -> nothing was observed, rc 2
        modules present, none in population  -> observed, found nothing
                                                applicable, rc 0

    Those are different states and the second is legitimately a pass. A correct
    fix has to separate "the corpus was empty" from "the corpus had nothing of
    this kind in it" — which is a design decision per rule, not a mechanical
    edit, and is why nine rules share the shape rather than one.

    (Tested in a throwaway copy and restored; the tree is clean.)
    The sibling branch already does it in all twelve, which is why this reads as
    an inconsistency to close rather than a judgement call to argue.

F10 LATENT (matrix) — `denial_that_constitutes_the_value_it_appears_to_negate`
    has the same intra-function limitation on its "inline denial regex" clause.
    A denial pattern compiled at module level under a local name is invisible:

      inline        def extract_unconstrained_paths(s):
                        if re.search(r"\b(?:no|not|never)\b", s): ...
                    -> rc 1, names the function, the concept and the pattern
      module-level  _DENIAL = re.compile(r"\b(?:no|not|never)\b")
                    def extract_unconstrained_paths(s):
                        if _DENIAL.search(s): ...
                    -> rc 0, "blanket-checked among them: 0"

    Unlike F9 this one is LATENT — 0 genuine live instances. But HOW I reached
    that zero was wrong the first time, and the correction is the most important
    thing in this finding.

    *** MY FIRST ZERO WAS VACUOUS, AND IT IS THE DEFECT THIS WHOLE CAPTURE IS
    ABOUT. *** I wrote a sweep that called the checker's own concept helper
    guarded by `hasattr(m, '_constitutive_concept')`. That helper does not exist
    and never did — it is `_concept_of`. So the guard was permanently False,
    `concept` was always None, `if not concept: continue` skipped EVERY function
    in the tree, and the scan reported 0 having examined NOTHING. I then wrote
    that 0 into a finding. A zero from an instrument nobody proved could answer
    non-zero is NOT OBSERVED, not zero — which is the rule the sibling programs
    in this very branch exist to enforce, and I broke it in the report about
    them.

    REDONE PROPERLY, positive control FIRST. The scan now mirrors the checker's
    real attribution (`_concept_of(fn.name)`, then `_concept_of(field)` over
    `_assigned_fields`, exactly as the checker does at its lines 186 and 190).
    Planting one synthetic instance makes it return 1, so the instrument can
    answer non-zero. Against the shipped tree it returns TWO candidates:

      gate_discloses_denominator_check.py:753 `_honest_about_an_absent_project`
        NOT the defect. It matches a reason string saying "not applicable" / "no
        such directory" and returns True on finding it. The denial IS the value
        it is looking for, which is the correct behaviour, not the inversion
        this rule is about.

      phase1_doc_one_shot_runner.py:31669 `gen_l4_regmap`
        NOT the defect. The function is 2146 lines long. The concept match comes
        from a field named `unspecified` somewhere inside it; the module-level
        denial pattern `_RE_L4_NO_REGMAP` is used at line 33807, about two
        thousand lines away, and nothing connects them. This is precisely the
        naive-form false positive the checker's own docstring records —
        "an absence verb anywhere and a path anywhere in the same string
        returns 78 claims of which 73 are false ... sometimes hundreds of
        characters apart".

    So the conclusion is unchanged — 0 genuine live instances, nothing hidden
    today — but it is now OBSERVED rather than asserted, and had the real number
    been non-zero I would never have known. Worth one line in the docstring, not a landing blocker.
    (The `_BLANKET_CALLS` list does catch module-level names it knows —
    `is_denied`, `NEGATION_RE`, `DENIAL_CORE_RE` — so the gap is only for a
    locally-named one.)

F11 MINOR (both) — THREE rules key their population on a hardcoded vocabulary:
      two_input_selectors_given_together_must_refuse (matrix, row 28)
          two fixed selector lists; `--project-dir` is invisible, `--corpus` is
          not, and the identical defect flips verdict on the flag's name.
      explicit_argument_outranks_the_environment_pointer
          POINTER_NAMES = ("CORPUS_ENV", "_CORPUS_ENV", "VIBE_IC_BENCHMARK_DATA")
          My fixture using a fourth pointer name was invisible.
      generated_values_state_whether_they_were_read_or_defaulted
          VALUE_HINTS = ("_ns", "value", "fraction", "period", "delay", "default")
          My `declared_supply_v` helper was invisible; renaming the field to one
          inside the list made the identical defect go red.
    Both answered rc 2 NOT CHECKED with the denominator printed, rather than
    passing — which is the honest failure mode and is why this is minor. But
    the coverage of both is a word list, not a structure, and neither docstring
    says so.

F2  MINOR (matrix) — `test_declared_invocation_accepted_by_its_own_parser.py` is
    the only file on its branch with no repository-sweep test. Its checker
    measures rc 0 today, so nothing is red; but the state is unpinned, and F1
    is what an unpinned state looks like later.

F3  CORRECTION TO THE BRIEF'S PREMISE — "three of its ten are population
    EXTENSIONS that import an existing predicate". TWO import one:
        declared_invocation_accepted_by_its_own_parser  -> _gate_invocation
        denial_that_constitutes_the_value_...           -> _prose_polarity
    The third ALREADY-PROGRAM record is `invocation_proved_by_parse_not_by_text`,
    whose note names hdl_declaration_scan_strips_comments_check for a DIFFERENT
    corpus (HDL text, not python source). It imports nothing from it and should
    not — there is no shared predicate to import. I looked for copied logic and
    found none. The sentence in the hand-off is off by one; the engineering is
    right.

F4  LAND-ORDER — SUPERSEDED FOR jdistmat, WHICH NOW MERGES CLEAN. Having
    merged main at b7f504e25 and regenerated the derived files, jdistmat merges
    into a4caccefe with ZERO conflicts. jdistchip still has the four below, and
    whichever branch lands SECOND will need them re-rendered against a main that
    includes the first. The original finding follows.

    ORIGINAL: landing both produces FOUR conflicts, all in generated
    count files: vibe-ic-marketplace/README.md, plugins/vibe-ic/README.md,
    programs/INDEX.md, programs/PROGRAM_INVENTORY.json. Each branch restates the
    count from its own base (matrix 1238->1248, chip 1238->1250). The correct
    merged figure is 1260, measured on the trial merge. Whoever lands second
    must RE-RENDER with gen_program_inventory.py, not hand-resolve — a
    hand-resolved count is a population pin restated for one arrival and not the
    other, which is rule #6 on the very branch being landed.
    Neither branch bumps a VERSION or plugin.json. Correct — the pusher assigns.

F5b "BLOCKS" IS AN ASPIRATION, NOT A WIRING FACT — and I used the word as
    though it were one. jdistchip caught this about their own claim first
    (14d57fdfd, "I called a gate 'blocking' from its docstring; none of the five
    blocks"), and it applies to my F1 and F15 wording equally.

    VERIFIED INDEPENDENTLY on the composed trees — for each gate at rc 1, every
    reference outside its own file, its own test, the inventories and docs/:

        gate_proof_vocabulary_has_a_producer          rc 1   docs only
        layer_membership_is_declared_..._prefix       rc 1   docs only
        metric_constant_across_differing_arms_...     rc 1   docs only
        only_the_declaring_step_writes_its_output     rc 1   one docstring
                                                      mention in
                                                      signoff_report_states_its_
                                                      stage.py + the rc-contract
                                                      test
        every_required_metric_key_has_a_producer      rc 1   the rc-contract test

    FIVE GATES AT rc 1 IN COMPOSITION AND NOT ONE IS WIRED. Nothing runs any of
    them in a position where the exit status stops anything.

    THE ONE EXCEPTION IN THIS REPORT IS F14. `atomic_artifact_write_check` is an
    EXISTING main gate, wired at tools/ci/repo_hygiene_gates.sh:1795 through
    `run`, which is `_dispatch 0 0` — rc 1 fails the suite. That is why F14 is
    the only finding here that actually blocks, and why it is worth separating
    from the five above rather than counting them all as "red gates".

    SO SEPARATE THE TWO THINGS, as jdistchip put it: rc 1 is a FACT ABOUT THE
    TREE, and every one of those reds is a real finding except F15's; "THIS GATE
    BLOCKS" is an INTENT until something invokes the program. Where this report
    says a gate "blocks", read "declares that it blocks". F1 and F15 are not
    claims that a batch will be stopped — nothing would stop it — they are
    claims about a verdict shipped without a disposition, and in F15's case a
    verdict that is untrue.

    AND THAT IS ITS OWN FINDING. Three programs announce "THIS GATE BLOCKS
    (rc=1)" in their docstrings and block nothing, which is precisely the class
    this whole capture exists to name: a machine declared to refuse that nobody
    runs. It is the same shape as `gate_is_wired_check`'s own subject.

F5  OBSERVATION (both, not a blocker) — none of the 30 is wired into anything.
    `grep -rl` across *.py/*.yaml/*.json/*.sh/*.md finds each referenced only by
    its own test, its own inventory json, and INDEX.md. No runner, no flow yaml,
    no CAPTURE_ROUTING.json, no hooks/, no tools/ci. They escape the repo's two
    wiring gates because those populations are `*_check/_audit/_guard/_lint/
    _gate.py` and none of the 30 carries such a suffix — measured:
    gate_is_wired_check and checker_execution_wiring_audit return the SAME
    finding set on main, on jdistmat and on jdistchip.

    RE-MEASURED AT THE CURRENT TIPS, and this is the cleanest statement of it.
    `checker_execution_wiring_audit` prints the size of its own population:

        main      1238 programs   635 checker-shaped
        jdistmat  1254 programs   635 checker-shaped   (+16 programs, +0)
        jdistchip 1250 programs   635 checker-shaped   (+12 programs, +0)

    Thirty new enforcement programs across the two branches, and the
    population of the repo's wiring gates does not move by one. Not one of the
    30 carries a `_check/_audit/_guard/_lint/_gate` suffix, so none is visible
    to gate_is_wired_check, to checker_execution_wiring_audit, or to
    gate_zero_denominator_refuses_check (which globs `*_check.py` — F12). Their
    only automatic reader is the repo-sweep test inside their own test file.
    Which is exactly why F1 was invisible.

    WIRING RE-CHECKED AT THE LAST TIPS, because four programs were renamed and
    six added since the first grep. The core observation holds for both branches
    — no runner, no flow yaml, no CAPTURE_ROUTING.json, no hooks/, no tools/ci
    executes any of the 30. jdistmat's only cross-references are docstring
    mentions between siblings.

    BUT jdistchip HAS STRENGTHENED ITS AUTOMATIC COVERAGE, and it deserves
    saying. `tests/test_chip_path_rules_rc_contract.py` now names all twelve and
    pins the property NO PER-RULE TEST CAN ASSERT, because it is about what
    happens when the checker itself goes wrong:

        test_a_crashing_scan_is_not_checked_never_a_finding
        test_a_bad_invocation_is_three_not_one
        test_an_empty_population_reports_no_finding

    12 rules x 3 properties = 36 tests, all green. The first of them is exactly
    the concern behind METHOD 2 of this report — "Python exits 1 on an uncaught
    exception, and rc 1 is this family's code for I FOUND A DEFECT, so a checker
    that raises reports a finding it never made". I probed that by hand with a
    blinded stub; jdistchip has now made it a machine-checked family invariant.
    That is the strongest structural improvement either branch has made, and
    jdistmat has no equivalent.

    ALSO RE-MEASURED, and then RE-RE-MEASURED after main advanced. The first
    pass, against main at v1.11.68, recorded gate_is_wired_check and
    checker_execution_wiring_audit as "rc 1 on all three, pre-existing on main".
    THAT IS NOW STALE, and the way I found out is worth more than the numbers.

    *** COMPARING AN UN-REBASED BRANCH TIP AGAINST AN ADVANCED MAIN MEASURES THE
    WRONG SUBJECT. *** Neither branch has rebased, so a gate main FIXED in its
    214 new commits still reads red on the branch tip — and a naive tip-vs-main
    diff reports that as a BRANCH REGRESSION when it is main's own repair
    arriving late. The correct instrument is the COMPOSED tree: new main plus
    the branch, which is what actually lands. Re-measured that way:

        gate at v1.11.69                main   matrix-composed  chip-composed
        gate_is_wired_check              0           0               0
        checker_execution_wiring_audit   0           0               0
        flow_gate_enforcement_audit      0           0               0
        corpus_cardinality_pin_scan      1           1               1
        atomic_artifact_write_check      0           1  <- F14        0

    Main repaired three of the four gates I had called "pre-existing red"; only
    corpus_cardinality_pin_scan is still red, and it is red identically on both
    composed trees. Over the full 29-gate set on the COMPOSED trees, chip
    regresses NOTHING and matrix regresses exactly one — F14. That is the
    landing-relevant statement, and it is the one to trust.

        plugin_full_audit           rc 0 on main / matrix / chip
        single_testpath_guard       rc 0 on all three
        source_chip_agnostic_check  rc 0 on all three

    *** THE SENTENCE THAT USED TO END THIS PARAGRAPH WAS WRONG. It read
    "NEITHER BRANCH REGRESSES A REPO-LEVEL GATE", generalised from the five
    gates above to all of them. Driving the 29 gates named by the repository's
    own `tools/ci/repo_hygiene_gates.sh` shows jdistchip regresses none and
    jdistmat regresses exactly one — `atomic_artifact_write_check`, main 0 ->
    branch 1. See F14. Five hand-picked gates were not a basis for a claim
    about every gate, and I should not have written one. ***

F6  DOC ACCURACY (matrix, no code impact) — the capture record for
    `denial_that_constitutes...` says prose_polarity_consulted_check.py "is red
    on the shipped tree". Measured rc 0 on origin/main AND on the branch. Stale
    sentence; the rule it justifies stands on its own measurement.

F7  FIXED BY THE AUTHOR WHILE I WAS WRITING (chip). Commit 317cef847, "a
    checker whose filename made it invisible to its own family", renames it to
    `pytest_aggregate_carries_its_runtime_identity.py`. Verified: no `test_*.py`
    remains in programs/, and the rule still answers correctly under the new
    name — my defect fixture rc 1, my remedy rc 0, blinded control fails on
    `assert ('image' in '')`, repo sweep rc 2 NOT CHECKED with its reason. The
    original finding is preserved below for the record.

    ORIGINAL: programs/test_aggregate_carries_its_runtime_identity.py is
    the first `test_*.py` ever placed in programs/ (main has none). Not
    collected today (pytest.ini declares one testpath; run_tests.sh enumerates
    explicit directories), but `pytest programs/` would collect it and every
    reader will read it as a test. Renaming it would also put it inside
    gate_is_wired_check's population, where a checker belongs.

F8  COSMETIC — test_generated_values...::test_the_landed_helpers_are_still_
    recognised emits `DeprecationWarning: invalid escape sequence '\s'` from
    `<unknown>:2`. The literal is in a PRE-EXISTING repo source file that the
    new checker parses. Suite noise, nothing more.

F17 NEW, 2026-08-22 (matrix) — NINETEEN OF TWENTY CHECKERS SHIP A `--json`
    ARTEFACT PATH THAT NO TEST EVER RUNS. Found while positive-controlling my
    own F14 remedy validation, which is the only reason it surfaced: I was
    checking my evidence, not theirs.

        jdistmat: 20 of 20 new checkers declare a `--json` option
                   1 of 20 has a test that passes `--json`
                  19 of 20 therefore ship an unexercised artefact path
        jdistchip: 0 of 12 declare `--json` — NO GAP, nothing to test

    DEMONSTRATED, not inferred. I applied the F14 conversion to three of them
    and deliberately omitted the import, leaving `atomic_write_text` undefined
    on the write path:

        33 passed, pytest rc=0        <- the suite is blind to it
        same program with --json:  rc 2, "the walk did not complete
                                   (NameError: name 'atomic_write_text' is not
                                   defined). NOT a pass."

    So the branch's green is real for the verdict logic and says nothing about
    the artefact path. Any edit to that path — the F14 remedy above being the
    one this repository is about to make to all twenty — lands untested.

    A ONE-LINE REMEDY EXISTS AND THE BRANCH ALREADY CONTAINS IT.
    `test_two_input_selectors_given_together_must_refuse.py` is the one file
    that does it; the other nineteen can copy its shape.

    AND IT EXPLAINS F14's ASYMMETRY, which I had recorded as a fact without a
    cause. F14 hits matrix and not chip because chip's twelve programs write no
    declared artefacts at all — there is nothing for `atomic_artifact_write_
    check` to police. The two branches are not differently disciplined here;
    they are differently shaped. That is a fairer statement of the same
    measurement, and I would not have had it without asking why my own control
    passed.
```

## THINGS I TRIED THAT DID NOT BREAK ANYTHING

```text
  * 22 hand-built defects and 22 hand-built remedies, in my own trees, not
    copied from the tests. Every red named the site; every remedy went green;
    stderr was empty on every red.
  * Silent-rc-1 mutation of all 22 — no control survived, and none failed on rc.
  * Silent-rc-0 mutation of all 22 — every control failed on rc.
  * Cross-branch: every checker of each branch run against a trial merge of
    BOTH. No new finding in either direction. Only #17 (rc 1, F1) and #22
    (rc 2, by design) are non-zero, identically to their own branches.
  * All 22 test files together on the trial merge: 253 passed, 1 warning, 128s.
  * Repo-level meta-gates on all three trees: gate_is_wired_check rc 1,
    checker_execution_wiring_audit rc 1 (BOTH pre-existing on main),
    plugin_full_audit rc 0. Finding-set diffs against main empty for both.
  * Inventory hygiene: the 7 inventoried rules grandfather 38 rows; every row
    carries a `reason`; every one of the 7 has a stale-row-is-a-failure test, so
    the allowlist cannot rot into a suppression list.
  * `_prose_polarity` regression: the branch's change is purely additive (one
    widened `typing` import, then new names only). Its existing tests pass, 42.
  * 836-run disagreement matrix: every rule against every other rule's remedy.
    Owner check 19/19; disagreements 0.
  * 37 adjacent existing programs driven over defect and remedy arms: 0
    discriminating. Six whole-tree ones closed by finding-set diff instead: 0
    delta on either branch, including corpus_cardinality_pin_scan, which is red
    on main and stays byte-identically red on both branches.
  * Scope limit found and recorded rather than filed as a defect: #5 needs an
    intra-module call binding the corpus to the searching function. My first
    fixture omitted it and correctly passed. Honest under-report, matching its
    documented method.
```

## THE SWEEP-rc COLUMN, RE-MEASURED AFTER THE F12 CORRECTION

```text
The F12 error was an invocation-form mistake, so the question it raises is
whether that class of error reached anything else in this report. The largest
exposed surface is the table's `sweep rc` column — the brief's question 3, "does
the checker exit 0 on the tree we are shipping", answered 32 times.

I re-ran the whole column on 2026-08-22 at main a4caccefe / jdistmat facc28860 /
jdistchip c0e19ace9, each gate driven in the form it accepts and NO rc 3 scored
as a verdict:

    32 of 32 agree with the table.   25 rc 0 · 6 rc 1 · 1 rc 2
    0 gates were unresolvable (every one parsed under --root or positional)
    matrix takes `--root`, chip takes a positional root, and each returns rc 3
        to the other's form — the trap that produced the F12 number

THE SEVEN NON-ZERO, AND WHY EACH IS NOT A QUESTION-3 FAILURE:

    gate_proof_vocabulary_has_a_producer            rc 1  = F15, a FALSE red,
        and the only one of the seven I hold against its branch
    only_the_declaring_step_writes_its_output       rc 1  = F1, findings true,
        no repository-sweep test — the finding is the missing test, not the red
    layer_membership_is_declared_..._prefix         rc 1  declared + pinned;
        its six findings verified true by hand
    metric_constant_across_differing_arms           rc 1  declared + pinned;
        denominator verified by hand (60 arms, 60 distinct knobs dicts)
    every_required_metric_key_has_a_producer        rc 1  declared + pinned;
        verified independently (0 measured against 364, beside a control
        measured 206 times)
    signoff_report_states_its_stage                 rc 1  declared + pinned by
        a rewritten member-set test; went rc 0 -> 1 at 4445f34a2 when the author
        repaired their own always-green gate
    pytest_aggregate_carries_its_runtime_identity   rc 2  deliberate: "This tree
        is a repository, not a run tree", asserted by its own test

ONE COUNT MOVED. An earlier passage in this report records "chip-composed 12
programs, TWO red". At today's tip it is three, the third being
`signoff_report_states_its_stage`, whose rc 0 -> 1 transition this report
already documents separately. The passage was correct when written; the branch
moved under it. Stated here rather than silently edited, because a count that
changes for a recorded reason is evidence and a count that changes silently is
not.

SO THE F12 DEFECT WAS LOCAL TO F12'S HARNESS, not general to this report. The
sweep column was measured per gate, each in its own form, and it holds. That is
a finding about my own instrument, and it is the reason this section exists: a
correction is worth more when it comes with the bound on what else it touches.
```

## F14 RE-VALIDATED ON THE COMPOSED TREE, 2026-08-22

```text
F14 is the only finding that stops a landing, and I had validated its remedy
nine commits earlier. The landing test is the COMPOSED tree, not the branch tip,
so I rebuilt it and re-ran the whole thing at main a4caccefe + jdistmat
facc28860.

THE MERGE IS NOW CLEAN. jdistmat merges into a4caccefe with ZERO conflicts —
the four generated count files no longer collide, the author having absorbed
main at b7f504e25. Both arms below are the same merge: identical tree hash
967ace003166466991cb816c8bad863a0c2c0208, differing only by the remedy.

THE THREE ARMS, each replaying the runner's own 28 wired invocations:

    main a4caccefe                        rc0 26   rc1 0   rc2 2
    composed, NO remedy                   rc0 25   rc1 1   rc2 2
    composed, WITH the 20-file remedy     rc0 26   rc1 0   rc2 2

    The single rc 1 is atomic_artifact_write_check under `run`, which is
    _dispatch 0 0 — rc 1 fails the suite. The two rc 2 are
    macro_obs_geometry_intersect_check and tool_diagnostic_id_gate, both under
    run_tolerating_uncheckable, and BOTH ARE ALSO rc 2 ON MAIN. They are the
    tree's normal state, not a branch effect.

    Diffing the remedied arm against main row by row: all 28 identical. The
    only differing line is the harness's own header naming the tree path.

THE REMEDY, EXACTLY. All 20 offending sites are one shape —
`Path(a.json_out).write_text(json.dumps(...))`. Two lines per file:

    +from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082
    -            Path(a.json_out).write_text(json.dumps(
    +            atomic_write_text(Path(a.json_out), json.dumps(

    20 files changed, 40 insertions, 20 deletions. All 20 compile. The gate goes
    533 -> 513 non-atomic writes, rc 1 -> rc 0, which is main's number exactly.
    Note the idiom: these sites write TEXT, so it is `write_text`, not the
    `write_json` this report named earlier — both exist in the helper, and the
    house pattern for this shape is `write_text as atomic_write_text`.

THE TEST-SUITE EVIDENCE FOR THIS REMEDY IS NOT LOAD-BEARING, and it was mine.
I had written that the remedy is validated partly because "the branch's own test
files still pass". At today's tip that run is 233 passed, rc 0, writing nothing
into the tree. Then I asked the question that makes a green mean something:
would those tests go RED on a remedy applied WRONGLY?

    Applied the call swap to three programs and DELIBERATELY OMITTED the import,
    leaving `atomic_write_text` an undefined name:

        33 passed in 63.50s     pytest rc=0

    The suite does not notice. The mechanism, confirmed directly:

        broken program, no --json   -> rc 0   (what the tests run)
        broken program, with --json -> rc 2
            "[CANNOT DETERMINE] registry_is_the_iteration_domain: the walk did
             not complete (NameError: name 'atomic_write_text' is not defined).
             NOT a pass."

    Only 1 of the 21 matrix test files passes `--json` at all. The artefact-write
    path — the thing F14 is entirely about — is exercised by one test file out of
    twenty-one, so a broken conversion passes the suite.

    THIS ALSO INDICTS MY OTHER TWO EVIDENCE LINES, and I would rather say so than
    let the reader assume they cover it. `atomic_artifact_write_check` is a
    STATIC check over the source, so it certifies the call shape and not that the
    program still runs. And the 28 wired invocations do not touch these programs
    at all, because none of the twenty is wired yet (F5b). So none of my three
    original evidence lines actually executed the converted code path. The
    remedy is validated by running the twenty with `--json` and comparing rc and
    artefact against the pre-remedy tree — which is recorded below — and NOT by
    the suite being green.

    THE REMEDY, RE-VALIDATED THE RIGHT WAY. All twenty programs run with
    `--json`, pre-remedy and post-remedy, on the SAME composed base (identical
    tree hash, the only difference being the forty added and twenty removed
    lines):

        rc, pre vs post ............ identical for all 20
                                     (17 rc 0 + 3 rc 1 in both arms; the three
                                      rc 1 are the declared reds — gate_proof_
                                      vocabulary, layer_membership, metric_
                                      constant — matching the sweep column)
        artefact written ........... 20/20 both arms, valid JSON both arms
        artefact CONTENT ........... byte-identical in 20 of 20, after
                                     normalising the two tree paths

    And the instrument is proven able to answer otherwise: the deliberately
    broken conversion above returns rc 2 with a NameError named in its message,
    so a run that comes back rc-identical is a measurement and not an absence.
    (I also positive-controlled the file comparison itself — diffing two
    DIFFERENT programs' artefacts, which it correctly reports as differing.
    A 20-of-20 "identical" from a comparison that cannot see a difference would
    have been the same shape of empty green as the suite result it replaces.)

    NOTE FOR WHOEVER APPLIES IT: a wrong conversion does not crash loudly. The
    branch's own traceback guard turns it into a courteous rc 2 with a named
    reason, and rc 2 under `run` fails the landing suite just as rc 1 does. So a
    botched F14 fix would swap one suite failure for another that looks unrelated
    to it.

AND COMMIT BEFORE RUNNING THE SUITE. I nearly published a false red here:
policy_direction_pin_check returns an untolerated rc 2 on a dirty checkout, so
the remedied arm would have failed on the 20 uncommitted edits rather than on
anything real. Committed first; it returns rc 0 in both arms.

A MEASUREMENT OF MINE THAT I THREW AWAY, recorded because the failure is
instructive and it nearly went into this document as a result. My first
composed replay was VOID: I applied the 20-file remedy while that replay was
still running against the same tree. It was at row 27 of 29, and
atomic_artifact_write_check is row 29 — so the decisive cell was measured on
the remedied tree while the other 28 were measured on the un-remedied one, and
the suite came up green BY ACCIDENT. The right answer, for the wrong reason,
is the hardest kind to catch: it agrees with what you expected. Both arms above
were re-run on frozen trees with nothing edited during either.

This is the same rule as "never edit the tree during a pytest run", which this
repository already knows and which I had written down. Knowing a rule and
holding it while impatient are different skills.
```

## THE CAPTURE RECORDS AGAINST THE TREE, BOTH DIRECTIONS — nothing found

```text
Re-checking the brief's CLAIM 1 at today's tips, and then pushing past it into
the bookkeeping behind it. This section reports a clean result; the brief asked
for those to be said plainly rather than dressed up.

CLAIM 1 STILL HOLDS at jdistmat facc28860. In `2026-08-21-jcap-matrix`:
11 records, 10 carrying `rule_name`, every one of the 10 a slug that IS the stem
of a program on the branch, every one carrying its sentence in `title`. Record
11 has no `rule_name` and never did. Unchanged from the rename commit, and the
branch has added ten more programs since without breaking the convention.

FORWARD: every rule_name resolves to a program.
REVERSE: every program the records claim shipped exists.
    ppa DISTIL.md     6 named  ->  6 exist
    matrix DISTIL.md  10 named -> 10 exist
    chip DISTILLATION.md 10 named -> 8 on this branch, and the other 2 are
                      explicit cross-references to the sibling lane's programs,
                      which exist there. 10 of 10 resolve; 8 of 10 resolve
                      WITHOUT leaving the branch, and stating it the second way
                      is the honest one.

THE SIX ppa RULES THAT NAME NO PROGRAM ARE NOT A GAP. I derived that set
independently — rule_names in recoveries.json with no matching program — before
reading their disposition, and it matched their own declared "Not shipped (6)"
exactly. Each carries a measured reason, not an excuse: one is ALREADY
IMPLEMENTED elsewhere (`_ppa/benchmark.py`'s REQUIRED_SCOPE table, with the
null-placeholder case refused as SCOPE_SENTINEL); two have no static signature
that discriminates (a scan would flag 37 of 37, or 100 of 131); two need a
declaration the tree does not carry; one is half-clean and says which half. The
file states the rule itself — "a record here that names no program is NOT an
oversight" — and the tree agrees with it.

TWO THINGS I FLAGGED THAT WERE MY OWN MISREADS, recorded because both are the
same error and someone re-running this will hit them:

  * chip's 13 records "have no `title`". They have a DIFFERENT SCHEMA — no
    `title`, but `fires_on_original`, `fires_on_a_different_instance`,
    `measured_before`, `measured_after`, `notes`. Nothing was lost because
    there was never a sentence-form `rule_name` there to move. I applied
    jdistmat's schema to jdistchip's file and read the difference as damage.
  * two programs chip's DISTILLATION.md cites "do not exist". They exist on the
    SIBLING branch, and the citing paragraph says so in terms — it is chip
    naming the census lane's offenders and adding "None is from this lane".

  Both are the failure this report keeps finding in itself: an instrument
  answering correctly about the wrong subject. Neither is a finding against
  either branch.

AND A CORROBORATION OF F14 FROM THE OTHER LANE. chip's DISTILLATION.md records
the same defect independently — "529 write their declared report destination
NON-atomically, residual baseline 515 ... the SAME 16 unregistered offenders,
none is from this lane". They measured 16; I measure 20 today, the branch having
added four programs since. Two lanes reaching the same finding by different
routes is worth more than either alone, and it is the strongest single argument
that F14 is real rather than an artefact of how I drove the gate.
```

## THE BLINDED-CONTROL CLAIM, RE-DERIVED — and a mutant of mine that was unfair

```text
"All 32 negative controls fail on CONTENT when the checker is blinded" is the
central methodological claim of this report, and it is the one I had not
re-derived. Done now, at facc28860 / c0e19ace9, for all 32 rather than a sample.

THE HEADLINE HOLDS. Replace each checker with a stub that exits 1 and prints
nothing, run its own test file: 32 of 32 go red. Not one suite is satisfied by a
silent stub.

THE SUMMARY SENTENCE WAS STILL TOO BROAD, and I have narrowed it. It is true of
the 32 controls this report QUOTES — one per checker, each asserting on output,
each failing with the `AssertionError: in ''` the table records. It is not true
of every negative control in those suites. 49 tests survive the blinding; 34 of
them do invoke the program, and all 34 assert its rc and nothing about what it
said. Eight of the 34 present as negative controls by name or docstring —
including one whose docstring reads, in capitals, "THE NEGATIVE CONTROL for the
source arm", asserting `rc == 1` alone. All eight are on jdistchip; jdistmat's
red controls assert content without exception.

AND THEN I CHECKED MY OWN MUTANT, WHICH IS THE PART WORTH READING. A stub that
returns 1 while printing nothing is not a failure these programs can have. They
map an uncaught exception to rc 2 — `prepared_checkout_states_the_revision_it_
holds` has ten such handlers — and no-finding to rc 0. So an `rc == 1`
assertion already excludes both realistic regressions. Measured rather than
reasoned: stubbing that checker to return 0 fails 15 of its 17 tests.

    what an rc-only red control DOES exclude:  the checker stopping detecting
                                               (rc 0, caught, 15 tests)
                                               the checker crashing (rc 2,
                                               caught, these programs catch)
    what it does NOT exclude:                  going red for a DIFFERENT reason
                                               on that fixture

    So the eight are WEAKER than the content-asserting ones, and they are not
    vacuous. The gap is one failure mode wide, not a hole.

I am recording this at that strength deliberately. My first reading of the 34
was "a third of the surviving tests are vacuous", which is the shape of finding
this report has already caught itself producing twice — an alarming number from
an instrument nobody audited. The instrument here was mine, and auditing it cost
one command and turned a headline into a footnote. The headline would have been
wrong.
```

## THE FIXTURE MATRIX, RE-RUN AT TODAY'S TIPS — 988 runs

```text
The last block of this report's evidence not yet re-derived: the brief's
questions 1 and 2, restated as a matrix. 19 paired fixture trees I wrote,
every checker on both branches over both arms, at facc28860 / c0e19ace9.

    988 runs      rc 2 = 554     rc 0 = 415     rc 1 = 19

OWNER CHECK — each fixture's owning rule red on the defect, green on the remedy:
19 OF 19, and getting there took one correction of my own harness.

    Driven as the harness had them, it read 17 of 19. The two misses were
    `content_pinned_authority_verified_only_at_merge` and
    `wall_clock_bound_standing_in_for_a_verdict`, both rc 0 on BOTH arms —
    which is the signature of a rule answering in a mode you did not mean.
    Both are ADVISORY: rc 0 is what they return on a finding unless asked
    otherwise. With `--strict`, which is the shipped verdict for a red:

        authpin  defect --strict rc 1   remedy --strict rc 0
        wall     defect --strict rc 1   remedy --strict rc 0

    So 19 of 19. THAT IS THE FIFTH TIME IN THIS WORK AN INVOCATION FORM HAS
    CHANGED AN ANSWER, and the fourth where the wrong form made a branch look
    worse than it is. The list is now: `--strict` on advisory rules, an empty
    `--inventory` on rules that grandfather, `--inventory` passed to rules that
    reject it, a bare invocation in F12, and this. Every one of them is the same
    mistake — driving a program in a way its wiring never drives it — and I have
    made it in both directions.

DISAGREEMENTS — a non-owner checker red on another rule's REMEDY: ZERO.
That is the harm the brief named, and it does not occur across 988 runs.

    One row is red on BOTH arms and is discarded as noise, exactly as before:
    `every_required_metric_key_has_a_producer` on my `measonly` fixture, whose
    records file carries a single metric key, so most of that rule's axes are
    unprovable in it. It answers correctly about a tree built for a different
    rule.

    THE NOISE COUNT HAS HALVED SINCE I FIRST RAN THIS, from two rows to one,
    and for a reason worth naming: jdistchip fixed that rule at 094c2cb7e —
    "the metric gate counted the consumer as its own producer" — and one of the
    two rows went away with the bug. A cross-run that gets quieter because the
    author repaired something is the cheapest possible confirmation that the
    repair was real.
```

## HOW TO DRIVE ALL 32 — the antidote to the mistake I made five times

```text
Five times in this work an invocation form changed an answer, and four of those
made a branch look worse than it is. That is not five coincidences; it is one
hazard that anyone re-running these measurements will meet. So here is the
contract, MEASURED rather than read off the argparse calls — every program run
both ways against its own tree, and rc 3 scored as "wrong form", never as a
verdict.

  branch  root form      flags accepted     shipped rc   checker
  CHIP R (positional)               rc0   declared_basis_matches_the_session_inputs
  CHIP R (positional)               rc0   explicit_argument_outranks_the_environment_pointer
  CHIP R (positional)               rc0   generated_values_state_whether_they_were_read_or_defaulted
  CHIP R (positional)               rc0   local_clone_does_not_borrow_objects
  CHIP R (positional)               rc0   measurement_only_artefact_is_not_a_verdict_source
  CHIP R (positional)               rc0   prepared_checkout_states_the_revision_it_holds
  CHIP R (positional)               rc0   printed_remedy_runs_as_printed
  CHIP R (positional)               rc0   provenance_value_is_resolved_not_constant
  CHIP R (positional)               rc1   every_required_metric_key_has_a_producer
  CHIP R (positional)               rc1   only_the_declaring_step_writes_its_output
  CHIP R (positional)               rc1   signoff_report_states_its_stage
  CHIP R (positional)               rc2   pytest_aggregate_carries_its_runtime_identity
  MAT  --root R               jsn   rc0   published_absence_claim_is_rechecked_against_the_tree
  MAT  --root R               jsn   rc1   gate_proof_vocabulary_has_a_producer
  MAT  --root R               jsn   rc1   layer_membership_is_declared_not_inferred_from_a_filename_prefix
  MAT  --root R               jsn   rc1   metric_constant_across_differing_arms_is_not_measured
  MAT  --root R           str jsn   rc0   content_pinned_authority_verified_only_at_merge
  MAT  --root R           str jsn   rc0   wall_clock_bound_standing_in_for_a_verdict
  MAT  --root R       inv     jsn   rc0   declaration_searched_only_inside_a_truncated_window
  MAT  --root R       inv     jsn   rc0   declared_invocation_accepted_by_its_own_parser
  MAT  --root R       inv     jsn   rc0   denial_that_constitutes_the_value_it_appears_to_negate
  MAT  --root R       inv     jsn   rc0   invocation_proved_by_parse_not_by_text
  MAT  --root R       inv     jsn   rc0   population_guard_asserts_equality_not_a_floor
  MAT  --root R       inv     jsn   rc0   population_pin_without_its_member_set
  MAT  --root R       inv     jsn   rc0   reference_control_resolved_through_a_mutable_ref
  MAT  --root R       inv     jsn   rc0   registry_is_the_iteration_domain
  MAT  --root R       inv     jsn   rc0   spawned_gate_whose_status_is_discarded
  MAT  --root R       inv     jsn   rc0   two_input_selectors_given_together_must_refuse
  MAT  --root R       inv str jsn   rc0   explicit_argument_outranks_the_environment_pointer_census
  MAT  --root R       inv str jsn   rc0   local_clone_does_not_borrow_objects_census
  MAT  --root R       inv str jsn   rc0   only_the_declaring_step_writes_its_output_census
  MAT  --root R       inv str jsn   rc0   provenance_value_is_resolved_not_constant_census

READ IT THIS WAY:
  * ALL 20 matrix programs take `--root R`; positional gives rc 3.
    ALL 12 chip programs take a positional R; `--root` gives rc 3.
    The two branches are exact mirrors, which is why scoring an rc 3 as a
    verdict makes them look identical on an axis where they differ completely.
  * `inv` = accepts `--inventory`. FOURTEEN do. Passing an EMPTY inventory to
    one of these does not make it stricter, it removes the grandfathering, and
    the rule then reports history rather than regression. That is what F9's
    "10 sites" figure needs and what turned 3 reds into 11 in an early sweep of
    mine.
  * `str` = has an ADVISORY mode: rc 0 on a finding unless `--strict`. SIX do.
    Driving these plain and reading rc 0 as "no finding" is the error that made
    the fixture matrix read 17 of 19 instead of 19 of 19.
  * `jsn` = writes a `--json` artefact. TWENTY do, all on matrix, and only one
    of the twenty has a test that exercises that path — see F17.
  * shipped rc is the verdict on the tree the branch ships, driven correctly.

AND ONE PROGRAM HAS TWO ARMS, which a static reading gets wrong. I built this
table from `add_argument` first and it classified
`prepared_checkout_states_the_revision_it_holds` as taking `--root`, which
contradicted the rule above and looked like an error in guidance I had already
published. Measured, the positional gives rc 0 and `--root` gives rc 3, because:

    ap.add_argument("tree", nargs="?", ...)   # source tree to scan
    ap.add_argument("--root", ...)            # runtime arm: a prepared
    ap.add_argument("--expect", ...)          #   checkout to interrogate
    ap.add_argument("--upstream", ...)

It is a two-arm program. Its `--root` is a different MODE, not a different
spelling of the same one, and its rc 3 was a correct refusal of an incomplete
runtime invocation. The published rule was right; my static instrument was
wrong, and I nearly corrected a correct sentence on its word. Sixth entry in
the same list, and the only one so far that ran the other way.
```

## VERDICTS

```text
origin/jdistmat/matrix-distil  >> LAND WITH F15 + F14 + F9 + F12 FIXED

    Eighteen of its twenty programs are sound IN THEIR PREDICATE, verified
    twice over in both directions (ten at the first tip, ten more as they were
    pushed). TWO carry predicate defects, not one as this paragraph said until
    2026-08-22: F9, whose implementation is narrower than its docstring, and
    F15, whose scan root makes its verdict false of the repository. F12 is a
    separate, contract-level problem affecting THREE of them (corrected down
    from eight on 2026-08-22; the F12 paragraph below carries the measurement)
    and is not about whether they detect the right thing:
    I reintroduced each defect myself and got a specific, correctly-reasoned
    red, and blinding each checker reddened its control on the assertion it is
    named after. On the tree it ships on, every checker answers as its own
    tests declare it should: 25 of the 32 exit 0, six exit 1 and one exits 2,
    and of those seven exactly two are held against their branch (F15's false
    red and F1's undisposed one) — the other five are declared in the verdict
    line and pinned by the checker's own test. ("Every checker exits 0" is what
    this sentence said until 2026-08-22; it was never true and the table two
    thousand lines above always said otherwise.) No duplicates —
    the two rules that overlap an existing predicate IMPORT it, verified down to
    `classify_not_invocable` having exactly one definition in the repository.
    The recoveries.json rename moved content and deleted none, field by field.
    Seven allowlists, 38 rows, every row reasoned, every one guarded against
    going stale. Three times my fixture came up green and three times the
    checker was right and I was wrong, twice against a documented and TESTED
    exclusion — that is a good sign about this branch, not a bad one.

    The first of the two, `declaration_searched_only_inside_a_truncated_window`,
    needs one thing fixed first. Its docstring claims a predicate its
    implementation does not have, and the difference is not academic: 31 live
    sites in the shipped
    tree are invisible to it (40 raw, nine withdrawn as defensible, from a
    scanner positive-controlled against the checker's own ten) — including one
    in a file whose direct-form twin it already inventories, and including an
    SPDX-header check that is verbatim the failure the rule was written to
    end. Its PASS line asserts something about
    this tree that is not true. Either resolve one level of name binding, or say
    the limit out loud in the docstring, the verdict line and a test. Cheap
    either way, and the branch lands.

    F14 is the hard one and it is new: this branch turns an EXISTING main gate
    red. `atomic_artifact_write_check` is rc 0 on main and rc 0 on the sibling
    branch, and rc 1 here, because TWENTY of this branch's own new programs
    write their `--json` output non-atomically (sixteen when this paragraph was
    written; the branch has added four since). It is a ratchet, so it cannot be
    waived by registering them — the remedy is `from _atomic_artefact import
    write_text as atomic_write_text`, since every one of the twenty sites writes
    TEXT; `write_json` also exists in that helper and is what I first named here,
    wrongly. Until it is fixed the COMPOSED tree is red too, and it
    is red entirely on this branch's account.

    F12 is the same failure mode as F9 in a second place: a PASS that claims
    more than the run measured. THREE of this branch's sixteen non-census gates
    certify an EMPTY SCAN — measured directly, at today's tip, against a tree
    holding nothing. All twelve on the sibling branch refuse, each with a named
    reason, and so do thirteen of this branch's own sixteen, which is what makes
    the three worth fixing: they are inconsistent with their own siblings, not
    with a foreign standard. Three lines each, and worth doing in the same
    commit as F9 because it is one idea, not two. (Published as nine of
    fourteen; corrected downward on 2026-08-22 — see the CORRECTION in F12.)

    F2 (one missing sweep test), F6 (one stale docs sentence) and F10 (a latent
    twin of F9 with zero live instances) are follow-up commits, not holds.

origin/capture/jdistchip-chip-path-rules  >> LAND WITH F1 FIXED

    Eleven of its twelve are as sound as the matrix arm's, on the same doubled
    evidence. Two of my fixtures came up green and both times the checker was
    right against a documented, tested narrowing. The two claimed true positives
    are real defects that I reproduced by reverting the fixes. The narrowing in
    #15 — refusing object alternates but deliberately NOT the hardlink clone a
    sibling gate prints as its own remedy — is the kind of care usually missing,
    and #22 answering NOT CHECKED over an empty population instead of PASS is
    this repo's own doctrine obeyed rather than quoted. Three of these programs
    refused rather than passed when I fed them something outside their
    population, which is the behaviour the whole capture is about.

    The twelfth, `only_the_declaring_step_writes_its_output`, must not land as
    it stands. It declares itself blocking, exits 1 on the tree it ships on with
    six findings I confirmed are genuine — unchanged through all four pushes,
    including two that were about those six — and it is the only file on the
    branch without the repository-sweep test all eleven siblings have. That is not a
    wrong checker — my own three-way fixture shows it is right, and right for
    the right reason — it is a right checker shipped with no disposition for
    what it found, and the missing test is why. Fix the six, inventory the six,
    or restate the rule as advisory; then add the sweep test.

    F11 (three hardcoded vocabularies, all disclosed at rc 2) and F8 (cosmetic)
    are follow-ups. F7 the author fixed at 317cef847 while I was writing.

    I did not fix anything, per the brief. The authors do.

    MERGEABLE, BUT NOT YET LANDABLE — and those are different questions.
    The MERGE is clean again: what remains of it is four generated count files,
    the mechanical F4 conflicts. But the composed tree FAILS
    `atomic_artifact_write_check`, inherited whole from jdistmat (F14), so the
    order of operations is: fix F14 on jdistmat, then land in either order, then
    re-render the count files. I checked the merge before I checked the composed
    verdict, and said "landable" on the strength of the first; that was the
    wrong order and F14 records the correction.

    On the collision itself, they were not mergeable at all for the middle of
    this exercise: four rule names appeared on both, two of them returned
    opposite verdicts about origin/main, and one branch waived in an inventory
    the exact defect the other repaired in code. The author settled it at
    bebd9c1e1 by ruling their four are CENSUSES and renaming them, and I
    verified that resolution end to end (see F13). What is left of the merge is
    four generated count files — the mechanical F4 conflicts. Land in either
    order, then re-render INDEX.md and PROGRAM_INVENTORY.json with
    gen_program_inventory.py. Do NOT hand-resolve those four: a hand-merged
    count is a population pin restated for one arrival and not the other, which
    is rule #6 on the very branch being landed.

    WHAT THE TWO BRANCHES DID WITH THIS REPORT IS ITSELF EVIDENCE. Between my
    first pass and my last, F7 was fixed, F13 was ruled on and resolved, one
    chip commit was retracted by its own author one commit later, and jdistmat's
    two newest rules (rows 29 and 30) are textbook applications of the remedies
    F1 and F12 ask for — a deliberate red DECLARED in the docstring and PINNED
    by a test, and a green guarded by a test asserting its own denominator
    exceeds 50. The remaining findings are the ones nobody has acted on yet, not
    the ones nobody understood.

RE-VERIFICATION AT THE LATER TIPS
    Everything in this report was FIRST measured at 88ec1594f / 8470a80c4. The
    branches then moved three more times each. Re-run at bb8bf676f / 35e9bc1e8,
    and the load-bearing parts again at 3c3a6e0e4 / 317cef847:
      F1  survives unchanged — chip's only_the_declaring is still rc 1 on its
          own tree with the same 6 findings, and its test file still has no
          repository-sweep test (only test_the_real_flow_declares_a_substantial_
          population, which checks the denominator, not the verdict).
      F9  survives — my name-bound window fixture still reads "constant-size
          windows: 3 / slice-then-search sites: 0" and PASSes. Its magnitude was
          later re-derived as 31 in-class of 40 raw, after positive-controlling
          the scanner against the checker's own ten findings.
      F12 survives, but SMALLER THAN PUBLISHED — three matrix gates still exit
          0 on an empty scan with the zero printed, not nine. See the
          CORRECTION in F12: the nine was my instrument, not their code.
      Both new suites are green: jdistmat 147 passed (14 test files),
          jdistchip 216 passed, 1 warning (13 test files).

    THE CHURN WAS LARGE, so I re-measured rather than assuming. Between the two
    pairs of SHAs, jdistchip MODIFIED 11 of its 12 programs and all 12 of its
    test files and added a cross-cutting `test_chip_path_rules_rc_contract.py`;
    jdistmat modified 2 of its original 10 and added the 4 colliding copies.
    Seven of jdistchip's commits are titled as fail-open and false-pass repairs
    ("the revision checker gave a FALSE PASS on the case it exists for", "three
    more fail-open cases", "an empty corpus was rendering as nine findings") —
    the authors were finding the same class of defect I was, in parallel.

    THE 15th MATRIX RULE, added while I was writing, verified the same way:
      population_guard_asserts_equality_not_a_floor — "a population guard must
      be able to answer NO; a literal asserted against its own length is a
      tautology that passes for free, on every tree, forever."
        Q1  my own defect (`_TABLE = ["a","b","c"]` then
            `assert len(_TABLE) == 3`) -> rc 1,
            "tests/test_sample.py:5  len(_TABLE) == 3  (the literal holds 3)".
            My remedy, re-deriving the population live and comparing both the
            count and the member set -> rc 0. Bidirectional.
        Q2  blinded (silent rc 1): its controls fail on
            `assert '_PORTS' in ''` and `assert 'NEG_FIXTURES' in ''` —
            content, not rc.
        Q3  rc 0 on its own tree: "len() over an unmutated literal: 23 /
            guards that cannot fail: 3 / inventory rows applied: 3".
        Q4  no duplicate found; and the rule is self-consistent — its own test
            uses `len(NEG_FIXTURES) >= 5`, the floor form its docstring names
            as the acceptable one.

    Q3 RE-MEASURED, all 26 program files on their own trees:
      jdistmat  14 of 14 rc 0. (content_pinned_authority and wall_clock are
                ADVISORY by design and are rc 0 at their default; they go rc 1
                only under --strict, which is the documented contract. My first
                re-run passed --strict and briefly read as two new reds; it was
                my flag, not their tree.)
      jdistchip 10 rc 0, one rc 1 (only_the_declaring — F1, unchanged, still
                6 findings), one rc 2 (test_aggregate, declared NOT CHECKED and
                pinned by its own test).

    Q1/Q2 RE-MEASURED: a 988-run matrix, 26 checkers over my 19 fixture pairs.
      Owner check 19 of 19 bidirectional at the new tips — every rule still red
      on my hand-built defect and green on my hand-built remedy.
      Non-owner rc 1: four rows, none a disagreement — two are the colliding
      matrix copies correctly catching chip's fixture (evidence FOR the
      predicates matching, see F13), two are the known measonly/axis noise that
      fires identically on both arms.
      rc distribution: 554 NOT CHECKED, 413 PASS, 21 FAIL.

    Q4 RE-MEASURED AND EXTENDED. The whole-tree finding-set diffs were re-run
    at the CURRENT tips and are reported under F5 — plugin_full_audit,
    single_testpath_guard and source_chip_agnostic_check rc 0 on all three
    trees; gate_is_wired_check and checker_execution_wiring_audit rc 1 on all
    three with ZERO new findings. The empirical duplicate probe was extended
    from 25 adjacent programs to 37, covering the two genuinely new rules, with
    0 discriminating.

    WHAT IS STILL AS OF THE ORIGINAL SHAs, stated so nobody over-reads this
    report: the per-row hand reproductions for rows 1-22 (rows 23-28 were done
    at the later tips), and the 836-run disagreement matrix — though that one
    was re-run whole as the 988-run matrix above. Whoever lands should re-run
    the duplicate probe once F13 is settled, because the four colliding files
    will by then be four files and not eight.

--------------------------------------------------------------------------------
Evidence, left in place, all clean:
    /tmp/jvM  main      @ 81cd5321b   (also used to build the composed tree)
    /tmp/jvMain main @ 81cd5321b      (clean baseline for the 29-gate sweep)
    /tmp/jvA  jdistmat  @ 88ec1594f   (first tip)
    /tmp/jvA4 jdistmat  @ 3c3a6e0e4   /tmp/jvA5 jdistmat  @ 222a24479 (last tip,
                                                 18 programs, F13 resolved)
    /tmp/jvB3 jdistchip @ 3b8466453   /tmp/jvB6 jdistchip @ ffa316c78 (last tip)
    /tmp/jvout   mutation logs, meta-gate outputs, hyg_*.txt (the 29-gate
                 sweep on all three trees) and hyg_gates.txt (the list, taken
                 from tools/ci/repo_hygiene_gates.sh)
    /tmp/jvfx    36 fixture trees, one per hand reproduction
    /tmp/jvfx2   19 paired defect/remedy trees, + envptr_mat and prov_mat (the
                 even-handed pairs for F13), + popguard and dualsel2 (rows 27
                 and 28), + cross.json (836 runs, original tips),
                 + cross2.json (988 runs, new tips), + dup.json / dup3.json
    (The worktrees for the superseded tips bb8bf676f and 8470a80c4 were removed
     once their measurements were written up; every tree listed above is clean
     and detached.)
Nothing was pushed. No version bumped. Neither branch was edited.
--------------------------------------------------------------------------------
```

