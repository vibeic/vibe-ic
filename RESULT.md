# The PPA exit-code contract: three of the eleven were program defects, eight were not

Base: `origin/main` @ `8a9c5ad9e` (v1.11.51), which carries the suite that found
them (`38dab3bb2`, v1.11.50).
Branch: `jrc/ppa-layer-rc-contract`. One commit, `cddc5c128`, touching three
program files. No version bump, no test file edited, no baseline written.

---

## The short version

Eleven named reds. **Three are defects in the programs; they are fixed here and
each has a mutation arm that names exactly one test.** The other **eight are not
reachable by any change to any program**: they fail inside `pytest.fail(...)`
before the program is invoked, because the two layer files discover their
parametrisation by glob (18 programs) and declare their invocations in a
hardcoded table (14 programs). The four the brief names are precisely the four
in the gap.

I measured all eight anyway, by invoking the four programs the way the tables
would have to declare them. **All eight arms pass.** The four programs are
contract-correct on the vacuous arm and on the traceback arm today; what is
missing is the declaration, and the declaration lives in the test file.

Per the brief I did not edit the tests. The eight one-line entries are handed
over in [§6 Handoff](#6-handoff-changes-in-files-this-branch-does-not-own),
which is the same route `test_ppa_layer_exit_contract.py` already uses for its
own three cross-ownership pins.

And the denominator question found more than the eleven did: **the PPA layer has
24 executables and the suite parametrises over 18 of them.** Of the six it never
reaches, three carry defects in the classes the suite exists to catch — two of
them the *same* unknown-flag defect I fixed in the four.

---

## 1. Per program: what it returned, and what it returns now

Measured on this host, `python3` 3.10.12, pytest 9.1.1.
`A` = an absent path under an empty `tmp_path`; `D` = that empty directory;
`J` = a file holding `{"not": "what you wanted", "n": [1,2,3]}`.

### The three defects, fixed

| program | invocation | before | after | contract |
|---|---|---|---|---|
| `ppa_agent_context_build.py` | `--this-flag-does-not-exist` | **rc=2** | **rc=3** | §1: bad invocation is 3 |
| `ppa_diagnostic_router.py` | `--this-flag-does-not-exist` | **rc=2** | **rc=3** | §1: bad invocation is 3 |
| `ppa_signoff_records.py` | `--help` | **rc=3** | **rc=0** + usage | `--help` is a correct invocation |

**Why the first two were 2.** Both called `ap.parse_args(argv)` and nothing else.
`argparse` exits 2 on a usage error — its own convention, older than this
contract — and §1 gives 2 to UNDETERMINED. The usual way a flow gate honours
"rc=2 is never PASS" is to treat 2 as *not applicable here, carry on*, so a
misspelled flag reads as a step that had nothing to check and the run continues
green having measured nothing. A 3 cannot be read that way by anybody.

**Why the third was 3.** It had already fixed the above, with the repair that
invites the opposite mistake:

```python
try:
    args = ap.parse_args(argv)
except SystemExit:
    return RC_BAD_INVOCATION
```

That catches the exception *type*. `--help` raises `SystemExit(0)` too, so
asking the program what its flags are became a bad invocation. The two are one
defect seen from both sides: fixing either alone produces the other.

**The fix.** All three now go through `_ppa/cli_exit.parse_or_refuse`, which
reads argparse's exit **code** — 0 for `--help`, 2 for a usage error — and maps
only the second to 3. It already shipped on this base and already had its own
mutation arm (`test_cli_exit_helper_tells_help_from_usage_error_by_code`). Using
it means a nineteenth program inherits both halves at once instead of
rediscovering the trap.

Nothing else in the three programs changed. Their own refusal paths still
answer as they did:

| program | invocation | rc | marker |
|---|---|---|---|
| `ppa_signoff_records.py` | `D` (a run dir with no sign-off artefact) | 2 | `[CANNOT CHECK]` |
| `ppa_agent_context_build.py` | `A` (absent manifest) | 2 | `[CANNOT CHECK]` |
| `ppa_agent_context_build.py` | no positional | 3 | — |
| `ppa_diagnostic_router.py` | `A` (absent situation) | 2 | `[CANNOT CHECK]` |
| `ppa_diagnostic_router.py` | no positional | 3 | — |

### The eight that no program change can reach

`ppa_pr_scope_check.py` is in this group only; it has **no defect** — it already
answered 3 on an unknown flag and 0 on `--help` before this branch.

All four fail at

```python
argv = {...14 entries...}.get(prog)
if argv is None:
    pytest.fail(f"{prog} has no vacuous invocation in this file's table. ...")
```

**Negative control, run in both directions.** I replaced `ppa_signoff_records.py`
with a stub that satisfies every assertion in both arms, and then with a stub
that violates every one of them, and ran the two arms against each:

```
ARM A — stub that answers rc=2 + [CANNOT CHECK] to everything, rc=0 + usage to --help
  Failed: ppa_signoff_records.py has no vacuous invocation in this file's table. ...
  Failed: ppa_signoff_records.py has no invocation in this file's table; its traceback arm is untested
  2 failed, 111 deselected in 0.62s

ARM B — stub that prints "PASS: everything is fine" and exits 0 to everything
  Failed: ppa_signoff_records.py has no vacuous invocation in this file's table. ...
  Failed: ppa_signoff_records.py has no invocation in this file's table; its traceback arm is untested
  2 failed, 111 deselected in 0.78s
```

Byte-identical verdicts for a perfect program and a maximally broken one. The
arm's answer is independent of the program under test, so no edit to any of the
four can turn it green. That is not a criticism of the test — the `pytest.fail`
is a correct and deliberate alarm for *a program was added and nobody declared
how to invoke it with nothing to look at*. It is simply an alarm whose remedy is
a declaration, and the declaration is in the test file.

**What the four actually do, once declared.** Same assertion bodies, run outside
the suite against the invocations the tables would have to carry:

| program | vacuous invocation | rc | marker | verdict |
|---|---|---|---|---|
| `ppa_signoff_records.py` | `[D]` | 2 | `[CANNOT CHECK]` | would PASS |
| `ppa_agent_context_build.py` | `[A]` | 2 | `[CANNOT CHECK]` | would PASS |
| `ppa_diagnostic_router.py` | `[A]` | 2 | `[CANNOT CHECK]` | would PASS |
| `ppa_pr_scope_check.py` | `["--changed-file", A]` | 2 | `[CANNOT CHECK]` | would PASS |

| program | traceback invocation | rc | traceback in stderr | verdict |
|---|---|---|---|---|
| `ppa_signoff_records.py` | `[str(tmp_path)]` (holding `J`) | 2 | no | would PASS |
| `ppa_agent_context_build.py` | `[J]` | 1 `[REFUSE]` | no | would PASS |
| `ppa_diagnostic_router.py` | `[J]` | 1 `[REFUSE]` | no | would PASS |
| `ppa_pr_scope_check.py` | `["--changed-file", J, "--catalogue", J]` | 2 `[CANNOT CHECK]` | no | would PASS |

Two notes on the traceback table for whoever applies it:

- `ppa_signoff_records.py` takes a *directory*, so the arm's junk has to be a
  directory holding the junk document, exactly as the existing
  `ppa_closure_run.py` entry passes `str(tmp_path)`. Passing `J` itself
  produces rc=3 `[CANNOT CHECK] ... is not a directory`, which also satisfies
  both assertions but exercises the argument check rather than the parser.
- For `ppa_pr_scope_check.py`, `["--changed-file", J]` alone reaches rc=1
  `[FAIL] 5 applicable, 0 N/A, 15 undetermined`. That satisfies the assertions
  as written (no traceback; rc in range), but it is a *finding* derived from a
  file of nonsense, because `--changed-file` is a line-per-path list and a JSON
  document has lines. `--catalogue J` puts the junk where a JSON document is
  actually expected and gets the honest 2. I would use the second.

---

## 2. The mutation arm for each fix

Each arm was run: revert one call site, run
`test_ppa_layer_exit_contract.py` whole, restore. The four standing reds are the
undeclared-vacuous arms above and are present in every row.

| mutation | reds | delta |
|---|---|---|
| *(none — as shipped on this branch)* | 4 | baseline |
| `ppa_agent_context_build.py` → bare `ap.parse_args(argv)` | 5 | **+`test_unknown_flag_is_bad_invocation_not_undetermined[ppa_agent_context_build.py]`** |
| `ppa_diagnostic_router.py` → bare `ap.parse_args(argv)` | 5 | **+`test_unknown_flag_is_bad_invocation_not_undetermined[ppa_diagnostic_router.py]`** |
| `ppa_signoff_records.py` → bare `except SystemExit: return RC_BAD_INVOCATION` | 5 | **+`test_help_is_not_a_bad_invocation[ppa_signoff_records.py]`** |

Each mutation adds exactly one red and it is the one the brief names. The third
is the sharper arm of the three: the reverted code still answers 3 on an unknown
flag, so `test_unknown_flag_...[ppa_signoff_records.py]` stays green and only the
`--help` arm moves — which is the whole point of reading the exit code instead
of the exception type.

---

## 3. The by-TEST-ID A/B

`python3 -m pytest test_ppa_layer_exit_contract.py test_ppa_layer_internal_error_is_not_a_finding.py -p no:randomly`

| test ID | before | after |
|---|---|---|
| `test_help_is_not_a_bad_invocation[ppa_signoff_records.py]` | FAILED | **PASSED** |
| `test_unknown_flag_is_bad_invocation_not_undetermined[ppa_agent_context_build.py]` | FAILED | **PASSED** |
| `test_unknown_flag_is_bad_invocation_not_undetermined[ppa_diagnostic_router.py]` | FAILED | **PASSED** |
| `test_vacuous_input_is_undetermined_not_pass[ppa_agent_context_build.py]` | FAILED | FAILED — undeclared |
| `test_vacuous_input_is_undetermined_not_pass[ppa_diagnostic_router.py]` | FAILED | FAILED — undeclared |
| `test_vacuous_input_is_undetermined_not_pass[ppa_pr_scope_check.py]` | FAILED | FAILED — undeclared |
| `test_vacuous_input_is_undetermined_not_pass[ppa_signoff_records.py]` | FAILED | FAILED — undeclared |
| `test_no_ppa_program_lets_a_traceback_reach_the_exit_code[ppa_agent_context_build.py]` | FAILED | FAILED — undeclared |
| `test_no_ppa_program_lets_a_traceback_reach_the_exit_code[ppa_diagnostic_router.py]` | FAILED | FAILED — undeclared |
| `test_no_ppa_program_lets_a_traceback_reach_the_exit_code[ppa_pr_scope_check.py]` | FAILED | FAILED — undeclared |
| `test_no_ppa_program_lets_a_traceback_reach_the_exit_code[ppa_signoff_records.py]` | FAILED | FAILED — undeclared |

Whole PPA suite, 55 files, `test_ppa*.py`, file-count guarded at `>= 50`:

```
before   12 failed, 1523 passed, 17 skipped, 24 xfailed   in 75.61s
after     9 failed, 1526 passed, 17 skipped, 24 xfailed   in 74.06s
```

Exactly three moved. No test that passed before fails now.

The ninth red in both columns is
`test_ppa_runner_extraction_ledger.py::test_no_new_ppa_logic_may_be_added_to_the_runner`
(`_report_wns_tcl` at `phase3_one_shot_runner.py:34044` belongs in
`_ppa/timing.py`). It is red on the unmodified base, it is not one of the
eleven, and this branch does not touch it.

11 tests report `NOT_VERIFIED` in both columns: this host carries jsonschema
3.2.0, which has no `Draft202012Validator`, so the published draft-2020-12
schemas were not applied in either run. That is a skip and not a pass in both
columns alike, so it does not move the A/B.

---

## 4. The denominator question

> *Ask whether the same four defects exist in PPA programs the suite does NOT
> parametrise over, and if the parametrisation has a denominator it should be
> printing.*

### 4.1 Yes, it has one, and it is printing the wrong half of it

```
DISCOVERED by the glob `programs/ppa_*.py`         : 18
DECLARED in the exit-contract vacuous table        : 14
DECLARED in the internal-error traceback table     : 14
the two tables agree on their key set              : True
floor asserted by test_the_program_set_is_not_empty: >= 14  (PASSES at 18)
DECLARED but not discovered (a stale entry)        : none
```

The suite has **two** denominators and guards only one of them. `PPA_PROGRAMS`
is discovered — correctly, and the file says why: *"a fifteenth program added
tomorrow is covered by this file the moment it lands, which is the only way a
LAYER property stays a layer property."* But the *invocations* are declared, in
two hand-maintained tables, and nothing relates the two counts. The result is
that the file's guard for this exact hazard,
`test_the_program_set_is_not_empty`, asserts `len(PPA_PROGRAMS) >= 14` and
**passes at 18 while four of those 18 have no invocation at all** — its own
message still reads *"expected the fourteen shipped ppa_* programs"*, as do both
module docstrings ("Fourteen programs honour it individually", "across the
fourteen shipped `ppa_*` programs"). The floor is a number from a night when
14 and 14 were the same number.

The gap is not silent — the per-program `pytest.fail` is loud, names the program,
and says what to do — so this is a much milder version of the shape than the
defects the suite finds. But it is the same shape, and the brief is right to name
it: **a file whose subject is "a checker that reports on a population it never
established" reports `>= 14` over a population of 18 with 4 holes in it.**

What it should print is the pair, not the floor:

```
assert set(PPA_PROGRAMS) == set(_VACUOUS_ARGV), (
    f"{len(PPA_PROGRAMS)} ppa_* programs discovered, "
    f"{len(_VACUOUS_ARGV)} invocations declared; undeclared: "
    f"{sorted(set(PPA_PROGRAMS) - set(_VACUOUS_ARGV))}")
```

which fails once with the whole list instead of N times with one name each, and
which also catches the opposite drift — an entry left behind for a program that
has been deleted, invisible to a floor forever.

### 4.2 The layer is 24 executables, and the suite reaches 18

`glob("ppa_*.py")` is a *naming* convention standing in for a *layer* boundary.
Six PPA-layer executables are outside it. Three are modules in `_ppa/` that ship
a `main()` and a `__main__` block, and three are programs in `programs/` that
import `_ppa` or cite `PPA_INTERFACES.md` under a different name:

| executable | how it is outside the glob |
|---|---|
| `_ppa/area.py` | `_ppa/` module with a CLI; its own docstring states the four-code contract |
| `_ppa/timing.py` | `_ppa/` module with a CLI |
| `_ppa/backends/openroad.py` | `_ppa/backends/` module with a CLI |
| `power_total_vs_budget_check.py` | imports `_ppa`; not named `ppa_*` |
| `closed_loop_executable_coverage_check.py` | cites `PPA_INTERFACES.md`; not named `ppa_*` |
| `readme_ppa_extractor.py` | cites `PPA_INTERFACES.md`; `ppa` is not the prefix |

I ran all four arms against all six.

**`--help` → 0: all six pass.** Nothing here.

**Unknown flag → 3: two fail, with the defect I just fixed in two of the four.**

| executable | `--this-flag-does-not-exist` | |
|---|---|---|
| `_ppa/area.py` | 3 | ok |
| `_ppa/backends/openroad.py` | 3 | ok |
| `closed_loop_executable_coverage_check.py` | 3 | ok |
| `readme_ppa_extractor.py` | 3 | ok |
| **`_ppa/timing.py`** | **2** | **same defect as `ppa_diagnostic_router.py`** |
| **`power_total_vs_budget_check.py`** | **2** | **same defect as `ppa_agent_context_build.py`** |

Both are a bare `parse_args`, and both take the same one-line fix — the same
`_ppa/cli_exit.parse_or_refuse` — so the answer to the brief's question is:
**yes, and it is the identical defect, not merely the same class.** The suite
would have caught both on the day it landed if its parametrisation were the
layer rather than the prefix.

**Vacuous → 2 with a marker: one fails on the marker.**

| executable | vacuous invocation | rc | marker |
|---|---|---|---|
| `_ppa/area.py` | `--baseline A --candidate A` | 2 | `[CANNOT CHECK]` |
| `_ppa/timing.py` | `D` | 2 | `[CANNOT CHECK]` |
| `_ppa/backends/openroad.py` | `--log A` | 2 | `[CANNOT CHECK]` |
| `readme_ppa_extractor.py` | `--readme A` | 2 | `[CANNOT CHECK]` |
| **`power_total_vs_budget_check.py`** | `D` | 2 | **none** |

`power_total_vs_budget_check.py` refuses honestly in substance — it prints
`INCOMPLETE: total power was NOT compared against anything` and names the
authority it wanted — but `INCOMPLETE:` is not one of the two markers §1 fixes,
and §1 fixes them precisely so that a 2 can never be read as a silent skip by a
reader who is grepping. `test_vacuous_refusal_is_marked` would be red on it.

**Traceback → none, rc in range: all six pass.** No uncaught exception reached
an exit code in any of the six.

### 4.3 Two rc=0 answers I checked and am NOT reporting as defects

Both looked like the vacuous pass on first measurement. Neither is, and the
reason is worth writing down because it is the same reason the declared table
exists.

- **`closed_loop_executable_coverage_check.py`** answers `[PASS]` rc=0 when
  handed an empty directory. Its population is not the directory: it is the flow
  document, and it had read 69 steps and 22 declared closed-loop edges before
  answering. Point `--flow` at an absent or empty file — its *actual* input —
  and it answers 2 `[CANNOT CHECK] the flow document could not be read`. It even
  prints, unprompted, *"zero claims were EXAMINED, which is not the same as zero
  claims being clean."* The 0 was earned; my invocation was wrong. **This is
  exactly the failure the tables prevent** — a vacuous arm invented by whoever
  is running it tests the invoker's guess about the population, not the program.

- **`readme_ppa_extractor.py`** answers rc=0 with `hints=0` over a 0-byte file
  and over a JSON document. Its zero-population guard fires only when the file
  is *unreadable*. Whether a document that was read and yielded nothing should be
  2 is a real question — `ppa_metric_extract.py` decided it should be, and the
  internal-error file's own docstring cites that decision — but this program is
  an extractor of *hints* that override nothing, it prints the digest and the
  byte count so a zero-hint run cannot be mistaken for a run that opened nothing,
  and rc=1 is spent on "a README number contradicts the SDC". I am flagging it as
  **a question for its owner**, not as a defect, because I cannot show it
  publishes a claim it did not earn.

---

## 5. Constraints

- Not pushed to `main`; branch `jrc/ppa-layer-rc-contract` only.
- No plugin version bump; no manifest touched.
- No `--write-baseline`.
- No test file edited.
- English only; no foundry, process node, SKU or chip codename anywhere in the
  change or in this document.
- Every generated file list fed to pytest was guarded by a minimum count
  (`test_ppa*.py`, guard `>= 50`, actual 55) before the run, so neither an empty
  list nor a missing file could read as green.

---

## 6. Handoff: changes in files this branch does not own

Per `PPA_INTERFACES.md` §6 — *"If you need a change in someone else's file, write
it in your RESULT.md and it is applied at landing; do not edit it"* — and per the
brief's instruction not to edit the tests.

### 6.1 `tests/test_ppa_layer_exit_contract.py`, `_vacuous_argv` table — four entries

Closes `test_vacuous_input_is_undetermined_not_pass` for all four. Measured
above: each answers 2 with `[CANNOT CHECK]`.

```python
"ppa_agent_context_build.py":  [a],
"ppa_diagnostic_router.py":    [a],
"ppa_pr_scope_check.py":       ["--changed-file", a],
"ppa_signoff_records.py":      [d],
```

### 6.2 `tests/test_ppa_layer_internal_error_is_not_a_finding.py`, the `argv` table — four entries

Closes `test_no_ppa_program_lets_a_traceback_reach_the_exit_code` for all four.

```python
"ppa_agent_context_build.py":  [j],
"ppa_diagnostic_router.py":    [j],
"ppa_pr_scope_check.py":       ["--changed-file", j, "--catalogue", j],
"ppa_signoff_records.py":      [str(tmp_path)],
```

### 6.2b Proof that 6.1 and 6.2 close all eight

Applied verbatim to a **throwaway copy** of both files under
`programs/.jrc_probe/` (dot-prefixed so pytest never collects it, removed
immediately after; the repo's own test files were not touched and
`git status --porcelain` was empty before and after):

```
# the 8 arms, restricted to the four programs
24 passed, 89 deselected in 1.11s

# both layer files, whole
110 passed, 3 xfailed in 5.52s
```

Zero failures. With the three program fixes on this branch plus these eight
declarations, **all eleven named reds are green** and the three strict
cross-ownership pins still hold. The eight are a declaration and nothing else.

### 6.3 The denominator guard, in both files

Replace the `>= 14` floor with the discovered-vs-declared equality shown in
§4.1, and drop "fourteen" from the two module docstrings and from the guard's
own failure message. Eighteen programs ship today.

### 6.4 The three cross-ownership pins in `test_ppa_layer_exit_contract.py`

`_XFAIL_UNKNOWN_FLAG` / `_XFAIL_HELP` are `xfail(strict=True)` and still hold on
this branch (3 xfailed, 0 xpassed). They are unaffected by this change; noted so
the lander knows they were checked and not merely left alone.

### 6.5 Two out-of-lane programs carrying defects the suite cannot see

Both take the same one-line fix this branch applied to its own three:

```python
from _ppa import cli_exit
args, rc = cli_exit.parse_or_refuse(ap, argv)
if args is None:
    return rc
```

- **`_ppa/timing.py`** (timing lane) — unknown flag exits 2, must be 3.
- **`power_total_vs_budget_check.py`** (power lane) — unknown flag exits 2, must
  be 3; and its vacuous refusal at rc=2 prints `INCOMPLETE:` where §1 requires
  `[CANNOT CHECK]` or `[REFUSE]`.

### 6.6 The parametrisation boundary

Whoever owns the two layer files: the layer is 24 executables and the glob is a
prefix. §4.2 lists the six it misses and which of them are red today. A
prefix-shaped denominator over a layer-shaped property will keep being off by
however many PPA executables get named something else.

### 6.7 A question for the owner of `readme_ppa_extractor.py`

See §4.3. Read-but-empty is rc=0 there and rc=2 in `ppa_metric_extract.py`. One
of the two is the layer's answer; I could not establish which from the code.
