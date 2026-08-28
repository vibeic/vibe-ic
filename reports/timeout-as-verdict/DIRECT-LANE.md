# The 1178 direct points — a watchdog, not a relabel

The census slice this lane owns is `cls==A && direct==yes`: **1178 rows** where a
call site passes its own `timeout=` and the expiry becomes a *failing verdict
about the subject*. The brief was explicit — do not start until you have
grouped, because a tail of 1178 is not 1178 problems.

It is not. It is **one problem, 1178 times.**

## The owner's rulings this lane is written to

> 出現 1 個 failure，位置是未修改的 analog_a3_netlist_emit，看起來是 60 秒的
> timeout 造成的 failure。你怎麼知道它 60 秒這次過了，換一臺機器會不會跑得更久
> 或跑得更快？你不知道嘛。

and, on what counts as a fix:

> Timeout 就結束這件事情不 make sense。任何 Timeout 要先用「看門狗」取代，而不是
> 把 fail 變成 not_measured — 那是**最下策**。

Both are load-bearing here. The first says a wall-clock bound answers *"how long
has it been"* and is then spent as if it answered *"is this working"*. The second
says that relabelling the expiry to NOT_MEASURED is not a fix: it still kills
work that was progressing, and only stops lying about why. **The kill is the
defect.**

The first ruling's own example is a TEST bound, and this lane's slice is 89%
tests. That is not a low-value corner of the tail; it is where the report came
from.

## Grouping, before any edit

Every row is the same call — `subprocess.run(..., timeout=N)`. 1165 of 1167 are
`subprocess.run`; 2 are `Popen`. What differs is only *who reads the result*.

| tree | sites |
| --- | ---: |
| `programs/tests/` | 997 |
| `programs/` (non-test) | 68 |
| `mcp-eda/` | 36 |
| `tools/` (repo root) | 40 |
| elsewhere | 13 |

**584 distinct files, 1104 distinct enclosing functions.** The tail is flat, not
clustered — so it was grouped by the only axis that predicts the fix: what the
call passes.

| kwarg | sites | share |
| --- | ---: | ---: |
| `timeout` | 1165 | 99.8% |
| `capture_output` | 1153 | 98.8% |
| `text` | 1121 | 96.1% |
| `cwd` | 168 | 14.4% |
| `env` | 92 | 7.9% |
| `check` | 51 | 4.4% |
| `input` | 16 | 1.4% |
| `stdout` / `stderr` | 12 / 12 | 1.0% |
| `stdin` | 9 | 0.8% |
| `errors` | 4 | 0.3% |

**1128 of 1167 (96.7%) pass nothing a `subprocess.run`-shaped progress-supervised
drop-in cannot take.** That single number is the grouping result, and it is why
this lane is one fix applied 1065 times rather than a thousand judgement calls.

## The census's own precision, measured

The brief warned to expect ~1 in 5 false positives. On this slice it is far
better than that, and the difference is worth recording because it changes how
the next lane should budget.

Every row was located on the current tree by AST (alias-aware: a function-local
`import subprocess as _sp` counts), not by the census's line numbers, which had
drifted 30 commits.

| | rows | |
| --- | ---: | --- |
| located as a true direct site | 1167 | 99.1% |
| **genuine false positives** | **5** | **0.4%** |
| line-drift, could not be located | 6 | 0.5% |

The 5 genuine false positives are both of the kinds the brief named, and both
are mechanically separable:

* **4 are call-through, not direct** — `mcp-eda/.../terasic-de10lite/driver.py`
  lines 230, 245, 911, 1128 are `run([...], timeout_s=20)`, a *local helper*.
  The helper itself is a separate census row and IS direct; fixing it fixed all
  four callers, which is the grouping working.
* **1 is not a subprocess call at all** — `formal_property_run.py:1514` calls
  that module's own `def run(project, ...)`.

The remaining 6 are the census's line numbers pointing into a file that moved
more than the ±60-line search window; the sites are real and elsewhere in the
same files.

**The 20% figure did not reproduce. 0.4% did.**

## The fix: `_progress_run`, built on `_watchdog`

`programs/_progress_run.py` is a `subprocess.run`-shaped call that judges
PROGRESS. A call site converts by deleting `timeout=`.

It does not reinvent the supervisor: it drives `_watchdog.run_supervised`, the
primitive this repo already had. Progress is *did anything MOVE between two
looks* — output bytes, CPU (`utime+stime` over the child **and its live
descendants**, so a quiet compute phase counts), block I/O. Any signal advancing
= PROGRESSING, and a progressing child is **never** killed, however long it
legitimately takes. Nothing advancing across N consecutive looks = STALLED.

**N is how many times we looked, not how long we waited.** A six-hour proof
burning CPU advances the CPU signal at every look and can never trip the stall.
That is the property a wall-clock bound cannot have.

Two outcomes, and neither is a timeout:

* the child exits → a `CompletedProcess`, whatever it took;
* every readable signal sat still across N looks → `Stalled`, which is a
  **finding about the child**, not about the host, and therefore actionable.

Where the caller is a gate and cannot act on it, `exit_undetermined_on_stall`
maps it to rc 2 UNDETERMINED — the repo's existing rule that *a review which
could not decide must never reach the stamp as a review that decided nothing was
wrong*. That is the last resort the second ruling permits, and it is reached only
**after** the progress logic has decided the child is genuinely wedged.

### What the compatibility surface serves, and what it refuses

Widening it was not cosmetic: 39 of 1167 sites passed something the drop-in
refused, and they were concentrated exactly where it matters — the protected
landing transition and the pytest runtime preflight feed children
`stdin=DEVNULL`; `gate_host_independence_check` needs ONE combined stream
because separately captured stdout-then-stderr is not the order a human or
`2>&1 | tee` observes, and that ordering is verdict-bearing.

Served: `cwd`, `env`, `check`, `input=` (handed over as a seekable file, never a
writer thread this module could block on), `stdin=`, `(stdout=PIPE,
stderr=STDOUT)` for one combined stream, `(stdout=PIPE, stderr=PIPE)` for the two
separately, `errors="replace"`, `shell=`, and `text=False` for raw bytes.

Refused, **out loud**: any other `errors=` policy, and any `stdout=<file>`
redirect. An argument accepted and then not honoured would leave a converted gate
reading an empty answer and calling it a clean one — worse than the timeout it
replaced. A file redirect would take the output away from the progress meter
while the result went on claiming an output signal; the honest answer there is
`run_supervised(log_path=...)`, which watches the file it writes.

`text=False` is real bytes, not decode-and-re-encode. The test asserts, as its
own negative control, that the lossy alternative really would destroy a payload:
a caller splitting `git ls-files -z` on NUL or reading a blob out of `git
cat-file --batch` must get the bytes the child actually wrote.

`FileNotFoundError` is re-raised rather than reported as rc 127. `subprocess.run`
raises for a missing executable and call sites across this repo catch it to say
"the tool is not installed"; the supervisor's rc 127 is right for a supervisor
and wrong for a drop-in. **A drop-in may not change the exception contract.**

## What was done

| | sites |
| --- | ---: |
| worklist (census class-A direct, located) | 1154 |
| **converted** | **1066** |
| held, with a reason | 88 |

* **PROD: 102 of 102.** Gates, flow runners, and MCP tools — where a fired bound
  becomes a landing verdict or a tool's answer to a user.
* **TEST: 964 of 1052**, across `programs/tests/`, `mcp-eda/test/` and `tools/`.

Three coordinated edits per site, all by AST position, never by regex:

1. the callee becomes `_pr.run` — or `_pr.run_best_effort` at **12 hand-named**
   cleanup/capability probes whose result reaches no verdict;
2. `timeout=` goes, or becomes an explicit `text=False` at the 11 sites reading
   bytes;
3. the **22 `except ...TimeoutExpired` handlers guarding those calls** are
   retargeted to `_pr.Stalled`, and every one of their messages is rewritten.

That third edit is not tidiness. Those are recovery paths their authors wrote for
"the child did not finish"; left catching an exception that can no longer be
raised, they would be dead code that still reads as coverage. And a retargeted
handler that still says "timed out" says the wrong thing about the right event —
three of them named a bound that no longer exists, including a `_p0_gate_record`
carrying `timeout_s: 60` and a message telling the reader to raise
`VIBEIC_GATE_TIMEOUT_S`. **A record naming a ceiling nobody spent is worse than
no detail: the first thing it makes a reader do is raise something.**

51 entry points now exit through `exit_undetermined_on_stall`. 358 + 16 + 22
orphaned `import subprocess` lines and 80 orphaned module-level bounds
(`_CLI_BOUND_S`, `_GATE_TIMEOUT_S`, `_NESTED_PYTEST_TIMEOUT_S`, …) are removed
with the comment blocks that documented them: a dead `_TIMEOUT_S = 60` is not
inert, it reads as live policy and invites the next author to spend it.

### `matrix_mutation_ledger` — the flagship

It was already doing what the second ruling calls 最下策. It killed a cell at
900 s and recorded NOT_MEASURED: honest about the lie, and still killing work
that was progressing. `_run_cell` and `replay` now take the supervision cadence
instead of a bound, and the two docstrings that said "``timeout`` bounds ONE
cell" say what is true.

Its three bound tests are re-anchored on the property rather than on the number.
The probe sleeps **forever** instead of for thirty seconds — under a clock,
thirty seconds was merely longer than the bound; under supervision a
thirty-second sleep wakes and answers. The cadence is three looks a second
apart, chosen **above** pytest's own ~0.65 s idle boot floor, so the stall is
caused by the probe going quiet and not by looking during start-up.

## What was held, and why — 88 sites in 22 files

Not one was held for convenience.

| reason | sites | files |
| --- | ---: | ---: |
| the file is NAMED for the timeout machinery — converting it converts the subject under test | 62 | 12 |
| the file drives a deliberately hanging or spinning child, where the bound IS the stimulus | 17 | 6 |
| single stragglers in files otherwise converted | 9 | 4 |

The largest single holding is `test_ci_harness_timeout_ceiling_check.py` (35
sites), which exists to police inner bounds.

**One of those holds is a correction to my own selection.**
`tools/ci/test_landing_runtime_preflight_gate.py` has neither "timeout" nor
"bound" in its name, so the filter missed it and it was converted. Its
`test_an_inner_bound_is_a_real_bound` exists to prove the bounds THAT FILE uses
sit under the harness ceiling and that one of them really stops a child that
does not return — and `pytest.raises(subprocess.TimeoutExpired)` cannot hold
against a call with no bound to expire. Retiring that guard is a policy decision
about whether the ceiling rule still applies, and it belongs to whoever owns the
rule. Reverted, and reported.

## Both directions, everywhere

**A guard that stopped refusing is a deletion, not a fix.** Every property is
asserted in both directions, and each pair is written as an A/B against the call
being replaced — testing only the new call would pass just as well if the new
call never refused anything at all:

* a quiet CPU-bound child that outlives a bound is **no longer failed**, and the
  same child IS failed by `subprocess.run(timeout=...)`;
* a motionless child is **still caught** — on the plain path, on the combined
  stream, in bytes mode, and when fed by `input=`;
* a measured slow host makes the primitive **more patient, never less**;
* a missing executable raises `FileNotFoundError` on both sides.

## Verification, and the three defects it caught

Three real defects in this work were found by measuring rather than asserting.
They are recorded because each is a reusable trap.

**A file-wide regex reached code no site named.** The first pass tidied the
ragged `text=True, )` left by the deletions with `s/,\s*\n\s*\)/)/` over the
whole file. It found a `tuple(rules,)` in `formal_property_run.py`, turned a
one-element tuple into a bare value, and broke the module's import. The cleanup
is now scoped to the span each site owns, the whole pass is regenerated from
main rather than patched, and the property is **checked**: an AST node-kind
histogram per file, base vs here, reports drift in exactly the statements the
change deliberately deletes. A vanished `Tuple` shows up in the same column.

**Ten converted files pointed the loader at their own directory.** `_progress_run`
lives in `programs/`; nine files under `tools/` and one five levels down inside
`mcp-eda/src` are not there. All ten raised `ModuleNotFoundError` — including two
landing gates, which would have failed at the first line rather than at the
check. They now walk UP for the directory that holds it.

**A differential is not optional when the instrument is new.** The probe that
found those ten also reported 17 failures among the 50 converted modules under
`programs/`, with `'NoneType' object has no attribute '__dict__'`. Running the
identical probe against clean main produced the identical 17: those modules
introspect themselves through `sys.modules`, and a module loaded by
`spec_from_file_location` under a made-up name has no entry to find. A real
import reports 0 on both arms.

### The A/B

Two equal-length sibling checkouts, base commit vs candidate, run separately.

| arm | failures |
| --- | ---: |
| base `851b7e8a69`, 69 files | 2 |
| candidate, same 69 files | 25 |

The 2 on the base are pre-existing on this host. The 23 new ones were **one
cause in three shapes**, and none of them was the conversion being wrong about
production behaviour: the tests inject the process launch at `subprocess.run`,
and the launch had moved. Six files now substitute at `mod._pr` (two of those
modules no longer import `subprocess` at all, so the old line could not even
resolve); `test_suite_write_guard` copies the guard into a detached mirror and
now carries its siblings with it; and
`test_analog_one_shot_runner_a1a3_producers` spied on one seam when the runner
has two — three of its producer dispatches are census rows classified
NOT_MEASURED, outside this lane, and still launch through `subprocess.run`.

Fixing those seams surfaced the `FileNotFoundError` contract and the ledger's
bound tests, both above.

On the `tools/` and `mcp-eda/` set: **6 failed / 313 passed on BOTH arms, same
names**, plus 152 passed under `mcp-eda/test`. Differential pyflakes on every
touched file, base vs here: 152 → 147, 104 → 96, 8 → 7. No new findings.
