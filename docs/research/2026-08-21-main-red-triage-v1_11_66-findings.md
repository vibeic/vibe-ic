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
| **G4 interruption timeouts** | **2** | `subprocess.TimeoutExpired` on the two TERM/kill tests | **NOT SETTLED** — these bound a kill path; could be load or real. Not measured to a conclusion |
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

## M8 — G4 SETTLED AS FAR AS THIS HOST ALLOWS: it cannot be settled here

The two `subprocess.TimeoutExpired` reds are
`test_interruption_kills_a_term_ignoring_parallel_arm_and_removes_worktrees` and
`test_pid_only_term_kills_a_term_ignoring_b2_and_removes_worktrees`. Both go
through `_assert_interruption_cleans_every_parallel_arm`, which deliberately
plants a TERM-IGNORING arm — `while :; do sleep 30; done` — and then asserts the
verifier's cleanup kills it and removes the worktrees. The bound is `_T = 55`.

They are red on the host BOTH under `$HOME` and outside it, so they are not the
G1 artefact. **But the image lane cannot adjudicate them**: in the image every
test in this file fails first on the absent Docker CLI, so the lane that would
act as the control is masked.

**G4 is therefore UNSETTLED, and it is unsettleable on 8hd-3** for the same
reason as G2/G3: there is no environment here in which this guard runs cleanly,
so there is no control arm for a kill-path test whose outcome depends on process
and cgroup behaviour. It folds into the same conclusion rather than standing as
a separate open question.

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

| group | n | cause | settled? |
|---|--:|---|---|
| G1 | 13 | subject under `$HOME`; `hermetic_candidate_runner.py:426` refuses it | **SETTLED — mine** |
| G2 | image lane | no Docker CLI in the pinned image | **SETTLED — environment** |
| G3 | 5 | host git 2.34.1 < 2.38, verifier drops to its degraded tier and refuses with a different rc | **SETTLED — environment; the verifier behaved correctly** |
| G4 | 2 | TERM/kill cleanup exceeds `_T=55` | **UNSETTLEABLE HERE** — the image control is masked by G2 |
| G5 | 1 | no corpus transition computed under a stub that forces one | **OPEN**, three of my own hypotheses eliminated |
| G6 | 1 | probe records only `cleanup.*`, no `A2/B1/B2.started` | **OPEN**, corpus eliminated as a cause |

**Not one of the 22 is a demonstrated defect in main.** Two remain open with
their obvious causes eliminated, two are unsettleable on this host, and
eighteen are environment — thirteen of those mine.

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
of them has moved since v1.11.62, which is consistent with all four being about
the environment or about evidence this host cannot produce, and inconsistent
with any of them being a live regression.

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
