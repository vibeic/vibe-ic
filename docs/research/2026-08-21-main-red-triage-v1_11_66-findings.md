# findings — agent `ptmo`: the v1.11.66 red triage, and what auditing my own claims found

host 8hd-3 · started 2026-08-21 · **32 sections; read this header before M0**

**SCOPE HAS GROWN PAST THE TITLE IT STARTED WITH.** This began as RUN 8 —
"v1.11.62 and the ownership question" — and M0 below still states that premise,
correctly, as the premise OF RUN 8. The document now runs to M36 and the branch
is cut from `6d06ba664` ("final disposition at v1.11.66"). **M0 is history, not
the current base.**

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
* **seven instrument defects catalogued**, of which THREE reported my own work as
  more successful than it was.
* **nine retractions of published findings**, plus three near-misses that
  measurement killed before publication.

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
| 1 | `test_flow_compliance_check_gate` | `the finding itself is missing from the evidence snippet` |
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

### The seven instrument defects, consolidated

That section covered one rule. By the end there were seven, and **every one of them
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
| **Flow-gate enforcement audit** (3 reds + 1 blocking hygiene FAIL) | `area_total_vs_budget_check` and `tapeout_docs_gen` must declare `ENFORCEMENT`. `advisory` is TRUTHFUL today and closes all four (M29 — the `program_exit_zero:` clauses execute nowhere). The only question is whether these two SHOULD be able to stop a step. | **policy, one line each** |
| **Re-founding B and D** (2 + 2 reds) | B: specified, both channels confirmed, safety bound documented — unbuilt on sequencing, not hazard. D: mechanism fully described; needs a real published cell, and authoring one to turn a test green is the move this campaign forbids. **A and C are DONE** (4 reds closed). | **decision + evidence** |
| **Coverage bridge** (2 reds) | ~~vocabulary (M33)~~ ~~registry lookup (M37)~~ ~~policy call (M38)~~ — **M39: probably a DEFECT.** `verilator_coverage_measure.py:54,445` documents rc=3→`WAIVED-DEFERRED` as the DESIGNED path for an absent executable, so the test asks for what the program says it does. `:420-421` requires **rc=3 AND the `PASS_WITH_WAIVERS` sentinel**; the hypothesis is one half is missing. **Not verified — a place to look, not a finding.** | **likely defect** |
| **Matrix family** (8 of 11, one cause) | a published run tree carrying `floorplan/placed/post_cts/post_hold.def`, `eco_trigger_decision.json` and `critical_path.sp` — or a registry waiver with disclosure. Closing this layer should close the census layer with it (M34, M35). | **evidence or owner waiver** |
| **`0.5ic`** (2 reds) | the shuttle operator's published project template — `from: external, check: none`. *"It is data we never went and got"* (M36). | **external artefact** |
| **CI image has no Docker CLI** (12 IMAGE-ONLY reds + 1 skipped cell) | a Docker CLI + daemon, OR the third option: thread `--docker-bin` through the verifier so these drive a fake docker as `test_hermetic_candidate_runner.py` already does — which trades a strong unrunnable guarantee for a weaker runnable one AND opens a seam on a protected path (M31). | **lane decision, 3 options** |
| **`magic` / 0.8 s lease** (2 reds) | the ratios this document claims to record and does not (M36). Deliberately not re-measured — load-sensitive, shared host. | **an honest gap** |

## D. Corrections to my own earlier reports — the complete list

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

**Three near-misses that measurement killed before publication**, listed because
each would have been believed: "three tamper guards fail in the strong tier" (the
tamper simply fails now), a `git stash` control that measured my own file and
would have confirmed my conclusions circularly, and a `tail -3` capture that
reported a fix I had not made.
