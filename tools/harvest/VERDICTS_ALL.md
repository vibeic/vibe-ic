# `verdicts_all.tsv` — the consumable that contains every decided row

`verdicts_joined.tsv` is scoped to the 355-row roster. My 1084 extra rows cover worktrees found on
8HD-9 and 8HD-7 that the roster never listed, and a gate has been reporting them as invisible:

    FAIL: 1083 decided rows are invisible to whatever reads verdicts_joined.tsv

Merging them *into* `verdicts_joined.tsv` would silently change that file's meaning from "the roster"
to "everything", in a file three agents write. So this is a **union**, and `verdicts_joined.tsv` is
left byte-untouched.

| | rows |
|---|---|
| from `verdicts_joined.tsv` | 355 |
| from `verdicts_extras_joined.tsv` | 1084 |
| **total** | **1439** |
| RECOVER / LANDED / ABANDON | 1226 / 184 / 29 |

Each row carries a `source` column naming which input it came from, so the union is reversible.

## Conflicts are surfaced, never resolved

Rows are keyed by `(host, path)`. Where a key appears in both inputs with different verdicts, **both
rows are emitted with `source=CONFLICT`**. Picking a winner would bury the one thing worth seeing,
and precedence between two agents' measurements is not mine to invent.

**The real data produces 0 conflicts — because the key overlap is 0.** That is a property of the
inputs, not evidence that the detector works, and the two are indistinguishable in the output. The
branch is therefore proven by control: injecting one row that re-asserts a real `verdicts_joined`
key with the opposite verdict yields exactly two rows marked CONFLICT, both retained.

## One path in both, and it is not a conflict

`/home/reyerchu/_batch42` appears under host 112 (joined) and host 102 (extras). Both say RECOVER and
both cite `benchmark-data/ic/INDEX.md` at `ef98fd8a58995747`. Checked directly: the worktree exists
on **both** machines with that identical content. Two copies, two correct rows, no dispute — which
is why the key is `(host, path)` and not `path`.

A first check reported it absent from .112 and I was one step from writing "worktrees are being
deleted during this session". That reading came from a nested-quoting `ssh` construct that had
already produced empty output once today. **Absence is the reading that raises the alarm, so it is
the one that must be re-measured with a script file rather than nested quotes.** All 27 worktrees I
swept on .112 are still present; nothing is being deleted.
