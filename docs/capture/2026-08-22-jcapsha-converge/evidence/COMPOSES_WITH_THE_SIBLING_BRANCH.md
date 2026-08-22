# This branch and `jpadsite/pad-site` conflict, and here is the resolution, tested

A lander will want both: this branch carries the parity register and the
general guard; `origin/jpadsite/pad-site` carries the NORTH and CORNER
orientation fixes that I independently confirmed are live on main. They touch
the same three files.

**MEASURED, not assumed** — merged in a scratch worktree, not pushed:

    git merge origin/jcapsha/converge-capture-distill   (onto 725f9352f)
    CONFLICT (content): programs/_pad_ring.py
    CONFLICT (content): programs/pad_ring_gen.py
    CONFLICT (content): programs/tests/test_pad_ring.py

Six hunks. Every one of them is **two authors writing the same correction in
different words** — the retraction of the inertness claim, arrived at
independently on both branches.

## The resolution, per file, on the merits

I read every hunk before choosing. Taking one whole side blind is a silent
revert; that is not what happened here.

**`_pad_ring.py` -> take THEIRS.** They renamed `VERTICAL_SIDE_ORIENT` to
`SIDE_ORIENT` and ADDED the `"S"` and `"N"` entries — that is the NORTH fix,
real code. Mine only re-words the comment above the same table. Theirs is a
strict superset of the change; keeping mine would have thrown away a fix to
preserve a paragraph.

**`pad_ring_gen.py` -> take THEIRS.** Both rename the constant and the schema
key to exactly the same names; theirs additionally drives all four sides from
`SIDE_ORIENT`. The prose differs and says the same thing.

**`tests/test_pad_ring.py` -> KEEP BOTH.** Theirs adds the tests for the NORTH
and CORNER fixes; mine adds the general identifier guard and the report-key
test. Neither is a rewording of the other and choosing between them would drop
real coverage. Grafted, not chosen: 92 test functions in the merged file.

## The merged tree, run

    pytest (pad_ring + parity + both pins + routing + emit)
        197 passed, 16 skipped, rc 0
        [PASS] suite_write_guard: wrote nothing

    upstream_contract_parity_check.py
        PASS: 3 registered re-implementation(s)   rc 0

**And the load-bearing one:**

    pytest -k "asserts_inertness or refuted_premise"   ->  2 passed

My general guard passes on THEIR fix, in the merged tree. That is the third
confirmation that it enforces the rule and not my edit — the first was
running it against their file directly, the second was that it still refuses
main, and this is it surviving a real merge of the two.

## What a lander should do

Take `jpadsite/pad-site` as the vehicle for the pad-ring source changes — it is
six commits, it fixes NORTH and two CORNERS with an A/B, and my rename
duplicates one of its commits (`c56b8e1b1`) without adding to it. Take this
branch for the parity register, the two upstream pins, the routing entry, the
capture, and the general guard. The conflict above resolves in one pass and the
result is green.
