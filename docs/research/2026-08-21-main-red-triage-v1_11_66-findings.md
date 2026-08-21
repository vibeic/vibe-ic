# findings — agent `ptmo`, RUN 8: v1.11.62, and the ownership question

host 8hd-3 · 2026-08-21

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

**A/B, same tree, only `save_container` differing** (both lanes carry the M15
`rw_bind` test, so both are 17 tests):

| lane | full-file runs with >=1 failure |
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
| 11 | matrix family | the 54-ID agent's lane |
| 2 | coverage bridge | **jmain-green's 38** (confirmed against the split), red since v1.11.18, and it poses a verdict-vocabulary DESIGN question: should "oracle PASS with no coverage measurement" be `VACUOUS-PASS` or `WAIVED-DEFERRED`? Same class as the flow-gate intent call — not mine to guess |
| 3 | flow-gate enforcement audit | a POLICY call: two gates must declare `ENFORCEMENT: blocking\|advisory`, and the flow's `program_exit_zero` clauses make either choice wrong without a wiring change |
| 2 | manifest parity | EVIDENCE this host lacks: 0 of the manifest's 15 declared run roots are present |
| 9 | landing-verdict guard | the guard is UNRUNNABLE here — needs docker CLI + git >= 2.38 + a non-`$HOME` subject in ONE environment |
| 2 | `magic` flake, 0.8 s lease family | characterised, ratios recorded |

**Nothing is left in the "red, cause unknown" state**, which was the state the
whole 92 started in.

## The instrument, hardened

`SCRATCH_ROOT_RULE.md` written and the three runners annotated. Two clauses,
each bought with a false finding: the scratch root must be SHORT (a long path
fills fixed-size evidence windows) and OUTSIDE `$HOME` (the hermetic runner
refuses a subject under it). `/tmp/ps` satisfies both; the descriptive path I
used for most of this job satisfies neither.

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


# ===== REQUESTS TO THE LANDER =====

Branch `ptmo/main-red-triage-v11166`. Three files: this document, plus two test
files. **No program, no gate, no flow, no version, no baseline was touched.**

## A. Take freely — strict improvements, no decision needed

| # | change | why it is safe |
|---|---|---|
| 1 | `test_hermetic_candidate_runner.py`: `save_container` gains `create=` and writes atomically (M16) | HARNESS only. Kills a **4-in-10** flake whose message falsely accuses `hermetic_candidate_runner.py` of leaking containers. A/B 4/10 -> 0/12. The runner is untouched. |
| 2 | `test_hermetic_candidate_runner.py`: new `rw_bind` behaviour + `test_a_read_write_subject_bind_refuses_before_the_candidate_starts` (M15) | ADDITIVE. First coverage of the `"bind is not exact/read-only"` refusal. Mutation arm proven: delete the `RW is not False` clause and it goes red. |
| 3 | `test_landing_merge_verdict.py`: the G4 diagnosis fix (M8) | Does NOT change any verdict. Converts a misattributed `TimeoutExpired` into a message naming the true cause, and stops leaking the verifier process. The two tests stay RED either way. |

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

**Take it** if you want the landing gate to stop believing a green it cannot
fail. **Defer it** if adding a red now is worse for you than a known-false green
— but then please record it, because nothing else will surface it.

I did NOT do the same to `test_end_to_end_candidate_cannot_prewrite_base_wave_artifacts`,
which is also vacuous, because its property IS guaranteed elsewhere (the arm's
read-only mount topology, M15). Vacuity alone did not seem sufficient grounds.

## C. Three things I could not settle, and what each needs

| item | what is missing | who can supply it |
|---|---|---|
| Flow-gate enforcement audit (3 reds + 1 blocking hygiene FAIL) | `area_total_vs_budget_check` and `tapeout_docs_gen` must declare `ENFORCEMENT: blocking\|advisory`, but their `program_exit_zero:` clauses (flow lines 1847, 5788) make either choice wrong without a wiring change | a POLICY call, not a measurement |
| `flow_manifest_declaration_parity` (2 reds) | a run root from the manifest's declared 15; **0 of the 15 are on this host** | anyone with a real run root |
| Re-founding the 10 knob-dependent tests (M13) | six test-only env knobs cannot cross the hermetic arm boundary, and `os.kill(arm_pid, 0)` is a host-namespace assertion about a container-namespace process | a POLICY call: re-found on `/evidence` + arm receipts + `landing_completion_record.py`, or punch a test-only hole in `_LAND_REVIEWED_ENV_NAMES` plus a writable mount. I recommend the former and did neither. |

## D. Corrections to my own earlier reports, so you do not act on the old ones

1. **"G4 is unsettleable on this host"** — WRONG. It is 8/8 deterministic and
   fully settled (M8, M13).
2. **"9 landing-verdict reds are UNRUNNABLE here"** — at least 2 are runnable;
   the verifier completes in the degraded rebase-replay tier. The docker/git-2.38
   explanation does not cover G4.
3. **"G5 and G6 are OPEN"** — both CLOSED, and they are the same defect as G4,
   not three findings (M13).
4. **The `test_malformed_progress` flake is "load-confounded"** — WRONG, and I
   nearly published it. It reproduces 4/10 on an idle host (M16).
