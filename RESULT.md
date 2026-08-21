# Open the deadline

Branch `agent/jdeadline-open-the-red-deadline`, three commits on `e4c5840d6`
(v1.11.57):

    1f383bfb8  docs: the line where the deadline is read      (published FIRST)
    e69004cd2  docs: why no fix inside the suite can hold it
    35b79bcee  landing: open the deadline

## 1. THE NAME, WHICH WAS PUBLISHED BEFORE ANY CHANGE

`vibe-ic-marketplace/plugins/vibe-ic/programs/gate_red_since_check.py`

    :231   bound = int(row["max_commits"])          <- READ here
    :243   if behind > bound:  -> Finding("expired") <- BITES here
    :223   behind = age(since)                       <- the clock, in commits

`age` is `git rev-list --count {sha}..HEAD` (`:268`), so every reader of the
same tree computes the same number with no persisted run history — which is the
constraint that shaped the whole design, because the dispatch record is written
to a temporary directory and destroyed with the run.

**What would have to set it.** A row in `tools/ci/gate_red_since.json` under
`acknowledged`, with `gate` / `since` / `max_commits` (`_REQUIRED_KEYS`, `:117`)
and by convention `owner` / `why`. Today that list is `[]`, and it has always
been `[]`.

**Why it stayed `[]`, which is the actual finding.** The loop at `:194` is
`for row in ledger:` — the domain is the LEDGER, not the reds. A red that no row
mentions is not examined at all, and the file exits `[PASS] gate_red_since:
every red is NEW or owned by a live, unexpired acknowledgement` (`:350`). So the
only way to acquire a deadline was to volunteer for one, in a file whose own
`_doc` block says plainly that a row grants no leniency and buys no green. It is
pure cost. Nobody ever wrote one. The deadline was real, correct, tested — and
unreachable.

**What a landing would have done differently had it been open.** Between
e4880703b (2026-08-12), where `flow-gate enforcement audit` first went red on
the base, and 752a8baa, there are 704 commits and 96 version-bearing landings.
Under this rule the FIRST of those 96 refuses, with the gate named, unless
somebody writes the row — and writing the row is what makes the red visible,
owned, and dated. Ninety-five landings would have been unaffected because the
first one would have forced the choice.

## 2. THE HONEST N — AND IT MAKES TODAY'S MAIN UNLANDABLE

I am not choosing a comfortable N, so here is the uncomfortable one.

**For a red nobody has acknowledged, the grace is 0 commits.** Not a constant I
picked: "red for N commits" requires a first-red commit to count from, and for
an unacknowledged red no such commit exists anywhere in the repo. Only 0 and
infinity are computable. Infinity is the state being removed.

**The declared N is `max_commits`, per gate, in the row.** Bounded above by
`MAX_BOUND_COMMITS = 500`, renewed only by moving `since` forward (which is a
tracked edit with an author and a date), and it cannot be raised past the
ceiling. That row IS the amnesty the brief allows: a reason, an owner, an expiry.

**BLAST RADIUS, MEASURED.** `tools/ci/repo_hygiene_gates.sh --summary-json` on
origin/main `e4c5840d6` (v1.11.57), rc=1:

    declared 85 | ran 85 | decided 75 | PASS 67 | FAIL 8 | NOT_CHECKED 10

The 8 in state FAIL:

    flow-gate enforcement audit
    L-doc field producer
    evidence citation resolves
    checker execution wiring
    gates are wired to something
    declaration scans strip comments
    d3 declaration/manifest parity
    liar census controls still fire

Record: `~/_jdeadline/main_hygiene.json`.

So, stated plainly: **with this rule wired on and the ledger as it stands today,
main is unlandable until 8 rows exist.** That is the number. It is the owner's
call whether to write 8 rows, fix 8 gates, or stage it gate-by-gate.

**What I can and cannot honestly seed.** Only `flow-gate enforcement audit` has
a provable first-red commit — `e4880703b`, measured, and it is already recorded
in a comment in `landing_merge_verdict.py:1141-1145`. For the other seven I
cannot invent `since`, `max_commits` or `owner`: I would be manufacturing the
date that sets the deadline, which is exactly the quiet constant the brief
forbids. Each needs its owner to bisect it or to state a bound.

## 3. THE TESTS — BOTH DIRECTIONS AND A MUTATION ARM

`programs/tests/test_inherited_red_deadline.py`, **14 passed**.

REFUSES: an inherited blocking red with no owner; one past its deadline.

DOES NOT: one inside its deadline; a `WROTE_CORPUS` or `EXEMPTION_EXPIRED`
finding (parametrized — these are the "gate not so declared" mirror, and the
`FAIL` kind is precisely what "declared always-run-and-BLOCKING" reduces to
after `_gate_dispatch.sh`, since `run_tolerating_uncheckable` produces
`NOT_CHECKED` and never reaches the carried list); a red that is not inherited
at all, which belongs to the NEW-failure rule and not to this one.

MUTATION, five arms — raising the bound past the ceiling, dropping the bound,
citing a commit this repo does not have, repointing the row at a different gate:
all still refuse. And moving `since` forward, the one legitimate renewal:
correctly goes quiet. The last arm is the one that proves the other four are
discrimination and not a stuck refusal.

END-TO-END: three cases drive the real `decide()` on the LAND-OK baseline
borrowed from `test_landing_merge_verdict._decide` rather than restated, so a
change to that baseline cannot leave this file asserting against a fiction.

REGRESSION: `test_landing_merge_verdict.py` — main 22 failed, branch 22 failed,
**NEW 0**. (The 22 are host-dependent and identical on both arms.) It was
briefly 24: a top-level `sys.path.insert` in this authority file changed what
every later import resolves to inside the isolated trusted entry and broke two
end-to-end refusal paths. The import is now by-path and lazy, with that measured
reason written above it in the code.

## 4. WHERE IT SITS, AND WHAT IS STILL OFF

`gate_red_since_check.inherited_red_reasons(carried, ledger, age)` is a pure
function in a file that is NOT protected. `landing_merge_verdict.decide()` — 
which IS protected, `["authority"]` — consumes it AFTER the hygiene if/elif/else
chain and never inside it, so it cannot change which branch of that chain runs.
It only ever appends to `reasons`. The forcing function has to live in the
protected file for the reason in `e69004cd2`: any enforcement inside the hygiene
suite subtracts itself, because the suite's own failure is what the differential
then cancels on both arms.

**It is off by default.** `--red-since-ledger` / `--red-since-repo` default to
absent; with them absent the verdict emits the disclosure
`INHERITED_RED_DEADLINE_NOT_EVALUATED` and a note that ownership is UNKNOWN,
rather than reading as clean. No caller passes them in this commit, so no
landing behaviour changes until somebody wires it.

## REQUESTS TO THE LANDER

1. **`landing_merge_verdict.py` is protected, so this needs a PREPARE/ACTIVATE
   pair.** I have deliberately not authored one: the slot has been consumed four
   times today and a PREPARE is a photograph. Tell me the tree it lands on and I
   will render one against it — `~/_jlandpar/rechain.sh` does it in one command
   and asserts its own argument count.

2. **The wiring is one line, and it is yours to decide, not mine.** In
   `tools/gatekeeper-land-differential.sh`, add to the verdict invocation:

       --red-since-ledger "$BASE_WORKTREE/tools/ci/gate_red_since.json" \
       --red-since-repo   "$BASE_WORKTREE"

   The ledger must be read from the BASE arm, not the candidate: otherwise a
   branch can author its own amnesty in the same commit that needs it.

3. **Before you wire it, decide the 8.** Wiring it on today refuses every
   landing until the 8 gates above are fixed or acknowledged. I would land 1+2
   dark now (they change nothing), and wire 3 the moment there are 8 rows or 8
   fixes. I am not proposing a transition period, because a transition period is
   the comfortable N wearing a different hat.

4. **One row I can seed honestly if you want it**: `flow-gate enforcement audit`
   / `since: e4880703b` / `owner:` yours to fill. `max_commits` is a bound on
   how long it may still take, which only its owner can state — I will not put a
   number there.
