# `retired/` — run output that is NOT a published result

Everything under this directory was moved here from the **IC level** of this
cell (`benchmark-data/ic/<IC>/`), where the published layout contract admits
only two kinds of entry: `input/`, and one `v<major>.<minor>.<patch>_<PDK>/`
folder per converged (version x PDK) cell. Nothing here is deleted — deleting a
run would make "we never ran this" and "we ran it, it failed, and we kept the
record" the same state, which is the one thing `benchmark-data/ic/` exists to
keep apart (see `benchmark-data/ic/INDEX.md`).

**Nothing under `retired/` may be cited as a result.** Not as a pass, not as a
converged cell, not as the evidence behind a number. It is a record of what a
run produced, kept where a reader can still find it, and nothing more.

## What was moved, and what was wrong with where it was

### `clean_run_v1422_20260715/`

A run folder under the `clean_run_*` prefix. `.gitignore` ignores that whole
prefix under `benchmark-data/ic/*/` and re-admits only two files from it
(`.gitignore`, `RESULT.md`), so a folder published under that name presents as
a complete record while its phase output is filtered on the way in. That is the
exact failure mode the naming rule exists to prevent: the folder looks like
evidence and is not the thing it looks like. Retained because issue repro
commands name this path verbatim; retained as a *record*, not as a result.

### `ic_level_run/` (`phase1/`, `phase3/`, `reports/`)

Run output that landed at the IC level instead of inside a versioned cell. At
the IC level it is attributable to **no plugin version and no PDK** — the two
facts a published cell's folder name exists to state — so no reader can say
which build produced it or which process it targets. Moved intact, under one
directory so its internal relative paths (`phase1/generated_docs/...`,
`phase3/analog/...`, `reports/orchestrator/...`) still resolve to each other.

## What is still published for this IC

`input/` (the shared design input) and the versioned cell(s) beside it. Those
are the only entries at the IC level, which is what the contract says.
