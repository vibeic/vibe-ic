# Package invariants — the rule lives next to the code it binds

## The gap this closes

Measured 2026-08-19 against the deepseek-harness tree at `99f6f02fe`, counted in
a clone rather than read off a summary: **54 top-level packages, 226 leaf
packages, 219 `invariant.ts` files** — one per package, sitting next to the code.

Our standing verdict against that tree has two halves:

- **Ahead on enforcement.** Our gates block landing, and they are adversarially
  tested; a rule here is not advice.
- **Behind on locality.** Every rule we enforce lives centrally. A contributor
  editing `commands/` or `ip-catalog/` cannot see the rule that binds what they
  are editing without going somewhere else to look for it, and mostly does not.

`package_invariants_check.py` closes the locality half without giving up the
enforcement half.

> Five files in this repo already match the word `invariant`
> (`cross_constant_invariant_check.py`, `fsm_error_invariant.py`, and three
> tests). Those are unrelated single checks about invariants **inside a chip**.
> They are not this pattern and must not be counted as adoption of it.

## What a package declares

One `INVARIANTS.json` at the package root. Each entry carries the rule twice —
once for the human, once for the machine — because a statement with no rule is
decoration and a rule with no statement is unreadable:

| field | for | meaning |
|---|---|---|
| `id` | both | stable handle; the gate quotes it when it fails |
| `statement` | human | the rule, one sentence |
| `why` | human | what went wrong, or would go wrong, without it |
| `rule` | machine | one of four kinds (below) |
| `counterexample` | machine | a file the rule **must** reject; a list when the rule has more than one clause, one entry per clause, each with a `proves` note |

Rule kinds, deliberately four — a rule language is a maintenance surface:

- `forbid_regex` — no file matching `include` may contain `regex`
- `require_regex` — every file matching `include` must contain `regex`
- `require_companion` — every entry matching `for_each` must have the file named
  by `companion`
- `forbid_path` — no entry may match `glob`

In globs `*` and `?` do not cross `/`; `**` does.

## Who reads it

1. **The gate**, on every landing run, through
   `programs/tests/test_package_invariants_check.py`. The declared rules are
   evaluated against the package's own files.
2. **The gate again, differently.** Every counterexample a rule declares is
   evaluated in isolation and must be rejected by that rule. A rule that cannot
   reject one of its own counterexamples is reported `NON_DISCRIMINATING` and
   fails. This is what stops a per-package file from decaying into per-package
   decoration, which is the single biggest risk of moving rules out of the
   centre.

   A rule with more than one clause declares one counterexample per clause. A
   single counterexample against a two-clause rule shows only that one clause
   discriminates, and the other half is then a claim nobody has tested — which
   is how a rule ends up saying more than it checks.
3. **The contributor, at the moment it matters.**
   `tools/ci/pre_commit_check.sh` calls `--touched` on the staged file list and
   prints back the invariants binding every package the commit changes.

## What fails, and when

| code | when |
|---|---|
| `VIOLATION` | a package file breaks a rule its own package declares |
| `NON_DISCRIMINATING` | a rule did not reject its own counterexample |
| `MISSING_FILE` | an enrolled package exists with no `INVARIANTS.json` |
| `EMPTY` | the file exists and declares zero invariants |
| `UNENROLLED` | an `INVARIANTS.json` sits in a package nobody enrolled |
| `STALE_ENROLLMENT` | an enrolled path is no longer a directory |
| `ZERO_ENROLLMENT` | the enrollment names no package, so a PASS would be a PASS over nothing |
| `VACUOUS_RULE` | a rule selected zero of its own package's files, so it held over nothing |
| `SCHEMA` | the document is malformed, or a rule is not evaluable |

`ZERO_ENROLLMENT` and `VACUOUS_RULE` are the two ways this gate could report a
confident PASS over nothing, and both are answered rather than assumed away. An
emptied enrollment makes every loop body below it unreachable; a rule whose glob
no longer matches anything in its package goes on passing forever while binding
an empty set. `forbid_path` is the one kind exempt from the second check, because
for that kind an empty selection is the rule being obeyed.

`MISSING_FILE` and `EMPTY` carry the weight of the whole design. Deleting a
package's invariant file, or emptying it, must **never** read as "this package
has no constraints" — that is precisely the failure mode locality would
otherwise introduce, so both are hard failures.

## Enrollment, and why it is not derived

`programs/package_invariants_enrolled.json` names the enrolled packages.

Enrollment cannot be derived from "has an `INVARIANTS.json`", because then
deleting the file would delete the obligation and the gate would go green on the
exact act it exists to catch. So enrollment is a **separate memory**: the file is
required *because the package is enrolled*, not because the file is there.

Getting a package out of the gate therefore takes three edits in three files:
delete `INVARIANTS.json`, remove the enrollment entry, and lower
`_ENROLLMENT_FLOOR` in `programs/tests/test_package_invariants_check.py`. All
three are visible in a diff. There is no single silent one.

## Adding a package

1. Write `INVARIANTS.json` at the package root. Every rule needs a
   `counterexample` that genuinely violates it — the gate checks this, so a
   placeholder will not land. If the rule has more than one clause, give it one
   counterexample per clause.
2. Add the package path to `programs/package_invariants_enrolled.json`.
3. Raise `_ENROLLMENT_FLOOR` in
   `programs/tests/test_package_invariants_check.py`.
4. Run `python3 programs/package_invariants_check.py`. It must print `PASS` and
   name the new count.

Declare rules that are **true today**. A rule that is aspirational lands the tree
red, and a rule narrowed with exclusions until it passes is a rule that checks
less — which is worse than not having written it.
