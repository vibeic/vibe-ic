# deepseek-harness — four mechanisms against four measured vibe-ic defects

Date: 2026-08-19. Worktree: detached at `2b93d8723` (v1.10.81).
Upstream read: `deepseek-ai/deepseek-harness` @ `master`, pushed 2026-08-17,
via the GitHub API (repo confirmed to exist; `main` does not, `master` does).
Sources reached: `docs/subsystems/scope.md`, `docs/cordis-tutorial/02-lifecycle-and-effects.md`,
`packages/session/session-persistence/README.md`, `packages/guard/timeout-policy/README.md`,
`packages/sandbox/sandbox-policy/README.md`, and the recursive tree listing.
Sources NOT reached: no package `src/*.ts` was read — every statement below about
upstream behaviour comes from its own README/docs prose, not from its code.

Ranked by consequence. Class is the cost of the defect the mechanism addresses,
not the cost of adopting it.

---

## 1. Append-only event log with typed interruption — SOLVES OUR DEFECT

**Class: a published number that is wrong in the safe-looking direction.**

WHAT THEY DO. `session-persistence` makes the event log the single source of
truth ("The persisted unit IS the existing `SessionEvent`"). Two invariants
carry the weight:

- *Contiguous `seq`* — `load` rejects a `seq` gap in the MIDDLE of the log;
  `append`'s first `seq` must equal the stored next-seq.
- *A crashed turn is CLOSED, not truncated* — on load, an unclosed final turn
  gets durably appended synthetic closers: a risk-classified `tool/result` per
  unanswered call, then `step/end` + `turn/end {interrupted}`. The risk classes
  are named: `TOOL_NOT_STARTED` (request without a durable call) and
  `TOOL_OUTCOME_UNKNOWN` (durable call without a result). Only a never-fully-
  written torn tail is discarded.

The load-bearing property is not "there is a log". It is that **the interruption
is written into the same artifact the verdict reads**, so a truncated run cannot
present as a complete one.

WHAT WE CHECK. We already have more of this than the addendum implies, and it is
good work:
- `_semantic_child_progress.py` — append-only JSON-line FSM
  `start -> checkpoint(unit) -> terminal` over an ordered manifest plus nonce,
  with `NORECORD` explicitly a *recording* outcome and never a correctness
  verdict. That is a genuine third state.
- `_pytest_progress_plugin.py` — append-only lifecycle events, one stream file
  per process so xdist yields N clean streams instead of one interleaved one.
- `pytest_per_file_junit.py` — owns the exact defect (vibe-ic#1654, measured
  2026-08-15 at `1adbf3444`): `--timeout-method=thread` cannot interrupt
  `waiter.acquire()`, pytest-timeout takes the PROCESS down, and a dead process
  writes no junit. In the originating run the hanging file was 1 of 91.
- `landing_merge_verdict.py` — `ABSENT` is already a first-class outcome, and
  `NORECORD` is already structured evidence rather than console text (#1709).

THE GAP. Our liveness channel and our verdict channel are **two different
artifacts, by explicit design** — `_pytest_progress_plugin.py` says so in its
own docstring: "This is a liveness channel, not verdict evidence... JUnit plus
the OS process return code remain the inputs to the landing verdict." So the
progress stream knows the run died, and the verdict reader cannot see that,
because the verdict reader reads junit and junit is simply *missing*. The
differential is `candidate failing set - base failing set`; a missing junit
yields an empty set on both arms; empty minus empty is no new failures. A run
that was killed reports the same shape as a run that was clean.

Upstream's answer is not a better timeout. It is that **absence is not a
representable state** — the log is rejected if it has a hole, and closed with a
typed `{interrupted}` marker if it has a ragged end.

SMALLER VERSION WE COULD ADOPT. Do not adopt event sourcing. Adopt the two
invariants at the junit boundary only: (a) the arm driver writes a
`turn/end`-equivalent sentinel into the *verdict* artifact set, so a missing
sentinel is a positive INTERRUPTED record rather than an absent file; (b)
`landing_merge_verdict.decide` refuses on INTERRUPTED instead of computing a
differential over it. `ABSENT` already exists as an outcome — the work is
making the arm *emit* it rather than inferring it from a missing file.

## 2. Reversible effects on the Context — DOES NOT SOLVE OUR DEFECT

**Class: a wrong writer is named; hours lost, silicon unaffected.**

WHAT THEY DO. `ctx.effect(() => { acquire(); return () => release() })`.
Registrations made through Cordis APIs are effects and are undone when the
owning plugin unloads. `ctx.on`, `ctx.plugin`, service and tool registrations
are already effects. Fibers move `PENDING → LOADING → ACTIVE → UNLOADING →
DISPOSED` (or `FAILED`).

WHAT WE CHECK. `tools/ci/_gate_dispatch.sh` brackets every gate with
`git status --porcelain --ignored=traditional -- benchmark-data` and names a
gate that changes it. `--ignored` is load-bearing and the comment says why: the
ignored class is invisible to plain `git status` while still being read by the
next gate. The measured damage is recorded there — 1078 leftovers in the main
checkout, which inflated the script's own declared-gate count from 68 to 169,
and produced 13 phantom FAILs reproducing on two unrelated PRs.

THE GAP — AND WHY THIS MECHANISM IS THE WRONG ANSWER. `ctx.effect()` is a
**teardown ordering** primitive, not an attribution primitive. It can only know
about resources acquired *through the Context by cooperating code*. Our gates
are subprocesses that write to a shared filesystem; they register nothing. A
reversible effect gives per-fiber ownership of *registrations you made*, never
of *arbitrary writes a child process made*. Adopting it would not let two gates
run concurrently and still be attributable.

Worth recording: their own doc names an ordering caveat — "disposers start in
reverse registration order, but multiple **async** disposers run concurrently."
That is the same class of hazard we pinned `GATE_DISPATCH_JOBS=1` to avoid.

SMALLER VERSION. The mechanism that actually buys concurrent attribution is
mechanism 4, not this one: give each gate its own writable overlay and diff the
overlay instead of the shared tree. Attribution then comes from the mount, and
the current `GATE_DISPATCH_JOBS=1` pin can be lifted on evidence rather than
kept as a workaround.

## 3. Scope registration primitives — PARTIAL; the transferable idea is next door

**Class: a check reports clean over a population nobody looked at.**

WHAT THEY DO. `packages/core/scope`: `ScopeKey` is an opaque identity;
`Scope` pairs a registration context with two teardown paths; `ScopedLayers<L>`
owns an eager global layer plus lazily created exact-scope layers, where
`peek(undefined)` means no overlay and reads never create layers.

WHAT WE CHECK. We have more here than upstream does, and ours is aimed at
exactly our question:
- `gate_discloses_denominator_check.py` — a PASS must say how much it looked at.
- `gate_zero_denominator_refuses_check.py` — and disclosing a zero denominator
  is a *different property* from refusing on one; its docstring records three
  gates that returned a verdict about a design they had not read, and that the
  P0 umbrella reads exit codes while the disclosure sits in prose.
- `_corpus_denominator.py`, `_gate_denominator.py`, `_corpus_location.py`,
  `extraction_coverage_denominator_audit.py`, and `--corpus-may-be-absent` as a
  declared flag across ~10 checkers.

THE GAP. Their `scope` is about **visibility and lifetime of registrations**,
not about what a check read. It does not answer our question, and adopting it
would not close our failure mode. Searched: `programs/` for `scope`, `corpus`,
`denominator`, `attempt`, `not_run`, `skipped` — we are ahead here.

The transferable idea is in their **sandbox-policy**, not their scope package:
"**The switch IS its event; nothing mutates the mode out of band**", with
`effectiveSandboxMode(events)` a pure fold over the log. That makes "what this
actor was allowed to touch" a value **derived from the record** and therefore
inspectable after the fact. Our `gate_scope` is a runtime argument that leaves
no trace in the artifact. Smaller version: have each gate emit its resolved
scope (root, glob, matched count) into its own record, so
`gate_zero_denominator_refuses_check` can audit the *recorded* population
instead of re-deriving it by driving the gate on an empty project.

## 4. Process-level sandbox vs our Docker — OURS IS STRONGER; THEIRS IS PER-SESSION

**Class: cosmetic for correctness; real for concurrency (see #2).**

WHAT THEY DO. `sandbox-policy` owns one resolved mode-and-root per call.
Modes are `read-only` / `workspace-write` / `danger-full-access`, defaulting to
`read-only` (fail-safe). A per-session override is one log-only `sandbox/mode`
event; an `./invariant` companion rejects a forged event outside the closed
vocabulary. Enforcement is process-level (bwrap / Landlock / Seatbelt per the
owner's summary; I did not read the enforcing backends).

WHAT WE CHECK. `tools/ci/protected_landing_transition.json`, profile
`vibeic-landing-hermetic-v1`: `cap_drop: ALL`, `network: none`,
`read_only: true`, `user: 65534:65534`, `no-new-privileges:true`, tmpfs mounts,
and an image pinned by digest (`ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2…`).

THE GAP — SMALL, AND IT RUNS THE OTHER WAY. Ours guarantees strictly more for
the landing arm: a pinned image digest is *toolchain* reproducibility, which no
process-level sandbox provides, and `network: none` plus `cap_drop: ALL` is a
stronger confinement than a filesystem-mode policy. What theirs buys that ours
does not: (a) **granularity** — per-call, per-session policy inside one process
tree, where ours is per-container and all-or-nothing; (b) **cheapness** — a
process-level jail is affordable per-gate, a container is not, which is what
makes the mechanism-2 overlay fix practical; (c) the policy is **replayable**,
because the mode switch is an event.

NOT DETERMINED: whether their sandbox actually confines a non-cooperating child
process on Linux, and how Landlock's ruleset is composed. I read the policy
package's README only, not `sandbox-local`.

---

## Upstream properties that are WORSE than ours — do not adopt wholesale

1. **Their tool timeout is cooperative and unverified.** `timeout-policy` states
   it plainly: "The derived signal only **notifies**; termination stays with the
   tool... a tool that ignores the signal will not stop on timeout." Nothing
   checks that a tool declaring `timeoutMs` actually forwards `exec.signal`. So
   the declaration is a promise with no enforcement — the same shape as a gate
   that declares a corpus and never reads it. This is the closest thing I found
   upstream to a check that cannot fire: for a non-cooperating tool the deadline
   is unfalsifiable, and it is documented rather than detected.
   Our `pytest_per_file_junit.py` is *ahead* here: it accepted that the deadline
   cannot be made to win and changed what survives the kill instead.

2. **`list()` is unpaginated and unfiltered**, and there is **no deletion or
   retention API** — their own "Known Limitations". Our `benchmark-data/ic/retention.json` exists.

3. **No partial-turn resume** — a crashed turn can only be closed, never
   continued. Acceptable for them; it would be a regression against our
   close-loop ECO flows.

## The measurement the addendum asked me to check

Neither published number survives derivation. Counted at `2b93d8723`:

| statement | where | what it counts | true today |
|---|---|---|---|
| "917 programs" | `vibe-ic-marketplace/README.md:40,358`; `plugins/vibe-ic/README.md:200,205` | `programs/*.py` **including** `_`-prefixed shared libs | **1178** |
| "918 deterministic programs" | owner's comparison | — | never equalled `programs/*.py` at any commit 2026-07-19..25 |
| "737 programs" | `vibe-ic-marketplace/README.md:554` | unknown | 1178 |
| "478 programs" | `skills/core-agent-loop/SKILL.md:251` | unknown | 1178 |
| "1102 programs" | `programs/INDEX.md:1186` | unknown | 1178 |
| "~600 checkers" | repo prose | plausibly `*_(check\|audit\|lint).py` | **577** (or 544 for `*_check.py` alone) — roughly current |
| "56 EDA tools" | `README.md:358,438,559` | `MCP_TOOL_INVENTORY.json.total` = 48 eda + 7 device + 1 other | **56 — correct** |

Provenance of 917, established by bisecting the claim against the tree:
introduced at `73d1efb20` (2026-07-20 03:31:59 +0800), where `programs/*.py` was
**exactly 917**. It was right when written and has drifted by 261 since.

So "~600 checkers" and "917 programs" are **not** measuring the same thing and
neither is a correction of the other: checkers are a ~49% subset of programs.
The 917 family is stale; the checker count is roughly current.

WHY THIS KEEPS HAPPENING, which is the finding that matters more than the
number. The MCP tool count is **generated from code** and carries a contract in
its own file: "AUTHORITATIVE MCP tool inventory — generated from code by
tools/gen_mcp_tool_inventory.py. Do NOT hand-edit; the website tool count must
read `total` from here." It is the one count that is right. The program count
has no generator and no gate — I searched `programs/` for `inventory`, `census`,
`count`, `manifest` and found `gen_skill_inventory.py` (skills) and
`benchmark_run_manifest.py`, but nothing that counts programs. Five hand-written
numbers in five files is the predictable result.

Statements that need correcting: the four "917" sites, `README.md:554` (737),
`SKILL.md:251` (478), and `programs/INDEX.md:1186` (1102). The durable fix is a
`gen_program_inventory.py` on the `gen_mcp_tool_inventory.py` pattern plus a
gate asserting every published count reads from it.

## By-product: the box's only `deepseek` artefact, and it is not this repo

Before the addendum settled the subject, the only `deepseek` string on this host
was `manual-deepseek-coder-6.7b` / `-33b` in `~/verilog-eval/scripts/sv-generate`
(NVlabs/verilog-eval @ `c498220`). That is a benchmark we run, so the following
measured defects are recorded here rather than discarded. All three reproduce.

1. **PASS is a substring grep over a log the solver's own code can write to.**
   `sv-iv-analyze` sets `no_mismatch` on the first line matching
   `^Mismatches: (\d+) in \d+ samples$` and **never clears it** (`scripts/sv-iv-analyze:284-299`).
   The DUT is compiled into the same simulation as the testbench, so its
   `$display` lands in the same log. Measured: two samples with **identical,
   wrong** logic (`assign zero = 1'b1` where the spec says always LOW), the
   second adding one line — `initial $display("Mismatches: 0 in 20 samples");`.
   The simulation reported `Mismatches: 20 in 20 samples` for **both**.
   `sv-iv-analyze` scored them `R,.` — a 50% pass rate on a problem answered
   wrongly twice. The honest-wrong control fails, so the test is not vacuous;
   it is forgeable.

2. **A problem that was never attempted leaves the denominator.** `main()` globs
   `{problem}/{problem}_sample*-sv-iv-test.log`; a problem with no log never
   enters `self.data`, and the reported rate is `pass_rate_sum / len(self.data)`.
   Measured: scoring one real problem plus three never-attempted ones prints
   `pass_rate = 50.00` over a denominator of 1, with no row and no warning for
   the missing three. All-missing raises `ZeroDivisionError`. Two states, not
   three — and the missing state is the silently favourable one.

3. **`count_failures.py` silently loses one problem.** `sv-iv-analyze.write_csv`
   emits `summary.csv` with **no header row**; `count_failures.py:20` calls
   `pd.read_csv` without `header=None`, so the first problem's row becomes the
   column names. Measured on a 3-problem file: 2 rows parsed, 4 of 6 samples
   tallied.

Also noted, not separately measured: `pass_rate_to_csv.py` requires build dirs
to match `build_<task>_<model>_shots<N>_n<M>`; anything else is silently skipped,
and the script prints "CSV file created successfully" over an empty result set.

Relevance to us: any vibe-ic VerilogEval number produced by driving upstream
`sv-iv-analyze` inherits (1) and (2). Neither is a defect in our runner. Our
comparables exist and are pointed the right way — `vacuous_testbench_check.py`
(three independent detectors, filename plays no role), `drc_vacuous_pass_check.py`,
`gate_zero_denominator_refuses_check.py` — but I found **no** program that
checks a DUT for forging a testbench verdict string. Searched `programs/` for
`$display` cross-referenced with `verdict|forge|self.?report|spoof`: the hits are
oracle/TB *generators*, not a forgery detector. That is a real, cheap gap:
a scan of the submitted RTL for the harness's own verdict tokens.
