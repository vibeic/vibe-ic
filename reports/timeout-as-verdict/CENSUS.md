# Timeout-as-verdict census

A wall-clock bound answers *"how long has it been"*. A verdict needs the answer to
*"is this working"*. Where a repo spends the first as if it were the second, the same
code on a slower host is recorded as a different design.

This census separates the three kinds and reports the denominator at every step.

* **A — DEFECT.** The timer firing produces a **FAILING** verdict about the subject.
* **B — ACCEPTABLE.** The timer firing produces **NOT_MEASURED / UNDETERMINED / UNKNOWN**.
  "I could not finish looking, so I am not answering" is honest. Left alone.
* **C — NOT A VERDICT.** A resource guard (a connect bound, a host watchdog, a
  constant-vs-constant configuration assertion). Left alone.

The only question asked of each site: **if this timer fires, is something recorded as
WRONG, or as UNKNOWN?** Wrong = A. Unknown = B.

Per-site table: `census.csv` (2188 rows, sorted by class).

## Denominator

Measured on `main` at the commit recorded in `PROVENANCE.json`, in an independent clone.

| tree | `.py` | `.sh` |
| --- | ---: | ---: |
| `plugin/programs/` | 4243 | 1 |
| `plugin/mcp-eda/` | 44 | 3 |
| `plugin/tools/` | 19 | 0 |
| `tools/` (repo root) | 200 | 26 |
| **searched** | **4506** | **30** |

* Files searched: **4536**. Parse failures: **0** — every `.py` yielded an AST, so no file
  was silently skipped.
* Files carrying at least one timeout-shaped site: **792**.
* Timeout-shaped sites found: **2341**.

`timeout` as a bare word appears in far more files than this. That string is not the
population; a site is only counted when it is a *bound with a consumer*.

### Sites by kind

| kind | n | how it was found |
| --- | ---: | --- |
| `timeout=`-family kwarg on a call | 1994 | AST: every `ast.Call` with a `timeout*` keyword |
| embedded shell `timeout` / `--timeout` inside `.py` | 153 | line scan |
| `except <Timeout…>` handler | 141 | AST: handler types matching `Timeout` |
| measured elapsed compared to a literal | 41 | AST: `Compare` with a duration name and a numeric literal |
| shell `timeout N` / `timeout -k` | 12 | line scan of `.sh` |

## Classification

### The 1994 `timeout=` call sites

Each site was attributed to its **innermost enclosing `try` whose handler can catch
`TimeoutExpired`** — which includes `subprocess.SubprocessError` (its parent),
`Exception`, `BaseException` and a bare `except`. The handler body was then read.

| | A | B | NOT_MEASURED |
| --- | ---: | ---: | ---: |
| `programs/tests/` | 1302 | 5 | 24 |
| `programs/` (non-test) | 302 | 24 | 225 |
| `mcp-eda/` | 38 | 0 | 7 |
| `tools/` | 43 | 2 | 22 |
| **total** | **1685** | **31** | **278** |

Of the 1685 class-A sites:

* **1178** are a **direct** `subprocess.run` / `check_output` / `Popen` / `communicate`
  with **no handler covering them**. The `TimeoutExpired` escapes: a program aborts with
  a traceback, a test ERRORs. Either way the run is recorded as a defect of the subject.
* **507** pass the bound **into a repo helper** (`_run`, `_docker_exec`, `G.audit`,
  `TP.evaluate`, `runner.run_argv`, …). These are not 507 independent defects — they
  collapse onto roughly 20 helpers, and the helper's own `subprocess.run` is where the
  fix belongs.
* **69** are covered by a handler that then records a **failing** verdict
  (`ok = False`, `return False`, `sys.exit(1)`, appending to a findings list).

The **278 NOT_MEASURED** are covered by a handler whose body matched neither the
failure nor the unknown vocabulary. They are **not** counted as acceptable. They are
unclassified, by name, in `census.csv` (`cls=NOT_MEASURED`).

### The 141 `except <Timeout>` handlers, read directly

| class | n |
| ---: | --- |
| A — the handler records a failing verdict | 27 |
| B — the handler records UNKNOWN / NOT_MEASURED / rc 2 | 46 |
| MIXED — both vocabularies in one body | 2 |
| NOT_MEASURED — matched neither | 66 |

Two of the 27 print the sentence *"a timeout is not a verdict"* and then `return 1`.
`plugin/programs/phase1_one_shot_runner.py:532` and `:686`. The diagnosis is already
written down at the site; only the exit code disagrees with it. Those two are a
one-line move from A to B (`return 1` -> the repo's rc 2 UNDETERMINED convention).

The 46 in class B are the shape to copy. `plugin/programs/matrix_mutation_ledger.py:2636`
is the clearest: *"the cell exceeded its bound and was killed, so pytest never recorded
it — this arm was NOT MEASURED. That is not evidence the gate stopped catching."*

### The 41 measured-elapsed comparisons

* **21** are `assert elapsed < N` / `assert elapsed > N` — a wall-clock number decides a
  test verdict directly. **Class A.** Listed in `census.csv`.
* **20** compare two constants (`AUDIT_TIMEOUT_DEFAULT_S > 180`) or check validity
  (`if spice_s <= 0`). No wall clock is measured. **Class C.**

At least one of the 21 is already known to be host-dependent in practice:
`test_matrix_63x8_coverage.py:2010` (`assert elapsed < 6`) fails under load and passes
when the host is quiet — the defect reproducing itself.

### The 12 shell `timeout` sites

All **C**: six are `timeout 10` around a driver probe in an `mcp-eda` shell test whose
result is `|| true`'d, one is a `wget --timeout=15` download bound, three are comments
describing the harness bound, one is `timeout 30` in `pre_commit_check.sh`.

## Headline

**Class A: 1733 sites** — 1685 `timeout=` sites + 27 `except` handlers + 21 elapsed
assertions. Removing the 507 call-throughs that collapse onto shared helpers, the number
of **independent** places to change is about **1220**, across **584** files.

## Precision of the class-A label

A random sample of **30** class-A sites (seed 1444) was read by hand:

| verdict on re-read | n |
| --- | ---: |
| class A confirmed — a real subprocess, no handler, a failing assertion downstream | 24 |
| false positive: `subprocess.run` is patched, nothing is ever spawned | 3 |
| false positive: a call-through, already separated out in the table above | 3 |

**24/30 = 80%** precision on the untightened label. The two false-positive kinds are both
mechanically separable and both are separated in the numbers above (only 2 of the 1178
direct sites sit in a file that patches `subprocess.run`), so the tightened
direct-subprocess count is the more accurate one.

## What the owner's own example turned out to be

`plugin/programs/tests/_analog_producer_fixture.py:76`

```python
def run_prog(prog: Path, project: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(prog), str(project), *args],
                          capture_output=True, text=True, timeout=60)
```

A shared fixture. No handler. Every test module importing `run_prog` inherits it, and a
slow host turns any of them into an ERROR attributed to the program under test.

One correction to the original diagnosis, for the record: `analog_a3_netlist_emit.py`
**does** catch its timeouts — `subprocess.TimeoutExpired` is a subclass of
`subprocess.SubprocessError`, and all seven of its `subprocess.run` calls sit under
`except (OSError, subprocess.SubprocessError)`. Six of those handlers return
`NOT_VERIFIED_NO_SIMULATOR` and are class B. The seventh, at line 878 (`timeout=300`
around the four checkers), sets **`ok = False`** and appends a finding — so it is class A,
and the conclusion holds for that site regardless.

## The replacement shape

Not a bigger constant. A bound tuned to one machine is the defect restated.

1. **Progress, not duration.** `plugin/programs/_watchdog.py::run_supervised` already
   does this: it returns on exit or on STALL, and kills only a job that is **not
   progressing** — CPU (`utime+stime`), I/O (`read_bytes+write_bytes`), RSS, output file
   count/bytes/mtime. Any signal moved = PROGRESSING. Nothing moved across N consecutive
   looks = STALLED. **N counts looks, not seconds**, so a six-hour job that is burning CPU
   never trips it.
2. **Where a number is unavoidable, measure it this session** rather than writing it
   down.
3. **Where a bound genuinely cannot be avoided, its expiry must produce NOT_MEASURED,
   never FAIL.** That alone converts a class A into a class B.
