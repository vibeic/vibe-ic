# Every number in this branch, re-measured on a clean tree

The brief's measurement protocol is `git clean -xdfq` +
`PYTHONDONTWRITEBYTECODE=1`. Earlier runs used a fresh worktree and cleared
`__pycache__` per arm, which is nearly that but not literally it. This closes
the gap, so no green here rests on a stray artefact.

    $ git status --porcelain          # everything of mine already committed
    (empty)
    $ git clean -xdfq
    $ git status --porcelain
    (empty)

## Base

    my base   a4caccefe (v1.11.69)
    main now  a4caccefe
    commits landed since I branched: 0

Main has NOT moved under this branch, so there is no merged-tree divergence to
check and the numbers below are against the same tree a lander would see. This
was re-fetched rather than assumed — a cached ref that has gone stale is how a
branch gets measured against a main that no longer exists.

## Greens, on the clean tree

    upstream_contract_parity_check.py                          rc 0
      pad_ring.upstream_pad_variables: upstream_names=20,
        implemented=9, declared_unperformed=3,
        omitted_by_design=8, known_gap=0
      pad_ring.along_the_row_extent:   anchors=2, pin=known_gap

    pytest (parity + routing-consistency + emit + pad_ring)    188 passed,
                                                               8 skipped, rc 0
      [PASS] suite_write_guard: this pytest session wrote nothing
             `git status --porcelain` would show.

    plugin_full_audit.py    D1 program-test-coverage: PASS (1241 programs)
                            D2 step-compliance-checker: PASS
                            => deterministic audit PASS

## The load-bearing red, on the clean tree

M1 — revert `_mentions` to the old bare-quoted-literal predicate:

    MUTATION APPLIED
    FAIL: 1 unaccounted name(s) across 2 registered re-implementation(s):
      - PAD_FAKE_SITES is classified implemented and does not appear in
        programs/_pad_ring.py. The register claims an implementation the
        module does not contain.
    MUTATED_RC=1

    restored -> RESTORED_RC=0, git status --porcelain clean

The mutation prints `MUTATION APPLIED` from an `assert` on its own anchor
string, because the M2 arm of the earlier sweep silently failed to apply and
the pytest run that followed reported 22 passed — a green that proved nothing.
A mutation that cannot say it applied is not a mutation.

## The one figure NOT re-measured, and why

`pad_ring.along_the_row_extent` stays `pin=known_gap`. No test on main pins our
along-the-row extent against upstream's `pad_cfg.tcl`, and this branch does not
add one, so the honest status is unchanged. Registering it as `test` without
writing the test would be the exact move the register exists to make
impossible.
