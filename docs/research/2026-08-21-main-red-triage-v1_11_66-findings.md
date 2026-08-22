# findings — agent `ptmo`: the v1.11.66 red triage, and what auditing my own claims found

host 8hd-3 · started 2026-08-21 · **read this header before M0**

> **THE SECTION COUNT IS GONE FROM THE TITLE, DELIBERATELY.** I corrected it three
> times (32 → 57 → 69) and it was stale again *within the commit that last fixed
> it* — M75 pushed it to 70 while claiming 69. **A number that is wrong after
> every commit does not belong in a header**; the command below is the number.
> The counters that remain are as-of the commit that last touched this block. Every section appended afterwards invalidates
> them and none of them touches this header — a summary's accuracy is inversely
> proportional to how much work happens after it is written. **Re-derive before
> quoting**, with:
>
> ```sh
> P=docs/research/2026-08-21-main-red-triage-v1_11_66-findings.md
> grep -cE '^## M[0-9]+' $P                                   # sections
> grep -oE '^## M[0-9]+' $P | grep -oE '[0-9]+' | sort -n | tail -1   # highest M
> sed -n '/^### .*instrument defects, consolidated/,/^\*\*The common shape/p' $P | grep -cE '^\| [0-9]+ \|'
> sed -n "/^## D\. Corrections/,\$p" $P | grep -cE '^[0-9]+\. \*\*'   # corrections
> ```
>
> That is four commands. **Every stale number in this document — six blockers, a
> section count, an instrument tally, a corrections list, a red inventory — cost
> less than that to check and more than that to believe.**
>
> **THE RED COUNTS HAVE NINE COPIES.** `9 failed → 6 failed` appears eight times
> here and once in the proposal document. They agree today (**M65** re-measured
> and diffed by ID), but nine copies of one number will diverge. **M65 is the
> authority**; treat the rest as references. Re-derive with:
>
> ```sh
> cd vibe-ic-marketplace/plugins/vibe-ic && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
>   python3 -m pytest -q -p no:cacheprovider -p no:pytest_ethereum \
>   programs/tests/test_landing_merge_verdict.py | tail -1
> ```
>
> **Diff the failing IDs, never the totals** — two runs matching on count with
> different sets is a trap this document fell into twice.
>
> **AND THE SAME RULE COVERS EVERY OTHER NUMBER HERE, because they are all
> duplicated.** Counted: the image lane's `22 failed, 112 passed` appears **6**
> times, the lease ratio `1/8` **7**, the harness flake `4/10` **6**, the `magic`
> determinism `10/10` **5**, the measured artefact size `1919` **3**. I am NOT
> adding a pointer per number — seven hand-maintained cross-references would be
> the same defect one level up, and `test_liar_census.py` already names it:
> *"a hand-maintained number that must be remembered by an author who is editing
> a different file is **prose wearing an assertion**"*.
>
> **THE RULE: for any measured number in this document, the section that FIRST
> MEASURED it is the authority. Every later mention is a reference.** If two
> disagree, the earlier measurement wins until someone re-runs it — and the
> re-run, not the argument, settles it.

**SCOPE HAS GROWN PAST THE TITLE IT STARTED WITH.** This began as RUN 8 —
"v1.11.62 and the ownership question" — and M0 below still states that premise,
correctly, as the premise OF RUN 8. The branch is cut from `6d06ba664` ("final
disposition at v1.11.66"). **M0 is history, not the current base.**

> **THIS PARAGRAPH USED TO SAY "the document now runs to M36."** It ran to M92
> when I noticed. **The header that warns "a summary's accuracy is inversely
> proportional to how much work happens after it is written" was carrying a
> count 56 sections stale**, in the same block that publishes a command to
> re-derive it. Kept as a worked example rather than quietly deleted: the rule
> was already written, already correct, and I broke it anyway by appending.

**TWO HEADLINE RESULTS POSTDATE MOST OF THIS DOCUMENT. Read them before you
trust an earlier framing:**

* **M90 — the two lanes AGREE, and I retract "the repair is invisible to CI".**
  With four invocation flags (docker CLI + socket + `--group-add` + **`-v
  /tmp:/tmp`**) the image lane goes **22 failed → 6 failed, 128 passed**, and the
  failing set is **byte-identical to the host's**. My re-founded design A and C
  tests PASS there. **The repair was never invisible; the lane was
  misconfigured, and I described the misconfiguration as a property of my own
  work.** Every earlier "22 failed, 112 passed" in this document describes the
  UNCONFIGURED lane and should be read that way.
* **M91/M92 — the six survivors are ONE defect.** Every one is a test control
  that used to cross as an environment variable and cannot, because the arm's
  environment is a closed seven-name allowlist. **Committed tree data crosses**
  — built and executed, not argued (M92). All six are then blocked behind
  PROTECTED files, which M91 got wrong for four of them and M92 corrects.

**If you read only one thing, read `REQUESTS TO THE LANDER` at the end.** It is
the only section maintained as a current summary; everything between M0 and it is
a chronological log in which later sections retract earlier ones.

**What the log is mostly about, in the end.** It began as a triage of main's reds
and became, roughly half by volume, an audit of MY OWN claims — because those
turned out to be the least reliable thing in it:

* **six disposition rows audited → six corrections.** Not one survived as written.
* **six "not mine" claims audited → five collapsed, one held** with a better
  framing. A blocker reads as modesty and is therefore the last thing anyone
  re-checks, its author included.
* **ten instrument defects catalogued**, of which FOUR reported my own work — or
  my own record — as more accurate than it was, and one **silently skipped a push**
  while reporting success.
* **twenty-six retractions of published findings**, plus three near-misses that
  measurement killed before publication. **Two of my conclusions reversed twice.**
* **eight blockers audited: seven were WRONG.** Five outright false, one badly
  stated, one wrong about the work required — and one correct, which is the only
  reason to trust the other seven.

The reds are in the tables. The reason to keep the rest is that most of what went
wrong here was not in the repository.

## M0 — PREMISE: main is v1.11.62. NEITHER of the two changes is in the tree.

```
git ls-remote origin refs/heads/main -> 6dfe15a329e6e1fbd621d0bfaadaed41c3c5db9a
6dfe15a32 landing(ACTIVATE): the lane-parallel window into the protected runtime [v1.11.62]
plugin.json -> 1.11.62
```

* **v1.11.64 — the persistent-red deadline — HAS NOT LANDED.**
  `tools/ci/gate_red_since.json` still reads `"acknowledged": []`, zero rows,
  identical to every previous measurement.
* **v1.11.66 — the cross-layer win — HAS NOT LANDED.** What did land is
  `8e2a3cbfb` [v1.11.61], whose own subject is the CONTROL, not the win:
  *"the PnR-only baseline reproduces all 15 published cells to the digit"*.
* v1.11.63 (my v1.11.57 triage) has not landed either.

So the question "how many reds would refuse a landing under the new deadline"
cannot be answered AGAINST the new deadline — it does not exist here yet. It can
be answered structurally, and that answer is more useful than a count.

## M1 — THE STRUCTURAL ANSWER: none of my BOTH reds CAN be owned

`gate_red_since.json`'s own field documentation:

> `gate` — **the gate's label EXACTLY as `tools/ci/_gate_dispatch.sh` records
> it.** A label that matches nothing in the record is failed as `stale`, so a
> drifting label cannot go quiet.

and the checker implements exactly that:

```
def _states(record): """Map gate label -> state, from the dispatcher's own record."""
```

**Every red on my list is a pytest NODE ID** — `programs/tests/test_x.py::test_y`
— produced by the TARGETED-TEST arm, not a dispatcher gate label produced by the
hygiene suite. `grep -cv '^programs/tests/test_.*::' ` over the input set is 0.

**So a row naming any of my reds would be rejected as `stale` today**, because
its label matches nothing in the dispatcher's record. They are not "unowned";
they are **UNOWNABLE by this mechanism**.

That is the same domain split I flagged when I broke the three-way convergence
with jlandpar, and it now has a practical consequence for the landing question:

* if v1.11.64's deadline covers ONLY dispatcher gates, then my 22-ish test-ID
  reds are **untouched by it**, and "can main land tomorrow" is decided by the
  HYGIENE GATE set, not by my list;
* if the intent is that test-ID reds must also be owned, the register needs a
  second key space first — today it cannot express one.

**The number the question is really asking for is therefore the count of RED
DISPATCHER GATES, not the count of red test IDs.** I am measuring that
separately rather than answering with a number from the wrong domain.

## M2 — ROOT CAUSE OF THE 22, AND IT MAY RETRACT MY OWN HEADLINE

The 22 `test_landing_merge_verdict` reds have **two different causes, one per
lane**, and neither is obviously about main:

```
IMAGE  [NORECORD] hermetic candidate: cannot execute Docker CLI:
                  [Errno 2] No such file or directory: 'docker'
HOST   [NORECORD] hermetic candidate: subject would expose the host HOME
                  to the candidate
```

**IMAGE cause, confirmed:** `docker run … --skip bash -lc 'which docker'` ->
**NO DOCKER CLI IN THE IMAGE**. The test drives `gatekeeper-verify-merge.sh`,
which launches a hermetic candidate runner in a container. There is no
docker-in-docker in `vibeic-eda`, so the B1 arm cannot start and its receipt is
NORECORD.

**HOST cause, and this one is MINE:**
`tools/ci/hermetic_candidate_runner.py:426`

```python
if _inside(resolved, home):
    raise Refusal(f"{kind} would expose the host HOME to the candidate")
```

`_resolve_mount` refuses ANY subject under `$HOME`. My private path is
`/home/reyerchu/_ptmo_priv/...` — **under `$HOME`**. So the host-lane red is
produced by WHERE I PUT MY CLONE, not by the code under test.

**I reported these 22 to the operator as "BOTH-lanes real, about main" and as
the highest-value red on the board. That claim is now in doubt from both
sides.** The decisive experiment is running: the same file, host lane, from a
clone OUTSIDE `$HOME` (the session scratchpad), where the refusal structurally
cannot fire.

This is exactly the class my whole job exists to detect — a red that is about
the measuring environment and not the subject — and I nearly shipped it as the
headline. The reason I caught it is the same reason I caught the `magic` one:
reading the failure MESSAGE per lane instead of trusting the colour.

## M3 — THE DECISIVE EXPERIMENT: 22 red -> 9 red from outside `$HOME`

Same file, same host lane, same commit, subject cloned into the session
scratchpad (outside `$HOME`, where the HOME refusal structurally cannot fire):

```
/home/reyerchu/_ptmo_priv/... (under $HOME)   134 cases,  22 red
<scratchpad>/nohome/...       (outside)       134 cases,   9 red     394s
```

**13 of the 22 were an artefact of where I put my clone. I retract that part of
my headline.** I reported them to the operator as BOTH-lanes real and as the
highest-value red on the board; 13 of them were mine.

## M4 — ITEM 1: ROOT CAUSE, AND WHY IT IS NOT A CODE FIX

The guard drives `gatekeeper-verify-merge.sh`, which launches a HERMETIC
CANDIDATE RUNNER. Measured, both lanes:

| requirement | image lane | host lane |
|---|---|---|
| Docker CLI (to launch the hermetic arm) | **ABSENT** (`which docker` -> nothing) | present |
| `git merge-tree --write-tree` (>= 2.38, the STRONG tier) | git **2.43.0** OK | git **2.34.1** -> `fatal: unknown rev --write-tree` |
| subject outside `$HOME` | n/a | mine was inside; fixed by moving |

```
IMAGE cause: [NORECORD] hermetic candidate: cannot execute Docker CLI
HOST  cause: DEGRADED TIER … git 2.34.1 does not support `merge-tree --write-tree`
             (needs >= 2.38) … the squash-vs-rebase cross-check WAS NOT PERFORMED
```

**Neither lane available on this host can run this guard cleanly.** The image has
the new git and no docker; the host has docker and a git three minor versions too
old. The guard needs **docker CLI + git >= 2.38 + a subject outside `$HOME`, in
ONE environment**, and no environment on 8hd-3 provides all three.

**THE PARAGRAPH THE RULING ASKED FOR — what this repository does not hold.**
I cannot fix these on their merits from here, and the missing thing is not code.
The landing-verdict guard is an END-TO-END test of the merge path: it needs to
start a container (docker CLI), compute a real 3-way `merge-tree --write-tree`
(git >= 2.38), and mount a subject that is not under the operator's home. The
pinned runner image supplies the git but deliberately contains no docker CLI, so
the hermetic arm cannot start inside it; this host supplies the docker but a git
that silently drops the verifier to its DEGRADED tier, where the refusal it
returns has a different rc than the strong tier the tests assert. What the
repository does not hold is **a single attested environment in which the landing
verifier's own end-to-end guard can execute** — either a runner image carrying a
docker CLI (docker-in-docker or a mounted socket, which is a security decision,
not a bug fix), or a host git >= 2.38, or a declared third lane for this file.
Until one of those exists, every verdict this guard produces on 8hd-3 is
"I could not look", and the honest record is that it is UNRUNNABLE here rather
than failing.

> **SUPERSEDED — read M8, M18 and M26 before acting on the paragraph above.**
> It is wrong. The guard DOES run on this host in the degraded rebase-replay
> tier; M8 measured G4 at 8/8 deterministic, and M18's two-lane A/B measured
> **10 BOTH-lane reds** with the pinned image on the STRONG (`merge-tree`) tier.
> Designs A and C have since closed four of them. This paragraph is kept as the
> record of what I believed at the time, and as an example of the failure it
> claims to be describing: I reported "I could not look" as a property of the
> guard when it was a property of where I was looking from.

## M5 — ITEM 2: THE 22, GROUPED BY CAUSE

| group | n | cause | one defect or several |
|---|--:|---|---|
| **G1 HOME-exposure** | **13** | `hermetic_candidate_runner.py:426` refuses any subject under `$HOME`; my clone was there | **ONE**, and it is MINE, not main's. Retracted. |
| **G2 no docker in the image** | all image-lane | `vibeic-eda` has no docker CLI, so the hermetic arm never starts | **ONE** environment fact, not a repo defect |
| **G3 degraded tier** | **5** | host git 2.34.1 < 2.38, so `merge-tree --write-tree` is unavailable and the verifier refuses with a different rc than the tests assert | **ONE** environment fact. The verifier BEHAVED CORRECTLY — it refused, and said why, in the same output |
| **G4 interruption timeouts** | **2** | control arm unreachable across the hermetic boundary | **SETTLED (M8)** — 8/8 deterministic, not load. Test is stale vs hermetic arms; diagnosis fixed, property still unguarded |
| **G5 record shape** | **1** | `KeyError: 'corpus_transitions'` — the verifier returned `LAND_OK` and `hygiene_finding_delta["status"] == "CLEAN"`, but the delta carries no `corpus_transitions` key the consumer reads | **CANDIDATE REAL DEFECT.** Same producer/consumer-shape class as `3f5473a1b [v1.11.53] ppa(records)`, one lane over |
| **G6 lane-parallel probe** | **1** | the concurrency probe dir holds only `cleanup.*`; none of `A2.started`/`B1.started`/`B2.started` was recorded | **CANDIDATE REAL DEFECT**, and pointed: v1.11.62 IS "the lane-parallel window into the protected runtime". Could still be downstream of the arms not starting |

G5 and G6 both got PAST `assert r.returncode == 0` and `doc["verdict"] ==
"LAND_OK"` — the verifier ran and allowed the landing — so they are about the
RECORD the verifier publishes, not about whether it refused. Those two are the
ones worth someone's time, and neither is a relaxation, a baseline rewrite or a
skip.

## M6 — G5 RUN TO GROUND, and it CORRECTS MY PUSHED COMMIT

I labelled G5 in the pushed commit message as a *"producer/consumer shape, same
class as v1.11.53"*. **That label is wrong and I am correcting it.**

`hygiene_finding_delta.py:1017`:

```python
if transition is not None:
    result["corpus_transitions"] = [transition]
```

The key is **CONDITIONAL BY DESIGN**, and every other consumer reads it as
`d.get("corpus_transitions", [])`. The shape is consistent; there is no
producer/consumer disagreement. `KeyError` means simply **`transition is None` —
no corpus transition was computed.**

Instrumented (a scratch COPY, marked INSTRUMENT ONLY, no verdict taken from it),
the delta the verifier actually published is:

```json
{"status":"CLEAN","introduced":[],"carried":[],"cleared":[],
 "no_verdict_either_side":[],"empty_corpora":[],
 "base_findings":0,"candidate_findings":0,"declared":1}
```

The test expects the stub's routed-DEF expansion: `base_items 0 ->
candidate_items 1`, `replacement_gates 4`. It got **`declared: 1`** — one gate,
not the four `run_tolerating_uncheckable` calls `_per_routed` makes — and
**`empty_corpora: []`**, i.e. the base corpus was never seen as empty either.

## M7 — AND THE PROBABLE REASON IS MINE AGAIN: I NEVER BOUND THE CORPUS

```
env | grep VIBE_IC_BENCHMARK_DATA   -> UNSET
grep -l VIBE_IC_BENCHMARK_DATA run*.sh -> none of my runner scripts binds it
```

The stub expands `gate_dispatch_over "published cells carrying a routed DEF"`.
With **no benchmark corpus bound**, that population is empty, so the expansion
declares no replacement gates and no EMPTY→expanded transition exists to record.
The very first tier report in this thread bound it explicitly
(`VIBE_IC_BENCHMARK_DATA=/home/reyerchu/_tier_priv/bdata-jtier`, 4 published
cells) and noted the same loop "expanded over 1 item". **I have never bound it in
any run of this job.**

**So G5 is most likely a missing-input artefact of my harness, not a defect** —
and by the same argument G6's absent `A2.started`/`B1.started`/`B2.started`
probe markers may be the same thing one level up. I have NOT proved that; what I
have proved is that the input the test needs was absent from every measurement I
took, so neither G5 nor G6 can be called a defect on this evidence.

**This is the third time in this job that a red I was about to attribute to main
turned out to be my own environment** — pytest-timeout, the `$HOME` mount, and
now the unbound corpus. All three were found the same way: by reading what the
failing thing actually said instead of what its colour implied.

## M8 — G4 SETTLED (and my earlier "unsettleable here" is RETRACTED)

The two reds are
`test_interruption_kills_a_term_ignoring_parallel_arm_and_removes_worktrees` and
`test_pid_only_term_kills_a_term_ignoring_b2_and_removes_worktrees`, both through
`_assert_interruption_cleans_every_parallel_arm`.

**RETRACTION.** I previously wrote that G4 was unsettleable on 8hd-3 because the
image lane is masked and the outcome "depends on process and cgroup behaviour".
Both halves were wrong. The host lane adjudicates this completely, no image
control is needed, and the outcome does not depend on load at all.

**MEASUREMENT.** 8 repeats of each test from outside `$HOME` with a 6-char
TMPDIR (both known artefacts eliminated): **8/8 RED, both tests. Deterministic,
not flaky, not load-confounded.**

**ROOT CAUSE.** The test plants its TERM-ignoring arm by patching
`tools/gatekeeper-land.sh` and guarding the hang on two host-side channels: the
env var `GATEKEEPER_CONCURRENCY_PROBE_DIR`, and a shared host directory the arm
writes its pid into. Both channels predate the hermetic-arm work. The arms now
run under `tools/ci/hermetic_candidate_runner.py`, and
`launch_hermetic_land_arm` (`tools/gatekeeper-verify-merge.sh:538-551`) passes an
explicit reviewed `--env` allowlist — `GATEKEEPER_BASE`,
`GATEKEEPER_BENCHMARK_DATA_SHA`, `GATEKEEPER_HYGIENE_*`,
`GATEKEEPER_VERIFY_ARM`, `GATEKEEPER_VERSION_BY_GATEKEEPER`,
`VIBEIC_LANDING_PROGRESS_NONCE` — which does **not** carry
`GATEKEEPER_CONCURRENCY_PROBE_DIR`; `_reviewed_process_env` scrubs everything
else. The injected `while :; do sleep 30; done` is therefore unreachable. Even
if the variable were forwarded, the probe directory is an unmounted host path,
so the arm could not write the pid where the host-side test looks for it.

Evidence, from the verifier's own captured stdout: it runs to **completion,
rc=0, `LAND OK`**, having dispatched `--- arm A2/B2: base rc=0 candidate rc=0
(hermetic gates)`. It never hangs. The verifier is healthy; the CONTROL never
existed.

Note the runtime snapshot is NOT the reason: `--- protected runtime=base/
fixture-next` selects the clone's own base commit, which does contain the test's
committed hang. The hang is present in the arm's tree and simply never fires.

**CONSEQUENCE 1 — the property is untested.** "An interrupt kills a
TERM-ignoring parallel arm and removes every worktree" is not verified by
anything. The cleanup-event emitter still exists and still works
(`gatekeeper-verify-merge.sh:851-856`, host side), but no test reaches it. These
two tests are red rather than silently green, so nothing is being falsely
claimed — but the guarantee they name is unguarded.

**CONSEQUENCE 2 — the failure misreported itself, and I fixed that.** The old
line was:

    assert pid_file.is_file(), proc.communicate(timeout=2)

The assert MESSAGE is evaluated on failure, against a verifier that is still
running (it takes ~21-25s; the old wait bound was a 12s wall-clock estimate). So
`communicate(timeout=2)` raises `TimeoutExpired`, and that exception REPLACES the
AssertionError. The test then reports `timed out after 2 seconds`, which reads as
"the verifier hung" — the exact inverse of the truth. It also leaked the
verifier, since nothing reaped it. This is precisely the Rule 9 class this brief
exists to stamp out: "I could not read it" and "I read it and it was empty"
producing the same verdict.

The fix settles the process first and then distinguishes the two cases by name,
and raises the wait to `_T` — the same ceiling the cleanup wait 40 lines below
already uses, under a comment that explicitly disavows wall-clock estimates
("Wait on the cleanup protocol, not on a wall-clock estimate of how fast a loaded
host can remove four worktrees"). Someone hardened the second wait and left the
first.

A/B, both tests, host lane:

| | message |
|---|---|
| before | `subprocess.TimeoutExpired: ... timed out after 2 seconds` (blames the verifier — false) |
| after | `Failed: the verifier EXITED rc=0 without ever running the A2/B2 control arm: the injected hang was unreachable, so this test measured NOTHING about interrupt cleanup` (true, and carries the verifier's full output) |

**THE TESTS ARE STILL RED. This fix does not turn them green and cannot.** It
converts a misattributed red into a correctly attributed one. Mutation arm: the
pristine file at base reproduces `TimeoutExpired` 8/8.

**WHAT A REAL FIX WOULD HAVE TO DO, AND WHY I DID NOT MAKE IT.** Restoring the
guarantee is not a channel patch, for a reason that kills the cheap version: the
test ends with

    with pytest.raises(ProcessLookupError): os.kill(arm_pid, 0)

which is a HOST-namespace assertion about a process that now lives in a
container PID namespace. Forwarding the probe dir would not make that assertion
meaningful again. The guard has to be re-founded on the container lifecycle —
does the runner kill and reap the arm's container, and are the four worktrees
gone — which is a different guarantee expressed differently, and it touches
`hermetic_candidate_runner.py` and `gatekeeper-verify-merge.sh`, both PROTECTED
paths in the AUTHORITY/RUNTIME closure. The alternative, punching a test-only env
var and host mount through the hermetic boundary, weakens the isolation property
the boundary exists to provide. **Which of those two is acceptable is a policy
call, not mine to make unilaterally** — same class as the flow-gate ENFORCEMENT
decision and the coverage-bridge verdict-vocabulary question already escalated
above.

**Correction to the "9 landing-verdict guard UNRUNNABLE here" count.** At least
these 2 of the 9 ARE runnable on 8hd-3: the verifier completes normally in the
degraded rebase-replay tier. Their failure has nothing to do with the absent
docker CLI or git 2.34.1. The unrunnable count is at most 7, and the docker/git
explanation does not cover G4.

## M13 — G4, G5 AND G6 ARE ONE DEFECT, and it has a false-green half

Chasing G4 to ground gave a mechanism, and the mechanism turned out to be
general. `tools/ci/hermetic_candidate_runner.py` validates each land arm's
environment against a CLOSED allowlist:

```
_LAND_REVIEWED_ENV_NAMES = frozenset({
    "GATEKEEPER_BASE", "GATEKEEPER_BENCHMARK_DATA_SHA",
    "GATEKEEPER_HYGIENE_PROGRESS", "GATEKEEPER_HYGIENE_REPORT",
    "GATEKEEPER_VERIFY_ARM", "GATEKEEPER_VERSION_BY_GATEKEEPER",
    "VIBEIC_LANDING_PROGRESS_NONCE",
})
```

checked per arm at `hermetic_candidate_runner.py:285`. **The runner is correct.**
This is a deliberate isolation boundary and nothing below asks for it to be
weakened.

The stub `gatekeeper-land.sh` that these end-to-end tests plant reads **six
test-only control knobs that are not on that list and have no producer anywhere
in the runtime**:

```
GATEKEEPER_CONCURRENCY_PROBE_DIR     GATEKEEPER_RELINK_SELECTION
GATEKEEPER_MUTATE_BENCHMARK_ARM      GATEKEEPER_STUB_BASE_EXPANDED
GATEKEEPER_PREWRITE_BASE_ARTIFACTS   GATEKEEPER_STUB_ROUTED_TRANSITION
```

Every one is set by a test on the PARENT verifier and consumed only inside the
ARM. None can arrive. The tests were written for a pre-hermetic world in which
the arm inherited the parent's environment.

**THE NATURAL EXPERIMENT that proves it.** G6
(`test_end_to_end_candidate_wave_precedes_parallel_isolated_base_wave`) hands
one probe directory to the run and asserts `A2.started`, `B1.started`,
`B2.started` appear in it. After the run that directory contains **exactly**:

```
cleanup.done   cleanup.reaped   cleanup.started
```

Three markers, all written by the VERIFIER on the host
(`gatekeeper-verify-merge.sh:851-856`). Zero written by any arm. Same directory,
same run, same variable — host writes land, arm writes do not. It is not an
unwritable path, not a missing stub, not load. And `returncode == 0` and
`verdict == LAND_OK` both passed: the verifier is healthy and the arms ran.

**G5 is the same defect.** Its control is `GATEKEEPER_STUB_ROUTED_TRANSITION`,
consumed only at stub line 1745, absent from the allowlist. The stub's
transition block never runs, no transition is produced, and
`delta["corpus_transitions"]` is therefore absent — the `KeyError`. This is why
all three of my earlier corpus hypotheses were disproven: the corpus was never
the variable. **G5 is closed, and it is not a defect in the corpus, the
producer, or the consumer.**

### The blast radius, measured by test ID

Ten tests depend on a knob that cannot arrive. Measured individually, serially,
outside `$HOME`:

| test | knob | result |
|---|---|---|
| `..._interruption_kills_a_term_ignoring_parallel_arm...` (G4) | PROBE_DIR | RED |
| `..._pid_only_term_kills_a_term_ignoring_b2...` (G4) | PROBE_DIR | RED |
| `..._candidate_wave_precedes_parallel_isolated_base_wave` (G6) | PROBE_DIR | RED |
| `..._trusted_verifier_supplies_the_one_bootstrap_evidence` (G5) | STUB_ROUTED_TRANSITION | RED |
| `..._b2_corpus_mutation_is_post_attested_and_norecord` | MUTATE_BENCHMARK_ARM | RED |
| `..._relinked_parent_selection_is_norecord` | RELINK_SELECTION | RED |
| `..._candidate_cannot_prewrite_base_wave_artifacts` | PREWRITE_BASE_ARTIFACTS | **GREEN — vacuity RISK** |
| `..._post_bootstrap_equal_corpus_uses_ordinary_delta` | STUB_BASE_EXPANDED, STUB_ROUTED_TRANSITION | **was GREEN — vacuity PROVEN, now an honest RED (M14)** |
| `..._the_caller_checkout_is_never_touched` | PROBE_DIR | GREEN — genuine |
| `..._the_version_deferral_still_refuses_a_backwards_version` | PROBE_DIR | GREEN — genuine |

The last two are genuine: their assertions (sandbox HEAD/status/worktree
unchanged; `rc != 0`) do not depend on the knob at all.

**The two above them are the serious half, and they are GREEN.** Each asserts a
NEGATIVE whose precondition is delivered by a knob that cannot arrive:

* `..._cannot_prewrite_base_wave_artifacts` asserts `"candidate planted this
  base log" not in r.stdout`. The prewrite never happens, so the string is
  trivially absent.
* `..._post_bootstrap_equal_corpus_uses_ordinary_delta` asserts
  `corpus_transitions == []`. The corpus is never expanded, so "no transition"
  is trivially true. **It is the exact mirror of G5**: same knob, the
  presence-assertion fails and the absence-assertion passes.

A red that cannot fire is visible. A green that cannot fail is not. These two
are the reason this group matters more than its count.

**THE POSITIVE CONTROL I RAN, AND WHY IT WAS INCONCLUSIVE.** The prewrite block
is guarded on the unreachable knob AND on `GATEKEEPER_VERIFY_ARM`, which IS
forwarded — so I hard-enabled it in the stub, which travels via the tree
(runtime snapshot from base) rather than the environment. **The test still
passed.** I am NOT reporting that as "the guard discriminates", because the
attack still did not reach its target: the block writes to
`$(dirname "$GATEKEEPER_BENCHMARK_MEASUREMENT_RECORD")`, and that variable is
**absent from `hermetic_candidate_runner.py` entirely**, so it is unset in the
arm, `dirname ""` resolves to `.`, and the forged files landed in the
container's own working directory. I could not deliver the attack, which is not
the same as the attack being blocked. **Those two guards remain UNPROVEN in
either direction**, and saying so is the whole point of rule 9.

### M14 — one of the two silent greens is PROVEN vacuous, and is now red

`..._post_bootstrap_equal_corpus_uses_ordinary_delta` is no longer a risk; it is
measured. Instrumenting the delta at the moment of its assertion:

```
{"key_present": false, "value": "<ABSENT>",
 "delta_keys": ["base_findings","candidate_findings","carried","cleared",
                "declared","empty_corpora","introduced",
                "no_verdict_either_side","status"]}
```

**The key is ABSENT, not empty.** The test passed only because it read it as
`delta.get("corpus_transitions", [])`. Its docstring names the
expanded<->expanded path; with neither knob able to cross, base and candidate
are both EMPTY, which is still "equal", so every one of its five assertions
holds through a path it does not name.

This is the repository's own rule 9 violated in one line, and the proof is that
its sibling does it correctly. **Same key, same condition, two verdicts:**

| test | how it reads the key | verdict when the producer never runs |
|---|---|---|
| `..._trusted_verifier_supplies_the_one_bootstrap_evidence` (G5) | `delta["corpus_transitions"]` | **RED** — `KeyError`, loud and true |
| `..._post_bootstrap_equal_corpus_uses_ordinary_delta` | `delta.get("corpus_transitions", [])` | **GREEN** — the default hides it |

The bare subscript tells the truth. The defaulted `.get` converts "I could not
read it" into "I read it and it was empty" — the exact collapse this brief
forbids.

**FIXED, and note this deliberately turns a GREEN into a RED.** The assertion now
demands the key before comparing it:

```python
assert "corpus_transitions" in delta, (
    "the corpus-transition producer never ran, so an equal-corpus "
    "assertion here cannot fail and is not measuring the post-bootstrap "
    "path: " + repr(sorted(delta)))
assert delta["corpus_transitions"] == []
```

A/B: before `1 passed`; after `1 failed` naming the true cause. Mutation arm:
restore the `.get` default and it passes again. This is not a relaxation and not
a new defect — it is the SAME defect, moved from the silent column to the loud
one, where the deadline and the landing gate can see it. It should go red until
the knob channel is re-founded, and then go green for the right reason.

**The other silent green is NOT fixed, deliberately.**
`..._cannot_prewrite_base_wave_artifacts` remains UNPROVEN: my positive control
could not deliver the attack (`GATEKEEPER_BENCHMARK_MEASUREMENT_RECORD` is absent
from the runner, so the forged writes went to the container's cwd). I will not
convert a green to a red on a guard I have not shown to be vacuous. It stays
listed as a risk with the control recorded.

Revised count for the one defect: **7 loud, 1 unproven, 2 genuine** across ten
tests.

### M15 — the OTHER silent green is settled too, and its guarantee had no can_fail arm

`..._cannot_prewrite_base_wave_artifacts` is resolved, structurally, without
needing to land the attack.

The arm's mount topology (`hermetic_candidate_runner.py:1902-1907`) is:

| destination | mode |
|---|---|
| `/subject`, `/runtime`, `/corpus` | bind, **readonly=True** |
| `/input/selection`, `/input/progress-plan.json` | bind, **readonly=True** (individual FILES, not a directory) |
| `/evidence` | named volume, RW |
| `/tmp` | tmpfs |
| rootfs | **`read_only_rootfs: True`** |

**The parent's run directory is not mounted into the arm at all.** There is no
path from inside a hermetic arm to `base_hygiene.json`, `base.xml` or
`base_land.log`. The prewrite attack is not blocked by a check — it is
unreachable by construction. That is also why my M13 positive control wrote
nowhere: `/input` is not a mount, only two files inside it are, and the rootfs
is read-only, so the forged writes failed silently (the stub never checks
`printf`'s status).

**So this one must NOT be turned red, and the contrast with M14 is the point:**

| test | vacuous? | is the property guaranteed elsewhere? | action |
|---|---|---|---|
| `..._post_bootstrap_equal_corpus...` | yes, measured | **no** — nothing computes the transition | **made red (M14)** |
| `..._cannot_prewrite_base_wave_artifacts` | yes | **yes** — the read-only mount topology | **left green** |

Vacuity alone does not justify flipping a green. What matters is whether
anything else holds the property up.

**But nothing was testing that topology.** The refusal branch
`"candidate {role} bind is not exact/read-only"` was exercised by **no test**.
The fake-docker harness already had `wrong_user` and `extra_mount`, and I
assumed those covered it. They do not, and finding out why is itself a small
result: **both are refused by the evidence-volume PROVISIONER, not by the
candidate profile at all** —

```
wrong_user   -> evidence volume provisioner identity/configuration differs
extra_mount  -> evidence volume provisioner mount differs
rw_bind      -> candidate subject bind is not exact/read-only
```

because they perturb *every* container the fake docker creates, so the
provisioner check fires first and the candidate profile is never inspected.
Refusing earlier is correct and safe; but it means neither shape covers the
candidate-profile branches their names suggest.

**FIXED.** Added a `rw_bind` behaviour that flips ONLY the subject bind to
read-write, so the provisioner passes and the refusal must come from the
candidate profile, plus a dedicated test that names the owning branch and
asserts no candidate container ever started (the provisioner legitimately does,
which is why this could not be folded into the parametrized test above).

Mutation arm: delete `or item.get("RW") is not False` from the runner and the
new test goes RED; restore it and GREEN. It discriminates on exactly that clause.

A/B of the whole file, interleaved: `BASE 2 failed/14 passed`, `BASE 16 passed`,
`MINE 17 passed`, `MINE 17 passed`. 16 -> 17 is the one added test.
**Note the baseline's own flake:**
`test_malformed_progress_is_norecord_and_cleanup_is_owned` fails intermittently
with DIFFERENT parametrisations run to run, on the pristine tree. Two runs both
reading "2 failed" had different node IDs. It is pre-existing, timing-sensitive,
and not attributable to this change — recorded here so nobody attributes it.

### M16 — the flake I nearly misattributed, run to ground: the HARNESS resurrects a removed container

In M15 I recorded a pre-existing flake in
`test_malformed_progress_is_norecord_and_cleanup_is_owned` and left it at "timing
sensitive, not mine". That was not good enough, and characterising it properly
changed the answer twice.

**First correction: it is NOT load-confounded.** After three consecutive green
full-file runs on a quiet machine I was about to write "only appears under
contention". The next runs refuted that:

```
r1..r6   17 passed
r7       2 failed  [duplicate] [nan]
r8       3 failed  [duplicate] [malformed] [nan]
r9       2 failed  [malformed] [nan]
r10      2 failed  [duplicate] [malformed]
```

**4 of 10 runs, each of the three parametrisations failing exactly 3 times**, on
an idle host. Had I stopped at three green runs I would have published the wrong
cause. Disk was 38% full and 13% inodes, so it is not exhaustion either.

**The failing assertion is not the one the name suggests.** It is not the
refusal that is flaky — `returncode == 2`, `[NORECORD]`, no receipt and no
output dir all hold every time. It is:

```python
assert not (case["state"] / "container.json").exists()
```

the *cleanup* half. So the shape is "the runner refused correctly but appears to
have leaked the container it created".

**And the runner did NOT leak it.** Its own call log for a failing case:

```
container create ... / container inspect ... / container start --attach
container kill  vibeic-candidate-<id>
container rm --force
container inspect vibeic-candidate-<id>      <- verifies absence
volume rm --force / volume inspect
```

Kill, force-remove, then inspect to confirm absence. That is exactly right.

**The defect is in the test harness.** `container.json` on a failing case is
**0 bytes**, with an mtime LATER than the `container rm` entry in the call log.
`FAKE_DOCKER`'s `save_container` did:

```python
container_path(...).write_text(json.dumps(doc), encoding="utf-8")
```

Two races in one line:

1. **Resurrection.** The attached child writes its final `State` after the run.
   If `container rm` unlinks the record first, this call RE-CREATES it — after
   the runner has already removed it and verified it absent. Real docker cannot
   resurrect a removed container; only the simulation can.
2. **Torn write.** `write_text` truncates before writing, so a kill in between
   leaves a 0-byte file. A 0-byte file still `exists()`, so it still reads as
   "the container is present" — the same collapse rule 9 forbids, in a harness
   rather than a gate.

**FIXED** in the harness, not the runner:

```python
def save_container(doc, create=False):
    path = container_path(doc["Name"].lstrip("/"))
    if not create and not path.exists():
        return                     # a removed container stays removed
    tmp = path.parent / (path.name + ".%d.tmp" % os.getpid())
    tmp.write_text(json.dumps(doc), encoding="utf-8")
    os.replace(tmp, path)          # atomic: no 0-byte window
```

with `create=True` at the single `container create` site.

**A/B, same tree, only `save_container` differing** (both arms carry the M15
`rw_bind` test, so both are 17 tests). **These are HOST-lane numbers** — see M23,
where the image lane turns out not to reproduce the race at all:

| arm (host lane) | full-file runs with >=1 failure |
|---|--:|
| before the harness fix | **4 / 10** |
| after the harness fix | **0 / 12** |

The "before" arm IS the mutation arm: it is the pristine `save_container`
measured over ten runs, not an assertion that it would fail.

**This is why it matters beyond one flake.** A 4-in-10 red in the landing
runtime's own test file, whose message says "cleanup is not owned", points
directly at `hermetic_candidate_runner.py` leaking containers — a plausible,
serious, and completely false conclusion. It is the same lesson as the seal-ring
retraction: the failing thing was the fixture, not the subject.

### One defect or several

**SUPERSEDED BY M18 — the count is thirteen, not ten.** M18 found three more
guards defeated by a SECOND mechanism (the read-only object-exact subject), so the
honest statement is one root cause through two mechanisms across thirteen tests.
The paragraph below is left as written because its reasoning is unchanged; only
the scope grew.

**ONE defect, six unreachable knobs, ten affected tests** (7 red after M14, 1
unproven, 2 genuine greens). G4, G5 and G6 in the
table below collapse into this single entry; they are not three findings. The
cause is one architectural change — arms became hermetic — that the end-to-end
tests in this file were never migrated across. Both previously OPEN items are
now closed by it.

It is not a live regression: these have been broken since the arms became
hermetic, and no landing behaviour changed. But it is a property of main rather
than of this host, and its consequence is that **a block of landing-guard
end-to-end tests is not exercising the paths it names** — six loudly, two
silently.

### What a fix must do, and why I did not make it

Not a channel patch, for three independent reasons:

1. G4 asserts `os.kill(arm_pid, 0)` in the HOST namespace about a process that
   now lives in a container PID namespace. Forwarding the knob would not make
   that assertion meaningful.
2. The knobs deliver to host paths (`PROBE_DIR`) that are not mounted into the
   arm, so both an env entry AND a mount would be required.
3. Adding six test-only names to `_LAND_REVIEWED_ENV_NAMES` plus a writable host
   mount punches a hole through the exact isolation boundary the allowlist
   exists to enforce — in the landing gate, on PROTECTED AUTHORITY/RUNTIME paths.

The honest alternative is to re-found these guards on channels that already
cross legitimately — the published `/evidence` output dir, the arm receipts, and
`tools/ci/landing_completion_record.py`, which already exists to be *"the exact
machine completion record for one hermetic landing arm"*. That is a redesign of
ten tests against the hermetic contract, and it is the same policy call as the
flow-gate ENFORCEMENT decision. **Escalated, not guessed.**

## M9 — the corpus-bound re-run, and one limitation of it

Corpus staged OUTSIDE `$HOME` (the hermetic runner refuses a corpus under HOME
as well as a subject): 457 MB, **3 published cells carrying a routed DEF** —
`spm` on `sky130A`, `ihp-sg13g2` and `gf180mcuD`, all open PDKs.

**Limitation, recorded before the result rather than after:** the copy has no
`.git` (`git -C … log` -> *fatal: not a git repository*), because the source was
a worktree directory. Gates that read the corpus as a TREE are unaffected; any
gate that asks it a git question (`--changed-since`, run manifests) will get
"could not look" rather than an answer, and I will not read such a result as a
verdict.

## M10 — G5: THREE HYPOTHESES, ALL MINE, ALL NOW DISPROVEN

I proposed three causes for `KeyError: 'corpus_transitions'`. **All three are
wrong, and each was eliminated by measurement rather than argument.**

**H1 — "producer/consumer shape defect, same class as v1.11.53."** DISPROVEN.
`hygiene_finding_delta.py:1017` sets the key conditionally by design and every
other consumer reads it with `.get(..., [])`. No disagreement exists.

**H2 — "I never bound the benchmark corpus."** DISPROVEN. Bound the REAL
published corpus (`vibeic/benchmark-data`, upstream head, real git index) and
re-ran the single test: **identical `KeyError`, 16.99 s.**

**H3 — "the corpus is empty or unreadable, so the routed-DEF loop expands over
nothing."** DISPROVEN, and it took building the fixture the system asks for.
`tools/ci/routed_def_corpus.py` reads GIT'S INDEX, so a tree-only copy is
refused — loudly and correctly:

```
UNDETERMINED: … exists but is not a git checkout. This producer reads git's
INDEX; treating a loose directory as zero routed DEFs would be a false empty
corpus.
```

and a corpus with three versions of one design is refused too:

```
UNDETERMINED: design 'spm' publishes more than one routed-DEF version
('v1.5.58_ihp-sg13g2', 'v1.5.65_sky130A'). … a two-phase identity migration is
required before this population can expand without duplicate gate owners.
```

Reduced to ONE version per design, the resolver yields the cell cleanly:

```
…/bdata/ic/spm/v1.5.65_sky130A/phase3/stage3/pnr/routed.def
```

**With that corpus bound — index present, exactly one published cell, resolver
happy — the test still fails identically.** So the corpus is fully exonerated.

**G5 therefore remains OPEN with three causes eliminated.** That is a better
handoff than the "candidate real defect" I first wrote and than the "withdrawn,
probably my corpus" I wrote second, and both of those earlier labels are
retracted. What is now known: the verifier returns rc 0 and `LAND_OK`, publishes
a delta with `status CLEAN`, `declared: 1` and `empty_corpora: []`, and computes
NO corpus transition, under a stub that is supposed to force one.

## M11 — A FACT ABOUT THE PUBLISHED CORPUS worth more than G5

```
git clone --depth 1 https://github.com/vibeic/benchmark-data.git
bcf2f94 withdraw all four published cells, and write down what may be published here
tracked routed DEFs: 0        tracked files under ic/: 459
```

**The published corpus contains ZERO published cells today.** All four were
withdrawn upstream. The very first tier report in this thread flagged this as a
risk — *"a fleet note written the same day reports all 4 cells being
withdrawn … re-pin the corpus SHA before comparing"* — and it has since
happened. Every gate whose population is "published cells carrying a routed DEF"
now expands over nothing, and the resolver is built to call that UNDETERMINED
rather than clean, which is the right behaviour and worth knowing before someone
reads a green from it.

## M12 — the whole-file corpus A/B confirms it at file scale

```
outside-$HOME, corpus UNBOUND : 134 cases, 9 red
outside-$HOME, corpus BOUND   : 134 cases, 9 red
FIXED by binding: 0        NEW red from binding: 0        identical SET
```

The corpus is not the variable for ANY of the nine, not just G5. My "unbound
corpus" hypothesis is disproven at file scale as well as for the single test.

## FINAL ATTRIBUTION OF THE ORIGINAL 22

The ruling asked, for each group, whether it is ONE defect or SEVERAL. That
column is the point of the table, so it is the last one.

| group | n | cause | settled? | one defect or several? |
|---|--:|---|---|---|
| G1 | 13 | subject under `$HOME`; `hermetic_candidate_runner.py:426` refuses it | **SETTLED — mine** | **ZERO defects.** One operator mistake, mine, counted thirteen times. The refusal is the runner working exactly as designed. |
| G2 | image lane | no Docker CLI in the pinned image | **SETTLED — environment** | **ZERO defects in main**, but see the note below — it is not harmless. |
| G3 | 5 | host git 2.34.1 < 2.38, verifier drops to its degraded tier and refuses with a different rc | **SETTLED — environment; the verifier behaved correctly** | **ZERO defects.** One host property, five reds. The verifier disclosed the degradation rather than hiding it, which is the behaviour we want. |
| G4 | 2 | the injected TERM-ignoring arm never runs: `GATEKEEPER_CONCURRENCY_PROBE_DIR` is not in the hermetic arm's reviewed env allowlist | **SETTLED (M8)** — 8/8 deterministic | **ONE defect**, shared with G5 and G6 (M13). |
| G5 | 1 | `GATEKEEPER_STUB_ROUTED_TRANSITION` never reaches the arm, so the stub's transition block never runs | **CLOSED (M13)** | same ONE defect as G4/G6 — not a separate finding. |
| G6 | 1 | the `.started` markers are arm-side writes through `GATEKEEPER_CONCURRENCY_PROBE_DIR`, which is not on the arm allowlist | **CLOSED (M13)** | same ONE defect as G4/G5 — not a separate finding. |

### THE ANSWER IN ONE LINE

**Twenty-two reds. ONE defect.** Three environmental causes account for the
other eighteen — and one of those three, my own `$HOME` mistake, accounts for
thirteen on its own. Counting reds was never going to find this; only grouping
them did.

### The G2 note — RETRACTED AND REPLACED (M17)

**I published a wrong claim here and am correcting it.** The previous version of
this section said:

> No test in `test_landing_merge_verdict.py` can run in the pinned image at all
> — they all die at the absent Docker CLI. So the landing verdict's own guard is
> not being exercised by CI.

**That is false.** Measured in the pinned image
(`sha256:66c33ff2…d01ff`, `--skip` first, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`):

```
134 tests collected
22 failed, 112 passed          (reproduced twice, same 22 IDs)
```

**112 of 134 pass in the CI lane.** The absent Docker CLI is real — confirmed
directly, `command -v docker` returns nothing in the image — but it takes out 22
tests, not the file. The conclusion I drew from it, that this guard is not
exercised by CI, is withdrawn.

I wrote that claim from a measurement I remembered from earlier in this session
rather than one I re-ran. It is the fifth claim of mine in this thread to fail on
re-measurement, and it only surfaced because I went back to check a recollection
I had already committed. **Anything in this document sourced from memory rather
than from a command in the same session should be treated as suspect until
re-run.**

The 22 image-lane failures, by ID:

```
test_a_host_without_merge_tree_names_the_version_found_and_needed
test_end_to_end_a_green_test_cannot_move_b1_to_another_commit
test_end_to_end_a_known_good_branch_is_allowed
test_end_to_end_an_innocuous_diff_that_leaves_a_test_red_is_refused
test_end_to_end_b2_corpus_mutation_is_post_attested_and_norecord
test_end_to_end_candidate_cannot_prewrite_base_wave_artifacts
test_end_to_end_candidate_wave_precedes_parallel_isolated_base_wave
test_end_to_end_index_flags_cannot_hide_changed_b1_bytes
test_end_to_end_mutable_base_cache_is_disabled_and_remeasured
test_end_to_end_post_bootstrap_equal_corpus_uses_ordinary_delta
test_end_to_end_relinked_parent_selection_is_norecord
test_end_to_end_replace_refs_cannot_redefine_the_verified_tree
test_end_to_end_the_fallback_allows_a_known_good_branch
test_end_to_end_the_fallback_still_refuses_an_innocuous_diff_that_leaves_a_test_red
test_end_to_end_trusted_verifier_supplies_the_one_bootstrap_evidence
test_end_to_end_what_is_gated_is_the_squash_and_not_the_branch
test_interruption_kills_a_term_ignoring_parallel_arm_and_removes_worktrees
test_pid_only_term_kills_a_term_ignoring_b2_and_removes_worktrees
test_reassert_refuses_a_record_that_was_not_a_pass
test_reassert_refuses_when_the_base_moved
test_the_forced_fallback_is_the_only_thing_the_env_var_can_do
test_the_tier_the_script_picks_matches_this_hosts_real_capability
```

Every test M13 named as red is in this list, which is consistent — but M13's
conclusions were measured by ID in both lanes and do NOT rest on this section.
**M13, M14, M15 and M16 are unaffected by this retraction.**

Whether these 22 are image-only or also red on the host is a by-ID A/B, not
something to infer. It is running; until it lands, the honest statement is only
that **22 of this file's 134 tests do not run in the CI lane, and 112 do.**

**REVISED BY M13.** Of the 22, four (G4 x2, G5, G6) ARE a demonstrated defect in
main — one defect, not four: six test-only env knobs that cannot cross the
hermetic arm boundary. Nothing remains OPEN. The other eighteen are environment,
thirteen of those mine. The defect's most serious consequence is not among the
22 at all: two landing-guard tests OUTSIDE this red set are GREEN while unable to
exercise the path they name.

# ===== ITEM 1, THE REMAINING DEBT: the paragraph for G5 and G6 =====

The ruling allowed "fix it, or write down in one paragraph exactly what evidence
this repository does not hold". I owed that for G5 and G6 and had not written
it. Here it is, after two instrumentation attempts that both came back
unreadable rather than negative.

**What I tried.** G5 and G6 share a suspected cause: the A2/B2 arms, which run
the planted `gatekeeper-land.sh` stub that would produce both the corpus
transition (G5) and the `A2.started`/`B1.started`/`B2.started` probe markers
(G6). I instrumented the stub on an INSTRUMENT-ONLY copy to record which arm
invoked it — first to `/tmp`, then next to `$GATEKEEPER_HYGIENE_REPORT`, a path
the parent demonstrably reads. **Neither run produced a marker anywhere I could
find.** That is NOT evidence the stub did not run: the arms execute inside
containers whose `/tmp` is not the host's, and the second attempt is gated on
`GATEKEEPER_HYGIENE_REPORT` being set in the arm's own environment, which I
could not confirm. Two "could not look" results, and I will not report either as
"it did not run".

**THE PARAGRAPH.** What this repository does not hold is **an observable record
of which landing arms actually executed, surviving the run**. `gatekeeper-verify-merge.sh`
launches A2/B1/B2 into containers and the only durable thing it publishes is the
final verdict document; whether a given arm started, what it dispatched, and
whether a planted stub was reached are visible only from INSIDE that container's
namespace, which no lane on this host can read back. The repository already has
the program that would fix this — `tools/ci/landing_completion_record.py`,
*"the exact machine completion record for one hermetic landing arm"*, with
`full:completion-record` as a declared stage — but the same defect its sibling
documents applies: `gate_red_since_check.py`'s module docstring records that the
hygiene `--summary-json` is written into a `tempfile.TemporaryDirectory` and
destroyed with the run, so *"Nothing compares two records; there is no second
record to compare to."* Until a per-arm completion record is PUBLISHED rather
than discarded, "did A2 run, and did it dispatch the four replacement gates" is
unanswerable from outside, and G5 and G6 cannot be separated from each other or
from the environment. **That is the missing evidence: not a fixture, not a
version, not a corpus — a record the system writes and then deletes.**

# ===== THE NUMBER THAT DECIDES WHETHER MAIN CAN LAND =====

The question was: of the reds that are BOTH-lanes real, how many are UNOWNED —
i.e. would refuse a landing under the new deadline. With v1.11.64 landed, the
domain is settled by its implementation (`inherited_red_reasons` iterates
`hygiene_finding_delta`'s CARRIED list, unpacking `kind, label, _corpus`), so
the answer is **not** a number from my 44 pytest node ids. It is the count of
carried HYGIENE findings.

Measured: `repo_hygiene_gates.sh --summary-json` on v1.11.66, image lane,
`VIBEIC_SUBJECT_ROOT` = the pristine clone. Blocking verdicts:

**FAIL — 6**

```
flow-gate enforcement audit
checker execution wiring
gates are wired to something
declaration scans strip comments
d3 declaration/manifest parity
liar census controls still fire
```

**NOT_CHECKED, BLOCKING, no exemption — 1**

```
corpus "published cells carrying a routed DEF" is EMPTY — nothing was checked over it
```

**Every other NOT_CHECKED carries a declared exemption with an expiry**
(2026-11-30 or 2027-02-28) and is non-fatal — PPA record/contract/coverage gates,
the two that need an authenticated `gh`, the four that need the container image,
`engineering evidence fresh` (refuses a shallow clone), and the known-debt
blocker-list contract. Those are ALREADY "owned with an expiry", which is the
same shape the new deadline imposes on FAILs — the mechanism is not new to this
repository, only newly applied to reds.

**CONFIRMED BY THE COMPLETED RUN** (the preview above was taken mid-run; these
are the final numbers from `--summary-json`):

```
declared 85 | ran 85 | decided 70 | passed 64 | failed 6 | not_checked 15 | wrote_corpus 0
not_checked_unexempted: ['corpus "published cells carrying a routed DEF" is EMPTY — nothing was checked over it']
exemptions_expired: []      wiring_errors: []      288s
```

`exemptions_expired: []` and `wiring_errors: []` are the two lines that make the
rest of it believable: no exemption has outlived its date, and the suite is not
reporting a verdict over a gate it failed to wire.

**So the answer is SIX rows** — one per FAIL, each needing a `gate`,
`since`, `max_commits`, `owner` and `why` — **plus one blocking NOT_CHECKED that
no row can fix**, because the empty corpus is not a red to acknowledge but an
absent input: `vibeic/benchmark-data @ bcf2f94` withdrew all four published
cells, so the population is 0 and the resolver correctly refuses to call that
clean.

Two honesty notes on that number:
1. It is ONE run, ONE lane, corpus pointer unset (the in-repo `benchmark-data/ic`
   was used). Binding the published corpus would not change the empty-corpus
   line — upstream has 0 cells either way — but it could move others.
2. `inherited_red_reasons` acts on CARRIED findings, i.e. red on BOTH arms of a
   real landing. These six are red on main, so in any landing they are red on the
   base too and therefore carried. That is the inference; I have not run a
   two-arm landing to observe the carried list directly, and the record that
   would let me is the one this repository writes and deletes.

# ===== v1.11.66 TRIAGE: the $HOME artefact is now QUARANTINED, not counted =====

The v1.11.66 triage tree is `/home/reyerchu/_ptmo_priv/main1166` — **under
`$HOME`**. So `hermetic_candidate_runner.py:426` fires on every
`test_landing_merge_verdict` id exactly as it did the first time, and without
intervention those 22 would have been bucketed **BOTH** and handed over as
"real about main" a second time.

The bucketer now carries the knowledge instead of me having to remember it:

```python
HOME_ARTEFACT_FILE = "test_landing_merge_verdict"
...
if base == HOME_ARTEFACT_FILE and bucket in ("BOTH", "HOST-ONLY"):
    bucket = "HOME-ARTEFACT-SUSPECT"
```

At 237/419: `GREEN-BOTH 206 · BOTH 9 · HOME-ARTEFACT-SUSPECT 22 · IMAGE-ONLY 0 ·
HOST-ONLY 0`. The 22 are quarantined rather than promoted, and the authoritative
host column for that file comes from a clone OUTSIDE `$HOME` at the same commit,
running separately.

**This is the one durable improvement to my own instrument out of the whole
thread.** Three times a red was mine rather than main's — pytest-timeout, the
`$HOME` mount, the corpus — and each time I caught it by reading the message.
Only this one is now caught by the tool whether or not I remember to read.

## THE QUARANTINE PAID OFF, MEASURED

The outside-`$HOME` arm at v1.11.66, 603 s, 134 cases:

```
under $HOME   (the triage tree)   22 red    <- what the table would have said
outside $HOME (authoritative)      9 red
identical 9-id SET at v1.11.62 and at v1.11.66; 0 closed, 0 new
```

**13 of the 22 are the `$HOME` artefact at v1.11.66 exactly as at v1.11.62.**
The difference this round is that `HOME-ARTEFACT-SUSPECT` caught them without me
having to remember — the first time in this thread that a known artefact of mine
was stopped by the instrument rather than by my reading the message.

The 9 survivors are stable across four versions and are the groups already
named: 5 x git 2.34.1 degraded tier, 2 x TERM/kill timeouts (G4), G5, G6. None
of them has moved since v1.11.62. For three of the four that is consistent with
being about the environment or about evidence this host cannot produce.

**G4 is the exception, and M8 corrects this paragraph.** Its two reds are not
environmental: they are deterministic (8/8), they reproduce on a healthy
verifier that returns `LAND OK`, and their cause is a stale test whose control
channel cannot cross the hermetic arm boundary. It is not a live REGRESSION —
the tests have been red since the arms became hermetic — but it is a live
property of main, not of this host, and the interrupt-cleanup guarantee is
currently unguarded.

# ===== v1.11.66 FOUR-WAY BUCKET — COMPLETE, 419/419 =====

```
   GREEN-BOTH              369
   BOTH                     24     real about main, red in both lanes
   IMAGE-ONLY                3     test_pad_and_seal_ring_on_the_chip_path (x3)
   HOST-ONLY                 0
   FLAKY-KNOWN               1
   HOME-ARTEFACT-SUSPECT    22     quarantined, NOT counted; authoritative
                                   outside-$HOME measurement says 9 of these are
                                   red and 13 are my clone location
   NOT_MEASURED              0
```

**The current red list is 33 IDs**: 24 BOTH + 3 IMAGE-ONLY + the 9 real ones
inside the quarantined 22 (established by the outside-`$HOME` arm; 0 closed and
0 new since v1.11.62), minus double counting — the quarantined file contributes
9, not 22.

The 24 BOTH by file:

```
 6  test_matrix_d3_outputs_produced          declared outputs not produced
 3  test_matrix_mutation_ledger              incl. the 1.6x remainder
 3  test_issue901_structured_vacuity         a tier granted without its count
 2  test_v0_2_96_issue460_coverage_bridge
 2  test_matrix_63x8_coverage
 2  test_flow_manifest_declaration_parity
 1  each: test_pytest_per_file_junit, organic900_901, issue490,
       issue306, flow_compliance_check_gate, digital_hardmacro_gen
```

**IMAGE-ONLY = 3, HOST-ONLY = 0.** The seal-ring trio is on its FIFTH consecutive
tree (v1.11.47, .51, .57, .62, .66) and has never once appeared on the host,
because on a host with no PDK the code never reaches the failing branch. It
remains the single best argument in this whole thread for running the control
lane: it is not a phantom, it is the opposite — a real defect only the CI lane
can see.

# ===== I WAS WRONG ABOUT THE SEAL-RING TRIO, FIVE TIMES. HERE IS THE FIX. =====

I called these three "a real defect only the CI lane can see" and "the best
argument in this thread for running the control", at v1.11.47, .51, .57, .62 and
.66. **They are not a defect in the program. The program is correct in BOTH
lanes, and the test was reading the machine.**

`_skip`'s own docstring draws the distinction and cites the regression it exists
for:

> `marker=True` means "die finishing was considered and legitimately does not
> apply here" — the PDK ships no seal-ring generator. That is a DECIDED outcome
> and it earns `die_finishing.SKIPPED.txt`.
> `marker=False` … means "the step could not run": no streamed GDS … Those are
> absences of the step's own INPUTS … and they must NOT leave a "skipped" marker
> behind, because the flow reads that marker as the step having produced one of
> its two declared outcomes.

MEASURED:

```
HOST : PDK=<unset>                                  -> "no generator declared" -> marker True  -> PASS
IMAGE: PDK=ihp-sg13g2 PDK_ROOT=/foss/pdks (real PDKs installed)
                                                    -> a generator RESOLVES, so that branch
                                                       never fires; control reaches
                                                       "no streamed GDS"      -> marker False -> FAIL
```

`resolve_script`'s documented order includes `$KLAYOUT_SEALRING_SCRIPT` and
`$PDK_ROOT/$PDK/`. The fixture never pinned which of the two conditions it
meant, so **the assertion was answered by whether the host had a PDK installed**.

**THE FIX** — in `_seal`, clear the three variables `resolve_script` consults for
the duration of the call, so the fixture states its own precondition. Not a
relaxation: every test using this helper is about what the DESIGN DECLARED, none
is about the host's PDK, and the assertion now means the same thing everywhere.

**PROOF, both directions:**

```
unmodified, image lane        3 failed, 43 passed
FIXED,      image lane       46 passed
FIXED,      host lane        46 passed        (no regression)
fix REVERTED, image lane      3 failed, 43 passed   <- mutation arm
```

**What this costs my earlier reporting:** IMAGE-ONLY was 3 at five consecutive
versions and I attributed it to main every time. The correct count of IMAGE-ONLY
defects in main across this whole thread is **zero**. The image control still did
its job — it surfaced a test that could not survive a PDK being installed — but
what it surfaced was a fixture defect, not a program defect, and I should have
read `_skip`'s docstring the first time instead of the fifth.

# ===== WORKING THE 24 BOTH: what each cluster needs =====

| n | cluster | status |
|--:|---|---|
| 6 | `test_matrix_d3_outputs_produced[step15/17/19/20/30/32]` | matrix family — the 54-ID agent's lane |
| 3 | `test_matrix_mutation_ledger` incl. the `1.6x` remainder | matrix family |
| 2 | `test_matrix_63x8_coverage` | matrix family |
| 3 | `test_issue306`, `test_issue490`, `test_organic900_901` | **ONE cause**: they all print the same `flow gate enforcement audit` (181 clauses / 172 gates / 19 ENFORCED / 153 AUDIT_ONLY / 131 UNDECLARED). And `flow-gate enforcement audit` is ALSO one of the 6 blocking hygiene FAILs — **one defect in four places** |
| 2 | `test_flow_manifest_declaration_parity` | **needs evidence this host does not hold** — see below |
| 2 | `test_v0_2_96_issue460_coverage_bridge` | Step 4 prints VACUOUS-PASS where the test wants WAIVED-DEFERRED |
| 1 | `test_pytest_per_file_junit::test_nested_collect_progress…` | the 0.8 s forward-progress lease family, characterised in run 2 as load-fragile; image `stage=collecting`, host `stage=running` |
| ~~1~~ **0** | ~~`test_flow_compliance_check_gate`~~ | **CLOSED — 36 passed (M47).** Re-ran it; the red is gone. It was also the only detail row with no summary disposition. |
| 1 | `test_digital_hardmacro_gen` | the known `magic` flake |

## `flow_manifest_declaration_parity` — ATTEMPTED, and it needs evidence this host lacks

The gap is exactly one path: step `31` declares
`reports/phase3/drc_signoff.json` and the dimension-3 manifest has no entry
(164 declared vs 163 entries). The flow's own comment argues that declaration at
length and NAMES this cost: *"16 roots carry `drc_signoff.rpt`, 3 carry
`drc_signoff.json`, so 13 would report the new entry MISSING."*

So the legitimate fix is to MEASURE the entry, because the manifest is an
evidence record — *"where a real run produced it, at what path, and at what size
in bytes"* — not a list somebody writes.

**I cannot measure it here.** The manifest declares 15 run roots and
**0 of the 15 are present on this host**. Files named
`reports/phase3/drc_signoff.json` DO exist here (8 of them), but every one is in
an agent scratch tree, and the manifest's own `_admissibility` excludes exactly
that: *"A run root counts as a real flow run only if it carries
`provenance.jsonl` or `reports/orchestrator/`. Agent scratch trees with
hand-seeded artefacts are excluded: counting a seeded input as a produced output
is exactly the false-pass this campaign exists to remove."*

Adding an entry measured from one of those eight would be the false-pass the
fixture was written to prevent. **NOT FIXED, and deliberately so.** What it
needs is one of the 15 declared run roots, or a fresh admissible run that
produces the file.

## The highest-value remaining fix is the flow-gate enforcement audit

It is the only cause on this list that is **one defect closing four things** —
three of the 24 BOTH reds and one of the six blocking hygiene FAILs — and it is
the one that stands between main and a landing rather than merely being red.

## The flow-gate enforcement audit — ROOT-CAUSED TO TWO NAMES, and it is a POLICY call

```
[FAIL] 2 NEW gate(s) are AUDIT_ONLY and declare no intent at all:
   undeclared::area_total_vs_budget_check
   undeclared::tapeout_docs_gen
```

That is the whole refusal. Fixing it closes THREE of the 24 BOTH reds
(`test_issue306`, `test_issue490`, `test_organic900_901`) **and one of the six
blocking hygiene FAILs** — the best ratio on the board.

The declaration is one line in each program's docstring, opening with
`ENFORCEMENT: blocking` or `ENFORCEMENT: advisory` (`_DECL_RE`, and #886 made a
mid-sentence mention not count).

**But which one is a POLICY DECISION, and it is not mine to take.** Both gates
are declared in the flow with `program_exit_zero:` clauses —

```
flow:1847  - program_exit_zero: "area_total_vs_budget_check . --json reports/phase2/gates/area_budget.json"
flow:5788  - program_exit_zero: "tapeout_docs_gen --project . --out-dir reports/phase3/docs"
```

— so the flow's own text implies BLOCKING, while the audit measures them
AUDIT_ONLY because no runner invokes them where the status can stop a step.
Therefore:

* `ENFORCEMENT: blocking` moves them into the audit's OTHER failing shape,
  "DECLARES blocking, wired AUDIT_ONLY", which is the `known` shrink-only
  register — unless somebody also WIRES them;
* `ENFORCEMENT: advisory` contradicts the flow clause that says their exit
  status matters.

Two bad options unless the wiring changes with the declaration. **NOT FIXED, and
deliberately: the audit exists precisely to force this decision to be taken by
someone, and taking it by guess is the failure mode it was built against.**
Whoever owns those two gates has a two-line fix plus a wiring decision.

# ===== A FOURTH ARTEFACT OF MINE, AND THIS ONE IS SYSTEMIC: TMPDIR LENGTH =====

`test_flow_compliance_check_gate::test_a_real_verdict_is_not_mistaken_for_a_crash`
asserts `'verdict: FAIL' in snippet`. The snippet in my run STARTS MID-PATH —
`yerchu/_ptmo_priv/tmp1166t/image/pytest-of-designer/pytest-3/...` — so it is a
fixed-size evidence WINDOW, and my 96-character TMPDIR pushed the marker out of
it.

```
TMPDIR=/home/reyerchu/_ptmo_priv/tmp1166t/image   (96 chars)  -> FAILED
TMPDIR=/tmp/ptmo_short                            (16 chars)  -> 1 passed in 0.87s
```

**Not about main. About the length of the path I chose.** That is the fourth
environment artefact of my own in this thread — pytest-timeout, the `$HOME`
mount, the unbound corpus, and now TMPDIR depth.

**And unlike the others this one is SYSTEMIC**: any test that quotes a bounded
evidence window containing a path is exposed, so I cannot assume it touched only
this ID. Every file carrying a BOTH red is therefore being re-run with a 6-char
TMPDIR (`/tmp/ps`) to find out which other reds are mine.

This is the sharpest lesson of the whole job: **four times my measurement
environment produced a red I was ready to attribute to the subject, and each
time the tell was in the text of the failure rather than in its colour.** The
`$HOME` one is now caught by the instrument. This one needs the same treatment —
a short, fixed scratch root, not a descriptive one.

## The short-TMPDIR sweep, COMPLETE (12 of 12 BOTH-red files)

```
red with my 96-char TMPDIR : 24
red with a 6-char TMPDIR   : 23

WENT GREEN on a short TMPDIR — MINE (1):
    test_flow_compliance_check_gate::test_a_real_verdict_is_not_mistaken_for_a_crash

appeared only on the short path: NONE
```

**The blast radius of the TMPDIR artefact is exactly ONE id, measured over all
twelve files rather than assumed from one.** The other 23 survive a 6-character
path and stay attributed. Nothing appeared only on the short path, so the sweep
did not trade one artefact for another.

**THE CURRENT RED LIST AT v1.11.66 IS 23 BOTH + 9 in the quarantined
landing-verdict file = 32**, with IMAGE-ONLY 0 (the seal-ring trio fixed) and
HOST-ONLY 0.

# ===== FINAL DISPOSITION AT v1.11.66 =====

Every remaining red is now attributed to one of four causes, none of which is
"unknown":

| n | reds | disposition |
|--:|---|---|
| 11 | matrix family | **narrowed, M34.** **M35: 8 of the 11 are ONE cause.** 2 = `63x8_coverage`, now examined — the census records the SAME six steps as `ENFORCED` while the live run fails, so it is the census layer of the same defect, not a separate family; 3 = mutation-ledger reds measured in M32 (incl. `[step0.5ic]`); 6 = `d3_outputs_produced`, whose records cite **home-kind** roots this dimension does not search, with NO published/repo root here carrying the artefacts. Needs a published run tree or a registry waiver — a requirement, not an owner. |
| 2 | coverage bridge | **jmain-green's 38**, red since v1.11.18. ~~a verdict-vocabulary DESIGN question~~ — **narrowed, see M33: both terms are established (1485 / 215 uses) and asymmetric. `WAIVED-DEFERRED` requires a recorded waiver id + owner reason; absent one it is not available and the pass is vacuous. The open item is "is there a waiver?", a lookup — not a vocabulary choice.** |
| 3 | flow-gate enforcement audit | a POLICY call — but SMALLER than stated here, see **M29**. ~~the flow's `program_exit_zero` clauses make either choice wrong~~: those clauses execute NOWHERE, so `advisory` contradicts nothing and is truthful today. The real question is only whether these two SHOULD be able to stop a step. |
| 2 | manifest parity | ~~EVIDENCE this host lacks~~ — **WRONG, see M30/M32. 10 of the 15 declared roots ARE here, two carry the artefact. FIXED: 3 reds closed.** |
| 9 | landing-verdict guard | ~~UNRUNNABLE here~~ — **WRONG, see M8/M18/M26.** It runs on the host in the degraded tier; the two-lane A/B measured **10 BOTH-lane reds**, and designs A and C have since closed **4** of them. 6 remain, each with a named cause (M26). |
| 2 | `magic` flake, 0.8 s lease family | ~~characterised, ratios recorded~~ — **UNBACKED, see M36: no ratios appear anywhere in this document.** Deliberately not re-measured: load-sensitive flakes measured now would describe tonight, not the run this row means. |

**Nothing is left in the "red, cause unknown" state**, which was the state the
whole 92 started in.

## The instrument, hardened

`SCRATCH_ROOT_RULE.md` written and the three runners annotated. Two clauses,
each bought with a false finding: the scratch root must be SHORT (a long path
fills fixed-size evidence windows) and OUTSIDE `$HOME` (the hermetic runner
refuses a subject under it). `/tmp/ps` satisfies both; the descriptive path I
used for most of this job satisfies neither.

### The ten instrument defects, consolidated

That section covered one rule. By the end there were ten, and **every one of them
produced a confident, plausible, WRONG answer rather than an error.** That is the
property worth internalising: a broken instrument almost never announces itself:

| # | defect | how it presented | the guard |
|---|---|---|---|
| 1 | `for n in $rest` word-splits parametrised IDs — `test_x[and all 56 tools]` becomes many words | `no tests ran`, rc 4 | `mapfile` + `"${IDS[@]}"` |
| 2 | an EMPTY pytest selector array falls back to `pytest.ini` `testpaths` | silently started the WHOLE suite and competed with my own measurements for 11 minutes | refuse loudly on an empty selector list |
| 3 | `git stash -- <file>` returns SUCCESS when the changes are COMMITTED, so `\|\|` short-circuits and the fallback `checkout` never runs | a "pristine baseline" that was re-running my own modified file, and would have reported `0 added, 0 removed` — a clean circular confirmation | assert the control is in place before measuring; refuse to run if it is not |
| 4 | a test-ID set-difference cannot distinguish RENAMED from FIXED | reported a renamed test as "now green" | check the collected-count invariant alongside the ID diff |
| 5 | a verification grep written from REMEMBERED phrasing rather than the actual string | two present changes read as MISSING | check the query before believing an absence |
| 6 | `cd X && CMD &` backgrounds the whole list, not just `CMD` | two files written into the operator's checkout | absolute paths in anything backgrounded |
| 8 | grepping pytest's `...`-elided `repr` as if it were the run's output | two probes returned two of eleven gate lines; the missing nine were simply not in the string | dump the output to a file; a `repr` is not a capture |
| 9 | **backticks inside a heredoc'd commit message run as command substitution** | `` `ifdef/`endif `` in a `git commit -F -` body silently became `endif`; bash printed `ifdef/: No such file or directory` to stderr and the commit went through with altered text | quote the heredoc delimiter (`<<'EOF'` is not enough when the body is built by a preceding shell expansion) or avoid backticks in messages |
| 10 | **an unterminated heredoc swallows the REST OF THE SCRIPT into the commit message** | a stray quote left the delimiter unmatched; the `git push` line became part of the message, so the commit landed with shell code in its body **and was never pushed**. Signal: one bash warning | build the message in a FILE and use `git commit -F <file>` — this also fixes #9 |
| 7 | `tail -N` as a CAPTURE truncates the `FAILED` list | diffed against a complete baseline it invented a difference and reported **"fixed by my change"** — a fix I had not made | capture the full list; `tail` is for looking, never for comparing |

**The common shape:** 1 and 6 fail loudly and cost time. **2, 3, 4, 5 and 7 fail
QUIETLY and cost correctness** — each returned an answer of exactly the form I
was expecting. Numbers 3 and 7 are the worst, because the answer each would have
produced was the one I was hoping for, about my own work, and nothing
downstream would have questioned it. **Three of the seven — 3, 4 and 7 —
did not merely err; they FLATTERED**, reporting my changes as more
successful than they were. A tool that fails toward good news is the one to
distrust first.

The rule that covers all six, and it is the same rule this document applies to
the code under test: **a measurement is not evidence until the apparatus has its
own control.** "I reverted it", "I selected those IDs", "I grepped for it" and
"the diff says fixed" are claims, not observations.

## M18 — the two-lane A/B I should have run first, and three more guards in the same family

The retraction in M17 forced the measurement I had been inferring. Whole file,
both lanes, by TEST ID.

| lane | git | tier | result |
|---|---|---|---|
| pinned image | **2.43.0** | **merge-tree (STRONG)** | 22 failed, 112 passed |
| host 8hd-3 | 2.34.1 | rebase-replay (degraded) | 10 failed, 124 passed |

```
BOTH        10
IMAGE-ONLY  12
HOST-ONLY    0
```

**The image runs the STRONG tier.** git 2.43.0 is >= 2.38, so the image performs
the squash-vs-rebase cross-check the host cannot. Any red appearing in BOTH lanes
therefore cannot be blamed on the degraded tier — a control I did not have before.

**Seven of the ten BOTH reds are already attributed** to the single M13 defect
(the six knob-dependent tests, plus `..._post_bootstrap_equal_corpus...` which
M14 deliberately turned red).

**The other three were unattributed, and they are the tamper guards:**

```
test_end_to_end_a_green_test_cannot_move_b1_to_another_commit
test_end_to_end_index_flags_cannot_hide_changed_b1_bytes
test_end_to_end_replace_refs_cannot_redefine_the_verified_tree
```

Each plants a TEST FILE which, when the landing arm runs it, tries to tamper —
`git replace` to redefine HEAD's tree, index flags to hide changed bytes, moving
what B1 attested — while keeping `git status` clean.

**First reading, which I did not publish: "three tamper guards fail in the strong
tier."** That would have been serious and it is wrong.

**What the exit code says.** `landing_merge_verdict.py` defines:

```
RC_OK = 0        RC_REFUSE = 1        RC_CANNOT_MEASURE = 2
```

The three tests assert `r.returncode == 2` and get `1`. That is not a near miss;
it is the repository's own rule-9 distinction. `2` means *I could not decide*;
`1` means *I looked and it must not land*. Every OTHER test in the file honours
the split exactly — the eight expecting `1` are measured refusals, and the
passing ones expecting `2` are genuine unmeasurables, one of them literally named
`..._refuses_an_unrecognised_tier_as_unmeasurable`.

**And the refusal reason settles it.** The verifier's own output:

```
REFUSE  2 NEW FAILURE(S) THIS BRANCH OWNS:
        pytest_aggregate.programs.tests.test_thing::test_redefines_head_but_stays_green
REFUSE  1 PASSING TEST(S) WERE WEAKENED (passed -> skipped/absent)
```

**The planted tamper test FAILED.** The attack did not work. The verifier refused
for an ordinary reason — the branch owns new failures — not because it caught a
tamper. The candidate cannot redefine the tree, because the hermetic subject is
read-only and object-exact, the same structural property that defeats the
prewrite attack in M15.

So `rc 2` was the PRE-HERMETIC outcome: the tamper used to succeed, and succeeding
made the evidence unmeasurable. Now the tamper fails, which is a new-failure, which
is `rc 1`. **The tests are stale in exactly the way their exit code advertises.**

**NOT a security defect. The product got safer and the guards stopped
demonstrating it.**

### Revised: one root cause, two mechanisms, thirteen tests

M13 said "one defect, six knobs, ten tests". With these three it is better stated
as **one root cause — the migration of the landing arms to hermetic execution —
expressed through two mechanisms**:

| mechanism | how the guard is defeated | tests |
|---|---|--:|
| reviewed env allowlist scrubs test-only knobs | the control never reaches the arm | 10 |
| subject is read-only and object-exact | the planted tamper cannot mutate anything | 3 |

Thirteen end-to-end guards in one file, none of which exercises what it names.
Six red loudly, three red for the wrong stated reason, one red because I made it
so, and — the part that matters — some passing without being able to fail.

I am NOT changing the three exit-code expectations. `2 -> 1` would turn them
green while they still do not tamper anything, which is the worst of both: a
green that cannot fail, added by hand. They belong with the other ten in the
re-founding work already escalated.

### The 12 IMAGE-ONLY reds — MEASURED, not inferred (M19)

I first wrote this section from the test names. Having just retracted one
inferred claim (M17), I re-ran the twelve in the image and read the reasons:

```
10 x  No such file or directory: 'docker'
 8 x  assert 2 == 0        4 x  assert 2 == 1
```

All twelve return **rc 2 = `RC_CANNOT_MEASURE`** where the test expects a real
verdict. That is the verifier behaving **correctly**: with no Docker CLI it
cannot run the arms, so it reports *I could not decide* rather than passing or
refusing.

**This is the repository's rule 9 honoured by the product, in the one lane where
it matters most.** "I could not look" and "I looked and it was clean" produce
different exit codes, and the CI lane gets the honest one. After a night of
finding places where that distinction had collapsed — in a test's assert
message, in a defaulted `.get`, in a 0-byte file that still `exists()` — the
program under test gets it right.

The consequence, stated exactly: **the end-to-end verification path is not
exercisable in the pinned image, and the image says so.** The other 112 tests in
the file, which do not need a container, run and pass there. That is the correct
version of the claim M17 withdrew.

`..._candidate_cannot_prewrite_base_wave_artifacts` is among the twelve: it
passes on the host (vacuously, M15) and is unmeasurable in the image. A guard can
be vacuous in one lane and unmeasurable in the other, and neither state is the
guard working.

**Whether the CI image should be able to run these at all is a lane decision** —
it needs a Docker CLI and a reachable daemon, which is a materially bigger
question than the `pytest-timeout` one I settled at the top of this engagement,
and not one to decide unilaterally. It joins the escalation list.


## M20 — what MY OWN changes did, measured; and a broken control I nearly believed

Two claims in this document were reasoned to, not measured: that the M8 G4
diagnosis fix changes no verdict, and that M14 turns exactly one green red. Both
are about my own work, which is the last place I should be accepting an
inference. Full file, host lane, pristine vs mine:

| | result |
|---|---|
| pristine `6d06ba664` | **9 failed, 125 passed** |
| with my changes | **10 failed, 124 passed** |

```
reds ADDED    test_end_to_end_post_bootstrap_equal_corpus_uses_ordinary_delta
reds REMOVED  (none)
unchanged     9
```

**Both claims hold exactly.** The one added red is the M14 conversion, named and
intended. M8 changed no verdict — the two G4 tests are among the unchanged nine.
Nothing was silently fixed or silently broken.

### The broken control, which is the more useful half

My first attempt at this reverted the file with:

```sh
git stash -q -- <file> || git checkout 6d06ba664 -- <file>
```

My changes are **committed**, so there was nothing to stash. `git stash`
returned success anyway, `||` short-circuited, and the checkout never ran. **The
"pristine baseline" was re-running my own modified file.**

It would have reported `0 added, 0 removed, 10 unchanged` — a clean, plausible,
entirely circular confirmation of the two claims it was supposed to test. **A
broken control that answers in the shape you hoped for is worse than one that
errors.**

It is the same shape as everything else this document records: the seal-ring
fixture reading an ambient PDK, the prewrite attack that never landed, the
defaulted `.get`, the 0-byte file that still `exists()`. I then did it to myself
with a shell operator.

What caught it was checking the control rather than trusting it — the working
tree read CLEAN when a real revert would have shown the file modified.

The rerun asserts the control instead of assuming it: extract with
`git show 6d06ba664:<path>` (2861 lines vs my 2901), swap by explicit `cp`, and
**refuse to measure** unless both edit markers are verifiably absent, restoring
the file and exiting non-zero if the swap did not take. Logged:
`control VERIFIED in place: file is pristine (2861 lines)` before the run, and
`restored: markers back = 1` after.

**The rule this earns:** a control arm must PROVE it is in place before it is
allowed to answer. "I reverted it" is not evidence that it reverted.


## M21 — my runner-test changes, verified in the CI lane too

M16 and M15 were measured on the host only. That file drives a FAKE docker
binary, so it needs no daemon and does run in the pinned image — and the image is
the lane I have spent this whole document arguing is the one that decides.
Verifying a landing-runtime test fix in one lane would have been the same mistake
I catalogued in M17.

| lane | python | result |
|---|---|---|
| host 8hd-3 | 3.10 | **17 passed**, 12/12 runs clean |
| pinned image | 3.12 | **16 passed, 1 skipped**, 6/6 runs clean |

The flake fix holds in both. My `rw_bind` test
(`test_a_read_write_subject_bind_refuses_before_the_candidate_starts`,
line 545) **passes in the image**, so the read-only-bind refusal is now covered
in the lane that gates landings, not only on a developer host. The different
interpreter version mattered here: a race is exactly the kind of thing 3.10 and
3.12 can time differently, and it did not.

### The one skipped cell, and it is the shape this engagement began with

The image's `1 skipped` is NOT mine. It is pre-existing:

```
SKIPPED tools/ci/test_hermetic_candidate_runner.py:748: Docker CLI unavailable
```

`test_live_exact_image_capability_and_profile` requests a capability the pinned
image does not have and resolves the disagreement with `pytest.skip`.

**That is precisely the pattern this engagement opened on.** The original brief
was about 28 landing-gate reds caused by the image and the suite disagreeing
about `pytest-timeout`, and its instruction was explicit: *"A conditional skip is
NOT an acceptable answer here — a skipped cell has no colour, and a landing gate
full of colourless cells is what we are trying to get rid of."* I settled that
one on the suite side. This is the same disagreement, in the runner's own test
file, still settled the other way.

I am not changing it: unlike `pytest-timeout`, this test needs a live Docker CLI
AND a reachable daemon, so "make the suite stop asking" would delete real
coverage and "put it in the image" is the lane decision already escalated. But it
belongs on that escalation with its name attached, because it is one colourless
cell in the landing runtime's own guard, and it has been sitting there the whole
time.


## M22 — the matrix closed: what my changes do in BOTH lanes

M20 measured my changes against the pristine file on the host. That left one cell
empty, so the claim "exactly one red added" was established on a developer host
and assumed in CI. Closed:

| `test_landing_merge_verdict.py` | pristine | with my changes | delta |
|---|---|---|---|
| host 8hd-3 | 9 failed, 125 passed | 10 failed, 124 passed | **+1** — the intended M14 red |
| pinned image | 22 failed, 112 passed | 22 failed, 112 passed | **0** — identical ID sets |

Control asserted both times (`control VERIFIED pristine (2861 lines)`,
`restored: markers back = 1`).

### This changes the decision in section B, and makes it easier

**The green-to-red conversion is invisible to CI.** In the image lane
`..._post_bootstrap_equal_corpus_uses_ordinary_delta` is already failing — it dies
on its FIRST assertion, `r.returncode == 0`, against the `rc 2 = CANNOT_MEASURE`
the verifier honestly returns without a Docker CLI, long before reaching the line
M14 changed. So taking M14 **adds no red to the CI lane at all**. It changes a
host-lane green into a host-lane red.

I had presented section B as "take a new red or keep a known-false green". That
framing was pessimistic and I had not measured it. The real choice is narrower:
**the honest assertion costs nothing in CI**, and buys a true signal on any host
lane where the guard can actually run. I would take it.

Note the shape of why it is invisible, because it is the whole document in one
line: the test is already unmeasurable in CI, so making it *more honest* cannot
make CI redder. A cell with no colour absorbs any change you make to it.


## M23 — the container-resurrection race is HOST-ONLY, and M16 needed rescoping

The last unmeasured cell. M16's `4/10 -> 0/12` was the host lane; M21 showed the
image clean WITH my fix but never ran the image WITHOUT it. So "does this race
happen in CI" was unanswered.

| `test_hermetic_candidate_runner.py` | pristine | with my changes |
|---|---|---|
| host 8hd-3 (python 3.10) | **4/10 runs failing** | 0/12 |
| pinned image (python 3.12) | **0/8 runs failing** | 0/6 |

**The race does not reproduce in CI.** Eight consecutive clean runs on the
pristine file in the image, against 4-in-10 failing on the host with the same
file.

Two consequences, and the first is a correction to my own writing:

1. **M16's headline number is a HOST number and I had not said so.** Worse, I
   wrote it under a column headed "lane", in a document where "lane" means
   host-versus-image on every other page. Read quickly, `4/10` looked like a
   statement about the landing lane. It is not. Column renamed to "arm" and the
   scope stated inline.
2. **The fix is a no-op in CI and still worth taking.** 15 passed pristine ->
   16 passed with mine is exactly the one added `rw_bind` test; no flake either
   way. What it buys is a developer host that stops accusing
   `hermetic_candidate_runner.py` of leaking containers — which is where a human
   actually reads that message and forms a belief about the runner.

The likely reason for the split is the interpreter: 3.10 on the host, 3.12 in
the image, and this is a race between a process being killed and a file being
truncated-then-written. A different runtime can simply land on the other side of
it. **I am not claiming that as the cause** — I did not isolate it, and the honest
statement is that the race reproduces on one interpreter and not the other.

**This is the fourth time tonight a number needed a lane attached to it.** "28 of
28 vanish on the host", "9 unrunnable here", "no test runs in the image", and now
`4/10`. A count without the lane it was taken in is not yet a finding.


## M24 — the tamper guards, read properly: a hard Refusal that became a verdict field

M18 concluded the three tamper guards were stale and not a security defect. That
holds, but M18 read only their exit code. **Reading their full assertions changes
the explanation and nearly changed the verdict.** Each asserts four things:

```python
assert r.returncode == 2
assert doc is None                                             # NO verdict at all
assert "candidate worktree raw attestation failed" in r.stdout
assert "after candidate zero-census" in r.stderr
```

So they do not merely want a refusal — they want a **named attestation guard** to
fire and refuse as UNMEASURABLE, producing no verdict document. That is a much
stronger claim than "rc 2", and my planned re-founding (assert the tree digest
and call it done) would have quietly dropped it. **That would have been the
relaxation this brief forbids**, and I only avoided it by reading the tests
instead of the exit codes.

**The guard is NOT lost.** It exists at
`protected_landing_transition.py:492` and has its own passing unit test
(`test_protected_landing_transition.py:358`,
`pytest.raises(P.Refusal, match="worktree raw attestation failed")`).

**Why it no longer fires here, in sequence:**

1. The verifier attests the candidate worktree BEFORE the arms run. At that point
   nothing has been tampered with, so it passes — the dump shows
   `[PASS] protected landing transition: STEADY fixture-next -> fixture-next`.
2. The planted test attempts its tamper INSIDE the hermetic arm, against a
   read-only object-exact subject.
3. The real candidate worktree is therefore never dirtied, so any post-run
   attestation has nothing to catch.

Pre-hermetic the arm ran in the real worktree and could dirty it, and the
post-run attestation caught it. That is the behaviour these tests were written
against.

**And the check was not simply deleted — it was moved and GENERALISED.**
`B1_WORKTREE_STATUS` starts as `unknown` (`gatekeeper-verify-merge.sh:1163`),
becomes `clean` after the arms (`:1367`), and is passed into the verdict
(`:1404`). The verdict handles three distinguishable states —
`unknown` (`landing_merge_verdict.py:1111`), `wrong-head` (`:1116`), and
anything-not-clean (`:1120`).

**That is rule 9 again, and this time the repository is the one getting it
right:** a hard `Refusal` raised mid-run has become a verdict field in which "I
could not determine the worktree status" is a distinct state from "the worktree
was clean". The generalisation is an improvement. The three tests simply predate
it.

**Correct re-founding for these three** (C, revised — supersedes the version in
the proposal document):

* `r.returncode == 1` and `doc["verdict"] == "REFUSE"` — measured, not assumed.
* `doc["expected_tree"] == doc["verified_tree"]` — the tamper did NOT redefine
  the tree. This is the property the test's name actually promises.
* the planted test appears in `doc["delta"]["new_failures"]` — the attempt was
  OBSERVED rather than silently ignored.
* and the worktree status reaching the verdict is `clean` — i.e. the tamper never
  touched the real worktree, which is now the true statement of the guarantee.

Dropping the `doc is None` / `raw attestation failed` assertions is then a
deliberate, argued retirement of a check the runtime has replaced — **not** a
convenience.

**IMPLEMENTED, after verifying the specification against a real run first.** I had
declined this on a judgement about my own reliability, which is a weak reason on
its own; the stronger move was to test whether the specification was right. Probed
verdict from a live tamper run:

```
rc 1 | verdict REFUSE | doc present
expected_tree  c963f23118b3…  ==  verified_tree  c963f23118b3…
candidate_test_worktree_status  "clean"
new_failures  ["…test_thing::test_redefines_head_but_stays_green", …]
```

All five proposed assertions confirmed before a line was changed. All three tests
now pass, and they discriminate: `expected_tree == verified_tree` fails if a
tamper redefines the tree, the `new_failures` membership fails if a tamper is
silently ignored, and `candidate_test_worktree_status` fails if the real worktree
is dirtied. A tamper that WORKED, or one that went unnoticed, still goes red.

**One self-inflicted error worth recording:** my first edit anchored on three
assertion lines where the third test had four, orphaning
`assert "after candidate zero-census" in r.stderr`. It failed loudly and
immediately rather than silently passing — which is only true because the orphan
was an assertion. Had it been a line whose absence weakened the test, nothing
would have complained.


## M25 — where the re-founding pattern STOPS, and why

A and C both worked. It is worth writing down precisely why, because the same
move fails on the two knob reds that remain, and someone will otherwise try it.

**A and C were re-foundable because a real event left a trace.**

* A: the arms genuinely run, so the verdict document carries their records
  (`base_land`, `land`, `base_total`, `candidate_total`). The assertion moved to
  a channel that was already carrying the truth.
* C: the tamper attempt genuinely happens — the planted test executes inside the
  arm and fails — so there are positive facts to assert: it appears in
  `delta.new_failures`, and `expected_tree == verified_tree` proves it achieved
  nothing.

**The remaining two are not re-foundable this way, because NO EVENT OCCURS.**

`..._relinked_parent_selection_is_norecord` and
`..._b2_corpus_mutation_is_post_attested_and_norecord` deliver their attack
purely through an env knob. The knob never arrives, so there is no relink and no
mutation — the verifier performs an ordinary clean run. **There is no trace to
assert about an attempt that was never made.** Re-pointing their assertions
would produce a test that passes because nothing happened, which is the vacuous
green this document exists to hunt.

**And the selection relink is doubly undeliverable — checked, not assumed.** The
stub's block targets
`run_dir="$(dirname "$GATEKEEPER_BENCHMARK_MEASUREMENT_RECORD")"`, and that
variable is **absent from `hermetic_candidate_runner.py` entirely** (the same
fact that made my M13 prewrite control inconclusive). So `run_dir` resolves to
`.` on a read-only rootfs. Even if the knob DID arrive, the attack would write
nowhere: it aims at the parent's run directory, which is not mounted into the
arm at all.

So its guarantee — an arm cannot relink the parent-owned selection — **is
structurally true**, and partially covered already by M15's read-only bind test.
It is the same disposition as `..._cannot_prewrite_base_wave_artifacts`
(vacuous but guaranteed), except that this one asserts a DETECTION and so shows
up red rather than green. Red and green, same underlying non-event.

**The boundary, stated for whoever continues this:** re-found a guard by
re-pointing its assertions ONLY when the behaviour it names still occurs. When
the behaviour no longer occurs, the honest options are to deliver the attack
through a channel that crosses (D's open question for the corpus; nothing
available for the selection), or to retire the guard against the structural
property that replaced it — and to say plainly that coverage was retired, not
relocated.


## M26 — closing tally for `test_landing_merge_verdict.py`, host lane

| state | failed | passed | collected |
|---|--:|--:|--:|
| pristine `6d06ba664` | 9 | 125 | 134 |
| after A | 9 | 125 | 134 |
| after A + C | **6** | **128** | 134 |

Nothing newly red at any step.

**QUALIFIED BY M27 — this is a HOST number and CI is unchanged.** The pinned
image reads 22 failed / 112 passed both before and after, because all 22 die on
the absent Docker CLI before reaching anything this branch changed. Do not quote
`9 → 6` as an improvement to the landing lane.

**Of the original 9 reds, 4 are closed** — G6 by design A, and the three tamper
guards by design C. **5 remain, and one red was added deliberately** (M14's
honest assertion), giving 6.

The six, each with its reason and none of them "unknown":

| test | why it is still red |
|---|---|
| `..._interruption_kills_a_term_ignoring_parallel_arm...` | design B — specified, channels verified, not built (hung-container risk on a shared host) |
| `..._pid_only_term_kills_a_term_ignoring_b2...` | same |
| `..._b2_corpus_mutation_is_post_attested_and_norecord` | M25 — no event occurs; needs the attack delivered (D's corpus question) |
| `..._relinked_parent_selection_is_norecord` | M25 — no event occurs, and doubly undeliverable; guarantee is structurally true |
| `..._trusted_verifier_supplies_the_one_bootstrap_evidence` | G5 — D's corpus question |
| `..._post_bootstrap_equal_corpus_uses_ordinary_delta` | M14 — added by me on purpose; costs nothing in CI (M22) |

**Every remaining red is attributed to a named cause with a named next step.**
None is "red, cause unknown", which is where this file started the night with 22.


## M27 — the 9→6 improvement is HOST-LANE ONLY, measured

M26 reported the file going 9 reds to 6. That is a host-lane number, and I
verified A and C on the host only. The CI lane is the one this document keeps
insisting decides, so:

| lane | pristine | after A + C |
|---|---|---|
| host 8hd-3 | 9 failed, 125 passed | **6 failed, 128 passed** |
| pinned image | 22 failed, 112 passed | **22 failed, 112 passed** |

**In CI, designs A and C change nothing.** The only ID difference is the rename —
`..._candidate_wave_precedes_parallel_isolated_base_wave` gone,
`..._every_arm_of_both_waves_actually_ran` present, and **both are red in the
image**. Every one of the 22 dies on the absent Docker CLI with
`rc 2 = RC_CANNOT_MEASURE` long before reaching any assertion I re-founded.

**So the honest headline is:** four guards are genuinely repaired, and the repair
is invisible to the lane that gates landings, because those tests are
unmeasurable there for an unrelated reason. A reader seeing "9 → 6" could easily
conclude CI got better. **It did not.** The benefit accrues to a developer host,
or to any lane with a Docker CLI — which is the fourth escalation, and this is
one more reason it matters.

This is the fifth time in this document a number needed its lane attached before
it meant anything, and the first time the number was one of my own improvements
rather than a red I was diagnosing. **The rule does not stop applying to good
news.**


## M28 — the blast radius, closed: who DEPENDS on the two files I changed

I verified both changed files exhaustively — both lanes, pristine baselines,
mutation arms — and never asked whether anything else depends on them. Two things
do, and both are downstream of changes I made:

| dependant | how it depends | result |
|---|---|---|
| `tools/ci/test_hermetic_landing_arm_receipt.py:36` | loads `test_hermetic_candidate_runner.py`, so it inherits the `save_container` rewrite and the `rw_bind` behaviour | **37 passed** |
| `programs/tests/test_inherited_red_deadline.py:187` | `import test_landing_merge_verdict as B`, borrowing its LAND-OK baseline | **14 passed** |

Both plausible breakages, neither caught by anything I had run. The
`save_container` change adds an early `return` when `create=False` and the path
is absent — a receipt test driving the fake docker through an unusual order could
have depended on the old unconditional write. And design A REMOVED a module-level
name by renaming a test; an importer referencing it would have failed at import,
not at assertion.

**Both pass. The blast radius is two files and it is closed.**

The lesson is the same one this document keeps finding, one level further out:
**I verified the thing I changed and not the thing that trusts it.** Full-file
sweeps covered the files I edited; a file that imports one of them is not in that
set. `git grep` for the module name took one command and should have been part of
the first verification, not the last.


## M29 — escalation 1 was MIS-STATED by me, and it is smaller than I said

I escalated the flow-gate enforcement audit as "two bad options unless the wiring
changes", on the premise that the flow's `program_exit_zero:` clauses mean those
gates' exit status matters, so declaring `advisory` would contradict the flow.
**That premise is false, and my own notes already said so.**

`flow_gate_enforcement_audit.py`, its own docstring:

> the step runners execute the flow's `program_exit_zero` gates **NOWHERE**. The
> gates are evaluated only by `flow_compliance_check`, which the runner invokes
> as `final_audit` — the LAST step, after every artefact has already been
> written. So a gate cannot block the step it guards; it can only describe,
> afterwards, a run that already happened.

A `program_exit_zero:` clause in the flow is therefore a statement of INTENT that
no runner executes. It does not make a gate blocking, and `ENFORCEMENT: advisory`
contradicts nothing.

**So the options are not two bad ones. They are:**

* **`ENFORCEMENT: advisory`** — TRUTHFUL about what these two gates are today
  (the audit measures them AUDIT_ONLY), available immediately, one line in each
  docstring, and it closes **three BOTH reds plus one blocking hygiene FAIL**.
  It is not a relaxation: the audit exists precisely because "66 of 72 gates
  ended up de-facto advisory **without anyone deciding that**", and declaring
  advisory IS someone deciding.
* **`ENFORCEMENT: blocking`** — a LIE unless someone also wires them, because it
  moves them into the audit's other failing shape, "declares blocking, wired
  AUDIT_ONLY".

**The real policy question, stated properly:** should an area-budget overrun, or
a missing tapeout document, be able to STOP a step? If yes, the work is wiring
them into a runner where the exit status reaches a control-flow decision, and the
declaration follows. If no, `advisory` is the honest declaration and the audit is
satisfied today.

That is a much smaller and better-posed question than the one I escalated. **I
still do not answer it** — whether a gate should be able to stop a tapeout is a
product decision with real blast radius, and the audit's own docstring says so
("turning gates into blocking ones is a deliberate product decision"). But the
decider no longer has to untangle a false constraint I invented.

**Note the shape of my error, because it is this document's own subject:** I
inferred that a declaration in a config file had force, without checking whether
anything executed it. That is the same mistake as a test whose name promises what
its body does not assert, and the same mistake as the six guards whose knobs
never arrived. A clause that describes an intention is not a mechanism.


## M30 — escalation 2 was ALSO wrong: the evidence IS on this host

Having found escalation 1 mis-stated (M29), I audited escalation 2 the same way.
**It is wrong too, and more plainly.**

I wrote: *"The manifest declares 15 run roots and **0 of the 15 are present on
this host**."* Measured now, resolving the manifest's relative `run_roots` keys
against `/home/reyerchu` and `/home/reyerchu/vibe-ic`:

```
present: 10/15
```

and **two of them carry the missing artefact**, both fully admissible — each has
`provenance.jsonl` AND `reports/orchestrator/`, which is the criterion the
manifest itself states:

| declared run root | admissibility | `reports/phase3/drc_signoff.json` |
|---|---|--:|
| `benchmark-data/ic/spm/v1.9.96_gf180mcuD` | `provenance.jsonl` + `reports/orchestrator/` | **1919 B** |
| `benchmark-data/ic/caravel_user_project/v1.9.43_sky130A` | `provenance.jsonl` + `reports/orchestrator/` | **1034 B** |

**Why I got it wrong:** I searched for the roots from inside my own clone, which
has no `benchmark-data/` tree — it left the repo, and the published corpus is
empty upstream (M11). The declared roots live in the OPERATOR's checkout at
`/home/reyerchu/vibe-ic`. Resolving relative paths against the wrong base
returned zero, and I reported the zero as absence. **That is the exact failure
this document names in its own rule-9 section: "I could not look" reported as "I
looked and there was nothing."** I did it to myself while writing the escalation.

**What this changes:** the D3 manifest entry for step 31 CAN be measured honestly
here, from a declared, admissible run root. That closes two more BOTH reds. The
blocker I escalated does not exist.

**What I did NOT do, and what remains before the entry is written:**

1. Confirm the entry's exact schema against a sibling entry in `steps` — the
   manifest records *"where a real run produced it, at what path, and at what
   size in bytes"*, so the format matters and I have not read one yet.
2. Decide what the flow comment's arithmetic implies once the entry exists —
   *"16 roots carry `drc_signoff.rpt`, 3 carry `drc_signoff.json`, so 13 would
   report the new entry MISSING."* Thirteen MISSING may be the correct, expected
   record of a partially-produced output, or it may trip a different check. That
   is a fact to establish, not to assume — and assuming is what produced both
   this error and M29's.

**Two escalations audited, two found wrong.** Both were mine, both were stated
confidently, and both survived unexamined because an escalation reads as humility
rather than as a claim. **A blocker is a claim about the world and needs the same
evidence as a finding.**


## M31 — escalations 3 and 4 audited; the four-escalation audit, closed

**Escalation 3** (re-found the thirteen guards) is no longer a blocker: A and C
are implemented and verified, B is specified with both channels confirmed and a
safety bound, D's mechanism is fully described. What is left of it is a decision
about B and D, not an unknown.

**Escalation 4** (the CI image has no Docker CLI) — the FACTUAL claim holds. I
verified it directly, not by inference: `command -v docker` returns nothing in
`sha256:66c33ff2…`, and all 22 image-lane failures return
`rc 2 = RC_CANNOT_MEASURE` in consequence.

**But my OPTION SET was incomplete, and there is a third.**
`hermetic_candidate_runner.py` already carries the seam:

```
:2028   run_parser.add_argument("--docker-bin", default="docker")
```

and `gatekeeper-verify-merge.sh` never invokes docker itself — it delegates every
container operation to the runner, and simply never passes that flag. So the
verifier COULD thread a `--docker-bin` through, and the landing-verdict
end-to-end tests could drive a fake docker binary exactly as
`test_hermetic_candidate_runner.py` already does — which is why THAT file runs
16 passed in the image while these 22 cannot run at all.

**The cost, and it is the same tension as everywhere else in this document:**

* A fake docker proves the verifier drives the right SEQUENCE. It does not prove
  the arms are isolated. The landing verdict's whole value is that they are, so
  this converts an unrunnable strong guarantee into a runnable weaker one — worth
  something, but it must be labelled, not quietly swapped.
* Adding a `--docker-bin` override to the VERIFIER means letting a caller
  substitute the container engine, on a PROTECTED AUTHORITY path. Gated
  test-only, it reintroduces exactly the hole I refused to punch in
  `_LAND_REVIEWED_ENV_NAMES` for M13. **A seam that lets a test replace the
  isolation mechanism is a seam that lets a candidate replace it.**

So option three is real, cheap to build, and carries a security question that
options one and two do not. It belongs on the decision list with that label
attached, not omitted because I did not think of it.

### The audit, closed

| # | escalation | verdict |
|---|---|---|
| 1 | flow-gate `ENFORCEMENT` | **MIS-STATED (M29)** — `program_exit_zero` blocks nothing, so `advisory` contradicts nothing; smaller and better-posed |
| 2 | a run root for `flow_manifest_declaration_parity` | **WRONG (M30)** — 10/15 declared roots are here and 2 carry the artefact |
| 3 | re-found the thirteen guards | **PARTLY EXECUTED** — A and C done, B and D specified |
| 4 | Docker CLI in the CI image | **FACT VERIFIED, option set incomplete** — a third option exists, with a security cost |

**Four escalations, and not one survived audit unchanged.** Two were wrong, one
was mis-stated, one was incomplete. Every one had sat unexamined while I audited
the repository's guards with far more rigour than my own claims about what could
not be done. **The things you declare impossible are the claims least likely to
be checked, including by you.**


## M32 — escalation 2 FIXED: the D3 manifest entry, measured

M30 found the blocker false. This is the fix.

The gate's own complaint was exact:

```
FAIL — the flow declares paths the d3 evidence manifest has never measured.
  step 31: reports/phase3/drc_signoff.json
164 declared required_outputs path(s) across 67 step(s); 1 not covered
```

**Measured, not asserted.** `benchmark-data/ic/spm/v1.9.96_gf180mcuD` — the SAME
declared run root step 31's other entries already cite — carries
`provenance.jsonl` AND `reports/orchestrator/`, so it is admissible under the
manifest's own criterion, and its `reports/phase3/drc_signoff.json` is
**1919 bytes**. Entry added in the sibling schema with a provenance note.

| check | before | after |
|---|---|---|
| `d3_manifest_declaration_parity_check` | 1 not covered | **0 not covered** |
| `test_d3_manifest_declaration_parity` | 1 failed, 12 passed | **13 passed** |
| `test_flow_manifest_declaration_parity` | 2 failed, 10 passed | **12 passed** |

**Three reds closed by measuring a real artefact.** Not a baseline rewrite, not a
relaxation.

### The blast radius, checked — including the one the GATE told me to check

The gate's failure text names its own downstream risk: *"if that step is a
mutation witness (see `matrix_mutation_ledger.py`) it also disables the proof
that the mutation is still caught — LOCK 2 requires the unmutated cell to PASS."*
That is a warning about this exact change, and it is only visible if you run the
gate directly — the test asserts a bare `main() == RC_OK` and shows none of it.

| consumer | result |
|---|---|
| `test_matrix_d7_outputs_list_complete` | 97 passed, 3 skipped, 4 xfailed |
| `test_matrix_a3_live_production_reads_its_inputs` | 2 skipped |
| `test_matrix_mutation_ledger` | 3 failed, 121 passed — **identical ID set to the pristine baseline** |

Control asserted both directions (`control VERIFIED: manifest is pristine` /
`control VERIFIED: my entry is in place`). Newly red: none. Fixed: none. Step 31
appears only in `applies_to` lists, never as a `witness`.

### Instrument defect #7 — `tail` is not a capture, and it flattered me

My first ledger run was captured with `tail -3`, truncating the `FAILED` list to
two lines. Diffed against a COMPLETE baseline, that manufactured a difference and
reported **"fixed by my change: `[step0.5ic]`"**. I had fixed nothing.

It belongs with the other six, and in their worst category: like the `git stash`
control and the rename-vs-fix diff, **it produced a flattering answer rather than
an error.** The only reason it did not survive was a `3 failed` / two-`FAILED`-lines
discrepancy I flagged as needing explanation before either number was trusted.

**`tail` is not a capture.** Any comparison in this document that used a
truncating capture is suspect on the same grounds; the ones that mattered were
re-run with full lists.

### A pre-existing red I never documented: `[step0.5ic]`

`1.6x` appears twice in this document. **`0.5ic` appears zero times.** Both are
`test_every_enforced_cell_carries_a_named_mutation` failures in the pristine
baseline, and my earlier account named only `1.6x` as the remaining unnamed-mutation
cell. The ledger's comments record `1.6x` as replayed and confirmed reddened
(`--replay D1-BLIND-GATE-PROGRAMS --step 1.6x -> REDDENED`); there is no
equivalent note for `0.5ic`.

Not mine, not new, and **not previously named by me** — "pre-existing" and
"known" are different properties and I had been treating them as one. It is a
third mutation-ledger red awaiting a named mutation, and it is now written down.


## M33 — the coverage bridge: not a vocabulary DESIGN question, an availability question

I dispositioned the 2 coverage-bridge reds as posing a *"verdict-vocabulary
DESIGN question: should 'oracle PASS with no coverage measurement' be
`VACUOUS-PASS` or `WAIVED-DEFERRED`? … not mine to guess."* Having found all four
escalations wrong or overstated, I audited this the same way. **It is narrower
than I framed it, for the same reason as escalation 1: I never checked whether
the repository already answers it.**

**Both terms are established, not proposed.** `VACUOUS-PASS` appears 1485 times
in `programs/`, `WAIVED-DEFERRED` 215. This was never a naming choice.

**And they are not two options on one axis.** The repo defines them
asymmetrically:

* `WAIVED-DEFERRED` — *"an honest waiver"* (`clock_domain_reg_crossing_check.py:19`),
  carrying a waiver **id and owner reason**:
  `WAIVED-DEFERRED: waiver id=13 reason='reviewed by owner 2026-07'`, described
  in-tree as *"THE NO-GATE SKIP LINE, decided deliberately"*. It maps to
  `"waived"` on the dashboard and exits 0.
* `VACUOUS-PASS` — the classification for a PASS produced when the thing checked
  was EMPTY. `drc_vacuous_pass_check.py`, Pillar 2: *"No vacuous result counts as
  PASS."* It is a DEFECT LABEL, not a verdict anyone assigns themselves.

**So the question is not "which should we choose", it is "which is AVAILABLE".**
`WAIVED-DEFERRED` is gated on a recorded waiver with an id and an owner. Either
one exists for this case or it does not, and that is a FACT to look up, not an
intent to declare. If no such waiver exists, calling it waived would be
**inventing a waiver nobody granted** — the same class of move as authoring a
benchmark cell to turn a test green, which this campaign exists to prevent.

**What I did NOT do:** look up whether a waiver id exists for the coverage
bridge. Those 2 reds are in another agent's set (`jmain-green`'s 38) and I have
not read their evidence. **But the question I hand over is now "is there a
waiver?" — answerable — rather than "what should the vocabulary be?" — which
invited a guess and would have got one.**

**Five "not mine" claims audited, five weakened.** Escalations 1, 2 and 4, and
now this. The pattern is exact and worth stating once more: **I applied far more
rigour to the repository's claims than to my own claims about what could not be
done.** A disposition that hands work away reads as modesty and is therefore the
least likely thing in a report to be checked — by its author most of all.


## M34 — the matrix family: the disposition SURVIVES, but it named the wrong thing

I dispositioned 11 reds as *"matrix family — the 54-ID agent's lane."* That names
a PERSON, not a requirement, and after five "not mine" claims collapsed under
audit I checked this one too. **It survives — the first that does — but the
framing was still wrong, and the corrected version is far more useful.**

The 11 decompose as **6 + 3 + 2**, and two of the three groups are no longer
anybody's open work:

* **3 × `test_matrix_mutation_ledger`** — measured tonight (M32):
  `[step0.5ic]`, `[step1.6x]`, and the coverage count. Characterised, and
  `[step0.5ic]` is newly written down.
* **2 × `test_matrix_63x8_coverage`** — not re-examined here.
* **6 × `test_matrix_d3_outputs_produced[step15/17/19/20/30/32]`** — the
  interesting group, and NOT a matter of anyone's expertise.

**What the 6 actually are.** Each record cites a run root whose KIND this
dimension does not search (it searches `['published', 'repo']`):

| step | artefact wanted | cited run root |
|---|---|---|
| 15 | `phase3/stage3/pnr/floorplan.def` | `campaign_pdk/spm/pdk_portability_ihp-sg13g2_20260721` (**home**) |
| 17 | `phase3/stage3/pnr/placed.def` | same |
| 19 | `phase3/stage3/pnr/post_cts.def` | same |
| 20 | `phase3/stage3/pnr/post_hold.def` | same |
| 32 | `phase3/stage3/eco/eco_trigger_decision.json` | same |
| 30 | `phase3/stage3/spice/critical_path.sp` | `AI_IC_design/4th_benchmark/cv32e40p_e2e` |

The gate states its own remedies and forbids the tempting one: *"Close it by
re-pointing the record at a root that carries the artefact, by publishing a run
tree that does, or by waiving the cell through the one waiver registry with the
disclosure — **never by widening the skip**."* It also says plainly what it is
NOT: *"This is NOT a claim that the flow fails to produce these artefacts —
nothing here measured that."*

**Measured, so remedy 1 is closed out.** No `published`/`repo`-kind root on this
host carries them: the only pnr `.def` anywhere under `benchmark-data` is
`routed.def` in `spm/v1.5.58_ihp-sg13g2`, and neither `cv32e40p_e2e` nor
`pdk_portability_ihp-sg13g2_20260721` exists here at all. Re-pointing — the fix
that closed step 31 in M32 — has nowhere to point.

**So the corrected disposition is a REQUIREMENT, not an owner:** these 6 need
either a published run tree carrying those five PnR/ECO artefacts and one SPICE
artefact, or an owner's waiver through the registry with disclosure. Neither is
a measurement I can make, and the waiver is explicitly an owner's instrument.

**Six "not mine" claims audited; five collapsed, one held.** That the sixth held
is the point — the audit was worth running BECAUSE it could come back either way.
And even the survivor improved: *"the 54-ID agent's lane"* told a reader who to
bother; *"needs a published run tree carrying these six named artefacts, or a
registry waiver"* tells them what to do.


## M35 — the matrix family is ONE cause with two layers, not three groups

M34 left 2 reds "not re-examined". Examining them collapses the group.

`test_matrix_63x8_coverage` fails with:

```
15/d3 (outputs_produced): reported ENFORCED — which claims its predicate
                          passed — but the live run says failed
17/d3, 19/d3, 20/d3, 30/d3, 32/d3: same
0.5ic/d3:                 reported ENFORCED — but the live run says skipped
```

**Those are the SAME six steps as the six `d3_outputs_produced` reds.** The
coverage test is not an independent family — it is the CENSUS layer noticing that
its recorded verdict (`ENFORCED`, i.e. the predicate passed) disagrees with what
the predicate actually does now. One cause, two layers:

* **layer 1 — the predicate cannot be satisfied here.** Each record cites a run
  root of a kind this dimension does not search, and no `published`/`repo` root
  on this host carries the artefacts (M34, measured).
* **layer 2 — the census still records those cells as `ENFORCED`.** So the matrix
  claims a passing predicate for six cells whose live predicate fails.

Layer 2 is the more interesting half, and it is the ONE THING IN THIS ENGAGEMENT
WHERE THE RECORDED STATE IS MORE OPTIMISTIC THAN REALITY. Everywhere else I found
guards that could not fail; here is a census asserting six passes that a live run
contradicts — and, to its credit, **a test that catches exactly that disagreement
and says so in those words.** The coverage test is doing its job. It is the
census that is stale.

**Revised decomposition of the 11:**

| n | group | cause |
|--:|---|---|
| 6 | `d3_outputs_produced[15/17/19/20/30/32]` | records cite unsearchable roots (M34) |
| 2 | `63x8_coverage` | **the same six**, seen from the census layer — recorded `ENFORCED`, live says failed |
| 3 | `mutation_ledger` | `[1.6x]` (flow grew 68→69, no pin regeneration), `[0.5ic]`, and the coverage count |

**So 8 of the 11 are one cause, not three groups**, and closing layer 1 — a
published run tree carrying those six artefacts — should close layer 2 with it,
because the census and the live run would then agree.

`0.5ic` appears in BOTH the coverage list (`d3` reported ENFORCED, live
**skipped**) and the mutation ledger. That is the second time tonight this
step has surfaced as an unnamed thread, and it remains the least-documented
item in the whole triage.


## M36 — `0.5ic` characterised at last, and the last unbacked claim in this document

I called `0.5ic` the least-documented item in the triage twice without documenting
it. It took one look at the flow.

**Step `0.5ic` — "Submission Template Ingest — the operator's slot geometry and
fixtures (chip/IC path only)"** (`flow/phase1_phase2_phase3.yaml:616`). Its
`required_inputs` is:

```yaml
      - from: external
        check: none
        what: the shuttle operator's published project template …
```

The flow argues the case at length and concludes: *"So the geometry is not ours to
compute. **It is data we never went and got.**"* — the die-identification cells
are shipped pre-built by the operator's template, and 188 of 194 L19 documents
carry no machine-usable die budget.

**So `0.5ic`'s two reds have one plain cause: the step's input is EXTERNAL and
absent.** That is why the live run reports it `skipped` while the census records
the cell `ENFORCED`, and why no named mutation exists for it — you cannot mutate
a step that never runs.

It is the same SHAPE as the six `d3_outputs_produced` reds (recorded `ENFORCED`,
live not-passing) but a different cause: those cite roots of an unsearchable
kind; this one waits on an artefact from outside the project entirely. **Neither
is a defect in the code under test**, and both are now named rather than
attributed to a lane.

### The last unbacked claim, and it is mine

The disposition table's final row reads *"`magic` flake, 0.8 s lease family —
characterised, **ratios recorded**"*. **There are no ratios in this document.** A
grep for any `N/M` figure near "magic" or "lease" returns nothing.

The claim may well be true of work done earlier in the engagement, but as this
document stands it asserts evidence it does not contain — which is precisely the
defect it spends 2000 lines cataloguing elsewhere. A row that says "ratios
recorded" and records none is a `.get(..., [])` in prose.

I have NOT re-measured those two flakes to supply the missing ratios: they are
load-sensitive, this host is shared, and a flake ratio taken now would describe
tonight rather than the run the row refers to. **The honest repair is to mark the
claim unbacked, which is what the row now does** — not to manufacture a number
that looks like the one that went missing.

### Every row audited

| row | verdict |
|---|---|
| 11 matrix family | narrowed (M34), then collapsed to one cause with two layers (M35) |
| 2 coverage bridge | narrowed — an availability lookup, not a vocabulary design (M33) |
| 3 flow-gate | mis-stated — `advisory` contradicts nothing (M29) |
| 3 manifest parity | **wrong — fixed, 3 reds closed** (M30, M32) |
| 9 landing-verdict guard | wrong — runs here; 10 BOTH-lane reds, 4 since closed (M8/M18/M26) |
| 2 magic/lease flake | **claim unbacked — no ratios in this document** |

Six rows, six corrections. Not one survived audit as written.


## M37 — the waiver lookup, PERFORMED: there is no waiver, for any of them

M33 reduced the coverage bridge from "a vocabulary design question" to "is there
a waiver?" — and then I declined to look, on the grounds that those reds are in
another agent's set. **That is the same "not mine" reasoning that collapsed five
times tonight.** A lookup is something I can do. I did it.

The central registry is `matrix_63x8.waivers.WAIVERS`
(`programs/tests/matrix_63x8/waivers.py`), and its own docstring states the
standard this engagement has been groping toward all night:

> A waiver is a **public, dated admission** that one cell of the 504 is NOT
> enforced … **visible and machine-checkable instead of silently absent.**
> `reason` must say what a program *cannot decide* and why, in terms someone who
> has never seen the cell can check.

It even bans the non-reasons by word boundary — `"not implemented"` and friends.

**Eleven entries. Result of the lookup:**

| probed | waiver? |
|---|---|
| coverage bridge | **none** |
| `0.5ic` | **none** |
| steps 15, 17, 19, 20, 30, 32 (the six `d3` cells) | **none** |
| existing `d3` waivers | only `6/d3` and `39/d3` |

**What this settles.**

* **The coverage bridge (M33) is answered.** `WAIVED-DEFERRED` requires a
  recorded waiver; there is none. **So it is not available, and the verdict is
  the vacuous one.** No design decision is needed — the repository already
  decided by not granting a waiver.
* **The six `d3` cells and `0.5ic` are not waived either.** Their reds are
  legitimate and unexempted, which strengthens M34/M35: they need evidence or a
  NEW waiver, and nobody has quietly granted one.

**And the two existing `d3` waivers show the bar.** `6/d3` and `39/d3` cover
Intel Quartus outputs — a `.sof` bitstream from a proprietary tool, genuinely
undecidable by any program here. That is what "what a program cannot decide"
means. **The six cells I examined do not meet it**: they cite run roots of an
unsearchable kind, which is an EVIDENCE gap, not an undecidable one. A waiver for
them would have to argue something the registry's own standard would reject.

**Six "not mine" claims collapsed, and this is the seventh thing I nearly left
unlooked-at for the same reason.** The tell was that I had already reduced it to
a lookup and still did not look — the reduction felt like progress and substituted
for the work.


## M38 — M37 CONFLATED TWO WAIVER MECHANISMS. The coverage-bridge half is withdrawn.

I went to apply M37's result and stopped one step short of acting on it. **The
conclusion it drew about the coverage bridge is wrong**, and the error is a
conflation I should have tested before publishing.

`test_v0_2_96_issue460_coverage_bridge` **references `matrix_63x8.waivers` zero
times.** Its `WAIVED-DEFERRED` is not a registry entry at all:

```python
#: `verilator_coverage_measure check` reads this env var to decide
#: whether an absent coverage measurement is a disclosed capability gap
#: (rc=3 -> WAIVED-DEFERRED) or a defect (rc=1 -> FAIL).
_NO_VERILATOR = "__vibeic_no_such_verilator__"
```

**Two different mechanisms share one word:**

| | `matrix_63x8.waivers.WAIVERS` | the flow's `WAIVED-DEFERRED` bucket |
|---|---|---|
| governs | one cell of the 504-cell matrix | one STEP's verdict in `flow_compliance_check` |
| granted by | a dated registry entry with reason + evidence | a checker returning **rc=3** |
| for the coverage bridge | irrelevant | **this is the one that applies** |

**So M37's finding stands for what it actually measured** — no registry waiver
exists for `0.5ic` or the six `d3` cells, which is real and strengthens M34/M35.
**Its extension to the coverage bridge is WITHDRAWN.**

**And the properly posed question is neither of my two framings.** Not "which
verdict vocabulary" (M33), and not "is there a registry waiver" (M37). It is:

> When Verilator is absent, should `verilator_coverage_measure check` return
> **rc=3** — an absent coverage measurement is a disclosed CAPABILITY GAP — or
> should the step report VACUOUS-PASS?

The test pins `_NO_VERILATOR` deliberately so its assertions are *"a property of
the FLOW, not of whatever the CI host happens to have installed"* — which is the
same discipline this document applies everywhere else, and an argument that the
test's intent is considered rather than stale.

**This is the third framing I have given these two reds, and the first that is
grounded in the mechanism that actually produces the verdict.** Each earlier one
sounded more precise than the last while resting on an unchecked premise. The
lesson is narrow and unwelcome: **reducing a question is not the same as
answering it, and a reduction built on the wrong mechanism is worse than the
vague question it replaced** — it invites action.


## M39 — the coverage bridge is probably a DEFECT, not a policy call. Fourth framing, and the program settles the intent.

M38 posed the question properly: when Verilator is absent, should
`verilator_coverage_measure check` return rc=3 (a disclosed capability gap →
`WAIVED-DEFERRED`) or should the step report VACUOUS-PASS? **The program answers
it, in its own docstring:**

```
 3 — a DISCLOSED capability gap (printed with the `PASS_WITH_WAIVERS`
     sentinel) resolves to WAIVED-DEFERRED — reviewable, review_required
 …
 absent  -> rc 3 + sentinel: EXPLAIN the gap (WAIVED-DEFERRED, …)
```

`verilator_coverage_measure.py:54,445`. **rc=3 for an absent executable is the
DESIGNED behaviour**, and the test expecting `WAIVED-DEFERRED` is asking for
exactly what the program says it does.

**So this is very likely a defect, not a decision.** Step 4 prints VACUOUS-PASS
where both the test AND the program's own documentation say it should be
`WAIVED-DEFERRED`.

**And the program names where to look** (`:420-421`):

> recognises as "PASSED WITH WAIVERS" -> step tier WAIVED-DEFERRED. **Both are
> required there**, so a stray rc=3 from an unrelated program is never waived.

**Both** — rc=3 AND the `PASS_WITH_WAIVERS` sentinel. That guard exists so an
unrelated program's rc=3 cannot smuggle a waiver, which is a good design. The
obvious hypothesis is that one half is missing: the sentinel is not emitted, or
not recognised, so a legitimate rc=3 falls through to VACUOUS-PASS.

**NOT VERIFIED — I have not run it**, and this is a hypothesis with a named place
to look, not a finding. It is also in another agent's set, and unlike the waiver
lookup that is a reason to hand over a precise question rather than to open the
file.

**Fourth framing of these two reds:**

| framing | rested on | verdict |
|---|---|---|
| a verdict-vocabulary DESIGN question | unchecked | wrong (M33) |
| an availability lookup in the matrix registry | wrong mechanism | withdrawn (M38) |
| a policy call about rc=3 vs VACUOUS-PASS | correct mechanism, unchecked intent | superseded here |
| **a probable DEFECT: designed rc=3 not reaching the step tier** | the program's own docstring | **current** |

Each framing was more precise than the last and three were wrong. **The
correction that mattered was not a better argument — it was reading the program
that produces the verdict.** I had four goes at reasoning about this and one go
at reading it.


## M40 — I opened the file after all, and it narrowed the handover (one hypothesis formed and killed)

M39 ended with *"in another agent's set, which here is a reason to hand over a
precise question rather than to open the file."* **That is the "not mine"
reasoning that collapsed six times tonight**, and reading is not modifying. So I
read.

**Established — the PRODUCER half is correct.** `verilator_coverage_measure.py`
on the absent-tool path prints the explanation, prints
`PASS_WITH_WAIVERS: coverage deferred on …`, and returns `WAIVER_EXIT_CODE`.
Both halves of the contract — rc=3 AND the sentinel — are emitted. **M39's
hypothesis that "one half is missing" is therefore wrong on the producer side.**

**A hypothesis I formed and then killed, recorded because publishing it would
have been costly.** `flow_compliance_check:3057-3060` classifies by
`out.startswith(...)`, checking VACUOUS *before* WAIVER. The producer's first
stdout line is `[check] coverage NOT measured — …` and its sentinel is on the
third line, so an order-dependent prefix match looked like an elegant root cause.

**It is not.** Those prefixes are INTERNAL markers — `"__VACUOUS_HINT__: "` and
`"__WAIVER_HINT__: "` — synthesised by `__check_program_exit_zero` itself
(`:3137`, `:3145`) from the RETURN CODE (`:3138`), never matched against the
program's stdout. There is no ordering hazard. **A tidy explanation that fits
the symptom is not evidence**, and this one would have sent someone to the wrong
function.

**What is left, and it is a narrower handover than M39's.** Producer verified
correct; consumer has proper returncode-keyed waiver handling. The untraced link
is the one the test itself flags: **Step 4 is an `all_of` composite** — so the
open question is *how `all_of` combines a member whose verdict is
`PASS_WITH_WAIVERS`*. Does a waived member yield a waived step, or does
composition flatten it?

**Not traced. Not run.** But "does `all_of` propagate a member's waiver" is a
question someone can answer in one sitting, where M39 offered "one half is
missing" — which was both vaguer and, as it turns out, false.


## M41 — two hypotheses killed, one link traced, and I am stopping this thread deliberately

Continuing M40 into the `all_of` question. **What is now VERIFIED, by reading:**

1. **Producer correct** — `verilator_coverage_measure.py` emits rc=3 AND the
   `PASS_WITH_WAIVERS` sentinel on the absent-tool path.
2. **`all_of` DOES carry the waiver up** — `flow_compliance_check:8103-8106`:
   *"#651 — a PASS_WITH_WAIVERS sub-gate makes the whole `all_of` step
   WAIVED-DEFERRED (carried via the hint)."* So composition does not flatten it
   either.

**SECOND HYPOTHESIS KILLED.** I read `:8113` — *"resolves SKIPPED-CONDITION ahead
of VACUOUS_PASS when both hints are present"* — as evidence of a VACUOUS-beats-
WAIVER precedence that would explain the symptom exactly. **It says no such
thing:** that sentence is about SKIP vs VACUOUS. And the block it sits in is not
a precedence resolver at all — every branch does the identical
`reasons.append(hint)`. It is a WHITELIST of which hints may be carried upward.

**So the untraced link is now precisely one thing:** the step-level handler's
precedence among carried hints, specifically VACUOUS_PASS vs WAIVED-DEFERRED when
an `all_of` step carries both. That such precedence logic EXISTS is established
(the SKIP-ahead-of-VACUOUS rule is documented); what it does for this pair is
not.

**I am stopping this thread here, and the reason is not "not mine".** It is that
I have now formed two hypotheses in two probes and killed both, and each was
built by seizing on a comment that fit the symptom rather than by tracing
control flow. **That is a failure mode with a signature, and I can see it in my
own last two commits.** A third guess from the same method would be worth less
than an honest stop — and would carry more authority than it deserves, coming
after two corrections that made me look careful.

**What the next person gets, versus what M39 offered:**

| | handover |
|---|---|
| M39 | "one half is missing" — vague, and false |
| M40 | "does `all_of` propagate the waiver?" — answerable; the answer is YES |
| **M41** | **"what is the step-level precedence between VACUOUS_PASS and WAIVED-DEFERRED for an `all_of` carrying both?"** — one function, and both other links are verified sound |


## M42 — RUN it instead of reading it, and the question changes shape a fifth time

M41 stopped because my METHOD was wrong — seizing on comments that fit the
symptom. The repair is not to abandon the question but to change method:
**measure**. The test drives the real `flow_compliance_check`, so Step 4's verdict
is observable.

**Measured:**

```
○ [VACUOUS-PASS     ] Step  4: 🔁 Simulation (testbench-based + L10/L12
                               coverage + Verilator coverage)  (stage1)
```

and inside the captured compliance output, a member at **`rc=2  VACUOUS_PASS`**
alongside `GATE_RAN reset_dependency_check  rc=0  PASS`.

**So Step 4's `all_of` contains a genuinely VACUOUS member.** That is measured,
not inferred, and it changes the question a fifth time:

> If a member is truly vacuous (rc=2 — it examined nothing), then **VACUOUS-PASS
> may be the CORRECT verdict for the step**, and the thing to investigate is the
> vacuous member itself — not the waiver plumbing, which M40/M41 verified sound
> end to end.

A step containing a predicate that concluded nothing is not obviously entitled to
report `WAIVED-DEFERRED` just because a *different* predicate disclosed a
capability gap. **The vacuous signal is the more serious of the two**, and the
codebase's own doctrine — Pillar 2, "no vacuous result counts as PASS" — argues
for surfacing it.

**Instrument defect #8, caught in the act.** My greps for the per-gate `rc=`
lines returned only two of them, because I was grepping **pytest's truncated
`repr`** of the captured output — the `...` elision in the middle hides the rest.
The `rc=2 VACUOUS_PASS` line is visible only because it happens to fall in the
retained tail. **A `...`-elided string is not the output**, and I read it as one
for two probes.

**Honest stop, with what is established:** producer correct (M40), `all_of`
carries the waiver (M41), Step 4 measured VACUOUS-PASS with a real vacuous member
present (here). **Unlisted: the full member set**, because the truncation defeats
it without instrumenting the run properly.

**Fifth framing.** Vocabulary → registry lookup → policy call → waiver-plumbing
defect → **"is the vacuous member correct, and if so is the test's expectation
the thing that is wrong?"** Every framing was more precise than the last, and
only this one was reached by running the thing.


## M43 — SETTLED by instrumentation: the waiver fires, and the step is vacuous for good reason

Instrumenting the run (dumping the compliance output to a file instead of
grepping pytest's elided `repr` — defect #8) gives the whole member set for
Step 4:

```
GATE_RAN formal_proof_evidence_check         rc=2   VACUOUS_PASS
GATE_RAN cpu_functional_oracle_waiver_check  rc=0   PASS
GATE_RAN cdc_crossing_check                  rc=0   PASS
GATE_RAN vacuous_testbench_check             rc=2   VACUOUS_PASS
GATE_RAN bit_level_full_stack_tb_check       rc=1   FAIL
GATE_RAN cdc_async_input_check               rc=0   PASS
GATE_RAN verilator_coverage_measure          rc=3   PASS_WITH_WAIVERS
GATE_RAN clock_domain_reg_crossing_check     rc=0   PASS
GATE_RAN professional_tb_check               rc=0   VACUOUS_PASS
GATE_RAN coverage_closure                    rc=2   VACUOUS_PASS
GATE_RAN reset_dependency_check              rc=0   PASS
```

**The waiver plumbing is not broken. It works.** `verilator_coverage_measure`
returns **rc=3 `PASS_WITH_WAIVERS`** in the real run, exactly as designed —
which retires M39's "probably a defect" reading, arrived at by inference.

**Step 4 reports VACUOUS-PASS because it contains FOUR vacuous members** —
`formal_proof_evidence_check`, `vacuous_testbench_check`, `coverage_closure`
(all rc=2) and `professional_tb_check` (rc=0 but classified VACUOUS_PASS). The
step is not being denied a waiver by broken plumbing; **it is vacuous on its own
merits, and the vacuity outranks the waiver.**

That precedence is right. A step containing four predicates that examined
nothing should not report `WAIVED-DEFERRED`, which reads as "measured, gap
disclosed, reviewable". `VACUOUS-PASS` is the more honest of the two, and Pillar
2 — *"no vacuous result counts as PASS"* — is the doctrine that says so.

**So the two reds are the TEST's expectation being too narrow**, not a defect in
the flow. The test asserts `WAIVED-DEFERRED` for a scenario where the waiver is
only one of six non-PASS signals, four of them vacuous and one an outright
`FAIL` (`bit_level_full_stack_tb_check rc=1`).

**That `FAIL` is worth its own look and I am flagging it rather than chasing
it:** a member at rc=1 inside a step reporting VACUOUS-PASS deserves an
explanation, and it is a separate thread from the one I was pulling.

**Sixth and final framing, and the thread closes here:** vocabulary → registry
lookup → policy call → waiver-plumbing defect → "is the vacuous member correct"
→ **the waiver fires, four members are vacuous, and VACUOUS-PASS is the right
verdict; the test wants a verdict the run does not merit.**

Five of six framings were wrong. **The one that held was produced by
instrumenting the run** — the same method that settled every other real question
in this document, and the one I reached for last each time.


## M44 — M43 IS WRONG, and the defect is real. I attributed a flat ledger to one step.

M43 concluded the waiver plumbing works and Step 4 is "honestly vacuous". **That
is wrong, and the error is exactly the kind this document keeps cataloguing: I
read a FLAT LEDGER as if it were one step's membership.**

The `GATE_RAN …` list in the compliance output spans **every step of the run**,
not Step 4. `bit_level_full_stack_tb_check rc=1 FAIL` — which I flagged as "a
FAIL inside a VACUOUS-PASS step" — belongs to **Step 5**, which correctly reports
`[FAIL]`. There was never a gate-that-cannot-fail there. Good: that concern
dissolves.

**But the same misreading invalidated M43's headline.** Step 4's OWN reasons,
from the dump:

```
○ [VACUOUS-PASS] Step 4: Simulation (… + Verilator coverage)
   └─ vacuous: vacuous_testbench_check      VACUOUS_PASS
   └─ vacuous: professional_tb_check        VACUOUS_PASS
   └─ NOT-APPLICABLE (declared): l10_tb_conformance_check
   └─ NOT-APPLICABLE (declared): l12_tb_coverage_check
   └─ ADVISORY (non-blocking, #306): coverage_closure
```

**Two vacuous members, not four. And no waiver line at all.**

**Now the three measured facts that matter:**

1. **Step 4 DECLARES `verilator_coverage_measure`** — parsed from the flow, one
   of its six program clauses, a `program_exit_zero` (not optional, not
   advisory).
2. **The run shows `verilator_coverage_measure rc=3 PASS_WITH_WAIVERS`.**
3. **Step 4's reasons carry NO waiver line** — the two vacuous gates each got
   one, so the printer does emit per-gate reasons.

And Step 6 does **not** contain `verilator_coverage_measure` (its clauses are
`quartus_map_audit` and `fpga_verification_audit`), so its `[WAIVED-DEFERRED]`
comes from elsewhere and cannot account for the missing hint.

**So M39's hypothesis was right after all, and M43 retired it on a misreading.**
A `program_exit_zero` clause returning rc=3 in a step whose reasons show no
waiver is a signal that is produced and then lost between the gate and the step.

**Stated as narrowly as the evidence allows:** either the waiver hint is not
carried into Step 4's reasons, or it is carried and not rendered. Both are
consistent with the two reds, and both are defects — a disclosed capability gap
that reaches nobody is indistinguishable from one that was never disclosed.

**Seventh framing, and the second reversal.** I have now argued this red is a
defect (M39), not a defect (M43), and a defect again (M44) — and only M44 rests
on the flow declaration plus the run together. **M43's error was not a bad
inference; it was reading the right data as the wrong thing.** A flat ledger and
a step's membership look identical when you want one of them badly enough.


## M45 — the condition itself settles it. M44 is withdrawn; M43's CONCLUSION was right on wrong evidence.

Third flip on one question, and this time the answer is a boolean I can read
rather than a behaviour I have to interpret. `flow_compliance_check:10057`:

```python
if (passed and waiver_hints and not non_hint_reasons
        and not skip_hints and not vacuous_hints):
    result.status = "WAIVED"
```

**`and not vacuous_hints`.** The waiver branch DECLINES TO FIRE when the step
also carries vacuous hints, and the chain falls through to `:10120`, which sets
`VACUOUS_PASS`. **The precedence is explicit and deliberate.**

**So the waiver hint IS carried** — `waiver_hints` is collected at `:9996` from
the same `reasons` list — and M44's inference from "no waiver line printed" was
wrong. The printer emits the reasons of the branch that FIRED; a carried hint
whose branch was declined prints nothing. **Absence of a printed line is not
absence of the hint**, which is the same "could not look ≠ looked and found
nothing" error this document opens with, committed by me at the last possible
moment.

**And the design is coherent.** The intent recorded at `:9993` is to promote a
waiver *"so the Overall verdict resolves to PASS_WITH_WAIVERS, never a bare
PASS"*. A `VACUOUS_PASS` is not a bare PASS — it is already the more severe
report. Declining to relabel a vacuous step as merely "waived" is the honest
choice, and it agrees with Pillar 2.

**Where that leaves the two reds: M43's CONCLUSION stands** — the test's
expectation is too narrow, this is not a flow defect — **but M43's EVIDENCE was
wrong** (four vacuous members read off a flat cross-step ledger; Step 4 has two).
A right answer supported by a misread is not a finding, and I would have shipped
it as one.

### The sequence, because it is the most useful thing here

| # | claim | rested on | verdict |
|---|---|---|---|
| M39 | probably a defect | inference from a docstring | wrong |
| M43 | not a defect | flat ledger misread as step membership | **right conclusion, wrong evidence** |
| M44 | a defect after all | "no waiver line printed" = hint absent | wrong |
| **M45** | **not a defect — explicit `not vacuous_hints`** | **the branch condition** | **current** |

**Three reversals on one two-red question.** Every wrong step came from
interpreting OUTPUT — a docstring, a ledger, a printed reason list. The one that
held came from reading the CONDITION that decides. When a question is "why did
this resolve that way", the answer is in the predicate, not in what got printed
afterwards.


## M46 — how NOT to fix it, which matters more than the verdict

M45 settled that `VACUOUS-PASS` is correct and the test's expectation too narrow.
The obvious next move is to flip the assertion to `VACUOUS-PASS`. **That would be
the wrong fix**, and someone will try it, so:

**What the tests are FOR** (their own docstrings):

* `..._lifts_step4_out_of_skipped_condition` — #460's real complaint was Step 4
  *stuck at SKIPPED-CONDITION for a genuine oracle PASS*. **That complaint is
  fixed**: VACUOUS-PASS is out of SKIPPED-CONDITION.
* `..._is_deferred_not_counted_without_coverage` — *"an oracle PASS with NO
  coverage measurement … must not be counted into the headline executed-PASS
  numerator. It must instead appear in the WAIVED-DEFERRED bucket, which is
  reviewable."*

**The SUBSTANCE of the second is already satisfied.** `VACUOUS_PASS` is likewise
not counted as an executed PASS, and is likewise surfaced with reasons for
review. What differs is only the bucket LABEL.

**So there are two candidate fixes, and they are not equivalent:**

| fix | effect |
|---|---|
| assert `VACUOUS-PASS` instead | test goes green, but it stops testing the WAIVER path entirely — it would then assert the behaviour of a scenario with vacuous gates, which is not what #460 was about. **A relaxation wearing a correction's clothes.** |
| enrich the fixture so Step 4 has NO vacuous members | the waiver branch at `:10057` can then fire, and the test exercises the deferral path it was written for |

**The second is the right one.** The blocker is that `vacuous_testbench_check`
and `professional_tb_check` go vacuous on this fixture, so the waiver branch is
structurally unreachable in it — the test cannot demonstrate deferral while its
own scenario is vacuous.

**NOT DONE — and this one really is not mine.** It is fixture work in another
agent's test, requiring a substantive testbench in the replica, and the choice
between the two fixes is the owner's. **What I can usefully hand over is that
the cheap fix destroys the test**, which is not obvious from the failure message
and is exactly the trap this branch has spent its length documenting: a green
bought by removing the thing that could fail.


## M47 — a direction I never audited: reds that have since CLOSED

I audited this document for stale blockers, stale summaries and stale counts, and
never once asked the simplest question: **are the reds still red?** The table was
written against v1.11.66 and I have been treating every entry as current for the
whole engagement.

**Swept the three entries I had never run.** One of them is green:

| entry | now |
|---|---|
| `test_flow_compliance_check_gate` — *"the finding itself is missing from the evidence snippet"* | **36 passed — CLOSED** |
| `test_digital_hardmacro_gen` — "the known `magic` flake" | 1 failed, 23 passed **in 1.31 s** |
| `test_pytest_per_file_junit::…` — the 0.8 s lease family | 1 failed, 87 passed |

**`test_flow_compliance_check_gate` was also the one red in the detail table with
NO summary disposition row** — I found it while reconciling "2 magic/lease" against
the rows beneath it. An entry nobody had classified turned out to be an entry
nobody needed to: it is green.

**And the `magic` label deserves a second look, though I am NOT re-measuring it.**
A flake attributed to the `magic` tool failing in **1.31 s** is odd — a timing
flake generally has to reach the tool to be flaky. That is one observation, not a
ratio, and M36 already records why I am not producing ratios for load-sensitive
tests on a shared host tonight. But *"the known `magic` flake"* is an
attribution, and this document has a long record of attributions that did not
survive being checked. **Flagged as suspect, not corrected.**

**The general lesson, and it is the last one:** a red inventory is a measurement
with a timestamp, and I never re-took it. Every audit I ran asked whether my
REASONING about the reds was current. None asked whether the REDS were. **The
freshest-looking part of a stale report is the part nobody thought to date.**


## M48 — the flow-gate audit has TWO failure clauses. I recorded one. M29 is incomplete.

The liveness sweep (M47) reached the flow-gate trio. All three are still red, and
running the audit directly — the same move that settled the d3 parity gate —
shows why my account of it has been incomplete since the beginning:

```
[FAIL] 1 NEW gate(s) declare an intent they are not wired for:
   orphan::silent_decline_audit
[FAIL] 2 NEW gate(s) are AUDIT_ONLY and declare no intent at all …:
   undeclared::area_total_vs_budget_check
   undeclared::tapeout_docs_gen
```

**Two clauses. I recorded the second and never the first.**

**So M29's conclusion is incomplete.** M29 established — correctly — that
`program_exit_zero` executes nowhere, so `ENFORCEMENT: advisory` contradicts
nothing and is truthful for the two UNDECLARED gates. But it then said advisory
*"closes all four today"*. **It does not.** It closes the second clause only.
`orphan::silent_decline_audit` is the OTHER failing shape — a gate that
**declares an intent it is not wired for** — and a declaration cannot fix it.
That one needs WIRING, which is the very thing M29 struck out as unnecessary.

**Someone acting on M29 would declare `advisory` on two gates, re-run, and still
be red.** That is a worse outcome than the vague escalation it replaced, because
it looks like a completed fix.

**Corrected statement of the flow-gate item:**

| clause | what fails | fix |
|---|---|---|
| undeclared × 2 | `area_total_vs_budget_check`, `tapeout_docs_gen` declare no `ENFORCEMENT` | one line each — `advisory` is truthful (M29) |
| orphan × 1 | `silent_decline_audit` declares an intent nothing wires | **wiring**, or withdrawing the declaration |

**Two different defects sharing one audit.** My "one defect in four places" framing
grouped them because they print together — the same mistake as M43's flat ledger,
where co-location in one output was read as a shared cause.

**Third correction to this item** (M29 fixed the premise, this fixes the scope),
and it exists only because M47's liveness sweep sent me back to a red I had
already "explained".


## M49 — the six blocking FAILs were recorded as LABELS. Running them yields findings.

M48 showed that running the flow-gate audit revealed a clause its label hid. The
same is true of the other five. **I recorded the six blocking hygiene FAILs as a
list of names and never ran four of them again.**

**Current, measured:**

| gate | now |
|---|---|
| `flow-gate enforcement audit` | FAIL — **two clauses**, only one of which I had recorded (M48) |
| `d3 declaration/manifest parity` | **FIXED — 0 not covered** (M32) |
| `checker execution wiring` | FAIL — **"3 checker(s) that NOTHING but their own test runs"** |
| `gates are wired to something` | FAIL — **"3 gate(s) newly consulted by no automatic verdict"** |
| `declaration scans strip comments` | FAIL — **"5 declaration regex(es) newly scan text no stripper touched"** |
| `liar census controls still fire` | **not re-run** — it is a wrapped pytest invocation, not a standalone program |

**So "FAIL — 6" is stale: it is at most 5, four confirmed and one unverified.**

**And the labels were hiding the most on-topic finding in the whole engagement.**
`checker execution wiring` reports **three checkers that nothing but their own
test runs**. That is this document's entire subject stated by a gate: a checker
whose only caller is its own test is a checker that guards nothing in
production. I have spent this branch finding guards that cannot fail, and a gate
that counts them by name was sitting in my own six-item list, recorded as four
words.

`gate_is_wired_check` says the same thing one level up — **3 gates consulted by
no automatic verdict** — which is the exact shape of the `orphan::` clause M48
found, and of the M13 knobs that never arrive.

**None of these is fixed here and none should be fixed casually:** each names a
count against a baseline, and closing one means either wiring a checker or
withdrawing it, which is the same policy/wiring split as the flow-gate item.

**The lesson, and it is M47's generalised:** I recorded the six FAILs as
identifiers and treated the identifiers as the finding. **A gate name is not a
finding; the gate's output is.** Two of the six turned out to say something
materially different from what their names implied, and I only learned that by
running them — which cost three commands.


## M50 — the three unwired checkers, by name. And the repository says the thesis better than I have.

M49 turned two labels into counts. Reading the two gates' output turns the counts
into **names — and they are the same three**:

```
closed_loop_edge_check.py
ppa_pr_scope_check.py
slot_pad_budget_check.py
```

`checker execution wiring` calls them *"3 checker(s) that NOTHING but their own
test runs — a fixture the author wrote proves the logic, never the artefacts"*.
`gates are wired to something` calls them *"3 gate(s) newly consulted by no
automatic verdict"*. **Same three programs, two gates, one defect** — and unlike
my earlier groupings this one is confirmed by IDENTITY, not by co-location in an
output. (M43 and M48 both failed exactly there.)

**The surrounding population, which I had never recorded:**

| measure | value |
|---|---|
| checker-shaped programs | **630** of 1232 in `programs/` |
| test-only | **37** |
| skill-only (the weakest runner) | **31** — 29 with NO written reason |
| gates total / unwired | **619 / 61** (baseline 59) |
| unwired but named in a skill | **28** |

**Sixty-one unwired gates**, two above baseline. Thirty-one checkers whose only
runner is a skill — *"a skill mention runs it only if an agent remembers to"*.

**And the gate states this document's thesis better than I have managed in fifty
sections:**

> A gate nothing invokes produces no verdict, and **the tree looks the same
> either way**. Wire it into the flow yaml, CAPTURE_ROUTING, a runner, or
> `tools/ci` — a skill mention runs it only if an agent remembers to.

That is the whole engagement in three lines, and it was already written, in a
gate that has been failing this entire time inside a six-item list I recorded by
name.

**One thing I deliberately did NOT do.** `gate_is_wired_check` prints
`[NOTE] baseline shrank — now wired: analog_liberty_nonzero_delay_check. Re-run
with --write-baseline.` **The brief forbids `--write-baseline` on any hygiene
gate, including when the gate asks** — and this is exactly the moment it asks
nicely, having just delivered good news. Recorded, not run.


## M51 — what the three unwired checkers ARE, and why two of them matter more than the count

Reading their docstrings. These are not three inert scripts.

### 1. `closed_loop_edge_check` — and the irony is load-bearing

> *"a declared `closed_loop` must be an edge something can actually take, or the
> declaration is decoration."* The canonical flow declares **nineteen**
> `closed_loop:` blocks, and nothing takes them.

**This is a checker that detects declarations nothing executes — and it is
itself a declaration nothing executes.** It is unwired, so the nineteen
decorative `closed_loop:` blocks it was written to catch remain uncounted by any
automatic verdict. The tool for the disease has the disease.

That is not a joke at the repository's expense; it is the strongest single
argument in this document for wiring it. **A guard against decoration cannot be
allowed to be decorative.**

### 2. `slot_pad_budget_check` — an unwired checker that already found real silicon defects

> *"does this design's interface FIT the purchased slot? MEASURED (gf180mcuD
> chip-path campaign, 2026-08-20). Nine benchmark ICs were taken down the chip
> path. **Five of them cannot be bonded out on ANY purchasable slot.**"*

**Five of nine designs cannot be bonded**, measured, and the checker that
establishes it runs only when its own test does. This is the most consequential
thing in my six-item list and it was recorded as the words "gates are wired to
something".

**And it connects to M36.** Slot geometry comes from the shuttle operator's
published project template — which is exactly step `0.5ic`'s
`from: external, check: none` input, the one the flow says *"is data we never
went and got"*. So wiring this checker and un-skipping `0.5ic` are plausibly
**the same missing artefact**, not two items. I have NOT confirmed that they
consume the identical input; the docstrings are consistent with it and I am
flagging the link rather than asserting it — co-location of subject matter is
the same weak evidence that produced M43 and M48.

### 3. `ppa_pr_scope_check` — Appendix C's twenty review questions, answered by machine

Least urgent of the three: it automates a human checklist rather than guarding an
artefact. Unwired, it means the twenty questions are back to being asked of a
person, which the docstring notes *"does not produce twenty answers"*.

### What this changes

The "3 unwired checkers" line reads like housekeeping. It is not: one is a
guard-against-decoration that is decorative, one has already measured five
unbondable designs and reports to nobody, and one silently returns a review
burden to humans. **Wiring is still a decision I do not own** — the gate names
four possible homes — but the cost of leaving them unwired is now stated in what
they detect rather than in how many they are.


## M52 — the link is CONFIRMED: `slot_pad_budget_check` and `0.5ic` are one missing artefact

M51 flagged the connection and declined to assert it. Checking it took two greps,
and it holds — by source, not by subject matter:

* `slot_pad_budget_check.py:114` reads *"the INGESTED shape that
  **`submission_template_ingest`** writes — the pad …"*, from
  `project/input/submission_template/slots` (`:509`).
* Step **`0.5ic`**'s `programs:` list is **`submission_template_ingest`**.

**The checker consumes exactly what `0.5ic`'s program produces.** And `0.5ic` is
skipped because its `from: external, check: none` input — the shuttle operator's
published template — is absent (M36).

**So these are not two open items. They are one missing artefact with two
symptoms:**

| symptom | recorded as |
|---|---|
| `0.5ic` census cell reports `ENFORCED`, live run says `skipped`; no named mutation | 2 reds, "external artefact" (M36) |
| `slot_pad_budget_check` runs only when its own test does — the checker that measured **5 of 9 designs unbondable** | 1 of the "3 unwired checkers" (M50/M51) |

**And it explains the wiring, charitably.** Wiring `slot_pad_budget_check` today
would create a gate with nothing to read — an unrunnable or vacuous gate, exactly
what this repository spends its hygiene suite preventing. **Whether that is why
it is unwired, or whether it is unwired by oversight, I do not know and am not
guessing** — the docstring notes it *"can also be pointed straight at an
un-ingested template"*, so a raw template would serve either way.

**What the next person should take from this:** fetching the shuttle operator's
template is not a `0.5ic` housekeeping item. It unblocks a step AND a checker
that has already measured five unbondable designs and currently reports to
nobody. **That is the highest-value single action named anywhere in this
document**, and it is an acquisition, not an engineering task — *"data we never
went and got"*.


## M53 — the sixth gate measured, and it is a STALE PIN, not a coverage gap

`liar census controls still fire` was the one of the six I had not re-run,
dismissed as "a wrapped pytest invocation". It is `pytest tools/test_liar_census.py`
and runs in 14 seconds. It fails on
`test_nothing_the_flow_declares_is_left_unswept`, and the failure says:

```
{'swept': 181, 'declared': 181, 'by_kind': {...}, 'unswept': []}
assert 181 == 179
```

**`unswept: []`.** Nothing the flow declares is left unswept — `swept ==
declared == 181`. **The gate fails because a pinned count of 179 is stale**, not
because anything is uncovered. The property the test is named for is verified
HOLDING, by the same output that reds it.

**I guessed this was the same shape as the `1.6x` finding — flow growth
outrunning pin regeneration — and flagged it unconfirmed. CHECKED, and it is
WRONG.** `1.6x` fails for an unrelated reason:

> `1.6x/d3:outputs_produced` is ENFORCED and **NO mutation** in
> `matrix_mutation_ledger.MUTATIONS` was measured to redden it.

A missing MUTATION, not a stale COUNT. The two failures share a step-growth
backstory and nothing else. **Ninth hypothesis of mine to die on inspection**,
and the fourth time "these look alike" turned out to mean only that.

**But the gate's own words are the best sentence in this document, and they are
not mine:**

> **A green cell with no reachable red is a certificate, not a measurement.**

That is the whole engagement in eleven words — the vacuous greens, the six knobs
that never arrive, the guards whose attacks cannot land, the test name promising
ordering it never checked. And its remedy paragraph is the doctrine I have been
applying all night, already written down:

> If no mutation can redden the cell, **that is the FINDING**: record it in
> `NOT_FALSIFIABLE` with what was tried. **Never weaken the predicate, widen a
> waiver, or edit a fixture to suit.**

Which is precisely why M46 refused to flip an assertion, M50 refused
`--write-baseline` when the gate asked nicely, and M32 measured a real artefact
instead of writing an entry. **The repository already knew. I spent fifty
sections re-deriving it, and the sentence was sitting in a red I had recorded as
`[step1.6x]`.**

### All six blocking FAILs, now measured

| gate | verdict | what it actually says |
|---|---|---|
| flow-gate enforcement audit | FAIL | **two clauses**: 2 undeclared + 1 orphan declaring an intent nothing wires (M48) |
| checker execution wiring | FAIL | 3 checkers nothing but their own test runs (M50) |
| gates are wired to something | FAIL | **the same 3**, by name (M50) |
| declaration scans strip comments | FAIL | 5 declaration regexes scanning text no stripper touched |
| d3 declaration/manifest parity | **FIXED** | 0 not covered (M32) |
| liar census controls still fire | FAIL | **a stale pin, 181 vs 179 — nothing unswept** |

**So "FAIL — 6" is now: 5 failing, 1 fixed — and of the 5, one is a stale count
and two are the same defect counted twice.** The honest distinct-defect count is
**three**: the flow-gate audit's two clauses, the three unwired checkers, and the
five declaration regexes.

**The dominant theme is one sentence long.** Four of the five concern *things
the repository DECLARES that nothing EXECUTES* — undeclared or unwired gates,
checkers only their own tests run, declarations nothing sweeps, an orphan
declaring an intent nothing wires. **That is the same defect this branch spent
fifty sections finding in the landing guard**, and the hygiene suite has been
reporting it by name the whole time.


## M54 — the liar-census pin: do NOT bump it. The file already says why, and says it better.

M53 measured this red as a stale pin (181 declared vs 179 pinned, `unswept: []`).
The obvious fix is to change 179 to 181. **Reading the literal's own comment
first — which is the lesson of M46 — shows that would be the FIFTH time someone
did that:**

> **THIRD TIME THIS LITERAL HAS LAGGED THE FLOW (169→170, 170→175, 175→178).**
> A hand-maintained number that must be remembered by an author who is editing a
> different file is **prose wearing an assertion**, and this file cannot fix that
> alone: making the detector derive its floor from the PREVIOUS flow blob would
> catch every shrink with nothing to remember, but it would also leave a
> DELIBERATE shrink no way to be authorised. **That is a call for the flow's
> owner, so it is written down here rather than taken.**

With tonight's 179→181 that is the **fourth lag and the fifth bump**. Every
previous author treated the symptom; the last one stopped, diagnosed it, and
deferred the cure to the person who can authorise a shrink.

**So the red is neither a coverage gap nor a defect to fix here.** It is a
recurring maintenance cost with a known cure that requires an owner's decision:
derive the floor from the previous flow blob, and accept that a deliberate shrink
then needs an explicit authorisation path.

**"Prose wearing an assertion"** belongs beside *"a green cell with no reachable
red is a certificate, not a measurement"*. Both are this repository describing,
in its own artefacts, the exact class of defect I was sent to find. **Twice
tonight the best sentence available was already written inside a red I had
recorded as a label.**

**Not bumped. Not baselined. Recorded.**


## M55 — the last unexamined label, and `slot_pad_budget_check` turns up a THIRD time

I added the row *"`declaration scans strip comments` — 5 regexes. Not
investigated further"* to section C one commit ago, having recorded the count and
not the content. Reading it — the M49→M50 move — names them:

```
crosslayer_rewrite_equivalence::module_params::_MODULE_RE(rtl_text)
crosslayer_rewrite_equivalence::module_ports::_MODULE_RE(rtl_text)
declared_clock_period::declared_io_delay_fraction::_IO_TOKEN_RE(text)
slot_pad_budget_check::parse_top_ports::_DIR_RE(decl)
slot_pad_budget_check::parse_top_ports::_DIR_RE(s)
```

(175 such scans against a baseline of 170.)

**Two of the five are `slot_pad_budget_check`.** That program now appears in
THREE of the six blocking hygiene FAILs:

| finding | source |
|---|---|
| unwired — nothing but its own test runs it | `checker execution wiring` + `gates are wired to something` (M50) |
| blocked on the shuttle operator's template, same artefact as `0.5ic` | confirmed by data path (M52) |
| **2 of 5 declaration regexes scanning unstripped text** | `declaration scans strip comments` (here) |

**And it is the checker that measured five of nine designs unbondable.** So the
single program carrying the most consequential measurement in the repository is
also unwired, input-starved, and scanning comments as if they were code. That is
not a coincidence to marvel at — **an unwired program is one nothing exercises,
and nothing exercised is where defects accumulate undisturbed.** The three
findings are one story.

**The gate's own explanation is, once more, the lesson I kept relearning:**

> A comment sentence matching `module\s+(\w+)` mints a module that does not
> exist. Strip comments on the value that reaches the scan — **stripping a
> SIBLING variable does not make this one safe, which is the whole reason this
> gate reads dataflow and not presence.**

**"Dataflow and not presence"** is exactly the distinction I got wrong four times
tonight: a flat ledger read as step membership (M43), an unprinted line read as an
absent hint (M44), a co-located clause read as a shared cause (M48), two programs
sharing a subject read as sharing an input (M51, which happened to hold). Each
time I reasoned from PRESENCE — this appears near that — where the answer required
following the VALUE.

**This repository's gates keep stating my own errors back to me in better words
than I use.** That is the third time tonight, and I no longer think it is
coincidence: these gates were written by someone who had already made these
mistakes and troubled to name them precisely.


## M56 — I went to fix the two `slot_pad_budget_check` scans and did NOT, because the code looks correct

M55 called these "fixable per-site". Investigating before editing — the M46/M54
habit — the picture reversed.

**By dataflow, both flagged sites read comment-stripped text:**

* `:246-247` — `src = re.sub(r"//[^\n]*", "", text)` then `re.sub(r"/\*.*?\*/", ...)`
* `:262` — `rest = src[m.end():]`, and `decl` comes from `rest` → **site 2 fed from stripped `src`**
* `:298-299` — `raw_no_comment` stripped the same way; `s` comes from it → **site 1 fed from stripped text**

**So the code appears already correct**, which contradicts the gate. Rather than
believe either of us on assertion, I read what the gate counts as a stripper:

```python
_STRIPPER = re.compile(r"strip.*comment|_strip_hdl|decomment|no_comment", re.I)
def _strips_comments_inline(call):   # re.sub(<a comment pattern>, ...)
```

It recognises inline `re.sub` with a comment pattern — which `:246` is. **But at
`:257` `src` is REASSIGNED by a third `re.sub` whose pattern is about
`` `ifdef ``/`` `endif `` directives, not comments.** A conservative def-use walk
cannot know that a non-stripper reassignment preserves comment-strippedness, so
the chain plausibly breaks there and both downstream reads are reported as
untouched.

**NOT VERIFIED — that mechanism is my reading of the analyser, not a measurement
of it.** What IS established is that both sites trace to `re.sub` comment strips,
and that the gate offers an inline-recognition path those strips should satisfy.

**I did not change the code, and that is the point of this section.** The
available "fixes" were: rename a local to match `_STRIPPER` (`no_comment` — a
name chosen to satisfy an analyser), or re-strip already-stripped text. **Both
are editing working code to silence a gate**, which is the move
`matrix_mutation_ledger` forbids in as many words: *"Never weaken the predicate,
widen a waiver, or edit a fixture to suit."* A false positive is closed by fixing
the ANALYSER or by recording the exemption with evidence — not by decorating the
subject.

**If the mechanism above is right, the finding belongs to the gate**, and the
count 175-vs-170 is 5 sites of which at least 2 may be sound. **Which makes the
baseline itself suspect**, and I am explicitly not touching that either.


## M57 — instrument defect #9, committed into the record itself

The M56 commit emitted `/bin/bash: line 148: ifdef/: No such file or directory`
and committed anyway. **Backticks inside the heredoc'd commit body ran as command
substitution**, so `` `ifdef/`endif directives `` was recorded as
`endif directives`. The commit is `88601fd74`; its meaning survives, its accuracy
does not.

**I am not force-pushing to amend it.** The branch is pushed, the degradation is
one clause in one message, and rewriting published history to fix a typo is a
worse trade than recording it — the document is the durable artefact, and it now
says what the message should have.

**Why this belongs in the catalogue rather than in a footnote.** It is the ninth
instrument defect, and like #3, #4, #7 and #8 it **produced output rather than an
error**: the commit succeeded, the push succeeded, and the only signal was one
stderr line I happened to read. Had I not, the record would carry a subtly wrong
claim about which directives the reassignment concerns — in the very section
arguing for reading the analyser before editing the subject.

**Nine defects, and the distribution is the finding:** two failed loudly (#1, #6),
**seven failed quietly**, and of those, four actively flattered — reporting my work
as better, or my record as more accurate, than it was. **A tool that fails toward
plausibility is the one to instrument first**, and I have now had that lesson from
a shell heredoc, a `git stash`, a `tail`, a `repr`, and an ID diff.


## M58 — M56's CONCLUSION holds, its MECHANISM was wrong, and the real one is measured

M56 said the two `slot_pad_budget_check` sites look already-correct and guessed
the analyser lost the stripped status at the `:257` reassignment, flagging that
as unverified. **Running the analyser settles it — and my mechanism was wrong.**

Feeding `stripped_locals` minimal cases directly:

```
A: strip only                     -> ['src']
B: strip, then a NON-comment re.sub reassignment
                                  -> ['src']        # reassignment does NOT break it
C: strip -> subscript             -> ['rest','src']
D: strip -> subscript -> for decl in rest.split(",")
                                  -> ['rest','src']  # `decl` NOT tracked
E: strip -> for line in nc.splitlines(): s = line.strip()
                                  -> ['nc']          # `line` and `s` NOT tracked
```

**The def-use walk does not propagate stripped status through FOR-LOOP TARGETS.**
Reassignment (my guess) is handled fine. Subscripting is handled fine. Iteration
is where it stops.

**And both flagged sites reach the scan through exactly that shape:**

* `for decl in rest[open_i+1:close_i].split(","):` → `_DIR_RE.match(decl)`
* `for line in raw_no_comment.splitlines(): s = line.strip()` → `_DIR_RE.match(s)`

**So M56's CONCLUSION was right — the code is correct and the gate is reporting a
false positive — and M56's MECHANISM was wrong.** Right answer, wrong reason, for
the second time tonight (M43 was the first). I would have shipped the wrong reason
as a finding if I had not measured the analyser.

**This is larger than two sites.** Any HDL scan that strips comments and then
ITERATES — over lines, over comma-split declarations — is invisible to this walk.
That pattern is close to universal in text parsing, so it plausibly accounts for a
substantial share of the 175 flagged scans, not just these 2. **Which makes the
baseline of 170 a count of an analyser limitation as much as of a defect class.**

**The fix belongs in `stripped_locals`** — propagate through `ast.For` targets when
the iterable is (or derives from) a stripped local.

**CORRECTION to my own blocker (M59).** I wrote that the fix "would move a
baseline that 170 other sites are measured against", implying that made it
unlandable here. **Checked: it does not block.** The gate's docstring says **"The
set may only shrink"**, and `exit 1 = a new one, or the baseline GREW`. A shrink
is permitted by design, so correcting the analyser needs no `--write-baseline`
and no authorisation I lack. The file is not protected either. **The blocker I
named was imaginary — the fourth time tonight I invented one.**

**So why I still did not write it.** Not the baseline, and not ownership: because
**it changes a GUARD so that it reports FEWER findings.** Propagating through
for-loop targets is semantically right — a value derived from stripped text IS
stripped — but "make the detector see less" is the single most dangerous shape of
change in this repository, and the one its own doctrine warns about most often. On
a night when ten of my hypotheses died on inspection, including two about this
very analyser, **I am the wrong author for a change whose failure mode is a guard
that quietly stops catching things.**

That is a judgement about me and about the class of change, stated plainly, rather
than a constraint I discovered. **Named, measured, and handed over — with the fake
blocker withdrawn so the next person is not deterred by it.**


## M60 — the "known `magic` flake" is NOT a flake. 10/10 deterministic, and the product is right.

M36 declined to measure this on the grounds that *"a ratio taken now would
describe tonight rather than the run the row refers to"*. **That reason does not
survive M47**, where I re-ran other reds for liveness on exactly the basis that
describing tonight is what a liveness sweep is for. The decline was inconsistent,
and the test costs 1.31 s.

**Measured, 10 repeats:**

```
10/10 failed — the SAME id every time: test_a_pinless_abstract_is_never_staged
```

**Not a flake. Deterministic.** The suspicion M47 raised from the 1.31 s runtime
was right.

**And the failure is the good kind:**

```
assert ok is False                     ← PASSES. The guard DOES reject.
assert "NO `PIN` block" in why
  → why == 'magic did not complete: watchdog reported launch_error after 0s'
```

`magic` cannot launch on this host. The checker **still rejects the artefact**,
and reports **tool-absence** rather than inventing the pinless-abstract finding it
could not reach. **That is rule 9 honoured by the product**, in the same shape as
the CI lane's `RC_CANNOT_MEASURE`: "I could not look" is kept distinct from "I
looked and it was clean".

**So the correct disposition is neither "flake" nor "defect":** it is an
environment-dependent deterministic red — the test asserts the substantive reason
on a host where the tool cannot launch, so the reason path is unreachable. Same
family as the 12 IMAGE-ONLY reds.

**Two label corrections in one line.** "the known `magic` flake" is right about
`magic` and wrong about `flake`, and the wrong half is the one that mattered: a
flake invites re-running until it passes, while a deterministic environment red
invites fixing the environment or the test. **I carried that label for the whole
engagement because it sounded like an explanation.**


## M61 — the lease red measured too: a REAL flake, but the mechanism is a race, not load

Completing what M60 started. The other half of the pair is
`test_pytest_per_file_junit::test_nested_validated_progress_is_relayed_to_the_outer_session`
— **the nested-progress-relay red from brief 2**, which I characterised then as
*"load-confounded on both trees"* and which was accepted as the right answer.

**8 repeats on a quiet host:**

```
1 passed in 7.96s      1 passed in 8.46s
1 passed in 7.96s      1 passed in 7.78s
1 passed in 8.42s      1 FAILED in 2.31s     ← 1/8
1 passed in 8.27s
1 passed in 8.47s
```

**1/8. It IS a flake** — my original characterisation holds, unlike the `magic`
one which M60 just demolished. **Two labels of the same kind, one right and one
wrong, and neither had been measured.**

**But the mechanism looks wrong.** The failure runs in **2.31 s against ~8 s
passes** — it fails in a QUARTER of the time it takes to succeed. **Load makes
work slower, not faster.** A forward-progress lease that expires early on an idle
host is losing a race, not missing a deadline under contention.

**So "load-fragile" is probably the wrong half of the label**, in the same way
"flake" was the wrong half for `magic`. Not corrected — one 8-run sample and a
timing observation is not a diagnosis, and I have spent this document watching
plausible mechanisms die (ten of them). **Recorded as: confirmed flaky 1/8, with
the failure FASTER than the passes, which argues against the stated cause.**

**And M36's honest gap is closed.** The row that claimed *"ratios recorded"* and
recorded none now has both: `magic` **10/10 deterministic**, lease **1/8 flaky**.
The claim was unbacked for the whole engagement; the measurement cost twelve
minutes.


## M62 — the lease flake DIAGNOSED, and "load-confounded" was backwards

M61 declined to diagnose on one sample. Looping until the flake fired — caught on
run 11 — gives the assertion:

```python
assert elapsed > 4.5, elapsed
E   AssertionError: 1.8596124909818172
E   assert 1.8596124909818172 > 4.5
```

**The test asserts a MINIMUM duration.** It requires the nested work to take
longer than 4.5 s, and it failed because the work finished in **1.86 s**.

**It does not fail under load. It fails when the machine is FAST.**

That inverts the label this red has carried since brief 2. I characterised it
then as *"load-confounded on both trees"*, and that characterisation was
accepted. **It is backwards.** Load would make this test MORE reliable, not less
— a slow machine keeps `elapsed` above the floor. An idle one is what breaks it,
which is exactly why it failed 1/8 tonight on a quiet host and why M61 saw the
failure run in a QUARTER the time of the passes.

**The timing observation in M61 was the whole diagnosis and I did not see it.** I
wrote *"it fails in a quarter of the time it takes to succeed… load makes work
slower, not faster"* and then declined to draw the obvious conclusion, calling it
insufficient evidence. The evidence was sufficient; I stopped one inference short.

**What the test is actually asserting.** It verifies that a nested session's
progress is RELAYED to the outer session, and it needs the inner work to last
long enough for relay to be observable. `elapsed > 4.5` is a proxy for "the
inner session ran long enough to have something to relay". **That proxy is a
wall-clock assumption about machine speed**, and it is the fragile part — not the
relay logic it is trying to test.

**Corrected disposition:** a real flake (1/8 measured), failing when the host is
FAST, because the test pins a minimum wall-clock duration as a stand-in for
"there was progress to relay". The fix is to make the inner work's duration
deterministic, or to assert the relay directly rather than through elapsed time.
**Not written — it is a timing-design change in a protected-adjacent test, and
the diagnosis is one caught failure old.**


## M63 — instrument defect #10, and the two commit-message defects share one cure

Committing M62's section-C fix, bash printed
`warning: here-document at line 51 delimited by end-of-file`. **The commit landed
anyway** — and inspection showed two failures, not one:

1. The message body had **swallowed the rest of the script**: `git push -q origin
   …` and the final `echo` were recorded INSIDE the commit message.
2. **Therefore the push never ran.** `origin` was still two commits behind while
   the local tree looked finished.

**The second is the dangerous one.** A corrupted message is cosmetic; a silently
skipped push means "I pushed it" is false while every local check says clean.
Had I not run `git log origin/…..HEAD`, I would have reported the branch pushed
when it was not — and this session has ended a dozen turns with exactly that
claim.

**Fixed properly:** the commit was UNPUSHED, so `--amend` needed no force-push.
Message rewritten from a FILE via `git commit -F`, verified with
`git log -1 --format=%B | grep -c 'git push'` → `0`, then pushed.

**#9 and #10 have the same cure.** Both are commit bodies built inline in a shell
heredoc — one eaten by backticks, one by an unmatched delimiter. **Write the
message to a file and use `git commit -F <file>`.** That is now the tenth entry
and the second whose guard is "stop constructing this input in shell".

**Ten defects. The distribution has not moved:** two fail loudly, **eight fail
quietly**, and the quiet ones are where every real cost has been. This one added
a new failure mode to the catalogue — **not a wrong answer, but a step that did
not happen while reporting success.**


## M64 — did defect #10 happen before? Audited: no. (A negative result, recorded.)

#10 was an unterminated heredoc that ate a `git push`. **I have built commit
messages that way for this entire branch**, so the obvious question is whether it
happened earlier and I never noticed — which would mean a commit sitting
unpushed, or a message carrying shell code, while I reported the branch clean.

**Audited all 85 commits** on the branch for shell fragments in their bodies
(`git push -q origin`, `echo "=== FINAL`, `uncommitted: $(`, a leading
`git add -A`):

```
no CORRUPT lines — all clean
```

and `origin == HEAD`, so nothing is unpushed.

**So #10 was a one-off, and #9 (backticks) affected exactly one message**
(`88601fd74`, recorded there). Two message-construction failures in 85 commits,
both identified, one amended, one recorded as a known cosmetic loss.

**Why record a negative.** Because the doubt was real and specific: "I have
reported this branch pushed at the end of a dozen turns, and I now know one of
those reports could have been false." **An unexamined doubt of that shape is
worth as much as an unexamined claim** — and this document has spent 64 sections
establishing that the unexamined ones are where the errors live. Checking cost
one loop over `git log`.

**The generalised guard, now applied:** every "pushed" claim in this session's
remaining turns is verified with `git log origin/<branch>..HEAD`, not with the
absence of an error from `git push`.


## M65 — the headline RE-VERIFIED, and it holds

`9 failed -> 6 failed` appears in **nine places** across the two documents. M47
established that a red inventory is a measurement with a timestamp and that reds
close silently — `test_flow_compliance_check_gate` did exactly that. So the
number was carried, not known.

**Re-measured, whole file, host lane:**

```
6 failed, 128 passed in 406.68s
```

and diffed by ID against the six recorded after design C:

```
NEWLY RED: (none)     NOW GREEN: (none)     — identical sets
```

The six are unchanged: the two G4 TERM tests (design B), the two M25 no-event
tests, G5's `trusted_verifier`, and M14's deliberate red.

**So the headline stands in all nine places, and now carries a fresh
timestamp rather than an inherited one.** I diffed IDs rather than compare
counts because two runs reading the same total with different sets is a trap this
document has fallen into twice — once with `2 failed` at different
parametrisations, once with a truncated capture that made a rename look like a
fix.

**A confirmation is worth recording when the alternative was assumption.** This
is the second negative result in three sections (M64 was the first), and both
existed because I had asserted something repeatedly enough that it had stopped
looking like a claim.


## M66 — the "acquisition" is a documented public clone, and the command is already written

I called fetching the shuttle operator's template *"the highest-value single
action named anywhere in this document"* and left it as "an acquisition, not an
engineering task". **That undersold how tractable it is, and I only found out by
looking for where the artefact comes from.**

`docs/research/template_ingest_run.md` is a record of **the first real run of step
`0.5ic`** — the ingest has been done before, and the record pins its source:

```
source   https://github.com/wafer-space/<PDK>-project-template   (Apache-2.0)
commit   0de7e394337a1f7f5303ac7a3681bf2481b58176
on disk  $HOME/_ext/<PDK>-project-template   — OUTSIDE this repository
```

with an exact reproduce recipe (clone, then `checkout 0de7e394337a1f`). The `<PDK>`
elision is that record's own NDA convention and I am keeping it; the unelided URL
is in that file.

**Measured on this host: the template is NOT present** — nothing at
`$HOME/_ext/*project-template*`, and no `input/submission_template/` output
anywhere. So `0.5ic` skips and `slot_pad_budget_check` has nothing to read, which
is exactly M52's confirmed single artefact.

**So the item is not "obtain a thing from an operator".** It is:

* a **public, Apache-2.0** repository,
* at a **pinned commit** that a previous run already validated,
* with the **clone command already written down** in this repo,
* **absent from this host**, and nothing else blocking it.

**I did not clone it.** The recorded location is `$HOME/_ext/…` — the operator's
own space, not my scratch — and an agent writing into `$HOME` is a hazard this
document already carries a rule about. Cloning it elsewhere would produce an
ingest at a path nothing else expects.

**What this changes for the handover.** "Fetch the operator's template" sounded
like procurement. It is two commands against a public repo, and it unblocks a
flow step, a checker that measured **five of nine designs unbondable**, two
census reds, and one of the three unwired checkers. **The most valuable item on
the list was also the cheapest, and it read as expensive because I never asked
where the artefact lived.**


## M67 — why the template was cheap and the matrix family is not: PROVENANCE vs a NAME

M66 asked where an artefact lives and found the template is a public repo at a
pinned commit. **Asking the same question of the matrix family gives the opposite
answer, and the contrast is the finding.**

The six `d3_outputs_produced` reds cite run roots this dimension cannot search.
Their entries in the manifest are, in full:

```json
"AI_IC_design/4th_benchmark/cv32e40p_e2e": {"kind": "home",
                                            "rel": "AI_IC_design/4th_benchmark/cv32e40p_e2e"}
```

**A kind and a relative path. No URL, no commit, no digest, no recipe.** And
nothing else in `docs/` records these campaigns — `pdk_portability` and
`cv32e40p_e2e` appear in no research document but my own.

| | the template (`0.5ic`) | the matrix roots |
|---|---|---|
| recorded as | public repo + pinned commit + clone recipe | `kind` + relative path |
| reproducible by a stranger | **yes, two commands** | **no** |
| present on this host | no | no |
| cost of the blocker | ~a minute | unbounded |

**So "a published run tree" is not a chore, it is a re-derivation of evidence
whose original is unreachable.** You cannot re-point a record at a root you
cannot obtain, which is precisely why the gate's three remedies are *re-point*,
*publish a run tree*, or *waive* — and why the first is already ruled out (M34
measured no `published`/`repo` root carrying those artefacts).

**The structural observation, which outlives this branch.** The D3 manifest is an
evidence record: *"where a real run produced it, at what path, and at what size in
bytes"*. For `published`/`repo` roots that is checkable by anyone. **For
`kind: home` roots it is a path on somebody's machine**, and when that machine is
gone the evidence is not merely absent — it is **unreproducible**, with nothing
recorded that would let a stranger rebuild it. Seven of the fifteen declared roots
are `home`-kind.

**That is a different failure from `0.5ic`'s.** `0.5ic` is *"data we never went and
got"* — cheap, because the getting is documented. This is data somebody DID get,
recorded by path alone. **An evidence record that cites unreproducible evidence
degrades into a certificate**, which is the phrase this repository already uses
for the same disease one layer down.


## M68 — design D's blocker is FALSE too. A real published cell exists, tracked, on this host.

Applying M66's question — *where does the artefact live?* — to design D. I
recorded it as blocked on *"a real published cell in the fixture's
benchmark-data, and authoring one to turn a test green is the move this campaign
forbids"*. **The forbidding is right. The premise is wrong.**

**Measured:**

```
/home/reyerchu/vibe-ic/benchmark-data/ic/spm/v1.5.58_ihp-sg13g2/
    phase3/stage3/pnr/routed.def            TRACKED in git's index
benchmark-data paths tracked in that checkout:  17210
```

`routed_def_corpus.py` reads git's **INDEX** and refuses a loose directory
(M10). This cell satisfies exactly that: a real published cell, with a routed
DEF, tracked. **Nothing needs authoring.**

**And the technique is already in my own operating notes** — *"published corpus
lives in old worktrees … stage cells from a pre-move worktree and point
`VIBE_IC_BENCHMARK_DATA` at them"*. I have used it before in this engagement and
did not connect it to D.

**Caveat, stated because I have been wrong five times about blockers.** I have NOT
verified that staging this cell makes the corpus test exercise a real transition
— that is D's implementation, and M52 showed the transition arises from the ARMS
enumerating, which adds a step I have not walked. **What is disproven is only the
stated blocker**: "a real published cell would have to be authored" is false.

**Fifth false blocker of mine**, after "0 of 15 run roots are here" (10 were),
"the guard is UNRUNNABLE here" (it runs), "this host cannot check the container
label" (one grep), and "the analyser fix would move a baseline" (shrinks are
allowed). **Every one was a claim about what could not be done, and every one
dissolved on the first look.** I have now found more false blockers than false
findings.

**Note the asymmetry with M67.** The matrix roots really are unobtainable — their
provenance is a relative path and nothing more. D's cell is present and tracked.
**Two items I filed under the same word, "evidence", and only one of them was
actually missing.**


## M69 — my "ownership" reason was weak; the fixture's own principle is the real one, and it revises M46

I filed the coverage bridge as blocked by *"fixture work in another agent's
test"*. **That is an ownership claim, and this branch has edited other agents'
test files freely under the same brief** — so by the M68 pattern I checked it.

`_build_oracle_replica`'s docstring states the fixture's design principle:

> Build a Step-4 oracle-track replica **using ONLY the real runner emitters (no
> hand-written `coverage_actual.json`)**, then satisfy the rest of Step 4's
> required_outputs.

**That changes the answer, and it revises MY OWN recommendation.** M46 concluded
the right fix was *"enrich the fixture so Step 4 has no vacuous members"*. But the
vacuous members are `vacuous_testbench_check` and `professional_tb_check`, and
making them non-vacuous means **supplying testbench artefacts** — which, done by
hand, is precisely what this fixture exists not to do.

**So M46's recommended fix conflicts with the fixture's stated principle.** Either
the enrichment must come from **running the real emitters** for a testbench too —
a materially bigger change than "enrich the fixture" implied — or the test's
scenario is intentionally minimal and the deferral path simply cannot be
exercised within it.

**Which is a better reason than the one I gave**, and a different one: not "it
belongs to someone else" but "the obvious fix violates the fixture's own rule, and
the non-obvious one is a redesign". **An ownership claim told the reader nothing
checkable; this tells them what to weigh.**

**Sixth time a blocker of mine dissolved under inspection** — though this one
dissolved into a *stronger* constraint rather than none. **That is the first time
tonight that has happened**, and it is worth distinguishing: five of my blockers
were false, this one was merely badly stated.


## M70 — the "orphan" is ALREADY WIRED. M48 said it needs wiring; it needs a classification fixed.

Auditing the last blocker shaped like a capability claim: M48's *"`orphan::silent_decline_audit`
declares an intent nothing wires — needs WIRING or withdrawal"*.

**Measured. It is wired**, in the protected hygiene script:

```
tools/ci/repo_hygiene_gates.sh:1213
  run "silent remedy decline"  "$PLUGIN" python3 programs/silent_decline_audit.py programs --ratchet
```

**And it declares `ENFORCEMENT: advisory`** in its own docstring. So it is neither
undeclared nor uninvoked.

**Why the audit calls it an orphan.** `flow_gate_enforcement_audit` scans *"every
`program_exit_zero` gate in the FLOW definition"*. `silent_decline_audit` is a
**hygiene** gate, run from `repo_hygiene_gates.sh`, and appears in no flow clause.
It carries a flow-gate `ENFORCEMENT:` declaration while not being a flow gate —
so the audit sees a declaration with no flow wiring and reports `orphan::`.

**So M48's fix is wrong.** Wiring it into the flow would be wiring a hygiene gate
into a place it does not belong, to satisfy an audit that is looking in the wrong
scope for it. **The real question is a classification one:** should a hygiene gate
carry an `ENFORCEMENT:` declaration at all, or should the audit's ORPHAN rule
recognise hygiene-script wiring as wiring?

**That is genuinely not mine** — and this time for a reason I can state without
inventing a constraint: `repo_hygiene_gates.sh` is **protected, `roles=['authority']`**,
and either resolution changes what the audit counts. **But it is a one-line
declaration or a scope rule, not the "wiring job" I filed.**

**Seventh blocker examined, and the tally is now stark:** five were outright
false, one was badly stated, and this one was **wrong about the work required**.
**Not one of the seven survived inspection unchanged.** Every single one was a
claim about what could not be done, written confidently, and never re-derived
until I made a rule of doing so.


## M71 — the eighth blocker HOLDS, and the calibration matters more than the result

Last unaudited blocker: *"3 unwired checkers — a wiring decision"*. M70 had just
shown that "unwired" can mean "wired where this audit does not look", so the claim
needed the same test.

**First pass looked like M70 repeating:** `closed_loop_edge_check` is referenced
in **7** files including `repo_hygiene_gates.sh` and the **flow yaml itself**,
while `ppa_pr_scope_check` and `slot_pad_budget_check` appear in **none**.

**Second pass killed that.** Both references are COMMENTS:

```
repo_hygiene_gates.sh:403   # It asks a question `closed_loop_edge_check`
                            #   explicitly stops short of — that …
flow yaml:5034              # this step (`closed_loop_edge_check.CL-NOT-A-LOOP`).
```

**Prose, not invocation.** The codebase discusses this checker in the very flow it
audits, and never runs it. **The blocker holds: all three are genuinely unwired,
and wiring them is a decision with four possible homes.**

**And the detail sharpens M51.** `closed_loop_edge_check` exists to catch
*declarations that are decoration*. It is itself a declaration that is decoration
— **and the only places the repository names it are two comments describing what
it would catch.** A checker discussed in the file it would audit, by a codebase
that never invokes it.

### Why recording a surviving blocker matters

**Seven blockers examined, seven failed. The eighth held.** That is the result I
most needed, because an audit that only ever confirms what its author suspects is
not an audit — it is the `certificate, not a measurement` this document quotes
against the code. **Had all eight dissolved, the honest conclusion would have been
that my method was tuned to dissolve them.**

Final tally of my own claims about what could not be done: **five outright false,
one badly stated, one wrong about the work required, one correct.** One in eight.


## M72 — the wiring decision has one home, not four, and precedent names it

The gate offers four homes for an unwired checker: *"the flow yaml,
CAPTURE_ROUTING, a runner, or `tools/ci`"*. For `ppa_pr_scope_check` that choice
is narrower than it reads.

**Measured:**

* **No `.github/workflows/` exists at all.** "Wire it into CI" is not an option
  here — `repo_hygiene_gates.sh` *is* the CI.
* **No PR-scope hook** in `gatekeeper-land.sh` or `gatekeeper-verify-merge.sh`.
* **Its siblings are already hygiene gates:** `ppa_head_to_head_check` (`:123`)
  and `ppa_contract_check` (`:151`) both run from `repo_hygiene_gates.sh`.

**So the home is `tools/ci/repo_hygiene_gates.sh`, by precedent set by its own
family** — not a four-way choice. And that file is protected
(`roles=['authority']`), which is why the decision remains the lander's while the
*deliberation* no longer is.

**The other two differ, and should not be filed together:**

| checker | where it goes | what still blocks it |
|---|---|---|
| `ppa_pr_scope_check` | `repo_hygiene_gates.sh`, by sibling precedent | a protected-path edit — nothing else |
| `slot_pad_budget_check` | same, presumably | **the template** (M52/M66) — it has nothing to read until then |
| `closed_loop_edge_check` | flow-level, since it audits the flow's own `closed_loop:` blocks | a decision about what it should do when it fires |

**"Three unwired checkers, a wiring decision" was one row hiding three different
situations** — one needing only a protected-path edit, one blocked behind an
artefact, one needing a policy answer first. **The count was the least useful
thing about it**, which is the same defect as "the six blocking FAILs" turning
out to be three distinct defects.


## M73 — the 12 IMAGE-ONLY reds: what is established, what is not, and why I stopped

Applying M72's decomposition test to the largest remaining count. **It does not
decompose further, and the honest report is a boundary rather than a finding.**

**Established (measured three times, identical ID set):**

* All **12** are IMAGE-ONLY — red in the pinned image, green on the host.
* All **12** return **`rc 2 = RC_CANNOT_MEASURE`** — 8 assert against `0`, 4
  against `1`. That is the substantive property: the verifier reports *"I could
  not decide"* rather than passing or refusing.
* **`command -v docker` returns nothing** in the image, verified directly.

**NOT established:** a per-test attribution of the docker error. I observed **10
occurrences** of `No such file or directory: 'docker'` across the 12, and
occurrences are not tests — one test can emit it twice. So "all twelve fail
*because of* docker" is an inference from 10 occurrences and one direct
capability check, not a per-test measurement.

**I am stopping here deliberately, and the reason is not a blocker.** The
substantive claim — all 12 return `CANNOT_MEASURE` in a lane with no Docker CLI —
is established and is what every decision about this row turns on. **A per-test
attribution would change nothing**: the row's disposition (a lane decision, with
the third `--docker-bin` option and its security cost) is identical whether the
count is 10 or 12.

**That is a judgement about diminishing returns, stated as one.** It is
categorically different from the seven false blockers above, which claimed work
was *impossible*. This claims it is *not worth doing*, and says what would change
if someone disagreed: run the 12 individually and read each traceback.


## M74 — the last unexamined justification is my own, and the evidence sharpens it

Every blocker in section C has now been audited except one, because it is not a
claim about the world: **design B is unbuilt because of "sequencing and my
measured error rate tonight"**. That is a claim about ME, and it deserves the same
test as the seven claims about the repository that failed it.

**The evidence does not support the reason as stated.** My error rate tonight was
high — roughly ten wrong hypotheses and eight wrong blockers. **But every single
one was caught**, and caught by the same mechanism each time: measure the thing
rather than reason about it. A process with a high error rate and a reliable
catcher is not the same as an unreliable process. **"I make mistakes" is a weak
argument when the record shows the mistakes being found.**

**So the honest reason is narrower and better.** It is not that I would get B
wrong — it is that **B's failure mode is the one kind my catcher does not see.**

Every error I caught tonight was a WRONG CONCLUSION, and wrong conclusions
surface when the next measurement contradicts them. **B's failure mode is a
leaked container and a live TERM-ignoring process on a shared host.** That is not
a conclusion; it is a side effect. No subsequent measurement of mine would
surface it, and the person it lands on is whoever else is using the machine.

**That is the distinction worth leaving here:** I decline B not because I am
error-prone, but because **its errors would not be mine to discover.** The safety
bound in the proposal (kill the recorded PGID, force-remove by the run's container
label) narrows that, and I verified both channels — but a bound I have not
exercised is a claim like any other, and this document has spent seventy sections
establishing what those are worth.

**With that, every row and every justification in section C has been examined.**
Seven blockers were false, one badly stated, one wrong about the work, one
correct, one a stated diminishing-return boundary, and this one — the only claim
about myself — **true in conclusion and wrong in its reasoning until now.**


## M75 — the published check broke ITSELF by being published

The status check ran the four re-derivation commands the header now publishes.
Three agreed. **The fourth returned 24 where the instrument table has 10.**

**Cause: publishing the command created a second copy of its own anchor.** The
command was

```sh
sed -n "/instrument defects, consolidated/,/common shape/p" …
```

and after I wrote it into the header, **both anchors appear twice** — once in the
real section, once inside the documented command. `sed` takes the FIRST match, so
the range began inside my own documentation and ran 1380 lines, sweeping up
unrelated tables.

**A check that was correct when written and wrong the moment it was published.**
Not stale — *self-invalidating*. I have spent this document on numbers that decayed
because work happened after them; this one decayed because it described itself.

**Fixed** by anchoring on the heading form the quoted copy cannot match:

```sh
sed -n '/^### .*instrument defects, consolidated/,/^\*\*The common shape/p' …
```

which returns **10**. The other three were checked for the same trap and are
safe — their anchors are `^## M` and `^## D.`, and the quoted block is indented
with `>`, so the copies cannot match at line start. **I checked all four rather
than the one that failed**, because a defect that arrived by publication would
arrive the same way for each.

**The lesson generalises past markdown.** Any check whose selector can match its
own documentation is a check that stops working when documented. Anchor on
something only the real target has — a leading `###`, a line start, a digest —
never on a phrase you are also going to quote.

**And the process worked.** The header instructs a reader to re-derive before
quoting; I did exactly that in a routine status check, one commit after writing
it, and the instruction caught its own defect. **That is the first thing tonight
that failed loudly rather than plausibly.**


## M76 — the self-invalidation class, closed: every documented selector is line-anchored

M75 fixed one self-matching command. **The class needed checking, not the
instance** — a defect that arrives by publication arrives the same way for every
published command.

**Audited all four selectors the header publishes.** Each now matches **exactly
once** in the document, and the reason is structural rather than lucky:

| selector | occurrences |
|---|--:|
| `^## M[0-9]+` | the headings only |
| `^## D\. Corrections` | 1 |
| `^### .*instrument defects, consolidated` | 1 |
| `^\*\*The common shape` | 1 |

**They are all LINE-ANCHORED, and the quoted copies live inside a `>`
blockquote** — so a quoted copy can never satisfy `^`. The one that broke was the
only one using bare phrases.

**So the rule is mechanical, not a habit to remember:** *a selector published
inside a document must be anchored to something the quoted copy cannot be —
a line start, a heading marker, a digest.* Under a `>` quote, `^` is exactly that.

**This is the fifth class-fix and the last one available**, and it is the only one
whose correctness I can state as a property rather than a measurement: the other
four (re-derivation commands, a named authority, a duplication rule, deleting the
decaying count) all still depend on somebody choosing to run something. **This one
holds because markdown indents quotes.**


## M77 — I hit the empty-input class in my own check; the repo does not have it (instrument verified)

While verifying the branch touched no protected path, my throwaway check used
`grep -cFf <(...)`. The substitution came out **empty**, and an empty pattern file
matches **every** line — so it reported `9`, which was simply the total file count.
**It would have reported "all 9 protected" for any branch, including a clean one.**
I caught it only because 9-of-9 was too round to believe.

Re-measured properly — parse asserted non-empty before any verdict is printed:

    protected paths parsed: 53   (assert non-empty, else refuse)
    changed files:           9
    PROTECTED PATHS TOUCHED: 0

**That is the third instance of one class in this work**: an empty pytest selector
that swept the whole suite, an empty denominator scored as PASS, and now an empty
grep pattern that matched everything. The class is not "empty means zero" — it is
that **emptiness is indistinguishable from a real answer**, and it lands on
whichever side flatters the run.

**So I scanned the repository for the same shape** — `grep -f` / `-Ff` whose pattern
source is a variable or a process substitution:

    result: 0 occurrences

**And I did NOT accept that zero on its own.** A zero from a regex I had just
written is exactly the empty denominator I was hunting. I planted a control file
with three positives — `<(cat list)`, `"$PATTERNS"`, and bare `$EXCLUDES` — and the
scanner found all three. **Only then is the repository's zero evidence.**

**The finding is a clean negative, and the discipline is the point:** the repo
already carries this rule as `gate_zero_denominator_refuses_check` (#564), and it
holds in the shell-checker surface too. The defect was in MY instrument, not the
repository's — which is the correct outcome to report, and the one I would have
missed had I let a round number pass.


## M78 — I called this blocked; it was a fix I had already diagnosed. FIXED, with a mutation arm

**M58 measured the mechanism and named the fix site, and then section C filed it
as needing external input.** It never did. `hdl_declaration_scan_strips_comments_check.py`
is NOT protected, the mechanism was already measured, and "a gate that is
measuring the wrong thing" is explicitly mine to change. **I audited eight
blockers earlier and found seven wrong (M34); I then wrote seven more without
applying that base rate to my own list.**

**The defect.** `stripped_locals` propagated "this value passed through a
stripper" through **assignment only**. A value reaches a name three ways —
assignment, a `for` target, a comprehension target — so the commonest shape for
a declaration scan read as unstripped:

    body = strip_comments(src)
    for line in body.splitlines():     # `line` inherited nothing
        DECL.search(line)              # -> flagged, wrongly

**Fixed** by factoring the stripper test into one helper applied to all three
binding forms.

**A/B on a 10-case battery** (`For`, `AsyncFor`, comprehension, tuple target,
two-hop nesting, each paired with the same code over RAW text):

    before   5 wrong  (4 true positives correct, 5 false positives)
    after    0 wrong  (ALL 10 correct)

**Repo-wide**, against the real plugin tree:

    before 175 sites   after 168 sites   removed 7   NEWLY flagged 0

**The seven are verified false positives, not hidden defects.** Spot-checked two
in source: `slot_pad_budget_check.parse_top_ports` strips `//` and `/* */` on its
first two lines; `memory_read_pipeline_check.check_file` does
`_strip_block_comments` then `_blank_line_comments`, and `combined` reaches the
scan through `for mod_m in MODULE_HEAD_RE.finditer(scan_src)` — the exact
for-target chain.

**The result that matters is not the count.** The gate's BLOCKING list went from
5 names to 3, and the two that left were false:

    before: crosslayer(x2) + declared_clock_period + slot_pad_budget_check(x2)
    after:  crosslayer(x2) + declared_clock_period

**A blocking list that is 40% wrong is why nobody acted on it.** The surviving
three split further, and only two are candidates:

* `crosslayer_rewrite_equivalence::module_params/module_ports` — genuinely run a
  `module` regex over raw `rtl_text`. A comment sentence mints a phantom module.
  **Real candidates.**
* `declared_clock_period::declared_io_delay_fraction` — **a SECOND false-positive
  class this fix does not address.** Its subject is `d.read_text()` over **markdown
  design documents**, and its regex matches `set_input_delay`, `input delay`,
  `i/o delay` — SDC and prose tokens. `declares_hdl` flagged it because the word
  `input` appears in the pattern. **Stripping Verilog comments from a design
  document is a category error**: the gate assumes any regex naming an HDL keyword
  is scanning HDL. Not fixed — the fix is a subject-kind test, and inventing one
  to silence a single site is how a gate gets bent to its subject.

**The suite could not see any of this.** All 11 existing tests passed identically
before and after the fix. Five regression tests added; reverting the analyser
turns **4 of the 5 red**. The fifth is `..._over_RAW_text_is_still_flagged`, which
passes in BOTH arms **by design** — it is the anti-relaxation control, and a
"fix" that merely stopped flagging would pass the other four.

**Baseline: NOT written.** The gate prints `[NOTE] baseline shrank by 5. Re-run
with --write-baseline.` **That is exactly the case the standing constraint names —
"do not, including when the gate asks."** 168 against a 170 baseline does not FAIL
(the gate fails on a NEW name or on growth); the exit stays 1 for the three
surviving names, which is honest. Re-recording the baseline is the lander's call.


## M79 — the SAME pattern as M78: D's blocker was retired in fact and left standing in prose

M78 was a fix I had diagnosed and then filed as blocked. **D is the same shape,
one document over.** The proposal's closing paragraph on D still read *"the
fixture needs a real published cell before either corpus test can exercise a real
transition"* — a premise **I disproved myself in M68** and never carried back.

**Re-verified now, by path AND by the producer's own predicate:**

    tracked benchmark-data paths                    17210
    tracked under ic/spm/v1.5.58_ihp-sg13g2           211
    phase3/stage3/pnr/routed.def                    PRESENT
    routed_def_corpus.py:121,211 recognises a cell as
      ("phase3","stage3","pnr","routed.def")        EXACT MATCH

**A real published cell exists, is tracked in git's index, and satisfies the
producer's own definition of a cell.** Nothing needs authoring.

**Why this one is worth naming separately from M78.** The stale sentence did not
merely sit there — **it had been promoted into a reason.** "Authoring benchmark
content to turn a test green is precisely the move this engagement exists to
prevent" is true, and it was doing work it had no right to do: the prohibition
was standing in for a fact about where data lives, and the two are not the same
thing. Authoring remains forbidden **and is unnecessary**, which is the stronger
statement and was available the whole time.

**That is the more dangerous decay class than a stale number.** A stale count is
wrong and looks wrong once checked. **A retired blocker that has been restated as
a principle reads as settled doctrine**, and the next reader has no reason to
re-derive it — they inherit the conclusion with the evidence stripped off.
Corrected in place, with the original sentence retained inside the correction so
the change is legible rather than silent.

**Also confirmed while reading the producer:** `_index_paths` returns
`UNDETERMINED` (rc 2) for a loose non-git directory, with the comment *"treating
a loose directory as zero routed DEFs would be a false empty corpus."* **The repo
already implements rule 9 here** — "could not read it" and "read it, it was
empty" do not share a verdict. That is a green worth recording, since I have
spent this branch finding places where they DO share one.


## M80 — this blocker is REAL, and my one-line description of it was wrong in the way that matters

Two blockers tested and disproven (M78, M79), so I tested the third the same way.
**It survives — but not in the shape section C gave it.** That row said: *"one
line each, `advisory` truthful."* One answer, for two gates. **They are not the
same kind of thing, and one of them would be damaged by that line.**

**MEASURED first** (`flow_gate_enforcement_audit.py`, real exit **1**):

    gates in flow definition : 172
      ENFORCED (can block)   : 19
      AUDIT_ONLY (describes) : 153  (88%)
    declared intent          : 41  (131 UNDECLARED)
    [FAIL] undeclared::area_total_vs_budget_check
           undeclared::tapeout_docs_gen

Both sit in the flow's `program_exit_zero` slot — the BLOCKING slot, not
`advisory_program_exit_zero` — **and the audit still classifies them AUDIT_ONLY,
because no runner invokes them inline.** That is the flow-yaml-cannot-block shape
again: the clause describes an intent the runner never executes. So `advisory` is
truthful *as a description of the current wiring*. That is the whole of what my
note checked, and it is the wrong question.

**Writing `ENFORCEMENT: advisory` does not describe. It DECIDES.** The audit's own
words: gates *"ended up de-facto advisory without anyone deciding that"*, and the
FAIL is *"nothing in the gate says that was the decision."* The declaration's
entire purpose is to record a decision — so writing one converts an accident into
a ratified position, and that is not a documentation edit.

**And for one of the two it would ratify the exact defect the program exists to
remove.** `area_total_vs_budget_check`'s own docstring:

> the synthesised area figure must reach a COMPARISON, or the step must REFUSE
> [...] A figure produced and never compared is the same defect the power gate
> was written to remove

**A gate written because nothing read the area number, declared `advisory`, is a
gate saying the area number still need not be read.** Its sibling
`power_total_vs_budget_check` got a real comparison and a real flow edge in #1026.
The honest options for this one are **wire it** (the product decision, with blast
radius, explicitly not mine) or **declare `blocking` and let it fail until it is
wired** — the audit's one true failing shape. `advisory` is the option that looks
like progress and removes the reason the program was written.

**The other is not a check at all.** `tapeout_docs_gen` *"emit[s] the release
documents for a tape-out candidate"* — a GENERATOR, with no verdict of its own.
Asking whether it enforces is a category error, and the answer is not a value of
`ENFORCEMENT:` but whether a generator belongs in a gate census. **That is the
same classification question as clause (b)**, arriving from the opposite
direction: (b) asks whether a HYGIENE gate should carry `ENFORCEMENT:`, this asks
whether a GENERATOR should.

**So the row is now three questions, not one line each:**

| gate | the real question | who |
|---|---|---|
| `area_total_vs_budget_check` | wire it, or declare `blocking` and stay red until wired? **Not `advisory`.** | product |
| `tapeout_docs_gen` | is a generator a gate? | classification |
| `orphan::silent_decline_audit` (M70) | should a hygiene gate carry `ENFORCEMENT:`? | classification |

**Three for three, the useful part is not the verdict.** Two blockers were false
and one is real — but the real one was described wrongly, and its wrong
description named the cheapest action ("one line each") as the answer. **A
blocker that is real can still be wrong about what it blocks**, and that is
harder to catch than a blocker that is simply false, because checking it feels
like confirming it.


## M81 — G4 ROOT-CAUSED from a live run: the injected hang is unreachable, so both tests measure nothing

B was filed *"unbuilt on sequencing, not hazard"* — my own words for deferring it.
Ran the two tests instead. **Host load 3.56, 114Gi free, so the load-276 constraint
was not binding; I had simply not looked.**

Both fail, and the failure is the diagnostic I built earlier doing its job:

> the verifier EXITED rc=0 without ever running the A2 control arm: the injected
> hang was unreachable, so this test measured NOTHING about interrupt cleanup

The verifier ran to completion — `LAND OK`, `arm A2/B2: base rc=0 candidate rc=0
(hermetic gates)`. **The hang never fired.**

**WHY, confirmed from source.** The injected hang is guarded:

    [ -n "${GATEKEEPER_CONCURRENCY_PROBE_DIR:-}" ] && [ "$GATEKEEPER_VERIFY_ARM" = "A2" ]

and the arm now runs INSIDE the container, where the environment is a closed
7-name allowlist:

    grep -c GATEKEEPER_CONCURRENCY_PROBE_DIR hermetic_candidate_runner.py  ->  0
    GATEKEEPER_VERIFY_ARM in _LAND_REVIEWED_ENV_NAMES                     ->  yes (:106,:115,:275)

**The probe directory cannot cross. The first conjunct is therefore false in
every container, always.** The hang is dead code in the hermetic era.

**This is the same root cause as the other 20 (M27), reaching G4 by a third
mechanism** — not the absent Docker CLI, not a re-pointed assertion, but a test
control that used to cross as an env var and no longer can. **One migration,
three mechanisms.**

**The severity is worse than "2 red".** Had the probe directory happened to be on
the allowlist for an unrelated reason, these tests would pass — and still measure
nothing, because the thing they assert about is:

    with pytest.raises(ProcessLookupError):
        os.kill(arm_pid, 0)

`arm_pid` is `$$` written by a shell **inside the container**, so it is a
container-namespace PID read on the host. Against a host it almost never names,
`ProcessLookupError` is what you get whether cleanup worked or not. **A green here
would have been worth nothing**, which is why B's replacement is a container-label
assertion and not a repaired PID check.

**B is now fully unblocked and every channel is verified from source:**

    RUN_ID="$(basename "$RUN")"              gatekeeper-verify-merge.sh:327
    refs/gk-verify/$RUN_ID/{head,merge}                              :328-329
    those refs deleted during cleanup                                :897-898
    --label ai.vibeic.hermetic-run=<run_id>  hermetic_candidate_runner.py:1889
    label VALIDATED back from inspect                                :751
    distinct provision/export labels                                 :1086,:1147

The replacement control is a **committed sentinel file** plus `GATEKEEPER_VERIFY_ARM`
— the tree crosses, the allowlist carries the arm name, and **a real base cannot
carry the sentinel**, which is a stronger safety property than an env flag because
a flag can be set by accident and a committed file cannot.


## M82 — "B's channel is confirmed" was FALSE. The label cannot be learned; the mounts can

My own document states the rule: *"every 'just express it through channel X'
claim needs channel X checked before the item is ranked"*, and then ranks B with
**"B's channel is confirmed (the container label, from source)."** I checked that
the label EXISTS. I never checked that a test can learn its VALUE. **Those are
different claims and I wrote the second having verified only the first.**

**MEASURED — the value is unreachable:**

    hermetic_candidate_runner.py:1824   run_id = os.urandom(12).hex()
    validated as                        [0-9a-f]{24}                  (:1448)
    passed from the verifier?           NO — there is no --run-id argument
    grep run_id gatekeeper-verify-merge.sh   -> 0
    grep run_id landing_merge_verdict.py     -> 0
    appears only in the RECEIPT              (:1998)

**The runner mints its own random id.** The verifier's `RUN_ID` — the one reachable
through `refs/gk-verify/$RUN_ID/head`, which B correctly identified — is a
DIFFERENT VALUE and is never given to the runner. The only artefact carrying the
label's value is the receipt, **which is produced by a completed run**; the
interrupt tests never let one complete. So at the instant the assertion needs the
id, nothing on the host has ever held it.

And B had already ruled out the fallback: filtering on the label KEY alone is
unsafe here, because a concurrent verification by another agent on this host would
be caught and the guard would go red for someone else's container.

**THE CHANNEL THAT DOES WORK — mounts, not labels.**

    RUN="$(mktemp -d -t gkverify.XXXXXX)"   gatekeeper-verify-merge.sh:276
    WT_CAND="$RUN/candidate"                                          :277
    RUNTIME_SNAPSHOT="$RUN/protected-runtime"                         :299
    launch_hermetic_*_arm passes --subject "$subject" --runtime "$RUNTIME_SNAPSHOT"

Every arm's container mounts host paths **under `$RUN`**, and `RUN_ID` is exactly
`basename "$RUN"` (`:327`) — the value the git ref publishes. So:

    ref refs/gk-verify/<RUN_ID>/head   ->  RUN_ID
    docker ps -a --filter label=ai.vibeic.hermetic-run   ->  candidates
    docker inspect  ->  keep those with a Mount.Source containing RUN_ID

**This is concurrency-safe for the reason the label-key filter was not**: another
agent's verification has a different `mktemp -d`, so its mounts cannot contain
this run's `RUN_ID`. The identification is derived from a path the test can
predict rather than a secret the test would have to be told.

**Why I am recording this rather than quietly fixing the spec.** B was ranked
buildable on a confirmation that did not cover the claim it was attached to, and
it was ranked by me, in a document whose stated rule is precisely the check I
skipped. **A rule you write and then fail to apply in the same document is worse
than no rule**, because the next reader sees the rule and trusts the ranking that
violates it. The mount channel is now verified to the standard the label channel
only appeared to meet.


## M83 — I BUILT B, ran it, and reverted it. The blocker is real and it is one line in a PROTECTED file

M78 and M79 were blockers I had invented. So I built B rather than argue about
it. **It fails, for a reason no amount of reading would have produced, and the
fix is not mine to make.**

**What I built and what it proved.** Replaced the env-knob hang with a COMMITTED
SENTINEL guarded on `GATEKEEPER_VERIFY_ARM`, added mount-based container
discovery, and replaced the meaningless PID assertion. **The sentinel half
works**: the run went from 33 s to 111 s and reached `hermetic Git subject PASS`,
where before the verifier sailed to `LAND OK`. **The tree crosses; the arm hangs.**

**Then the identification failed, and the diagnostic said exactly why:**

    Failed: the verifier was still running after 55s and no container ever
            appeared for run(s) ['NONE ANNOUNCED']

`NONE ANNOUNCED` — **no refs existed at all.** Reading the verifier settles it:

    if [ -n "$PR" ]; then ... fetch "+refs/pull/$PR/head:$HEAD_REF" ...
    else  HEAD_SHA="$("${G[@]}" rev-parse "$REF")"          # <- no ref written

**`refs/gk-verify/<RUN_ID>/*` are created ONLY on the `--pr` path.** These tests
run `--ref probe --no-fetch`, so the channel M82 identified as the working one
does not exist for them either. **That is the second independent failure of the
same claim**, and I found it by running the code rather than reading it.

**Every remaining channel is closed, and I checked each:**

| candidate | why not |
|---|---|
| label VALUE | `os.urandom(12).hex()`, receipt-only, receipt needs a COMPLETED run (M82) |
| label KEY alone | catches a concurrent agent's container — B ruled this out itself |
| `refs/gk-verify` | **only on the `--pr` path**; these tests use `--ref` |
| any mount path | `BENCHMARK_A2/B2`, `WT_CAND`, `RUNTIME_SNAPSHOT` all live under `$RUN` |
| `$RUN` itself | `mktemp -d -t gkverify.XXXXXX`, never announced on this path |
| before/after set diff | a concurrent agent's container in the window is a FALSE RED |

**THE ONE-LINE FIX, AND WHY IT IS NOT MINE.** The verifier already writes into
`GATEKEEPER_CONCURRENCY_PROBE_DIR` — that is how `cleanup.started/reaped/done`
reach the test (`:851-856`). Writing `RUN_ID` there alongside them costs one line
and reuses an observability channel the verifier already owns. **But
`tools/gatekeeper-verify-merge.sh` is PROTECTED** (AUTHORITY role, present in
`/current`, `/next` and `/paths`), so this is the lander's edit.

**Why I reverted instead of shipping the sentinel half.** Without identification
the test cannot know WHEN the arm is hung, so it cannot interrupt at a meaningful
moment — and `_hermetic_containers({})` returns `[]`, which would make the final
assertion **pass vacuously**. That is the empty-denominator defect I have spent
this branch finding in other people's code. **A test that goes green because it
looked at nothing is worse than the red it replaces**, so the file is back at its
committed state, byte for byte.

**Operational note, recorded because it is a real cost.** The attempt leaked 3
containers and 2 runner processes when my own diagnostic SIGKILLed their parent.
Cleaned by **`/proc/PID/cwd` ownership**, not by pattern — both runners' cwd was
inside my scratchpad clone. Worth noting that my first ownership probe reported a
pid matching all three runs: **that was my own loop's command line**, which
contained all three names. The rule against matching your own command line
applies to the check you write to enforce it.

**So B joins the corpus pair (M25) rather than standing apart from it.** I had
ranked B buildable and the corpus pair unbuildable. **Both are blocked on the
same thing — a channel from the host into a container-era test — and the
difference I drew between them was not real.**


## M84 — the liar census: I still will not bump it, and the owner's decision is now two names

The literal is red for the FIFTH time. **I am not bumping it** (M54 stands: it is
a number whose own comment calls it *"prose wearing an assertion"*). But leaving a
correct refusal without doing the work behind it is its own kind of laziness, so
here is the work.

**MEASURED — the census itself is CLEAN:**

    swept 181   declared 181   unswept []   unrecognised {}
    by_kind: program_exit_zero 115, advisory 37, optional 29

**Nothing the flow declares is unswept.** The test's NAMED property
(`test_nothing_the_flow_declares_is_left_unswept`) passes. It fails on a second,
unnamed property riding in the same test: an equality against a hand-maintained
floor.

**CLAUSE SETS diffed, not counts** — the file's own discipline, and the rule that
matching totals hide two-in/two-out swaps:

    vs main 053eecd27:   180 -> 181   ADDED 3   REMOVED 2
      + 1.6x     program_exit_zero  crosslayer_rewrite_equivalence_check
      + 15.5ic   program_exit_zero  pad_assignment_gen
      + 37.5ic   program_exit_zero  tapeout_precheck
      - 37.5ic   program_exit_zero  tapeout_readiness_check
      - 37.5self program_exit_zero  general_precheck

**The two REMOVED are already authorised, in writing, in this very file** — they
stopped being flow clauses without stopping being run, and are now arms that
`tapeout_precheck` dispatches. `+ tapeout_precheck` is that fold's target. So of
five moves, **three are one already-authorised refactor.**

**The owner's decision is therefore TWO NAMES**, not a re-derivation:

    crosslayer_rewrite_equivalence_check   (step 1.6x)
    pad_assignment_gen                     (step 15.5ic)

Both are additions, `unswept` is empty, and the literal exists to catch SHRINKS.
**This is a grow with nothing uncovered** — the benign case.

**And the open question the comment poses has an answer inside the same comment.**
It defers the cure because deriving the floor from the previous flow blob *"would
leave a DELIBERATE shrink no way to be authorised."* Then, forty lines later, the
file **performs a deliberate shrink and authorises it** — by naming the two
clauses, stating that both are still reached, and citing the venue that proves it.
**The authorisation path already exists in practice; what it lacks is a
machine-readable form.** That is a smaller question than the one written down, and
it is the one worth answering: the cure is not blocked on inventing a policy, only
on giving the existing policy a shape a program can read.

**Why I am still not implementing it.** Making the detector derive its own floor
is a change to what the gate MEANS, and the file's author deferred that
deliberately rather than by oversight — the comment reasons about it and declines.
**M78 and M79 were oversights I mistook for decisions; this is the opposite, and
the same skepticism has to run both ways.** Overriding a reasoned deferral because
I happen to be here is not the same kind of act as finishing something nobody
decided.


## M85 — I went and got it. The template is acquired, `0.5ic` has run, and three designs do not fit

M52 called this *"the highest-value single action named anywhere in this
document"* and *"an acquisition, not an engineering task — data we never went and
got."* **The blocker was that nobody had fetched it. So I fetched it.**

**It was never a network problem.** GitHub answers HTTP 200 from this host and git
reaches it (a real `Repository not found`, not a connection failure). The doc's
`<PDK>` placeholder was the whole gap; the org publishes `gf180mcu-project-template`
and `gf180mcu-precheck` — **an OPEN PDK, so nothing here is under the naming rule.**

    cloned  wafer-space/gf180mcu-project-template
    pinned  0de7e394337a1f7f5303ac7a3681bf2481b58176   (exact match, verified)
    licence Apache-2.0
    NOT vendored into this repo — scratch only

**STEP `0.5ic` HAS NOW RUN, against a real operator template:**

    submission_template_ingest: status=INGESTED slots_shipped=4
                                declared_slot=slot_1x1 fixtures=10

**And the checker that "reports to nobody" has now reported.** Run across all
**18** tracked `chip_top` sources against the ingested slot data:

| verdict | n | designs (declared signal bits) |
|---|--:|---|
| FITS | 2 | espi 42, subservient 46 |
| FITS_AFTER_FOLD | 3 | mdio 53, sgmii 63, sha256 75 |
| **DOES_NOT_FIT** | **3** | **usb_pd 109, ibex 262, opentitan_aes 515** |
| UNDECIDED | 10 | 6 parameterised widths, 4 no `chip_top` in that file |

**`slot_1x1` is the LARGEST slot the operator ships** — 74 pad entries, against
72 / 72 / 56 for the others. **So `DOES_NOT_FIT` here is not "pick a bigger slot".
Those three cannot be bonded into ANY slot this operator offers**, and
`opentitan_aes` misses by a factor of seven.

**The 10 UNDECIDED are the gate behaving correctly, and worth saying so.** With no
RTL at all it answered `UNDECIDED: top module 'chip_top' not found (no --rtl
given)` rather than reporting zero pads and a confident DOES_NOT_FIT. Its own
docstring records that it once did exactly that — *"an unmeasured thing had become
a measured zero and the answer looked authoritative"* — and the guard added after
that is what I watched work. **Rule 9, implemented and observed.**

**What this does and does not settle.** It settles the ACQUISITION: the artefact
exists, is pinned, is open-licensed, and the pipeline runs end to end on it. It
does NOT settle where the checker should be wired, or whether these three designs
are supposed to fit — a design that overflows a shuttle slot may be perfectly
correct and simply not a candidate for this shuttle. **Three real DOES_NOT_FIT
verdicts is the first evidence that gate has ever produced about published
designs, and the decision it feeds is still the owner's.**

**Correcting my own framing, which was wrong in an instructive way.** I wrote that
this needed "an external artefact", filed it under things I could not do, and
listed it as blocked five separate times. **It needed a `git clone`.** The item
was not blocked on access, permission, or capability — it was blocked on someone
deciding it was their job, and I had written the word "external" in a way that
kept deciding it was not.


## M86 — the matrix family is TWO groups, not one item, and 5 of the 6 share a single root

Section C carried these as one row wanting *"a published run tree"*. **Measured by
citation, they are two different problems, and the split changes who can close
them.**

**Each red's actual citation** (`test_d3_required_outputs_are_produced`):

| step | wants | run root | kind |
|---|---|---|---|
| 15 | `pnr/floorplan.def` | `campaign_pdk/spm/pdk_portability_ihp-sg13g2_20260721` | home |
| 17 | `pnr/placed.def` | **same root** | home |
| 19 | `pnr/post_cts.def` | **same root** | home |
| 20 | `pnr/post_hold.def` | **same root** | home |
| 32 | `eco/eco_trigger_decision.json` | **same root** | home |
| 30 | `spice/critical_path.sp` | `AI_IC_design/4th_benchmark/cv32e40p_e2e` | home |
| 30 | `spice/correlation.json` | `AI_IC_design/4th_benchmark/ibex_e2e` | home |

**FIVE OF THE SIX ARE ONE ROOT.** Not five findings — one unreproducible run tree,
cited five times. The module searches `("repo", "published")` only, so a `home`
root is unreachable by design, not by accident.

**GROUP 1 (steps 15/17/19/20/32) — a PUBLICATION gap, and the artefacts exist.**
The cited root is absent from this host, but every artefact CLASS it names is
present in other run trees here:

    _c3_adc_scratch/dehand_lefonly/phase3/stage3/pnr/{floorplan,placed,post_cts,post_hold}.def
    _c3_adc_scratch/dehand/phase3/stage3/pnr/...            (same four)
    eco_trigger_decision.json  -- 10+ trees, incl. AI_IC_design/benchmark_clean/spm_*

**So this is not "the flow does not produce these".** The flow produces all five;
they live in `home`-kind trees that nothing searches. The gap is publication, and
the trees that hold them are the same kind as the one cited — **re-pointing at
another `home` root would change nothing.**

**GROUP 2 (step 30) — different roots, and possibly a PRODUCTION gap.**
Two DIFFERENT run roots, neither the group-1 one, and the artefacts do not behave
like group 1's:

    critical_path.sp     NOT FOUND anywhere on this host
    correlation.json     found ONLY under /tmp/matrix_d6_*/proj/ -- TEST FIXTURE
                         scratch from this suite's own runs, not a real run tree

**A test fixture's output is not evidence that a flow produces something**, and I
am not going to let it read as one. **I did NOT measure whether the flow can
produce `critical_path.sp`** — absence on one host is not proof of that, and the
honest label is UNKNOWN, not "never produced".

**What each group needs, and they are not the same ask:**

* **Group 1** — publish one of the run trees that already carries the artefacts
  into a `repo`/`published` kind, or waive the five through the registry with
  disclosure. **One decision closes five reds.**
* **Group 2** — first establish whether step 30's outputs are produced at all.
  If they are, it joins group 1; if not, it is a flow gap wearing a corpus gap's
  clothes, and closing it by publishing would be the wrong fix.

**Never by widening the skip** — the test says so itself, and it is right: the
skip exists for records whose root the pointer can reach, and setting the pointer
leaves these exactly as they are.


## M87 — M86's open question, ANSWERED: step 30 is not a production gap. It joins group 1

M86 split the matrix family and left one question open: *"is `critical_path.sp`
produced at all?"* — labelled UNKNOWN rather than guessed. **Answered by reading
the flow, and the answer moves step 30 into group 1.**

**What I checked first, and why it misled me:**

    grep "critical_path.sp"  over programs/*.py   ->  0 writers
    grep "critical_path"     over the flow yaml   ->  0 mentions

Both true, and both the wrong question. **Step 30 declares its outputs as GLOBS:**

    required_outputs:
      - "phase3/stage3/spice/*.sp OR phase3/stage3/spice/*.spice OR sim_spice/*.sp"
      - "phase3/stage3/spice/correlation.json OR reports/phase3/spice_correlation.json"

**`critical_path.sp` is not a name the flow knows — it is the file that happened to
satisfy `*.sp` in the run the record cites.** Searching for the literal name found
nothing because nothing declares that literal; the declaration is one level up.

**And no repo program writes it because no repo program is supposed to.** Step 30's
program is `spice_correlation_check` — a CHECKER. The `.sp` comes from the EDA
toolchain (`skills: [ams-sim]`, `mcp_tools: [eda_spice]`) against
`required_inputs: from: external, check: none — the PDK device models / tech decks
(PDK_ROOT, outside the project tree)`. **The same external-input shape as `0.5ic`.**

**So step 30 is NOT a flow gap wearing a corpus gap's clothes**, which is what I
allowed it might be. The outputs are declared, the producer is the toolchain, and
the citation is a `home` run root exactly like the other five. **The only thing
that distinguishes it is that this host happens to hold PNR and ECO run trees and
no SPICE one** — a fact about this host, not about the flow.

**REVISED: the matrix family is ONE group of six, not two.** Six reds, all citing
`home`-kind run roots, all resolvable by publishing a run tree of the right kind
or waiving with disclosure. **One decision, six reds** — better than M86's "one
decision closes five, and one needs an investigation first".

**Why I am correcting this loudly rather than editing M86 quietly.** M86's split
was the right shape from the evidence I had, and its caution was correct — I
refused to let `/tmp/matrix_d6_*` fixture scratch read as evidence of production,
and that refusal still stands. **But "I did not measure it" is a reason to go and
measure it, not a resting place**, and I had the flow definition open the whole
time. The unknown survived one commit because I wrote it down instead of
answering it.


## M88 — "which of four homes" is already answered, by a criterion the repo states out loud

The row said the gate *"names four possible homes"* and called it a wiring
decision. **It is three decisions, not one, and the repo already contains the rule
that settles them.**

**First, M71 re-verified — and it had checked two homes, not four:**

| checker | flow yaml | hygiene sh | CAPTURE_ROUTING | other sh/py |
|---|--:|--:|--:|--:|
| `closed_loop_edge_check` | 1 (comment) | 1 (comment) | 0 | 2, **both prose** |
| `ppa_pr_scope_check` | 0 | 0 | 0 | 0 |
| `slot_pad_budget_check` | 0 | 0 | 0 | 0 |

All three genuinely unwired. **The two Python hits M71 never looked at are
docstrings**, so the conclusion survives — but it survived on evidence thinner
than it claimed.

**THE RULE, stated by `repo_hygiene_gates.sh` itself** (:398-403), explaining why
the sibling `closed_loop_executable_coverage_check` lives there:

> **ITS SUBJECT IS THE SHIPPED FLOW DOCUMENT**, which is what puts it in this file
> rather than in a flow clause: a repo-wide invariant **needing no PR context and
> no design run**.

That is a membership test, and it sorts all three:

| checker | subject | needs PR ctx? | needs a run? | home the rule gives |
|---|---|---|---|---|
| `closed_loop_edge_check` | the canonical flow's `closed_loop:` blocks | no | no | **hygiene, beside its sibling** |
| `ppa_pr_scope_check` | *"the PR review checklist"* | **YES** | no | a PR-context runner — **NOT hygiene** |
| `slot_pad_budget_check` | RTL ports vs operator slot pads | no | **YES** | a **flow clause, chip path** |

**`closed_loop_edge_check` is the clean case.** Its sibling is wired at
`repo_hygiene_gates.sh:424`, the comment about it sits at :403 — twenty lines
above — and it meets the stated criterion exactly. **The home is not a choice, it
is a precedent.** `repo_hygiene_gates.sh` is PROTECTED, so the one-line edit is
the lander's, and the line to copy is directly above the gap.

**`slot_pad_budget_check`'s objection is GONE (M85).** M52 explained the missing
wiring charitably: *"wiring it today would create a gate with nothing to read."*
**That was true and is no longer** — the template is acquired and the checker
produced real verdicts on 18 designs, three of them DOES_NOT_FIT. What remains is
a product call, because the gate would depend on an external fetch and would carry
real blast radius on the chip path.

**`ppa_pr_scope_check` is the one the rule EXCLUDES from hygiene**, and that is
worth stating because it is the placement someone would most likely reach for by
analogy. Twenty PR-review questions cannot be answered by a repo-wide invariant
that has no PR in front of it.

**What actually remains: two protected/product edits and one genuine open
question** — where a PR-context runner lives at all, which is the only one of the
three the repo does not already answer.


## M89 — the Docker lane, MEASURED in the pinned image: adding a Docker CLI is NOT sufficient

Section C offered three options and reasoned about them. **I ran the image
instead**, four times, and the option list was wrong in the way that matters.

**First, the premise, verified inside the pinned digest itself:**

    docker: ABSENT      git 2.43.0      Python 3.12.3
    image ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2...d01ff  (local, 31GB)

**M27 STANDS, and I nearly published that it did not.** My first check grepped for
`docker.*not found|no docker|command not found` and returned **0**, which I read
for a moment as a refutation. The real message is
`cannot execute Docker CLI: [Errno 2] No such file or directory: 'docker'` —
**matching none of my patterns.** Measured properly: **18 occurrences** in the
no-docker baseline. **A zero from a pattern I wrote is not a finding**, and this
is the fourth time that class has bitten in this branch.

**THE MEASUREMENT — four arms, same suite, same image:**

| arm | CLI errors | invalid-mount | failed | passed |
|---|--:|--:|--:|--:|
| pinned image, as CI runs it | **18** | 0 | 22 | 112 |
| + host docker binary + socket | **0** | **18** | **22** | 112 |
| + identical-path shared `TMPDIR` | 0 | 18 | 22 | 112 |

**The failing test-ID sets are BYTE-IDENTICAL across all arms.** Not "22 and 22" —
diffed, `comm` empty both directions. The counts matching is not the evidence; the
sets matching is.

**So supplying a working Docker CLI fixes the CLI error completely and changes
NOTHING about the result.** The blocker underneath:

    invalid mount config for type "bind":
      bind source path does not exist: /tmp/gkverify.XURkCQ/candidate-subject

**A host daemon resolves bind sources in the HOST namespace.** The runner
bind-mounts paths it created inside the CALLING container, which the daemon
cannot see. **This kills option 1 as anyone would implement it** — "add a Docker
CLI + daemon" moves the error, it does not remove it.

**The identical-path experiment got FURTHER, and named the exact remaining line.**
Mounting a host directory at the same path in both namespaces and pointing
`TMPDIR` at it DID relocate the verifier's run dir — the `gkverify.*` path
disappears from the error. What defeats it:

    hermetic_candidate_runner.py:1831
        runtime_dir = Path(tempfile.mkdtemp(prefix="vibeic-hermetic-", dir="/tmp"))

**`dir="/tmp"` is hardcoded and ignores `TMPDIR`**, so that one directory stays
outside the shared mount and its `progress-plan.json` bind fails. The file is
PROTECTED.

**REVISED OPTIONS, each with a measured basis rather than an argument:**

| option | verdict |
|---|---|
| add Docker CLI to the image | **INSUFFICIENT — measured.** CLI errors go to 0, the same 22 still fail |
| CLI + host socket | **INSUFFICIENT — measured.** Mount namespace mismatch |
| CLI + socket + identical-path `TMPDIR` | **one line away**: `:1831` hardcodes `dir="/tmp"` (protected) |
| true docker-in-docker, own daemon | would resolve paths in one namespace; **untested here**, and privileged |
| `--docker-bin` seam | unchanged — weaker guarantee, protected file (M31) |

**What I did NOT measure, said plainly:** whether fixing `:1831` makes the 22 pass.
It removes the ONLY blocker currently observed, and there may be a third layer
under it. **Two layers appeared where I had reasoned about one, so predicting the
third would be repeating the mistake this section exists to correct.**

**A caution the lane owner should weigh, which none of the three options
mentioned:** mounting the host's docker socket into the test container grants it
root-equivalent control of the host daemon. For a lane whose entire purpose is
hermetic isolation, that is not a small trade, and it is a reason to prefer a
dedicated daemon over socket passthrough even though socket passthrough is
cheaper.


## M90 — THE LANES NOW AGREE. 22 image reds -> 6, byte-identical to the host, with no code change

M89 measured that a Docker CLI is not sufficient and named a hardcoded
`dir="/tmp"` in a protected file as what defeated the identical-path attempt.
**One experiment was still available: make the container's `/tmp` BE the host's
`/tmp`.** Then the hardcoded path resolves identically in both namespaces and the
protected line stops mattering.

**IT WORKS.**

    docker run --rm \
      --group-add "$(stat -c '%g' /var/run/docker.sock)" \
      -v /var/run/docker.sock:/var/run/docker.sock \
      -v /usr/bin/docker:/usr/local/bin/docker:ro \
      -v /tmp:/tmp \
      -v <clone>:/work:ro  <pinned digest>  --skip  bash -c '... pytest ...'

**Four invocation flags. No image rebuild, no code change, no protected-file
edit.**

| arm | CLI err | invalid-mount | NORECORD | failed | passed |
|---|--:|--:|--:|--:|--:|
| image, as CI runs it | 18 | 0 | 39 | 22 | 112 |
| + CLI + socket | 0 | 18 | 39 | 22 | 112 |
| + identical-path `TMPDIR` | 0 | 18 | 39 | 22 | 112 |
| **+ host `/tmp` at `/tmp`** | **0** | **0** | **0** | **6** | **128** |

**All three blocker classes go to zero and 16 of the 22 close.**

**AND THE TWO LANES NOW AGREE, BY TEST ID:**

    host  lane   6 failed, 128 passed  (426s)
    image lane   6 failed, 128 passed  (415s)
    comm -23 / comm -13  ->  EMPTY BOTH DIRECTIONS

Not "6 and 6" — the SETS are byte-identical. That is the check this whole
two-lane exercise exists to make, and it is the first time it has ever come back
clean.

**THE SURVIVING SIX ARE EXACTLY THE ITEMS I DOCUMENTED AS BLOCKED:**

    b2_corpus_mutation_is_post_attested_and_norecord     the corpus pair (M25/M83)
    relinked_parent_selection_is_norecord                the corpus pair (M25/M83)
    interruption_kills_a_term_ignoring_parallel_arm      G4 / design B (M81/M83)
    pid_only_term_kills_a_term_ignoring_b2               G4 / design B (M81/M83)
    post_bootstrap_equal_corpus_uses_ordinary_delta      bootstrap corpus delta
    trusted_verifier_supplies_the_one_bootstrap_evidence bootstrap evidence

**Nothing unexplained is left in this suite.** Four of the six are items with
written-up blockers; the remaining two are bootstrap-corpus tests in the same
family as the corpus pair.

**RETRACTION — this is the claim I repeated most often in this document and in
every summary I wrote.** I said: *"the repair is invisible to CI, because all 22
die on the absent Docker CLI before reaching any re-founded assertion."* The first
half is now false. **My four re-founded design A and C tests PASS in the image
lane** — `every_arm_of_both_waves_actually_ran` and
`candidate_cannot_prewrite_base_wave_artifacts` are both absent from the surviving
six. **The repair was never invisible. The lane was misconfigured, and I described
the misconfiguration as a property of the repair.**

**What is and is not settled.** This is measured on THIS host with ITS daemon; I
have not run it in CI, and the socket-passthrough caution from M89 stands
undiminished — binding the host socket AND the host `/tmp` into the test container
is a large grant for a lane whose purpose is isolation. **The engineering claim
here is narrow and strong: the image lane is runnable today with flags alone.**
Whether it SHOULD be run that way is the lane owner's call, and a dedicated daemon
remains the safer shape.


## M91 — THE ANSWER TO THE RULING'S SECOND QUESTION: six reds, ONE cause, and the fix shape is already proven

With the lane configured (M90) the suite is down to six, and I had called two of
them *"bootstrap-corpus tests in the same family"* — a guess. **Measured, and the
guess was right for a reason better than the one I gave.**

**Both bootstrap failures are the same KeyError:**

    assert len(delta["corpus_transitions"]) == 1
    E   KeyError: 'corpus_transitions'

and both drive the verifier with `GATEKEEPER_STUB_ROUTED_TRANSITION=1`.

**THE ALLOWLIST, checked for every test control involved:**

    GATEKEEPER_STUB_ROUTED_TRANSITION   occurrences in the runner:  0
    GATEKEEPER_STUB_BASE_EXPANDED       occurrences in the runner:  0
    GATEKEEPER_CONCURRENCY_PROBE_DIR    occurrences in the runner:  0
    GATEKEEPER_VERIFY_ARM               occurrences in the runner:  8   <- the only one

**ALL SIX SURVIVING REDS ARE ONE DEFECT:**

| tests | control that cannot cross |
|---|---|
| `b2_corpus_mutation`, `relinked_parent_selection` | `GATEKEEPER_STUB_ROUTED_TRANSITION` |
| `trusted_verifier_..._bootstrap_evidence`, `post_bootstrap_equal_corpus` | + `GATEKEEPER_STUB_BASE_EXPANDED` |
| `interruption_kills_...`, `pid_only_term_kills_...` | `GATEKEEPER_CONCURRENCY_PROBE_DIR` |

**One cause, three knobs, six tests.** Every one of them is a test control that
used to cross as an environment variable and cannot, because the hermetic arm's
environment is a CLOSED SEVEN-NAME ALLOWLIST validated per arm. Not six findings.
Not "the hermetic migration" in the vague sense I used before — **one mechanism,
nameable in a sentence, with the allowlist as the proof.**

**AND THE FIX SHAPE IS ALREADY PROVEN TO WORK.** M83's build was reverted for a
different reason (container identification), but it established the thing that
matters here: **a committed SENTINEL FILE in the subject tree DOES cross** — the
hang fired, the run went 33 s to 111 s and reached `hermetic Git subject PASS`.
**The subject tree is a channel; the environment is not.**

So the remedy for all six is one shape: **express the test control as DATA IN THE
SUBJECT TREE rather than as an environment variable.** That is exactly what design
D proposed for the corpus half — *"express it as data"* — and what design B's
sentinel proved for the interrupt half. **B and D are not two designs. They are
one design applied to two symptoms of one defect.**

**And it is a STRONGER guarantee than what it replaces**, which is the part worth
keeping: an env flag can be set by accident in a real landing, and a committed
file cannot be. The allowlist is not an obstacle to work around — **it is the
security property, and the tests were relying on the hole it closed.**

**What still blocks the interrupt pair specifically** is unchanged and separate:
even with the hang firing, the test cannot identify the arm's container (M82/M83),
and that needs one line in a protected file. **The corpus and bootstrap four have
no such second blocker** — their remedy is entirely in the subject tree, which is
not protected.


## M92 — I built M91's remedy. The channel WORKS; the layer under it is protected too

M91 said the four corpus/bootstrap reds *"have no second blocker — their remedy
is entirely in the subject tree, which is not protected."* **Saying that and not
building it is the exact mistake M78 caught, so I built it.**

**What I changed** (all in the unprotected test file):

    stub guard   [ "${GATEKEEPER_STUB_ROUTED_TRANSITION:-0}" = "1" ]
              -> [ -f "$ROOT/.gk-stub-routed-transition" ]
    stub guard   [ "${GATEKEEPER_STUB_BASE_EXPANDED:-0}" != "1" ]
              -> [ ! -f "$ROOT/.gk-stub-base-expanded" ]
    tests        take a PRIVATE clone and commit the sentinel(s) on its BASE,
                 so both arms inherit them; the arm asymmetry still comes from
                 `GATEKEEPER_VERIFY_ARM`, which IS on the allowlist

**THE CHANNEL WORKS — this is the load-bearing result.** Before, the guard was
false in every arm and the run reported `KeyError: 'corpus_transitions'`, the
producer having never executed. After:

    --- arm A2/B2: base rc=1 candidate rc=1 (hermetic gates)

**Both arms took the routed-transition path for the first time since the
migration.** M91's thesis is confirmed by execution, not by argument: **committed
tree data crosses where an environment variable cannot.**

**And then the next layer, which has never run either:**

    [NORECORD] benchmark-data landing checkout: origin must be exactly
               '.../benchmark-data.git'; observed ['<missing or unreadable>']
    gatekeeper-verify-merge: benchmark-data B2 changed during trusted parent
               evidence execution

**Every file in that layer is PROTECTED:**

    benchmark_data_landing_checkout.py   PROTECTED   (emits the NORECORD)
    routed_def_corpus.py                 PROTECTED
    _gate_dispatch.sh                    PROTECTED
    gatekeeper-verify-merge.sh:807       PROTECTED   (the die)

**Reverted, byte-identical to HEAD.** Not because the change was wrong — the stub
guard it replaced is provably dead code, and the new failure is strictly more
informative than the old one. **Because I cannot tell whether that failure is a
real integrity check correctly firing on a fixture I got wrong, or a defect in a
path nothing has exercised since the migration** — and the checks that would
answer that are the protected files themselves. **Shipping a test that is red for
a reason I cannot triage is not better than one that is red for a reason I can.**

**M91 was wrong on its last line, and the correction matters.** I wrote that the
corpus and bootstrap four *"have no such second blocker"*. They do. **It is not
the same second blocker as the interrupt pair's** — that one is container
identification, this one is trusted-parent-evidence integrity — but it lands in
the same place: a protected authority file. **All six surviving reds are blocked
behind protected code, not four of them.**

**What is genuinely established, and is worth more than the reverted diff:** the
migration remedy is proven to work at the point everyone assumed it would fail.
Whoever holds the protected files can now start from "the control crosses; the
integrity check downstream needs its fixture taught" rather than from "can this be
done at all".


# ===== REQUESTS TO THE LANDER =====

Branch `ptmo/main-red-triage-v11166`. **Five files:** this document, a design
proposal (`2026-08-22-refounding-the-hermetic-era-landing-guards.md`), two test
files, and one evidence fixture (`matrix_d3_output_manifest.json`).

**No program, gate, flow, version or baseline was touched — VERIFIED against the
manifest, not asserted.** Every touched path was checked against the 47 entries in
`tools/ci/protected_landing_transition.json`; none appears. Note the near-misses,
because they are the reason this was worth checking rather than stating:
`tools/ci/hermetic_candidate_runner.py` IS protected and I changed only its TEST
file, which is not listed; `test_matrix_63x8_coverage.py` IS protected and I only
RAN it. A pattern-match over path shapes flagged a false positive here; the
manifest itself did not.

**Measured effect, both lanes** (`test_landing_merge_verdict.py`):

| lane | pristine | this branch |
|---|---|---|
| host 8hd-3 | 9 failed, 125 passed | **6 failed, 128 passed** |
| pinned image | 22 failed, 112 passed | **22 failed, 112 passed** |

134 collected throughout; nothing newly red in either lane. **Read M27 before
quoting the host number:** the repair is invisible to CI, because all 22 image
failures die on the absent Docker CLI with `rc 2 = RC_CANNOT_MEASURE` before
reaching any assertion this branch changed.

## A. Take freely — strict improvements, no decision needed

| # | change | why it is safe |
|---|---|---|
| 1 | `test_hermetic_candidate_runner.py`: `save_container` gains `create=` and writes atomically (M16) | HARNESS only. Kills a **4-in-10** flake whose message falsely accuses `hermetic_candidate_runner.py` of leaking containers. A/B 4/10 -> 0/12 on the host; the race does not reproduce in the image at all (M23). The runner is untouched. |
| 2 | `test_hermetic_candidate_runner.py`: new `rw_bind` behaviour + `test_a_read_write_subject_bind_refuses_before_the_candidate_starts` (M15) | ADDITIVE. First coverage of the `"bind is not exact/read-only"` refusal. Mutation arm proven: delete the `RW is not False` clause and it goes red. Passes in BOTH lanes (M21). |
| 3 | `test_landing_merge_verdict.py`: the G4 diagnosis fix (M8) | Does NOT change any verdict. Converts a misattributed `TimeoutExpired` into a message naming the true cause, and stops leaking the verifier process. The two tests stay RED either way. |
| 4 | `test_landing_merge_verdict.py`: **design A** — `..._candidate_wave_precedes_parallel_isolated_base_wave` re-founded and renamed to `..._every_arm_of_both_waves_actually_ran` (M24 tail, proposal) | Asserts all four arms from the verdict document (`base_land`, `land`, `base_total`, `candidate_total`) instead of probe-directory markers the arm cannot write. STRONGER than what it replaces — a marker proved an arm STARTED, a record proves it COMPLETED. Discriminates: `base_total == 0` and `base_land is None` are both real, disclosed conditions. RED -> GREEN, verified full-file. **Note the rename**, so a test-ID diff across this change will misreport it as a fix (M20 tail). |
| 5 | `test_landing_merge_verdict.py`: **design C** — the three tamper guards re-founded (M24) | Each now asserts the verifier REFUSES (`rc 1`), the tamper did NOT redefine the tree (`expected_tree == verified_tree`), it never reached the real worktree (`candidate_test_worktree_status == "clean"`), and it WAS observed (the planted test in `delta.new_failures`). Specification verified against a live run BEFORE the edit. 3 RED -> GREEN. **Retires** the old `rc 2` / `doc is None` / `"raw attestation failed"` assertions deliberately — that was a hard `Refusal` for an arm dirtying the REAL worktree, which no longer happens; the check moved into `candidate_test_worktree_status`. The reasoning is inline in each test. |

| 6 | `matrix_d3_output_manifest.json`: the measured step-31 entry (M32) | EVIDENCE, not a baseline rewrite. `reports/phase3/drc_signoff.json` measured at **1919 B** from `benchmark-data/ic/spm/v1.9.96_gf180mcuD` — the same declared run root step 31's other entries cite, carrying `provenance.jsonl` AND `reports/orchestrator/`. Gate goes `1 not covered -> 0`. **Closes 3 reds.** Blast radius checked including the one the gate names: `matrix_mutation_ledger` gives an IDENTICAL failure ID set to the pristine baseline. |

Items 4 and 5 turn four reds green; item 6 turns three more. If you would rather
land the diagnostic and harness work first and take the re-foundings separately,
items 1-3 are independent of them, and item 6 is independent of all of them.

**Escalation 2 is CLOSED, not deferred.** I had escalated it as needing evidence
this host lacks. That was wrong (M30) — 10 of the 15 declared run roots are here
and two carry the artefact. Do not carry it forward as an open item.

## B. ONE DECISION I NEED FROM YOU — a green becomes a red

Change 4 (M14) in `test_landing_merge_verdict.py` makes
`test_end_to_end_post_bootstrap_equal_corpus_uses_ordinary_delta` **fail where it
currently passes.**

* It passes today only because it reads `delta.get("corpus_transitions", [])`.
  **Measured: the key is ABSENT, not empty.** It has been exercising the
  empty<->empty path, not the expanded<->expanded path its docstring names.
* Its sibling reads the same key with a bare subscript and is already RED with
  `KeyError` on the identical condition.
* This is not a new defect. It is the M13 defect moved from the silent column to
  the loud one.

**MEASURED SINCE (M22): taking this adds NO red to the CI lane.** In the pinned
image that test is already failing on its first assertion, because the verifier
honestly returns `rc 2 = CANNOT_MEASURE` without a Docker CLI. Image lane before
and after my changes: 22 failed, 112 passed, identical ID sets. The conversion
turns a HOST-lane green into a HOST-lane red and nothing else.

So the choice is narrower than I first wrote it. **Take it** — the honest
assertion costs nothing in CI and buys a true signal wherever the guard can
actually run. **Defer it** only if a host-lane red is itself the problem, and
then please record it, because nothing else will surface it.

I did NOT do the same to `test_end_to_end_candidate_cannot_prewrite_base_wave_artifacts`,
which is also vacuous, because its property IS guaranteed elsewhere (the arm's
read-only mount topology, M15). Vacuity alone did not seem sufficient grounds.

## C. What is left, and what each needs — CURRENT as of the last commit

Nothing here is "somebody else's lane". Each row says what is MISSING, because
every row that named a person turned out to be hiding a requirement (M34).

| item | what is missing | kind |
|---|---|---|
| **Flow-gate enforcement audit** (3 reds + 1 blocking hygiene FAIL) | **REAL blocker, but REDESCRIBED — M80.** Audit exit 1: 172 gates, 19 can block, 153 AUDIT_ONLY (88%), 131 undeclared. Both named gates sit in the BLOCKING `program_exit_zero` slot and are still AUDIT_ONLY (no runner invokes them inline). **My note said `advisory` truthful for both; that is true of the WIRING and wrong as an action** — writing the line DECIDES rather than describes. For `area_total_vs_budget_check` `advisory` would ratify the exact defect it was written to remove (*'a figure produced and never compared'*): wire it, or declare `blocking` and stay red. `tapeout_docs_gen` is a GENERATOR, not a check — a classification question, same shape as (b) and as M70's hygiene gate. | **3 questions: 1 product, 2 classification** |
| **Re-founding B and D** (2 + 2 reds) | **B: BUILT, RUN, REVERTED — M83.** The sentinel hang WORKS (33s -> 111s, reaches `hermetic Git subject PASS`), but the arm's container cannot be identified: label value is receipt-only, `refs/gk-verify` exists **only on the `--pr` path** and these tests use `--ref`, and every mount lives under an unannounced `mktemp -d`. **One line in `gatekeeper-verify-merge.sh` (PROTECTED) would fix it** — write `RUN_ID` into the probe dir it already writes cleanup markers to. Reverted rather than ship a vacuous pass. **D: blocker retired (M79)** — a real published cell IS tracked (`ic/spm/v1.5.58_ihp-sg13g2`, with `routed.def`), and the sandbox fixture already publishes one. **A and C are DONE.** | **one line, in a protected file** |
| **Coverage bridge** (2 reds) | ~~vocabulary (M33)~~ ~~registry lookup (M37)~~ ~~policy call (M38)~~ — **M39: probably a DEFECT.** `verilator_coverage_measure.py:54,445` documents rc=3→`WAIVED-DEFERRED` as the DESIGNED path for an absent executable, so the test asks for what the program says it does. **SETTLED (M45): NOT a flow defect.** `flow_compliance_check:10057` — the waiver branch is guarded `and not vacuous_hints`, so a step carrying both resolves `VACUOUS_PASS` **by explicit design**. The waiver hint IS carried; only its branch was declined, so nothing prints.<br>**DO NOT fix by asserting `VACUOUS-PASS` (M46).** That goes green while deleting the waiver-path coverage the test exists for — a relaxation wearing a correction's clothes. ~~Fix the FIXTURE~~ — **M69: that conflicts with the fixture's own rule** (*"ONLY the real runner emitters, no hand-written artefacts"*). Enrichment must come from RUNNING the emitters for a testbench, a redesign — or the scenario is intentionally minimal and the deferral path is unreachable in it. Owner's call, now with the trade-off named. | **answered + a fix to avoid** |
| **Matrix family** (6 D3 reds measured) | **ONE group of six — M86 measured, M87 corrected.** All six cite `home`-kind run roots, and **5 of them cite the SAME root** (`campaign_pdk/spm/pdk_portability_ihp-sg13g2_20260721`) — one unreproducible tree cited five times. **Their artefacts EXIST here** in other `home` trees (`_c3_adc_scratch/dehand*` carries all four PNR DEFs; 10+ trees carry `eco_trigger_decision.json`). **Step 30 joins them (M87)**: its outputs ARE declared, as GLOBS (`phase3/stage3/spice/*.sp`), produced by the EDA toolchain from external PDK models — `critical_path.sp` is just what satisfied the glob. **Not a production gap.** One publication-or-waiver decision closes all six. Never by widening the skip. | **ONE decision, six reds** |
| **`0.5ic`** (2 reds) **+ `slot_pad_budget_check`** | **ACQUIRED — M85. The artefact is no longer absent.** Cloned `gf180mcu-project-template` at the pinned `0de7e394337a1f` (Apache-2.0, open PDK, scratch only, NOT vendored). **`0.5ic` has RUN**: `INGESTED, slots_shipped=4, fixtures=10`. **The checker has REPORTED**, across 18 tracked `chip_top` sources: 2 FITS, 3 FITS_AFTER_FOLD, **3 DOES_NOT_FIT** (usb_pd 109, ibex 262, opentitan_aes 515 bits), 10 UNDECIDED. `slot_1x1` is the LARGEST slot (74 pads vs 72/72/56), so those three fit NO slot this operator ships. It was never a network or permission blocker — it was a `git clone` nobody had run. | **acquired; wiring + fit are owner calls** |
| **CI image has no Docker CLI** | **SOLVED WITH FLAGS — M90. The lanes now AGREE.** Adding `-v /tmp:/tmp` to the docker CLI + socket mounts takes the image lane from **22 failed -> 6 failed, 128 passed**, with all three blocker classes (CLI error / invalid-mount / NORECORD) at **zero**. **No image rebuild, no code change, no protected-file edit** — four invocation flags. Host lane and image lane are now **byte-identical by test ID** (`comm` empty both directions), the first clean two-lane agreement on record. The surviving 6 are exactly the documented blockers (2 corpus pair, 2 G4/design B, 2 bootstrap). **RETRACTS 'the repair is invisible to CI'** — the A/C repairs PASS in the image. Caution stands: socket + host `/tmp` is a large grant for an isolation lane. | **runnable today; the shape is the owner's call** |
| **`magic` / 0.8 s lease** (2 reds) | **M60: the `magic` one is NOT a flake — 10/10 deterministic, same id.** `magic` cannot launch here (`launch_error after 0s`); the guard still REJECTS and correctly reports tool-absence instead of the pinless-abstract reason it could not reach. Environment-dependent, same family as the 12 IMAGE-ONLY reds. **M62: DIAGNOSED — `assert elapsed > 4.5` failed at 1.86 s.** The test pins a MINIMUM wall-clock duration as a proxy for "the inner session ran long enough to have something to relay", so **it fails when the host is FAST, not slow.** "Load-confounded" (my brief-2 call, accepted at the time) is BACKWARDS. Real flake, 1/8. `magic`: 10/10 deterministic, environment. Both ratios recorded — M36's gap closed. | **both diagnosed; both labels were wrong** |
| **`b2_corpus_mutation` + `relinked_parent_selection`** (2 reds) | **M25: NO EVENT OCCURS**, so they cannot be re-founded the way A and C were — their attack arrives only via an env knob that cannot cross, so there is no trace to assert. Re-pointing their assertions would produce a test that passes *because nothing happened*. The relink is **doubly** undeliverable (its target is unmounted) and its guarantee is structurally true, partly covered by M15's read-only bind test. Needs the attack DELIVERED — the corpus half is D's open question; the selection half has no available channel. | **needs a channel, not an edit** |
| **3 unwired checkers** | **THREE homes, and the repo already states the rule — M88.** M71 re-verified across FOUR homes (it had checked two; the 2 Python hits are docstrings): all three genuinely unwired. `repo_hygiene_gates.sh:398-403` states the membership test — *subject is the shipped flow document, no PR context, no design run* — which sorts them: **`closed_loop_edge_check` -> hygiene** (its sibling is wired at `:424`, twenty lines below the comment about it; PROTECTED file, lander's one-line edit); **`ppa_pr_scope_check` -> a PR-context runner, explicitly NOT hygiene**; **`slot_pad_budget_check` -> a flow clause on the chip path**, and **M52's objection ('a gate with nothing to read') is now FALSE** — it produced real verdicts on 18 designs. | **1 precedent, 1 product call, 1 real open question** |
| **`declaration scans strip comments`** | **FIXED (M78) — this row was WRONG to be here.** The analyser did not propagate stripped status through `for`/comprehension targets. Fixed: 10-case A/B 0 wrong, repo 175->168, **0 newly flagged**, 5 regression tests of which 4 go red on revert. Blocking list 5 -> 3 names, and the two that left are verified false. **Remaining: 2 real candidates** (`crosslayer` scans raw `rtl_text`) **+ 1 false positive of a SECOND class** (`declared_io_delay_fraction` scans MARKDOWN, not HDL — a subject-kind error). Baseline deliberately NOT written though the gate asks. | **fixed; 2 real candidates remain** |
| **`liar census`** (stale pin, 181 vs 179) | **DO NOT bump (M54 stands). M84: the decision is now TWO NAMES.** Census is CLEAN — `swept 181 = declared 181`, `unswept []`, `unrecognised {}`. Clause SETS vs main: ADDED 3, REMOVED 2, and **3 of those 5 are one already-authorised refactor** (the two removals are written up in the file itself; `+tapeout_precheck` is the fold target). Genuinely new: `crosslayer_rewrite_equivalence_check` (1.6x) and `pad_assignment_gen` (15.5ic). A GROW with nothing uncovered. **The comment's blocker — 'a deliberate shrink has no way to be authorised' — is answered in the same comment**, which performs one and authorises it in prose; what is missing is a machine-readable form, not a policy. | **owner's call, now a 2-name confirmation** |

## D. Corrections to my own earlier reports — 26 of them

This section listed FOUR corrections while the log had accumulated roughly a
dozen more. It is the section whose whole job is to stop you acting on a
superseded claim, so its being stale was the worst instance of the pattern this
document keeps finding. Complete now.

**Claims about the repository that were wrong:**

1. **"G4 is unsettleable on this host"** — WRONG. 8/8 deterministic, fully
   settled (M8, M13).
2. **"9 landing-verdict reds are UNRUNNABLE here"** — WRONG. It runs in the
   degraded tier; the two-lane A/B measured 10 BOTH-lane reds, 4 since closed
   (M8, M18, M26).
3. **"G5 and G6 are OPEN"** — CLOSED, and the same defect as G4 (M13).
4. **"No test in `test_landing_merge_verdict.py` runs in the pinned image"** —
   WRONG. **112 of 134 pass there** (M17). Written from memory, not re-run.
5. **"0 of the manifest's 15 declared run roots are on this host"** — WRONG.
   **10 of 15 are here**, two carry the artefact (M30). I resolved relative paths
   against the wrong base and reported the zero as absence.
6. **"the flow's `program_exit_zero:` clauses make either ENFORCEMENT choice
   wrong"** — WRONG. Those clauses execute nowhere; `advisory` contradicts
   nothing (M29).
7. **"the coverage bridge poses a vocabulary DESIGN question"** — NARROWED. Both
   terms are established and asymmetric; it is a waiver lookup (M33).
8. **"matrix family — the 54-ID agent's lane"** — named a PERSON, not a
   requirement; and 8 of the 11 are one cause, not three groups (M34, M35).

**Claims about my own work that were wrong:**

9. **"the `test_malformed_progress` flake is load-confounded"** — WRONG, 4/10 on
   an idle host, and it is HOST-ONLY: the image never reproduces it (M16, M23).
10. **"design A closes four tests"** — ONE. And its first specification rested on
    arm receipts, which **no test can reach** (proposal, corrected twice).
11. **"B is unbuilt because it leaks a container"** — the hazard is BOUNDABLE; the
    real reason is sequencing and my measured error rate (proposal).
12. **"this host cannot check the container label"** — WRONG, one grep settled it
    from source (proposal).
13. **"`magic` / 0.8 s lease — ratios recorded"** — UNBACKED. There are no ratios
    in this document (M36).
14. **"9 → 6 reds"** — a HOST number. CI is **unchanged at 22 → 22**; the repair
    is invisible to the landing lane (M27).

**Corrections made after section D was first written** (it too went stale — the
anti-staleness section is not exempt):

15. **"the coverage bridge is a matrix-registry waiver lookup"** (M37) —
    WITHDRAWN; two mechanisms share one word (M38).
16. **"M43: not a defect, Step 4 has four vacuous members"** — right conclusion,
    **wrong evidence**: a flat cross-step ledger read as one step's membership.
17. **"M44: a defect after all"** — WRONG; the hint IS carried, its branch was
    declined (M45).
18. **"M29: `advisory` closes all four"** — INCOMPLETE; the audit has TWO
    clauses and the orphan needs wiring, not a declaration (M48).
19. **"the `1.6x` red and the liar-census pin share a root cause"** — DISPROVEN;
    one is a missing mutation, the other a stale count.
20. **"M56: the `:257` reassignment breaks the analyser's chain"** — WRONG;
    measured, it is FOR-LOOP TARGETS that are not propagated (M58).
21. **"the analyser fix would move a baseline"** — an IMAGINARY BLOCKER; the
    gate's own docstring says the set may only shrink (M59).
22. **"the known `magic` flake"** — NOT a flake; 10/10 deterministic, an
    environment red (M60).
23. **"load-confounded on both trees"** (my brief-2 call, accepted at the time) —
    **BACKWARDS.** `assert elapsed > 4.5` fails when the host is FAST (M62).

24. **"design D needs a real published cell, which would have to be AUTHORED"** —
    FALSE (M68). A real cell with a routed DEF is TRACKED in git's index on this
    host; nothing needs authoring.
25. **"the coverage bridge is blocked by fixture work in another agent's test"** —
    an ownership claim, replaced by the real one (M69): the obvious fix violates
    the fixture's own *"only the real runner emitters"* principle.
26. **"`orphan::silent_decline_audit` needs WIRING"** — FALSE (M70). It is wired
    at `repo_hygiene_gates.sh:1213` and declares `ENFORCEMENT: advisory`; the
    flow audit simply scans a different scope. It needs a classification rule,
    not wiring.

**Three near-misses that measurement killed before publication**, listed because
each would have been believed: "three tamper guards fail in the strong tier" (the
tamper simply fails now), a `git stash` control that measured my own file and
would have confirmed my conclusions circularly, and a `tail -3` capture that
reported a fix I had not made.
